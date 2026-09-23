"""The character record the school server hands back after a character is made.

Two messages describe the same person and neither layout was guessed: both were
read off the client's own code.

``MsgClRequestCharacterCreate`` (0x030C) is what the client sends. Its reader,
Input_MsgClRequestCharacterCreate::deserialize (0x8F89F0), takes 74 bytes; the
dump function beside it (0x8F7880) names every one of them, so the parse below
is exact rather than inferred from byte diffs.

``MsgSvResultCharacterListFromAccount`` (0x0319) is the answer to
``MsgClQueryCharacterListFromAccount`` (0x0318), and its reader is 0x8F9620:
``u16 count`` and then that many entries of **238 bytes**. The names come from
the dump at 0x8FA2B0, whose field order matches the reader's call order one for
one — including the three fixed-width strings of 11 bytes (family/first/nick),
the two of 21 (friendGroupName, catchCopy) and the two 16-byte club arrays.

Widths come from mtNetStreamInputBuffer's vtable (0xC0B8B0): +0x20 reads a u64,
+0x24 a u32, +0x28 a u16, +0x2C a u8, and the helper at 0xA49610 copies a fixed
byte count straight out of the stream (its third push is that count). Everything
is big-endian, and the wire form is packed: the 0xF0 that the size helper
(0x8F7F60) multiplies by is the in-memory stride, two bytes wider than what the
reader actually consumes.
"""

from __future__ import annotations

import json
import os
import random
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import ability
import career
import catchcopy
import club
import curriculum
import dramarecord
import facing
import item
import options
import posts
import romance

if TYPE_CHECKING:
    # Only for the annotation on CharacterStore. charaids imports this module for
    # CHARA_ID_BASE, so importing it back at runtime would be a cycle.
    import charaids

NAME_LEN = 11  # tmn::MAX_CHARA_* + 1, i.e. five double-byte characters
GROUP_NAME_LEN = 21  # tmn::MAX_GROUP_NAME + 1, also tmn::MAX_CHARA_CATCHCOPY + 1
NUM_OF_CLUB = 16
NUM_OF_CHARA_ABILITY = 6

LOOKS = (
    "forelock",
    "backHair",
    "hairColor",
    "outline",
    "skinColor",
    "eyes",
    "pupilColor",
    "eyebrows",
    "mouth",
)
ACCESSORY = (
    "uniform",
    "tie",
    "hairAccessory",
    "faceAccessory",
    "bodyAccessory",
    "reserve1",
    "reserve2",
)

ENTRY_SIZE = 238

# Where a character stands when the account has no saved position. Zero is not a
# usable answer: reference/idlist/map.txt record 0 has an empty name and 0xFFFF
# sentinels in its tail, i.e. it is the table's "no map" entry, and posInfo is the
# only place the client is ever told which map it is on. Map 1 is 屋外, the school
# grounds, which is the one map that always exists.
SPAWN_MAP_ID = 1

# posX/posY are isometric cell indices, not pixels, and 屋外 runs about 0..190 on
# each axis. Three independent measurements agree that one step moves a sprite by
# a 1.483:1 screen offset — the world view (probe characters four units away
# landed 179.7 px across and 121 px down), the minimap ruler, and the tile cursor
# itself — and the school's artwork in mmt_010100.png is a diamond of exactly
# 903 x 609 px, ratio 1.483. The diamond is not inscribed in the 9600 x 7232
# rectangle; it has margins, and its own proportions are the tile's.
#
# Fitting that gives, in rectangle pixels:
#
#     rect_x = 4650 + (posX - posY) * 23.74     posX runs down-right
#     rect_y =  370 + (posX + posY) * 16        posY runs down-left
#
# Which ex_map_object confirms, and not weakly. Run its 屋外 decorations through
# it and 門松１, 案山子１ and 雪だるま all land on cell (100, 84) while 門松２,
# 案山子２ and 雪だるまバケツ帽子 all land on (112, 84) — three seasons sharing two
# fixed decoration slots. Better still, ランタン１-４ come out at posX 162.0, 162.1,
# 162.2, 162.3 with posY stepping by 11 each time, and ランタン５-６ at one posY with
# posX stepping by 11.2: a row of lanterns lying exactly along a coordinate axis,
# which a wrong transform does not produce.
#
# It also explains the older note about (0, 0) leaving the character "in the
# treetops": (0, 0) is the diamond's top corner, and the top of the school map is
# forest.
#
# The pixel figures below stay because they are what the fit is built out of.
#
# posX/posY are map pixels, and the map's own size says how many there are.
# Every map ships a bin_<id>.arc holding bge_<id>.bin, whose header is the magic
# "BGE0" followed by two u32: the map's width and height. 屋外 is 9600 x 7232;
# 食堂 is 3200 x 1856; a classroom is 1600 x 1216.
#
# reference/idlist/ex_map_object.txt gives coordinates in that same space. Each
# 24-byte tail is ``u16 ? | u16 mapId | u16 posX | u16 posY | u16 w | u16 h |
# u8 hasCollision | i16 dx | i16 dy | u16 w | u16 h | u16 modelId``, and every
# one of the 79 seasonal decorations lands inside its own map's BGE0 box — all
# 37 of them in 食堂 inside 3200 x 1856, which is not something a wrong field
# split does by accident. So these are real, in-world positions.
#
# What they are *not* is proof of walkability: an object sits where it sits.
#
# 門松 are the pines that flank an entrance, and 案山子 and 雪だるま reuse the same
# two slots, so cells (100, 84) and (112, 84) are a decoration pair with the way
# in between them. Standing in the middle of that gap is the best first guess at
# ground a character is allowed to be on.
SPAWN_POS = (106, 84)

# ⭐⭐⭐ 初登校: where a character stands the very first time [登校] is pressed.
# RESTORED from the tutorial's own last scene, not from a table of positions --
# there is no such table.
#
# The manual (`manual/p02_06`) says 初登校 plays the tutorial and then enters
# マップモード, and that every later 登校 puts the character back where it logged
# out. So the only 登校 this server has to answer for itself is the first one,
# and the honest answer is wherever the tutorial leaves the player.
#
# Where that is comes from reading `amm_e001`/`skr_e001` in the order they
# *run*, not the order their blocks sit in the file. The long tutorial's main
# routine (ip=493) calls its scenes as subroutines: … → 0x14 → 0x15 (the walk
# to your own classroom, label 21) → 0x1a → 0x22 → 0x23 → 0x4c → 0x4d → 0x4e →
# 0x5a → 0x5c → 0x0a → 0x0c → OP_END. The classroom walk is the middle of the
# tour, and it ends in a SCREEN_BLACK_OUT with the map switched off; nothing
# after it puts anybody on a map again. What comes after is portraits over
# backgrounds, and the very last EVENT_BG_LOAD of the script (ip=15769) is bg 8
# 「廊下（昼）」, loaded right after bg 57 「理事長室（昼）」 -- the player has just
# stepped out of the 理事長室 into the corridor when the event ends. (Round 192
# read the classroom walk as the ending because label 21 is the second-to-last
# block in the file; a β1 tester's diary line about 自分の教室前 describes where
# the *crowd* was after wandering around, not where the tutorial put them.)
#
# So the standing cell is the one the 理事長室's corridor door delivers into,
# and that is a row of the game's own door table: map 45 door 3/4 → map 43
# (5,25)/(6,25). Read from mapgraph at import, with the same cell as a fallback
# for a build that has no graph.
#
# ⚠️ INVENTED, and it is one decision rather than a number: that a character
# who has not had its 初登校 yet is placed at the *end* of the tutorial rather
# than where it starts (map 43 (5,27), a few cells away). Nothing says what the
# original sent in the 0x480F that precedes the tutorial. Placing them at the
# end is what makes the two versions agree: the long one ends there, and the
# short one -- 「ひとりで行ける」, which never touches a map at all (2.143 五) --
# leaves the player wherever this server put them.

#: ⚠️ INVENTED — the one 組 this server's school opens, and so the 組 every
#: character here is in (0 = Ａ組).
#:
#: A policy, not a measurement. The original decided a 組 automatically at
#: registration, and the player could neither pick one nor ask to be put with a
#: friend -- `p03_04` says 「登録すると、「期生」・「クラス」が自動的に決定され」 and
#: no source anywhere states the rule it decided by.
#: Two things about it are settled even so, and both are negative: the 組 was
#: not keyed on 期生 (players six cohorts apart shared one) and classes were not
#: filled one at a time (every letter Ａ..Ｚ was in use), which leaves balancing
#: by headcount as the likeliest rule -- a school held 5000 by the top bucket of
#: `student_num_scale.bin`, so roughly 192 to a 組.
#:
#: ⭐ None of which this server can usefully copy. 授業 and 試験 happen in the
#: classroom of your own 組, so spreading a handful of players over 26 rooms
#: would mean nobody is ever in class with anybody. One open 組 is the choice;
#: turning this knob moves everyone to a different one (5 = Ｆ組) rather than
#: spreading them out.
#:
#: ⚠️ Deliberately not per-character: a 組 that differs between characters
#: needs a school-wide roster to balance against, plus a slot in the record to
#: keep it fixed afterwards (登録内容は変更できません), and neither exists yet. The
#: wire has carried this same value all along -- `MsgSvResultScoreCard`,
#: `0x0319`, `0x6501` -- and `_Session.in_class` now starts from it rather than
#: from a literal, so the room a lesson happens in cannot drift away from the
#: 組 the screen prints. The tutorial reads it too, to pick which classroom
#: door its mid-tour walk goes to.
IN_CLASS = 0

#: ⚠️ INVENTED — how a newly registered character's 組 is picked:
#: "fixed" (every character gets IN_CLASS), "balanced" (whichever of the 26 has
#: the fewest), or "random".
#:
#: ⭐ The rule the original used is not recoverable, and this is the knob that
#: admits it rather than hiding one choice inside a literal. "fixed" is the
#: default because of who plays here, not because of what the original did: 授業
#: and 試験 happen in the classroom of your own 組, so on a server with a handful
#: of players 26 open rooms means nobody is ever in class with anybody. "balanced"
#: is the likeliest reconstruction of the original -- a 組 was decided at
#: registration with no say from the player, cohorts mixed inside one, every
#: letter was in use, and classes were the unit official events scored (試験 の
#: クラス平均点, and the 2006-11-08 server merge moved whole ones 「バランスよく」)
#: -- but likeliest is not measured, and "random" is the other candidate that
#: the same evidence cannot rule out.
#:
#: ⚠️ A character's 組 is written into its record when it is created and never
#: read from this knob again: 登録内容は変更できません, and a 組 that moved when an
#: operator turned a knob would take the player's classroom, their 名刺 line and
#: their lesson attendance with it. Turning this decides where the NEXT
#: character enrols. Records written before the key existed read as IN_CLASS,
#: which is what they have always been sent as.
CLASS_ASSIGNMENT = os.environ.get("TMO_CLASS_ASSIGNMENT") or "fixed"

