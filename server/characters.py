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
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import ability
import club
import curriculum
import facing
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
# Each entry is ``(nickname, charaFrameId, capturedNpcId, coupleFlag)`` and
# clones the first real character's looks, so the notebooks differ only in the
# field under test and in the あだな that labels them.
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
LIST_PROBES: tuple[tuple[str, int, int, int], ...] = ()
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


def display_name(info: bytes) -> str:
    """「姓 名」, the way a chat line should credit whoever typed it."""
    fields = parse_create_info(info)

    def text(key: str) -> str:
        raw = fields[key]
        assert isinstance(raw, bytes)
        return raw.split(b"\x00")[0].decode("cp932", "replace")

    return f"{text('familyName')}{text('firstName')}".strip() or "?"


def list_entry(
    chara_id: int,
    info: bytes,
    pos: tuple[int, int] | None = None,
    map_id: int = SPAWN_MAP_ID,
    captured_npc_id: int = NO_CAPTURED_NPC,
    couple_flag: int = 0,
    in_club: int = 0,
) -> bytes:
    """Build one 238-byte MsgSvResultCharacterListFromAccount entry.

    Everything the create request already said about the character is carried
    over verbatim; the rest is a freshly enrolled student. The character-select
    screen confirms how the filled-in values read: ``period`` 1 prints as
    「1 期生」, ``inClass`` is zero-based (1 came out as 「B組」, so A組 is 0), and
    ``inClub`` 0 with an empty ``friendGroupName`` give 「クラブ 無所属 / グループ
    無所属」 — which is what makes this entry the cheapest place to read a
    joined club back off the screen: the same slot prints the club's name from
    `club.bin` once ``in_club`` is not 0.
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
    out += struct.pack(">H", 1)  # period
    out += b"\x00" * GROUP_NAME_LEN  # friendGroupName
    out += struct.pack(">HH", 0, in_club)  # inClass (0 = A組), inClub
    out += b"\x00" * GROUP_NAME_LEN  # catchCopy
    out += struct.pack(">BB", couple_flag, 1)  # coupleFlag, newbieFlag
    out += struct.pack(">HHH", 0, 0, 0)  # title, classPost, clubPost
    out += struct.pack(">H", f["charaType"])
    out += struct.pack(">H", 0)  # testLv
    out += b"\x00" * (2 * NUM_OF_CHARA_ABILITY)  # abilityParam[6]
    out += b"\x00" * NUM_OF_CLUB  # clubParamInfo.level[16]
    out += b"\x00" * NUM_OF_CLUB  # clubParamInfo.gauge[16]
    out += struct.pack(">H", 0)  # virtue
    out += struct.pack(">B", 0)  # stress
    out += struct.pack(">HH", 0, 0)  # charaCondition, coupleInClass
    out += b"\x00" * (3 * NAME_LEN)  # couple family/first/nick names
    out += struct.pack(">Q", 0)  # playTime
    out += struct.pack(">HHH", map_id, *(pos or SPAWN_POS))  # posInfo: mapId, posX, posY
    out += struct.pack(">B", 0)  # direction
    out += struct.pack(">H", captured_npc_id)  # capturedNpcId
    out += struct.pack(">B", 0)  # tutorialFlag
    if len(out) != ENTRY_SIZE:
        raise AssertionError(f"entry is {len(out)}B, reader wants {ENTRY_SIZE}")
    return bytes(out)


TINY_ENTRY_SIZE = 74


def add_entry(
    chara_id: int,
    info: bytes,
    pos: tuple[int, int] | None = None,
    names: tuple[bytes, bytes] | None = None,
    map_id: int = SPAWN_MAP_ID,
    direction: int = facing.DEFAULT,
    action: int = 0,
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
    out += struct.pack(">I", 0)  # friendGroupId
    if len(out) != TINY_ENTRY_SIZE:
        raise AssertionError(f"entry is {len(out)}B, reader wants {TINY_ENTRY_SIZE}")
    return bytes(out)


CHARA_INFO_SIZE = 139


def chara_info(info: bytes, in_club: int = 0) -> bytes:
    """Build the 139-byte MsgSvResultCharaInfo (0x6501) parameter block.

    This is what the lobby asks for the moment a character appears in the scene:
    MsgClQueryCharaInfo (0x6500) carries one u32 charaId and the answer carries no
    id at all, just the record. Reader is Input_MsgSvResultCharaInfo::deserialize
    (0x8F3FB0), 38 reads, and the dump at 0x8F4750 names them in the same order.

    Compared with the 238-byte list entry this one drops everything the lobby has
    no use for — abilities, club levels, stress, playTime, position — and adds
    ``loverCharaId``, ``friendGroupId`` and the two leader flags.
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
    out += struct.pack(">HHH", 1, 0, in_club)  # period (1 期生), inClass (A組), inClub
    out += b"\x00" * GROUP_NAME_LEN  # catchCopy
    out += struct.pack(">BB", 0, 1)  # coupleFlag, newbieFlag
    out += struct.pack(">HHH", 0, 0, 0)  # title, classPost, clubPost
    out += struct.pack(">I", 0)  # loverCharaId
    out += b"\x00" * GROUP_NAME_LEN  # friendGroupName
    out += struct.pack(">I", 0)  # friendGroupId
    out += struct.pack(">BB", 0, 0)  # leaderAuthorityFlag, leaderQualificationFlag
    if len(out) != CHARA_INFO_SIZE:
        raise AssertionError(f"info is {len(out)}B, reader wants {CHARA_INFO_SIZE}")
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
        self.records.append({"charaId": chara_id, "info": info.hex()})
        self._save()
        return chara_id

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

    def entries(self) -> bytes:
        """``u16 count`` followed by one entry per character.

        Plus one stand-in notebook per LIST_PROBES entry when that switch is
        filled, so a question about a field of this record can be asked of three
        notebooks at once instead of one login per value. They are cloned from
        the first real character, which is also why they are skipped when the
        account is empty: there would be nothing to clone.
        """
        parts = []
        for record in self.records:
            chara_id = int(record["charaId"])
            map_id, pos_x, pos_y = self.location(chara_id)
            parts.append(
                list_entry(
                    chara_id,
                    bytes.fromhex(str(record["info"])),
                    (pos_x, pos_y),
                    map_id,
                    in_club=self.in_club(chara_id),
                )
            )
        if self.records and LIST_PROBES:
            info = bytes.fromhex(str(self.records[0]["info"]))
            for index, (label, frame_id, captured, couple) in enumerate(LIST_PROBES):
                parts.append(
                    list_entry(
                        LIST_PROBE_ID_BASE + index,
                        relabel(info, label, frame_id),
                        captured_npc_id=captured,
                        couple_flag=couple,
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
        """
        for record in self.records:
            if int(record["charaId"]) != chara_id:
                continue
            fields = parse_create_info(bytes.fromhex(str(record["info"])))
            saved = record.get("romance")
            return romance.Romance(
                int(fields["sex"]), saved if isinstance(saved, dict) else None
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

    def in_club(self, chara_id: int) -> int:
        """The club id to put on the wire for this character, 0 if none."""
        state = self.club(chara_id)
        return state.in_club if state else club.NO_CLUB

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

    def summary(self) -> str:
        return ", ".join(
            f"#{r['charaId']} {describe(bytes.fromhex(str(r['info'])))}" for r in self.records
        ) or "(none)"

    def _save(self) -> None:
        if self.path is None:
            return  # detached: writes stay in memory and go when the connection does
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, indent=2), encoding="utf-8")