#: The 組 a character lands in under CLASS_ASSIGNMENT, given how many are in
#: each. Pure, so the policy can be read (and tested) without a store on disk.
def pick_class(counts: "dict[int, int]") -> int:
    rooms = len(curriculum.CLASSROOM)
    mode = CLASS_ASSIGNMENT
    if mode == "balanced":
        # Ties go to the lowest 組, so an empty school fills Ａ組 first and the
        # answer does not depend on dict order.
        return min(range(rooms), key=lambda room: (counts.get(room, 0), room))
    if mode == "random":
        return random.randrange(rooms)
    if mode != "fixed":
        print(f"[characters] CLASS_ASSIGNMENT={mode!r} is not one of "
              f"fixed/balanced/random; enrolling in {IN_CLASS} instead")
    return IN_CLASS

#: ⚠️ INVENTED — the 期生 every character created on this server is (2 = 2期生).
#:
#: The rule behind it is not invented -- `p03_04`: 「1期生・2期生などの「期生」は、
#: キャラクターの作成時期に応じて自動的に決定されます」, with βテスト期間中
#: characters 1期生 and 正式サービス開始後 ones 2期生 or later -- but which of those this server stands in for is a choice,
#: and the client it serves is what settles it: a pressed retail disc (its
#: `update.ini` says VERSION=2006012300) could only be registered once the
#: service was open, and that is 2期生.
#:
#: ⭐ It is a label and nothing else. Eight text templates print it -- 経歴's
#: 「%1%期生として入学」, the first line of the right-click name card, the
#: character-select screen, the 立候補者情報 of an election -- and no rule in the
#: manual, in 運営方針 or on this wire takes it as an input.
PERIOD = 2

PRINCIPAL_ROOM = 45           # 特殊教室校舎１Ｆ理事長室
SPECIAL_BUILDING_1F = 43      # 特殊教室校舎１Ｆ, the corridor outside it
#: The step out of that door goes +Y, which the client draws as down-and-left
#: (facing's own measurement), and the tutorial itself pairs a +Y neighbour
#: with dir 6 three times over. The door table happens to say 6 for this door
#: too, but that number lives in the map file's own namespace (see
#: mapgraph.landing) and is not what this is read from.
DEBUT_FACING = facing.DOWN | facing.LEFT


def _corridor_outside_principal_room() -> tuple[int, int, int]:
    """``(mapId, posX, posY)`` the 理事長室's corridor door delivers into."""
    import mapgraph  # local: mapgraph imports nothing from here, but keep it lazy
    for _, _, _, (dest_map, dest_x, dest_y, _) in mapgraph.exits(PRINCIPAL_ROOM):
        if dest_map == SPECIAL_BUILDING_1F:
            return dest_map, dest_x, dest_y
    return SPECIAL_BUILDING_1F, 5, 25


DEBUT_CELL = _corridor_outside_principal_room()


def debut_cell() -> tuple[int, int, int]:
    """``(mapId, posX, posY)`` for a character who has never been to school."""
    return DEBUT_CELL


#: twoshot_place key of 並木道, as 屋外's own cells say: every cell of every
#: collision file carries the key of the place it belongs to. See mapgraph.region.
TREE_LINED_WALK = 1

#: Facing up the avenue, towards the fountain and the building beyond -- the
#: direction the opening background is painted from. That step is -Y, the
#: opposite of the door step DEBUT_FACING reads, and the client draws it as
#: up-and-right (the tutorial's own walk ends on dir 9, going the same way).
DEBUT_FACING_ALONE = facing.UP | facing.RIGHT

# ⭐⭐⭐ 初登校, the other ending. The cell above is where the event leaves the
# player, and the event is not compulsory: it opens by asking whether to go and
# find somebody to ask, and 「聞かなくてもだいじょうぶ！」 takes a road that calls
# two subroutines -- the six キーワード and the close-down -- and stops, at the
# first of the two OP_END both halves of the pair have. Nothing of the event
# plays on it and nothing moves the player, so the honest answer for it is not
# where the event ends but where it began, and the script says where that is:
# the first thing it loads, before the opening waist-up goes up, is the
# background of 噴水の並木道 -- the brick avenue that runs from the 正門 up to
# the fountain, with the main building behind it.
#
# ⛔️ Not 「the road that walks nobody」, which is a different and larger set:
# saying 「案内にはおよばない」 half way through skips the tour of the school and
# still plays every scene after it, and those end outside the 理事長室 like the
# guided road does. Only the road that plays nothing at all lands here.
#
# Which cells those are is the map's own answer rather than a reading of the
# painting: every cell of 屋外 carries the key of the place it belongs to, and
# the 並木道's cells are a 12-wide strip running north from the gate plaza,
# parted in the middle by the fountain. The player has just walked in through
# the 正門, so the cell is the southern end of that strip, mid-avenue.
#
# ⚠️ INVENTED, the same one decision the cell above is and no more: *which* end
# of the avenue a character whose event played none of itself stands at. The
# strip, the map and the facing are all read.


def _foot_of_the_tree_lined_walk() -> tuple[int, int, int]:
    """``(mapId, posX, posY)``: the 正門 end of 屋外's 並木道, mid-avenue."""
    import mapgraph  # local: mapgraph imports nothing from here, but keep it lazy
    extent = mapgraph.size(SPAWN_MAP_ID)
    if extent is None:
        return SPAWN_MAP_ID, 125, 137
    width, height = extent
    walk = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if mapgraph.region(SPAWN_MAP_ID, (x, y)) == TREE_LINED_WALK
        and mapgraph.walkable(SPAWN_MAP_ID, (x, y))
    ]
    if not walk:
        return SPAWN_MAP_ID, 125, 137
    # Furthest from the fountain is furthest from the building, which on this
    # map is +Y: the gate plaza is the bottom edge of the artwork.
    gate_end = max(y for _, y in walk)
    across = sorted(x for x, y in walk if y == gate_end)
    return SPAWN_MAP_ID, across[(len(across) - 1) // 2], gate_end


DEBUT_CELL_ALONE = _foot_of_the_tree_lined_walk()


def debut_cell_alone() -> tuple[int, int, int]:
    """``(mapId, posX, posY)`` for a debut whose event played none of itself."""
    return DEBUT_CELL_ALONE


# Standing the player on ex_map_object's numbers put it on flat blue with no
# scenery at all, and the client never emitted a move for any click — it only
# turned to face one. Blue is the map's out-of-bounds colour: 屋外's artwork is a
# diamond inscribed in the 9600 x 7232 rectangle, so the four corner triangles
# are empty water, which is exactly what the screen showed. Had (5170, 3413)
# been in rectangle pixels it would have landed on the central lawn, in plain
# sight of the fountain. It did not, so the wire's posX/posY are *not* the same
# units ex_map_object stores its sprite placements in — the playable range is
# smaller, and the size of one unit is still unknown.
#
# So no lobby probes this round. Guessing one scale at a time costs a full
# login per guess, and there is a cheaper instrument: the minimap.
# The minimap ruler proved the axes are the two isometric diagonals and that its
# dots do get drawn even out of bounds, but it only gives minimap pixels per
# unit, and nothing says what the minimap's own scale is. The world view does not
# have that problem: it is a 1:1 2D isometric render, so a screen pixel there is
# a map pixel, and the map's size in pixels is known exactly (9600 x 7232 from
# BGE0). Put characters at known offsets from the player and the screen distance
# between them converts units to map pixels directly.
#
# Offsets step by 8 rather than 2 so the set spans 4 to 2048 in only four rungs.
# A wide spread beats a fine one here because a single visible probe is already
# enough — its offset is known, so its distance from the player gives the scale
# on its own; the others only need to bracket it.
# Extra characters dropped into the lobby at chosen coordinates. This is how the
# scale got measured — eight of them at offsets 4, 32, 256 and 2048 from the
# player, of which the two nearest shared the screen and gave 4 units = 179.7
# screen pixels — and it stays wired up because it costs nothing: the client
# draws them straight from the 74-byte record and does not even ask
# MsgClQueryCharaInfo about them.
#
# Empty in normal use; fill it to put markers on the map again.
PROBE_POSITIONS: tuple[tuple[str, int, int], ...] = ()
# ⭐ Where real charaIds start, and it is the client's rule rather than ours.
#
# 0x00404FF9 is a predicate the binary applies to ids in 38 places, built out of
# two range checks (0x00404FDF and 0x00404FBB). It answers zero — "this is an
# ordinary character" — only for
#
#     0x000F0000 … 0x000FFFFF     and     0x01000000 … 0xFFFFFFFE
#
# and for everything else it answers nonzero, meaning "resolve this through the
# NPC subsystem". The lesson scene has no NPC subsystem, so a seatInfo carrying
# a small charaId sent it into a branch that dereferences a global nothing ever
# fills (0xE361A4), and the client died on a read of 0x000000A0.
#
# Rounds 1–43 used charaId 1 and nothing complained, because the lobby, chat,
# warping and the 通知表 never ask the question. 授業 does, and the other 37 call
# sites are still unexplored — so this is not a workaround for one screen, it is
# the id space the client was built for.
#
# Measured: the same lesson that killed the client with charaId 1 ran through
# with 0x01000001, drew the chibi at its desk and the panel above it.
CHARA_ID_BASE = 0x0100_0000

PROBE_ID_BASE = 9000  # charaIds for the probes, kept clear of real characters
# Where the stand-ins stop. Was open-ended when real ids were 1, 2, 3…; now that
# they start at CHARA_ID_BASE an unbounded test would call every real character a
# marker, so it is bounded here rather than left as a trap.
PROBE_ID_LIMIT = 10000

# Stand a marker on every doorway of whatever map the player is on: scaffolding,
# now taken down. It was put up to answer two questions and both are answered.
#
# Whether the doorway table read out of the collision files was right — 屋外's 72
# markers and 食堂's 2 all came up in the doorways, and warps in both directions
# matched the table. And where the ground was: a doorway cell was the only kind
# of cell known to be stand-on-able, because the player has to step on one to
# warp. mapgraph.walkable() now answers that for every cell of every map, so the
# markers are not holding the only copy of anything any more.
#
# Off means the campus is empty except for the player, which is what it should
# look like. Turning it back on is one word, for the next time a batch of
# stand-ins is the cheapest way to ask the client something.
MARK_DOORS = False

# Who confessed to this character, in the 238-byte character-list entry's
# capturedNpcId. 0xFFFF is this game's "nothing here" sentinel and it is not a
# guess about this field in particular: the create block the client itself sends
# ends in ten 0xFF bytes for the accessory slots it is not using, and
# reference/idlist/map.txt's record 0 -- the table's "no map" row -- pads its
# tail the same way.
#
# Capture-NPC ids, meanwhile, start at 0, so 0 is a real person and not an
# absence. That was read out of capture_npc.bin rather than assumed, and it took
# reparsing the table: header offset 0x0c says this table's key is 4 bytes, not
# the 2 the dumper used to assume, so reference/idlist/capture_npc.txt used to
# show id=1 ten times over with every name blank. Read four bytes and the ten
# records come out as 0x00000001, 0x00010001 ... 0x00090001 -- the
# ``npcId{categoryId, id}`` pair MsgSvNotifyNpcControl carries, little-endian, so
# categoryId 1 (capture) and id 0..9 -- against 天宮小百合, 春日つかさ, 弥生水奈
# and the rest of the heroines. The dumper was fixed on 2026-08-02 and the table
# now reads `1:0 天宮小百合`.
#
# Which matters because 再入学 is only meant to be available to a character who
# has been confessed to (manual/p02_06, manual/p09_02) and the button came up
# enabled while the server was sending 0 here. Sending the sentinel instead is
# the claim "nobody has confessed", which for this server is simply true: there
# is no romance system, so no capture can ever have happened.
#
# Measured, not reasoned: three notebooks went up at once, differing only in the
# field under test, and the user read the 再入学する button off each. 0xFFFF grey,
# 0 lit, and 0xFFFF with coupleFlag=1 grey as well. So capturedNpcId alone drives
# it and coupleFlag has nothing to do with it — which also means the greying is a
# client-side decision taken straight off this record, with no server round trip.
NO_CAPTURED_NPC = 0xFFFF

# Characters per account, and it is a hard limit rather than a policy: the
# client's reader has room for this many and no bound of its own.
#
# The manual states the rule (manual/p03_01: 「最大３人までキャラクターを作成する
# ことができます」) and Input_MsgSvResultCharacterListFromAccount::deserialize
# (0x8F9620) shows why it is the client's number too. Entries land at +8 with
# stride 0x100 and the u16 count sits at +0x308, so 8 + 3 * 0x100 lands exactly
# on the count -- the array is sized for three and ends where the count begins.
# The loop re-reads its bound from that field on every pass (0x8F9934, ``movzx
# edx, word ptr [ecx]``), so a longer list writes past the array with nothing
# stopping it.
#
# KONAMI's server could not have sent a fourth entry, so nothing in the client
# was ever written to survive one. Both directions are guarded here: create is
# refused at the cap, and entries() truncates whatever the store happens to hold.
MAX_CHARACTERS = 3

# Extra notebooks on the キャラクター選択 screen, the same instrument as
# PROBE_POSITIONS but pointed at a different question. The screen holds three,
# the message struct has room for exactly three (entries start at +8, stride
# 0x100, count at +0x308), and the player is using one -- so two are free to ask
# the client something and read the answer off one screen.
#
# Each entry is ``(nickname, charaFrameId, capturedNpcId, coupleFlag, couple)``
# and clones the first real character's looks, so the notebooks differ only in
# the field under test and in the あだな that labels them. ``couple`` is None or
# ``(familyName, firstName, nickName, inClass)`` for the partner -- round 218's
# addition, and the only way to put a カップル on this screen without writing
# loverCharaId into a save file.
#
# ⚠️ charaFrameId is which of the three notebooks the entry lands in, not
# decoration. The first attempt at this ruler left it cloned along with
# everything else, so all three entries claimed notebook 0: the screen showed one
# filled notebook carrying the *last* entry's あだな and two empty ones, and the
# round's reading was worthless. Give every entry a slot of its own.
#
# ⚠️ These are not real characters. Their charaIds are not in the store, so
# 登校 on one lands in an empty scene and 削除する answers Ng. They are there to
# be looked at, not pressed.
#
# Empty in normal play.
LIST_PROBES: "tuple[tuple[str, int, int, int, tuple[bytes, bytes, bytes, int] | None], ...]" = ()
LIST_PROBE_ID_BASE = 9500  # past PROBE_ID_BASE's markers and the direction ruler


def door_markers(map_id: int) -> tuple[tuple[str, int, int], ...]:
    """``(destination map name, posX, posY)`` for each of a map's doorway cells.

    One marker per cell, not per door: a door usually owns one cell, but several
    doors can share a destination and a few own two. Sorted so the ids a session
    hands out stay stable between logins.
    """
    from mapgraph import exits, name  # local: characters.py is imported by tools too

    seen: dict[tuple[int, int], str] = {}
    for _, _, cell, (dest_map, _, _, _) in exits(map_id):
        seen.setdefault(cell, name(dest_map))
    return tuple((name, x, y) for (x, y), name in sorted(seen.items()))


def marker_names(label: str) -> tuple[bytes, bytes]:
    """Split a label across the two 11-byte name fields the client draws.

    Shift-JIS, because that is what the character-create message carries. The
    fields hold five double-byte characters each, so the cut is by character and
    never mid-byte-pair — a half-encoded name is exactly the kind of thing that
    would show up as garbage over someone's head.
    """
    per_field = NAME_LEN // 2
    head, tail = label[:per_field], label[per_field : per_field * 2]
    return tuple(part.encode("shift_jis", "replace") for part in (head, tail))

# The minimap is a ruler the server gets to draw on. Pressing the map button
# sends MsgClRequestMinimapStart (0x3C00) and greys the button until an answer
# comes; what fills the map afterwards is MsgSvNotifyMinimapNotify (0x3C06),
# whose reader (0x902B70) takes a u16 count and then, per entry, one u8 through
# the stream's +0x2C slot and three u16 through +0x28 — and the dump beside it
# (0x902940) names them ``type`` and ``posInfo={mapId, posX, posY}``. Seven bytes
# on the wire, eight in memory.
#
# That means every dot on that map is a coordinate *we* chose, drawn over
# artwork we already have a copy of: mmt_010100.png is 960 x 723, exactly a tenth
# of the map's 9600 x 7232, so where a dot lands is directly readable.
#
# The set below is built to be read off a screenshot without labels:
#
#   corners  the rectangle's four corners, its centre, and where the player is
#            standing. If posX/posY were rectangle pixels these would sit on the
#            image's own corners and middle — one glance settles that question.
#   rays     three rays out of the origin, along +X, along +Y and diagonally,
#            each doubling. Doubling is self-labelling: whatever the scale, the
#            gaps between consecutive dots double, so any dot can be identified
#            by counting, and the last one still on the map gives the range.
#
# The four groups get different ``type`` values so they can be told apart if the
# client draws types with different icons; all four are real chara_type.txt ids
# (0=ＰＣ, 1=攻略ＮＰＣ, 3=汎用ＮＰＣ, 15=ゲームマスターＰＣ), so none of them is a
# value the client has no artwork for.
# The big map turned out to be a static overview with place labels and no
# character dots on it at all, so it reads nothing back. The small corner
# minimap does carry a dot, centred on the player — and it was solid blue, the
# same out-of-bounds colour as the world view, which is one more confirmation
# rather than a measurement.
#
# What it can still do is act as a ruler: the dots below sit at fixed offsets
# from wherever the player is, doubling as they go, so the gap between
# neighbouring dots on the minimap gives minimap-pixels per coordinate unit.
def minimap_params(map_id: int, positions: list[tuple[int, int, int]]) -> bytes:
    """``u16 count`` then one 7-byte ``type | mapId | posX | posY`` per dot.

    ``positions`` is (type, posX, posY); type 0 is ＰＣ, the rest of the values
    come from reference/idlist/chara_type.txt.

    This carried the doubling ruler that settled the coordinate scale. Now that
    the scale is known it goes back to its real job — saying who is where — for
    everyone *except* the player, whom the client draws itself. A dot here is
    painted once and never moves, so the player's own belongs to the client:
    see the MsgClRequestMinimapStart branch in mps_session.
    """
    body = struct.pack(">H", len(positions))
    for probe_type, pos_x, pos_y in positions:
        body += struct.pack(">BHHH", probe_type, map_id, pos_x, pos_y)
    return body


# A tour rather than a scale sweep: the scale question is answered, so the sweep
# that used to hold one "centre of 屋外" per candidate unit now holds one real
# place per stop. Opening the map steps to the next one, which is a way to walk
# the whole map in a single login and find out which cells the client will let a
# character stand on.
#
# Each entry is (label, posX, posY), and every coordinate is a decoration cell
# out of ex_map_object except the last two, which are read off mmt_010100.png
# through the transform above.
WARP_SWEEP: tuple[tuple[str, int, int], ...] = (
    ("kado gap  gate decorations", 106, 84),
    ("fountain  噴水広場", 102, 124),
    ("arch      祭アーチ", 96, 165),
    ("lantern   ランタン path", 162, 98),
    ("statue    理事長像", 33, 85),
    ("tree      クリスマス/七夕ツリー", 169, 142),
    ("koi       鯉幟", 184, 70),
    ("centre    diamond middle", 95, 95),
)


def parse_create_info(info: bytes) -> dict[str, object]:
    """Split a MsgClRequestCharacterCreate parameter block into named fields.

    The one sample on record decodes cleanly: names "aa", sex 0, bloodType 0,
    birth 1/1, every ``looks`` value 0 (the default face), uniform 4, tie 9 and
    0xFFFF — "nothing equipped" — in the five remaining accessory slots, with
    all 74 bytes consumed.
    """
    if len(info) != 74:
        raise ValueError(f"create info is {len(info)}B, expected 74")
    out: dict[str, object] = {}
    pos = 0

    def u8() -> int:
        nonlocal pos
        pos += 1
        return info[pos - 1]

    def u16() -> int:
        nonlocal pos
        pos += 2
        return struct.unpack_from(">H", info, pos - 2)[0]

    def name() -> bytes:
        nonlocal pos
        pos += NAME_LEN
        return info[pos - NAME_LEN : pos]

    out["charaFrameId"] = u8()
    out["familyName"] = name()
    out["firstName"] = name()
    out["nickName"] = name()
    out["sex"] = u16()
    out["bloodType"] = u16()
    out["birthMonth"] = u8()
    out["birthDay"] = u8()
    for field in LOOKS + ACCESSORY:
        out[field] = u16()
    out["charaType"] = u16()
    return out


def relabel(info: bytes, label: str, frame_id: int) -> bytes:
    """Retag a create block for use as a stand-in notebook.

    Two fields move. The あだな, which sits after charaFrameId and the two other
    names (1 + 11 + 11) and is the line the character-select page prints on its
    own, so three otherwise identical notebooks can be told apart. And
    charaFrameId itself, byte 0, which decides *which* notebook the entry lands
    in — leave it cloned and every stand-in piles into the same one.
    """
    at = 1 + NAME_LEN * 2
    tag = label.encode("shift_jis", "replace").ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    return bytes((frame_id,)) + info[1:at] + tag + info[at + NAME_LEN :]


def describe(info: bytes) -> str:
    """One-line rendering of a create block, for the server log."""
    fields = parse_create_info(info)

    def text(key: str) -> str:
        raw = fields[key]
        assert isinstance(raw, bytes)
        return raw.split(b"\x00")[0].decode("cp932", "replace")

    return (
        f"{text('familyName')} {text('firstName')} ({text('nickName')}) "
        f"sex={fields['sex']} blood={fields['bloodType']} "
        f"birth={fields['birthMonth']}/{fields['birthDay']} "
        f"frame={fields['charaFrameId']} type={fields['charaType']}"
    )


def name_trio(info: bytes) -> tuple[str, str, str]:
    """``(familyName, firstName, nickName)`` as text, NUL-trimmed.

    The three strings a scenario reads out of `PC[0x3010]`, `PC[0x3011]` and
    `PC[0x3012]` -- see `script.PC_FAMILY_NAME`. `full_name` hands the wire the
    fixed-width bytes it wants; this hands the script engine the characters,
    because what a comparison over there is against is a string pool literal.
    """
    fields = parse_create_info(info)

    def text(key: str) -> str:
        raw = fields[key]
        assert isinstance(raw, bytes)
        return raw.split(b"\x00")[0].decode("cp932", "replace")

    return text("familyName"), text("firstName"), text("nickName")


def profile_numbers(info: bytes) -> tuple[int, int, int]:
    """``(birthMonth, birthDay, skinColor)`` off one create block.

    The three numbers a scenario reads out of `PC[0x3015]`, `PC[0x3016]` and
    `PC[0x3704]` -- see `script.PC_BIRTH_MONTH` for the readings and their
    witnesses. Raw, as the block holds them: the month is already 1-based.
    """
    fields = parse_create_info(info)
    return (int(fields["birthMonth"]), int(fields["birthDay"]),
            int(fields["skinColor"]))


def display_name(info: bytes) -> str:
    """「姓 名」, the way a chat line should credit whoever typed it.

    ⚠️ The space is not decoration and it was missing until round 295, where
    the client drew both spellings in one window: a チャットルーム roster holds
    a row per member, the recipient's own row is drawn by the client off its own
    record as 「試験 三郎」, and the rows this end supplies arrived beside it as
    「試験次郎」. The map nameplate under a character spells it with the space
    too. ⇒ this is the game's own formatting, read off the screen rather than
    chosen.
    """
    fields = parse_create_info(info)

    def text(key: str) -> str:
        raw = fields[key]
        assert isinstance(raw, bytes)
        return raw.split(b"\x00")[0].decode("cp932", "replace")

    return f"{text('familyName')} {text('firstName')}".strip() or "?"


def list_entry(
    chara_id: int,
    info: bytes,
    pos: tuple[int, int] | None = None,
    map_id: int = SPAWN_MAP_ID,
    captured_npc_id: int = NO_CAPTURED_NPC,
    couple_flag: int = 0,
    in_club: int = 0,
    group_name: bytes = b"",
    title: int = 0,
    class_post: int = 0,
    club_post: int = posts.NO_CLUB_POST,
    tutorial_flag: int = 0,
    couple_names: "tuple[bytes, bytes, bytes] | None" = None,
    couple_in_class: int = 0,
    in_class: int | None = None,
    catch_copy: bytes = b"",
) -> bytes:
    """Build one 238-byte MsgSvResultCharacterListFromAccount entry.

    Everything the create request already said about the character is carried
    over verbatim; the rest is a freshly enrolled student. The character-select
    screen confirms how the filled-in values read: ``period`` 1 printed as
    「1 期生」 when that was what this end sent (it sends PERIOD now), ``inClass``
    is zero-based (1 came out as 「B組」, so A組 is 0), and
    ``inClub`` 0 with an empty ``friendGroupName`` give 「クラブ 無所属 / グループ
    無所属」 — which is what makes this entry the cheapest place to read a
    joined club back off the screen: the same slot prints the club's name from
    `club.bin` once ``in_club`` is not 0.

    ⭐ ``group_name`` is the other half of that same line, and it is the cheapest
    positive control there is for the 仲良しグループ work: the select screen
    prints this string with no permission check of any kind, so if the name
    shows up here but the toolbar's seventh icon still refuses to open, the
    bytes are landing and the gate is somewhere else. See groups.py.
    """
    f = parse_create_info(info)
    out = bytearray()
    out += struct.pack(">B", f["charaFrameId"])
    out += struct.pack(">I", chara_id)
    for key in ("familyName", "firstName", "nickName"):
        raw = f[key]
        assert isinstance(raw, bytes)
        out += raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += struct.pack(">HH", f["sex"], f["bloodType"])
    out += struct.pack(">BB", f["birthMonth"], f["birthDay"])
    for key in LOOKS + ACCESSORY:
        out += struct.pack(">H", f[key])
    out += struct.pack(">H", PERIOD)  # period
    out += group_name.ljust(GROUP_NAME_LEN, b"\x00")[:GROUP_NAME_LEN]  # friendGroupName
    out += struct.pack(">HH",
                       IN_CLASS if in_class is None else in_class,
                       in_club)  # inClass (0 = A組), inClub
    # ⭐ catchCopy. Twenty-one zeros until round 400, which is how long the
    # field had a name and no writer -- see catchcopy.py for the button that
    # fills it. ⛔️ Nothing on THIS screen draws it: the character-select card
    # and its 「情報を見る」 page are as silent about it as they are about the
    # three 役職 fields beside them. It is packed here because the entry is the
    # record and the record now has the value, not because a pixel depends on
    # it -- 0x6501 is the copy the name card reads.
    out += catchcopy.field(catch_copy)
    out += struct.pack(">BB", couple_flag, 1)  # coupleFlag, newbieFlag
    # ⭐ Three hard zeros until round 156. ``title`` is the 称号 out of the 経歴
    # -- one per character, not one per message -- and the other two are
    # posts.Posts; see that module for what each one keys and what draws it.
    out += struct.pack(">HHH", title, class_post, club_post)
    out += struct.pack(">H", f["charaType"])
    out += struct.pack(">H", 0)  # testLv
    out += b"\x00" * (2 * NUM_OF_CHARA_ABILITY)  # abilityParam[6]
    out += b"\x00" * NUM_OF_CLUB  # clubParamInfo.level[16]
    out += b"\x00" * NUM_OF_CLUB  # clubParamInfo.gauge[16]
    out += struct.pack(">H", 0)  # virtue
    out += struct.pack(">B", 0)  # stress
    out += struct.pack(">HH", 0, couple_in_class & 0xFFFF)  # charaCondition, coupleInClass
    # ⭐⭐ FOUR MORE FIELDS THAT HAD NEVER BEEN FILLED, and the comment naming
    # them had been sitting here since the entry was first built: the partner's
    # 組 and their three names. Round 218 read them off the client's own dump of
    # this message (the `coupleInClass=` / `coupleFamilyName=` strings at
    # 0x7FE8xx) and connected them to the pair /couple already stores. This is
    # the one place in this build where a カップル has somewhere to show: the
    # キャラクター選択 notebook is a screen that exists and opens, while the
    # 0x45xx カップル一覧 behind CSequencerCoupleInfo has no way in -- see
    # couple.py for why that is a date and not a gap.
    #
    # ⚠️ ONLY A PARTNER IN THE SAME ACCOUNT CAN BE NAMED HERE. This runs off one
    # CharacterStore and a lover in somebody else's account is not in it, so a
    # cross-account pair sends coupleFlag with the names left blank. That is the
    # honest rendering of "this store does not know", and it is visible on
    # screen rather than silent, which is why it is not worked around here.
    if couple_names is None:
        out += b"\x00" * (3 * NAME_LEN)  # couple family/first/nick names
    else:
        for raw in couple_names:
            out += raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += struct.pack(">Q", 0)  # playTime
    out += struct.pack(">HHH", map_id, *(pos or SPAWN_POS))  # posInfo: mapId, posX, posY
    out += struct.pack(">B", 0)  # direction
    out += struct.pack(">H", captured_npc_id)  # capturedNpcId
    # ⭐⭐⭐ 初登校. `manual/p02_06`: 「選択したキャラクターが初登校の場合には
    # チュートリアルイベントを行った後、マップモードに入ります」 -- so the screen
    # this entry draws is where 「is this one's first day」 is decided, and this
    # is the only field on the wire that could say it. Hard 0 until round 192,
    # and nothing this end sends is read anywhere else, which is what made it the
    # cheapest thing to try. See CharacterStore.debut_pending.
    out += struct.pack(">B", 1 if tutorial_flag else 0)  # tutorialFlag
    if len(out) != ENTRY_SIZE:
        raise AssertionError(f"entry is {len(out)}B, reader wants {ENTRY_SIZE}")
    return bytes(out)


TINY_ENTRY_SIZE = 74

# ⭐⭐ friendGroupId's 「no group」 is 0xFFFFFFFF, not 0 -- measured in round 143
# off the client's own code, not guessed. The PC 交流メニュー's 「グループ登録申込み」
# is greyed out unless the person right-clicked answers -1 here: the predicate
# behind that icon (VA 0x6FC2B2) reads friendGroupId out of the character record
# and refuses on anything else, so a server that says 0 is saying 「already in
# group 0」 and the invite can never be offered. Sending 0 is what kept that icon
# grey through rounds 141-142 while every other explanation was ruled out.
#
# ⚠️ The neighbouring leaderAuthorityFlag is read by the same predicate, on the
# *inviter* instead, and there 0/1 is right -- only this one field is a -1 field.
NO_GROUP = 0xFFFFFFFF


def add_entry(
    chara_id: int,
    info: bytes,
    pos: tuple[int, int] | None = None,
    names: tuple[bytes, bytes] | None = None,
    map_id: int = SPAWN_MAP_ID,
    direction: int = facing.DEFAULT,
    action: int = 0,
    group_id: int = NO_GROUP,
) -> bytes:
    """Build one 74-byte MsgSvNotifyCharacterAdd (0x480F) entry.

    This is the message that puts a character into the scene, and it is the only
    place the client is told where anybody stands: the ``posInfo`` inside the
    238-byte character-list entry feeds the select screen, not the lobby.

    The reader is Input_MsgSvNotifyCharacterAdd::deserialize (0x901010) — ``u16
    count`` then entries of exactly 74 bytes, using the same mtNetStreamInputBuffer
    vtable slots as everything else (+0x24 u32, +0x28 u16, +0x2C u8, and 0xA49610
    for the two 11-byte names). The dump beside it names every field in the same
    order the reader consumes them: a ``tinychara`` of charaId, the two names, sex
    and the nine ``looks``/seven ``accessory`` values, then ``position`` (posInfo's
    mapId/posX/posY plus direction), ``action``, ``pose`` and ``friendGroupId``.

    Note the trio omits nickName and bloodType, which the 238-byte list entry does
    carry — this really is the smaller "tiny" record, not a prefix of the other.

    ``pos`` and ``names`` override the position and the two name fields, which is
    what the coordinate probes ride on: the same character record placed at eight
    spots under eight labels, so the name over each head says which candidate it is.

    ``direction`` rode on the same idea, and that is how its encoding got
    settled: a grid of stand-ins, one per value 0-15, each labelled with its own
    number, so one screenshot answered the whole field instead of one login per
    candidate. It is a four-bit mask of 上/下/左/右; see facing.py for the
    reading and chat.direction_probes for the ruler that produced it. The
    default here is DOWN rather than the 0 it used to be, because 0 turns out to
    set no direction bit at all.

    ``map_id`` is what makes indoor maps possible at all. It used to be pinned to
    屋外 because the player never left it; now that MsgClRequestCharaWarp is
    answered, the reload that follows a warp has to re-add the character on the
    map it warped *to*, or the client would be told it is standing outdoors while
    it draws the cafeteria.
    """
    f = parse_create_info(info)
    out = bytearray()
    out += struct.pack(">I", chara_id)
    shown = names if names is not None else (f["familyName"], f["firstName"])
    for raw in shown:
        assert isinstance(raw, bytes)
        out += raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += struct.pack(">H", f["sex"])
    for key in LOOKS + ACCESSORY:
        out += struct.pack(">H", f[key])
    out += struct.pack(">HHH", map_id, *(pos or SPAWN_POS))  # posInfo
    out += struct.pack(">B", direction)
    # ``action`` is the u16 nobody has read yet. It is the only field in the
    # entry that could carry the icon 「ルームを作成したキャラクターの頭上の
    # アイコン」 names, which is the manual's only way into somebody else's
    # 自主トレ room -- so it gets a ruler of its own (chat.action_probes).
    out += struct.pack(">H", action)
    out += struct.pack(">B", 0)  # pose
    # ⭐⭐ This is the copy the client reaches for the *first* time somebody is
    # right-clicked, before MsgSvResultCharaInfo for that id has come back --
    # measured in round 143, where the 「グループ登録申込み」 icon stayed grey on
    # the first right-click and went live on the second. So NO_GROUP has to be
    # right in both messages or the menu is wrong exactly once per character.
    # ⚠️⚠️ And it is the copy that decides the icon even long after 0x6501 has
    # been answered: round 150 right-clicked a player who was in the same group
    # as the person clicking, and 「グループ登録申込み」 was offered anyway,
    # because this entry had been going out with NO_GROUP for everybody. The
    # stand-ins (markers, rulers) keep the default -- they are in no group and
    # there is nobody to ask -- but every entry for a real character now carries
    # the real id, out of groups.GroupBook.id_of.
    #
    # ⚠️ 0x480F is an *add*, not a refresh, so a character whose group changes
    # while somebody is looking at them has to be redrawn: see
    # _presence_refresh_onlookers and the callers around each mutation.
    out += struct.pack(">I", group_id)  # friendGroupId
    if len(out) != TINY_ENTRY_SIZE:
        raise AssertionError(f"entry is {len(out)}B, reader wants {TINY_ENTRY_SIZE}")
    return bytes(out)


CHARA_INFO_SIZE = 139


def chara_info(
    info: bytes,
    in_club: int = 0,
    group_name: bytes = b"",
    group_id: int = NO_GROUP,
    leader_authority: int = 0,
    leader_qualification: int = 0,
    lover_chara_id: int = 0,
    title: int = 0,
    class_post: int = 0,
    club_post: int = posts.NO_CLUB_POST,
    in_class: int | None = None,
    catch_copy: bytes = b"",
) -> bytes:
    """Build the 139-byte MsgSvResultCharaInfo (0x6501) parameter block.

    This is what the lobby asks for the moment a character appears in the scene:
    MsgClQueryCharaInfo (0x6500) carries one u32 charaId and the answer carries no
    id at all, just the record. Reader is Input_MsgSvResultCharaInfo::deserialize
    (0x8F3FB0), 38 reads, and the dump at 0x8F4750 names them in the same order.

    Compared with the 238-byte list entry this one drops everything the lobby has
    no use for — abilities, club levels, stress, playTime, position — and adds
    ``loverCharaId``, ``friendGroupId`` and the two leader flags.

    ⚠️ Those last three are the only place this end can tell the client anything
    about 仲良しグループ before a single 0x62xx message is exchanged: the seventh
    toolbar icon and the PC menu's 「グループ登録申込み」 both decide whether they
    are usable without asking. All four default to the zeros this server sent
    before groups existed, so a character in no group is byte-identical to how it
    always was; groups.GroupBook.fields is what fills them in.
    """
    f = parse_create_info(info)
    out = bytearray()
    for key in ("familyName", "firstName", "nickName"):
        raw = f[key]
        assert isinstance(raw, bytes)
        out += raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += struct.pack(">HH", f["sex"], f["bloodType"])
    out += struct.pack(">BB", f["birthMonth"], f["birthDay"])
    for key in LOOKS + ACCESSORY:
        out += struct.pack(">H", f[key])
    out += struct.pack(">H", f["charaType"])
    out += struct.pack(">HHH", PERIOD,
                       IN_CLASS if in_class is None else in_class,
                       in_club)  # period, inClass, inClub
    # ⭐⭐ catchCopy, and THIS is the copy that shows: 「キャッチコピー：%1%」
    # (`msg_text` 223) is one of the five lines of the right-click name card,
    # which is built from this message. See catchcopy.py.
    out += catchcopy.field(catch_copy)
    # ⚠️ coupleFlag is derived, never stored: one field cannot say 「恋人あり」
    # while the other says who, so the flag is 1 exactly when there is an id.
    # Both were hard zeros until round 154 and a character with no 恋人 is still
    # byte-identical to what this server always sent.
    out += struct.pack(">BB", 1 if lover_chara_id else 0, 1)  # coupleFlag, newbieFlag
    # ⭐ See list_entry: the same three, and this is the copy the right-click
    # name card is built from -- the one that has a 「所属部：%1%  役職：%2%」
    # line to put a 部活役職 in (posts.py names the rows).
    out += struct.pack(">HHH", title, class_post, club_post)
    out += struct.pack(">I", lover_chara_id)  # loverCharaId
    out += group_name.ljust(GROUP_NAME_LEN, b"\x00")[:GROUP_NAME_LEN]  # friendGroupName
    out += struct.pack(">I", group_id)  # friendGroupId
    out += struct.pack(">BB", leader_authority, leader_qualification)
    if len(out) != CHARA_INFO_SIZE:
        raise AssertionError(f"info is {len(out)}B, reader wants {CHARA_INFO_SIZE}")
    return bytes(out)


#: 0x4813's body, and the width is the deserializer's rather than a sum of
#: guesses: 0x901C50 reads u32, u16, u16, u16, u16, u8, u32, u32 and two
#: 21-byte fixed fields, in that order and with nothing between them.
INFO_CHANGED_SIZE = 63


def info_changed(
    chara_id: int,
    title: int = 0,
    class_post: int = 0,
    club_post: int = posts.NO_CLUB_POST,
    in_club: int = 0,
    lover_chara_id: int = 0,
    group_id: int = NO_GROUP,
    group_name: bytes = b"",
    catch_copy: bytes = b"",
) -> bytes:
    """One 0x4813 MsgSvNotifyCharacterInfoChanged: the record's mutable half.

    This is `chara_info` minus everything that cannot change: no name, no sex,
    no birthday, no looks, no abilities. What is left is the nine fields the
    client keeps in its own per-charaId chara store, and the message exists to
    overwrite them there without touching anything else.

    ⭐ THE HANDLER IS THE SPECIFICATION. 0x77FE62 is nine calls in a row, one
    per field, each of them `(store, charaId, value)`: friendGroupName
    (0x6F8F22), friendGroupId (0x6F8F47), catchCopy (0x6F902B), inClub
    (0x6F906D), coupleFlag (0x6F9089), title (0x6F90A3), classPost (0x6F90BF),
    clubPost (0x6F90DB) and loverCharaId (0x6F90F7). Every one of them looks
    the charaId up in the same std::map and returns without writing when there
    is no record, so a notify about somebody a client has never been told about
    is a no-op rather than a fault.

    ⭐⭐ IT IS NEVER FOR THE SUBJECT, and that is read off the client rather
    than assumed. Each of those setters has a sibling that takes no charaId and
    fills in its own (0x6F891C, "my charaId"), and those siblings are what the
    Ok handlers call: 0x4313 OkCharaMenuCatchcopy runs 0x6F91D2 -> 0x6F9190,
    0x5A01 OkClubEnter and 0x5A04 OkClubPart both run 0x6F91BA. So the client
    maintains its own row out of its own replies, and 0x4813 is how everybody
    else's row is kept up to date. ⚠️ This is the opposite answer to the one
    round 441 measured for 0x4100, where no such sibling exists and the subject
    has to be told about itself -- the two are not one rule, and the thing to
    look for is the own-id wrapper.

    ⚠️ ``coupleFlag`` is derived here exactly as `chara_info` derives it: the
    flag says whether there is a 恋人 and ``loverCharaId`` says who, so one is
    1 precisely when the other is set.
    """
    out = bytearray()
    out += struct.pack(">I", chara_id)
    out += struct.pack(">HHHH", title, class_post, club_post, in_club)
    out += struct.pack(">B", 1 if lover_chara_id else 0)
    out += struct.pack(">II", lover_chara_id, group_id)
    out += group_name.ljust(GROUP_NAME_LEN, b"\x00")[:GROUP_NAME_LEN]
    out += catchcopy.field(catch_copy)
    if len(out) != INFO_CHANGED_SIZE:
        raise AssertionError(
            f"info_changed is {len(out)}B, reader wants {INFO_CHANGED_SIZE}"
        )
    return bytes(out)


class CharacterStore:
    """The characters this account has made, kept across server restarts.

    Only the raw create block is stored. It is the exact bytes the client sent,
    so nothing is lost to a partial understanding of the format, and the list
    entry is rebuilt from it on demand.
    """

    def __init__(
        self,
        path: Path | None,
        ids: "charaids.CharaIndex | None" = None,
        account_id: int = 0,
        group_book: object = None,
    ) -> None:
        # ⚠️ path is None for a detached store: one that is never read from disk
        # and never written back. It exists so a connection that has not named an
        # account has somewhere harmless to read and write -- an empty list, and
        # writes that go nowhere -- instead of falling onto a real account's
        # file. See MpsServer._chars for the one caller that makes one.
        self.path = path
        # Who hands out charaIds, and who this store asks for. Both are None/0
        # for a detached store, and that is the whole reason they are arguments
        # rather than globals: a connection that has not named an account must
        # not push the server-wide counter along or leave an ownerless row in
        # the index. See add() for what it does instead.
        self.ids = ids
        self.account_id = account_id
        # ⚠️ Typed as object rather than annotated properly: groups.py imports
        # this module for GROUP_NAME_LEN, so naming GroupBook here would close
        # that circle. Only the select screen's 「グループ ...」 line needs it,
        # and a detached store simply has none.
        self.group_book = group_book
        self.records: list[dict[str, object]] = []
        if path is not None and path.exists():
            try:
                self.records = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"[characters] ignoring unreadable {path}: {exc}")

    def full(self) -> bool:
        """True when this account cannot take another character.

        The caller answers MsgSvNgCharacterCreate instead of creating one; see
        MAX_CHARACTERS for why silently allowing a fourth is not an option.
        """
        return len(self.records) >= MAX_CHARACTERS

    def roster_size(self) -> int:
        """How many characters this account has right now, counted off the file.

        Off the file rather than ``self.records`` on purpose: the store that
        asks is the game connection's, whose snapshot dates from bind time,
        and the character about to play 初登校 was created on the school
        connection after that. ``reload`` would see it too, but it swaps
        ``self.records`` wholesale and is reserved for ``entries``; this one
        reads, counts and touches nothing. A detached store, or an unreadable
        file, counts what it holds. Used by ``mps_session.tutorial_ask`` --
        the constant above it says why the count is what 初登校's opening
        question is answered with.
        """
        if self.path is not None and self.path.exists():
            try:
                return len(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        return len(self.records)

    def notebook_taken(self, frame_id: int) -> bool:
        """True when one of this account's characters is already in that 手帳.

        ⭐ 「その生徒手帳には、既にキャラクターが登録されています」 is the
        client's own sentence for this and it says 生徒手帳, not account -- so
        the rule the reason names is per-notebook, and full() is the same fact
        seen from the other side once all three are occupied.

        A well-behaved client never asks for an occupied one: the player clicks
        a notebook that is drawn empty. What it protects against is measured
        rather than imagined -- three entries sharing charaFrameId 0 draw as ONE
        filled notebook carrying the last one's あだな, so a collision does not
        look like a collision on screen, it looks like a character that
        vanished. See LIST_PROBES.
        """
        for record in self.records:
            try:
                fields = parse_create_info(bytes.fromhex(str(record["info"])))
            except (ValueError, KeyError):
                continue
            if fields["charaFrameId"] == frame_id:
                return True
        return False

    def add(self, info: bytes) -> int:
        if self.ids is not None:
            chara_id = self.ids.mint(self.account_id)
        else:
            # Detached: this store is not on disk and its id is not in the
            # index, so the number only has to be one the client will draw and
            # one this store has not used. It belongs to nobody, which is the
            # honest answer for a connection that never said who it was --
            # owner() will not find it, and nothing persists it.
            chara_id = max(
                (int(r["charaId"]) for r in self.records), default=CHARA_ID_BASE - 1
            ) + 1
        # ⭐ "debut": this character has not had its 初登校 yet. Written at
        # creation rather than inferred later, so that the day this file is read
        # by something that has never seen the migration rule below, the answer
        # is in the record instead of in a heuristic.
        #
        # ⭐⭐ "romance", round 194, and it is there for that same reason: an
        # empty cast — nobody met — is what a new character now starts with, and
        # 初登校 is what puts the first name on stage (romance.absorb). A record
        # written before that has to be given the old assumption instead, and
        # the only thing that tells the two apart is whether this key is there
        # at all ⇒ writing it here keeps `romance()`'s fallback a statement
        # about the record's age rather than a guess about its owner.
        #
        # ⚠️ `declare_empty_cast` would supply it at 登校 anyway, so this is the
        # belt and not the braces. Keep both: a character is readable — /rom,
        # a tool, a future caller — before it has ever been to school, and the
        # honest answer for one this end created itself should not depend on a
        # migration rule meant for records it did not.
        # ⭐ "inClass": which 組 this character enrolled in, decided once here by
        # CLASS_ASSIGNMENT and never again -- 登録内容は変更できません, and the 組
        # is what picks the classroom its 授業 and 試験 happen in. A record from
        # before this key existed has no 組 of its own and reads as IN_CLASS,
        # which is the only value this server has ever sent for one.
        self.records.append({"charaId": chara_id, "info": info.hex(),
                             "debut": True,
                             "inClass": self._assign_class(),
                             "romance": romance.Romance(
                                 int(parse_create_info(info)["sex"])).to_json()})
        self._save()
        return chara_id

    def _school_class_counts(self) -> "dict[int, int]":
        """How many characters are in each 組, across every account on disk.

        ⚠️ School-wide rather than account-wide on purpose: balancing against
        this account's own three would put the first three characters in Ａ組,
        Ｂ組, Ｃ組 no matter how full those already are. Read off the records
        themselves rather than kept as a running tally, because a tally is a
        second copy of the same fact and the two would drift the first time a
        character was deleted by hand. Creation is rare and these files are
        small, so the walk costs nothing anyone can feel.
        """
        counts = {room: 0 for room in range(len(curriculum.CLASSROOM))}
        if self.path is None:
            return counts
        for path in sorted(self.path.parent.parent.glob("*/characters.json")):
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for record in records:
                room = int(record.get("inClass", IN_CLASS))
                if room in counts:
                    counts[room] += 1
        return counts

    def _assign_class(self) -> int:
        """The 組 a character created right now enrols in."""
        room = pick_class(self._school_class_counts())
        if room != IN_CLASS:
            print(f"[characters] enrolling in 組 {room} (CLASS_ASSIGNMENT="
                  f"{CLASS_ASSIGNMENT})")
        return room

    def in_class(self, chara_id: int) -> int:
        """Which 組 that character is in; IN_CLASS if the record predates the key."""
        for record in self.records:
            if int(record["charaId"]) == chara_id:
                return int(record.get("inClass", IN_CLASS))
        return IN_CLASS

    # ── 初登校 ──────────────────────────────────────────────────────────────
    def debut_placement(self, chara_id: int) -> bool:
        """Is `location` answering about this character with a debut cell?

        The three conditions are `location`'s own, kept here rather than
        re-spelled at the call site because the session has to ask them at 登校
        and act on the answer much later: which of the two debut cells a
        character belongs on is not settled until the tutorial has said whether
        it walked them anywhere, and by then the flag below is down and the
        record may have been written to. ⚠️ Guarded on "map"/"pos" as well as
        on the flag for the reason `location` is: re-arming an established
        character replays the event without also teleporting them.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            pos = record.get("pos")
            if isinstance(pos, list) and len(pos) == 2:
                return False
            return "map" not in record and self.debut_pending(chara_id)
        return False

    def debut_pending(self, chara_id: int) -> bool:
        """Has this character never been to school? (the ``tutorialFlag``)

        ⚠️⚠️ The obvious test -- ``career.visits == 0`` -- is wrong on this
        server's own saves and would have gone unnoticed for a round: the three
        characters on account 1 predate career.py entirely and have no "career"
        key at all, and account 10's has ``visits: 0`` beside ``seconds: 36``.
        Every one of them would have been called a first-timer and handed the
        tutorial again. So the count is not the evidence.

        The migration rule for a record written before "debut" existed is the
        one thing that is safe: a character that has never been in the world has
        never had anything written about it. Every path out of 登校 leaves a
        mark -- ``set_position`` writes "pos"/"map" on the first step taken and
        ``career`` on the first 登校 answered -- so a record holding nothing but
        the two keys ``add`` creates has never been played.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            if "debut" in record:
                return bool(record["debut"])
            return set(record) <= {"charaId", "info"}
        return False

    def set_debut_pending(self, chara_id: int, pending: bool) -> bool:
        """Arm or clear one character's 初登校; False if the id is not ours.

        Cleared by 登校 itself, because that is the moment the flag was read:
        the client has the answer and the select screen is gone. ⚠️ That means a
        client which died mid-tutorial does not get a second one -- which is the
        client's own rule as much as ours, since it is the one deciding what to
        do with the flag. /tutorial re-arms it.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            if "debut" in record and bool(record["debut"]) == pending:
                return False  # already says that; no write, no file churn
            record["debut"] = pending
            self._save()
            return True
        return False

    def declare_empty_cast(self, chara_id: int) -> bool:
        """Write 「nobody met yet」 into a record that has no 恋愛 row at all.

        ⭐⭐ Round 194, and it closes the one hole in `romance()`'s migration.
        That method has to guess for a record written before 初登校 could put
        anyone on stage, and it guesses from ``debut_pending`` — but 登校 clears
        that flag *before* the tutorial script runs, so between those two moments
        the guess flips to 「already debuted」 and the script's own write lands on
        a save that says 天宮 is there already. Measured, not feared: round 194's
        first real run replayed 初登校 on an old record and logged 「既に同じ値」.

        ⇒ the caller is 登校 itself, in the same breath as clearing the flag:
        having just told the client to play its 初登校, this end writes down that
        the campus is empty, and the tutorial fills it. Records that already
        carry a 恋愛 row are left alone — this only ever supplies a missing one.

        ⛔️ Not a reset. It cannot blank a cast that is already written, which is
        why re-arming an established character with /tutorial leaves that
        character's 恋愛 state exactly as it was.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            if isinstance(record.get("romance"), dict):
                return False
            fields = parse_create_info(bytes.fromhex(str(record["info"])))
            record["romance"] = romance.Romance(int(fields["sex"])).to_json()
            self._save()
            return True
        return False

    def position(self, chara_id: int) -> tuple[int, int]:
        """Where this character last stood, or the spawn point if it never has."""
        return self.location(chara_id)[1:]

    def location(self, chara_id: int) -> tuple[int, int, int]:
        """``(mapId, posX, posY)`` for one character, spawn point as the default.

        A cell number means nothing without the map it indexes: 屋外 runs to about
        190 on each axis while a classroom is a sixth of that, so (54, 19) is a
        different place in each. Records written before warping worked carry only
        ``pos``, and those are read as 屋外, which is where their owner was.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            pos = record.get("pos")
            map_id = int(record.get("map", SPAWN_MAP_ID))
            if isinstance(pos, list) and len(pos) == 2:
                return map_id, int(pos[0]), int(pos[1])
            if self.debut_placement(chara_id):
                # ⭐ Never been to school: stand where the tutorial ends, in
                # the corridor outside the 理事長室. See DEBUT_CELL.
                # ⚠️ This is the guided ending, and it is the answer given
                # before the event has been played -- the client is still on
                # 「登校処理を行っています」 and nobody has been asked anything
                # yet. A tutorial that turns out to walk nobody anywhere moves
                # the player to DEBUT_CELL_ALONE when it ends, which is the only
                # moment that road is known.
                return debut_cell()
            return map_id, *SPAWN_POS
        return SPAWN_MAP_ID, *SPAWN_POS

    def set_position(self, chara_id: int, pos: tuple[int, int], map_id: int) -> bool:
        """Remember a reported position; False if it was already that cell.

        The client walks locally and tells the server afterwards through
        MsgClCastCharaMove, so this is a record of where it says it went, not a
        decision. Writing only on a change keeps a walk across the map from
        rewriting the file once per step.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            if record.get("pos") == [pos[0], pos[1]] and int(
                record.get("map", SPAWN_MAP_ID)
            ) == map_id:
                return False
            record["pos"] = [pos[0], pos[1]]
            record["map"] = map_id
            self._save()
            return True
        return False

    def remove(self, chara_id: int) -> bool:
        """Drop one character; False if this account never had that id.

        The id does not come back. It used to: ``add`` picked max+1 over what was
        left, so deleting the newest character handed its number to the next one
        made. charaids.CharaIndex.release drops the ownership row and leaves the
        counter where it is, because a charaId is written down outside the record
        it names -- loverCharaId, friendGroupId, the address book -- and reusing
        it points all of those at somebody else.
        """
        kept = [r for r in self.records if int(r["charaId"]) != chara_id]
        if len(kept) == len(self.records):
            return False
        self.records = kept
        self._save()
        if self.ids is not None:
            self.ids.release(chara_id)
        return True

    def group_name(self, chara_id: int) -> bytes:
        """This character's 仲良しグループ name, or empty for 無所属.

        Empty is what every character answered before groups.GroupBook existed,
        and a detached store has no book at all, so both fall through to the
        same bytes the select screen has always been sent.
        """
        book = self.group_book
        if book is None:
            return b""
        return book.fields(chara_id)[0]

    def reload(self) -> None:
        """Re-read the file, in case another connection wrote it.

        ⚠️⚠️ A store belongs to one connection, and a player has more than one:
        the select screen is served on the school connection while everything
        said in chat arrives on the game connection, each with its own snapshot
        of the same file. Every mutator here is write-through, so the file is
        always the newer of the two -- but a snapshot taken at bind time is not,
        and 初登校 is the first field where that shows: /tutorial writes the bit
        from the game connection and the select screen has to see it.

        ⚠️ Called from `entries` and nowhere else on purpose. It is safe there
        because the select screen is drawn before anything on this connection
        has changed a record, and it would not be safe everywhere: this replaces
        `self.records` wholesale.
        """
        if self.path is None or not self.path.exists():
            return
        try:
            self.records = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[characters] keeping the loaded copy of {self.path}: {exc}")

    def entries(self) -> bytes:
        """``u16 count`` followed by one entry per character.

        Plus one stand-in notebook per LIST_PROBES entry when that switch is
        filled, so a question about a field of this record can be asked of three
        notebooks at once instead of one login per value. They are cloned from
        the first real character, which is also why they are skipped when the
        account is empty: there would be nothing to clone.
        """
        self.reload()
        parts = []
        for record in self.records:
            chara_id = int(record["charaId"])
            map_id, pos_x, pos_y = self.location(chara_id)
            held = self.posts(chara_id) or posts.Posts()
            parts.append(
                list_entry(
                    chara_id,
                    bytes.fromhex(str(record["info"])),
                    (pos_x, pos_y),
                    map_id,
                    in_club=self.in_club(chara_id),
                    group_name=self.group_name(chara_id),
                    couple_flag=1 if self.lover(chara_id) else 0,
                    couple_names=self.lover_names(chara_id),
                    title=self.title(chara_id),
                    class_post=held.class_post,
                    club_post=held.club_post,
                    tutorial_flag=1 if self.debut_pending(chara_id) else 0,
                    in_class=self.in_class(chara_id),
                    catch_copy=self.catch_copy(chara_id),
                )
            )
        if self.records and LIST_PROBES:
            info = bytes.fromhex(str(self.records[0]["info"]))
            for index, probe in enumerate(LIST_PROBES):
                label, frame_id, captured, couple_flag, couple = probe
                parts.append(
                    list_entry(
                        LIST_PROBE_ID_BASE + index,
                        relabel(info, label, frame_id),
                        captured_npc_id=captured,
                        couple_flag=couple_flag,
                        couple_names=None if couple is None else couple[:3],
                        couple_in_class=0 if couple is None else couple[3],
                    )
                )
        if len(parts) > MAX_CHARACTERS:
            # Reachable two ways: a characters.json written before the cap
            # existed, and LIST_PROBES set past the free notebooks. Neither is
            # worth sending a list the client cannot hold, so cut it and say so
            # -- silently dropping a character the player can see in the file
            # would be the more confusing failure.
            print(
                f"[characters] {len(parts)} entries exceeds the client's "
                f"{MAX_CHARACTERS}; sending the first {MAX_CHARACTERS}"
            )
            parts = parts[:MAX_CHARACTERS]
        return struct.pack(">H", len(parts)) + b"".join(parts)

    def find(self, chara_id: int) -> bytes | None:
        """The raw create block for one charaId, or None if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) == chara_id:
                return bytes.fromhex(str(record["info"]))
        return None

    def romance(self, chara_id: int) -> romance.Romance | None:
        """This character's 恋愛 state, defaults included, or None if unknown.

        Built fresh each time rather than cached: the player's sex comes out of
        the create block, so a Romance is only meaningful next to the character
        it belongs to, and the file is small enough that reconstructing beats
        keeping a second copy in sync.

        ⚠️⚠️ The one migration, round 194, and it is two questions and not one.
        Since round 194 nobody is on stage until 初登校 writes her there, so a
        record carrying no "romance" key has to be asked whether that debut is
        still ahead of it:

        * **still ahead** (``debut_pending``) — leave the campus empty. The
          tutorial is about to fill it, and pre-marking would take that away.
        * **already behind it** — its owner's debut played in a round where
          this end was not watching, so the old assumption (天宮 for a male
          character, 桜井 for a female one) is the only honest answer.

        ⚠️⚠️ The flag alone is not enough, because 登校 clears it *before* the
        tutorial script runs: between those two moments a character in the
        middle of its 初登校 reads as one that already had it, and the script's
        own write then lands on a save that already says 天宮 is on stage.
        ⭐ Measured, not feared — round 194's first real run hit exactly that and
        logged 「既に同じ値（記帳なし）」. Two writers close it, and neither is
        optional: ``add()`` stamps every new record, and ``declare_empty_cast``
        stamps an old one at 登校 while the flag still stands. ⇒ a record still
        reaching the guess below has never been through either.

        ⭐ Self-sealing rather than a permanent branch: the first `set_romance`
        for such a character writes the assumed cast out explicitly, and from
        then on the saved row answers and none of this runs again.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            fields = parse_create_info(bytes.fromhex(str(record["info"])))
            saved = record.get("romance")
            if isinstance(saved, dict):
                return romance.Romance(int(fields["sex"]), saved)
            return romance.Romance(
                int(fields["sex"]), None,
                assume_initial_cast=not self.debut_pending(chara_id),
            )
        return None

    def set_romance(self, chara_id: int, state: romance.Romance) -> bool:
        """Write one character's 恋愛 state back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["romance"] = state.to_json()
            self._save()
            return True
        return False

    def scorecard(self, chara_id: int) -> curriculum.ScoreCard | None:
        """This character's 通知表 state, defaults included, or None if unknown.

        Same treatment as ``romance``: rebuilt from the saved dict each time
        rather than cached, because a ScoreCard only means anything next to the
        character it belongs to and the file is small.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("curriculum")
            return curriculum.ScoreCard(saved if isinstance(saved, dict) else None)
        return None

    def set_scorecard(self, chara_id: int, card: curriculum.ScoreCard) -> bool:
        """Write one character's 通知表 state back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["curriculum"] = card.to_json()
            self._save()
            return True
        return False

    def ability(self, chara_id: int) -> ability.AbilitySheet | None:
        """This character's 能力パラメータ, defaults included, or None if unknown.

        Same treatment as ``romance`` and ``scorecard``, for the same reasons.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("ability")
            return ability.AbilitySheet(saved if isinstance(saved, dict) else None)
        return None

    def set_ability(self, chara_id: int, sheet: "ability.AbilitySheet") -> bool:
        """Write one character's 能力パラメータ back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["ability"] = sheet.to_json()
            self._save()
            return True
        return False

    def club(self, chara_id: int) -> "club.Membership | None":
        """This character's クラブ state, defaults included, or None if unknown.

        Same treatment as ``romance``, ``scorecard`` and ``ability``.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("club")
            return club.Membership(saved if isinstance(saved, dict) else None)
        return None

    def set_club(self, chara_id: int, state: "club.Membership") -> bool:
        """Write one character's クラブ state back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["club"] = state.to_json()
            self._save()
            return True
        return False

    def items(self, chara_id: int) -> "item.Inventory | None":
        """This character's アイテム, or None if it is not ours.

        Same treatment as ``club``, one subsystem over.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("items")
            return item.Inventory(saved if isinstance(saved, dict) else None)
        return None

    def set_items(self, chara_id: int, inv: "item.Inventory") -> bool:
        """Write one character's アイテム back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["items"] = inv.to_json()
            self._save()
            return True
        return False

    def options(self, chara_id: int) -> "options.GameOptions | None":
        """This character's オプション flags, or None if it is not ours.

        Same treatment as ``club``, and asked about somebody else's charaId as
        often as about our own: 通知表公開 is a permission the *owner* granted,
        so the branch that answers a peer's 通知表 looks the setting up in the
        owner's store (accounts.owner_of) rather than in the asker's.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("options")
            return options.GameOptions(saved if isinstance(saved, dict) else None)
        return None

    def set_options(self, chara_id: int, opts: "options.GameOptions") -> bool:
        """Write one character's オプション flags back. False if not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["options"] = opts.to_json()
            self._save()
            return True
        return False

    def catch_copy(self, chara_id: int) -> bytes:
        """This character's キャッチコピー, empty for none or not ours.

        ⚠️ Bytes, not str, all the way through: what the player typed is cp932
        off the wire and it goes back out as cp932, so nothing here has to pick
        a replacement character for a byte this end cannot read. Stored hex for
        the same reason the create block is.

        ⚠️ Asked about a peer's charaId far more often than about our own --
        the name card 0x6501 draws is somebody else's -- so the caller looks it
        up in the owner's store, the way `options` and `career` are looked up.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("catchcopy")
            if not isinstance(saved, str):
                return b""
            try:
                return catchcopy.parse(bytes.fromhex(saved))
            except ValueError:
                return b""
        return b""

    def set_catch_copy(self, chara_id: int, line: bytes) -> bool:
        """Write one character's キャッチコピー back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["catchcopy"] = catchcopy.parse(line).hex()
            self._save()
            return True
        return False

    def chara_type(self, chara_id: int) -> "int | None":
        """This character's 体型 out of the create block, or None if not ours.

        ⚠️ It lives in the create block rather than beside `catchcopy` and the
        other keys, because that is where it has always lived: the last u16 of
        the 74 bytes the client sent at creation, which is also what
        `list_entry`, `chara_info` and everything else pack. Keeping a second
        copy in the record would mean two answers to one question.
        """
        info = self.find(chara_id)
        return None if info is None else int(parse_create_info(info)["charaType"])

    def set_chara_type(self, chara_id: int, body_type: int) -> bool:
        """Write one character's 体型 back. False if it is not ours.

        The create block is stored verbatim and everything else is rebuilt from
        it on demand, so the change is made in place: charaType is its last
        u16 and nothing else moves. ⚠️ Rewritten through parse_create_info's own idea of the layout
        rather than a bare slice, so a block of the wrong length is refused here
        instead of silently having its last two bytes overwritten.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            info = bytes.fromhex(str(record["info"]))
            parse_create_info(info)  # raises unless this really is a 74B block
            record["info"] = (info[:-2] + struct.pack(">H", body_type & 0xFFFF)).hex()
            self._save()
            return True
        return False

    def career(self, chara_id: int) -> "career.Career | None":
        """This character's 経歴, or None if it is not ours.

        Same treatment as ``options``, and asked about a peer's charaId for the
        same reason: 経歴公開 gates a card somebody else opens, so the answer
        has to be built out of the owner's store.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("career")
            return career.Career(saved if isinstance(saved, dict) else None)
        return None

    def set_career(self, chara_id: int, state: "career.Career") -> bool:
        """Write one character's 経歴 back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["career"] = state.to_json()
            self._save()
            return True
        return False

    def drama_records(self, chara_id: int) -> "dramarecord.DramaRecords | None":
        """This character's ドラマイベント records, or None if it is not ours.

        Same treatment as ``career`` and ``posts``: rebuilt from the stored
        dict on every ask, so nothing here can go stale behind a cached copy.
        ⚠️ Asked about a peer's charaId as well, because the character-menu
        list is built out of whoever is being looked at.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("dramaEvents")
            return dramarecord.DramaRecords(saved if isinstance(saved, dict) else None)
        return None

    def set_drama_records(self, chara_id: int,
                          played: "dramarecord.DramaRecords") -> bool:
        """Write one character's ドラマイベント records back. False if not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["dramaEvents"] = played.to_json()
            self._save()
            return True
        return False

    def posts(self, chara_id: int) -> "posts.Posts | None":
        """This character's two 役職 keys, or None if it is not ours.

        Same treatment as ``options`` and ``career``, and asked about a peer's
        charaId for the same reason: the right-click name card is built out of
        the record of whoever was clicked, so the answer has to come from that
        character's own account store.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            saved = record.get("posts")
            return posts.Posts(saved if isinstance(saved, dict) else None)
        return None

    def set_posts(self, chara_id: int, held: "posts.Posts") -> bool:
        """Write one character's 役職 back. False if it is not ours."""
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            record["posts"] = held.to_json()
            self._save()
            return True
        return False

    def title(self, chara_id: int) -> int:
        """The 称号 to put on the wire, out of the 経歴 where it is stored.

        ⭐ One 称号 per character, not one per message: 0x4316 has carried this
        value since round 155 while 0x0319 and 0x6501 packed a constant 0
        beside it. They agree now. ⚠️ Nothing awards a 称号 and
        `designation.bin` has exactly one row, so today this is still 0 down
        every path -- the point is that it is no longer 0 for two different
        reasons. See career.TITLE_NONE.
        """
        state = self.career(chara_id)
        return state.title if state is not None else career.TITLE_NONE

    def lover(self, chara_id: int) -> int:
        """This character's ``loverCharaId``, 0 for 恋人なし or not ours.

        ⭐ ``coupleFlag`` is the half that shows: with it set, the right-click
        info box draws a pink heart where a newbie draws the green 若葉マーク.
        Round 154 measured that on screen, one variable at a time.

        ⚠️⚠️ ``loverCharaId`` is carriage only -- no screen anywhere yet. Both
        fields have a setter in the client's chara store (0x6F909D, 0x6F910B)
        and **neither has a getter**, while every neighbour that does something
        (charaType +0x48, inClub +0x4E, friendGroupId +0x8C, the two leader
        flags +0x90/+0x91) has both. ⚠️ That is a fact about the *store*, not
        about the value: the heart proves something reads coupleFlag, and it
        reads it off the 0x6501 message rather than out of the store. So "no
        getter here" is never a reason to call a field inert: the reader may
        simply live somewhere else.

        What is *not* here is deliberate: how a couple forms, what breaks one,
        and whether either side may refuse are rules the manual states no
        numbers for and the client cannot be asked about (the smallest-invention
        rule).
        The knob sets the field; it does not invent a 交際 system around it.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            return int(record.get("lover", 0) or 0)
        return 0

    def lover_names(self, chara_id: int) -> "tuple[bytes, bytes, bytes] | None":
        """This character's partner's three names, for 0x0319's couple fields.

        None when there is no partner, and also when there is one this store
        cannot see: a lover in another account is not in self.records, and the
        entry then goes out with coupleFlag set and the names blank. See
        list_entry for why that is left visible rather than papered over.
        """
        lover_id = self.lover(chara_id)
        if not lover_id:
            return None
        info = self.find(lover_id)
        if info is None:
            return None
        f = parse_create_info(info)
        return (
            bytes(f["familyName"]),   # type: ignore[arg-type]
            bytes(f["firstName"]),    # type: ignore[arg-type]
            bytes(f["nickName"]),     # type: ignore[arg-type]
        )

    def set_lover(self, chara_id: int, lover_id: int) -> bool:
        """Point one character's ``loverCharaId`` somewhere. False if not ours.

        One side only. Pairing both is the caller's job because the other half
        often lives in a different account's store, and this class only ever
        speaks for its own.
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            if lover_id:
                record["lover"] = int(lover_id)
            else:
                record.pop("lover", None)
            self._save()
            return True
        return False

    def in_club(self, chara_id: int) -> int:
        """The club id to put on the wire for this character, 0 if none."""
        state = self.club(chara_id)
        return state.in_club if state else club.NO_CLUB

    def sex(self, chara_id: int) -> "int | None":
        """This character's 性別 out of the create block, or None if not ours.

        Same numbering the cast slots in `drama_events.json` use, which is why
        `drama.selectable_actors` can compare the two directly.
        """
        info = self.find(chara_id)
        return None if info is None else int(parse_create_info(info)["sex"])

    def full_name(self, chara_id: int) -> tuple[bytes, bytes] | None:
        """``(familyName, firstName)`` as the create block holds them, SJIS.

        Both are already NAME_LEN bytes and NUL-padded, which is the shape the
        wire's fixed reader wants, so they go out untouched.
        """
        info = self.find(chara_id)
        if info is None:
            return None
        fields = parse_create_info(info)
        return bytes(fields["familyName"]), bytes(fields["firstName"])  # type: ignore[arg-type]

    def name_trio(self, chara_id: int) -> "tuple[str, str, str] | None":
        """This character's 姓 / 名 / ニックネーム as text, or None if not ours."""
        info = self.find(chara_id)
        return None if info is None else name_trio(info)

    def profile_numbers(self, chara_id: int) -> "tuple[int, int, int] | None":
        """This character's 誕生月 / 誕生日 / 肌色, or None if not ours."""
        info = self.find(chara_id)
        return None if info is None else profile_numbers(info)

    def summary(self) -> str:
        return ", ".join(
            f"#{r['charaId']} {describe(bytes.fromhex(str(r['info'])))}" for r in self.records
        ) or "(none)"

    def _save(self) -> None:
        if self.path is None:
            return  # detached: writes stay in memory and go when the connection does
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, indent=2), encoding="utf-8")
