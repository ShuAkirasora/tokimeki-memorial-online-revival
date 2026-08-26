"""MPS packet layer for the login-server connection (port 25573).

Unlike the updater and the login-lobby query, this connection wraps every
message in a tagged packet:

    u16 PS | u16 TAG | body            PS = 2 + len(body)

Tags come from ``mpsCipherManager``'s callers in tmo.exe: 0x30 carries a normal
message, 0x31 a fragment continuation, and 0x34/0x35/0x36 the three key-exchange
steps. The client opens with 0x34, expects 0x35 back, and answers 0x36.

The client's opening 0x34 is ``exchange_key_phase1``'s output (0xA4BB40):

    u16 checksum | u16 keylen | key | u32 sequence

The server answers with ``phase2``'s output (0xA4BC70), which echoes the client's
key back *first* so the peer can verify it, then carries the server's own key:

    u16 checksum | u16 clKeyLen | clKey | u16 svKeyLen | svKey | u32 sequence

The client runs ``phase3`` (0xA4BF50) on that — replying with only the server key
makes it log ``exchange_key_phase3: disagree with encipher key data`` and hang up
— and answers 0x36 in the same two-key shape, which the server's ``phase4``
(0xA4C2D0) verifies.

Every body except tag 8 is Blowfish-enciphered; server/mps_cipher.py implements
the variant tmo.exe uses and the client needs no patching. Which key applies
depends on the tag, mirroring the three modules mpsCipherManager holds:

* 0x34/0x35/0x36 travel under the bootstrap key, on both sides.
* 0x30 in either direction uses the key the *sender* announced during the
  exchange — the receiver installs it as its decipher key (0xA45E30).
* tag 8 is not enciphered at all. It is driven outside the cipher manager, which
  is what lets timesync_reply emit a 26-byte body: decipher (0xA4B300) rejects
  any length that is not a multiple of 8 before it looks at anything else.

Enciphering zero-pads to an 8-byte multiple, hence the trailing padding tolerated
when parsing.
"""

from __future__ import annotations

import asyncio
import os
import random
import secrets
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from characters import (
    LOOKS,
    ACCESSORY,
    DEBUT_FACING,
    IN_CLASS,
    MARK_DOORS,
    MAX_CHARACTERS,
    SPAWN_POS,
    SPAWN_MAP_ID,
    WARP_SWEEP,
    PROBE_ID_BASE,
    PROBE_ID_LIMIT,
    PROBE_POSITIONS,
    CharacterStore,
    add_entry,
    chara_info,
    describe,
    display_name,
    door_markers,
    marker_names,
    minimap_params,
    parse_create_info,
)
import ability
import accounts
import career
import chat
import club
import clubbattle
import codes
import curriculum
import exam
import facing
import friends
import groups
import gs3vm
import item
import konami_id
import lesson
import lesson_skill
import mapgraph
import mps_cipher
import options
import posts
import quiz
import romance
import script
import stress
import trainingroom
from common import ServiceConfig, ensure_runtime_dirs, inet_u32, write_packet_log

# All 675 ids, recovered from tmo.exe's parser tables and the category base each
# message's own debug string prints. Regenerate with the id extractor --python.
from message_names import MESSAGE_NAMES

#: How long a connection may say nothing before this server closes it.
#:
#: ⭐ TMO_IDLE_S overrides it, and the reason is the same one behind
#: clubbattle.TURN_DEADLINE_S — ⚠️⚠️ MEASURED THE HARD WAY, round 90: pausing
#: the client's machine to freeze the コマンド countdown killed the fight instead,
#: with 「通信が断たれました」 on screen and 「battle dropped on disconnect」 in
#: the log. The mechanism is not that a single pause ran long. It is that the
#: client's 30-second timesync runs on the CLIENT's clock, which the pause stops,
#: while this timeout runs on real time, which it does not: waking the machine for
#: two seconds at a time never accumulates the 30 seconds of client-side time one
#: heartbeat needs, so the socket goes quiet in real time no matter how short
#: each individual pause was. Freezing the client therefore requires stretching
#: this too — the two knobs are one technique, not two.
#:
#: ⚠️ Unset is the shipping 300, so an interrupted measuring session leaves
#: nothing behind. ⚠️ Do not leave it set while testing reconnect behaviour.
IDLE_TIMEOUT_S = float(os.environ.get("TMO_IDLE_S") or 300.0)

#: Seed for the coin `_script_die` flips at an `OP_RAND` branch. ⚠️ None is the
#: factory value and means a real coin; an int makes one server run repeatable,
#: which is for reproducing a report and nothing else -- see `gs3vm._Die`.
SCRIPT_DIE_SEED: int | None = None

TAG_TIMESYNC = 0x08
TAG_MESSAGE = 0x30
TAG_FRAGMENT = 0x31
TAG_KEX1 = 0x34
TAG_KEX2 = 0x35
TAG_KEX3 = 0x36

TAG_NAMES = {
    TAG_TIMESYNC: "timesync",
    TAG_MESSAGE: "message",
    TAG_FRAGMENT: "fragment",
    TAG_KEX1: "kex1",
    TAG_KEX2: "kex2",
    TAG_KEX3: "kex3",
}

# Length of the key we announce in 0x35. Each connection draws its own, the way
# the client draws its own from rand() at 0xA46267; 16 bytes keeps the 0x35 body
# at exactly 24, matching the client's own phase1 size.
SERVER_KEY_LEN = 16

MSG_CL_REQUEST_LOGIN = 0x7000
MSG_SV_OK_LOGIN = 0x7001
MSG_SV_NG_LOGIN = 0x7002
# The relay ticket coming home: first message on the game connection, and on the
# school connection after it. See accounts.TicketDesk.
MSG_CL_NOTIFY_AUTH_CODE = 0x0020
MSG_CL_REQUEST_GAME_LOGIN = 0x0200
MSG_SV_OK_GAME_LOGIN = 0x0201

# Which school 0x6603 MsgSvOkExamReady says the exam is at.
#
# ⚠️⚠️ **Not zero, and this cost a client.** 0x0201 has answered zero since the
# day it was first answered and nothing ever minded, so the exam's schoolId was
# given the same value on the reasoning that one number should not be written
# twice. It crashed the client: `school.bin` holds ten records keyed **1…10**,
# there is no school 0, and 0x6603 is the first message this server has ever
# sent whose schoolId the client actually looks something up with. The fault was
# a strlen at 0x00402E12 — `std::string::assign(const char*)` — walking a
# pointer whose value was **2**, which is what a missed record hands back.
#
# ⚠️ The client is never asked which school it is in and never volunteers it:
# `MsgClRequestSchoolSelect`'s dump string names a schoolId field, but the
# client serialises the message empty (observed: datalen 2, message id only),
# and an account that already has characters skips the select screen entirely.
# So this is a choice, constrained to 1…10 by the table.
EXAM_SCHOOL_ID = 1

# Queries whose answer is nothing but ``u16 count`` and that many fixed-size
# entries, so an empty list is two zero bytes. Which ones those are is not a
# guess: the shape reader walks each Input_<reply> deserializer and reports
# the ones that read a u16 and then loop (``counted``).
EMPTY_LIST_REPLIES = {
    0x0312: 0x0313,  # MsgClQueryGalleryList  -> MsgSvResultGalleryList
    0x0315: 0x0316,  # MsgClQueryEndingList   -> MsgSvResultEndingList
    # ⚠️ 0x0406 MsgClQueryLockerList used to be stubbed here with an empty list.
    # It is answered for real now, out of the account's own store -- see
    # item.Locker and the 0x0406 branch below -- because 0x4D0A can put things
    # into that store and a stub would have swallowed them.
    #
    # ⚠️ 0x6400 MsgClQueryFriendList was the second one to leave, in round 141,
    # for the same reason: 0x6403 can now put a name into the address book, and
    # a stub would have answered "you have no friends" over the top of it. See
    # friends.py -- and note that the query is the *only* thing that fills that
    # window, so the stub was also the reason it had never shown a row.
}

# The four things the アイテム window's buttons do to a row. Grouped because the
# window serialises its requests: answering three of them is not three quarters
# of the feature, it is a window that wedges on the fourth click.
ITEM_OPERATIONS = (
    item.MSG_CL_CAST_ITEM_EQUIP,
    item.MSG_CL_CAST_ITEM_USE,
    item.MSG_CL_REQUEST_ITEM_PUT_IN_LOCKER,
    item.MSG_CL_REQUEST_ITEM_DEL,
)

# Requests answered with a constant parameter block. Each layout comes from
# the shape reader plus the field names in the reply's dump function.
FIXED_REPLIES = {
    # 0x0700/0x0703 used to be here as a constant (1, 1, 0, 0) with 0x0703
    # written off as unanswerable. Both now have branches of their own further
    # down: the flags are per character, because 通知表公開 is a permission one
    # player grants about their own card and a server-wide constant cannot say
    # that. See options.py for the four names and what each one means.
    # The lobby handshake that follows 登校. All six messages of the two trios
    # are "empty" by the shape reader, and Input_MsgSvOkLobbyDataStart's vtable[0] is
    # 0x8CB9A0 — the same ``xor eax,eax; ret 8`` zero-param stub that
    # MsgSvOkSchoolLogin uses — so an Ok really is just the type and nothing
    # else. Whatever lobby content is meant to arrive between Start and End
    # must come as separate notifications; this only unblocks the bracket.
    # 0x4000 is not here: it needs a character pushed behind the Ok, so it has a
    # branch of its own further down.
    # ⚠️ 0x4003 does not close the bracket the way its name suggests. After a
    # cutscene the client opens one with 0x4000 and then simply does not send
    # this — round 42 waited on it to flush a chat line and waited forever; the
    # next one seen arrived minutes later, in the middle of starting the *next*
    # conversation. Do not use it as a "the map is back" signal.
    0x4003: (0x4004, b""),  # MsgClRequestLobbyDataEnd   -> MsgSvOkLobbyDataEnd
    # MsgClQueryPoolMessage -> MsgSvResultPoolMessage: the lobby asks this about
    # its own charaId right after MsgClQueryCharaInfo. The answer is a single u16
    # the dump (0x915A40) calls nNum, i.e. how many pooled messages are waiting;
    # the bodies would follow as MsgSvNotifyPoolMessage (0xA103), which carries a
    # counted string plus ImportanceLevel and category. Nobody is writing to this
    # player, so nNum is 0 and no notify is owed.
    0xA100: (0xA101, bytes(2)),
    # MsgClQueryGMCallList -> MsgSvResultGMCallList: asked once shortly after the
    # scene is up, and nothing visibly waits on it — the client went on walking
    # and warping while it went unanswered. Cheap to satisfy anyway.
    #
    # the shape reader called the reply empty; it is not. Input_MsgSvResultGMCallList's
    # vtable[0] (0x8E0700) makes exactly one call, through the stream's +0x14
    # slot, and that reader (0xA49A00) checks four bytes of headroom and names
    # itself "operator >> (int32_t)" when it runs out. The dump (0x8DF590) prints
    # a single field, nNum — the same shape as MsgSvResultPoolMessage's count of
    # waiting items. Nobody has called a GM here, so it is zero, and no
    # MsgSvNotifyGMCallList entries are owed.
    0x6711: (0x6712, bytes(4)),
    # Closing the minimap. Both Oks of the pair deserialize through 0x8CB9A0,
    # the shared zero-param stub, so neither carries anything; the Start side
    # has a branch of its own because it needs the dot list pushed behind it.
    0x3C03: (0x3C04, b""),  # MsgClRequestMinimapEnd -> MsgSvOkMinimapEnd
    # Bracketing an NPC event. Nothing has ever asked for these — they are here
    # ahead of the client because /npc pushes MsgSvNotifyNpcControl and this is
    # the likeliest thing to come back, and a round spent stalling on a reply
    # whose shape is already known would be a wasted one. The shape is not a
    # guess: Input_MsgSvOkNpcEventStart and Input_MsgSvOkNpcEventEnd both
    # deserialize through 0x8CB9A0, the shared zero-param stub that
    # MsgSvOkLobbyDataEnd above uses, so an Ok is the type and nothing else.
    # The requests do carry something (0x5600 reads one u16) which is ignored;
    # whatever an event needs beyond being acknowledged is still unknown.
    0x5600: (0x5601, b""),  # MsgClRequestNpcEventStart -> MsgSvOkNpcEventStart
    # ⭐ 0x5603 used to be the row below this one. It moved into the drama
    # branch in round 160, because answering it is no longer a formality: a
    # script started from a map object ends with the client sending this and
    # then saying nothing at all, on a black screen, while a script started by
    # talking to a chibi never sends it and reloads the map by itself. The
    # branch keeps the same Ok as its default and adds a knob (/evend) for
    # sending the teardown by hand.
    # ⭐⭐ Three of the six icons in the PC 交流メニュー, measured in round 151 by
    # right-clicking a second player and pressing them one at a time. All three
    # carry exactly one u32 -- the charaId of the person clicked -- and all three
    # had gone unanswered, which is the failure this project has already written
    # down twice: the client puts up 「通信中 / サーバーからの返答待ちです」 and
    # sits there. Round 151 measured that too, and measured the way out: an Ng or
    # an Error takes the box down with nothing else on screen, no re-login.
    #
    # ⭐ 経歴 IS NO LONGER ONE OF THEM. Its row said, for fifty rounds, that a
    # refusal was honest because there was no card to send -- and that the thing
    # which would take the row out is building the card, at which point 経歴公開
    # becomes its gate the way 通知表公開 is 0x430D's. That is what career.py
    # did; 0x4315 is handled below and the flag is read there.
    # The two that are left are: ツーショット and トレード are whole subsystems
    # (0x5000..0x5203 and 0x5100..0x5118) and a refusal is a rule nobody has read
    # off the client. ⚠️ INVENTED, and what overturns it is implementing either
    # family -- at which point these two rows come out.
    #
    # Reason byte is the NG_REASON placeholder defined below; the table is built
    # before that name exists, hence the literal.
    0x5000: (0x5002, b"\x00"),  # MsgClRequestTwoshotRequest -> MsgSvNgTwoshotRequest
    0x5100: (0x5102, b"\x00"),  # MsgClRequestTradeRequest   -> MsgSvNgTradeRequest
}

MSG_CL_QUERY_CHARACTER_LIST = 0x0318
MSG_SV_RESULT_CHARACTER_LIST = 0x0319
MSG_CL_REQUEST_CHARACTER_CREATE = 0x030C
MSG_SV_OK_CHARACTER_CREATE = 0x030D
MSG_SV_NG_CHARACTER_CREATE = 0x030E
MSG_CL_REQUEST_CHARACTER_DESTROY = 0x030F
MSG_SV_OK_CHARACTER_DESTROY = 0x0310
MSG_SV_NG_CHARACTER_DESTROY = 0x0311

# The payload both character refusals carry. Input_MsgSvNgCharacterCreate and
# Input_MsgSvNgCharacterDestroy share deserializer 0x8D84A0, which pulls one
# value through the stream's read-int8 slot (vt+0x1C), and each class's dump
# method names that field 「reason=%d」 -- so a refusal is one byte on the wire,
# not the empty message the Ok side of the pair sends (0x8CB9A0, `xor eax,eax;
# ret 8`, reads nothing).
#
# ⚠️ The value is a placeholder, not a finding, and following it statically ends
# at a wall rather than at an answer. The only place in the whole image that
# visibly reads the field back is the message's own debug dump; whoever else
# consumes it is reached through a delegate bound at run time, so "the client
# ignores it" cannot be concluded either. Zero is sent because the reader
# consumes a byte no matter what.
#
# The slot is read-int8, i.e. **signed**: a byte above 127 arrives negative.
NG_REASON = b"\x00"
MSG_CL_REQUEST_SCHOOL_LOGIN = 0x0306
MSG_SV_OK_SCHOOL_LOGIN = 0x0307
MSG_CL_REQUEST_SCHOOL_LOGOUT = 0x0309
MSG_SV_OK_SCHOOL_LOGOUT = 0x030A
MSG_CL_REQUEST_REENTRANCE = 0x031B
MSG_SV_OK_REENTRANCE = 0x031C
MSG_SV_NG_REENTRANCE = 0x031D
MSG_CL_REQUEST_LOBBY_DATA_START = 0x4000
MSG_SV_OK_LOBBY_DATA_START = 0x4001
MSG_CL_QUERY_POOL_MESSAGE = 0xA100
MSG_SV_NOTIFY_CHARACTER_ADD = 0x480F
MSG_SV_NOTIFY_CHARACTER_DEL = 0x4810
MSG_CL_QUERY_CHARA_INFO = 0x6500
MSG_SV_RESULT_CHARA_INFO = 0x6501
MSG_SV_ERROR_CHARA_INFO = 0x6502
MSG_CL_REQUEST_MINIMAP_START = 0x3C00

# How long the teacher's opening line is given, in the client's own milliseconds.
# ⚠️ INVENTED, and only meaningful if speechEndTime really is a moment in the
# timesync's frame rather than a duration — see lesson.start_params.
#
# Ten minutes rather than the eight seconds that seemed reasonable, and that is
# an experiment rather than a setting. The first 0x6100 was accepted — the client
# built the lesson scene and drew 体育's 校庭 backdrop, so the packet parsed —
# and then the process died. If the speech is what ends and nothing follows it,
# a speech that outlasts the period moves the crash out of reach; if the client
# dies just the same, the fault is in the packet and not in what comes after it.
# Either answer is worth one restart.
SPEECH_MS = 600_000
MSG_SV_OK_MINIMAP_START = 0x3C01
MSG_SV_NOTIFY_MINIMAP = 0x3C06
MSG_CL_CAST_CHARA_TURN = 0x4803
MSG_SV_NOTIFY_CHARA_TURN = 0x4804
MSG_SV_NOTIFY_GM_WARP = 0x6808
MSG_CL_REQUEST_CHARA_WARP = 0x4800
MSG_SV_OK_CHARA_WARP = 0x4801
MSG_SV_NG_CHARA_WARP = 0x4802
MSG_CL_CAST_NORMAL_CHAT = 0x4900
MSG_SV_NOTIFY_NORMAL_CHAT = 0x4901
# The other things the player can say, and why none of them is answered.
# Marked in the form the message audit reads, so that the audit counts them as
# decided rather than as forgotten.
# UNANSWERED 0x4A00 -- ひそひそ話 is addressed at one character, and nothing has
#   ever been seen selecting a target; answering it as a broadcast would be the
#   opposite of what it means.
# UNANSWERED 0x4600 -- 友達チャット, one of the 会話ツール window's channels. That
#   window has never been opened here, so nothing would ever send it (0x4700,
#   the group channel, is the same story -- see groups.py).
# UNANSWERED 0x480C -- 表情 on the map. Its lesson twin (0x610C) is answered
#   because the pair was being measured anyway; this one has no measured layout.

# How many 74-byte entries go into one MsgSvNotifyCharacterAdd. Sixteen keeps a
# batch at 1186 bytes of parameters — the same order as the messages already
# known to arrive intact — while 屋外's 72 doorways in one push would be 5.3 KB.
ADD_BATCH = 16

# The direction ruler's stand-ins, kept clear of the doorway markers so the two
# sets can share a scene: reusing an id would tell the client to move a marker
# rather than to add anything, and the ruler would come out with holes in it.
DIRECTION_PROBE_ID_BASE = PROBE_ID_BASE + 100
ACTION_PROBE_ID_BASE = PROBE_ID_BASE + 300  # /act, clear of the direction ruler
# The tinychara ``action`` field is the icon over a character's head.
ACTION_NONE = 0             # and so is 15, and so is everything from 16 up
# ⭐⭐⭐ Round 150 named the whole field. Two readings agree, neither of them a
# guess: the client ships fourteen icons as mch/act/act_bin/act_01..act_14 with
# one atlas behind them (mch/act/act_vrm), and the manual page p05_08 draws ten
# of them with their names (beta/manual/images/*.gif). Laying the two side by
# side matches act_NN to the manual's picture one for one, and the /act ruler
# then read the same fourteen back off the screen at exactly value == NN.
# ⚠️ Round 71's ruler recorded 4 and 12 as drawing nothing; both draw. 16-31
# were walked in round 150 as well and every one of them is blank.
ACTION_TALKING = 1           # 会話中        (kaiwa_chu)
ACTION_TRADING = 2           # トレード中    (trading_chu)
ACTION_LESSON = 3            # 授業中        (jugyou_shu)
ACTION_CLUB_ACTIVITY = 4     # クラブ活動中  (club_chu)
ACTION_DRAMA_EVENT = 5       # ドラマイベント中 (2shot_chat)
ACTION_READING_PAPER = 6     # 校内新聞閲覧中 (shinbun_eturan)
ACTION_LOCKER_OPEN = 7       # ロッカー開き中 (locker_hirakichu)
ACTION_SIGNBOARD = 8         # 看板          (kanban)
ACTION_CHAT_ROOM = 9         # チャット募集中 (chat_boshu)
ACTION_TRAINING_ROOM = 10    # 自主トレ募集中 (jishutore_boshu)
# 11-14 draw, but p05_08 names only ten and these four are not among them:
# 11 is a character holding out a heart, 12 a heart breaking, 13 a whole heart,
# and 14 is byte-identical artwork to 4. The hearts belong to 恋愛 / p05_12
# カップル; nothing here sends any of them.

# What the client sends while the player moves around, decoded rather than left
# as a hex blob because these carry the only coordinates the client ever states
# itself. Shapes are the shape reader's read widths:
#
#     0x4800 MsgClRequestCharaWarp  reads=2+2+2+1
#     0x4803 MsgClCastCharaTurn     reads=1
#     0x4809 MsgClCastCharaMove     reads=2+2+1
#
# and the field names follow MsgSvNotifyCharacterAdd's position block, which is
# mapId/posX/posY/direction in exactly that order.
MOVEMENT_SHAPES = {
    0x4800: ("HHHB", 7),
    0x4803: ("B", 1),
    0x4809: ("HHB", 5),
}
MOVEMENT_NAMES = {
    # 0x4800's fourth byte is direction, not status: unlike the move cast, this
    # one follows MsgSvNotifyCharacterAdd's position block exactly, which is
    # mapId/posX/posY/direction.
    0x4800: ("mapId", "posX", "posY", "direction"),
    0x4803: ("direction",),
    # The third byte is status, not direction: the dump at 0x900BD0 pushes
    # "posX=", "posY=", "status=" and stops there.
    0x4809: ("posX", "posY", "status"),
}

MSG_SV_NOTIFY_CHARA_MOVE = 0x480A


# id -> name, so a warp target can be named the moment it arrives instead of
# being looked up by hand. Purely cosmetic: nothing on the wire depends on it.
#
# These come out of the graph rather than reference/idlist/map.txt, which used
# to be read here as well. The two spell the 78 real maps identically -- the
# graph took its names from that same table when it was built -- so the second
# read only duplicated the first. The 14 ids map.txt carries on top of the
# graph are all 拡張用 / 欠番 / 空き部屋 placeholders with no collision data
# behind them, so a session can never stand on one; if such an id ever does
# reach a log line, "?" says more than a name would.
MAP_NAMES = {
    map_id: entry["name"]
    for map_id, entry in mapgraph.GRAPH.items()
    if entry.get("name")
}

# How long one cell of walking takes, in the client's clock units, which look
# like milliseconds. This is a guess and the first thing to tune: too small and
# characters will snap to the destination, too large and they will crawl.
MOVE_MS_PER_CELL = 300

# Notifications: the client tells us something and expects nothing back, so
# these are logged without the "no reply implemented" complaint.
# Client-initiated messages that belong to the drama flow but live outside the
# 0xE0xx block; see script.py for what each one is and how sure we are.
DRAMA_DOORS = {
    script.MSG_CL_QUERY_DRAMAEVENT_MATCHING_POSSIBLE,
    script.MSG_CL_QUERY_CHARA_MENU_DRAMA_EVENT_LIST,
    script.MSG_CL_REQUEST_NPC_MAP_OBJECT_EVENT,
    script.MSG_CL_REQUEST_NPC_MAP_OBJECT_MENU,
    script.MSG_CL_REQUEST_NPC_EVENT_START,
    script.MSG_CL_REQUEST_NPC_EVENT_END,
    script.MSG_CL_REQUEST_TITLE_EVENT_START,
    script.MSG_CL_REQUEST_TITLE_EVENT_END,
    script.MSG_CL_REQUEST_DRAMA_EVENT_START,
}

NOTIFICATIONS = {
    # ⚠️ 0x0020 MsgClNotifyAuthCode is deliberately NOT here any more. It is
    # still a notify and still gets no reply, but it is the only thing the game
    # and school connections say about which account they are, so it has a
    # handler of its own now. Putting it back would silently un-name every
    # connection past the login port.
    0x0100,  # MsgClNotifyGameServerLogout
    0x7100,  # MsgClNotifyLoginServerLogout
    # MsgClNotifyPlayerActivity. Never seen until round 32: it starts the moment
    # MsgSvNotifyScriptStart goes out and then repeats every 5 seconds for as
    # long as the scenario sequencer is the current one. Zero parameters, and it
    # keeps its cadence whatever we answer, so it is a heartbeat rather than a
    # request — it is in this list to stop it filling the log with "no reply
    # implemented", not because anything was proven about what it wants.
    0xA000,
}

# MsgSvResultSchoolList is the one list that has to be non-empty: the school
# select screen is where the client currently stops. Both the text writer
# (0x8F72F0) and the text parser (0x8F8680) agree on the shape — ``u16 count``
# then one ``u16 | u16`` pair per school, held in the message at +4 with stride
# 4 and the count at +0x40. The two fields are unnamed in the trace, so the
# first one is the school id: sending the ten real ids from
# reference/idlist/school.txt made the select screen show the ten real names
# (which are not on the wire — the client looks them up in its own school.bin),
# and picking the first one sent back MsgClRequestSchoolSelect with 0x0001.
#
# The second u16 is the student count, though proving it took two tries.
# 現在の生徒数 never prints a number: the client buckets the value through
# reference/idlist/student_num_scale.txt,
# whose four records carry [min, max] as little-endian u16 pairs in their
# trailing bytes and tile the range end to end:
#
#     0 生徒募集中        0 - 1999
#     1 まだまだ募集中  2000 - 3999
#     2 あと少しで定員  4000 - 4899
#     3 定員入学済      4900 - 5000   (5000 = 定員)
#
# So 0 and 101 look identical on screen, which is why a first attempt at
# 101..110 proved nothing at all. The values below straddle every boundary
# instead, and that settled it: school 3 (2000) and school 4 (3999) came up
# まだまだ募集中 while school 5 (4000) came up あと少しで定員, so the bucket
# flips exactly where the table says and the field is the count.
#
# The probe values that proved it are gone now; every school sits at zero, which
# is both honest for a one-player server and the safe bucket. Parking a school on
# 定員入学済 was never tested against whether it can still be picked.
SCHOOLS = tuple((school_id, 0) for school_id in range(1, 11))


def school_list_params() -> bytes:
    body = struct.pack(">H", len(SCHOOLS))
    for school_id, students in SCHOOLS:
        body += struct.pack(">HH", school_id, students)
    return body


# Where a successful login sends the client next. It speaks the same packet
# layer as 25573, so the same server class serves it.
GAME_PORT = 25574
# And where picking a school sends it after that — the client puts up
# 「学校に接続しています」, so this is a third connection, not a reuse of 25574.
SCHOOL_PORT = 25575


# Both of these are round-tripped by the client and neither is checked by it,
# which was measured rather than assumed: setting them to 0x0BADC0DE and 4242
# for one login left the whole flow — login, school select, character list,
# school login — unchanged, and both values came straight back, the authCode in
# MsgClNotifyAuthCode and the accountId in MsgClRequestGameServerLogin's
# `version[12+1]={%c}accountId=%d` tail. So they are ours to choose.
#
# Which is what keeps players apart now: the client never names its account
# after the login message — MsgClQueryCharacterListFromAccount goes out with no
# parameters at all — so the game and school connections are told which account
# they are by being handed an authCode and echoing it back. accounts.TicketDesk
# mints them; 0x0020 is the first message on those connections and 0x0200 is the
# second, so a connection knows itself before it can ask anything.
#
# These two are what an unnamed connection falls back to, and they are only
# reachable when something asks a character question before saying who it is.
FALLBACK_AUTH_CODE = 0x1234ABCD
FALLBACK_ACCOUNT_ID = accounts.FIRST_ACCOUNT_ID


def _peer_host(peer) -> str | None:
    """The host out of get_extra_info("peername"), stripped of the v6 prefix."""
    host = str(peer[0]) if isinstance(peer, tuple) and peer else None
    if host and host.startswith("::ffff:"):
        host = host[len("::ffff:") :]
    return host


def _is_loopback(host: str | None) -> bool:
    """Is this the machine the server is on? None (peer not recorded) is not."""
    return bool(host) and (host.startswith("127.") or host in ("::1", "localhost"))


def _season() -> int | None:
    """`script.SEASON_SOURCE` resolved to a season, or None to leave it alone.

    ⚠️ None is the shipped behaviour and it is not the same as 冬: it means the
    shadow never touches the register, so whichever constant the script writes
    into itself is the one the switch sees.
    """
    source = script.SEASON_SOURCE
    if isinstance(source, int):
        return source
    return curriculum.season() if source == "clock" else None


def ok_login_params(
    host_be: int = 0x0100007F,
    port: int = GAME_PORT,
    auth_code: int = FALLBACK_AUTH_CODE,
    account_id: int = FALLBACK_ACCOUNT_ID,
) -> bytes:
    """Build MsgSvOkLoginServerLogin's parameters.

    The client's own trace names every field::

        paramSize=0, relay_server_auth={ip=16777343, port=25574, authCode=0},
        accountId=0, accountType=0

    so the layout is u16 paramSize, then the relay ticket (u32 ip, u16 port,
    u32 authCode), then u32 accountId and u8 accountType. The address is stored
    the way inet_addr() keeps it, so 127.0.0.1 is 0x0100007F. The client hands
    authCode straight back to the game server as MsgClNotifyAuthCode, which is
    how the connection it opens there gets an account.
    """
    return struct.pack(">HIHIIB", 0, host_be, port, auth_code, account_id, 0)


def ng_login_params(reason: int) -> bytes:
    """Build MsgSvNgLoginServerLogin's parameters: the refusal, and why.

    ⚠️ The reason is one byte but the message is three, and the two in front of
    it are not optional. Input_MsgSvNgLoginServerLogin::deserialize (0x8F5780)
    reads a u16 into the object at +4 and only then the reason byte at +6 --
    paramSize is a field of the parameter block, the same leading zero that
    ok_login_params packs. Sending the reason on its own puts it where paramSize
    belongs and the client never builds the message at all: no error, no
    disconnection, the login screen simply keeps saying 「接続処理を行っています」
    until it is closed. Measured; it cost a round trip to find.
    """
    return struct.pack(">HB", 0, reason)


def ok_school_select_params(
    host_be: int = 0x0100007F,
    port: int = SCHOOL_PORT,
    auth_code: int = FALLBACK_AUTH_CODE,
) -> bytes:
    """Build MsgSvOkSchoolSelect's parameters.

    Output_MsgSvOkSchoolSelect::serialize (0x8F7470) writes u32, u16, u32 —
    the same shape as the relay ticket inside MsgSvOkLoginServerLogin, and the
    screen it drives (「学校に接続しています」) wants exactly that: address, port
    and the authCode the client will echo back as MsgClNotifyAuthCode.
    """
    return struct.pack(">IHI", host_be, port, auth_code)


def timesync_reply(request: bytes, first: bool) -> bytes:
    """Answer the client's tag-8 clock probe.

    0xA47EB0 parses the reply as ``u32 | u16 | u16 flag | u64 t1 | u64 t2 |
    u64 t3`` and computes ``offset = ((t2 - t1) + (t3 - t4)) / 2`` against its
    own clock t4, i.e. plain NTP with t1 echoed from the request. Reporting
    t2 = t3 = t1 declares the server clock identical to the client's, which is
    what we want locally: the offset then works out to half the round trip
    regardless of what the client's timebase actually is.

    ``flag`` 0 makes the client adopt the offset unconditionally and clear its
    round-trip history; anything else makes it accept the sample only when the
    delay is within a second of the running average, so only the first exchange
    is marked as a reset.

    0xA47DF0 reads its six fields straight from the packet cursor, which still
    sits at the very start: the ``u32`` and first ``u16`` it takes before the
    flag are the connection's 4-byte receive header and the tag itself, both of
    which packet() writes. Only the flag and the three timestamps belong here —
    26 bytes, for a 32-byte packet in total.
    """
    t1 = request[:8].rjust(8, b"\x00")
    return struct.pack(">H", 0 if first else 1) + t1 * 3


def checksum(data: bytes) -> int:
    """MPS body checksum (0xA4B9A0): xor of little-endian dwords, then fold."""
    acc = 0
    full = len(data) // 4 * 4
    for i in range(0, full, 4):
        acc ^= struct.unpack_from("<I", data, i)[0]
    for i in range(full, len(data)):
        acc ^= data[i]
    return ((acc >> 16) ^ acc) & 0xFFFF


def packet(tag: int, body: bytes, header: bytes = b"") -> bytes:
    """Frame one packet: ``u16 PS | header | u16 TAG | body``, PS covering all
    but its own two bytes.

    ``header`` is the per-connection receive prefix the client skips before
    reading the tag: every tag check (0xA47EB0 for 8, 0xA47100 for 9) reads the
    tag at ``cursor + *(u16*)(conn+0x1CA)`` without advancing, and 0xA460B0 does
    ``cursor += *(u16*)(ctx+0x12)`` before its own read. That field is zero on
    the login connection but 4 on the game connection, so the first packet the
    game server sent without it had its tag read 4 bytes early — the RCV probe
    caught ``t=0000`` with the cursor at base+6 instead of base+2, and a tag
    that is not 0x30 makes the client drop the stream without a word.

    The key exchange is the exception and must be sent with no header at all:
    0xA45D30 drives those packets itself and reads the tag with 0xA46A60 right
    at the cursor, without consulting the skip. Sending 0x35 with a header made
    it read 0x0000 instead of 0x35 and drop the connection before the cipher was
    ever invoked.

    The client's own packets carry no such prefix in either direction, matching
    the constructor at 0xA46F32: of the three u16s there only 0x1CA, the receive
    skip, is ever set to something else (0xA47055).
    """
    return struct.pack(">H", len(header) + 2 + len(body)) + header + struct.pack(">H", tag) + body


def parse_packets(buf: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
    out: list[tuple[int, bytes]] = []
    while len(buf) >= 4:
        size = struct.unpack_from(">H", buf, 0)[0]
        if len(buf) < 2 + size:
            break
        tag = struct.unpack_from(">H", buf, 2)[0]
        out.append((tag, buf[4 : 2 + size]))
        buf = buf[2 + size :]
    return out, buf


def _seal(body: bytes) -> bytes:
    """Prefix the checksum, then zero-pad to an 8-byte multiple.

    ``decipher`` (0xA4B300) rejects any length that is not a multiple of 8
    outright — the client logs ``exchange_key_phase3: illegal param2`` — while
    the checksum covers only the logical body, since the sender computes it
    before ``encipher`` applies the same padding.
    """
    sealed = struct.pack(">H", checksum(body)) + body
    return sealed + b"\x00" * (-len(sealed) % 8)


def kex1_body(key: bytes, sequence: int) -> bytes:
    return _seal(struct.pack(">H", len(key)) + key + struct.pack(">I", sequence))


def kex2_body(client_key: bytes, server_key: bytes, sequence: int) -> bytes:
    return _seal(
        struct.pack(">H", len(client_key))
        + client_key
        + struct.pack(">H", len(server_key))
        + server_key
        + struct.pack(">I", sequence)
    )


def parse_kex1(body: bytes) -> tuple[bytes, int]:
    """Return the client's key and starting sequence from a 0x34 body."""
    if len(body) < 8:
        raise ValueError(f"kex1 too short: {len(body)}B")
    if struct.unpack_from(">H", body, 0)[0] != checksum(body[2:]):
        raise ValueError("kex1 checksum mismatch")
    keylen = struct.unpack_from(">H", body, 2)[0]
    if len(body) < 4 + keylen + 4:
        raise ValueError(f"kex1 keylen {keylen} exceeds {len(body)}B body")
    key = body[4 : 4 + keylen]
    sequence = struct.unpack_from(">I", body, 4 + keylen)[0]
    return key, sequence


def parse_kex3(body: bytes) -> tuple[bytes, int]:
    """Return (echoed server key, sequence) from a 0x36 body.

    phase3's output only carries the peer's key back; the two-blob shape belongs
    to the 0x35 direction.
    """
    want = struct.unpack_from(">H", body, 0)[0]
    keylen = struct.unpack_from(">H", body, 2)[0]
    # Observed traffic checksums only through the key; phase1 covers the
    # trailing sequence as well. Accept either rather than reject the peer.
    if want not in (checksum(body[2 : 4 + keylen]), checksum(body[2 : 8 + keylen])):
        raise ValueError(f"checksum mismatch (keylen {keylen}, body {len(body)}B)")
    return body[4 : 4 + keylen], struct.unpack_from(">I", body, 4 + keylen)[0]


def parse_message(body: bytes) -> tuple[int, int, bytes]:
    """Unwrap a tag-0x30 body into (sequence, message type, parameters).

    Layout: ``u16 checksum | u32 sequence | u16 datalen | data | zero padding``,
    the checksum covering the sequence through the end of ``data``.

    ``data`` is ``u16 PT | params``. The 4 extra bytes that server-to-client
    messages carry between the two (see ``message_body``) are absent in this
    direction: the client's version report arrives as PT followed straight by the
    "00.01.13.00" string.
    """
    want, sequence, datalen = struct.unpack_from(">HIH", body, 0)
    logical = 8 + datalen
    if want != checksum(body[2:logical]):
        raise ValueError(f"checksum mismatch over {logical}B of {len(body)}B")
    data = body[8:logical]
    return sequence, struct.unpack_from(">H", data, 0)[0], data[2:]


def message_body(sequence: int, msg_type: int, params: bytes = b"", header: bytes = b"") -> bytes:
    """Wrap a server-to-client message.

    ``header`` is the same per-connection receive skip that packet() puts before
    the tag, because the client applies it a second time to the deciphered
    payload: decipher_message (0xA4C4D0) copies out exactly ``data``, and its
    caller then reads the message type at ``data[skip]`` — 0xA461C7 tests that
    u16 against 0x31, the fragment-continuation type. Without the leading bytes
    the game connection deciphered MsgSvOkGameServerLogin fine (the DEC probe
    fired, and none of decipher_message's three rejections were logged) and then
    read its type from four bytes too early, so the message object was never
    built and no MSG probe line appeared.

    The parameter block, on the other hand, always starts at a fixed ``data+6``
    — the skip is *not* applied to it. 0xA4B770 builds the parameter stream over
    the whole message body and seeks to a stored offset, and that offset does not
    depend on the connection. So the prologue is 6 bytes wide on both sides: the
    login connection lays it out as ``u16 type | u32 0`` and the game connection
    as ``u32 0 | u16 type``, and either way the parameters follow at 6.

    Round 6 is what pinned this down. MsgSvResultSchoolList went out with
    ``count=2``, four bytes into the parameter block, and the client's own trace
    still printed ``info[0]={}`` — it had read the count out of the zero gap.
    """
    pad = 6 - len(header) - 2
    if pad < 0:
        raise ValueError(f"header {len(header)}B leaves no room for the message type")
    data = header + struct.pack(">H", msg_type) + b"\x00" * pad + params
    return _seal(struct.pack(">IH", sequence, len(data)) + data)


class _Session:
    """Per-connection state.

    The sequence counter is deliberately shared by every connection of the
    process: decipher_message (0xA4C4D0) keeps the last sequence it accepted in
    the cipher manager and drops anything not strictly greater with "bad
    sequence number", and it is not obvious that the client resets that counter
    when it hops from the login server to the game server. Counting up across
    the whole session satisfies the check either way.
    """

    _next_seq = 100

    def __init__(self) -> None:
        self.client_key = b""
        # The three cipher modules mpsCipherManager keeps, from our side of the
        # wire. ``kex`` is the bootstrap-keyed one every connection starts with
        # and is used for nothing but the 0x34/0x35/0x36 bodies; the other two
        # are installed by the exchange and carry the messages afterwards. Each
        # connection re-runs the whole thing, so none of this is shared.
        self.kex_cipher = mps_cipher.Blowfish(mps_cipher.BOOTSTRAP_KEY)
        self.server_key = secrets.token_bytes(SERVER_KEY_LEN)
        self.in_cipher: mps_cipher.Blowfish | None = None
        self.out_cipher: mps_cipher.Blowfish | None = None
        self.syncs = 0
        # Which account this connection is, and its characters. Both stay unset
        # until the connection names itself -- with a registration code on the
        # login port, or by echoing an authCode on the game and school ports.
        # ⚠️ None is not "account 1": a store handed out before the connection
        # said who it was would answer every question plausibly and wrongly,
        # which is worse than answering nothing. See MpsServer._chars.
        self.account_id = 0
        self.characters: CharacterStore | None = None
        # This connection's socket, so that a message can be sent to a player
        # who did not ask for anything. Everything else in this server answers
        # the packet it is handling and hands the bytes back to the loop; a room
        # with two people in it is the first thing that cannot -- see
        # MpsServer._push. None until handle() has the writer.
        self.writer: "asyncio.StreamWriter | None" = None
        # The host at the other end of this connection, so that the account-1
        # fallback in _chars can tell a local client apart from a stranger. Set
        # in handle(); None until then, which _chars reads as "not local".
        self.peer_host: str | None = None
        self.chara_id = 0  # whoever MsgClRequestSchoolLogin named, 0 before 登校
        # When 登校 happened, by the monotonic clock; 0.0 = not at school.
        # 累計登校時間 on the 経歴 card is the sum of the spans this opens, so
        # every path that ends one has to close it -- 下校 and the disconnect
        # teardown both do. See MpsServer._career_depart.
        self.arrived_at = 0.0
        # 授業の鐘. Not saved with the character: a bell is a moment, and one
        # that rang while nobody was logged in is not owed to anyone afterwards.
        # It stays quiet until 登校 primes it — see the school-login handler.
        self.bell = lesson.Bell()
        # The period actually in progress, once 0x6100 has gone out. Not saved,
        # for the same reason: ten questions half answered are not owed to
        # anybody, and the original ends a lesson you walk out of too.
        self.lesson: lesson.Lesson | None = None
        # 試験期間, and the paper in progress inside it. Not saved either, and
        # for a third reason on top of the two above: the period is this
        # server's invention (there is no calendar in the client's data), so a
        # period that outlived a restart would need an end date to invent too.
        self.exam = exam.Period()
        # どの組に在籍しているか. Ａ組 until something sets it, which is also
        # what MsgSvResultScoreCard's inClass has been sending all along. It
        # decides the room a lesson happens in, via curriculum.CLASSROOM.
        self.in_class = 0
        self.warp_index = -1  # -1 = still at the spawn point, no warp sent yet
        # Which map the player is on. Cell coordinates are only meaningful
        # alongside this: MsgClRequestCharaWarp names a target map and a position
        # inside it, and the lobby reload that follows has to re-add the
        # character there rather than at the same numbers on 屋外.
        self.map_id = SPAWN_MAP_ID
        # Where the player is, in the isometric cell coordinates the wire uses.
        # It starts at the spawn point and is only as current as the last
        # MsgClCastCharaMove: the client walks on its own and reports after the
        # fact, so this trails a step behind rather than driving anything.
        self.pos = SPAWN_POS
        # Which way the character is turned. Kept up to date from two places:
        # the client's own turn casts, and the direction a walk ended up going.
        self.direction = facing.DEFAULT
        # 休憩: whether the player is sitting, and since when by the monotonic
        # clock. Not saved — a pose is a moment, like a bell, and a character
        # who logs out sitting has stopped sitting. ``sat_at`` doubles as the
        # accounting cursor: recovery consumes seconds off it rather than
        # resetting it, so the remainder that was not worth a whole point stays
        # on the clock instead of being thrown away every drain.
        self.pose = stress.POSE_STANDING
        self.sat_at = 0.0
        # The last stress/condition this session actually pushed, so the two
        # notifies go out on change rather than on every packet. -1 is "nothing
        # sent yet", which is not the same as 0: 0 is a real reading and the
        # client has to be told about it to take the bar away.
        self.sent_stress = -1
        self.sent_condition = -1
        # The markers standing in the scene, cached so the lobby's stand-ins and
        # the answers to MsgClQueryCharaInfo about them cannot disagree. Warping
        # changes the map, so this is rebuilt rather than computed once.
        self._markers: tuple[tuple[str, int, int], ...] = ()
        self._markers_map = -1
        # 友達登録 applications this session has out, by the charaId they were
        # sent to, and the ones sent *to* it. Per session and not saved: an
        # application is a question somebody is standing there waiting on, and a
        # player who logs out has stopped waiting. The two sets are kept apart
        # because the messages are -- 0x640A withdraws one of the first kind and
        # 0x6407/0x6408 answer one of the second.
        self.friends_asked: set[int] = set()
        self.friends_asking: set[int] = set()
        # 仲良しグループ 勧誘, the same idea one size smaller: 0x621C/0x621D/0x621F
        # carry no charaId, so a session can be one end of at most one invite at
        # a time and a set would be answering a question the wire cannot ask.
        # ``group_invited`` is whom this session has invited, ``group_inviter``
        # is who invited it.
        self.group_invited: int | None = None
        self.group_inviter: int | None = None
        # 引継 is the same handshake one field wider (0x620D carries a comment
        # as well as the id) and is held the same way, in its own pair: a
        # character can be one end of an invite and one end of a handover at
        # once, and 0x6211/0x6212/0x6214 are as id-less as 0x621C/0x621D/0x621F.
        # ``group_handover_to`` is the member this leader has offered the group
        # to, ``group_handover_from`` is the leader who offered it.
        self.group_handover_to: int | None = None
        self.group_handover_from: int | None = None
        # The client's own clock, as of the last tag-8 probe, plus when that
        # arrived by our monotonic clock. MsgSvNotifyCharaMove has to state an
        # arrivalTime on the client's timebase, and the tag-8 exchange is the
        # only clock the protocol has — which is what it exists for. Observed
        # values look like milliseconds since the client started (0x7533 ≈ 30 s
        # into a run), and timesync_reply already declares the two clocks equal.
        self.clock_t1 = 0
        self.clock_at = 0.0
        # The script this session is playing, if any. See script.py.
        self.script: script.Runner | None = None
        # What the next MsgSvQueryScriptCommandSelect carries, or None to let
        # the script's own option count decide. /sel overrides it; per-session
        # for the same reason /nev is, and because the meaning of `select` is
        # exactly the thing one login is meant to settle.
        self.select_override: tuple[int, int] | None = None
        # Which capture_npc_event key we hand back when the player talks to a
        # chibi. Per-session rather than global so that /nev can be tried
        # against a running client without a restart; see script.py.
        self.npc_event: tuple[int, int] = script.DEFAULT_NPC_EVENT
        # Which sub_menu.bin key we hand back when a type 1 menu item is picked
        # off a map object. Per-session for the same reason npc_event is: the
        # whole point of the knob is to try one key against a running client and
        # then the next; see script.DEFAULT_SUB_MENU and /smenu.
        self.sub_menu: int = script.DEFAULT_SUB_MENU
        # How 0x5603 MsgClRequestNpcEventEnd is answered. "auto" is the factory
        # behaviour and what every round before 160 did: the bare Ok, straight
        # away. "manual" logs the request and answers nothing, which hands the
        # whole teardown to /raw -- the only way to try an order other than
        # "Ok first" without spending a login per ordering. See /evend.
        # ⚠️ A knob whose default is the factory value, so forgetting to put it
        # back cannot leave a changed server behind.
        self.npc_event_end: str = "auto"
        # MsgSvNotifyNpcControl bodies /npc has pushed, so that a map reload can
        # put the same chibis back. Bodies rather than parsed pairs: nothing
        # here needs to read them, only to send them again.
        self.npc_spawns: list[bytes] = []
        # The capture_npc_event key of the conversation currently running,
        # or None when the script on air was started some other way. Only set by
        # the NPC_EVENT_START branch, so that /sc-ing a conversation script by
        # hand does not count as having talked to anybody.
        self.talking_about: tuple[int, int] | None = None
        # Which line the player clicked in that conversation, or None if it
        # never asked or never got an answer. Lives here rather than on the
        # Runner because all four NotifyScriptEnd paths drop the Runner before
        # crediting, and this is the number the credit needs; _script_start
        # clears it so a click cannot carry into the next script.
        self.talking_choice: int | None = None
        # Chat lines that must wait for the map to come back. A NotifyScriptEnd
        # is followed by the client tearing the event screen down and reloading
        # the lobby, and anything said in that window is simply gone — the packet
        # goes out (it is in the log, seq 137 of round 42) and no line appears.
        # The lines already in the bar survive the cutscene, so this is not the
        # window being cleared; it is not listening yet.
        self.pending_say: list[str] = []
        # Set when the reload's last message arrives, cleared when the queue is
        # flushed on the packet after that. See _drain_pending_say.
        self.say_armed = False
        # How far into runtime/console.txt this session has read. See
        # MpsServer._drain_console; the file is append-only from our side, so an
        # offset is all the bookkeeping it needs.
        self.console_at = 0
        # When the クラブ対戦 turn this connection is in stops taking commands,
        # by the monotonic clock; 0.0 when there is no turn open. It lives here
        # rather than on the Battle because next_wake is what the socket waits
        # on and next_wake is a session's own question. The Battle holds the
        # same moment for the resolution itself — see clubbattle.Battle.
        self.battle_due = 0.0

    def note_clock(self, t1: int) -> None:
        self.clock_t1 = t1
        self.clock_at = time.monotonic()

    def client_now(self) -> int:
        """Best estimate of the client's clock right now, in its own units."""
        if not self.clock_at:
            return 0
        return self.clock_t1 + int((time.monotonic() - self.clock_at) * 1000)

    def next_wake(self) -> float | None:
        """Seconds until something is due to be pushed, or None if nothing is.

        Everything else this server sends is either an answer or rides on an
        arriving packet, and the timesync every thirty seconds has been a good
        enough heartbeat for all of it: a bell that is up to half a minute late
        against a fifteen-minute period is not a bell anyone can catch out.

        A question's 残り時間 is different in kind. The client counts it down on
        screen from the endTime the server named, and 「残り時間が０になると正解が
        発表され」 — so the reveal has a moment, the player is watching it arrive,
        and being thirty seconds late is the difference between a lesson and a
        hang. Hence a real deadline; see MpsServer.handle, which waits on the
        socket for exactly this long instead of the idle timeout.
        """
        due = None
        if self.lesson is not None and not self.lesson.finished():
            due = self.lesson.due
        # An exam's ten minutes are the same kind of deadline for the same
        # reason: the client draws the 制限時間 counting down and 0x6A03 has to
        # arrive when it reaches zero, not on the next timesync.
        paper = self.exam.paper
        if paper is not None and not paper.called:
            due = paper.due if due is None else min(due, paper.due)
        seconds = None if due is None else (due - datetime.now()).total_seconds()
        # ⭐ A クラブ対戦 turn is the third of the same kind, and the manual is
        # explicit about it (p07_03): 「０になる前に入力を完了できなかった場合、
        # キャラクターは行動しません」 — the client draws 「あと N 秒」, closes
        # its command window at zero and then waits for the server to move the
        # round along. Being late here is not a late bell, it is a hung fight.
        #
        # ⚠️ Monotonic rather than a datetime, because that is the clock the
        # deadline was set on; mixing the two would put the fight's timing at
        # the mercy of the wall clock.
        if self.battle_due:
            left = max(0.0, self.battle_due - time.monotonic())
            seconds = left if seconds is None else min(seconds, left)
        return seconds

    def markers(self) -> tuple[tuple[str, int, int], ...]:
        """The stand-ins for the current map, computed once per map change.

        Empty in normal play — both switches behind it are off, and the scene is
        the player alone. The machinery stays because putting a labelled batch of
        stand-ins on the ground is this project's one reliable way to ask the
        client a question and read the answer off a single screenshot.
        """
        if self._markers_map != self.map_id:
            self._markers_map = self.map_id
            self._markers = door_markers(self.map_id) if MARK_DOORS else PROBE_POSITIONS
        return self._markers

    def next_warp(self) -> tuple[str, int, int]:
        """Step to the next entry of WARP_SWEEP, wrapping so it can be recycled."""
        self.warp_index = (self.warp_index + 1) % len(WARP_SWEEP)
        return WARP_SWEEP[self.warp_index]

    def take_seq(self, seen: int = 0) -> int:
        _Session._next_seq = max(_Session._next_seq, seen) + 1
        return _Session._next_seq


class MpsServer:
    """Serves the tagged MPS packet layer: key exchange, then messages.

    Both the login server (25573) and the game server it redirects to speak this
    protocol, so one class covers both. Messages without a reply are logged
    rather than answered; with the identity cipher they arrive as plaintext, so
    the log is enough to work out each layout before implementing it.
    """

    def __init__(
        self,
        root: Path,
        config: ServiceConfig,
        name: str = "mps",
        header_size: int = 0,
        accountstore: "accounts.AccountStore | None" = None,
        tickets: "accounts.TicketDesk | None" = None,
        tokens: "konami_id.TokenDesk | None" = None,
        advertise_ip: str = "127.0.0.1",
    ) -> None:
        self.root = root
        self.config = config
        self.conn_seq = 0
        # Where this server tells the client to go next. It has to be an address
        # the *client* can reach, which is not necessarily one this machine can
        # name for itself: behind NAT it is the public address, not the private
        # one the socket is bound to. So it is configured, never guessed from
        # the connection.
        self.advertise_ip = advertise_ip
        self.advertise_host_be = inet_u32(advertise_ip)
        # Shared with the other ports when run_all.py passes them in, and they
        # have to be: the client creates a character on the school server, may
        # ask any connection for the list, and hops between the three ports
        # carrying an authCode that only means something if all three read the
        # same desk.
        self.accounts = accountstore or accounts.AccountStore(root)
        self.tickets = tickets or accounts.TicketDesk()
        # Minted by the auth service on the HTTPS connection and redeemed
        # here, so this is the same object those servers hold or the token
        # the client carries over means nothing.
        self.tokens = tokens or konami_id.TokenDesk()
        # 自主トレルーム, held by the server rather than the session because a
        # room outlives whoever asks about it. Not persisted: a 看板 is up only
        # while its leader is logged in, and 0x580D reason 2 (切断による) is the
        # protocol saying so.
        self.trainingrooms = trainingroom.Board()
        # Fights in progress, opened by 0x5C06 and found by any participant.
        # Separate from the room board because a battle is not a room: 練習 and
        # フリー対戦 reach the same 0x5C** messages without one, and this server
        # only lacks those doors because it cannot place their NPCs yet.
        self.battles = clubbattle.Board()
        # Every connection currently up on this port. Kept so that a Notify can
        # find a player by charaId rather than only being able to answer the
        # connection it is standing on -- which is all a one-player server ever
        # needed. Per port on purpose: a room lives on the board of the port its
        # messages arrive at, and the sessions in it are on that same port.
        self.live: "list[_Session]" = []
        # Bytes to put before the tag on everything we send; see packet().
        self.header = b"\x00" * header_size
        runtime, self.packet_dir = ensure_runtime_dirs(root)
        # The out-of-band console; see _drain_console.
        self.console_path = runtime / "console.txt"
        self.tag = f"{name}{config.port}"
        # ⭐ The coin `_script_die` flips. A generator of its own rather than
        # the module one so that seeding it for a reproducible run cannot
        # reach anything else on this server.
        # ⚠️ Factory value is None -- a real coin. Set SCRIPT_DIE_SEED to an
        # int only to make one session repeatable, and note that it makes every
        # OP_RAND branch in that session fall the same way twice.
        self._script_dice = random.Random(SCRIPT_DIE_SEED)

    def _bind(self, session: "_Session", account_id: int, how: str) -> None:
        """Say which account this connection is, once it has named itself."""
        if session.account_id == account_id:
            return
        if session.account_id:
            # Two different accounts on one connection is not something the
            # client does, so it means a ticket was read wrong. Say so and take
            # the newer one, because the alternative -- keeping the old store
            # while the client believes it switched -- writes one player's
            # progress into another player's file.
            print(
                f"[{self.tag}] ⚠ connection was account {session.account_id}, "
                f"now says {account_id} ({how})"
            )
        session.account_id = account_id
        session.characters = self.accounts.characters(account_id)
        print(
            f"[{self.tag}] connection is account {account_id} ({how}); "
            f"characters: {session.characters.summary()}"
        )

    def _fallback_account(self, session: "_Session") -> int | None:
        """The account an unnamed connection may fall back to, or None.

        ⚠️⚠️ One decision, two callers: the character store (_chars) and the
        school-hop ticket (0x0303). Both used to fall back to account 1
        unconditionally, and on a public instance account 1 is the first
        registrant -- so a stranger who speaks the packet layer (its bootstrap
        key is a plaintext string, so anyone can) and skips the authCode landed
        on their save. Loopback keeps the single-player convenience; anyone else
        gets None, and each caller has its own harmless answer to that.

        In normal play neither caller reaches this: the client names its account
        first, with a registration code on the login port or an echoed authCode
        on the game and school ports.
        """
        if _is_loopback(session.peer_host):
            return FALLBACK_ACCOUNT_ID
        return None

    def _equip_replay(self, session: "_Session") -> bytes:
        """0x4D06 for everything this character is wearing, on entering a scene.

        ⭐⭐ NOTHING ELSE CAN CARRY IT. 0x4D03's rows are {categoryId, id, count}
        and have no room for a "worn" bit, so the tick in the window's 装備
        column and the clothes on the avatar are set by 0x4D06 and by nothing
        else. Measured twice: the client honoured an unsolicited 0x4D06 that
        took an item off a row it had not asked about, and -- the other half --
        after the server's worn list was emptied behind its back the window
        reopened with the tick still drawn, because the client was going by what
        it had last been told rather than by the list it had just been sent.
        Without this a relog would leave a dressed character drawn undressed and
        the column blank while the save still said otherwise.

        ⚠️ INVENTED THAT IT BELONGS HERE. The message is a Notify, i.e. built to
        report a change, and where the original put the *initial* state is not
        known -- the appearance block the create carries is the other candidate.
        Replaying at scene-build is the only route this server has, and it puts
        the player and the peers in the same pass.
        """
        inv = self._chars(session).items(session.chara_id)
        if inv is None or not inv.worn:
            return b""
        out = b""
        for category, item_id in inv.worn:
            params = item.equip_params(session.chara_id, category, item_id, 1)
            self._presence_relay(session, item.MSG_SV_NOTIFY_ITEM_EQUIP, params)
            out += self._answer(session, 0, item.MSG_SV_NOTIFY_ITEM_EQUIP, params)
        print(f"[{self.tag}] equip replay: charaId={session.chara_id} is wearing "
              + " ".join(f"{c}:{i}" for c, i in inv.worn))
        return out

    def _equip_replay_peers(
        self, session: "_Session", peers: "list[_Session]"
    ) -> bytes:
        """0x4D06 for what everybody ALREADY STANDING HERE is wearing.

        ⚠️⚠️ _equip_replay covers one direction only. It replays the entrant's
        own worn list and relays it to the peers, so a character who walks in
        arrives dressed on every screen that was already open -- but the screen
        that is being built right now is never told about anybody else's, and
        0x480F carries no worn bit to make up for it (see _equip_replay: this
        message and nothing else sets the clothes).

        ⭐ MEASURED round 148, A/B/A on two clients: a viewer who logged in
        while the other player stood there drew them bare-headed; the other
        player then re-entered and the ears appeared on that same screen; a
        fresh login by the viewer lost them again. So it is the entering
        client that is short of a message, not the record.

        ⚠️ Same invention boundary as _equip_replay -- that a scene build is
        where the initial state belongs is this server's route, not a restored
        one. What is restored is that only 0x4D06 can carry it.
        """
        out = b""
        dressed = []
        for other in peers:
            inv = self._chars(other).items(other.chara_id)
            if inv is None or not inv.worn:
                continue
            for category, item_id in inv.worn:
                out += self._answer(
                    session, 0, item.MSG_SV_NOTIFY_ITEM_EQUIP,
                    item.equip_params(other.chara_id, category, item_id, 1),
                )
            dressed.append(
                f"{other.chara_id}="
                + ",".join(f"{c}:{i}" for c, i in inv.worn)
            )
        if dressed:
            print(f"[{self.tag}] equip replay: charaId={session.chara_id} is "
                  f"shown " + " ".join(dressed))
        return out

    def _locker(self, session: "_Session") -> "item.Locker | None":
        """This connection's account's ロッカー, or None if it has no account.

        ⚠️ Goes through _chars first, and not as a formality: that is what binds
        a connection which has not named an account yet, and without it the
        locker would be looked up under account 0 and come back None for a
        connection whose characters resolve fine.
        """
        self._chars(session)
        return self.accounts.locker(session.account_id)

    def _chars(self, session: "_Session") -> CharacterStore:
        """This connection's characters; a detached empty store if it never said.

        See _fallback_account for the decision. A local connection falls back to
        account 1; a stranger gets a detached, empty store -- an empty list sends
        the client back to the school screen, and because the store is detached
        its writes go nowhere, so a create on an unnamed connection cannot touch
        a real account's file. Returning a store rather than None keeps every
        caller's ``_chars(session).xxx`` working instead of guarding forty of
        them.
        """
        if session.characters is None:
            account_id = self._fallback_account(session)
            if account_id is not None:
                print(
                    f"[{self.tag}] ⚠ character question before this connection "
                    f"named an account; local, so account {account_id}"
                )
                self._bind(session, account_id, "fallback")
            else:
                print(
                    f"[{self.tag}] ⚠ character question before this connection "
                    f"named an account, from {session.peer_host}; unnamed, "
                    "answering out of a detached empty store"
                )
                session.characters = CharacterStore(None)
        return session.characters

    def _packet(self, session: "_Session", tag: int, body: bytes) -> bytes:
        header = b"" if tag in (TAG_KEX1, TAG_KEX2, TAG_KEX3) else self.header
        return packet(tag, self._encipher(session, tag, body), header)

    @staticmethod
    def _encipher(session: "_Session", tag: int, body: bytes) -> bytes:
        """Apply the key this tag travels under. Tag 8 travels under none."""
        if tag in (TAG_KEX1, TAG_KEX2, TAG_KEX3):
            return session.kex_cipher.encipher(body)
        if tag == TAG_MESSAGE:
            if session.out_cipher is None:
                raise RuntimeError("message before the key exchange finished")
            return session.out_cipher.encipher(body)
        return body

    @staticmethod
    def _decipher(session: "_Session", tag: int, body: bytes) -> bytes:
        if tag in (TAG_KEX1, TAG_KEX2, TAG_KEX3):
            return session.kex_cipher.decipher(body)
        if tag == TAG_MESSAGE:
            if session.in_cipher is None:
                raise ValueError("message arrived before the key exchange finished")
            return session.in_cipher.decipher(body)
        return body

    def _answer(self, session: "_Session", seen: int, msg_type: int, params: bytes) -> bytes:
        send_seq = session.take_seq(seen)
        name = MESSAGE_NAMES.get(msg_type, "unknown")
        print(f"[{self.tag}] -> {name} (0x{msg_type:04x}) seq={send_seq} params={params.hex()}")
        return self._packet(
            session, TAG_MESSAGE, message_body(send_seq, msg_type, params, self.header)
        )

    def _session_of(self, chara_id: int) -> "_Session | None":
        """The live connection that 登校'd as this character, if it is still up.

        A charaId can name somebody who is not connected -- rooms are held by
        the board and a member's socket can go away -- so an absence here is
        ordinary and every caller has to expect it.
        """
        for other in self.live:
            if other.chara_id == chara_id:
                return other
        return None

    # ------------------------------------------------------------------
    # Presence: who else is standing on this map.
    #
    # Until round 71 the lobby only ever drew the player and the stand-ins, so
    # two people logged in at once could not see each other at all. That is not
    # a cosmetic gap: 自主トレ rooms are named by their leader's charaId and the
    # manual's only way in is 「ルームを作成したキャラクター（の頭上のアイコン）
    # を右クリック」, so a second player who cannot see the first has no way to
    # ask to join. The room family (0x58xx) was finished in round 67 and has
    # been waiting on this.
    # ------------------------------------------------------------------

    def _peers(self, session: "_Session") -> "list[_Session]":
        """Other 登校'd connections standing on the same map as this one.

        The map test is what keeps an indoor player out of an outdoor scene.
        There is no radius: 屋外 is one map and the client draws whatever it is
        handed, which is what the coordinate probes have been relying on since
        round 30.
        """
        return [
            other
            for other in self.live
            if other is not session
            and other.chara_id
            and other.map_id == session.map_id
            and other.writer is not None
            and not other.writer.is_closing()
        ]

    def _peer_chara(self, chara_id: int) -> "bytes | None":
        """Somebody else's character record, looked up in *their* store.

        Through accounts.owner_of rather than the live list, the same way
        _tr_names does it: the server holds an index from charaId to account, so
        this answers for a character whose owner has since logged out as well as
        for one standing on the map right now.
        """
        store = self.accounts.owner_of(chara_id)
        return store.find(chara_id) if store else None

    def _presence_entry(
        self, other: "_Session", action: "int | None" = None
    ) -> "bytes | None":
        """One 0x480F entry for somebody else, drawn where they are standing.

        Their record comes out of *their* CharacterStore, not the viewer's --
        accounts have separate stores (round 68), so looking a peer up in the
        viewer's store would find nothing at all.

        ⚠️ ``action`` overrides the icon byte and is FOR THE PROBE ONLY
        (``/cb presence … act=N``). It is not an invented value: the server puts
        ACTION_TRAINING_ROOM on this field for every room leader already, and
        the override only decouples 「which byte」 from 「who happens to lead a
        room right now」, which is what makes that byte testable at all -- see
        _battle_probe's presence branch.
        """
        info = self._chars(other).find(other.chara_id)
        if info is None:
            return None
        return add_entry(
            other.chara_id,
            info,
            pos=other.pos,
            map_id=other.map_id,
            direction=other.direction,
            action=self._presence_action(other) if action is None else action,
            # ⭐ The 仲良しグループ this character is in, and the PC menu's
            # 「グループ登録申込み」 reads it off this entry rather than off
            # 0x6501 -- round 150 saw the invite offered between two members of
            # the same group because this field was NO_GROUP for everybody.
            group_id=self.accounts.groups.id_of(other.chara_id),
        )

    def _presence_action(self, other: "_Session") -> int:
        """The icon to draw over this character's head.

        Which byte draws which picture is recovered (see the constants). What
        this server puts up is three of them:

        * 授業中 while a period is running. `p05_08`: 「授業中のマップキャラの
          頭上に表示されます」 -- the character keeps standing on the map while
          its owner is in the lesson scene, and until round 150 it stood there
          with nothing over its head, which reads as idling.
        * クラブ活動中 while a fight is on. `p05_09` counts 自主トレ as クラブ
          活動 for ストレス, and the same word names this icon.
        * 自主トレ募集中 for a room leader, and it has to be there: the manual's
          only way into somebody else\'s room is 「ルームを作成したキャラクター
          の頭上のアイコン」を右クリック. ⚠️ That 10 was settled twice over --
          the ruler draws a figure lifting weights, and the client offers 参加
          only when this byte is set.

        ⚠️ INVENTED: the order. Nothing says which icon wins when two apply, and
        as written a lesson beats a fight beats a room. Nobody can be in two of
        these at once today, so the ordering has never been exercised; what
        would overturn it is a manual line or a capture showing a different one
        on a character who qualifies for two.
        """
        if other.lesson is not None:
            return ACTION_LESSON
        if self.battles.battle_of(other.chara_id) is not None:
            return ACTION_CLUB_ACTIVITY
        room = self.trainingrooms.rooms.get(other.chara_id)
        return ACTION_TRAINING_ROOM if room is not None else ACTION_NONE

    def _presence_blocked(
        self, session: "_Session", also: "set[int] | None" = None
    ) -> "set[int]":
        """charaIds a 0x4810+0x480F pair must not reach right now.

        The pair edits the map scene, and round 96 measured what happens when it
        arrives at a client that has a different screen up: the 結果画面 took
        one and closed the connection. So it goes only to peers who are looking
        at the map -- not to somebody sitting in a lesson, not to somebody in a
        fight, and not to whatever extra ids the caller knows about (the fighters
        on a 結果画面 are exactly that case: the board has already forgotten the
        fight by the time their screen catches up).
        """
        blocked = set(also or ())
        for peer in self._peers(session):
            if peer.lesson is not None:
                blocked.add(peer.chara_id)
            elif self.battles.battle_of(peer.chara_id) is not None:
                blocked.add(peer.chara_id)
        return blocked

    def _presence_refresh_onlookers(
        self, session: "_Session", also: "set[int] | None" = None
    ) -> None:
        """Redraw this character for everybody whose map scene is actually up."""
        self._presence_refresh(session, skip=self._presence_blocked(session, also))

    def _presence_refresh(
        self, session: "_Session", skip: "set[int] | None" = None
    ) -> None:
        """Redraw this character on everybody else\'s screen.

        Delete then add, because 0x480F is an *add*: round 67 measured what the
        room roster does when the same row arrives twice (it counted the person
        twice) and there is no reason to expect the scene to be kinder. The
        client is told to drop somebody it can see and is immediately handed
        them back, which is the same pair of messages a warp out and back in
        would produce.

        ⚠️⚠️ ``skip`` names charaIds this pair must NOT reach, and it exists
        because one of them is fatal: a client sitting on the 結果画面 that is
        handed 0x4810 + 0x480F closes the connection and draws
        「通信が断たれました」 (measured round 96, three pairs, EOF right after).
        The scene those messages edit is not up while a fight is on screen.
        ⚠️ 0x4810 *alone* is survivable there — round 95 sent one down the
        disconnect path and the fight played on to turn 8 — so it is this pair,
        or the add half of it, and the two have not been separated.
        """
        peers = [
            peer for peer in self._peers(session)
            if skip is None or peer.chara_id not in skip
        ]
        if not peers:
            return
        self._presence_withdraw(session, peers)
        self._presence_announce(session, peers)

    def _presence_announce(
        self, session: "_Session", peers: "list[_Session] | None" = None,
        action: "int | None" = None,
    ) -> None:
        """Tell everybody else on the map that this character has appeared.

        Push-only and no sender copy: the client puts itself into the scene, and
        round 67 measured what a duplicate does -- the roster window counted the
        same person twice. Same rule as 0x580C.

        ⚠️ ``action`` is the probe-only icon override; see _presence_entry.
        """
        entry = self._presence_entry(session, action)
        if entry is None:
            return
        body = struct.pack(">H", 1) + entry
        for other in (self._peers(session) if peers is None else peers):
            self._push(
                other, self._answer(other, 0, MSG_SV_NOTIFY_CHARACTER_ADD, body)
            )
            print(
                f"[{self.tag}] presence: told charaId={other.chara_id} about "
                f"charaId={session.chara_id}"
            )

    def _presence_withdraw(self, session: "_Session", peers: "list[_Session]") -> None:
        """0x4810 to everybody who was told about this character.

        ``peers`` is passed in rather than recomputed because the caller is the
        disconnect path, which has to take the session out of ``self.live``
        before it starts telling people -- see the ordering note there.
        0x4810 is counted, 4B per entry (the frozen shape dump).
        """
        body = struct.pack(">HI", 1, session.chara_id)
        for other in peers:
            self._push(
                other, self._answer(other, 0, MSG_SV_NOTIFY_CHARACTER_DEL, body)
            )
            print(
                f"[{self.tag}] presence: told charaId={other.chara_id} that "
                f"charaId={session.chara_id} is gone"
            )

    def _presence_relay(self, session: "_Session", msg_type: int, params: bytes) -> None:
        """Send a Notify this character just earned to everybody watching them.

        The handlers build these for the actor and return them as the reply; the
        same bytes go out to the peers unchanged, because every one of them
        carries the charaId it is about. Without this a peer is drawn once at
        the spot where they logged in and then never moves again.
        """
        for other in self._peers(session):
            self._push(other, self._answer(other, 0, msg_type, params))

    def _push(self, session: "_Session", blob: bytes) -> None:
        """Write bytes down a connection that did not ask for them.

        ⚠️ No ``drain()``: every handler from _reply down is synchronous and
        returns bytes for the packet loop to write, and making one of them a
        coroutine to await backpressure would turn the whole chain async for the
        sake of a Notify that is at most a few hundred bytes going to at most
        MAX_MEMBERS recipients. ``write()`` buffers and the loop flushes it.

        A closing socket is skipped rather than raising: the disconnect path
        broadcasts a 0x580D through here, so the connection that just went away
        can be the very thing being told about.
        """
        if not blob or session.writer is None or session.writer.is_closing():
            return
        write_packet_log(self.packet_dir, self.tag, "out", blob)
        session.writer.write(blob)
        print(f"[{self.tag}] -> {len(blob)}B (push): {blob.hex()}")

    # ------------------------------------------------------------------
    # The script subsystem (0x72xx). See server/script.py for the protocol and
    # for how little of it has been on the wire — which is: none of it.
    # ------------------------------------------------------------------

    def _say(self, session: "_Session", seen: int, line: str) -> bytes:
        """One server line in the chat bar, so the screen says what the log says."""
        return self._answer(
            session,
            seen,
            MSG_SV_NOTIFY_NORMAL_CHAT,
            chat.notify_params(session.chara_id, chat.SERVER_NAME, line),
        )

    def _drain_pending_say(self, session: "_Session") -> bytes:
        """Say everything that was queued while the chat bar was not listening.

        One condition, measured rather than reasoned: the line has to go out
        *behind MsgSvResultPoolMessage*, the last answer of the reload the client
        runs after a cutscene. Earlier than that and it vanishes — round 42 sent
        one straight after NotifyScriptEnd and watched a packet leave with no
        line appearing, twice.

        The arming flag looks like it buys a delay and does not: it is set while
        0xA100 is being handled and this runs at the end of the same packet, so
        the flush rides out with that very reply. That is what was observed to
        work, so it is what the code does; the flag is only here so the drain can
        sit in the packet loop and stay out of the handler.

        seen=0 for the same reason _drain_console uses it: these answer no
        message of their own.
        """
        if not (session.say_armed and session.pending_say):
            return b""
        session.say_armed = False
        lines, session.pending_say = session.pending_say, []
        return b"".join(self._say(session, 0, line) for line in lines)

    # ── the shadow VM ────────────────────────────────────────────────────
    #
    # ⭐ What it is: a second machine running the same scenario the client is
    # playing, one instruction run at a time, fed by the client's own progress
    # reports. It exists because the register file the scripts compute over was
    # this end's business all along (round 175) and this end has never had one:
    # every OP_BR has been answered with a shrug and every choice box offered
    # with every line on.
    #
    # ⚠️⚠️ What it is NOT, this round: an answer. Nothing below changes a byte
    # that goes out. `resolve_branch` still falls through, `select_query` still
    # sends every bit. All the shadow does is say, in the log, what it would
    # have answered -- next to what was actually sent and next to what ends up
    # on the screen.
    def _shadow_start(self, session: "_Session", script_id: int) -> None:
        """Arm a follower for the scenario about to play, if we have it.

        The cells come from the player's own 恋愛 record and nowhere else --
        every number in there is one the save already holds. Whatever a script
        asks for beyond that reads as ⊤ and is counted, which is the point:
        the log ends up naming the cells this end would have to be able to
        answer before any of this could decide anything.
        """
        runner = session.script
        if runner is None:
            return
        love = self._chars(session).romance(session.chara_id)
        cells = dict(love.data_cells()) if love else {}
        # ⭐ 自分のクラス. Not out of the 恋愛 record -- out of the same constant
        # the character list and 0x6501 put on the wire, which is the whole
        # point: the tutorial reads this cell to decide which classroom door to
        # walk the player to, and the select screen has already told the client
        # which 組 it is. Two ends answering the same question differently is
        # the failure this closes.
        # ⭐ Round 192 this became load-bearing rather than diagnostic: with the
        # road bounded properly (`gs3vm._decided_road`) the dispatch tree this
        # cell feeds is answerable, so the value here is what decides which
        # classroom door the tutorial walks the player to. Supply it wrong and
        # the walk goes to the wrong floor -- which is exactly what happened
        # while nobody supplied it at all.
        cells[("PC", script.PC_IN_CLASS)] = IN_CLASS
        runner.shadow = gs3vm.follow(script_id, cells)
        if runner.shadow is None:
            print(f"[{self.tag}] vm: id={script_id} is not in runtime/scripts "
                  f"— no shadow for this one")
            return
        runner.shadow.season = _season()
        register = runner.shadow.script.season_register
        if register is not None:
            # ⭐ Said out loud whenever the script has the switch at all, so
            # that "the background did not change" can be told apart from "this
            # end never had a say in it".
            chosen = runner.shadow.season
            print(f"[{self.tag}] vm season: "
                  f"{gs3vm.register_name(register)} <- "
                  + ("台本のまま" if chosen is None
                     else f"{chosen} {gs3vm.SEASON_NAMES[chosen]} "
                          f"({script.SEASON_SOURCE})"))

    def _shadow_at(self, session: "_Session", local_ip: int, op: int):
        """Walk the shadow to where the client says it is. None if it cannot."""
        runner = session.script
        shadow = runner.shadow if runner is not None else None
        if shadow is None or shadow.lost:
            return None
        why = shadow.at(local_ip, op)
        if why is None:
            return shadow
        print(f"[{self.tag}] ⚠️ vm out of step: {why}")
        return None

    def _script_start(
        self,
        session: "_Session",
        seen: int,
        found: "script.Script",
        ctrl: int,
        npc_infos: list[tuple[int, int]],
        cast_players: bool = True,
    ) -> bytes:
        """Arm a script and offer it to the client with MsgSvRequestScriptReady.

        Shared by /sc and by the NPC-event door, so that a script the client
        asked for and a script we pushed by hand go out identically — if they
        behave differently, that difference is about the state the client is in
        and not about which line of ours sent it.

        ``cast_players`` fills ``pcInfo[]`` -- ⚠️ **on by default since round
        191**, where it used to be a ドラマイベント-only extra. What changed is
        not the reading of those scripts (their cast really is the players) but
        the discovery that a *solo* script needs the array too: `$m00`/`$n00`
        are the player's family and given names and they come from here, so
        leaving it empty is why the tutorial says 「くん、あなたの……」 with a
        hole where the name goes. See `script.CAST_LOCAL_PLAYER`.
        """
        if found.script_id is None:
            return b""
        pc_infos: list[tuple[int, bytes]] = []
        actor = script.CAST_LOCAL_PLAYER
        if cast_players and actor is not None:
            # ⭐ Whoever started it is PC#0 -- the slot `$m00` reads. There is
            # no second entry yet: the other player would come from the party
            # the matching screen builds, and that screen cannot be opened on
            # this server.
            info = self._chars(session).find(session.chara_id)
            if info is not None:
                pc_infos.append((actor, info))
        session.script = script.Runner(found, ctrl, npc_infos)
        session.talking_choice = None
        print(
            f"[{self.tag}] script start {found.file} id={found.script_id} "
            f"ctrl={ctrl} npcInfo={npc_infos} pcInfo={[a for a, _ in pc_infos]} "
            f"({len(found)} instructions)"
        )
        self._shadow_start(session, found.script_id)
        return self._answer(
            session,
            seen,
            script.MSG_SV_REQUEST_SCRIPT_READY,
            script.ready_params(found.script_id, npc_infos, pc_infos),
        )

    def _script_command(self, session: "_Session", seen: int, action) -> bytes:
        """Act on /sc, /scn or /sce."""
        if action.kind == "start":
            # A digit string is a scriptId rather than a name; see chat.py.
            found = (script.stub(int(action.name)) if action.name.isdigit()
                     else script.load(action.name))
            if found is None or found.script_id is None:
                return b""      # chat.respond already said so
            return self._script_start(session, seen, found, action.ctrl, action.npc_infos)
        if session.script is None:
            return self._say(session, seen, "台本が走っていない")
        if action.kind == "end":
            print(f"[{self.tag}] script end (manual) after {session.script.acks} acks")
            session.script = None
            return (
                self._answer(session, seen, script.MSG_SV_NOTIFY_SCRIPT_END, b"")
                + self._romance_credit(session, seen)
            )
        return self._script_step(session, seen, "manual")

    def _script_step(self, session: "_Session", seen: int, why: str) -> bytes:
        """Push the next instruction, or end the script if there is none left."""
        runner = session.script
        if runner is None:
            return b""
        here = runner.advance()
        if here is None:
            print(f"[{self.tag}] script finished ({runner.acks} acks) -> NotifyScriptEnd")
            session.script = None
            return (
                self._answer(session, seen, script.MSG_SV_NOTIFY_SCRIPT_END, b"")
                + self._say(session, seen, "台本終了")
                + self._romance_credit(session, seen)
            )
        ip, op, name, args = here
        print(f"[{self.tag}] script {why} -> ip={ip} op=0x{op:04x} {name} {args}")
        reply = self._answer(
            session,
            seen,
            script.MSG_SV_NOTIFY_SCRIPT_COMMAND,
            script.command_params(ip, op, runner.ctrl),
        )
        # OP_END is where the script says it is over. Sending it and then
        # stopping is the same order the file itself has; if the client would
        # rather see NotifyScriptEnd first, that is one of the things this run
        # is for.
        if op == script.OP_END:
            print(f"[{self.tag}] script hit OP_END -> NotifyScriptEnd")
            session.script = None
            reply += self._answer(session, seen, script.MSG_SV_NOTIFY_SCRIPT_END, b"")
            reply += self._say(session, seen, "台本終了 (OP_END)")
            reply += self._romance_credit(session, seen)
        return reply

    def _run_locker(self, session: "_Session", menu_item: int):
        """Run the original server's locker script for this menu_item.

        ⭐ Nothing about when a letter appears, whose it is, or which sub-menu
        goes with it is decided here. `lck_s103` and `lck_s102` are the scripts
        the original server ran, they are still the game's own bytecode, and
        `gs3vm` runs them -- so the thresholds and the ordering stay in the data.

        None means "this end could not run it", and every caller falls back to
        the constant it used before. Three ways to get there, all of them
        logged: the script was never exported, the character is not ours, or the
        script read a cell nobody supplied. ⚠️ The last one is the important
        one: gs3vm raises rather than reading a missing cell as zero, so a hole
        in `locker_cells` surfaces as a fallback and a line in the log instead
        of as a branch quietly taken the wrong way.
        """
        name = romance.LOCKER_SCRIPTS.get(menu_item)
        if name is None:
            return None
        love = self._chars(session).romance(session.chara_id)
        if love is None:
            return None
        try:
            result = gs3vm.run(name, love.locker_cells(menu_item))
        except (gs3vm.UnknownCell, gs3vm.UnsupportedOp, gs3vm.Runaway) as exc:
            print(f"[{self.tag}] {name}: {exc} — 台本を回せず、従来の答えに戻ります")
            return None
        if result is None:
            print(f"[{self.tag}] {name}: runtime/scripts に無し — 従来の答えに戻ります")
            return None
        if love.absorb(result.writes) and not self._chars(session).set_romance(
            session.chara_id, love
        ):
            print(f"[{self.tag}] {name}: 書き戻せませんでした")
        return result

    def _script_die(self, session: "_Session", wire_ip: int) -> bool:
        """Flip the coin an `OP_RAND` branch needs. True means「成立」.

        ⭐ A coin and not a roll: what `OP_RAND` draws from has never been read,
        and a two-armed `OP_BR` is a two-way choice whatever the range is. The
        reasoning, and the cost of it for an n-way ladder, are in `gs3vm._Die`.
        """
        heads = self._script_dice.getrandbits(1) == 1
        print(f"[{self.tag}] script die at wire {wire_ip}: "
              f"{'成立' if heads else '不成立'}")
        return heads

    def _script_keywords(self, session: "_Session", result) -> None:
        """Hand over the キーワード a finished script granted, if any.

        ⭐⭐ This is the original's own grant path, and finding it retires an
        invention: `club.Membership.grant_keyword` says in its docstring that
        「it is INVENTED that this happens at all」, because until round 193 the
        only way a character got one here was a `/kw` typed by hand. It happens
        in `PC_KEYWORD_UPDATE`, 127 of them across 38 scripts -- the two
        tutorials carry twelve apiece, six coin flips that grant one キーワード
        per **category** (`club.KEYWORD_BLOCKS`, six of them), and the 36
        ドラマイベント carry two to six each (2.150).

        ⚠️⚠️ NOT one per 能力パラメータ, though there are six of those as well
        (文系 理系 芸術 雑学 運動 スタミナ). The two sixes are a coincidence and
        the tutorials never touch an ability at all -- see 2.150 三. ⚠️ And
        「how many `UPDATE`s a script carries」 is not 「how many the player ends
        up with」: the tutorial's twelve pay out six.

        ⚠️ Only the local player's actor slot is applied. In a two-player
        ドラマイベント both PCs are named and each client runs the script for
        itself, so taking the other one here would grant it twice -- once from
        each side -- to somebody this session does not own.
        """
        wanted = [keyword_id for actor, keyword_id in result.keywords
                  if actor == script.CAST_LOCAL_PLAYER]
        if not wanted:
            return
        state = self._chars(session).club(session.chara_id)
        if state is None:
            print(f"[{self.tag}] キーワード {wanted}: 部活の記録が無く、記帳できません")
            return
        got = [keyword_id for keyword_id in wanted
               if not state.owns_keyword(keyword_id)
               and state.grant_keyword(keyword_id)]
        if got and not self._chars(session).set_club(session.chara_id, state):
            print(f"[{self.tag}] キーワード {got}: 書き戻せませんでした")
            return
        print(f"[{self.tag}] キーワード: {len(got)} 件記帳 {got}"
              + (f" · 既に所持 {sorted(set(wanted) - set(got))}"
                 if len(got) != len(wanted) else ""))

    def _script_debut(self, session: "_Session", result) -> None:
        """Let a finished script's own cell writes drive 登場, if any.

        ⭐⭐ Round 193, and it is the first time a scenario's writes reach a
        save at all: `<name>_e001` -- 初登校 -- sets `PC[0x3900+i]`, and until
        now this end collected that in `Result.writes` and dropped it.

        ⚠️ `Romance.absorb` decides *which* cells count, not this method; in
        particular it takes 登場 and refuses 進行度, argued next to those
        constants. So a run that writes nothing absorbable is silent here.

        ⭐⭐⭐ Round 194 is the half that makes it mean something. Round 193 was
        deliberately a no-op -- `initial_cast()` put 天宮/桜井 on stage from day
        one, so the value written was the value already there and `changed` came
        back False every time. Now a character starts with an empty campus and
        this method is **the** way anyone gets on it: no 初登校, no 天宮.

        ⚠️ Which makes the log line below the thing to read when a candidate is
        missing from a map push. 「記帳」 means this ran and took the write;
        「既に同じ値」 means the save already said so; silence means the script
        never wrote the cell, and then the question is the script or the gate,
        not this end's bookkeeping.
        """
        love = self._chars(session).romance(session.chara_id)
        if love is None:
            return
        touched = sorted(
            f"{address:#06x}={value}"
            for (family, address), value in result.writes.items()
            if family == "PC" and not isinstance(address, tuple)
            and romance.PC_DEBUT_BASE <= address
            < romance.PC_DEBUT_BASE + len(romance.CANDIDATES)
        )
        if not touched:
            return
        changed = love.absorb(result.writes)
        if changed and not self._chars(session).set_romance(session.chara_id, love):
            print(f"[{self.tag}] 登場フラグ {touched}: 書き戻せませんでした")
            return
        print(f"[{self.tag}] 登場フラグ {' '.join(touched)} -> "
              + ("記帳" if changed else "既に同じ値（記帳なし）")
              + f" · 現在の登場: {love.on_stage()}")

    def _romance_credit(self, session: "_Session", seen: int) -> bytes:
        """A finished conversation counts towards 親密さ; a main event moves her.

        This is the one automatic advance in the whole model, and it hangs off
        the script ending because that is the only moment this end reliably knows
        a conversation happened.

        ⚠️ It has to hang off **every** NotifyScriptEnd, and there are four. The
        client runs the script itself and reports OP_END, so the end that fires
        in practice is the one in _script_incoming; the two in _script_step are
        for scripts this end is driving and the fourth is /sce. Round 41 wired
        the other three, watched a whole conversation play, and credited nothing.

        ⚠️ ``changed`` comes back False for a 日常会話 that is not this player's
        best of the day with her — the scripts' own daily rule, not a miss. It
        credits nothing and says nothing, which is correct; do not "fix" it.

        Which candidate comes from the capture_npc_event category we handed back
        when the talk started — not from who is standing nearby, which the server
        does not know, and not from the chibi's npcId, which is 1:0 for all of
        them. Anything started by hand (/sc) has no key and credits nobody.
        """
        talking_about, session.talking_about = session.talking_about, None
        choice, session.talking_choice = session.talking_choice, None
        if talking_about is None:
            return b""
        found = romance.whose_event(talking_about[0])
        if found is None:
            return b""
        name, kind = found
        love = self._chars(session).romance(session.chara_id)
        if love is None:
            return b""
        if kind == "main":
            changed, note = love.see_main_event(name), "メインイベント"
        else:
            # What this particular conversation is worth, out of the table
            # rather than out of a constant: 22 of them grant nothing, the ones
            # that offer a choice do not all include 12, and which answer was
            # clicked reaches here as `choice`. See romance.talk_gain — without
            # a click it falls back to the floor of what the script could give.
            gain = romance.talk_gain(talking_about, choice)
            # The second gate her first メインイベント has to clear: 「能力が低い
            # 間は見られない」. Read here rather than inside Romance because the
            # 能力 sheet is a different record on the same character; passing
            # None would quietly disarm the gate, so this asks for the sheet
            # even when there is none to be had.
            sheet = self._chars(session).ability(session.chara_id)
            levels = sheet.levels() if sheet else None
            changed, advanced = love.talk(name, gain=gain, levels=levels)
            short = love.blocked_by_ability(name, levels)
            # ⚠️ Five outcomes, and only two of them are holes in the wiring:
            # answers this end knows about that never arrived, and a click it
            # cannot place. Both credit the floor instead of a reading, so the
            # log marks them and leaves the ordinary three unmarked.
            #
            # ⭐ The last one is not a hole and looked like one until round 173
            # watched it happen: five of the 22 conversations that never touch
            # 親密さ at all still put a choice on the screen, and 16:1 — the one
            # this server starts by default — is one of them. A conversation
            # whose gain does not depend on the answer has no byChoice row by
            # construction, so an answer arriving for one is expected, not a
            # miss.
            answers = romance.talk_answers(talking_about)
            if choice is None:
                how = f"⚠️ {answers}行の選択肢が未着" if answers else "選択肢なし"
            elif 0 <= choice < answers:
                how = f"選択肢{choice}"
            elif answers:
                how = f"⚠️ 選択肢{choice} は {answers} 行の範囲外"
            else:
                how = f"選択肢{choice}・加値に影響しない"
            note = f"日常会話+{gain}（{how}）" + (
                " -> メインイベント!" if advanced else "")
            if short:
                # 親密さ is at the rung and the event still did not play. Say
                # which 能力 and by how much, because from the outside this is
                # indistinguishable from the counter being broken — which is
                # exactly the reading the manual warns about:「そこからさらに
                # 仲良くなることはできません」.
                note += " ⚠️ 能力不足 " + " ".join(
                    f"{ability.ABILITIES[index]}{have}/{need}"
                    for index, (have, need) in short.items())
            if gain == 0:
                # Worth saying, unlike the daily-rule case below: silence there
                # means "already had her best today", silence here would look
                # like the handler never fired. It is a table entry, not a miss.
                # ⭐ Carrying `how` matters here and not only for show: this is
                # the one line that prints whatever the daily rule decides, so
                # it is where a stale choice bleeding in from the conversation
                # before would be visible.
                print(f"[{self.tag}] romance {name} 日常会話 {talking_about[0]}:"
                      f"{talking_about[1]} grants nothing（{how}）")
        if not changed:
            return b""
        self._chars(session).set_romance(session.chara_id, love)
        print(f"[{self.tag}] romance {name} {note}: {love.line(name)}")
        # Queued, not said: see _Session.pending_say. The save above is what
        # matters and it has already happened; this is only the receipt.
        session.pending_say.append(f"{note} {love.line(name)}")
        return b""

    def _drama_incoming(
        self, session: "_Session", seen: int, msg_type: int, params: bytes
    ) -> bytes | None:
        """The two doors into the drama-event list; see script.py's second half.

        Both answers carry the same records, so the only difference is which
        bracket they arrive in. Everything known about the drama events is sent
        every time: the point of these two branches is to find out what the
        client does with a full list, and sending a subset would only add a
        second unknown.
        """
        events = script.drama_events()
        keys = [(event["genre"], event["index"]) for event in events]
        name = MESSAGE_NAMES.get(msg_type, "unknown")
        print(f"[{self.tag}] drama <- {name} (0x{msg_type:04x}) params={params.hex()}")

        if msg_type == script.MSG_CL_QUERY_DRAMAEVENT_MATCHING_POSSIBLE:
            # result, reason — both u8. Say yes and give no reason; if the
            # client wanted a particular non-zero reason alongside a yes, the
            # screen not opening is what will say so.
            return self._answer(
                session, seen, script.MSG_SV_RESULT_DRAMAEVENT_MATCHING_POSSIBLE,
                bytes((1, 0)),
            )

        if msg_type == script.MSG_CL_REQUEST_NPC_MAP_OBJECT_EVENT:
            # Right-clicking a chibi and picking the speech balloon. npcId is
            # the four bytes the spawn script's cast named (1:0 = 天宮小百合);
            # menuItemId is which line of that little menu was taken.
            if len(params) < 6:
                print(f"[{self.tag}] npc menu: short body {params.hex()}")
                return None
            npc_id, menu_item = struct.unpack_from(">IH", params, 0)
            print(
                f"[{self.tag}] npc menu npcId={npc_id} menuItemId={menu_item}"
                f"{' (talk)' if menu_item == script.MENU_ITEM_TALK else ''}"
            )
            # The eventId we hand back is what chooses the conversation; see
            # script.DEFAULT_NPC_EVENT. npcId goes back unchanged.
            #
            # ⭐ Except behind the locker's letter item, where the game has a
            # script for exactly this question: lck_s102 reads which letter is
            # waiting and names its <キャラ>_e011. One letter, one candidate --
            # the correspondence is the script's, not a table here.
            event = session.npc_event
            result = self._run_locker(session, menu_item)
            if result is not None and result.event is not None:
                event = result.event
                print(f"[{self.tag}] lck_s102 → event {event[0]}:{event[1]}")
            return self._answer(
                session, seen, script.MSG_SV_OK_NPC_MAP_OBJECT_EVENT,
                script.npc_map_object_event_params(event, npc_id),
            )

        if msg_type == script.MSG_CL_REQUEST_NPC_MAP_OBJECT_MENU:
            # The same right-click, one item further along: a menu_item whose
            # type is 1 opens a sub-menu instead of starting an event. The body
            # is the 0x6304 body -- npcId u32, menuItemId u16 -- and the answer
            # is a single sub_menu.bin key that this end gets to choose.
            if len(params) < 6:
                print(f"[{self.tag}] map object menu: short body {params.hex()}")
                return None
            npc_id, menu_item = struct.unpack_from(">IH", params, 0)
            # ⭐ The locker's own script picks the sub-menu. What it offers says
            # whether there is a letter: 0 ロッカー起動 alone when there is none,
            # 1 手紙イベント起動 then 2 ロッカー・手紙メニュー on the visit that
            # puts one there, and 2 alone when one is already waiting.
            answer, why = session.sub_menu, "既定値"
            result = self._run_locker(session, menu_item)
            if result is not None and result.menu is not None:
                answer = result.menu
                offered = "/".join(hex(m) for m in result.menus)
                why = f"lck_s103 → {offered}"
            print(
                f"[{self.tag}] map object menu npcId={npc_id} "
                f"menuItemId={menu_item} -> sub_menu {answer} ({why})"
            )
            return self._answer(
                session, seen, script.MSG_SV_OK_NPC_MAP_OBJECT_MENU,
                struct.pack(">H", answer),
            )

        if msg_type == script.MSG_CL_REQUEST_TITLE_EVENT_START:
            # ⭐⭐⭐ 初登校. The client picked this scriptId out of its own table
            # after the character list said tutorialFlag = 1, and it is sitting
            # on 「登校処理を行っています」 until this is answered -- so an
            # unanswered 0x6C00 is a 登校 that never finishes, not a cosmetic
            # gap. See script.MSG_CL_REQUEST_TITLE_EVENT_START for the whole
            # bracket and how it was measured.
            #
            # Answered exactly like the 0x5600 door below, and for the same
            # reason: the Ok is empty, so the script has to be pushed behind it
            # or the client reaches the load with no id and says スクリプト
            # エラー ID:65535 (round 37).
            script_id = struct.unpack_from(">H", params, 0)[0] if params else 0
            found = script.by_script_id(script_id)
            if found is None:
                # ⚠️ Both halves of the pair are exported now -- `amm_e001` at
                # 0x2000 for a male character and `skr_e001` at 0x20f3 for a
                # female one (round 193 supplied the second) -- so this arm is
                # for a title event nobody has met yet. A stub still gets the
                # client out of the 登校 rather than leaving it on the dialog
                # for ever. ⚠️⚠️ But a stub writes no cells, so a character who
                # lands here gets no 登場 either (`_script_debut`): an empty
                # campus after 初登校 means read this line, not the save.
                print(f"[{self.tag}] title event {script_id} has no exported "
                      f"script — starting a stub (cast empty)")
                found = script.stub(script_id)
            print(f"[{self.tag}] ⭐ title event {script_id:#06x} -> {found.file}")
            infos = [(actor["actorId"], actor["id"]) for actor in found.actors]
            return (
                self._answer(session, seen, script.MSG_SV_OK_TITLE_EVENT_START, b"")
                + self._script_start(session, seen, found, 0, infos)
            )

        if msg_type == script.MSG_CL_REQUEST_TITLE_EVENT_END:
            # The closing half. Empty both ways (`the shape reader`), and
            # unlike the NPC-event end there is no ClearCharacterInfo to send
            # after it: this event was never started off a map object, so the
            # client is not waiting to be given a field back -- it is waiting to
            # be let into one, which is the 登校 it suspended.
            print(f"[{self.tag}] title event end")
            return self._answer(
                session, seen, script.MSG_SV_OK_TITLE_EVENT_END, b"")

        if msg_type == script.MSG_CL_REQUEST_NPC_EVENT_START:
            # The client has read the event record we pointed it at and is
            # asking for the script id it found there. Acknowledging is not
            # enough: round 37 answered only the Ok and the client fell over
            # with "スクリプトエラー：ファイル読み込みに失敗しました ID:65535",
            # i.e. it reached the load with no script id at all. The script has
            # to be pushed behind the Ok — and this is the state round 32 was
            # missing, when every 0x72xx went out on the campus screen and came
            # back "受信ハンドラが設定されていません".
            npc_event_id = struct.unpack_from(">H", params, 0)[0] if params else 0
            reply = self._answer(session, seen, script.MSG_SV_OK_NPC_EVENT_START, b"")
            found = None
            if script.FORCED_NEXT_SCRIPT is not None:
                # ⭐ `/sc next` armed a different script. This is the only place
                # a ドラマイベント can be started from, because the ids the
                # client can ask for never name one — see FORCED_NEXT_SCRIPT.
                # It disarms itself here so a forced start never outlives the
                # one right-click that was meant to carry it.
                wanted, script.FORCED_NEXT_SCRIPT = script.FORCED_NEXT_SCRIPT, None
                found = script.load(wanted)
                # ⚠️ `is not None`, not truthiness: Script defines __len__, so
                # an export with no instructions in it is falsy.
                print(f"[{self.tag}] npc event {npc_event_id} -> forced {wanted}"
                      + ("" if found is not None else " (no export; falling back)"))
            if found is None:
                found = script.by_script_id(npc_event_id)
            if found is None:
                # ⭐ No export for this id, so push a stub instead of giving up.
                # The client has already read the id out of its own table and
                # is waiting to be told to run it; answering with the id alone
                # is the whole question — whether an export was ever needed on
                # this path. Returning the bare Ok is the one outcome that
                # teaches nothing, because it ends in スクリプトエラー
                # ID:65535 whether or not the data would have helped.
                print(
                    f"[{self.tag}] npc event {npc_event_id} has no exported script "
                    f"— starting a stub (cast empty)"
                )
                found = script.stub(npc_event_id)
            # The cast comes out of the script's own header rather than from
            # this end: each .ssb names its actors, which is why 223 placement
            # scripts can all say NPC#1 and still be 223 different people.
            infos = [(actor["actorId"], actor["id"]) for actor in found.actors]
            session.talking_about = session.npc_event
            return reply + self._script_start(session, seen, found, 0, infos)

        if msg_type == script.MSG_CL_REQUEST_NPC_EVENT_END:
            # ⚠️ The client only sends this after an event that started from a
            # map object (npcId 16:1, the row of lockers). The same script
            # started by right-clicking a chibi ends with 0x4000 instead and the
            # map comes back on its own -- so this message is not a formality,
            # it is the client asking to be let out.
            #
            # The Ok alone is not letting it out: its handler is the shared
            # empty stub (`mov al,1; ret 4`), so the answer is received,
            # acknowledged and dropped, and the client sits on a black screen.
            # What ends the event is the ClearCharacterInfo that follows, with
            # the 0xffff sentinel -- see script.NPC_EVENT_CLEAR_TO_FIELD.
            if session.npc_event_end == "manual":
                print(f"[{self.tag}] npc event end — /evend manual: 返事なし")
                return None
            # ⭐ Whose ending, or none. PC[0x3a04] is the cell <キャラ>_e011
            # writes when the player opens the letter -- her index on the way in,
            # -1 on 「読まない」 -- and the ending this message plays is chosen by
            # exactly that number. ⚠️ Until this end runs the scenario scripts
            # too, nothing writes it, so this stays at the sentinel and the
            # player gets the map back, which is the behaviour that predates it.
            npc_id = script.NPC_EVENT_CLEAR_TO_FIELD
            love = self._chars(session).romance(session.chara_id)
            names = list(romance.CANDIDATES)
            if love is not None and 0 <= love.letter_event < len(names):
                npc_id = love.letter_event
                print(f"[{self.tag}] npc event end — {names[npc_id]} の"
                      f"エンディングへ (0x5606 npcId={npc_id})")
                # One-shot: the credits play once, and the next event out of the
                # locker is a fresh question.
                love.letter_event = romance.NO_LETTER_EVENT
                self._chars(session).set_romance(session.chara_id, love)
            return self._answer(
                session, seen, script.MSG_SV_OK_NPC_EVENT_END, b""
            ) + self._answer(
                session, 0,
                script.MSG_SV_NOTIFY_NPC_EVENT_CLEAR_CHARACTER_INFO,
                script.npc_event_clear_params(npc_id),
            )

        if msg_type == script.MSG_CL_REQUEST_DRAMA_EVENT_START:
            # scriptId, actorId in; a u64 dramaEventId back. Nothing is known
            # about what the id has to be, so it is 1 — distinct from zero, in
            # case zero reads as "none", and constant so that a second request
            # getting the same id is visible rather than hidden.
            requested = struct.unpack_from(">HH", params, 0) if len(params) >= 4 else (0, 0)
            print(f"[{self.tag}] drama start scriptId={requested[0]} actorId={requested[1]}")
            return self._answer(
                session, seen, script.MSG_SV_OK_DRAMA_EVENT_START, struct.pack(">Q", 1),
            )

        if msg_type == script.MSG_CL_QUERY_CHARA_MENU_DRAMA_EVENT_LIST:
            kept = keys[: script.CHARA_MENU_DRAMA_MAX]
            # nNum goes out as an int32 (the reader takes it through the input
            # stream's +0x14 slot, which is the signed 32-bit one).
            return self._answer(
                session, seen, script.MSG_SV_RESULT_CHARA_MENU_DRAMA_EVENT_LIST,
                struct.pack(">i", len(kept)),
            ) + self._answer(
                session, seen, script.MSG_SV_NOTIFY_CHARA_MENU_DRAMA_EVENT_LIST,
                script.drama_event_list_params(kept, script.CHARA_MENU_DRAMA_MAX),
            )

        if msg_type == script.MSG_CL_REQUEST_DRAMA_EVENT_MATCHING_START:
            kept = keys[: script.DRAMA_EVENT_MAX]
            # The party list goes out empty: there is only ever one player on
            # this server, so an entry would have to be invented, and an
            # invented party is a second thing that can be wrong.
            return (
                self._answer(
                    session, seen, script.MSG_SV_OK_DRAMA_EVENT_MATCHING_START,
                    script.matching_start_params(len(kept), 0),
                )
                + self._answer(
                    session, seen, script.MSG_SV_NOTIFY_DRAMA_EVENT_LIST,
                    script.drama_event_list_params(kept),
                )
                + self._answer(
                    session, seen, script.MSG_SV_NOTIFY_DRAMA_PARTY_LIST,
                    struct.pack(">H", 0),
                )
            )

        # The rest of the 0xE0xx family — party create/join/ready/start — is
        # only reachable once the screen is up, so it is logged rather than
        # answered until we have seen the screen come up at all.
        return None

    def _script_incoming(
        self, session: "_Session", seen: int, msg_type: int, params: bytes
    ) -> bytes | None:
        """Anything the client sends back in the 0x72xx range."""
        name = MESSAGE_NAMES.get(msg_type, "unknown")
        print(f"[{self.tag}] script <- {name} (0x{msg_type:04x}) params={params.hex()}")
        if session.script is None:
            print(f"[{self.tag}] script <- arrived with no script running")
            return None
        if msg_type == script.MSG_CL_OK_SCRIPT_READY:
            session.script.started = True
            # Nothing but the start signal. Rounds 30-32 followed it with a
            # 0x721f and read the silence as "the interpreter is dead"; round 37
            # showed the client had been running the script by itself all along
            # and those 0x721f were landing in the file header as garbage ips.
            return self._answer(session, seen, script.MSG_SV_NOTIFY_SCRIPT_START, b"")
        if msg_type == script.MSG_CL_NG_SCRIPT_READY:
            reason = params[0] if params else -1
            print(f"[{self.tag}] script REFUSED, reason={reason}")
            session.script = None
            return self._say(session, seen, f"台本を断られた reason={reason}")
        if msg_type == script.MSG_CL_NOTIFY_SCRIPT_COMMAND:
            session.script.acks += 1
            if len(params) < 6:
                print(f"[{self.tag}] script report: short body {params.hex()}")
                return None
            wire_ip, op = struct.unpack_from(">IH", params, 0)
            found = session.script.script
            local = found.local_ip(wire_ip)
            here = found.at(local)
            where = f"ip={local} (wire {wire_ip})"
            print(f"[{self.tag}] script at {where} op=0x{op:04x} "
                  f"{here[2] + ' ' + here[3] if here else '<not an instruction start>'}")
            shadow = self._shadow_at(session, local, op)
            if shadow is not None and op not in (
                script.OP_BR, script.OP_END, script.OP_SYNC_VARIABLE
            ):
                # Everything but the three the client waits on it resolved by
                # itself, so the shadow resolves it the same way and moves on.
                shadow.flowed()
            if op == script.OP_SYNC_VARIABLE:
                return self._script_variable(session, seen, local, shadow)
            if op == script.OP_END:
                # ⭐ The script says it is over, and until the server agrees the
                # client holds the event screen up with nothing on it — a black
                # screen that looks exactly like a crash and is not one. Sending
                # this makes the client ask for the map back with 0x4000 of its
                # own accord, which is how the player gets out of the cutscene.
                print(f"[{self.tag}] script reached OP_END -> NotifyScriptEnd")
                if shadow is not None:
                    # ⭐ The whole point of a shadow, in one line: what a
                    # register file on this end would have had to say, and
                    # which cells it would have needed to say it.
                    print(f"[{self.tag}] vm {shadow.describe()}")
                    print(f"[{self.tag}] vm {shadow.result.summary()}")
                    # ⚠️ A `Result` is what the run would have written; each
                    # helper below decides what it is willing to take out of it.
                    # `amm_e001` sets two 恋愛 cells at ip=444/452 and they are
                    # treated differently on purpose: 登場 is absorbed (round
                    # 193), 進行度 is not -- argued next to those constants in
                    # `romance.py`. ⛔️ Do not "finish the job" by taking 進行度
                    # too; the tutorial IS その１ and the spot table counts main
                    # events *after* the debut, so it would count a rung twice.
                    #
                    # ⚠️⚠️ And do not reason about *when* the original wrote
                    # them. `PC_DATA_UPDATE`, both キーワード ops and
                    # `PC_EVENT_VARIABLE_UPDATE` share one stub slot in the
                    # client (`reference/ssc_fields.tsv`) ⇒ nothing happens over
                    # there, the register file only exists here, and there is no
                    # observable difference to reproduce. ⛔️ 「when did the
                    # original server flush」 has never been observed here.
                    self._script_keywords(session, shadow.result)
                    self._script_debut(session, shadow.result)
                session.script = None
                # ⭐ This is the end that actually happens. The client runs the
                # script itself (round 37) and reports OP_END here, so the two
                # ends in _script_step are the server-driven ones and a 日常会話
                # never touches them. Round 41 hooked those two and the manual
                # /sce and called the credit wired; it fired on none of the
                # three. Any new NotifyScriptEnd has to credit here too.
                return (
                    self._answer(session, seen, script.MSG_SV_NOTIFY_SCRIPT_END, b"")
                    + self._romance_credit(session, seen)
                )
            if op != script.OP_BR:
                # A notification. The client resolved it itself and is already
                # moving; answering would only confuse the two ip units again.
                return None
            # The one it waits on. Both roads are logged every time, because
            # "which way did it go" and "which way could it have gone" is the
            # whole diagnostic for a script that plays but plays wrong.
            fall_through, taken = session.script.script.branch_roads(wire_ip)
            target, why = session.script.resolve_branch(wire_ip)
            if shadow is not None and why == script.STANDING_NO:
                # ⭐⭐ The one place the shadow decides instead of reporting,
                # and it is fenced twice over: the answer it replaces must be
                # the standing "no" (a forced branch or a choice chain outranks
                # it), and everything the branch decides must be invisible to
                # the save and to the story -- see `gs3vm._decided_road`.
                #
                # It started (round 185) as the 進行度 switch every 日常会話
                # opens with -- 「恋愛候補生が立っている位置は、メインイベント
                # を体験するごとに変わります」 -- and until it existed every arm
                # of that fell through, so a candidate's daily conversations
                # never changed their setting. ⭐ Round 192 fixed how the road is
                # bounded, which brought in the other family that needed it: the
                # 自分のクラス dispatch the tutorial walks you home on.
                verdict, goes_to = shadow.branch()
                if verdict is gs3vm.DIE:
                    # ⭐⭐⭐ The other thing this end may settle, and it is
                    # fenced by a different question from the one above. There
                    # the test is 「does the destination matter」; here it is
                    # 「is there anybody else who could answer」 -- and for a
                    # die there is not: the client's OP_RAND slot is a stub, so
                    # declining does not defer to the side that knows, it picks
                    # the fall-through arm every run (`gs3vm._Die`).
                    # ⚠️ `decided_road` deliberately does NOT gate this one,
                    # and the reason is the question above, not the destination:
                    # a die has no other side to defer to at all.
                    # ⚠️⚠️ Round 193 gave a second reason -- 「the six coin flips
                    # hand out キーワード, which that gate forbids」 -- and round
                    # 195 retired it: the gate now admits a road that writes only
                    # キーワード (`gs3vm._undecidable`), so these branches would
                    # pass it too. ⛔️ The carve-out stays anyway; it is about
                    # 「is there anybody else who could answer」 and always was.
                    # What still outranks it is the same thing that outranks the
                    # case below: `why == STANDING_NO`.
                    heads = self._script_die(session, wire_ip)
                    if heads:
                        target = found.wire_ip(goes_to)
                    why = f"サイコロ (OP_RAND -> {'成立' if heads else '不成立'})"
                elif (verdict is not None and not gs3vm._unknown(verdict) and verdict
                        and shadow.decided_road()):
                    target = found.wire_ip(goes_to)
                    why = f"表現のみ (vm cond={verdict})"
            other = "" if taken is None else f" 分岐先は ip={found.local_ip(taken)}"
            print(f"[{self.tag}] script branch -> wire {target} "
                  f"(ip={found.local_ip(target)}, {why}){other}")
            if shadow is not None:
                # ⚠️ Reported, not obeyed -- with the one exception just above.
                # This line says what the script's own arithmetic makes of the
                # same question, so that the two can be compared against a
                # screen before any more of it is allowed to move.
                condition, would = shadow.branch()
                if condition is gs3vm.DIE:
                    pass  # already said, and said with which way the coin fell
                elif condition is gs3vm.TOP:
                    print(f"[{self.tag}] vm cond=⊤ — this branch is not answerable here")
                elif condition is not None:
                    # OP_BR_WIDTH is in the client's unit (file bytes) and this
                    # line is in ours (u16 words), hence the halving.
                    goes = would if condition else local + script.OP_BR_WIDTH // 2
                    print(f"[{self.tag}] vm cond={condition} -> ip={goes}"
                          + (" = what was sent" if goes == found.local_ip(target)
                             else " ⚠️ NOT what was sent"))
                # And then it goes where the client was actually sent, which is
                # what keeps it in step with a screen it does not control.
                shadow.resumed(found.local_ip(target))
            return self._answer(session, seen,
                                script.MSG_SV_NOTIFY_SCRIPT_COMMAND_BRANCH,
                                script.branch_params(target))
        if msg_type == script.MSG_CL_NOTIFY_SCRIPT_COMMAND_BEGIN:
            # "This command needs you." Unlike 0x721b this one is a stop: the
            # client sits on it until the server sends whatever that command
            # wants. Only INPUT_SELECT is understood so far.
            if len(params) < 6:
                print(f"[{self.tag}] script begin: short body {params.hex()}")
                return None
            wire_ip, op = struct.unpack_from(">IH", params, 0)
            found = session.script.script
            local = found.local_ip(wire_ip)
            session.script.begun = (wire_ip, op)
            if op == script.OP_PLAYER_WAIT_TIME and script.RELEASE_PLAYER_WAIT:
                # ⭐ The wait a ドラマイベント is paced by. With one player in
                # the script there is nobody to wait for, so the release goes
                # out at once, as the same closing bracket a choice box gets.
                shadow = self._shadow_at(session, local, op)
                if shadow is not None:
                    shadow.flowed()
                session.script.begun = None
                print(f"[{self.tag}] PLAYER_WAIT_TIME ip={local} — 参加者は 1 人、"
                      f"その場で解除")
                return self._answer(session, seen,
                                    script.MSG_SV_NOTIFY_SCRIPT_COMMAND_END,
                                    script.command_end_params(wire_ip, op))
            if op != script.OP_INPUT_SELECT:
                print(f"[{self.tag}] script begin ip={local} op=0x{op:04x} "
                      f"— 応答未実装、待たせたまま")
                return None
            return self._script_select(session, seen, local)
        if msg_type == script.MSG_CL_RESULT_SCRIPT_COMMAND_SELECT:
            # ⭐ Which line the player clicked. The number is only half the
            # answer — the script asks about it through the OP_BR chain that
            # follows, which is what `chose` arms.
            if len(params) < 2:
                print(f"[{self.tag}] script select: short body {params.hex()}")
                return None
            (result,) = struct.unpack_from(">H", params, 0)
            session.script.chose(result)
            # ⭐ Kept past the OP_BR chain that consumes it: `chose` arms a
            # counter that `resolve_branch` disarms the moment it fires, and by
            # the time the script ends the Runner is gone as well. 親密さ is
            # settled at the end, not at the branch, so the number has to
            # outlive both.
            session.talking_choice = result
            print(f"[{self.tag}] ⭐ 選択肢 {result} が選ばれた")
            if session.script.shadow is not None:
                session.script.shadow.chose(result)
            # ⭐ …and the client is still stopped. Answering what the command
            # asked for does not end it; only the closing bracket does, carrying
            # the Begin's own {ip, op} back. Without this the box vanishes and
            # the script never resumes — which is exactly how it looked before
            # 0x721d was tried by hand.
            if session.script.begun is None:
                print(f"[{self.tag}] 選択が届いたが Begin を覚えていない")
                return None
            begun_ip, begun_op = session.script.begun
            session.script.begun = None
            return self._answer(session, seen,
                                script.MSG_SV_NOTIFY_SCRIPT_COMMAND_END,
                                script.command_end_params(begun_ip, begun_op))
        if msg_type == script.MSG_CL_NOTIFY_SCRIPT_COMMAND_SELECT_DEFAULT:
            # Arrives unasked, presumably as the highlight moves. Logged only:
            # answering something the client did not stop for is how rounds
            # 30-32 filled the log with replies to nobody.
            where = struct.unpack_from(">H", params, 0)[0] if len(params) >= 2 else -1
            print(f"[{self.tag}] script select default={where}")
            return None
        # Variables, errors, and the rest: logged, not answered. What the client
        # asks for unprompted is exactly what this run is here to find.
        return None

    def _script_variable(self, session: "_Session", seen: int, local_ip: int,
                         shadow) -> bytes:
        """Answer a stopped SYNC_VARIABLE with MsgSvNotifyScriptCommandVariable.

        ⭐⭐⭐ The client asks because it cannot answer: its OP_STR and its whole
        arithmetic family are logging stubs, so the register a line of dialogue
        is about to interpolate exists only on this side. In amm_e001 that is
        「確か$s00組だったかな……」 — the class name S0 was written a few dozen
        ips earlier by the branch chain over 自分のクラス, and until this
        existed the client sat on the finished page of dialogue forever.

        ⭐ **An empty list still releases it**, and that is the fallback here
        rather than silence: 0x9f0048 skips its apply loop when the count is
        zero and goes straight to the wait-flag clear at the bottom. So a script
        with no shadow — nobody ran `the script exporter` for it — plays on
        with an unfilled placeholder instead of stopping dead. ⚠️ Which is worth
        seeing in the log, because "the text has a hole in it" and "the script
        hung" look nothing alike on screen and identical from here.
        """
        entries = shadow.sync_values() if shadow is not None else []
        if shadow is None:
            print(f"[{self.tag}] ⚠️ SYNC_VARIABLE ip={local_ip} — no shadow, "
                  f"sending an empty list to release the client")
        elif not entries:
            print(f"[{self.tag}] ⚠️ SYNC_VARIABLE ip={local_ip} — the export "
                  f"names no registers here, sending an empty list")
        else:
            told = ", ".join(
                f"{gs3vm.register_name((category, number))}="
                + ("?" if value is None else repr(value))
                for category, number, value in entries
            )
            unknown = sum(1 for _, _, value in entries if value is None)
            print(f"[{self.tag}] SYNC_VARIABLE ip={local_ip} -> {told}"
                  + (f"  ⚠️ {unknown} of them this end could not say" if unknown else ""))
            shadow.flowed()
        return self._answer(session, seen,
                            script.MSG_SV_NOTIFY_SCRIPT_COMMAND_VARIABLE,
                            script.command_variable_params(entries))

    def _script_select(self, session: "_Session", seen: int, local_ip: int) -> bytes:
        """Answer a stopped INPUT_SELECT with MsgSvQueryScriptCommandSelect."""
        select, timer = script.select_query()
        if session.select_override is not None:
            select, timer = session.select_override
        shadow = self._shadow_at(session, local_ip, gs3vm.OP_INPUT_SELECT)
        if shadow is not None:
            mask, unknown, options = shadow.select()
            # ⚠️ Reported, not sent: `select` above is still SELECT_ALL. ⛔️ And
            # not cached either -- a script that redraws the same box after an
            # answer has been used gets a different mask the second time, which
            # is why this is asked at the box rather than looked up.
            print(f"[{self.tag}] vm select mask={mask:#x} of {options} options"
                  + (f" ⊤={unknown:#x}" if unknown else " (no ⊤)")
                  + (" = same as what is sent" if mask == (1 << options) - 1
                     else " ⚠️ narrower than what is sent"))
        # The export no longer decides the answer, only what the log can say
        # the box is about to show. Having no entry is ordinary — a stub has
        # none — so it is reported as an absence rather than as a fault.
        entry = session.script.script.selects.get(local_ip)
        if entry is not None:
            print(f"[{self.tag}] 選択肢 ip={local_ip}「{entry['prompt']}」: "
                  + " / ".join(entry["options"]))
        else:
            print(f"[{self.tag}] 選択肢 ip={local_ip}（文面は台本にしかない）")
        print(f"[{self.tag}] -> QueryScriptCommandSelect select={select} timer={timer}")
        return self._answer(session, seen,
                            script.MSG_SV_QUERY_SCRIPT_COMMAND_SELECT,
                            script.select_params(select, timer))

    def _career_depart(self, session: "_Session") -> None:
        """Close the 登校 span this session opened, if it opened one.

        Called from both ways a school day can end -- 下校 and the socket going
        away -- because 累計登校時間 is a sum of spans and a span that is never
        closed is time the player spent and the card never shows. ⚠️ It clears
        ``arrived_at`` so that calling it twice adds the span once: the logout
        path runs first and the teardown runs afterwards on the same session.
        """
        if not session.arrived_at or not session.chara_id:
            session.arrived_at = 0.0
            return
        span = time.monotonic() - session.arrived_at
        session.arrived_at = 0.0
        store = self._chars(session)
        state = store.career(session.chara_id)
        if state is None:
            return
        total = state.depart(span)
        store.set_career(session.chara_id, state)
        print(f"[{self.tag}] 下校 after {int(span)}s for "
              f"charaId={session.chara_id}: 累計 {total}s")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.conn_seq += 1
        print(f"[{self.tag}] ACCEPT peer={peer} (conn #{self.conn_seq})")
        session = _Session()
        session.writer = writer
        session.peer_host = _peer_host(peer)
        self.live.append(session)
        # Start at the end of the console, not the beginning: the file is a log
        # of what has already been run, and replaying it on every reconnect
        # would fire the last script again at login.
        try:
            session.console_at = len(self.console_path.read_text(encoding="utf-8"))
        except OSError:
            session.console_at = 0
        buf = b""
        try:
            while True:
                # Wait on the socket until either something arrives or something
                # is due to go out. Only a lesson in progress ever sets a
                # deadline; with none, this is the plain idle timeout it always
                # was. See _Session.next_wake for why questions need one.
                due = session.next_wake()
                try:
                    chunk = await asyncio.wait_for(
                        reader.read(65536),
                        timeout=due if due is not None else IDLE_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    if due is None:
                        print(f"[{self.tag}] idle timeout peer={peer}")
                        break
                    push = self._drains(session)
                    if push:
                        write_packet_log(self.packet_dir, self.tag, "out", push)
                        writer.write(push)
                        await writer.drain()
                        print(f"[{self.tag}] -> {len(push)}B (timer): {push.hex()}")
                    continue
                if not chunk:
                    print(f"[{self.tag}] EOF peer={peer}")
                    break
                write_packet_log(self.packet_dir, self.tag, "in", chunk)
                buf += chunk
                packets, buf = parse_packets(buf)
                for tag, body in packets:
                    name = TAG_NAMES.get(tag, "unknown")
                    try:
                        body = self._decipher(session, tag, body)
                    except ValueError as exc:
                        print(f"[{self.tag}] <- tag=0x{tag:04x} ({name}) undecipherable: {exc}")
                        continue
                    print(f"[{self.tag}] <- tag=0x{tag:04x} ({name}) {len(body)}B: {body.hex()}")
                    reply = self._reply(session, tag, body)
                    reply = (reply or b"") + self._drains(session)
                    if not reply:
                        continue
                    write_packet_log(self.packet_dir, self.tag, "out", reply)
                    writer.write(reply)
                    await writer.drain()
                    print(f"[{self.tag}] -> {len(reply)}B: {reply.hex()}")
        finally:
            # 0x580D reason 2 is 「切断による」, so a dropped connection taking
            # its owner out of the 看板 is the protocol's own rule and not
            # tidiness. ⚠️ It is also load-bearing here: rooms are not persisted,
            # and a leaver who stayed in one across a logout would meet
            # 「既に自主トレルームに入っているため、自主トレルームを作成でき
            # ません」 on every attempt for the rest of the process's life.
            #
            # ⚠️ Order: leave self.live FIRST. _tr_part_notice looks the room's
            # members up by charaId, and a session that is on its way out must
            # not be handed its own farewell.
            # 累計登校時間 owes this session whatever it spent at school, and
            # this is the last place that still knows who it was. ⚠️ It has to
            # be ahead of the removal below because it needs session.chara_id;
            # the logout path may already have closed the span, in which case
            # this is a no-op.
            self._career_depart(session)
            # Who was watching this character, worked out before the removal for
            # the same reason: after it, _peers can no longer see the session at
            # all, and the answer would be the wrong map's crowd.
            watchers = self._peers(session) if session.chara_id else []
            if session in self.live:
                self.live.remove(session)
            # ⚠️ This one fighter goes, the fight does NOT — Board.leave and
            # Fighter.gone say why. Round 94 closed the whole fight here, and
            # that is precisely what left the survivor stranded: a fight off the
            # board can no longer reach any ending, so the client sat on the
            # battle screen with 「残り　7　ターン」 and the only way out was
            # killing it. Carrying on reaches the one ending this server has
            # restored — turn 8, 0x5C1A, ［終 了］.
            #
            # ⚠️⚠️ Restored and invented, kept apart: that a disconnect owes the
            # others this message is RESTORED — error_message 494-495 gives
            # 0x5C1B reason 0 the sentence 「通信が切断されたため、クラブ活動を
            # 強制終了しました」, which is about this exact event. What the fight
            # does AFTERWARDS — carry on short-handed, be decided, be voided —
            # is NOT restored anywhere. Of the three, carrying on is the only
            # one that needs no new field on the wire and no new moment for a
            # fight to end at: see Fighter.gone.
            #
            # ⚠️⚠️ ORDER: innermost context first — fight, then room, then
            # world. MEASURED, not tidiness (round 94): 0x5C1B draws a
            # システムメッセージ naming the character who left, and the name has
            # to come from somewhere. Sent AFTER the 0x4810 that deletes them
            # and the 0x580D that unseats them, the same message drew nothing
            # at all on a real disconnect while the identical bytes from
            # ``/cb part`` — with neither of those ahead of it — drew the notice
            # every time. ⚠️ Which of the two silences it is NOT separated yet.
            gone = self.battles.leave(session.chara_id) if session.chara_id else None
            if gone is not None:
                self._cb_part_notice(
                    gone, session.chara_id, clubbattle.PART_DISCONNECTED
                )
                self._battle_carry_on(gone)
                print(f"[{self.tag}] battle left on disconnect, "
                      f"now {self.battles.summary()}")
            if watchers:
                self._presence_withdraw(session, watchers)
            room = self.trainingrooms.room_of(session.chara_id) if session.chara_id else None
            if room is not None:
                leader_id = room.leader_id
                self.trainingrooms.part(session.chara_id)
                self._tr_part_notice(
                    room, session.chara_id, leader_id,
                    trainingroom.PART_REASON_DISCONNECTED,
                )
                print(f"[{self.tag}] trainingroom dropped on disconnect, "
                      f"now {self.trainingrooms.summary()}")
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[{self.tag}] closed {peer}")

    def _reply(self, session: _Session, tag: int, body: bytes) -> bytes | None:
        if tag == TAG_TIMESYNC:
            session.syncs += 1
            first = session.syncs == 1
            session.note_clock(int.from_bytes(body[:8].rjust(8, b"\x00"), "big"))
            print(f"[{self.tag}] timesync #{session.syncs} t1={body[:8].hex()}")
            return self._packet(session, TAG_TIMESYNC, timesync_reply(body, first))
        if tag == TAG_KEX1:
            try:
                key, sequence = parse_kex1(body)
            except ValueError as exc:
                print(f"[{self.tag}] kex1 rejected: {exc}")
                return None
            print(f"[{self.tag}] client key={key.hex()} seq={sequence}")
            session.client_key = key
            # The announced key is the one its owner enciphers with, so the
            # client's goes on our incoming side and ours on our outgoing side.
            session.in_cipher = mps_cipher.Blowfish(key)
            session.out_cipher = mps_cipher.Blowfish(session.server_key)
            return self._packet(session, TAG_KEX2, kex2_body(key, session.server_key, 1))
        if tag == TAG_KEX3:
            try:
                echoed, sequence = parse_kex3(body)
            except ValueError as exc:
                print(f"[{self.tag}] kex3 rejected: {exc}")
                return None
            state = "ok" if echoed == session.server_key else f"MISMATCH ({echoed.hex()})"
            print(f"[{self.tag}] kex3 echo {state} seq={sequence} -> key exchange complete")
            return None
        if tag == TAG_MESSAGE:
            try:
                sequence, msg_type, params = parse_message(body)
            except (ValueError, struct.error) as exc:
                print(f"[{self.tag}] message rejected: {exc}")
                return None
            name = MESSAGE_NAMES.get(msg_type, "unknown")
            print(
                f"[{self.tag}] msg 0x{msg_type:04x} ({name}) seq={sequence} "
                f"params={params.hex() or '-'}"
            )
            if msg_type == MSG_CL_REQUEST_LOGIN:
                # The one message that names an account. See accounts.py for
                # what registrationCode holds and how that was measured.
                code = accounts.registration_code(params)
                # Who signed in at the auth service, carried across on the other
                # field of this same message. See konami_id.py for how it gets
                # here; "" is a client that never went through /login.php, and a
                # token naming nobody is one whose personal key did not verify.
                token = konami_id.token_from_params(accounts.session_id(params))
                signed_in_as = self.tokens.who(token)
                if signed_in_as:
                    who = f"signed in as {signed_in_as}"
                elif self.tokens.knows(token):
                    who = "signed in as nobody (personal key did not verify)"
                else:
                    who = "no session token"
                print(f"[{self.tag}] login: code {accounts.label(code)}, {who}")
                reason = self.accounts.check(code)
                if reason is None:
                    reason = self.accounts.check_login(code, signed_in_as)
                if reason is None:
                    try:
                        account_id = self.accounts.account_id(code)
                    except RuntimeError as exc:
                        # Out of account ids. The client has a sentence for
                        # exactly this and it is better than a dropped
                        # connection, which is what an uncaught error here used
                        # to give.
                        print(f"[{self.tag}] {exc}")
                        reason = codes.REASON_ACCOUNT_CREATE_FAILED
                if reason is not None:
                    print(
                        f"[{self.tag}] refusing code {accounts.label(code)}: "
                        f"reason {reason}"
                    )
                    return self._answer(
                        session, sequence, MSG_SV_NG_LOGIN, ng_login_params(reason)
                    )
                self._bind(session, account_id, f"code {accounts.label(code)}")
                auth_code = self.tickets.issue(account_id)
                print(
                    f"[{self.tag}] next hop {self.advertise_ip}:{GAME_PORT}, "
                    f"authCode={auth_code:#x} for account {account_id}"
                )
                return self._answer(
                    session,
                    sequence,
                    MSG_SV_OK_LOGIN,
                    ok_login_params(
                        self.advertise_host_be,
                        auth_code=auth_code,
                        account_id=account_id,
                    ),
                )
            if msg_type == MSG_CL_NOTIFY_AUTH_CODE:
                # The first message on the game and school connections, and the
                # only thing either of them ever says about which account it is.
                # It carries back the u32 handed out with the relay ticket, so
                # the desk that minted it can say whose connection this is.
                #
                # Answering nothing is still right -- it is a notify -- but it
                # is no longer ignored.
                echoed = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                account_id = self.tickets.redeem(echoed)
                if account_id is None:
                    print(
                        f"[{self.tag}] ⚠ authCode {echoed:#x} was not issued here; "
                        "this connection stays unnamed"
                    )
                else:
                    self._bind(session, account_id, f"authCode {echoed:#x}")
                return None
            if msg_type == MSG_CL_REQUEST_GAME_LOGIN:
                # Input_MsgSvOkGameServerLogin::deserialize (0x8DB8E0) reads a
                # single u16, which the client's own trace names schoolId.
                #
                # The tail of the request is the accountId this server sent at
                # login, echoed back (`version[12+1]={%c}accountId=%d`). Nothing
                # is decided on it -- 0x0020 arrived first and already named the
                # connection -- but disagreeing with it means one of the two
                # paths is wrong, and a second opinion is only useful if someone
                # looks at it.
                if len(params) >= 4:
                    echoed = struct.unpack_from(">I", params, len(params) - 4)[0]
                    if session.account_id and echoed != session.account_id:
                        print(
                            f"[{self.tag}] ⚠ accountId={echoed} in 0x0200 but the "
                            f"authCode said account {session.account_id}"
                        )
                return self._answer(
                    session, sequence, MSG_SV_OK_GAME_LOGIN, struct.pack(">H", 0)
                )
            if msg_type == 0x0300:
                return self._answer(session, sequence, 0x0301, school_list_params())
            if msg_type == MSG_CL_REQUEST_CHARACTER_CREATE:
                # Three per account, and the cap belongs here because the client
                # has no defence of its own: see characters.MAX_CHARACTERS for
                # what a fourth entry does to its list buffer. KONAMI's server
                # would never have sent one, so refusing is what the client was
                # built to meet.
                if self._chars(session).full():
                    print(
                        f"[{self.tag}] create refused: account already has "
                        f"{MAX_CHARACTERS}; {self._chars(session).summary()}"
                    )
                    return self._answer(
                        session, sequence, MSG_SV_NG_CHARACTER_CREATE, NG_REASON
                    )
                # Output_MsgSvOkCharacterCreate::serialize (0x8DCD80) writes one
                # u32 through the stream's write-u32 slot, and nothing else.
                chara_id = self._chars(session).add(params)
                print(f"[{self.tag}] character #{chara_id}: {describe(params)}")
                return self._answer(
                    session, sequence, MSG_SV_OK_CHARACTER_CREATE, struct.pack(">I", chara_id)
                )
            if msg_type == MSG_CL_REQUEST_CHARACTER_DESTROY:
                # 「キャラクターを削除しています」. The request is one u32 charaId
                # (the shape reader: 0x030f scalar reads=4). Ok takes nothing off the
                # wire — Input_MsgSvOkCharacterDestroy's deserializer is 0x8CB9A0,
                # the same ``xor eax,eax; ret 8`` stub MsgSvOkSchoolLogin uses —
                # but Ng is not that stub and does read one byte, so it goes out
                # with NG_REASON. Either way an unknown id gets an answer rather
                # than silence, which would leave the dialog spinning forever.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                if self._chars(session).remove(chara_id):
                    # Out of everybody's アドレス帳 as well. A row is built from
                    # the character's own record, so an edge to a deleted one
                    # would not show a stale name -- it would show nothing at
                    # all, and the friend on the other side would be left with a
                    # book they cannot repair from any button on screen.
                    self.accounts.friends.forget(chara_id)
                    # And out of any 仲良しグループ, which for a leader means the
                    # group goes with them -- see groups.GroupBook.leave.
                    self.accounts.groups.forget(chara_id)
                    print(f"[{self.tag}] deleted charaId={chara_id}; left: {self._chars(session).summary()}")
                    return self._answer(session, sequence, MSG_SV_OK_CHARACTER_DESTROY, b"")
                print(f"[{self.tag}] destroy: no charaId={chara_id}, answering Ng")
                return self._answer(session, sequence, MSG_SV_NG_CHARACTER_DESTROY, NG_REASON)
            if msg_type == MSG_CL_REQUEST_REENTRANCE:
                # 「再入学しています」, the 再入学する button on the character-select
                # screen. Request is one u32 charaId (the shape reader: 0x031b scalar
                # reads=4), matching the 00000001 seen on the wire.
                #
                # What it means, per the manual (manual/p02_06 and p09_02): after
                # a 恋愛候補生 confesses, re-enrolling wipes *that* candidate's
                # memory of the player so a different romance can be started.
                # Everything else — abilities, keywords, club techniques, items,
                # the address book — explicitly survives. So it is a targeted
                # reset, not a new game.
                #
                # Unreachable from the UI now, and left in place anyway. The
                # button that sends this greys itself when the character-list
                # entry carries capturedNpcId = 0xFFFF, which is what this server
                # always sends because it models no romance state at all
                # (characters.NO_CAPTURED_NPC, where the three-notebook
                # measurement behind that is written down). So nobody can ask for
                # a re-enrollment any more.
                #
                # Should the request arrive regardless, Ok is still the honest
                # answer: there is no capture on record, which is exactly the
                # state re-enrollment is asking to be put in. A server that grows
                # a romance system will want Ng here instead —
                # reference/idlist/error_message.txt #44 is 「再入学の手続きに必要な
                # 条件を満たしていません。」, though whether Ng's one byte indexes
                # that table has not been checked.
                #
                # Input_MsgSvOkReentrance's vtable[0] is 0x8CB9A0, the shared
                # zero-param stub, so the Ok carries nothing. Ng is not empty:
                # its reader is 0x8D84A0, which takes one byte through the
                # stream's +0x1C slot — the same one-byte error code
                # MsgSvErrorCharaInfo uses.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                if self._chars(session).find(chara_id) is None:
                    print(f"[{self.tag}] reentrance: no charaId={chara_id}, answering Ng")
                    return self._answer(session, sequence, MSG_SV_NG_REENTRANCE, bytes(1))
                print(f"[{self.tag}] reentrance for charaId={chara_id} (no romance state to clear)")
                return self._answer(session, sequence, MSG_SV_OK_REENTRANCE, b"")
            if msg_type == MSG_CL_QUERY_CHARACTER_LIST:
                # 238 bytes per entry; see characters.py for where each field
                # came from. An empty list here is what sent the client back to
                # the school screen right after it made a character.
                print(f"[{self.tag}] characters: {self._chars(session).summary()}")
                return self._answer(
                    session, sequence, MSG_SV_RESULT_CHARACTER_LIST, self._chars(session).entries()
                )
            if msg_type == 0x0303:
                # Reply ids run Request/Ok/Ng in threes (0x0200/01/02 did), so
                # MsgClRequestSchoolSelect(0x0303) answers as 0x0304.
                #
                # A third connection is about to open, and it will know nothing
                # about this one, so it gets its own ticket for the same account.
                #
                # ⚠️⚠️ Same fallback as _chars (see _fallback_account), and the
                # same reason to gate it: an unnamed connection asking for the
                # school hop must not be handed a ticket that names account 1,
                # because the school connection would redeem it and land there.
                # In normal play this is never reached unbound -- 0x0303 arrives
                # on the game connection, which echoed its authCode first.
                account_id = session.account_id or self._fallback_account(session)
                if account_id is None:
                    print(
                        f"[{self.tag}] ⚠ school hop requested before naming an "
                        f"account, from {session.peer_host}; refusing"
                    )
                    return None
                auth_code = self.tickets.issue(account_id)
                print(
                    f"[{self.tag}] school hop {self.advertise_ip}:{SCHOOL_PORT}, "
                    f"authCode={auth_code:#x} for account {account_id}"
                )
                return self._answer(
                    session,
                    sequence,
                    0x0304,
                    ok_school_select_params(
                        self.advertise_host_be, auth_code=auth_code
                    ),
                )
            if msg_type == MSG_CL_REQUEST_SCHOOL_LOGIN:
                # 「登校処理を行っています」. The request carries the u32 charaId
                # picked on the character screen; the answer carries nothing at
                # all — Input_MsgSvOkSchoolLogin's deserializer is 0x8CB9A0,
                # the shared ``xor eax,eax; ret 8`` stub, and its dump function
                # (0x8F75F0) prints the message name and no fields.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                session.chara_id = chara_id
                session.map_id, *pos = self._chars(session).location(chara_id)
                session.pos = (pos[0], pos[1])
                # ⭐⭐⭐ 初登校. The flag went out with the character list this
                # 登校 was picked off (characters.list_entry's tutorialFlag), so
                # by the time this message arrives the client already has the
                # answer and the select screen is gone -- which makes this the
                # moment it stops being true. `location` above has already put
                # the character where the tutorial ends; from here on it is
                # 「前回ログアウトした場所」 like everybody else.
                #
                # ⚠️ Cleared whether or not the client actually played the
                # tutorial. Nothing on this wire says it did, and the alternative
                # -- keep the flag until something confirms it -- would replay
                # the tutorial on every 登校 for as long as that confirmation
                # never comes. /tutorial re-arms it.
                if self._chars(session).debut_pending(chara_id):
                    session.direction = DEBUT_FACING
                    print(f"[{self.tag}] ⭐ 初登校 for charaId={chara_id}: "
                          f"tutorialFlag was 1, standing at map {session.map_id} "
                          f"{session.pos} facing {facing.NAMES.get(session.direction, '?')}")
                    # ⭐⭐ Round 194: say so in the save before the flag goes.
                    # The 初登校 about to play is what puts 天宮/桜井 on stage
                    # (romance.absorb), and `characters.romance()` can only tell
                    # an un-recorded old debut from a pending one while this flag
                    # still stands. So an old record gets its empty cast written
                    # down here, in the one moment both facts are true at once;
                    # see CharacterStore.declare_empty_cast for the run that
                    # measured what happens without it.
                    if self._chars(session).declare_empty_cast(chara_id):
                        print(f"[{self.tag}]   恋愛の記録が無いので「未登場」を記帳"
                              f"（初登校がこれから書き込む）")
                    self._chars(session).set_debut_pending(chara_id, False)
                # Swallow the bells for the lesson already under way, so that
                # 登校 at 14:53 does not ring the 14:45 本鈴 at someone who
                # could not have attended it anyway.
                session.bell.prime()
                # 登校回数 and the clock behind 累計登校時間. This message *is*
                # 登校, which is why the 経歴 card's two counted fields are
                # counted here and nowhere else -- career.py's docstring says
                # why they are the two nothing else in this server knows.
                state = self._chars(session).career(chara_id)
                if state is not None:
                    visits = state.arrive()
                    self._chars(session).set_career(chara_id, state)
                    print(f"[{self.tag}] 登校 #{visits} for "
                          f"charaId={chara_id}: {state.summary()}")
                session.arrived_at = time.monotonic()
                begins, subject = curriculum.next_lesson()
                print(
                    f"[{self.tag}] school login for charaId={chara_id}, last on map "
                    f"{session.map_id} ({MAP_NAMES.get(session.map_id, '?')}) at {session.pos}"
                )
                print(
                    f"[{self.tag}] 次の授業 {begins:%H:%M} "
                    f"{curriculum.SUBJECTS[subject]}, 教室 map "
                    f"{lesson.classroom_of(session.in_class)}"
                )
                return self._answer(session, sequence, MSG_SV_OK_SCHOOL_LOGIN, b"")
            if msg_type == MSG_CL_REQUEST_SCHOOL_LOGOUT:
                # 下校: the オプション menu's ログアウト, after its confirm dialog.
                # The request takes nothing off the wire and neither does the
                # answer — Input_MsgSvOkSchoolLogout's vtable[0] is 0x8CB9A0, the
                # shared ``xor eax,eax; ret 8`` stub that MsgSvOkSchoolLogin and
                # MsgSvOkCharaWarp also use.
                #
                # Going unanswered is what made logging out mean killing the
                # client: the two archived attempts (round20, round22d) both show
                # the cast, then five seconds of nothing, then the client putting
                # up another dialog and dropping the connection — after which the
                # whole updater → login → 選校 → 選角 chain had to be walked again
                # to get back in.
                #
                # Position is already on disk: every MsgClCastCharaMove and every
                # warp writes through to characters.json, so there is nothing to
                # flush here. What does have to go is the session's idea of who is
                # playing — if the client stays on this connection and walks back
                # in, MsgClRequestSchoolLogin sets it again, and if it instead
                # sends a lobby start without one, adding nobody beats adding the
                # character who just left.
                print(
                    f"[{self.tag}] school logout for charaId={session.chara_id}, "
                    f"last on map {session.map_id} "
                    f"({MAP_NAMES.get(session.map_id, '?')}) at {session.pos}"
                )
                self._career_depart(session)
                # Same treatment as the disconnect path: 「中断」 takes this
                # player out of the fight, and the fight carries on for whoever
                # is left rather than being taken off the board (Fighter.gone).
                # The survivors get the same 0x5C1B for the same reason the
                # room's 0x580D says 「切断による」 here: 0x5C1B has exactly two
                # reasons and the other one is 「サーバーとクライアントとの同期が
                # 取れません」, which this is not.
                #
                # ⚠️ Fight before room, the same order the disconnect path uses
                # and for the same measured reason — see the ORDER note there.
                gone = (
                    self.battles.leave(session.chara_id) if session.chara_id else None
                )
                if gone is not None:
                    self._cb_part_notice(
                        gone, session.chara_id, clubbattle.PART_DISCONNECTED
                    )
                    self._battle_carry_on(gone)
                    print(f"[{self.tag}] battle left at logout, "
                          f"now {self.battles.summary()}")
                # ⚠️⚠️ The same 0x4810 the disconnect path owes the others, for
                # the same reason and in the same place in the order. MEASURED
                # round 148, and the failure was neither an error nor a stale
                # sprite: without it the peers keep the leaver in their scene,
                # and the *next* login hands them a second 0x480F for a charaId
                # they still hold. Round 67 measured what a repeated add does to
                # a roster (it counts the person twice); on the map it puts the
                # right-click menu of that character entirely out of action --
                # all six icons grey, zero bytes on click -- and nothing on
                # screen says why. Relogging the *viewer* clears it, which is
                # what pinned the state to the viewer's copy rather than to the
                # leaver's record.
                #
                # ⚠️ This connection stays live (it is going to the character
                # select, not closing), so _peers still finds the audience --
                # unlike the disconnect path, which has to pass its watchers in
                # because it takes the session out of self.live first.
                peers = self._peers(session)
                if peers:
                    self._presence_withdraw(session, peers)
                # ⚠️ A 看板 has to come down here and not only on disconnect:
                # 「ゲームを中断（キャラクター選択画面に戻る）しても、退出する
                # ことになります」 (p07_06), and clearing chara_id below would
                # otherwise strand the room where nothing can reach it again.
                room = (
                    self.trainingrooms.room_of(session.chara_id)
                    if session.chara_id else None
                )
                if room is not None:
                    leader_id = room.leader_id
                    self.trainingrooms.part(session.chara_id)
                    # 「切断による」 for a 「中断」 as well: the other two reasons are
                    # 0x5809 and 0x581C, and this is neither. Nothing goes to the
                    # leaver — they are on their way to the character select and
                    # part() has already taken them out of the member list.
                    self._tr_part_notice(
                        room, session.chara_id, leader_id,
                        trainingroom.PART_REASON_DISCONNECTED,
                    )
                    print(f"[{self.tag}] trainingroom dropped at logout, "
                          f"now {self.trainingrooms.summary()}")
                session.chara_id = 0
                return self._answer(session, sequence, MSG_SV_OK_SCHOOL_LOGOUT, b"")
            if msg_type == MSG_CL_QUERY_POOL_MESSAGE:
                # Last step of the reload the client runs after a cutscene:
                # 0x4000, then the character and the NPCs go down, then it asks
                # for its own info and its pooled messages. This is the earliest
                # point a *push* survives; see _drain_pending_say. Falls through
                # to the table for the Ok.
                if session.pending_say:
                    session.say_armed = True
                # ⚠️ The ストレスバー is in the same boat, and it took a screenshot
                # to notice: a 0x4811 sent while the lobby is still loading is
                # accepted and then thrown away with the scene, so a player who
                # logged in with stress on the clock had no bar at all until
                # something moved the number. Forgetting what was sent makes the
                # next drain state it again, on this side of the reload.
                session.sent_stress = -1
                session.sent_condition = -1
            if msg_type == MSG_CL_REQUEST_LOBBY_DATA_START:
                # The Ok alone is not enough: the client sat here silently, never
                # sending MsgClRequestLobbyDataEnd, with a black screen. Nothing
                # had ever put its character into the scene, so push a
                # MsgSvNotifyCharacterAdd right behind the Ok. Two packets in one
                # write is fine — the client's parser reads them off the stream in
                # order, and every other reply already goes out as one blob.
                reply = self._answer(session, sequence, MSG_SV_OK_LOBBY_DATA_START, b"")
                info = self._chars(session).find(session.chara_id)
                if info is None:
                    print(f"[{self.tag}] lobby: no charaId={session.chara_id}, adding nobody")
                    return reply
                # The player, plus a stand-in per marker. Markers used to be
                # guesses — decoration coordinates that say where a thing is but
                # not whether the ground under it can be walked on — and every
                # batch had to be rated by eye. The doorway cells out of the
                # collision files need no rating: the player has to be able to
                # stand on one to walk through it.
                markers = session.markers()
                # The facing goes in too: a warp sets one and then triggers the
                # very reload that runs this, so leaving it off would land the
                # character on the new map turned whichever way add_entry
                # defaults to, undoing the direction the warp just chose.
                entries = [
                    add_entry(
                        session.chara_id,
                        info,
                        pos=session.pos,
                        map_id=session.map_id,
                        direction=session.direction,
                        group_id=self.accounts.groups.id_of(session.chara_id),
                    )
                ]
                for index, (label, pos_x, pos_y) in enumerate(markers):
                    entries.append(
                        add_entry(
                            PROBE_ID_BASE + index,
                            info,
                            pos=(pos_x, pos_y),
                            names=marker_names(label),
                            map_id=session.map_id,
                        )
                    )
                # And everybody else already standing here. This runs on every
                # lobby load, not just the first, so a player who warps indoors
                # and back arrives with the current scene rather than the one
                # that was true at 登校.
                peers = self._peers(session)
                for other in peers:
                    peer_entry = self._presence_entry(other)
                    if peer_entry is not None:
                        entries.append(peer_entry)
                # Sent in batches rather than as one 72-entry message. The client
                # copies a message's parameters into a buffer of a size it fixed
                # in advance, and mpsClientMessage::input (0xA45CD0) does not drop
                # anything that overflows it — it logs "too large parameter" and
                # then *clamps the length to the capacity*, so an oversized push
                # would arrive silently truncated in the middle of an entry. That
                # capacity is a field rather than an immediate, so its value is
                # not known; staying near the sizes already known to work is
                # cheaper than finding out the hard way, and nothing says this
                # notify may only be sent once.
                for batch in range(0, len(entries), ADD_BATCH):
                    part = entries[batch : batch + ADD_BATCH]
                    reply += self._answer(
                        session,
                        sequence,
                        MSG_SV_NOTIFY_CHARACTER_ADD,
                        struct.pack(">H", len(part)) + b"".join(part),
                    )
                # And the chibis, after the characters rather than before: the
                # spawner runs a placement script of its own, and there is no
                # reason to have it racing the scene it is placing them into.
                for spawn in session.npc_spawns:
                    reply += self._answer(
                        session, sequence, chat.MSG_SV_NOTIFY_NPC_CONTROL, spawn
                    )
                extra = f" plus {len(markers)} markers" if markers else ""
                if session.npc_spawns:
                    extra += f" and {len(session.npc_spawns)} NPCs"
                if peers:
                    extra += f" and {len(peers)} other player(s)"
                print(
                    f"[{self.tag}] lobby: adding charaId={session.chara_id}{extra} to map "
                    f"{session.map_id} ({MAP_NAMES.get(session.map_id, '?')}) at {session.pos}"
                    f", in {-(-len(entries) // ADD_BATCH)} batches"
                )
                # The other direction, once this scene is built: they can see the
                # peers now, so the peers have to be told about them.
                self._presence_announce(session)
                # ⚠️ Both directions, and both AFTER the 0x480F batches above:
                # 0x4D06 names a charaId the client has to be holding already,
                # so dressing anybody ahead of the add that creates them would
                # be talking about somebody who is not in the scene yet.
                return (reply + self._equip_replay(session)
                        + self._equip_replay_peers(session, peers))
            if msg_type == MSG_CL_QUERY_CHARA_INFO:
                # 「サーバーからの返答待ちです」 in the lobby: the client asks this
                # about every character it has been told to draw, one u32 charaId
                # at a time, and the answer carries the record with no id echoed
                # back. The Error reply takes a single byte — the shape reader calls it
                # empty, but its reader is the shared 0x8D84A0, which reads one
                # field through the stream vtable's +0x1C slot (0xA49960, one byte),
                # a slot the shape reader does not know about.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                info = self._chars(session).find(chara_id)
                if info is None:
                    # Somebody else's character. This is the first question the
                    # client asks about a person it has been told to draw, and
                    # answering Error is what 「選択されたキャラクターの情報が
                    # 不正です。」 on the right-click is made of -- which in turn
                    # is what stood between two players and a 自主トレ room.
                    # ⚠️ The record has to come out of the owner's store: every
                    # account keeps its own (round 68), so this connection's store
                    # simply does not have somebody else's character.
                    info = self._peer_chara(chara_id)
                if info is None and PROBE_ID_BASE <= chara_id < PROBE_ID_LIMIT:
                    # A stand-in — a doorway marker or a direction probe. None of
                    # them has a record of its own; hand back the player's, since
                    # all the client wants is something to draw. The test is the
                    # whole id range rather than the marker count because the
                    # ruler's ids sit past the markers', and a stand-in that gets
                    # an Error back is one the client draws nothing for.
                    info = self._chars(session).find(session.chara_id)
                if info is None:
                    print(f"[{self.tag}] chara info: no charaId={chara_id}, answering Error")
                    return self._answer(session, sequence, MSG_SV_ERROR_CHARA_INFO, bytes(1))
                print(f"[{self.tag}] chara info for charaId={chara_id}")
                # The four 仲良しグループ fields. The book is one table for the
                # whole server, so unlike the club flag there is no owner store
                # to look the asked-about character up in.
                gname, gid, authority, qualification = self.accounts.groups.fields(chara_id)
                # ⚠️ Same owner-store rule as in_club below: 恋人 is a fact about
                # the character being asked about, so it comes out of whichever
                # account holds that id, not out of the asker's store.
                owner = self.accounts.owner_of(chara_id) or self._chars(session)
                lover = owner.lover(chara_id)
                # ⚠️ Same owner-store rule again: a 役職 and a 称号 are facts
                # about the character being asked about. The name card that
                # comes out of this message has a 「所属部：%1%  役職：%2%」 line
                # (posts.py), so this is the copy that decides whether it is
                # drawn with a post or without one.
                held = owner.posts(chara_id) or posts.Posts()
                title = owner.title(chara_id)
                if (held.class_post != posts.CLASS_POST_NONE
                        or held.club_post != posts.NO_CLUB_POST or title):
                    print(f"[{self.tag}]   posts: {held.summary()} title={title} "
                          + " ".join(posts.club_post_readings(
                              held.club_post, owner.in_club(chara_id))))
                if lover:
                    print(f"[{self.tag}]   couple: loverCharaId={lover} (coupleFlag=1)")
                if gid or qualification:
                    shown = gname.split(b"\x00")[0].decode("cp932", "replace")
                    print(f"[{self.tag}]   group: id={gid} name={shown!r} "
                          f"leaderAuthority={authority} qualified={qualification}")
                return self._answer(
                    session,
                    sequence,
                    MSG_SV_RESULT_CHARA_INFO,
                    # The club flag out of the owner's store too, for the same
                    # reason the record is: asking this connection's store about
                    # somebody else's id answers about nobody.
                    chara_info(
                        info,
                        in_club=owner.in_club(chara_id),
                        group_name=gname,
                        group_id=gid,
                        leader_authority=authority,
                        leader_qualification=qualification,
                        lover_chara_id=lover,
                        title=title,
                        class_post=held.class_post,
                        club_post=held.club_post,
                    ),
                )
            if msg_type == curriculum.MSG_CL_QUERY_CURRICULUM:
                # 「生徒情報」→「時間割」. The request is empty and the answer is
                # four bytes of clock; the grid itself is drawn from the
                # client's own class_schedule.bin, which is why nothing about
                # the timetable crosses the wire. That makes the school clock
                # server policy in full — see curriculum.clock().
                body = curriculum.result_curriculum(exam_period=session.exam.on)
                type_id, day, hour, minute = struct.unpack(">bbBB", body)
                subject = curriculum.SUBJECTS[curriculum.current_subject()]
                print(
                    f"[{self.tag}] curriculum: 曜日={day} {hour:02d}:{minute:02d} "
                    f"timeTable={type_id}, this period is {subject}"
                )
                return self._answer(
                    session, sequence, curriculum.MSG_SV_RESULT_CURRICULUM, body
                )
            if msg_type == options.MSG_CL_QUERY_OPTION:
                # オプション, the four flags that cross the wire. Asked once
                # during 登校, right after the friend list. Answered out of the
                # character's own record since round 152; before that it was a
                # constant in FIXED_REPLIES, which was fine right up to the
                # moment one of the four had to mean something -- and 通知表公開
                # does, one branch down.
                #
                # ⚠️ Nothing has been seen asking this before a character is
                # picked, but a connection that did would have chara_id 0 and no
                # record; the defaults answer it, and they are byte for byte
                # what this server sent for the 140 rounds before the record
                # existed. Nobody's settings moved when this stopped being a
                # constant.
                opts = (
                    self._chars(session).options(session.chara_id)
                    or options.GameOptions()
                )
                print(f"[{self.tag}] option: {opts.summary()}")
                return self._answer(
                    session,
                    sequence,
                    options.MSG_SV_RESULT_OPTION,
                    opts.result_params(),
                )
            if msg_type == options.MSG_CL_REQUEST_GAME_OPTION_UPDATE:
                # The push-back half: the same four u8 coming the other way when
                # the player closes the オプション window. This went unanswered
                # until round 152 on the grounds that オプション is a client-side
                # window and nothing had ever sent it -- ⚠️ which was never
                # measured, only assumed, and a Request that goes unanswered is
                # the 「通信中」 wedge this project has now paid for twice.
                #
                # ⭐⭐ Round 152 pressed ［適 用］ with 通知表公開 alone flipped
                # and got 01 01 01 00 -- byte three, and only byte three. So the
                # four u8 really are 0x0701's four in 0x0701's order, measured
                # rather than inferred. The log below names each byte, which is
                # what made that readable at a glance; keep it that way.
                values = options.parse_update(params)
                opts = self._chars(session).options(session.chara_id)
                if values is None or opts is None:
                    print(f"[{self.tag}] option update: short body or no "
                          f"charaId={session.chara_id}, answering Ng")
                    return self._answer(
                        session,
                        sequence,
                        options.MSG_SV_NG_GAME_OPTION_UPDATE,
                        NG_REASON,
                    )
                was = opts.summary()
                opts.update(values)
                self._chars(session).set_options(session.chara_id, opts)
                print(f"[{self.tag}] option update: {opts.summary()} (was {was})")
                return self._answer(
                    session, sequence, options.MSG_SV_OK_GAME_OPTION_UPDATE, b""
                )
            if msg_type == curriculum.MSG_CL_QUERY_SCORE_CARD:
                # 「生徒情報」→「通知表」. One u32 charaId, because a player can
                # look at someone else's if that character's 通知表公開 is on.
                #
                # ⭐⭐ Round 151: the PC menu's 「通知表を見る」 sends this very
                # message with *the other player's* charaId, so this is not only
                # the 生徒情報 window's own query -- and until that round this
                # branch let a peer's card fall out through 「no charaId=…」
                # below, which reads like a lookup bug rather than the policy it
                # is. Round 152 made the policy real: the permission is the
                # owner's ``scorecard`` flag (options.py), read out of the
                # OWNER's store the way chara_info reads the record itself.
                # Asking this connection's store about somebody else's id
                # answers about nobody -- accounts keep separate stores.
                #
                # ⚠️ Which flag is consulted is the owner's, never the asker's:
                # 通知表公開 is a permission a player grants about their own
                # card. A viewer looking at their own card needs no permission,
                # hence the chara_id == session.chara_id shortcut staying in.
                #
                # The three 必要 columns are absent from the answer on purpose:
                # they are not on the wire at all, and the client fills them
                # from lesson.bin. Whether it really does is what opening this
                # screen is meant to show.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                store = self._chars(session)
                if chara_id != session.chara_id:
                    store = self.accounts.owner_of(chara_id) or store
                    opts = store.options(chara_id)
                    if opts is None or not opts["scorecard"]:
                        why = "unknown character" if opts is None else "通知表公開 is off"
                        print(f"[{self.tag}] scorecard for charaId={chara_id}: "
                              f"refused, {why}")
                        return self._answer(
                            session, sequence, curriculum.MSG_SV_ERROR_SCORE_CARD, bytes(1)
                        )
                card = store.scorecard(chara_id)
                names = store.full_name(chara_id)
                if card is None or names is None:
                    print(f"[{self.tag}] scorecard: no charaId={chara_id}, answering Error")
                    return self._answer(
                        session, sequence, curriculum.MSG_SV_ERROR_SCORE_CARD, bytes(1)
                    )
                print(f"[{self.tag}] scorecard for charaId={chara_id}: {card.summary()}")
                return self._answer(
                    session,
                    sequence,
                    curriculum.MSG_SV_RESULT_SCORE_CARD,
                    card.params(names[0], names[1]),
                )
            if msg_type == ability.MSG_CL_QUERY_CHARA_MENU_ABILITY:
                # 「生徒情報」→ the ability tab. One u32 charaId, the same shape
                # and for the same reason as the 通知表 query above.
                #
                # testLevel is taken from the ScoreCard rather than stored on
                # the sheet: it is a function of which 課程 are 修了, and the
                # 通知表 already answers it. Two copies would be two answers.
                #
                # ⚠️ …minus one, because this field is zero-based and
                # ScoreCard.test_level() is not. Measured: a character with no
                # 課程 finished is 試験レベル１ by `p06_01`, test_level() says 1,
                # and the screen drew 「試験レベル２」. Same base as 0x430D's
                # testLv (curriculum.TESTLV_BASE), which was measured the same
                # way and off by one in the same direction. The correction has
                # since been read back off the screen too: the same character
                # now draws 「試験レベル１」.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                sheet = self._chars(session).ability(chara_id)
                card = self._chars(session).scorecard(chara_id)
                if sheet is None or card is None:
                    print(f"[{self.tag}] ability: no charaId={chara_id}, answering Error")
                    return self._answer(
                        session, sequence, ability.MSG_SV_ERROR_CHARA_MENU_ABILITY, bytes(1)
                    )
                print(f"[{self.tag}] ability for charaId={chara_id}: {sheet.summary()}")
                return self._answer(
                    session,
                    sequence,
                    ability.MSG_SV_RESULT_CHARA_MENU_ABILITY,
                    sheet.result_params(card.test_level() - 1),
                )
            if msg_type in (career.MSG_CL_QUERY_CHARA_CAREER,
                            career.MSG_CL_QUERY_CHARA_CAREER_LIST):
                # 「経歴」 -- the 生徒情報 window's last tab, and the bottom-right
                # icon of the PC 交流メニュー when it is somebody else's. Two
                # queries, each one u32 charaId, and the same permission in
                # front of both: 経歴公開, the fourth オプション flag, read out
                # of the OWNER's store exactly the way 通知表公開 is above.
                #
                # ⭐ 0x4315 is the row that used to sit in FIXED_REPLIES, and
                # what took it out is career.py -- the refusal was for lack of a
                # card, not for lack of permission, and the flag had no reader
                # anywhere. It has one now, which is the whole point of the
                # exercise: 0x0703 could turn 経歴公開 ON since round 152 and
                # nothing downstream could tell.
                #
                # ⚠️ The two queries are answered together because they are
                # one screen, and that turned out to be load-bearing rather
                # than tidy: 0x4318 had never arrived in any log, and it flew
                # in the very next packet after the first 0x4316 went out. It
                # is sent once the card is up, so it could not have been seen
                # before the card existed. A window that opens and then hangs
                # on its second question is worse than one that never opens --
                # item.py's ALL FOUR OR NONE, for the same reason.
                #
                # ⚠️⚠️ THE TWO DO NOT ALWAYS NAME THE SAME PERSON. Right-click
                # someone and pick 経歴を見る and 0x4315 carries THEIR charaId
                # while the 0x4318 behind it carries YOUR OWN -- measured
                # twice, same both times. So the 過去の実績 pane on somebody
                # else's card lists the viewer's achievements. That is the
                # client's doing; each query is answered for the id it names,
                # because guessing who it "meant" would turn a difference that
                # can be seen into an assumption that cannot.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                store = self._chars(session)
                if chara_id != session.chara_id:
                    store = self.accounts.owner_of(chara_id) or store
                    opts = store.options(chara_id)
                    if opts is None or not opts["career"]:
                        why = "unknown character" if opts is None else "経歴公開 is off"
                        print(f"[{self.tag}] career for charaId={chara_id}: "
                              f"refused, {why}")
                        return self._answer(
                            session, sequence,
                            career.MSG_SV_ERROR_CHARA_CAREER, bytes(1)
                        )
                state = store.career(chara_id)
                if state is None:
                    print(f"[{self.tag}] career: no charaId={chara_id}, answering Error")
                    return self._answer(
                        session, sequence, career.MSG_SV_ERROR_CHARA_CAREER, bytes(1)
                    )
                if msg_type == career.MSG_CL_QUERY_CHARA_CAREER_LIST:
                    print(f"[{self.tag}] career list for charaId={chara_id}: "
                          f"{len(state.achievements)} 実績")
                    out = b""
                    for reply_type, reply_params in career.list_replies(state):
                        out += self._answer(session, sequence, reply_type, reply_params)
                    return out
                names = store.full_name(chara_id)
                if names is None:
                    print(f"[{self.tag}] career: no charaId={chara_id}, answering Error")
                    return self._answer(
                        session, sequence, career.MSG_SV_ERROR_CHARA_CAREER, bytes(1)
                    )
                # 授業出席数 and 習得部活奥義 are read off the 通知表 and the
                # 部活奥義 list rather than stored a second time; career.py says
                # why. Both come out of the same store as the card itself, so a
                # peer's card is a peer's numbers.
                card = store.scorecard(chara_id)
                member = store.club(chara_id)
                attended = sum(card.attendance) if card is not None else 0
                skills = len(member.skills) if member is not None else 0
                # ⚠️ inClass is the same value 0x430D has been sending all
                # along -- see the note on session.in_class. It draws as 組 and
                # not as 期生: the 経歴 window's 「1期生として入学」 line comes
                # from the client's own copy of period, not from this card.
                # Measured with /career probe; career.py's docstring has the
                # whole mapping.
                body = state.params(names[0], names[1], session.in_class,
                                    attended, skills)
                # ⚠️ Decoded back out of the body rather than printed off the
                # record: with /career probe armed the two disagree, and a log
                # that says what was stored while the wire says something else
                # is a log that cannot be used to read the screen.
                print(f"[{self.tag}] career for charaId={chara_id}: "
                      f"{career.describe(body)}")
                return self._answer(
                    session, sequence, career.MSG_SV_RESULT_CHARA_CAREER, body
                )
            if msg_type in (club.MSG_CL_QUERY_KEYWORD_LIST,
                            club.MSG_CL_QUERY_CLUB_SKILL_LIST):
                # The 部活デッキ window, opened from the toolbar. Two queries,
                # each answered with a count and then the rows. Each half is
                # whatever its knob granted — /kw for キーワード, /cs for
                # 部活奥義 — and club.py says why both defaulted to empty and
                # what the grant does and does not invent.
                member = self._chars(session).club(session.chara_id)
                if msg_type == club.MSG_CL_QUERY_KEYWORD_LIST:
                    pairs = club.keyword_replies(member)
                    owned = len(member.keywords) if member else 0
                    print(f"[{self.tag}] club keyword list: {owned} owned")
                else:
                    pairs = club.skill_replies(member)
                    owned = len(member.skills) if member else 0
                    print(f"[{self.tag}] club skill list: {owned} owned")
                out = b""
                for reply_type, reply_params in pairs:
                    out += self._answer(session, sequence, reply_type, reply_params)
                return out
            if msg_type == item.MSG_CL_QUERY_ITEM_LIST:
                # The アイテム window, opened by the toolbar's fourth icon and
                # queried again on every tab click. The u16 it carries is the
                # TAB, not a category — item.py maps one to the other, and says
                # why one query can need more than one notify.
                tab = item.parse_query(params)
                inv = self._chars(session).items(session.chara_id)
                rows = inv.for_tab(tab) if inv is not None else []
                print(f"[{self.tag}] item list: tab {tab} "
                      f"({item.tab_name(tab)}), {len(rows)} rows"
                      + (" [probe: every tab gets everything]"
                         if item.PROBE_ALL_TABS else ""))
                out = b""
                for reply_type, reply_params in item.list_replies(inv, tab):
                    out += self._answer(session, sequence, reply_type, reply_params)
                return out
            if msg_type in ITEM_OPERATIONS:
                # The buttons under that list: 装備 / 使用 / ロッカーにしまう /
                # 捨てる. ⚠️⚠️ ALL FOUR OR NONE. The window serialises its
                # requests -- measured: after one went unanswered the next press
                # only raised 「通信中」 and put nothing on the wire -- so one
                # missing answer freezes every other button too, and a partly
                # implemented window is worse than none.
                #
                # Which sentence a refusal picks is item.py's business, not this
                # branch's: that is where the evidence for each reason is
                # written down, including which ones this server cannot honestly
                # send at all.
                inv = self._chars(session).items(session.chara_id)
                locker = self._locker(session)
                if msg_type == item.MSG_CL_CAST_ITEM_EQUIP:
                    replies, changed = item.equip_replies(
                        inv, session.chara_id, params)
                elif msg_type == item.MSG_CL_CAST_ITEM_USE:
                    replies, changed = item.use_replies(
                        inv, session.chara_id, params)
                elif msg_type == item.MSG_CL_REQUEST_ITEM_PUT_IN_LOCKER:
                    replies, changed = item.put_in_locker_replies(
                        inv, locker, params)
                else:
                    replies, changed = item.del_replies(inv, params)
                if changed and inv is not None:
                    self._chars(session).set_items(session.chara_id, inv)
                    if msg_type == item.MSG_CL_REQUEST_ITEM_PUT_IN_LOCKER:
                        self.accounts.save_locker(session.account_id)
                print(f"[{self.tag}] item {name}: "
                      + " ".join(f"{t:#06x}" for t, _ in replies)
                      + (f" | {inv.summary()}" if inv is not None else "")
                      + (f" | {locker.summary()}" if locker is not None else ""))
                out = b""
                for reply_type, reply_params in replies:
                    # ⭐ The Notify answers carry a charaId and the Ok answers do
                    # not, which is the difference between something other
                    # players watch happen and something only the asker sees.
                    if reply_type in item.RELAYED:
                        self._presence_relay(session, reply_type, reply_params)
                    out += self._answer(session, sequence, reply_type, reply_params)
                return out
            if msg_type in (item.MSG_CL_REQUEST_LOCKER_ACCESS_START,
                            item.MSG_CL_REQUEST_LOCKER_ACCESS_END):
                # The bracket around an open ロッカー window. Both the requests
                # and their Oks read nothing off the wire (the shape reader: empty), so
                # there is nothing to decide -- but they still have to be sent,
                # for the same serialisation reason as the four above.
                reply_type = (item.MSG_SV_OK_LOCKER_ACCESS_START
                              if msg_type == item.MSG_CL_REQUEST_LOCKER_ACCESS_START
                              else item.MSG_SV_OK_LOCKER_ACCESS_END)
                print(f"[{self.tag}] locker {name}")
                return self._answer(session, sequence, reply_type, b"")
            if msg_type == item.MSG_CL_QUERY_LOCKER_LIST:
                # ⭐ The account's store, not the character's -- item.Locker has
                # the client's own sentences that say which. Answered exactly
                # like 0x4D00 because it is read by exactly the same code: one
                # Result with the total, then pages of at most 32 rows.
                tab = item.parse_query(params)
                locker = self._locker(session)
                rows = locker.for_tab(tab) if locker is not None else []
                print(f"[{self.tag}] locker list: tab {tab} "
                      f"({item.tab_name(tab)}), {len(rows)} rows")
                out = b""
                for reply_type, reply_params in item.locker_list_replies(locker, tab):
                    out += self._answer(session, sequence, reply_type, reply_params)
                return out
            if msg_type in (item.MSG_CL_REQUEST_LOCKER_TAKE,
                            item.MSG_CL_REQUEST_LOCKER_DEL):
                # 取り出す / 捨てる inside the locker window. ⚠️ These two count
                # in a u8 where the item window's two count in a u16; see
                # item.parse_locker_quantity.
                inv = self._chars(session).items(session.chara_id)
                locker = self._locker(session)
                if msg_type == item.MSG_CL_REQUEST_LOCKER_TAKE:
                    replies, changed = item.locker_take_replies(inv, locker, params)
                else:
                    replies, changed = item.locker_del_replies(locker, params)
                if changed:
                    self.accounts.save_locker(session.account_id)
                    if msg_type == item.MSG_CL_REQUEST_LOCKER_TAKE and inv is not None:
                        self._chars(session).set_items(session.chara_id, inv)
                print(f"[{self.tag}] locker {name}: "
                      + " ".join(f"{t:#06x}" for t, _ in replies)
                      + (f" | {locker.summary()}" if locker is not None else ""))
                out = b""
                for reply_type, reply_params in replies:
                    out += self._answer(session, sequence, reply_type, reply_params)
                return out
            if msg_type == club.MSG_CL_QUERY_CLUB_DECK_LIST:
                # The third of the 部活デッキ window's queries, and the one it
                # retries until answered. The entries go back out exactly as they
                # came in on 0x5B03; see club.py.
                deck_id = club.parse_deck_query(params)
                member = self._chars(session).club(session.chara_id)
                use = member.use_type(deck_id) if member else club.USE_TYPE_NONE
                items = member.deck(deck_id) if member else []
                print(f"[{self.tag}] club deck {deck_id}: {len(items)} items, "
                      f"useType={use:#04x}")
                return self._answer(
                    session,
                    sequence,
                    club.MSG_SV_RESULT_CLUB_DECK_LIST,
                    club.deck_reply(deck_id, use, items),
                )
            if msg_type == club.MSG_CL_REQUEST_CLUB_DECK_UPDATE:
                # 「更 新」. ⭐ This is the only place the client ever spells out
                # a useType, which makes answering it the way to measure that
                # byte — it comes back on the next 0x5B01 and the window draws
                # whatever we were told.
                parsed = club.parse_deck_update(params)
                if parsed is None:
                    # Either too short or a count that does not match the body
                    # length. ⚠️ Log the raw bytes: if the seven-byte entry ever
                    # turns out to be wrong, this line is where it shows up.
                    print(f"[{self.tag}] club deck update: body does not fit "
                          f"deckId+count+7×count+useType, raw={params.hex()}")
                    return self._answer(
                        session,
                        sequence,
                        club.MSG_SV_NG_CLUB_DECK_UPDATE,
                        struct.pack(">BH", club.NG_DECK_NOT_FOUND, 0),
                    )
                deck_id, items, use = parsed
                member = self._chars(session).club(session.chara_id)
                if member is None:
                    return self._answer(
                        session,
                        sequence,
                        club.MSG_SV_NG_CLUB_DECK_UPDATE,
                        struct.pack(">BH", club.NG_DECK_NOT_FOUND, 0),
                    )
                # ⭐ Every entry gets logged as it arrived AND as the guessed
                # reading of it, because 0x5B03 is the only place the client ever
                # spells out a deck entry — this is the measurement, and it is
                # still worth reading even though storing does not depend on it.
                for kind, payload in items:
                    print(f"[{self.tag}] club deck update {deck_id} item: "
                          f"{club.describe_deck_item(kind, payload)}")
                member.deck_use[deck_id] = use
                member.set_deck(deck_id, items)
                self._chars(session).set_club(session.chara_id, member)
                print(f"[{self.tag}] club deck update {deck_id}: {len(items)} items, "
                      f"useType={use:#04x}")
                return self._answer(
                    session,
                    sequence,
                    club.MSG_SV_OK_CLUB_DECK_UPDATE,
                    struct.pack(">B", deck_id & 0xFF),
                )
            if msg_type == club.MSG_CL_REQUEST_CLUB_ENTER:
                # 「入部」 off a 顧問/キャプテン's right-click menu. The clubId is
                # the NPC's own, read out of the client's common_npc.bin, so the
                # only thing that can be wrong with it here is that this server
                # let something write a placeholder key into a save file.
                #
                # ⚠️ The Ok carries nothing, so the client is not told what it
                # is now in — it already knows. What has to be right is the next
                # 0x6501 and the next character list, which is where inClub is
                # actually drawn.
                return self._club_enter(session, sequence, params)
            if msg_type == club.MSG_CL_REQUEST_CLUB_PART:
                # 「退部」, and the request is empty: a character is in at most
                # one club, so there is nothing to name.
                return self._club_part(session, sequence)
            if msg_type >> 8 == 0x58 and msg_type <= trainingroom.MSG_SV_ERROR_KICK:
                # 自主トレ, the 看板 room. ⭐ This is クラブ対戦's only entry that
                # is not a 顧問/キャプテン right-click, which is what makes it
                # reachable at all here — see trainingroom.py.
                return self._trainingroom(session, sequence, msg_type, params)
            if msg_type >> 8 == 0x5C:
                # クラブ対戦 itself. ⚠️ A SEPARATE FAMILY from the 0x58xx above
                # even though 自主トレ is what reaches it here: 練習 and
                # フリー対戦 arrive at the same messages through a door this
                # server cannot open. See clubbattle.py.
                return self._clubbattle(session, sequence, msg_type, params)
            if msg_type == lesson.MSG_CL_REQUEST_LESSON_READY:
                # The client sends this by itself, as part of tearing the scene
                # down after 0x6000 — there is no prompt and no button, so the
                # player never chose to be here. The body is empty: it asserts
                # nothing, not even which lesson it means, so every condition
                # `p06_02` lists is checked here or not at all.
                #
                # ⚠️ Refusing costs the player the connection (see NG_REASON and
                # Bell.poll), which is why the conditions are also checked before
                # the bell goes out rather than only here.
                refusal = session.bell.admit(
                    session.map_id, session.in_class,
                    neurotic=self._neurotic(session),
                    attends=self._attends(session, sitting=False),
                )
                if refusal is not None:
                    sent = lesson.refusal_reason(refusal)
                    note = "" if sent == refusal else f" (probe, really {refusal})"
                    print(f"[{self.tag}] lesson ready refused, reason={sent}{note}")
                    return self._answer(
                        session,
                        sequence,
                        lesson.MSG_SV_NG_LESSON_READY,
                        lesson.ng_params(sent),
                    )
                subject = session.bell.subject
                print(
                    f"[{self.tag}] lesson ready ok: {curriculum.SUBJECTS[subject]} "
                    f"in map {session.map_id}"
                )
                reply = self._answer(
                    session, sequence, lesson.MSG_SV_OK_LESSON_READY, b""
                )
                # The Ok on its own leaves the client sitting in a black screen
                # for as long as anyone cares to watch — it waits, it does not
                # time out, and it does not come back. The seat list is what it
                # is waiting for, so it goes out in the same packet.
                return reply + self._lesson_start(session, sequence, subject)
            if msg_type == exam.MSG_CL_REQUEST_EXAM_READY:
                # 0x6601's twin of the 授業 doorway, and the client sends it by
                # itself for the same reason: the bell tore the scene down and
                # nothing asked the player. Same admission rule, same cost for
                # refusing — see Bell.poll — plus the one rule that is only an
                # exam's, 「１科目につき１回しか受けられません」.
                return self._exam_ready(session, sequence)
            if msg_type == exam.MSG_CL_REQUEST_EXAM_START:
                # The scene is built; the client is asking for the paper.
                return self._exam_start(session, sequence)
            if msg_type == exam.MSG_CL_NOTIFY_EXAM_ANSWER_STATE:
                # The mark sheet, unprompted and unanswered. Kept so that a
                # paper the ten-minute bell interrupts still has answers on it.
                return self._exam_sheet(session, params, "answer state")
            if msg_type == exam.MSG_CL_REQUEST_EXAM_PART:
                # 退出. The same bytes, but this one commits: it is the only
                # place an exam reaches the save file.
                return self._exam_part(session, sequence, params)
            if msg_type == lesson.MSG_CL_CAST_LESSON_ANSWER:
                # 「答えを選択し左クリックで解答します」. Two u8: which question it
                # is answering and which choice was clicked. Deserializer
                # 0x008E4FF0 — u8 at +4, u8 at +5, nothing else.
                #
                # Nothing goes back now. `p06_02` step 3 puts the reveal at
                # 「残り時間が０になると」, not at the click, so the 0x6106 this
                # earns is sent by the clock in _drain_lesson. A Cast has no
                # reply by convention anyway.
                question_no, choice_id = struct.unpack_from(">BB", params, 0) \
                    if len(params) >= 2 else (0, 0)
                period = session.lesson
                if period is None or not period.take_answer(question_no, choice_id):
                    print(f"[{self.tag}] answer ignored: questionNo={question_no} "
                          f"choiceId={choice_id}")
                    return b""
                print(f"[{self.tag}] answer: questionNo={question_no} "
                      f"(ours is {period.question_no}, so the client counts from "
                      f"{'one' if question_no == period.question_no else 'zero'}) "
                      f"choiceId={choice_id} "
                      f"({'○' if period.would_be_right() else '×'} once time is up)")
                return b""
            if msg_type == lesson.MSG_CL_CAST_LESSON_CHAT:
                # The chat bar during 授業. A different message from the map's
                # 0x4900 for the same box on screen, which is why the console
                # used to go silent the moment a lesson started -- `/quiz` typed
                # in class in round 51 arrived here and drew "no reply
                # implemented". A Cast, so nothing appears until it is echoed.
                #
                # One seat, so the echo is the whole broadcast; if a second
                # student ever shares a lesson this is where their copy goes,
                # the way _presence_relay does it for the map.
                said = chat.parse_cast(params)
                names = self._chars(session).full_name(session.chara_id)
                family, first = names if names else (b"", b"")
                print(f"[{self.tag}] lesson chat: {said!r}")
                reply = self._answer(
                    session, sequence, lesson.MSG_SV_NOTIFY_LESSON_CHAT,
                    chat.lesson_notify_params(session.chara_id, family, first, said),
                )
                # ⭐ And this is the point of answering it at all: the console
                # works in class again, so a lesson can be steered without
                # leaving it.
                return reply + self._apply_chat(session, sequence, said)
            if msg_type == lesson.MSG_CL_CAST_LESSON_EMOTION:
                # 「/emotion」 in class. Never seen -- see chat.lesson_emotion_params
                # for why it is answered anyway -- and the echo is all there is
                # to do with it: the client draws the icon from the id it sent.
                emotion = chat.parse_emotion(params)
                print(f"[{self.tag}] lesson emotion: {emotion}")
                return self._answer(
                    session, sequence, lesson.MSG_SV_NOTIFY_LESSON_EMOTION,
                    chat.lesson_emotion_params(session.chara_id, emotion),
                )
            if msg_type in friends.HANDLED:
                # 友達登録 and the アドレス帳 window it fills. Grouped for the
                # same reason the item operations are: the list query and the
                # four-message application handshake are one feature, and a
                # window that lists nobody is what answering only the query
                # gets you.
                return self._friends(session, sequence, msg_type, params)
            if msg_type in groups.HANDLED:
                # 仲良しグループ: 「グループ情報」 and the 勧誘 handshake behind
                # the PC 交流メニュー's 「グループ登録申込み」; see _groups.
                return self._groups(session, sequence, msg_type, params)
            if msg_type in lesson_skill.HANDLED:
                # お助けスキル. Eight skills, one entry point: what differs
                # between them is which rules apply and what goes back, and both
                # of those live in lesson_skill.
                return self._lesson_skill(session, sequence, msg_type, params)
            if msg_type == MSG_CL_REQUEST_MINIMAP_START:
                # The map button greys itself out and waits. Answering unblocks
                # it; the dots that then appear are whatever the server pushes as
                # MsgSvNotifyMinimapNotify, which is why this is the cheapest
                # instrument available for reading the coordinate scale — the
                # backdrop it draws them on is mmt_010100.png, a file we have.
                # Opening the map briefly doubled as the coordinate sweep's
                # "next" button, and that is why the screen used to go black and
                # come back over and over: every MsgSvNotifyGMWarp makes the
                # client tear the scene down and run the whole lobby load again,
                # so map-open turned into warp, reload, warp, reload. The scale
                # question is settled, so the trigger is gone and this is a plain
                # answer plus the dots for whoever *else* is on the map.
                #
                # The player is deliberately not among them. Sending a type-0 dot
                # at session.pos looked right and was not: the client already
                # draws the player itself, in green, and keeps it under the feet
                # as they walk, while a pushed dot is painted once and never
                # moves again. The two agreed at the moment the map was opened
                # and parted company on the next step, leaving a blue dot
                # standing where the player had been. A dot the server cannot
                # keep current is worse than no dot — the client is the authority
                # on where the player is, and this is the one character it does
                # not need telling about.
                reply = self._answer(session, sequence, MSG_SV_OK_MINIMAP_START, b"")
                dots = [(3, pos_x, pos_y) for _, pos_x, pos_y in session.markers()]
                print(
                    f"[{self.tag}] minimap: map {session.map_id}, player at "
                    f"{session.pos} (drawn by the client), {len(dots)} server dots"
                )
                if not dots:
                    # Nobody else to draw, so nothing is sent. The Ok above is
                    # what ungreys the button; the notify only carries dots, and
                    # what an empty one does to the dot the client drew for
                    # itself is not known. Not asking is free.
                    return reply
                return reply + self._answer(
                    session, sequence, MSG_SV_NOTIFY_MINIMAP, minimap_params(session.map_id, dots)
                )
            if msg_type == stress.MSG_CL_CAST_CHARA_POSE:
                # [Insert], per `p05_04`'s 【休憩】: 「マップキャラが座ります。
                # 座ると、ストレスを徐々に回復させることができます」. So this is
                # not decoration — it is the only input the stress system has.
                #
                # ⚠️ Answer it. The client does not sit down on its own: it
                # casts, then waits, and an unanswered cast wedges its input for
                # the rest of the session exactly the way the turn cast did.
                # Both of those cost a session before the rule was written down.
                if not params:
                    return None
                session.pose = params[0]
                if session.pose == stress.POSE_SITTING:
                    session.sat_at = time.monotonic()
                print(
                    f"[{self.tag}] pose charaId={session.chara_id} -> "
                    f"{'座る' if session.pose == stress.POSE_SITTING else '立つ'}"
                    f"({session.pose})"
                )
                pose_params = stress.pose_params(session.chara_id, session.pose)
                self._presence_relay(
                    session, stress.MSG_SV_NOTIFY_CHARA_POSE, pose_params
                )
                return self._answer(
                    session, sequence, stress.MSG_SV_NOTIFY_CHARA_POSE, pose_params
                )
            if msg_type in MOVEMENT_SHAPES:
                # Ground truth for coordinates. Every one of these is the client
                # volunteering where it thinks the player is or wants to be, so
                # one step taken in the world is worth more than any amount of
                # reading decoration tables.
                fields, size = MOVEMENT_SHAPES[msg_type]
                if len(params) < size:
                    print(f"[{self.tag}] MOVEMENT {name}: short, {len(params)}B < {size}B")
                    return None
                values = struct.unpack_from(">" + fields, params, 0)
                named = " ".join(
                    f"{key}={value}" for key, value in zip(MOVEMENT_NAMES[msg_type], values)
                )
                print(f"[{self.tag}] MOVEMENT {name}: {named}")
                # Kept before session.pos is overwritten: how far the walk is
                # decides its arrivalTime, and the cast only names the
                # destination. Reading the distance off the already-updated
                # position made every move exactly one cell, so a five-cell walk
                # was given one cell's worth of time.
                prev_pos = session.pos
                # 「マップ上で座ってじっとしていると」 — walking is not sitting
                # still, and neither is changing maps. The client stands its
                # character up by itself when either happens and does not cast a
                # pose to say so, so the server has to notice: without this a
                # player who sat down once went on recovering for the rest of the
                # session while walking around, which was visible in the log as
                # 休憩 lines arriving from the far side of the campus.
                #
                # ⚠️ An inference from the client's animation, not from the wire.
                # If a pose=0 cast is ever seen arriving on its own after a move,
                # this is redundant rather than wrong.
                if session.pose != stress.POSE_STANDING:
                    print(f"[{self.tag}] pose: 立つ (moved)")
                    session.pose = stress.POSE_STANDING
                    session.sat_at = 0.0
                if msg_type == MSG_CL_CAST_CHARA_TURN:
                    # Alt+left-click, per the manual's 【向きを変える】: turn on
                    # the spot without walking.
                    #
                    # This used to go unanswered, on the reasoning that the
                    # client already faces the way it says it does and only the
                    # value was worth keeping. That cost a session: the client
                    # will not accept another movement input until the cast it
                    # sent has been answered, so one unanswered turn wedged it
                    # for good — logging back in did not help, because the first
                    # click of the new session was a turn as well. Four sessions
                    # in the logs contain a turn cast and not one of them has a
                    # move after it; the runs of moves, which are answered, go on
                    # for hundreds.
                    #
                    # MsgSvNotifyCharaTurn (0x4804) is charaId then direction,
                    # five bytes, the same u32-then-u8 the deserializer reads.
                    session.direction = values[0]
                    print(
                        f"[{self.tag}] turn charaId={session.chara_id} -> "
                        f"{facing.name(session.direction)}({session.direction})"
                    )
                    turn_params = struct.pack(">IB", session.chara_id, session.direction)
                    self._presence_relay(session, MSG_SV_NOTIFY_CHARA_TURN, turn_params)
                    return self._answer(
                        session, sequence, MSG_SV_NOTIFY_CHARA_TURN, turn_params
                    )
                if msg_type == 0x4809:
                    # The tripwire on the collision file. Walkability was worked
                    # out offline — every archived move, every doorway, every
                    # arrival cell, and one connected blob per map — and every
                    # one of those is a check against data already collected.
                    # This is the only one that can be surprised by something
                    # new: the client walking somewhere the file says has no
                    # floor. It prints and lets the step through, because the
                    # client's judgement outranks the inference either way; a
                    # single line of this in a log means the conclusion in
                    # the map exporter's docstring is wrong and should be taken apart.
                    target = (values[0], values[1])
                    if mapgraph.walkable(session.map_id, target) is False:
                        print(
                            f"[{self.tag}] WALKABILITY counterexample: map "
                            f"{session.map_id} {target} reads as having no floor, "
                            f"and the client walked onto it anyway"
                        )
                    session.pos = target
                elif msg_type == MSG_CL_REQUEST_CHARA_WARP:
                    # Checked against the collision files before the session
                    # forgets which map it was on. This never rejects: the client
                    # is the authority on where its doors go, and a mismatch is
                    # far likelier to mean the server's idea of where the player
                    # was standing had drifted.
                    print(
                        f"[{self.tag}] warp check: "
                        + mapgraph.explain_warp(
                            session.map_id, session.pos, values[0], (values[1], values[2])
                        )
                    )
                    session.map_id, session.pos = values[0], (values[1], values[2])
                    session.direction = values[3]
                if self._chars(session).set_position(
                    session.chara_id, session.pos, session.map_id
                ):
                    print(
                        f"[{self.tag}] saved charaId={session.chara_id} on map "
                        f"{session.map_id} at {session.pos}"
                    )
                if msg_type == MSG_CL_REQUEST_CHARA_WARP:
                    # Walking into a doorway. The client works out the target map
                    # and the cell inside it by itself — this is the only place it
                    # ever states a coordinate in a map other than the one it is
                    # standing on — so the server has nothing to decide and only
                    # has to agree.
                    #
                    # Input_MsgSvOkCharaWarp's vtable[0] is 0x8CB9A0, the shared
                    # ``xor eax,eax; ret 8`` stub, and its dump (0x8FFEA0) pushes
                    # the message name and no fields: zero parameters, confirmed
                    # the way every length here gets confirmed, by counting the
                    # reads rather than trusting the shape reader's "empty".
                    #
                    # What follows is a full scene teardown and lobby reload, the
                    # same one MsgSvNotifyGMWarp triggers, so the 0x4000 branch
                    # will re-add the character — on session.map_id, which is why
                    # it was updated above before the answer goes out.
                    map_name = MAP_NAMES.get(session.map_id, "?")
                    print(
                        f"[{self.tag}] warp charaId={session.chara_id} -> map "
                        f"{session.map_id} ({map_name}) at {session.pos}"
                    )
                    return self._answer(session, sequence, MSG_SV_OK_CHARA_WARP, b"")
                if msg_type == 0x4809 and len(params) >= 5:
                    # A cast is a request to walk, and nothing walks until the
                    # server says so. The client sent exactly one of these and
                    # then went quiet for good — no repeat, no complaint — which
                    # is the same shape as the lobby: it was waiting on a push,
                    # not an answer.
                    #
                    # MsgSvNotifyCharaMove (reader 0x900C60, dump 0x900DC0) is
                    # 18 bytes, not the 10 the shape reader reports: after charaId, the
                    # two coordinates, status and direction comes arrivalTime,
                    # read through the stream vtable's +0x10 slot, which 0xA49A50
                    # shows taking eight bytes. the shape reader does not know that slot,
                    # the same blind spot that made it call the one-byte messages
                    # empty.
                    #
                    # arrivalTime says when the walk finishes, on the client's own
                    # clock — hence tag 8 existing at all — so it is now plus the
                    # distance times a per-cell duration.
                    pos_x, pos_y, status = values
                    steps = max(abs(pos_x - prev_pos[0]), abs(pos_y - prev_pos[1]), 1)
                    arrival = session.client_now() + steps * MOVE_MS_PER_CELL
                    # Which way the walk leaves the character looking. Nothing
                    # else tells us: the client casts a turn when the player
                    # turns on the spot, but says nothing at all while walking,
                    # so echoing session.direction back sent the same stale
                    # number every time and the sprite snapped to one fixed pose
                    # on the last frame of every walk, wherever it had gone.
                    turned = facing.of_move(prev_pos, (pos_x, pos_y))
                    if turned is not None:
                        session.direction = turned
                    print(
                        f"[{self.tag}] move charaId={session.chara_id} -> ({pos_x},{pos_y}) "
                        f"{steps} cells, facing {facing.name(session.direction)}"
                        f"({session.direction}), arrivalTime={arrival}"
                    )
                    def move_params(when: int) -> bytes:
                        return struct.pack(
                            ">IHHBBQ",
                            session.chara_id,
                            pos_x,
                            pos_y,
                            status,
                            session.direction,
                            when,
                        )

                    # ⚠️ arrivalTime is on the *recipient's* clock, not the
                    # walker's -- that is the whole reason tag 8 exists -- so the
                    # relay recomputes it per peer instead of forwarding the
                    # walker's number. Two clients that started minutes apart
                    # have wildly different clocks, and handing one the other's
                    # timestamp would put the arrival in its past or far future.
                    # NOT MEASURED with two clients yet; if a relayed walk looks
                    # like a teleport or a freeze on the watcher's screen, this
                    # line is the first suspect.
                    for other in self._peers(session):
                        self._push(
                            other,
                            self._answer(
                                other,
                                0,
                                MSG_SV_NOTIFY_CHARA_MOVE,
                                move_params(other.client_now() + steps * MOVE_MS_PER_CELL),
                            ),
                        )
                    return self._answer(
                        session, sequence, MSG_SV_NOTIFY_CHARA_MOVE, move_params(arrival)
                    )
                return None
            if msg_type == MSG_CL_CAST_NORMAL_CHAT:
                # A cast, so nothing appears until the server broadcasts it back:
                # the speaker's own words reach them the same way everyone else's
                # would. See chat.py for both messages' layouts and for why the
                # server, not the client, has to keep the strings short.
                said = chat.parse_cast(params)
                info = self._chars(session).find(session.chara_id)
                who = display_name(info) if info else "?"
                print(f"[{self.tag}] chat {who}: {said!r}")
                chat_params = chat.notify_params(session.chara_id, who, said)
                # Everyone on the map hears it. 「通常会話」 is the map-wide
                # channel -- ひそひそ話 (0x4A00) is the one that is not, and it
                # is not answered here at all; see MSG_CL_CAST_NORMAL_CHAT for
                # the other three channels this one does not cover.
                self._presence_relay(session, MSG_SV_NOTIFY_NORMAL_CHAT, chat_params)
                reply = self._answer(
                    session, sequence, MSG_SV_NOTIFY_NORMAL_CHAT, chat_params
                )
                return reply + self._apply_chat(session, sequence, said)
            if msg_type >> 8 == 0xE0 or msg_type in DRAMA_DOORS:
                return self._drama_incoming(session, sequence, msg_type, params)
            if msg_type >> 8 == 0x72:
                # The script subsystem. Everything in it is unproven, so the
                # branch logs first and acts second: a reply we did not expect
                # is the finding, not a failure.
                return self._script_incoming(session, sequence, msg_type, params)
            if msg_type in NOTIFICATIONS:
                return None
            if msg_type in FIXED_REPLIES:
                reply_type, reply_params = FIXED_REPLIES[msg_type]
                return self._answer(session, sequence, reply_type, reply_params)
            if msg_type in EMPTY_LIST_REPLIES:
                reply_type = EMPTY_LIST_REPLIES[msg_type]
                return self._answer(session, sequence, reply_type, struct.pack(">H", 0))
            print(f"[{self.tag}] no reply implemented for 0x{msg_type:04x} yet")
            return None
        print(f"[{self.tag}] no handler for tag 0x{tag:04x}")
        return None

    def _club_enter(self, session: "_Session", sequence: int, params: bytes) -> bytes:
        """0x5A00 -> 0x5A01 MsgSvOkClubEnter, or 0x5A02 with a reason.

        Every refusal here is a sentence the client already has; see club.py for
        which index selects which, and for why 6 is the only one that means
        anything specific.
        """
        club_id = club.parse_enter(params)
        state = self._chars(session).club(session.chara_id)
        if club_id is None or state is None:
            print(f"[{self.tag}] club enter: no charaId={session.chara_id} or short body")
            return self._answer(
                session,
                sequence,
                club.MSG_SV_NG_CLUB_ENTER,
                club.ng_enter_params(club.NG_ENTER_FAILED),
            )
        refusal = state.enter_refusal(club_id)
        if refusal is not None:
            reason, remain = refusal
            print(
                f"[{self.tag}] club enter {club.name(club_id)} refused: "
                f"reason={reason} remain={remain}"
            )
            return self._answer(
                session,
                sequence,
                club.MSG_SV_NG_CLUB_ENTER,
                club.ng_enter_params(reason, remain),
            )
        state.enter(club_id)
        self._chars(session).set_club(session.chara_id, state)
        print(f"[{self.tag}] club enter charaId={session.chara_id} -> {state.summary()}")
        return self._answer(session, sequence, club.MSG_SV_OK_CLUB_ENTER, b"")

    def _club_part(self, session: "_Session", sequence: int) -> bytes:
        """0x5A03 -> 0x5A04 MsgSvOkClubPart, or 0x5A05 with a reason.

        Leaving stamps the day so the ten-day wait can be measured; nothing else
        on this server reads that stamp, which is the point of writing it now.
        """
        state = self._chars(session).club(session.chara_id)
        if state is None:
            print(f"[{self.tag}] club part: no charaId={session.chara_id}")
            return self._answer(
                session,
                sequence,
                club.MSG_SV_NG_CLUB_PART,
                club.ng_part_params(club.NG_PART_FAILED),
            )
        reason = state.part_refusal()
        if reason is not None:
            print(f"[{self.tag}] club part refused: reason={reason}")
            return self._answer(
                session, sequence, club.MSG_SV_NG_CLUB_PART, club.ng_part_params(reason)
            )
        left = state.part()
        self._chars(session).set_club(session.chara_id, state)
        print(
            f"[{self.tag}] club part charaId={session.chara_id} left {club.name(left)}, "
            f"{club.REJOIN_DAYS}-day wait starts"
        )
        return self._answer(session, sequence, club.MSG_SV_OK_CLUB_PART, b"")

    # ------------------------------------------------------------------
    # 自主トレ (0x5800-0x581D). See server/trainingroom.py for the layouts, the
    # restored refusals, and why this is the club-battle door that opens.
    # ------------------------------------------------------------------

    def _tr_names(self, chara_id: int) -> tuple[bytes, bytes]:
        """The two fixed-width name halves 0x580C and 0x580F carry.

        Asked about a charaId rather than a connection, and once a room can hold
        two players that id will often belong to somebody else's account. The
        charaId index says whose, so this does not have to search every store:
        see accounts.owner_of.
        """
        store = self.accounts.owner_of(chara_id)
        names = store.full_name(chara_id) if store else None
        return names if names else (b"\x00" * trainingroom.NAME_LEN,) * 2

    def _tr_cast(
        self,
        session: "_Session",
        seen: int,
        msg_type: int,
        params: "bytes | Callable[[int], bytes]",
        members: "list[int]",
    ) -> bytes:
        """Send one Notify to every listed character; return the sender's copy.

        ⚠️ The sender's copy is RETURNED rather than pushed. The packet loop
        writes what a handler returns, so pushing it here as well would put it
        on the wire twice. A caller that does not want the sender to hear it
        leaves them out of ``members`` and drops the b"" that comes back.

        ``params`` may be a callable when the recipients are owed different
        bodies — which 0x580C always is; see _tr_seat.

        A member with no live connection on this port is skipped. That is
        ordinary rather than an error: the board holds rooms, and a socket can
        go away between the message arriving and this running.
        """
        body = params if callable(params) else (lambda _chara_id: params)
        mine = b""
        for chara_id in members:
            if chara_id == session.chara_id:
                mine = self._answer(session, seen, msg_type, body(chara_id))
                continue
            other = self._session_of(chara_id)
            if other is None:
                continue
            self._push(other, self._answer(other, 0, msg_type, body(chara_id)))
        return mine

    def _tr_seat(
        self, session: "_Session", room: "trainingroom.Room",
        joiner: "trainingroom.Member",
    ) -> bytes:
        """0x580C for one join. Two different bodies go out, and they must.

        The joiner is told about everyone already seated; everyone already
        seated is told about the joiner, and about nobody else. ⚠️⚠️ Sending
        the whole roster both ways is the tempting version and it is wrong:
        0x580C merges rows in rather than replacing them (Room.roster_params),
        so the seated members would re-add every row they are already drawing.

        seen=0 because it answers nothing — it follows a change.
        """
        return self._tr_cast(
            session,
            0,
            trainingroom.MSG_SV_NOTIFY_JOIN,
            lambda chara_id: (
                room.roster_params(without=chara_id)
                if chara_id == joiner.chara_id
                else room.roster_rows([joiner])
            ),
            [m.chara_id for m in room.members],
        )

    def _battle_info(
        self, session: "_Session", room: "trainingroom.Room"
    ) -> bytes:
        """0x5C06 for a room whose leader has just pressed 「開 始」.

        ⚠️ A DIFFERENT BODY PER RECIPIENT, and only in its leading byte: the
        two rosters are shared, ``team`` says which side *this* reader is on.
        Building it per recipient is what _tr_cast's callable form is for.

        Each row needs the character's create block, which is looked up in
        *their own* store through accounts.owner_of — a room holds people from
        several accounts, and a charaId does not name its owner.

        ⚠️ A member whose record cannot be found is dropped from the roster
        rather than faked. That makes the side short, which is visible, in
        preference to drawing a character out of invented bytes, which is not.

        seen=0 because this answers nothing: 0x5818 was already answered by the
        0x5819 that goes out just before it.

        ⭐ This is also where the battle starts existing as a thing the server
        holds. Everything after it — the 0x5C07s coming back, the 0x5C09 that
        answers the last of them — needs to know who is fighting after the
        room has stopped being the subject, so the roster is built once here
        and kept on self.battles rather than re-derived from the room.
        """
        fighters: "list[clubbattle.Fighter]" = []
        for team in trainingroom.TEAMS:
            for member in room.team(team):
                info = self._peer_chara(member.chara_id)
                if info is None:
                    print(f"[{self.tag}] battle info: no record for "
                          f"charaId={member.chara_id:#x}, left out of the roster")
                    continue
                store = self.accounts.owner_of(member.chara_id)
                fighters.append(
                    clubbattle.Fighter(
                        member.chara_id,
                        team,
                        store.in_club(member.chara_id) if store else 0,
                        info,
                    )
                )

        battle = self.battles.open(fighters)
        # クラブ活動中 goes up over everybody who is fighting. ⚠️ The fighters
        # themselves are excluded: they are leaving the map scene for the fight,
        # and the 0x4810+0x480F pair is only safe for a client looking at the
        # map (round 96). The audience is the bystanders standing around them.
        combatants = {f.chara_id for f in fighters}
        for fighter in fighters:
            other = self._session_of(fighter.chara_id)
            if other is not None:
                self._presence_refresh_onlookers(other, also=combatants)
        sides = {t: [f.info_row() for f in battle.side(t)] for t in trainingroom.TEAMS}
        counts = "/".join(str(len(sides[t])) for t in trainingroom.TEAMS)
        print(f"[{self.tag}] battle info: Ａ/Ｂ={counts}, {self.battles.summary()}")

        def body(chara_id: int) -> bytes:
            fighter = battle.find(chara_id)
            return clubbattle.training_battle_info_params(
                fighter.team if fighter else trainingroom.TEAM_A,
                sides[trainingroom.TEAM_A],
                sides[trainingroom.TEAM_B],
            )

        return self._tr_cast(
            session,
            0,
            clubbattle.MSG_SV_NOTIFY_TRAINING_BATTLE_INFO,
            body,
            [m.chara_id for m in room.members],
        )

    def _clubbattle(
        self, session: "_Session", sequence: int, msg_type: int, params: bytes
    ) -> "bytes | None":
        """The 0x5Cxx family: the battle itself, once 0x5C06 has drawn it.

        ⚠️ The battle comes from ``self.battles``, not from the room it was
        opened out of. 自主トレ is the only door this server can open onto this
        family today, but 練習 and フリー対戦 arrive at these same branches, and
        a handler that reached for a trainingroom.Room would be wrong the day
        one of those opens.
        """
        chara_id = session.chara_id
        battle = self.battles.battle_of(chara_id)

        if msg_type == clubbattle.MSG_CL_NOTIFY_BATTLE_READY:
            # ⭐ Sent by the client unprompted once its battle scene is up —
            # which is how this message named itself as the one to answer
            # next. It carries a deckId; the answer carries a charaId and no
            # deck at all.
            deck_id = clubbattle.parse_ready(params)
            fighter = battle.find(chara_id) if battle else None
            if battle is None or fighter is None:
                print(f"[{self.tag}] battle ready from charaId={chara_id:#x} "
                      f"(deck {deck_id}) with no battle to tell")
                return None
            fighter.ready = True
            fighter.deck_id = deck_id
            print(f"[{self.tag}] battle ready: charaId={chara_id:#x} "
                  f"deck={deck_id} ({battle.summary()})")
            everyone = [f.chara_id for f in battle.fighters]
            out = self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_READY,
                clubbattle.battle_ready_params(chara_id),
                everyone,
            )
            # ⚠️ The turn opens on the LAST 0x5C07, not on each one. Every
            # client is drawing its own scene and they finish at their own
            # pace, so a turn started on the first one would begin for a
            # player whose battle is still being built.
            if battle.all_ready():
                out += self._battle_turn_start(session, battle)
            return out

        if msg_type == clubbattle.MSG_CL_CAST_BATTLE_COMMAND:
            return self._battle_command(session, battle, params)

        if msg_type == clubbattle.MSG_CL_NOTIFY_BATTLE_TURN_END:
            # ⭐ Empty body, and a Notify: 「I have finished playing this turn's
            # actions」. It is the counterpart of 0x5C07 one level down — the
            # client saying a piece of animation is over, not asking anything —
            # so it gets no answer of its own and the next 0x5C09 is the reply
            # the fight actually needs.
            fighter = battle.find(chara_id) if battle else None
            if battle is None or fighter is None:
                print(f"[{self.tag}] battle turn end from charaId={chara_id:#x} "
                      f"with no battle to end a turn of")
                return None
            fighter.turn_done = True
            done = sum(1 for f in battle.fighters if f.turn_done)
            print(f"[{self.tag}] battle turn end: charaId={chara_id:#x} "
                  f"({done}/{len(battle.fighters)}, {battle.summary()})")
            # ⚠️⚠️ PROBE ONLY, one shot, off unless /cb ordernext armed it —
            # see Battle.order_probe for what it is for. It goes out from this
            # handler round, so the client receives it one round trip after it
            # said 「my animation is over」, and nothing else is in the batch:
            # the turn is not done, so the branch below would have written
            # nothing at all.
            probe = battle.order_probe
            if probe is not None and probe[0] == chara_id:
                if battle.all_turn_done():
                    # ⚠️ Deliberately still armed. This 0x5C16 is the last one,
                    # so answering it means a turn start (or a result) in the
                    # same batch, and a batch with two candidates in it answers
                    # nothing. Say so and wait for a turn the fight is arranged
                    # for, rather than spending the shot on an unreadable one.
                    print(f"[{self.tag}] ⚠️ /cb ordernext NOT fired: this 0x5C16 "
                          f"is the last one, so the next turn would go out in "
                          f"the same batch — still armed")
                else:
                    battle.order_probe = None
                    who = ", ".join(f"0x{c:08x}" for c in probe[1]) or "nobody"
                    print(f"[{self.tag}] ⚠️ /cb ordernext FIRES on "
                          f"charaId={chara_id:#x}: 0x5C0D naming {who}, alone in "
                          f"this batch")
                    return self._tr_cast(
                        session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_ORDER,
                        clubbattle.action_order_params(probe[1]),
                        [f.chara_id for f in battle.fighters],
                    )
            if not battle.all_turn_done():
                return None
            if battle.finished():
                # 「1）〜3）を８ターンが終了するまで…繰り返します。5）勝敗が
                # 表示されます」. The repeat is over, so the next thing the
                # manual names is the result — and unlike the ninth 0x5C09 this
                # would have had to be, that is a message the original sends.
                print(f"[{self.tag}] battle reached the {clubbattle.TURN_LIMIT}-"
                      f"turn limit, showing the result")
                return self._battle_finish(session, battle)
            return self._battle_turn_start(session, battle)

        print(f"[{self.tag}] no reply implemented for 0x{msg_type:04x} yet")
        return None

    def _battle_command(
        self, session: "_Session", battle: "clubbattle.Battle | None",
        params: bytes,
    ) -> "bytes | None":
        """0x5C0A 「I pick this card, at them」 -> 0x5C0C to the whole fight.

        ⚠️ The card itself does not go out here. 0x5C0C has room for a charaId
        and a reason and nothing else, so what the other player learns from
        this exchange is only that a choice happened; the deckItem reaches
        them in 0x5C0E, once the turn resolves. This server therefore has to
        REMEMBER the choice, and remembering it is the reason 0x5C07's deckId
        was worth storing — itemNum is an index into that deck and into no
        other.

        ⚠️⚠️ Nothing is validated beyond 「there is a fight and you are in
        it」. The refusals this subsystem has are the two sentences in
        error_message (see clubbattle.COMMAND_*), and neither of them is
        「that card is not in your deck」 or 「that target is not here」 — so a
        server that invented a refusal for those would be inventing policy,
        not restoring it. A choice that does not resolve is a problem for the
        code that resolves it, which does not exist yet.
        """
        chara_id = session.chara_id
        parsed = clubbattle.parse_command(params)
        if parsed is None:
            print(f"[{self.tag}] battle command from charaId={chara_id:#x} "
                  f"is {len(params)}B, too short to read: {params.hex()}")
            return None
        item_num, is_attck, target_id = parsed
        fighter = battle.find(chara_id) if battle else None
        if battle is None or fighter is None:
            print(f"[{self.tag}] battle command from charaId={chara_id:#x} "
                  f"(item {item_num}) with no battle to put it in")
            return None
        everyone = [f.chara_id for f in battle.fighters]
        if battle.resolved:
            # ⭐ The one refusal this subsystem can make honestly, and the first
            # time it has ever been sendable: reason 2 is 「コマンド選択がゲーム
            # サーバ側の制限時間内に間に合いませんでした」, and a command that
            # arrives after the turn has already been played is exactly that.
            # ⚠️ Broadcast like the acceptance is, on the same argument (0x5C0C
            # names a charaId, so it is not a private answer) — but note that
            # nothing has been on screen to say whether the others are supposed
            # to see somebody else's refusal.
            print(f"[{self.tag}] battle command from charaId={chara_id:#x} "
                  f"arrived after turn {battle.turn} was played: reason=2")
            return self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_COMMAND,
                clubbattle.command_params(chara_id, clubbattle.COMMAND_TOO_LATE),
                everyone,
            )
        fighter.command = parsed
        card = self._battle_card(fighter, item_num)
        print(f"[{self.tag}] battle command: charaId={chara_id:#x} "
              f"itemNum={item_num} isAttck={is_attck} target={target_id:#x} "
              f"deck={fighter.deck_id} card={card} ({battle.summary()})")
        out = self._tr_cast(
            session,
            0,
            clubbattle.MSG_SV_NOTIFY_BATTLE_COMMAND,
            clubbattle.command_params(chara_id, clubbattle.COMMAND_OK),
            everyone,
        )
        # 「3）全員のコマンド入力終了後、全員の行動が実行されます」. ⚠️ On the
        # LAST command, not on each one — the same rule 0x5C09 is under one
        # level up, and for the same reason: a round played on the first choice
        # would act for somebody who is still looking at their cards.
        if battle.all_chosen():
            out += self._battle_resolve(session, battle)
        return out

    def _battle_deck(self, fighter: "clubbattle.Fighter") -> "list[list]":
        """The 部活デッキ this fighter brought, out of *their own* store.

        ⚠️ Through accounts.owner_of, not the handling session's store: a
        battle holds people from several accounts (the same rule _peer_chara is
        under), and reading the opponent's deck out of the chooser's save file
        would find either nothing or the wrong character's cards.

        ⚠️ Which deck is ``fighter.deck_id``, said once by 0x5C07 and never
        repeated on the wire. There is nothing to fall back on if that was
        missed, so an unknown character or an unset deck comes back empty and
        the caller decides what an empty deck means.
        """
        store = self.accounts.owner_of(fighter.chara_id)
        state = store.club(fighter.chara_id) if store else None
        return state.deck(fighter.deck_id) if state else []

    def _battle_card(self, fighter: "clubbattle.Fighter", item_num: int) -> str:
        """What ``itemNum`` names in this fighter's deck, for the log only.

        ⭐ SETTLED: itemNum is a 0-based index into the deck 0x5C07 named, in
        the order this server handed that deck over in 0x5B01. It is not the
        card's keyword id, and it is not 1-based.

        Round 87 read 0-based off the first real command — the player clicked
        row 7 and 06 came up — but both decks in that fight held keyword ids
        0-7 in order, so index and id carried the same value and only 「is it
        the row he clicked」 told them apart. Round 118 shuffled a deck into
        reverse order so that no row's index equalled its card's id, and had a
        real client play twice: row 7 (index 6, id 1) sent 06, row 4 (index 3,
        id 4) sent 03. Index both times. The second reading the log used to
        carry alongside this one has served its purpose and is gone.

        ⚠️ Still printed, still not acted on: the reason to keep naming the
        card is that a wrong deck or a stale save shows up here as a card
        nobody clicked, which is cheaper to notice than to debug.
        """
        deck = self._battle_deck(fighter)
        if not 0 <= item_num < len(deck):
            return f"deck{fighter.deck_id}[{item_num}]=(-) of {len(deck)}"
        kind, payload = deck[item_num][0], bytes.fromhex(str(deck[item_num][1]))
        named = club.describe_deck_item(int(kind), payload)
        return f"deck{fighter.deck_id}[{item_num}]=({named}) of {len(deck)}"

    def _battle_deck_item(
        self, fighter: "clubbattle.Fighter"
    ) -> "tuple[int, bytes] | None":
        """The six bytes 0x5C0E has to carry for this fighter's choice.

        ⚠️ Returns None rather than a stand-in when the index names nothing.
        0x5C0E's deckItem is the client's own struct going back out verbatim,
        so there is no such thing as a neutral value to put there — a made-up
        card would be a key the client looks up and draws. A fighter whose card
        cannot be resolved is dropped from the turn instead, which is the same
        thing that happens to one who never chose.
        """
        if fighter.command is None:
            return None
        item_num = fighter.command[0]
        deck = self._battle_deck(fighter)
        if not 0 <= item_num < len(deck):
            return None
        kind, payload = int(deck[item_num][0]), bytes.fromhex(str(deck[item_num][1]))
        if len(payload) != club.DECK_ITEM_BYTES:
            return None
        return (kind, payload)

    def _battle_mastery(
        self, fighter: "clubbattle.Fighter", kind: int, payload: bytes
    ) -> None:
        """Say what playing this card would do to its 習熟度. Writes NOTHING.

        ⭐⭐ This walks the whole path 習熟度 has to travel — from a card that
        is going out in 0x5C0E right now, back to the row 0x4305 sends for it —
        and prints the arithmetic instead of storing it. p07_02 says the number
        rises 「クラブ活動でキーワードを使用すると」 and a card in the action
        stream is that use, so this is the moment; what comes out on the log is
        exactly what club.use_count_after_use would have written.

        ⚠️⚠️ Printing is the whole reason this half can stand on its own. The
        step is INVENTED (club.USE_COUNT_PER_USE, argued where it is defined)
        and 習熟度 is 攻撃/防御 power as well as the gate on new キーワード, so
        the day something stores this number, gameplay moves. A log line does
        not, and it separates 「the path is right」 from 「the number is right」
        while nothing is yet at stake.

        ⚠️ At the ACTION rather than at the 0x5C0A that asked for it, which is
        a narrower moment than it sounds: a fighter whose card cannot be
        resolved is dropped from the turn, and a command that arrives after the
        turn was played is refused — neither of those used a card. Everyone in
        this stream did, on both sides, 自主トレ being PC-against-PC.

        ⚠️ The owner's own store, not the handling session's and not the deck's
        copy of the row (the same rule _battle_deck is under). Those six bytes
        are the client's struct as it stood when 0x5B03 registered the card and
        nothing refreshes them, so the two readings can disagree — and the
        disagreement is worth seeing: the day useCount moves, every deck holding
        that card keeps handing the old value back out in 0x5B01 until
        something rewrites the payload.

        ⚠️ /cb replay re-runs a turn that already resolved, so it prints these
        lines twice for one play. Harmless while they only print; whatever
        stores the number will need a guard the probe cannot walk through.

        ⛔️ kind 1 is a 部活奥義 and has no 習熟度 — its `completeness` is a
        different field, and an unread one.
        """
        if kind != club.DECK_ITEM_KEYWORD or len(payload) != club.DECK_ITEM_BYTES:
            return
        # ⚠️ Little-endian, the one field group in this protocol that is; the
        # measurement is at club.DECK_ITEM_KEYWORD.
        keyword_id, deck_use_count, _club_source = struct.unpack("<HHH", payload)
        store = self.accounts.owner_of(fighter.chara_id)
        state = store.club(fighter.chara_id) if store else None
        row = None
        if state is not None:
            row = next((r for r in state.keywords if r[0] == keyword_id), None)
        if row is None:
            # ⚠️ Worth a line rather than a silent return: the card came out of
            # this character's own deck, so the row it names ought to be in the
            # same character's 所持 list. A fighter no account claims is the
            # ordinary case for a stand-in and says nothing about the path.
            missing = "no account claims them" if store is None else "they do not own it"
            print(f"[{self.tag}] 習熟度 (not stored): charaId={fighter.chara_id:#x} "
                  f"played keyword {keyword_id} and {missing} — nothing to raise")
            return
        use_count = row[1]
        full = club.keyword_full_scale(keyword_id)
        stale = ("" if deck_use_count == use_count
                 else f" ⚠️ the deck's copy still says {deck_use_count}")
        if club.keyword_is_mastered(use_count, keyword_id):
            print(f"[{self.tag}] 習熟度 (not stored): charaId={fighter.chara_id:#x} "
                  f"keyword={keyword_id} useCount {use_count} of {full} — already "
                  f"満, nothing to raise and no second 0x5C17{stale}")
            return
        after = club.use_count_after_use(use_count, keyword_id)
        note = (" — reaches 満: 0x5C17 would be due here"
                if club.keyword_is_mastered(after, keyword_id) else "")
        print(f"[{self.tag}] 習熟度 (not stored): charaId={fighter.chara_id:#x} "
              f"keyword={keyword_id} useCount {use_count}->{after} of {full}"
              f"{note}{stale}")

    def _battle_resolve(
        self, session: "_Session", battle: "clubbattle.Battle",
        demo_first: bool = False, order_override: "list[int] | None" = None,
    ) -> bytes:
        """Play the turn: 0x5C0D, then 0x5C0E/0x5C0F for each one who acts.

        「3）全員のコマンド入力終了後、全員の行動が実行されます」 (p07_03).
        Two things reach this — the last 0x5C0A, and the 制限時間 running out —
        and Battle.resolved keeps them from both playing the same turn.

        ⚠️⚠️ ``demo_first`` IS A PROBE, off on every live path. It moves the
        0x5C12 from the end of the stream to the front — the one thing round 88
        could not test, because a probe can only append to a turn that has
        already gone out. It reorders messages this server builds anyway and
        changes no byte of any of them. See /cb replay first in _battle_probe.

        ⚠️ ``order_override`` is the same probe's other half: it names the
        0x5C0D roster instead of reading it off the plays. Also off on every
        live path, also a permutation of this fight's own fighters.

        ⚠️⚠️ NOTHING HAPPENS to anybody as a result. 0x5C0E states the card and
        the target, 0x5C0F says that character is done, and no 体力 moves: the
        damage rules are not restored, and 0x5C10/0x5C11 (Reaction/Effect) are
        not written. What this restores is the SHAPE of a turn, which is what
        the client is stuck waiting for; the arithmetic inside it is a separate
        piece of work and inventing it here would put numbers on the wire that
        no reading supports.

        ⚠️ The order goes out AFTER the cards have been looked up, so 0x5C0D
        names exactly the characters the 0x5C0E stream is about to mention. The
        other way round — announce, then discover a card is missing — would
        leave the client waiting on an action that never begins.

        seen=0 throughout: an action stream follows the last command, it does
        not answer it (the 0x5C0C that does has already gone out).
        """
        battle.resolved = True
        for other in (self._session_of(f.chara_id) for f in battle.fighters):
            if other is not None:
                other.battle_due = 0.0
        plays: "list[tuple[clubbattle.Fighter, int, bytes]]" = []
        for fighter in battle.actors():
            card = self._battle_deck_item(fighter)
            if card is None:
                print(f"[{self.tag}] battle action: charaId={fighter.chara_id:#x} "
                      f"chose {self._battle_card(fighter, fighter.command[0])} "
                      f"— nothing to play, left out of the order")
                continue
            plays.append((fighter, card[0], card[1]))
        everyone = [f.chara_id for f in battle.fighters]

        def demo_start() -> bytes:
            return self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_DEMO_START,
                b"",
                everyone,
            )

        order = [fighter.chara_id for fighter, _kind, _payload in plays]
        if order_override is not None:
            print(f"[{self.tag}] ⚠️ battle action: PROBE named roster — 0x5C0D "
                  f"names {', '.join(f'0x{c:08x}' for c in order_override)} "
                  f"instead of {', '.join(f'0x{c:08x}' for c in order) or 'nobody'}")
            order = order_override
        who = ", ".join(f"0x{c:08x}" for c in order) if order else "nobody acts"
        print(f"[{self.tag}] battle action order: turn={battle.turn}, {who}")
        out = b""
        if demo_first:
            # ⚠️ Printed before anything goes out, because every reading of
            # this turn depends on which arrangement it was: a screenshot of
            # the circle cannot tell you which stream drew it.
            print(f"[{self.tag}] ⚠️ battle action: PROBE /cb replay first — "
                  f"0x5C12 goes out AHEAD of 0x5C0D/0x5C0E/0x5C0F, not after")
            out = demo_start()
        out += self._tr_cast(
            session,
            0,
            clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_ORDER,
            clubbattle.action_order_params(order),
            everyone,
        )
        for fighter, kind, payload in plays:
            assert fighter.command is not None
            _item_num, is_attck, target_id = fighter.command
            # ⭐ Ahead of the probe, because this is about the card that was
            # actually played rather than the one /cb card swapped in. Prints
            # and stores nothing — see _battle_mastery.
            self._battle_mastery(fighter, kind, payload)
            # ⚠️⚠️ PROBE ONLY, one shot, off unless /cb card armed it — see
            # Battle.card_probe. It swaps the deckItem this ActionBegin names,
            # which is the only way to make the client resolve a kind no deck
            # here can hold.
            if battle.card_probe is not None:
                kind, payload = battle.card_probe
                print(f"[{self.tag}] ⚠️ battle action: DOCTORED by /cb card — "
                      f"deckItem is {club.describe_deck_item(kind, payload)} "
                      f"instead of the card played")
            print(f"[{self.tag}] battle action: charaId={fighter.chara_id:#x} "
                  f"{'攻撃' if is_attck else '防御'} target={target_id:#x} "
                  f"{club.describe_deck_item(kind, payload)}")
            out += self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_BEGIN,
                clubbattle.action_begin_params(
                    fighter.chara_id, kind, payload, target_id
                ),
                everyone,
            )
            # ⚠️⚠️ PROBE ONLY, one shot, off unless /cb fxnext armed it. This is
            # the one place a probe alters a real resolve, and it has to be:
            # round 90 measured that a second action stream inside an
            # already-played turn is ignored outright, so 0x5C10/0x5C11 can only
            # be put in front of a client from inside the turn it is about to
            # animate. See Battle.fx_probe.
            if battle.fx_probe is not None:
                fx_types, fx_value, fx_value2, fx_reaction = battle.fx_probe
                print(f"[{self.tag}] ⚠️ battle action: DOCTORED by /cb fxnext — "
                      f"0x5C10 reaction={fx_reaction}, 0x5C11 type="
                      f"{','.join(str(t) for t in fx_types)} "
                      f"value={'per type' if fx_value is None else fx_value} "
                      f"value2={fx_value2} at target={target_id:#x}")
                out += self._tr_cast(
                    session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_REACTION,
                    clubbattle.reaction_params(target_id, fx_reaction), everyone,
                )
                # ⭐ One 0x5C11 per type, all in this one action's stream. A
                # sweep costs a turn instead of a fight: a turn is 60 seconds
                # and a fight is eight turns plus five minutes of clicking, so
                # asking 「which row does each type draw」 one type at a time
                # is what makes that question expensive rather than the answer.
                # ⚠️ Reading a sweep means reading the log window in order, and
                # a type that draws nothing leaves no gap — see the ambiguity
                # note on EFFECT_TEMPLATE table in clubbattle.
                for fx_type in fx_types:
                    value = fx_type if fx_value is None else fx_value
                    out += self._tr_cast(
                        session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_EFFECT,
                        clubbattle.effect_params(
                            target_id, fx_type, value, fx_value2
                        ),
                        everyone,
                    )
            out += self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_END,
                clubbattle.action_end_params(fighter.chara_id),
                everyone,
            )
        # ⭐⭐⭐ And this is what actually makes the turn run. MEASURED, round 88:
        # a real client was given 0x5C0D and both 0x5C0E/0x5C0F pairs and sat
        # perfectly still — the 「decided」 markers stayed over both heads, no
        # 0x5C16 came back, and the fight was as stuck as it had been before any
        # of the three existed. One body-less 0x5C12 later, on the same live
        # battle, it reported 0x5C16 and drew 「残り　6　ターン」. Twice, on two
        # different turns, one of them a turn that had timed out.
        #
        # ⚠️ It goes LAST because that is where it was measured, not because the
        # order is known: the probe could only append to a turn already sent, so
        # 「DemoStart first, then the script」 was untested and not excluded.
        # What the test does settle is that the client holds the actions until
        # told, rather than playing each as it arrives.
        # ⭐ ``demo_first`` is the probe that finally asks the other half. It
        # never fires on a live path — only /cb replay first sets it.
        battle.fx_probe = None  # one shot: the next turn is a normal one again
        battle.card_probe = None  # same, and for the same reason
        if not demo_first:
            out += demo_start()
        # ⚠️⚠️ PROBE ONLY, one shot, off unless /cb ordertail armed it — see
        # Battle.tail_probe. It goes out one packet behind the 0x5C12 that ends
        # the turn, which is the earliest a second 0x5C0D can be put anywhere:
        # the window that 0x5C12 opens has just opened and the client has not
        # played a frame of the animation yet.
        #
        # ⚠️ It is deliberately BEHIND the demo_start above rather than in
        # place of it. The turn has to run — a stream the client never animates
        # would answer a different question — so this adds to that stream, and
        # the roster it names differs from the one the turn itself just sent so
        # that a repaint is a value change rather than an absence (an earlier lesson).
        tail = battle.tail_probe
        if tail is not None:
            battle.tail_probe = None
            roster, demo, tail_demo_first = tail
            who = ", ".join(f"0x{c:08x}" for c in roster) or "nobody"
            # ⚠️ Printed before the bytes go out and naming the arrangement,
            # for the reason demo_first's own line above says: the screenshot
            # afterwards shows a number, not which stream drew it. ⭐ And the
            # two demo flags are the whole question here, so they are spelled
            # out rather than summarised.
            print(f"[{self.tag}] ⚠️ /cb ordertail FIRES: "
                  f"{'0x5C12 then ' if tail_demo_first else ''}0x5C0D naming "
                  f"{who}{' plus a second 0x5C12' if demo else ''}, appended "
                  f"behind this turn's own 0x5C12")
            if tail_demo_first:
                # ⭐⭐ The one variable this branch exists to move: a 0x5C12
                # right in front of the appended roster, which is the shape
                # 2.62 step 5 had and the plain append does not. Everything
                # else stays exactly as the plain append leaves it, so the two
                # runs differ by this message and nothing else (an earlier lesson).
                out += demo_start()
            out += self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_ORDER,
                clubbattle.action_order_params(roster), everyone,
            )
            if demo:
                out += demo_start()
        return out

    def _battle_sheet(
        self, fighter: "clubbattle.Fighter"
    ) -> "tuple[list[int], int, int]":
        """One fighter's six 能力パラメータ plus their club's level and gauge.

        ⚠️ Through accounts.owner_of for the same reason _battle_deck is: the
        people in a fight come from several accounts and the handling session's
        store holds only its own.

        ⚠️ The level and gauge are the ones for THIS FIGHTER'S club — 部活レベル
        is per club (u8[16] in the ability sheet, 2.30) and 自主トレ takes all
        comers 「所属クラブに関係なく」 (p07_04), so there is no single club a
        fight could be said to be in. A character with no club, or one this
        server cannot find, comes back all zeroes.
        """
        store = self.accounts.owner_of(fighter.chara_id)
        sheet = store.ability(fighter.chara_id) if store else None
        if sheet is None:
            return ([0] * clubbattle.NUM_OF_CHARA_ABILITY, 0, 0)
        params = list(sheet.params[: clubbattle.NUM_OF_CHARA_ABILITY])
        params += [0] * (clubbattle.NUM_OF_CHARA_ABILITY - len(params))
        club_id = fighter.club_id
        level = sheet.club_level[club_id] if 0 <= club_id < len(sheet.club_level) else 0
        gauge = sheet.club_gauge[club_id] if 0 <= club_id < len(sheet.club_gauge) else 0
        return (params, level, gauge)

    def _battle_finish(
        self, session: "_Session", battle: "clubbattle.Battle",
        win_team: "int | None" = None, send_end: bool = True,
        refresh_fighters: bool = False,
    ) -> bytes:
        """0x5C1A then 0x5C1C: 「5）勝敗が表示されます」 and the way out.

        ⚠️ ``refresh_fighters=True`` is ALSO FOR THE PROBE ONLY (``/cb finish …
        refresh``) and is the one flag here that deliberately makes the server
        worse: it puts round 96's presence flush back, unskipped, INSIDE this
        handler turn. Round 102 established that the 0x4810/0x480F pair is
        survivable when a probe pushes it a second later, so what is left to
        test is the batch — see _battle_leave_rooms.

        ⚠️ ``send_end=False`` is FOR THE PROBE ONLY (``/cb finish … noend``) and
        exists because the one open question about this pair cannot be asked any
        other way. Measured, round 89: the player's actual exit is pressing
        ［終 了］ on the 結果画面, which makes the client send 0x4000 by itself —
        so whether the 0x5C1C this also sends is part of a normal ending, or
        only ever an abnormal one, is undecided. Answering it means sending
        0x5C1A alone at the ONE moment the client is idle enough to draw it,
        and that moment is this function; by the time a ``/cb result`` could be
        typed the fight is closed and the probe has nothing to aim at.

        ⭐⭐ THE WAY OUT IS THE POINT. Until this existed a fight that reached
        turn 8 simply stopped on its last frame and the player never got back
        to the campus — the only exit was killing the client. 0x5C1C is that
        exit, and it is pure plumbing: one restored byte (END_NORMAL), no
        arithmetic, nothing invented.

        ⚠️ What is NOT sent here: 0x5C17 GetKeyword, 0x5C18 GetItem, 0x5C19
        GetClubSkill. The manual grants all three with 〜ことがあります, so
        sending none of them is a legal round rather than a hole, and each one
        carries a lookup key (a keyword id, a categoryId/id pair) that this
        server has no restored rule for choosing. See their constants.

        ⚠️ The Battle is CLOSED before returning, so a stray 0x5C0A or 0x5C16
        arriving after the result finds nothing — which is what those handlers
        already print rather than crash on. The 自主トレルーム it came out of is
        deliberately left standing: nothing read so far says a room dissolves
        when its fight ends, and 0x5809/0x580A is how a member leaves one.

        seen=0: a result follows the last 0x5C16, it does not answer it.
        """
        if win_team is None:
            win_team = clubbattle.WIN_TEAM_NEITHER
        close = True
        if battle.hold_on_finish:
            # ⭐ /cb hold, one-shot. The 0x5C1A still goes out on the normal
            # path — the one instant the client is idle enough to draw the
            # 結果画面 — and nothing else does, so a probe can keep talking to a
            # fight that is still on the board. See Battle.hold_on_finish.
            battle.hold_on_finish = False
            send_end = False
            close = False
            if battle.hold_win_team is not None:
                win_team = battle.hold_win_team
                battle.hold_win_team = None
        everyone = [f.chara_id for f in battle.fighters]
        sheets = {f.chara_id: self._battle_sheet(f) for f in battle.fighters}
        for fighter in battle.fighters:
            params, level, gauge = sheets[fighter.chara_id]
            print(f"[{self.tag}] battle result: charaId={fighter.chara_id:#x} "
                  f"team={fighter.team} club={fighter.club_id} "
                  f"部活Lv={level}({gauge}) 能力={params}")
        print(f"[{self.tag}] battle end: winTeam={win_team} "
              f"after turn {battle.turn} ({battle.summary()})")

        def body(chara_id: int) -> bytes:
            params, level, gauge = sheets.get(
                chara_id, ([0] * clubbattle.NUM_OF_CHARA_ABILITY, 0, 0)
            )
            # ⚠️ before == after, everywhere. See clubbattle.result_params: the
            # rule that would move any of these is not restored, and a server
            # that made one up would be writing an invented reward into a save.
            return clubbattle.result_params(
                win_team,
                before_gauge=gauge, after_gauge=gauge,
                before_lv=level, after_lv=level,
                before_ability=params, after_ability=params,
            )

        out = self._tr_cast(
            session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_RESULT, body, everyone
        )
        if send_end:
            out += self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_END,
                clubbattle.end_params(clubbattle.END_NORMAL),
                everyone,
            )
        else:
            print(f"[{self.tag}] battle end: 0x5C1C withheld (probe)")
        # ⚠️ The deadline is cleared either way. The fight is over as far as
        # turns go, and a HELD one must not resolve another turn out from under
        # the 結果画面 sixty seconds later.
        for other in (self._session_of(c) for c in everyone):
            if other is not None:
                other.battle_due = 0.0
        if close:
            self._battle_stress(everyone)
            self.battles.close(session.chara_id)
            # ⚠️ Tied to `close`, not to `send_end`: a HELD fight is a probe
            # standing still, and taking its room away would move a second
            # thing while the probe is trying to measure the first.
            self._battle_leave_rooms(everyone, refresh_fighters=refresh_fighters)
        else:
            print(f"[{self.tag}] battle HELD open (probe): fight still on the "
                  f"board, /cb still has a target")
        return out

    def _battle_stress(self, everyone: "list[int]") -> None:
        """One クラブ活動's worth of ストレス for everybody who fought.

        ⭐⭐⭐ RESTORED from `p05_09`: 「授業・試験 / クラブ活動 / 奥義合成 を
        行なうと、ストレスがたまります」 and 「ストレスが高い状態でクラブ活動を
        行なうと、怪我をすることがあります」. Only the quantity is invented, and
        it is the same one a lesson costs -- see stress.STRESS_PER_CLUB_ACTIVITY.
        ⚠️ Rounds 36 through 148 built this whole family without ever charging
        it, so 怪我 and ドクターストップ were unreachable states; _injured says
        how that survived so long.

        ⚠️ Tied to the real ending only. The caller charges inside ``if close``,
        because a ``/cb hold`` fight passes through _battle_finish twice and a
        probe holding the board open must not cost the players two 部活.

        ⚠️ Everybody, not just the handling session: 自主トレ is a fight between
        accounts and the sheet of each one lives in its own store, which is why
        this goes through accounts.owner_of exactly as _battle_sheet does. A
        fighter who has already dropped still pays -- they did the activity --
        and simply has no session to be told about it.

        ⚠️⚠️ NOTHING IS SENT FROM HERE, and that is deliberate. The moment this
        runs is the 結果画面, which is the one moment round 96 measured a client
        dying on a message it takes calmly everywhere else (0x4810+0x480F, and
        _battle_leave_rooms carries the whole warning). 0x4811/0x4812 are not
        that pair, but they would be *new* traffic at that instant on nothing
        better than an assumption. _drain_vitals already pushes both the moment
        either value differs from what this session was last told, and it runs
        on every arriving packet -- so the screen is updated by the client's
        next breath instead, off the path this server has already measured.
        """
        for chara_id in everyone:
            store = self.accounts.owner_of(chara_id)
            sheet = store.ability(chara_id) if store else None
            if sheet is None:
                continue
            added, condition = stress.after_club_activity(sheet)
            store.set_ability(chara_id, sheet)
            print(f"[{self.tag}] club activity: charaId={chara_id:#x} "
                  f"ストレス +{added} -> {sheet.stress} "
                  f"({stress.screen(sheet.stress)}/100), 体調 "
                  f"{stress.name(condition)}")

    def _battle_leave_rooms(
        self, everyone: "list[int]", refresh_fighters: bool = False
    ) -> None:
        """Take the fighters out of the 自主トレルーム their fight came out of.

        ⭐⭐ SILENT ON THE WIRE, AND THAT IS THE POINT: every client has already
        left this room by itself, so there is nobody left to tell. Measured,
        rounds 93 and 95 —

        * the 自主トレルーム window is gone by the time the 結果画面 is up and
          cannot be called back, not even by having somebody join the room
          again (2.48 §5);
        * pressing ［終 了］ sends 0x4000 / 0x6500 / 0xA100 and no 0x5809
          Part, so the client never asks to be let out (2.50 §5);
        * back on the campus the client offers 看板作成 and does send 0x5800,
          which is not what a client that believed itself in a room would do.

        The server was the only one still holding them, and it answered that
        0x5800 with 0x5802 reason 3 「既に自主トレルームに入っているため、自主
        トレルームを作成できません。」 — so a player who had practised once
        could not put up a second 看板 without dropping the connection first.

        ⚠️ INVENTED, and it cannot be otherwise (the invention rule): nothing in the 0x58xx
        family says 「the room let you go because the fight ended」. The three
        restored PART_REASONs are 自分自身の要求 / リーダーに排除された /
        切断による, this is none of them, and putting one of them on the wire
        would be labelling the event wrong. ⭐ What is *not* a free choice is
        that it happens at all: the client leaves without telling anybody, so a
        server that did not do this by itself would ship the refusal above.

        ⚠️ This is NOT 「the room dissolves when its fight ends」, which 2.44
        declined to invent and still declines. Members are removed one at a
        time through Board.part, so p07_06's promotion rule applies and a room
        with somebody still in it stays up under a new leader. When the room's
        roster *is* the fight's roster — the only case ever measured, because
        the fight is built from the room — the last part empties the room and
        Board.part drops it. Same outcome, different rule.

        ⚠️⚠️ ``refresh_fighters=True`` DROPS THE skip= AND IS A PROBE ONLY
        (``/cb finish … refresh``). It restores, in the same handler turn, the
        flush that round 96 measured as fatal: the fighters are handed the
        presence pairs the skip= now keeps away from them.
        ⭐ Round 102 fired those same two messages from _battle_probe six times
        onto a live 結果画面 and the client survived every one, so the pair by
        itself is cleared and the remaining suspects are properties of the
        BATCH. Three of them come back only here, together:

        * ⭐⭐ ORDER. _push writes immediately, while this handler's own reply is
          written after it returns — so a fighter whose connection was the one
          drained receives the pairs BEFORE the 0x5C1A that follows them. Round
          96's log has exactly that: three pairs, then a single 122-byte write
          carrying timesync + 0x5C1A + 0x5C1C, then EOF. Every round 102 probe
          instead landed on a 結果画面 that was already up.
        * ⭐⭐ action=10. The promoted leader's add half carries it, and it is
          the one field value that has never reached a screen — round 102's
          subject was a plain member both times, so both adds read action=0.
        * The fight is off the board and its room is being taken apart, rather
          than held open with everything still standing.

        ⭐⭐⭐ Round 103 ran it: the client died BOTH times, EOF plus the
        「通信が断たれました」 dialog, and the second run's write was the same
        122-byte timesync + 0x5C1A + 0x5C1C round 96 logged. Two pairs are
        enough — round 96's third one was not the variable. Then the same fight
        cleared two of the three suspects above with /cb presence: the whole
        pair onto a live battle screen survives, action=10 survives (see
        act=N), and so does both at once. What is left is the batch itself —
        including the order, which round 103 could not separate from it.

        ⚠️ Nothing about the normal path moves: the default is False and the
        skip= stays exactly as 2.51 left it.
        """
        board = self.trainingrooms
        skip: "set[int] | None" = None if refresh_fighters else set(everyone)
        if refresh_fighters:
            print(f"[{self.tag}] ⚠ PROBE: presence flush NOT skipped for the "
                  f"fighters — round 96 replayed inside this handler turn")
        emptied: "list[trainingroom.Room]" = []
        for chara_id in everyone:
            room = board.room_of(chara_id)
            if room is None:
                # Logged out mid-fight: the disconnect path parted them then,
                # and 2.50 keeps them on the fight's roster anyway.
                continue
            was_leader = room.leader_id == chara_id
            board.part(chara_id)
            print(f"[{self.tag}] trainingroom left at battle end: "
                  f"charaId={chara_id:#x}, now {board.summary()}")
            # ⚠️ Two things move a pixel here, and until round 150 only one of
            # them did: leadership (the 看板 goes to whoever leads the room now)
            # and the fight itself (クラブ活動中 sits on every fighter while one
            # is on, so every fighter's byte changes when it ends). So the
            # refresh is no longer conditional on having led the room.
            # ⚠️⚠️ It must not reach the fighters — that pair is what
            # 「通信が断たれました」 came out of; see _presence_refresh. They do
            # not need it either: pressing ［終 了］ sends 0x4000, and that
            # branch rebuilds the whole scene with a freshly computed action
            # byte for every peer. ⚠️ Note self.battles.close() has already run,
            # so battle_of() no longer knows these are the people on a 結果画面
            # — `skip` is what keeps them out, not _presence_blocked.
            for who in ({chara_id, room.leader_id} if was_leader else {chara_id}):
                other = self._session_of(who)
                if other is not None:
                    self._presence_refresh(other, skip=skip)
            if room.members:
                if room not in emptied:
                    emptied.append(room)
            elif room in emptied:
                emptied.remove(room)
        for room in emptied:
            print(f"[{self.tag}] ⚠ {len(room.members)} left in {room.summary()} "
                  f"after its fight ended, and they were told nothing: no "
                  f"0x580D reason means 「the fight is over」")

    def _battle_probe(
        self, session: "_Session", sequence: int, args: "list[str]"
    ) -> bytes:
        """``/cb …``: poke a battle that is already on screen, without rebuilding it.

        ⚠️⚠️ A PROBE, not gameplay. It exists because the 0x5C** sequence is
        being read one message at a time off a live client, and every guess used
        to cost a rebuilt fight: two logins, a room, a join, two 準備ＯＫ, a
        開始 — five minutes to test a three-line change. These send one message
        into the fight that is already up.

        ``/cb by=i …``     ⭐⭐ RUN THIS LINE ON ONE CONNECTION ONLY: fighter
                           i's. Every other connection drains past it and does
                           nothing. Legal in front of any subcommand below.
        ``/cb``            what the server thinks the state is
        ``/cb demo``       0x5C12 MsgSvNotifyClubBattleDemoStart, body-less
        ``/cb sync [turn]``  0x5C09 MsgSvNotifyClubBattleTurnStart, bare, in the
                           middle of a turn — this side's turn counter, choices
                           and deadline all stay put. ⚠️⚠️ THE ONE PROBE HERE
                           THAT IS A NEW SHAPE, so send it alone before putting
                           it in a batch. ⚠️⚠️ ``turn`` decides whether the
                           client listens AT ALL: repeating this turn's own
                           number (the default) gets the message thrown away
                           whole, a number it has not seen gets acted on. See
                           the branch — the two were measured apart in round
                           113 and only the second one asks anything.
        ``/cb order [rev] [all] [@i …]``  0x5C0D again. Bare, that is the same
                           order this turn already sent, which asks nothing;
                           ``rev`` turns it around, ``all`` names everyone
                           rather than only those who chose a card, and ``@i``
                           names exactly those fighters in exactly that order.
                           ⭐ The point is the circle under a fighter's feet:
                           it holds ① from the 開始 splash onward, before any
                           0x5C0D exists, so this asks whether the message
                           repaints it and whether the number is a position in
                           this list at all.
        ``/cb replay [first] [rev|all|@i …]``  the whole action stream again,
                           with the same roster forms ``order`` takes. ⭐⭐ ``first``
                           moves the 0x5C12 to the FRONT of it. Round 88 could
                           only measure it at the end — a probe appends to a
                           turn that already went out — so 「DemoStart, then the
                           script」 stayed untested for eighteen rounds. On a
                           turn that has not been played yet (``/cb next``, then
                           this) it is a real first play, and the three things
                           to read off it are: which roster the circle under a
                           fighter's feet draws, whether the actions animate at
                           all, and whether 0x5C16 still comes back.
        ``/cb ordernext [rev|all|@i …] | off``  ⭐⭐ arm one 0x5C0D to go out
                           from INSIDE the handler round that receives THIS
                           connection's next 0x5C16, alone in its batch; ``off``
                           disarms. The roster forms are ``order``'s. ⭐ It
                           measured the far edge of the window 0x5C12 opens
                           (2.63): the circle does NOT move — once a client has
                           reported 0x5C16 for a turn, nothing in this family
                           repaints that widget. ⚠️ It skips a 0x5C16 that is
                           the fight's last one — see Battle.order_probe — so
                           somebody else has to still owe one, which on a
                           partner fight means ``the partner-fight driver --end-delay``.
                           ⭐⭐ With ``by=i`` naming a SPARRING PARTNER it
                           reaches the moment 2.63 could not: the partner's
                           0x5C16 arrives about half a second into the real
                           client's animation, so the 0x5C0D goes out while
                           that client is still playing the turn and has not
                           reported anything yet.
        ``/cb ordertail [rev|all|@i …] [demo] [demofirst] | off``  ⭐⭐ arm one
                           0x5C0D to be APPENDED to this fight's next action
                           stream, behind the 0x5C12 that closes it; ``demo``
                           puts a second 0x5C12 behind that, ``demofirst`` puts
                           one in FRONT of the appended roster instead. ⭐⭐ That
                           last one is the single knob between the two readings
                           2.64 left standing — see Battle.tail_probe for what
                           1, 2 and 3, 4 each mean. ⚠️ Take ``by=i`` with it — the
                           slot is one-shot and every connection drains the
                           line, so an unlocked one doctors two turns. It is
                           the positive control 2.63 lacks: the same widget,
                           the same message, at the earliest moment there is
                           instead of the latest. See Battle.tail_probe.
        ``/cb next``       pretend everyone reported 0x5C16 and start the next turn
        ``/cb result [n] [ruler]``  0x5C1A alone, winTeam=n, fight left standing
        ``/cb end [n]``    0x5C1C alone, reason=n
        ``/cb part [@i] [n]``  0x5C1B 「this one character dropped out」,
                           charaId of fighter i, reason=n. The fight is LEFT
                           STANDING — the disconnect path closes it, and this
                           asks what the message alone does.
        ``/cb presence [del|add|pair] [@i] [act=N]``  the 0x4810 / 0x480F halves
                           of a presence refresh, about fighter i, down THIS ONE
                           connection. The one probe here that is not a 0x5C**.
                           ⭐ It answered the round 96 question: NEITHER half
                           kills a client on the 結果画面 — see below.
                           ⭐⭐ ``act=N`` forces the icon byte on the add half
                           instead of reading it off room leadership, which is
                           the only way to aim ACTION_TRAINING_ROOM at a screen
                           without a second real client.
        ``/cb finish [n] [noend] [refresh]``  result + end + close, what turn 8
                           does by itself; ``noend`` withholds the 0x5C1C.
                           ⚠️⚠️ ``refresh`` drops the skip= on the presence
                           flush, putting round 96's whole batch back into this
                           one handler turn — the pairs arrive BEFORE the
                           0x5C1A and the promoted leader's add carries
                           action=10, neither of which /cb presence can stage.
                           See _battle_leave_rooms.
        ``/cb hold [n]``   arm the NEXT finish to send 0x5C1A alone, with
                           winTeam=n if given, and leave the fight standing.
                           ⚠️ The 結果画面 ignores every 0x5C1A after the first,
                           so a winTeam question needs the FIRST one to carry
                           it — hence arming rather than re-sending.
        ``/cb vit [v] [e] | off``   make every 0x5C09 from now on carry this
                           vitality/energy for everybody instead of their own.
                           With no argument, half of max vitality. ⭐ The one
                           probe that separates 「0x5C09 repaints the bar」 from
                           「the client resets it at turn start」 — the turn
                           either opens short or it does not.
        ``/cb states <c0,…,c7 | ruler | off> [@i]``  write one fighter's eight
                           status counters, so every 0x5C09 from now on carries
                           them. ⭐ The one probe for the last unread field of
                           0x5C09: this server has sent all-zero counters in
                           every fight ever, so nothing is known about what
                           they draw — see Fighter.states. ``ruler`` gives each
                           slot a different two-digit number (11,22,…,88), so
                           one frame says which slots have a shadow at all and
                           whether slot i means clubstatus id i. ⚠️ ``off`` is
                           all-zero, which is the shipping value.
        ``/cb timeout [ms] | off``  make every 0x5C09 from now on name a
                           deadline this many ms ahead of the reader's own
                           clock, instead of clubbattle.TURN_TIMEOUT_MS.
                           ⭐ A fight has eight turns and each one carries a
                           fresh deadline, so one fight asks eight numbers
                           rather than one — which is how the cap on that field
                           was settled (clubbattle.TURN_TIMEOUT_MS). ⚠️ It
                           moves this server's own patience with it, so a turn
                           still resolves when the countdown says it should —
                           unless TMO_TURN_DEADLINE_S pinned that side.
        ``/cb react [n] [@i]``      0x5C10 Reaction, reaction=n
        ``/cb effect [t] [v] [v2] [@i]``  0x5C11 Effect, type=t
                           ⭐ ``@i`` aims at fighter i; the default is whoever
                           the console line was drained for. v defaults to t.
        ``/cb fx [t] [v] [v2] [r]``      replay THIS turn with the pair in it
        ``/cb fxnext [t[,t…]] [v] [v2] [r]``  arm the NEXT turn with the pair
                           in it, which is the one that works — see
                           _battle_replay_fx. ⭐ ``t`` may be a comma list, and
                           then one 0x5C11 per type goes into the same stream.
        ``/cb card <kind> <12 hex digits> | off``  arm the NEXT turn so every
                           0x5C0E ActionBegin in it names THIS deckItem instead
                           of the card actually played. ⭐ The one way to ask
                           what ``kind`` = 1 (部活奥義) does, since no deck here
                           can hold one — see Battle.card_probe. ⚠️ The six
                           bytes are the client's own little-endian struct and
                           go out verbatim; for a クラブスキル that is
                           ``categoryId u16, id u16`` and two bytes nothing has
                           read yet, so 野球部 1:0 重いコンダラ is
                           ``/cb card 1 010000006400``.

        ⭐ Every one of them is a message this server already knows how to
        build; nothing here invents a shape.

        ⭐⭐ ``result`` is the ruler for a message whose twelve fields have never
        been on a screen. It does NOT close the fight, so several winTeam values
        can be tried into the same live battle — which is the only way to read
        an encoding that the binary states nowhere (clubbattle.WIN_TEAM_NEITHER).
        Its ``ruler`` form additionally pulls every before/after pair apart, so
        whichever half the screen draws names itself.

        ⭐⭐⭐ ``by=i`` IS THE ONE PIECE OF MACHINERY HERE THAT IS NOT A MESSAGE.
        A console line is drained by whichever connection speaks first, and WHO
        DRAINED IT decides what the other client sees, in what order: _push
        writes into a connection on the spot, while a handler's own reply waits
        for it to return. So the same ``/cb finish refresh`` delivers the
        presence pairs BEFORE the 0x5C1A when the real client runs it, and
        AFTER when the sparring partner does. Round 103 wanted the second half
        of that comparison and could not get it — a real client sends timesync
        every 30 seconds against the partner's 60, so it wins the race twice
        out of twice. ``by=i`` stops racing: the wrong connections skip the
        line and leave it for the right one.
        """
        battle = self.battles.battle_of(session.chara_id)
        if battle is None:
            return self._say(session, sequence, "/cb: no battle")
        # ⭐⭐ The lock, ahead of everything else so that a skipped line costs
        # nothing and answers nothing — see the docstring. It is stripped from
        # ``args`` here, so every branch below parses exactly what it always
        # did.
        #
        # ⚠️ Skipping is safe because ``console_at`` is per-session: each
        # connection reads the whole file for itself, so a line one of them
        # steps over is still ahead of all the others. The one who is meant to
        # run it will, on its next packet.
        run_by = None
        for token in args:
            if token.startswith("by="):
                try:
                    run_by = int(token[3:], 0)
                except ValueError:
                    run_by = None
        if run_by is not None:
            args = [a for a in args if not a.startswith("by=")]
            if not 0 <= run_by < len(battle.fighters):
                print(f"[{self.tag}] /cb by={run_by}: no such fighter, "
                      f"this fight has {len(battle.fighters)} "
                      f"({battle.summary()}) — nobody runs this line")
                return b""
            wanted = battle.fighters[run_by].chara_id
            if wanted != session.chara_id:
                # ⚠️ Printed, not silent. Which connection ran it is the
                # variable being controlled here, so the log has to show the
                # lock working rather than leave it to be inferred from what
                # came out the other end.
                print(f"[{self.tag}] /cb by={run_by}: skipped on "
                      f"charaId={session.chara_id:#x}, waiting for "
                      f"charaId={wanted:#x}")
                return b""
            print(f"[{self.tag}] /cb by={run_by}: running on "
                  f"charaId={session.chara_id:#x}")
        what = args[0] if args else "state"
        everyone = [f.chara_id for f in battle.fighters]

        def named_order(tokens: "list[str]") -> "list[int] | None":
            """``rev`` / ``all`` / ``@i @j …`` -> a roster, or None for the default.

            ⚠️ Every form is a PERMUTATION OF THIS FIGHT'S REAL FIGHTERS. 0x5C0D
            is a counted array of charaId and stays one; nothing here invents a
            shape or a character. ⚠️ @i is read in the order it was typed rather
            than sorted back into roster order, because which position a fighter
            is named at is the whole question.
            """
            picked = []
            for token in tokens:
                if not token.startswith("@"):
                    continue
                try:
                    index = int(token[1:], 0)
                except ValueError:
                    continue
                if 0 <= index < len(battle.fighters):
                    picked.append(battle.fighters[index].chara_id)
            if picked:
                chosen = picked
            elif "all" in tokens:
                # ⭐ Everyone, including whoever did not choose a card. actors()
                # leaves them out, so on a zero-click probe fight the default
                # form names one side only — which is a different question.
                chosen = list(everyone)
            elif "rev" in tokens:
                chosen = [f.chara_id for f in battle.actors()]
            else:
                return None
            return chosen[::-1] if "rev" in tokens else chosen

        if what == "state":
            for fighter in battle.fighters:
                print(f"[{self.tag}] /cb 0x{fighter.chara_id:08x} team={fighter.team} "
                      f"deck={fighter.deck_id} command={fighter.command} "
                      f"turn_done={fighter.turn_done}")
            return self._say(
                session, sequence,
                f"/cb {battle.summary()}, resolved={battle.resolved}",
            )
        if what == "demo":
            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_DEMO_START, b"", everyone
            )
        if what == "sync":
            # ⭐⭐⭐ A bare 0x5C09, mid-turn, that moves nothing on this side:
            # the turn counter, everybody's choice and the deadline all stay
            # where they were, so the only question it asks is what the WIRE
            # message does to a client that is already inside a turn.
            #
            # ⚠️⚠️ THE ONE PROBE IN HERE THAT IS A NEW SHAPE. Every other
            # branch replays a message at a moment the fight itself already
            # puts it in; this one puts a turn-start where the live path never
            # does. It may repaint the コマンド window, restart the countdown,
            # or kill the client outright (``finish refresh`` is exactly that
            # kind of splice). ⭐ Send it ALONE the first time and check the
            # client is still answering before running it inside a batch.
            #
            # ⭐ Why it exists: 2.67 measured 「the number under a fighter's
            # feet clears once a turn」 without being able to name the message
            # that clears it — 0x5C09, the client's own 0x5C16 and the コマンド
            # window reopening all sit on one instant in a live fight, and
            # round 112 could not pull the three apart. The idea was to
            # separate the first from the other two: put it between two 0x5C0Ds
            # and the second one's numbers either restart at ① or carry on
            # climbing.
            # ⚠️⚠️ Round 115 ran that and the read (①②) does NOT name a
            # culprit, because it is equally well explained by the leading
            # 0x5C0D never having been counted: the only phase this message is
            # eaten in is also a phase where nothing paints, and a 0x5C0D whose
            # count can be trusted has to go into an OPEN window — with the
            # whole turn boundary necessarily in between.
            # ⛔️⛔️ AND ROUND 116 CLOSED THE QUESTION OFF FROM THIS SIDE
            # ENTIRELY, so this branch is no longer a step towards it. Getting
            # 「0x5C09 plus the window reopening」 to happen AT ALL requires the
            # client to have reported 0x5C16 first (see below) — and that report
            # is the other candidate. Every timeline that makes one candidate
            # occur puts the other one ahead of it, so no injection schedule can
            # separate them; it is the client's turn state machine that forbids
            # the position, not bad luck with timing. What round 116 did settle:
            # a fake window timing out, and a 0x5C09 that got thrown away,
            # BOTH clear nothing (a roster taken in through an open window with
            # a live countdown still read ③④ afterwards). What still predicts
            # the screen for a re-implementation is unchanged and enough: the
            # count clears once per turn.
            #
            # ⛔️⛔️ WHAT DECIDES IT IS THE CLIENT'S PHASE, NOT ``turn``. Round
            # 113 read 「a repeated number is a no-op, a new number is eaten on
            # the spot」 off two sends whose turn numbers differed — but so did
            # their delivery phase, and round 115 separated the two:
            #
            # ⭐⭐⭐ AND THE PHASE THAT MATTERS IS ONE THE SCREEN DOES NOT SHOW:
            # round 116 found two states that are pixel-for-pixel alike (arena
            # visible, no window up) and answer this message oppositely. What
            # separates them is whether the client has REPORTED 0x5C16 for the
            # previous turn:
            #
            #   Reported it (nothing of the last turn left to settle): EATEN.
            #     A fresh コマンド window comes up, 「残り」 is repainted off THIS
            #     message's number (8 − number), and the window's own deadline
            #     is the timeoutTime it carried (measured: closed at T+59s,
            #     frame by frame, with no natural turn start in the log to
            #     account for it).
            #   Has NOT reported it: thrown away whole, WHATEVER the number.
            #     Two ways to be in this state, both measured: the コマンド
            #     window is still open (including at turn+1, the very number a
            #     real boundary carries -- the countdown kept ticking to the
            #     second, 59 -> 43 over the 16s elapsed, and 「残り」 never
            #     moved); or its countdown hit zero and nobody ever settled that
            #     turn, so the client is still waiting on a resolution that is
            #     not coming and considers itself mid-turn.
            #   Mid-animation (window closed, 0x5C16 imminent): NOT MEASURED.
            #
            # ⚠️⚠️ So the client's own turn state is the gate, and it is only
            # legible in THIS side's log (the 0x5C16 arrival) -- not on screen.
            # To make this probe land, send it after that arrival; a backstop
            # partner's --end-delay widens that stretch to however long is
            # needed.
            # ⚠️ ``turn`` still matters for READING the send, just not for
            # whether it lands: pick a number the natural sequence will not
            # reach, so 「残り」 says which message painted it (round 113 passed
            # turn+1 and lost that sign — the countdown was what saved it).
            # ⚠️ It is a wire value ONLY: this side's counter does not move, so
            # the next natural 0x5C09 still says what it was always going to.
            try:
                sync_turn = int(args[1], 0)
            except (IndexError, ValueError):
                sync_turn = battle.turn
            sync_rows = battle.turn_rows()
            print(f"[{self.tag}] /cb sync: bare 0x5C09, turn={sync_turn} "
                  f"({len(sync_rows)} fighter(s)); nothing on this side moved, "
                  f"battle is still at {battle.summary()}")

            def sync_body(chara_id: int) -> bytes:
                # ⚠️ Per-recipient clock, the rule _battle_turn_start is under:
                # timeoutTime names a moment on the RECIPIENT's timebase, and
                # copying one client's moment onto another teleports them
                # (2.15).
                other = self._session_of(chara_id)
                clock = (other or session).client_now()
                return clubbattle.turn_start_params(
                    sync_turn, clock + battle.timeout_ms(), sync_rows
                )

            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_TURN_START,
                sync_body, everyone,
            )
        if what == "order":
            # ⭐⭐ The list is a PARAMETER here, which is the whole point: what
            # the circle under a fighter's feet is drawn from cannot be read off
            # a fight that only ever sends one order. Sending the same order
            # twice asks nothing; sending a different one asks whether the
            # client redraws from this message at all.
            order = named_order(args[1:])
            if order is None:
                order = [f.chara_id for f in battle.actors()]
            who = ", ".join(f"0x{c:08x}" for c in order) if order else "nobody"
            print(f"[{self.tag}] /cb order: {who}")
            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_ORDER,
                clubbattle.action_order_params(order), everyone,
            )
        if what == "ordernext":
            # ⚠️⚠️ Arms rather than sends, and arming IS the measurement: the
            # instant being asked about is one round trip wide, and a console
            # line cannot be aimed that finely — it is drained on a timesync,
            # which is up to 30 seconds away. See Battle.order_probe.
            #
            if "off" in args[1:]:
                # ⭐ A disarm, because this one does NOT spend itself on every
                # 0x5C16 it sees: a shot that lands on the last one stays armed
                # (see Battle.order_probe), so 「armed and no longer wanted」 is
                # a state the fight can be left in. It is also the empty control
                # this probe needs — the same 0x5C16, with nothing armed.
                battle.order_probe = None
                print(f"[{self.tag}] /cb ordernext disarmed")
                return self._say(session, sequence, "/cb ordernext off")
            # ⭐ Prefer the ``@i`` forms. The roster is resolved HERE, while the
            # choices are usually still open, and ``rev``/the bare default read
            # actors() — which is 「who has chosen a card so far」 and is still
            # filling up. ``@i`` names fighters by seat, so it means the same
            # thing whenever it is typed.
            order = named_order(args[1:])
            if order is None:
                order = [f.chara_id for f in battle.actors()]
            battle.order_probe = (session.chara_id, order)
            who = ", ".join(f"0x{c:08x}" for c in order) if order else "nobody"
            print(f"[{self.tag}] /cb ordernext armed on "
                  f"charaId={session.chara_id:#x}: {who} (fires from inside the "
                  f"handler round of that character's next 0x5C16, once, and "
                  f"only if somebody else still owes one)")
            return self._say(
                session, sequence, f"/cb ordernext armed {who}"
            )
        if what == "ordertail":
            # ⚠️⚠️ Arms rather than sends, for a different reason than ordernext
            # does: this instant is not one a console line is too slow for, it
            # is one no console line can occupy at all. The turn's own stream is
            # built and written inside a single handler round, so 「right behind
            # it」 is a position in that stream rather than a time to type at.
            #
            # ⭐ It fires on the next resolve of THIS fight, whoever armed it:
            # the batch belongs to the turn rather than to a connection, so the
            # roster is the whole of what is being said here.
            # ⚠️⚠️ Which is why this one wants ``by=i`` more than ordernext
            # does. Every logged-in connection drains the console line for
            # itself, and this slot is one-shot: fire it on the first drain and
            # a later connection's drain re-arms it for the turn after — one
            # typed line, two doctored turns, and the second one silently
            # standing where the empty control was meant to be (4.17).
            if "off" in args[1:]:
                battle.tail_probe = None
                print(f"[{self.tag}] /cb ordertail disarmed")
                return self._say(session, sequence, "/cb ordertail off")
            # ⚠️ ``@i`` for the same reason ordernext prefers it: this is armed
            # while the choices are still open, and actors() at that moment is
            # 「who has chosen so far」 rather than who will act. A roster read
            # now and a roster the turn sends later would differ for a reason
            # that has nothing to do with the question.
            order = named_order(args[1:])
            if order is None:
                order = [f.chara_id for f in battle.actors()]
            # ⚠️ Exact tokens, so ``demofirst`` is not also a ``demo``: the two
            # put a 0x5C12 on opposite sides of the appended 0x5C0D and the
            # point of the pair is to have one without the other.
            demo = "demo" in args[1:]
            tail_demo_first = "demofirst" in args[1:]
            battle.tail_probe = (order, demo, tail_demo_first)
            who = ", ".join(f"0x{c:08x}" for c in order) if order else "nobody"
            shape = (f"{'0x5C12 then ' if tail_demo_first else ''}{who}"
                     f"{' plus a second 0x5C12' if demo else ''}")
            print(f"[{self.tag}] /cb ordertail armed: {shape} (fires once, from "
                  f"the end of this fight's next action stream)")
            return self._say(
                session, sequence,
                f"/cb ordertail armed {who}"
                f"{' demofirst' if tail_demo_first else ''}"
                f"{' demo' if demo else ''}"
            )
        if what == "replay":
            # ⭐⭐ ``first`` is the whole point of this branch now: it is the
            # only way to put 0x5C12 in FRONT of the action stream, because the
            # live path can only ever append. Nothing else about the turn
            # changes — same cards, same targets.
            # ⭐⭐ The 0x5C0D roster is a parameter here for the same reason it
            # is on ``order``, and on a zero-click probe fight it has to be:
            # only the fighters who chose a card get named, so a roster read off
            # actors() can only ever ADD or REMOVE a name — and 「the circle went
            # blank」 is an absence, which reads the same whether the client
            # repainted from the new list or cleared the widget for its own
            # reasons. Naming the roster turns the question into ①-vs-② on the
            # same character, which an absence cannot fake.
            battle.resolved = False
            return self._battle_resolve(
                session, battle, demo_first="first" in args[1:],
                order_override=named_order(args[1:]),
            )
        if what == "fx":
            return self._battle_replay_fx(session, battle, args[1:])
        if what == "fxnext":
            # ⚠️ Arms the NEXT resolve instead of replaying this one — see
            # Battle.fx_probe for the measurement that made /cb fx useless.
            def fxarg(position: int, fallback: int) -> int:
                try:
                    return int(args[1:][position], 0)
                except (IndexError, ValueError):
                    return fallback

            # ⭐ The first argument may be a comma-separated LIST of types, all
            # spliced into the same action stream. ``3`` and ``3,4,5,6`` are
            # both legal and a lone number behaves exactly as it always has.
            try:
                fx_types = tuple(int(t, 0) for t in args[1].split(",") if t)
            except (IndexError, ValueError):
                fx_types = (0,)
            if not fx_types:
                fx_types = (0,)
            # ⭐⭐ WITH NO ``value`` GIVEN, EACH TYPE SENDS ITS OWN NUMBER AS THE
            # VALUE, and that is what makes a sweep readable: 0x5C11's value is
            # PRINTED (round 97 measured 「…の気力が７７上がった！」 for
            # value=77), so 「気力が19上がった」 names the type that drew it
            # without trusting the order the lines came out in. ⚠️ Pass a value
            # explicitly and the whole sweep shares it, which reads back as one
            # anonymous line per hit.
            shared_value = None
            if len(args) > 2:
                try:
                    shared_value = int(args[2], 0)
                except ValueError:
                    shared_value = None
            battle.fx_probe = (
                fx_types, shared_value, fxarg(2, 0), fxarg(3, 0)
            )
            print(f"[{self.tag}] /cb fxnext armed: {battle.fx_probe} "
                  f"(fires on the next resolve, once)")
            return self._say(
                session, sequence, f"/cb fxnext armed {battle.fx_probe}"
            )
        if what == "card":
            # ⚠️ Arms the NEXT resolve, like fxnext and for the same measured
            # reason: a stream spliced into a turn the client has already
            # played is ignored outright (Battle.fx_probe).
            if len(args) > 1 and args[1].lower() == "off":
                battle.card_probe = None
                return self._say(session, sequence, "/cb card off")
            try:
                kind = int(args[1], 0)
                payload = bytes.fromhex(args[2])
            except (IndexError, ValueError):
                return self._say(
                    session, sequence,
                    "/cb card <kind> <"
                    f"{club.DECK_ITEM_BYTES * 2} hex digits> | off",
                )
            if len(payload) != club.DECK_ITEM_BYTES:
                return self._say(
                    session, sequence,
                    f"/cb card: deckItem payload is {club.DECK_ITEM_BYTES} "
                    f"bytes, got {len(payload)}",
                )
            battle.card_probe = (kind & 0xFF, payload)
            print(f"[{self.tag}] /cb card armed: "
                  f"{club.describe_deck_item(*battle.card_probe)} "
                  f"(fires on the next resolve, once)")
            return self._say(
                session, sequence,
                f"/cb card armed {club.describe_deck_item(*battle.card_probe)}",
            )
        if what == "vit":
            # ⚠️⚠️ Also arms rather than sends: the question is what a turn
            # OPENS with, and the only 0x5C09 the client will act on is the one
            # the normal path sends. See Battle.turn_start_hp.
            #
            # ⭐ Draining this line once per logged-in session is harmless, the
            # way ``hold`` is: writing the same pair twice is the same pair.
            if len(args) > 1 and args[1] in ("off", "none", "-"):
                battle.turn_start_hp = None
                shown = "off (each fighter's own numbers again)"
            else:
                def hparg(position: int, fallback: int) -> int:
                    try:
                        return int(args[position], 0)
                    except (IndexError, ValueError):
                        return fallback

                first = battle.fighters[0]
                pair = (
                    hparg(1, first.max_vitality // 2),
                    hparg(2, first.max_energy),
                )
                battle.turn_start_hp = pair
                shown = f"vitality={pair[0]} energy={pair[1]} for everyone"
            print(f"[{self.tag}] /cb vit: every 0x5C09 from now on carries "
                  f"{shown}")
            return self._say(session, sequence, f"/cb vit {shown}")
        if what == "states":
            # ⚠️⚠️ The only knob in here that writes a FIGHTER rather than the
            # board, and it is a probe for exactly that reason: nothing in this
            # server has ever written Fighter.states, so every 0x5C09 it has
            # ever sent carried eight zeros. A field whose only value so far is
            # its neutral one has not been measured at all — the reading 「the
            # client ignores these」 and the reading 「they drive the lamps」 fit
            # the same evidence (an earlier lesson).
            #
            # ⭐ Not one-shot, for turn_start_hp's reason: the question is what
            # a turn OPENS with. It restores itself for turn_start_hp's other
            # reason — the counters live on the Fighter, the Fighter dies with
            # the Board, and no fight outlives its board.
            #
            # ⭐ The target defaults to the sender the way react/effect do, so
            # the line each session drains aims at that session's own fighter.
            # ⚠️ With the widget drawing ONLY the reader's own row (4.15), an
            # explicit @i is what puts counters on one fighter and leaves the
            # sparring partners at zero — which is how a frame gets a control.
            index = None
            for token in args[1:]:
                if token.startswith("@"):
                    try:
                        index = int(token[1:], 0)
                    except ValueError:
                        continue
            if index is not None:
                if not 0 <= index < len(battle.fighters):
                    return self._say(
                        session, sequence,
                        f"/cb states: no fighter @{index}",
                    )
                target = battle.fighters[index]
            else:
                target = next(
                    (f for f in battle.fighters
                     if f.chara_id == session.chara_id), None
                )
                if target is None:
                    return self._say(
                        session, sequence,
                        "/cb states: this session has no fighter here, use @i",
                    )
            spec = next(
                (a for a in args[1:] if not a.startswith("@")), "ruler"
            )
            if spec in ("off", "none", "-"):
                counters = [0] * clubbattle.NUM_OF_CLUB_STATUS
            elif spec == "ruler":
                # ⭐ Two-digit repdigits rather than 1..8: if the client draws
                # the number anywhere, 「66」 says slot 6 without counting, and
                # a value that large cannot be mistaken for a turn or two of
                # some counter running down on its own.
                counters = [
                    11 * (i + 1)
                    for i in range(clubbattle.NUM_OF_CLUB_STATUS)
                ]
            else:
                try:
                    counters = [int(x, 0) for x in spec.split(",") if x != ""]
                except ValueError:
                    return self._say(
                        session, sequence,
                        "/cb states <c0,…,c7 | ruler | off> [@i]",
                    )
                counters = counters[:clubbattle.NUM_OF_CLUB_STATUS]
                counters += [0] * (
                    clubbattle.NUM_OF_CLUB_STATUS - len(counters)
                )
            target.states = counters
            seat = battle.fighters.index(target)
            print(f"[{self.tag}] /cb states: fighter @{seat} "
                  f"{target.chara_id:#x} counters={counters} "
                  f"(every 0x5C09 from now on carries them)")
            return self._say(
                session, sequence,
                f"/cb states @{seat} {counters}",
            )
        if what == "timeout":
            # ⚠️⚠️ A WIRE VALUE, and the only knob in here that is one. Every
            # other branch of this console sends a message; this one changes a
            # number inside the message the fight itself will send next.
            #
            # ⭐ Why it is not one-shot and not an environment knob, the same
            # two reasons turn_start_hp is neither: the question is about the
            # value a TURN OPENS with, so it has to survive to the next turn;
            # and the control and the probe belong in one fight, because
            # standing up a fight is five minutes of clicking.
            #
            # ⭐ Draining it once per logged-in session is harmless: writing
            # the same number twice is the same number.
            if len(args) > 1 and args[1] in ("off", "none", "-"):
                battle.turn_timeout_ms = None
            else:
                try:
                    battle.turn_timeout_ms = int(args[1], 0)
                except (IndexError, ValueError):
                    battle.turn_timeout_ms = None
            shown = (f"{battle.timeout_ms()} ms"
                     if battle.turn_timeout_ms is not None
                     else f"off (the stock {clubbattle.TURN_TIMEOUT_MS} ms)")
            print(f"[{self.tag}] /cb timeout: every 0x5C09 from now on names a "
                  f"deadline {shown} ahead of the reader's clock; this server "
                  f"waits {battle.deadline_s():g}s. ⚠️ The turn already open "
                  f"keeps the deadline it was started with.")
            return self._say(session, sequence, f"/cb timeout {shown}")
        if what == "hold":
            # ⚠️⚠️ This ARMS something; it sends nothing now. The whole point is
            # that the message has to go out on the normal path, at the one
            # moment the client will draw it. See Battle.hold_on_finish.
            #
            # ⭐ Unlike fxnext, running once per logged-in session is harmless
            # here: setting a flag that is already set is the same flag.
            battle.hold_on_finish = True
            try:
                battle.hold_win_team = int(args[1], 0)
            except (IndexError, ValueError):
                battle.hold_win_team = None
            shown = ("as computed" if battle.hold_win_team is None
                     else battle.hold_win_team)
            print(f"[{self.tag}] /cb hold armed: the next finish sends 0x5C1A "
                  f"alone (winTeam={shown}) and leaves the fight standing")
            return self._say(session, sequence, "/cb hold armed")
        if what == "next":
            for fighter in battle.fighters:
                fighter.turn_done = True
            # ⚠️ The limit is checked here as well as on the 0x5C16 path, and it
            # has to be: this probe runs once per LOGGED-IN SESSION, so one
            # ``/cb next`` line advances a two-player fight by two turns and can
            # step straight over TURN_LIMIT. Measured — a fight nudged to turn 9
            # drew 「残り　　ターン」 with the number simply blank, which is a
            # frame the original could not produce. Past the limit this does
            # what the real path does instead of inventing a ninth turn.
            if battle.finished():
                return self._battle_finish(session, battle)
            return self._battle_turn_start(session, battle)

        def number(index: int, fallback: int) -> int:
            try:
                return int(args[index], 0)
            except (IndexError, ValueError):
                return fallback

        if what == "result":
            win_team = number(1, clubbattle.WIN_TEAM_NEITHER)
            if "ruler" in args[2:]:
                # ⭐ 8.8 fixed point (2.30): 値 >> 8 is the level shown minus
                # one, so these draw レベル1〜6 for 「before」 and レベル11〜16
                # for 「after」 — six rows that cannot be mistaken for the other
                # six, and none of them near the u16 sign bit that switches the
                # client to its other rule.
                before = [index * 256 for index in range(6)]
                after = [(index + 10) * 256 for index in range(6)]
                bodies = clubbattle.result_params(
                    win_team,
                    before_gauge=10, after_gauge=90,
                    before_lv=3, after_lv=7,
                    before_ability=before, after_ability=after,
                )
                print(f"[{self.tag}] /cb result winTeam={win_team} ruler: "
                      f"gauge 10/90 lv 3/7 ability {before}/{after}")
                return self._tr_cast(
                    session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_RESULT,
                    bodies, everyone,
                )
            sheets = {f.chara_id: self._battle_sheet(f) for f in battle.fighters}

            def body(chara_id: int) -> bytes:
                params, level, gauge = sheets.get(
                    chara_id, ([0] * clubbattle.NUM_OF_CHARA_ABILITY, 0, 0)
                )
                return clubbattle.result_params(
                    win_team,
                    before_gauge=gauge, after_gauge=gauge,
                    before_lv=level, after_lv=level,
                    before_ability=params, after_ability=params,
                )

            print(f"[{self.tag}] /cb result winTeam={win_team}, real values")
            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_RESULT, body, everyone
            )
        if what == "end":
            reason = number(1, clubbattle.END_NORMAL)
            print(f"[{self.tag}] /cb end reason={reason}")
            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_END,
                clubbattle.end_params(reason), everyone,
            )
        if what == "part":
            # ⭐ The message the disconnect path now sends, without having to
            # disconnect: five minutes of relogin per question is what made
            # 0x5C1B unaskable in the first place.
            #
            # ⚠️⚠️ It deliberately does NOT close the fight, and that is the
            # whole point of having it as well as the real path. 「a disconnect
            # owes the others 0x5C1B」 is restored; 「and then the fight ends」
            # is not, and the real path bundles the two so tightly that a
            # client reacting to the close cannot be told from a client
            # reacting to the message. Here nothing else changes.
            #
            # ⚠️ Once per LOGGED-IN SESSION, like every /cb line. On the default
            # target that is one message naming each fighter, which is the
            # 「about me」 versus 「about somebody else」 comparison /cb effect
            # gets for free the same way; with an explicit @i both sessions send
            # the SAME body, and the second is the re-send that asks whether
            # this draws once and then stops listening, the way the 結果画面
            # does with 0x5C1A.
            target = session.chara_id
            for token in args[1:]:
                if not token.startswith("@"):
                    continue
                try:
                    index = int(token[1:], 0)
                except ValueError:
                    continue
                if 0 <= index < len(battle.fighters):
                    target = battle.fighters[index].chara_id
            plain = [a for a in args[1:] if not a.startswith("@")]
            try:
                reason = int(plain[0], 0)
            except (IndexError, ValueError):
                reason = clubbattle.PART_DISCONNECTED
            print(f"[{self.tag}] /cb part charaId={target:#x} reason={reason} "
                  f"(fight left standing: {battle.summary()})")
            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_PART,
                clubbattle.part_params(target, reason), everyone,
            )
        if what == "presence":
            # ⭐⭐ The probe that pulled round 96's "fatal" pair apart. Back then
            # a client sitting on the 結果画面 was handed 0x4810 + 0x480F, closed
            # the connection and drew 「通信が断たれました」; removing that one
            # refresh fixed it, so the pair got the blame. It could not be
            # checked on the real path -- _presence_refresh is the only thing
            # that sends either message at that moment and it always sends both.
            #
            # ⭐⭐⭐ Round 102 sent them from here instead and the blame did not
            # survive: del alone, add alone, the pair, THREE pairs back to back,
            # and the pair again after a 0x5C1C -- six deliveries onto a live
            # 結果画面, no EOF, no dialog. Whatever killed that client is still
            # in the rest of what _battle_finish wrote in the same turn.
            # ⚠️ The skip= on _presence_refresh stays anyway: that refresh is
            # not owed to anybody (the 0x4000 after ［終 了］ rebuilds the scene),
            # so keeping it costs nothing and the real cause is still unknown.
            #
            # ⚠️⚠️ ONE RECIPIENT — the connection this console line was drained
            # for, never the fight's roster. Every other line here casts to
            # ``everyone`` because it asks what a message DRAWS; this one asks
            # what a connection DOES with it, and a broadcast would take every
            # client down at once, leaving nothing to compare against.
            #
            # ⚠️ And it answers nothing in the chat bar. The others do, which is
            # harmless when the question is a picture; here the client is about
            # to either die or not, and a second message arriving in the same
            # breath would be one more suspect.
            mode = "pair"
            act: "int | None" = None
            for token in args[1:]:
                if token in ("del", "add", "pair"):
                    mode = token
                elif token.startswith("act="):
                    # ⭐⭐ The icon byte, decoupled from room leadership. Round
                    # 103 reproduced round 96 and the batch that killed the
                    # client contained exactly one add carrying
                    # ACTION_TRAINING_ROOM, because the fight's room had just
                    # promoted its second member. Staging that for real needs
                    # the subject to lead a room AND the recipient to be
                    # somebody else -- two real clients, since a scripted
                    # sparring partner has no screen. This asks the same
                    # question with one, and the answer was: the client
                    # survives it. action=10 is not what kills anybody.
                    try:
                        act = int(token[4:], 0)
                    except ValueError:
                        act = None
            subject = None
            for token in args[1:]:
                if not token.startswith("@"):
                    continue
                try:
                    index = int(token[1:], 0)
                except ValueError:
                    continue
                if 0 <= index < len(battle.fighters):
                    subject = battle.fighters[index].chara_id
            if subject is None:
                # ⭐ Default: the other fighter. A presence message is never
                # about the viewer -- the client puts itself into the scene, see
                # _presence_announce -- so aiming this at the recipient would
                # ask nothing at all.
                others = [
                    f.chara_id for f in battle.fighters
                    if f.chara_id != session.chara_id
                ]
                subject = others[0] if others else 0
            about = self._session_of(subject)
            if about is None:
                return self._say(
                    session, sequence,
                    f"/cb presence: charaId {subject:#x} is not connected",
                )
            # ⚠️ Whether the two are on one map is the difference between 「told
            # to edit somebody it can see」 and 「…somebody it never heard of」,
            # and only the first is the pair round 96 measured — _peers filters
            # on exactly this and the real refresh never reaches anyone else.
            # Print it now rather than reconstructing it from the logs later.
            shown_act = ("as computed "
                         f"({self._presence_action(about)})" if act is None
                         else f"FORCED to {act}")
            print(f"[{self.tag}] /cb presence {mode}: charaId={subject:#x} "
                  f"-> charaId={session.chara_id:#x} alone, action {shown_act} "
                  f"(same map: {about.map_id == session.map_id}, "
                  f"fight left standing: {battle.summary()})")
            if mode in ("del", "pair"):
                self._presence_withdraw(about, [session])
            if mode in ("add", "pair"):
                self._presence_announce(about, [session], act)
            return b""
        if what == "finish":
            return self._battle_finish(
                session, battle, number(1, clubbattle.WIN_TEAM_NEITHER),
                send_end="noend" not in args[1:],
                refresh_fighters="refresh" in args[1:],
            )
        if what in ("react", "effect"):
            # ⭐ The target defaults to the SENDER, which turns this probe's one
            # awkward property into the useful half of the experiment: a console
            # line is drained once per logged-in session, so in a two-player
            # fight one ``/cb effect`` goes out twice — once aimed at each
            # fighter — and both clients see both. That is the comparison the
            # measurement needs anyway (what does an effect ON ME look like
            # versus one on the other guy), delivered without a second command.
            # ⚠️ An explicit index makes it aim somewhere fixed instead, which
            # is what to use once the two forms need telling apart.
            target = session.chara_id
            index = None
            for token in args[1:]:
                if token.startswith("@"):
                    try:
                        index = int(token[1:], 0)
                    except ValueError:
                        continue
            if index is not None and 0 <= index < len(battle.fighters):
                target = battle.fighters[index].chara_id
            numbers = [a for a in args[1:] if not a.startswith("@")]

            def arg(position: int, fallback: int) -> int:
                try:
                    return int(numbers[position], 0)
                except (IndexError, ValueError):
                    return fallback

            if what == "react":
                reaction = arg(0, 0)
                name = (
                    clubbattle.REACTION_NAMES[reaction]
                    if 0 <= reaction < len(clubbattle.REACTION_NAMES)
                    else "?"
                )
                print(f"[{self.tag}] /cb react target={target:#x} "
                      f"reaction={reaction} (candidate name: {name})")
                return self._tr_cast(
                    session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_REACTION,
                    clubbattle.reaction_params(target, reaction), everyone,
                )
            # ⭐⭐ value defaults to the type number rather than to something
            # round, so a sweep labels itself: whatever the screen draws for
            # ``type=5`` shows a 5, and a frame caught mid-sweep still says
            # which code drew it. ⚠️ Without that, reading a sweep means
            # trusting the order the messages were sent in, which is exactly
            # the assumption a sweep is supposed to test.
            effect_type = arg(0, 0)
            value = arg(1, effect_type)
            value2 = arg(2, 0)
            print(f"[{self.tag}] /cb effect target={target:#x} "
                  f"type={effect_type} value={value} value2={value2}")
            return self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_EFFECT,
                clubbattle.effect_params(target, effect_type, value, value2),
                everyone,
            )
        return self._say(session, sequence, f"/cb: unknown '{what}'")

    def _battle_replay_fx(
        self, session: "_Session", battle: "clubbattle.Battle", args: "list[str]"
    ) -> bytes:
        """``/cb fx [type] [value] [value2] [reaction]``: a turn WITH 0x5C10/0x5C11 in it.

        ⚠️⚠️ THIS IS WHY A LONE ``/cb effect`` IS NOT THE EXPERIMENT. Round 88
        measured that the client HOLDS a turn's actions until 0x5C12 DemoStart
        tells it to play them — 0x5C0D and both 0x5C0E/0x5C0F pairs drew nothing
        at all until one body-less 0x5C12 arrived. So a 0x5C11 sent on its own,
        outside a stream, is being sent into the same silence: 「the screen drew
        nothing」 would then say nothing about the message, only about when it
        was sent. This rebuilds the whole stream with the effects inside it and
        ends with the DemoStart that makes it run.

        ⚠️ WHERE IN THE STREAM THEY GO IS A GUESS, and the first one worth
        trying: between 0x5C0E ActionBegin and 0x5C0F ActionEnd, because that
        pair brackets one character's action and these two are what that action
        DID (see action_end_params). Nothing read so far excludes them sitting
        after 0x5C0F instead, or being a stream of their own. ⭐ A screen that
        draws nothing here does NOT settle the meaning of ``type`` — it would
        first have to be retried at the other position, and that ambiguity is
        the price of not having found the client's handler.

        ⚠️ Like ``/cb replay`` this reads the commands the fighters already
        chose, so it only has something to replay between a turn resolving and
        the next one starting.
        """

        def arg(position: int, fallback: int) -> int:
            try:
                return int(args[position], 0)
            except (IndexError, ValueError):
                return fallback

        effect_type = arg(0, 0)
        value = arg(1, effect_type)
        value2 = arg(2, 0)
        reaction = arg(3, 0)
        everyone = [f.chara_id for f in battle.fighters]
        plays = []
        for fighter in battle.actors():
            card = self._battle_deck_item(fighter)
            if card is not None:
                plays.append((fighter, card[0], card[1]))
        if not plays:
            return self._say(
                session, 0, "/cb fx: nobody has a card chosen to replay"
            )
        print(f"[{self.tag}] /cb fx: type={effect_type} value={value} "
              f"value2={value2} reaction={reaction}, {len(plays)} action(s)")
        out = self._tr_cast(
            session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_ORDER,
            clubbattle.action_order_params([f.chara_id for f, _k, _p in plays]),
            everyone,
        )
        for fighter, kind, payload in plays:
            assert fighter.command is not None
            _item_num, _is_attck, target_id = fighter.command
            # ⭐ Aimed at the command's OWN target, so the effect lands on
            # whoever the card was played at rather than on a fixed character.
            # That is what makes 「did it draw on the right person」 answerable.
            out += self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_BEGIN,
                clubbattle.action_begin_params(
                    fighter.chara_id, kind, payload, target_id
                ),
                everyone,
            )
            out += self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_REACTION,
                clubbattle.reaction_params(target_id, reaction), everyone,
            )
            out += self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_EFFECT,
                clubbattle.effect_params(target_id, effect_type, value, value2),
                everyone,
            )
            out += self._tr_cast(
                session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_ACTION_END,
                clubbattle.action_end_params(fighter.chara_id), everyone,
            )
        return out + self._tr_cast(
            session, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_DEMO_START, b"", everyone
        )

    def _battle_turn_start(
        self, session: "_Session", battle: "clubbattle.Battle"
    ) -> bytes:
        """0x5C09, once every fighter has said its scene is up.

        ⚠️ ``timeoutTime`` is named on each RECIPIENT's own clock, so the
        deadline is computed per session rather than once — the same rule
        0x480A's arrivalTime is under (2.15: copying one client's moment to
        another teleports them). The turn number and everybody's numbers are
        identical for all of them; only the deadline is re-read.

        seen=0: this follows the 0x5C08 that answered the last 0x5C07, it does
        not answer anything itself.
        """
        battle.begin_turn()
        rows = battle.turn_rows()
        # ⭐ The same deadline the wire states, kept on OUR clock as well: the
        # timeoutTime below is a moment on each client's timebase and cannot be
        # compared against anything here. See _drain_battle for what runs when
        # it passes, and _Session.battle_due for why every fighter's session
        # gets a copy.
        # ⚠️ deadline_s(), not TURN_TIMEOUT_MS: normally the same 60 seconds,
        # but a measuring session can stretch THIS side alone (see the
        # constant), and /cb timeout moves both together.
        battle.deadline = time.monotonic() + battle.deadline_s()
        for fighter in battle.fighters:
            other = self._session_of(fighter.chara_id)
            if other is not None:
                other.battle_due = battle.deadline
        print(f"[{self.tag}] battle turn start: turn={battle.turn} "
              f"({len(rows)} fighter(s))")

        def body(chara_id: int) -> bytes:
            other = self._session_of(chara_id)
            clock = (other or session).client_now()
            return clubbattle.turn_start_params(
                battle.turn, clock + battle.timeout_ms(), rows
            )

        return self._tr_cast(
            session,
            0,
            clubbattle.MSG_SV_NOTIFY_BATTLE_TURN_START,
            body,
            [f.chara_id for f in battle.fighters],
        )

    def _cb_part_notice(
        self, battle: "clubbattle.Battle", gone_id: int, reason: int
    ) -> None:
        """0x5C1B to whoever else was in the fight. Push-only, no sender copy.

        The battle's own 0x580D twin: call it with the Battle that Board.leave
        just handed back, so the leaver is already marked gone when the pushes
        go out — and BEFORE _battle_carry_on, so the survivors learn who left
        before they are handed the next turn.

        ⚠️ ``battle.fighters`` still holds the leaver — the roster on the wire
        never shrinks, see Fighter.gone — so they are skipped explicitly here
        rather than by the roster having lost them, which is how
        _tr_part_notice does it. On the disconnect path the socket is already
        gone and _push would drop the write anyway; on the 「中断」 path it is
        NOT, and the leaver is on their way to the character select with no
        fight to be told about.

        ⚠️ One message per survivor and no sender copy, so unlike _tr_cast
        there is nothing to return: both callers are in teardown paths that
        have no reply of their own to append it to.
        """
        params = clubbattle.part_params(gone_id, reason)
        for fighter in battle.fighters:
            if fighter.chara_id == gone_id:
                continue
            other = self._session_of(fighter.chara_id)
            if other is not None:
                self._push(
                    other,
                    self._answer(
                        other, 0, clubbattle.MSG_SV_NOTIFY_BATTLE_PART, params
                    ),
                )

    def _battle_carry_on(self, battle: "clubbattle.Battle") -> None:
        """Restart a fight that was waiting on the fighter who just left.

        Call it right after Board.leave, and after the 0x5C1B that says who
        went: the survivors should hear what happened before they are handed
        the next turn.

        ⚠️⚠️ Only the two places a fight waits for a REPORT are unstuck here,
        because those are the only two nothing else covers:

        * the last 0x5C07 (all_ready) — the fight has not begun;
        * the last 0x5C16 (all_turn_done) — a played turn cannot advance.

        The third wait, for the last 0x5C0A, is already covered by the 制限時間:
        _drain_battle fires on the survivor's own deadline, tells everybody the
        missing choices were 「間に合いませんでした」 and plays the turn. Doing it
        here as well would resolve the turn early and skip that 0x5C0C — the
        one the client sits and waits for (round 88, see _drain_battle).

        ⚠️ Everything is driven off a SURVIVOR's session, not the leaver's: the
        leaver's socket is on its way out, and _tr_cast returns that session's
        own copy for a caller to write. Nobody is going to write theirs.
        """
        if battle.abandoned() or not battle.all_ready():
            return
        driver = None
        for fighter in battle.active():
            driver = self._session_of(fighter.chara_id)
            if driver is not None:
                break
        if driver is None:
            return
        if battle.turn < clubbattle.FIRST_TURN:
            print(f"[{self.tag}] battle carries on: everyone left is ready, "
                  f"starting the first turn")
            out = self._battle_turn_start(driver, battle)
        elif battle.resolved and battle.all_turn_done():
            if battle.finished():
                print(f"[{self.tag}] battle carries on: last turn was already "
                      f"played, showing the result")
                out = self._battle_finish(driver, battle)
            else:
                print(f"[{self.tag}] battle carries on: turn {battle.turn} was "
                      f"already played, starting the next one")
                out = self._battle_turn_start(driver, battle)
        else:
            # Mid-turn: the choices are still open and the deadline owns them.
            return
        self._push(driver, out)

    def _tr_part_notice(
        self, room: "trainingroom.Room", gone_id: int, leader_id: int, reason: int
    ) -> None:
        """0x580D to whoever is still in the room. Push-only, no sender copy.

        Call it after Board.part, so ``room.members`` is already the list of
        people who need telling and the leaver cannot be told twice.

        ⚠️ ``leader_id`` is the room's leader BEFORE the part, because that is
        the id every remaining client is naming this room by. When the leader is
        the one who left, Board.part promotes somebody — and this family has no
        message for that, so the remaining clients keep naming the room by an id
        that no longer leads it. NOT MEASURED, and not inventable from what is
        on hand: see the ⚠ log line in _trainingroom's part branch.
        """
        params = trainingroom.notify_part_params(gone_id, leader_id, reason)
        for member in room.members:
            other = self._session_of(member.chara_id)
            if other is not None:
                self._push(
                    other,
                    self._answer(other, 0, trainingroom.MSG_SV_NOTIFY_PART, params),
                )

    def _trainingroom(
        self, session: "_Session", sequence: int, msg_type: int, params: bytes
    ) -> "bytes | None":
        """The whole 0x58xx family, dispatched off one branch.

        Every Notify here goes to the whole room, which is what _tr_cast is for.
        ⚠️ Until round 69 they were all reflected straight back to the sender —
        correct only because a room could hold exactly one person, and quietly
        wrong the moment two accounts could log in at once. See trainingroom.py.
        """
        board = self.trainingrooms
        chara_id = session.chara_id

        def ng(msg: int, reason: int, why: str) -> bytes:
            print(f"[{self.tag}] trainingroom refused ({why}): reason={reason}")
            return self._answer(session, sequence, msg, trainingroom.ng_params(reason))

        if msg_type == trainingroom.MSG_CL_REQUEST_ADD:
            # 「看板作成」. ⚠️ Some of this window's gating never reaches us —
            # 「他の行動中は看板を作成できません」 is one of tmo.exe's own
            # strings, so the client has already said no to some presses.
            parsed = trainingroom.parse_add(params)
            headline, limit = parsed if parsed else (None, 0)
            # ⭐⭐⭐ RESTORED, sentence and reason byte both: 0x5802 reason 11 is
            # 「怪我をしていると、自主トレに参加することはできません。」 — the
            # client has been carrying that string all along and this end never
            # sent the byte that draws it. See stress.barred_from_club.
            reason = (trainingroom.NG_ADD_INJURED if self._injured(session)
                      else board.add_refusal(chara_id, headline, limit))
            if reason is not None:
                return ng(trainingroom.MSG_SV_NG_ADD, reason, f"add {params.hex()}")
            family, first = self._tr_names(chara_id)
            room = board.open(chara_id, headline, limit, family, first)
            print(f"[{self.tag}] trainingroom opened {room.summary()}")
            # The board over their head is how anybody else gets in.
            self._presence_refresh(session)
            out = self._answer(session, sequence, trainingroom.MSG_SV_OK_ADD, b"")
            # An empty 0x580C, and it stays: the leader is the only member, so
            # the roster without them is 「nobody else is here」, which is both
            # true and what the window drew when this was measured.
            return out + self._tr_seat(session, room, room.members[0])

        if msg_type == trainingroom.MSG_CL_REQUEST_INFO:
            leader_id = trainingroom.parse_leader(params)
            room = board.rooms.get(leader_id) if leader_id is not None else None
            if room is None:
                return ng(
                    trainingroom.MSG_SV_NG_INFO,
                    trainingroom.NG_INFO_NOT_FOUND,
                    f"info leaderId={leader_id}",
                )
            return self._answer(
                session, sequence, trainingroom.MSG_SV_OK_INFO, room.info_params()
            )

        if msg_type == trainingroom.MSG_CL_REQUEST_JOIN:
            leader_id = trainingroom.parse_leader(params)
            if leader_id is None:
                return ng(
                    trainingroom.MSG_SV_NG_JOIN,
                    trainingroom.NG_JOIN_NOT_FOUND,
                    "join with no leaderId",
                )
            # The same rule at the other door; 0x5808 reason 10 is its sentence.
            reason = (trainingroom.NG_JOIN_INJURED if self._injured(session)
                      else board.join_refusal(chara_id, leader_id))
            if reason is not None:
                return ng(
                    trainingroom.MSG_SV_NG_JOIN, reason, f"join leaderId={leader_id:#x}"
                )
            room = board.rooms[leader_id]
            family, first = self._tr_names(chara_id)
            joiner = room.add(chara_id, family, first)
            print(f"[{self.tag}] trainingroom joined {room.summary()}")
            out = self._answer(
                session, sequence, trainingroom.MSG_SV_OK_JOIN, room.join_params()
            )
            # ⚠️ Order: the Ok carries the headline and the cap, so it has to be
            # the packet that opens the window before any row arrives for it.
            return out + self._tr_seat(session, room, joiner)

        if msg_type == trainingroom.MSG_CL_REQUEST_PART:
            room = board.room_of(chara_id)
            if room is None:
                return ng(
                    trainingroom.MSG_SV_NG_PART,
                    trainingroom.NG_PART_NOT_IN_ROOM,
                    "part while in no room",
                )
            leader_id = room.leader_id
            board.part(chara_id)
            print(f"[{self.tag}] trainingroom left, now {board.summary()}")
            # Take the board down again -- and put one up over whoever Board.part
            # promoted, if it promoted anybody.
            self._presence_refresh(session)
            if room.members and chara_id == leader_id:
                promoted = self._session_of(room.leader_id)
                if promoted is not None:
                    self._presence_refresh(promoted)
            if room.members and chara_id == leader_id:
                print(f"[{self.tag}] ⚠ leader left a room that still has "
                      f"{len(room.members)} in it; promoted {room.leader_id:#x}, "
                      f"and no message in this family says so")
            out = self._answer(session, sequence, trainingroom.MSG_SV_OK_PART, b"")
            # ⚠️ The Notify goes to the leaver too, even when the room is now
            # empty: it is what tells a client its own row is gone. For them the
            # reason is 「自分自身の要求による」 — and for the people left behind
            # it is the same sentence about the same event, so one body serves.
            out += self._answer(
                session,
                0,
                trainingroom.MSG_SV_NOTIFY_PART,
                trainingroom.notify_part_params(
                    chara_id, leader_id, trainingroom.PART_REASON_SELF
                ),
            )
            self._tr_part_notice(
                room, chara_id, leader_id, trainingroom.PART_REASON_SELF
            )
            return out

        if msg_type == trainingroom.MSG_CL_CAST_CHAT:
            room = board.room_of(chara_id)
            read = trainingroom.parse_string(params)
            if room is None or read is None:
                return ng(
                    trainingroom.MSG_SV_ERROR_CHAT,
                    trainingroom.ERROR_CHAT_FAILED,
                    "room chat outside a room",
                )
            said, _ = read
            family, first = self._tr_names(chara_id)
            print(f"[{self.tag}] trainingroom chat: {said.decode('cp932', 'replace')!r}")
            # The speaker is in the list on purpose. 0x580E is a cast: nothing
            # appears in anyone's room window, the speaker's included, until the
            # server says it back — the same arrangement 0x4901 chat uses.
            return self._tr_cast(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_CHAT,
                trainingroom.notify_chat_params(chara_id, family, first, said),
                [m.chara_id for m in room.members],
            )

        if msg_type == trainingroom.MSG_CL_CAST_READY:
            room = board.room_of(chara_id)
            member = room.find(chara_id) if room else None
            if member is None:
                return ng(
                    trainingroom.MSG_SV_ERROR_READY,
                    trainingroom.ERROR_READY_FAILED,
                    "ready outside a room",
                )
            member.ready = trainingroom.parse_ready(params)
            # Both numbers, because they disagree on purpose: the wire's 0 is
            # 「準備ＯＫ」. See READY_ON in trainingroom.py.
            print(f"[{self.tag}] trainingroom ready={member.ready} "
                  f"(wire {params.hex() or '-'}) for {chara_id:#x}")
            # ⭐ The presser is still sent their own echo, which keeps round 67's
            # open question answerable: whether the badge is drawn off our 0x5812
            # or off the press itself is still not separated, and taking the echo
            # away now would change two things at once.
            return self._tr_cast(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_READY,
                trainingroom.notify_ready_params(chara_id, member.ready),
                [m.chara_id for m in room.members],
            )

        if msg_type == trainingroom.MSG_CL_REQUEST_TEAM_SELECT:
            room = board.room_of(chara_id)
            member = room.find(chara_id) if room else None
            team = trainingroom.parse_team(params)
            # ⭐ Logged raw and unconditionally: this byte is the only place the
            # client says which two values a team is numbered with, and nothing
            # else measures it. See TEAMS in trainingroom.py.
            print(f"[{self.tag}] trainingroom team select: raw byte {team!r}")
            if member is None:
                return ng(
                    trainingroom.MSG_SV_NG_TEAM_SELECT,
                    trainingroom.NG_TEAM_FAILED,
                    "team select outside a room",
                )
            if team not in trainingroom.TEAMS:
                return ng(
                    trainingroom.MSG_SV_NG_TEAM_SELECT,
                    trainingroom.NG_TEAM_BAD_TEAM,
                    f"team {team!r} is neither Ａ(0) nor Ｂ(1)",
                )
            member.team = team
            out = self._answer(session, sequence, trainingroom.MSG_SV_OK_TEAM_SELECT, b"")
            # ⚠️ No 0x580C follows any more. There used to be one and it was
            # invisible rather than right: with one member the roster-without-me
            # is empty, so it proved nothing, and sending a real one here would
            # re-add rows every recipient already has (Room.roster_params).
            # 0x5817 names a charaId and a team, which is a move instruction —
            # if the row did not exist the client would have nothing to move.
            return out + self._tr_cast(
                session,
                0,
                trainingroom.MSG_SV_NOTIFY_TEAM,
                trainingroom.notify_team_params(chara_id, team),
                [m.chara_id for m in room.members],
            )

        if msg_type == trainingroom.MSG_CL_CAST_BATTLE_START:
            room = board.room_of(chara_id)
            if room is None or room.leader_id != chara_id:
                return ng(
                    trainingroom.MSG_SV_ERROR_BATTLE_START,
                    trainingroom.ERROR_START_FAILED,
                    "start without leading a room",
                )
            if not room.all_ready():
                return ng(
                    trainingroom.MSG_SV_ERROR_BATTLE_START,
                    trainingroom.ERROR_START_NOT_ALL_READY,
                    "start before everyone is ready",
                )
            # ⚠️ 0x5819 is empty, so this says only 「it begins」. What draws the
            # battle is the 0x5C** family, and it follows immediately below:
            # the client does not act on this message, it waits for 0x5C06.
            # See clubbattle for why that took five rounds to see.
            print(f"[{self.tag}] trainingroom battle start: {room.summary()}")
            begun = self._tr_cast(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_BATTLE_START,
                b"",
                [m.chara_id for m in room.members],
            )
            return begun + self._battle_info(session, room)

        if msg_type == trainingroom.MSG_CL_NOTIFY_BATTLE_START:
            # Client -> server, no reply: it is telling us it has the scene up.
            print(f"[{self.tag}] trainingroom battle scene is up on the client")
            return None

        if msg_type == trainingroom.MSG_CL_CAST_KICK:
            room = board.room_of(chara_id)
            target = trainingroom.parse_leader(params)
            if room is None or room.leader_id != chara_id:
                return ng(
                    trainingroom.MSG_SV_ERROR_KICK,
                    trainingroom.ERROR_KICK_NOT_LEADER,
                    "kick without leading a room",
                )
            if target is None or target == chara_id or room.find(target) is None:
                return ng(
                    trainingroom.MSG_SV_ERROR_KICK,
                    trainingroom.ERROR_KICK_UNKICKABLE,
                    f"kick charaId={target!r}",
                )
            leader_id = room.leader_id
            board.part(target)
            print(f"[{self.tag}] trainingroom kicked {target:#x}, now {board.summary()}")
            params = trainingroom.notify_part_params(
                target, leader_id, trainingroom.PART_REASON_KICKED
            )
            # ⚠️ The kicked player is the one who most needs this and is the one
            # part() just took off the member list, so they are pushed by name
            # rather than reached through the room. 「リーダーに排除された」 is
            # their notice; the same body tells everybody else the row is gone.
            kicked = self._session_of(target)
            if kicked is not None:
                self._push(
                    kicked,
                    self._answer(
                        kicked, 0, trainingroom.MSG_SV_NOTIFY_PART, params
                    ),
                )
            # The leader is still seated, so their copy comes back through
            # _tr_cast as the reply — going through _tr_part_notice as well
            # would send it to them twice. No 0x580C: see the team-select
            # branch for why a roster refresh is not how a row is taken away.
            return self._tr_cast(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_PART,
                params,
                [m.chara_id for m in room.members],
            )

        print(f"[{self.tag}] no reply implemented for 0x{msg_type:04x} yet")
        return None

    def _seq_probe(
        self, session: "_Session", sequence: int, args: "list[str]"
    ) -> bytes:
        """``/seq [n] [ok]``: hand this connection a sequence number that went backwards.

        ⚠️⚠️ A PROBE, and the one probe here whose PURPOSE is to kill the client.
        It exists to test, with nothing else attached, the suspect that rounds
        96/103/104 kept dragging along: not what a batch of messages said, and
        not what order the *messages* were in, but whether the sequence number
        in the packet header went DOWN.

        _Session's own docstring already names the check on the other side:
        decipher_message (0xA4C4D0) keeps the last sequence it accepted and
        drops anything not strictly greater with 「bad sequence number」. What
        was never measured is what a client DOES with that rejection — ignore
        the message, or drop the connection.

        ⭐⭐ WHY THIS SHAPE. A handler's reply is numbered when it is built and
        written when it returns; _push writes immediately. So a handler that
        pushes to its OWN caller after building its reply hands that connection
        a high number first and a low one second. That is not a hypothetical:
        it is exactly what _battle_finish(refresh_fighters=True) does, and the
        skip= in _battle_leave_rooms is what keeps the shipped path away from
        it. Every measured death has it (round 96a: 1877 then 1866; round 103b:
        1097 then 1088; round 104B: 1152 then 1143) and no survivor does.

        Both forms send the same n+1 chat lines, to the same connection, in the
        same order on the wire. The ONLY difference is which line got the lower
        number, and that is the whole point: every earlier cut at this question
        moved two things at once, so none of them could name one.

        * ``/seq n``     — reply numbered FIRST, pushes numbered after it, reply
                           written last. The client is handed n+1, …, then n.
        * ``/seq n ok``  — pushes numbered first, reply numbered last. Same
                           lines, same arrival order, numbers ascending. This is
                           the control and it must survive.

        ⭐ The pushed lines land in the chat bar before the verdict, so the
        screen itself says the client was alive and parsing right up to the
        stale one.
        """
        control = "ok" in args
        try:
            count = next(int(a) for a in args if a.lstrip("-").isdigit())
        except (StopIteration, ValueError):
            count = 2
        count = max(0, min(count, 20))
        note = "ascending (control)" if control else "STALE"

        def pushed(i: int) -> bytes:
            return self._say(session, 0, f"/seq: pushed line {i + 1} of {count}")

        reply = b"" if control else self._say(
            session, sequence, f"/seq: reply, numbered before {count} pushes"
        )
        for i in range(count):
            self._push(session, pushed(i))
        if control:
            reply = self._say(
                session, sequence, f"/seq: reply, numbered after {count} pushes"
            )
        print(f"[{self.tag}] /seq: {count} pushes then a reply, numbering is "
              f"{note} — charaId={session.chara_id:#x}. If the connection drops "
              f"here, 0xA4C4D0 rejected the reply with 「bad sequence number」")
        return reply

    def _group_console(
        self, session: "_Session", sequence: int, args: "list[str]"
    ) -> bytes:
        """``/group ...``: the 仲良しグループ store, from the console.

        ⚠️ This is the only way into the store right now, and it is a stand-in
        for two things that do not exist here: the リーダー試験 NPC event, which
        is what awards 「リーダー資格」 in the real game, and the 0x6200 create
        handshake, which is what the client would send once the button that
        sends it is reachable. Both write exactly what this writes.

        ⭐ Most of this takes effect on a client that is already logged in only
        after a 登校. All four fields ride in MsgSvResultCharaInfo, which the
        client asks for once when a character enters the scene and then keeps.
        ⚠️ friendGroupId is the exception, because it rides in the 0x480F entry
        as well: the lines that change who is in a group redraw the characters
        they moved, so the PC menu on somebody else's screen keeps up without a
        再ログイン. The name and the two leader flags still need one.

            /group                     what the store holds
            /group qual on|off         leaderQualificationFlag for me
            /group create <name>       found one, me as leader
            /group join <charaId>      put somebody else in mine (hex ok)
            /group leave               脱退 -- the leader leaving disbands it
            /group disband             解散
            /group hand <charaId>      引継 -- hand the group to a member (hex ok)

        ⚠️ `hand` is the store half of 0x620D..0x6213 with the handshake taken
        out. It exists so a test can put an account on either side of the leader
        flag in one line; the wire path is _group_transfer and it asks the other
        end first.
        """
        book = self.accounts.groups
        me = session.chara_id
        what = args[0].lower() if args else ""
        mine = book.of(me)

        def state() -> str:
            where = mine.label() if mine is not None else "no group"
            qual = "yes" if me in book.qualified else "no"
            return f"/group {where}, qualified={qual} [{book.summary()}]"

        if not what:
            return self._say(session, sequence, state())
        if what == "qual":
            on = args[1:2] != ["off"]
            book.qualify(me, on)
            return self._say(session, sequence, f"/group qual {'on' if on else 'off'} "
                                                f"(re-login to see it)")
        if what == "create":
            name = " ".join(args[1:]).strip()
            if not name:
                return self._say(session, sequence, "/group create <name>")
            group = book.create(me, groups.name_bytes(name))
            if group is None:
                return self._say(session, sequence, f"/group: already in {mine.label()}")
            self._presence_refresh_onlookers(session)
            return self._say(session, sequence, f"/group created {group.label()} "
                                                f"(re-login to see the name)")
        if what == "join":
            if mine is None:
                return self._say(session, sequence, "/group: found one first")
            try:
                other = int(args[1], 0)
            except (IndexError, ValueError):
                return self._say(session, sequence, "/group join <charaId>")
            ok = book.join(mine.id, other)
            if ok:
                joined = self._session_of(other)
                if joined is not None:
                    self._presence_refresh_onlookers(joined)
            return self._say(session, sequence, f"/group join {other:#x}: "
                                                f"{'ok' if ok else 'refused'}")
        if what == "hand":
            if mine is None or mine.leader != me:
                return self._say(session, sequence, "/group: not the leader of one")
            try:
                other = int(args[1], 0)
            except (IndexError, ValueError):
                return self._say(session, sequence, "/group hand <charaId>")
            ok = book.hand_over(mine.id, other)
            return self._say(session, sequence, f"/group hand {other:#x}: "
                                                f"{'ok' if ok else 'refused'} "
                                                f"(re-login to see it)")
        if what in ("leave", "disband"):
            if mine is None:
                return self._say(session, sequence, "/group: not in one")
            was = mine.label()
            members = list(mine.members)
            if what == "leave":
                book.leave(me)
            else:
                book.disband(mine.id)
            # ⚠️ 脱退 by a member moves one character; 解散 -- and 脱退 by the
            # leader, which GroupBook.leave folds into 解散 -- moves everybody
            # who was in it, so redraw the lot rather than just this session.
            for member in members:
                moved = self._session_of(member)
                if moved is not None and book.of(member) is None:
                    self._presence_refresh_onlookers(moved)
            return self._say(session, sequence, f"/group left {was} (re-login to see it)")
        return self._say(session, sequence, f"/group: unknown '{what}'")

    def _couple_console(
        self, session: "_Session", sequence: int, args: "list[str]"
    ) -> bytes:
        """``/couple ...``: the カップル pair, from the console.

            /couple                    who this character is paired with
            /couple <charaId>          pair with that character (hex ok)
            /couple clear              break the pair

        ⚠️⚠️ **This is a knob on two wire fields, not a 交際 system.** The
        manual (`manual/p05_12`) says a couple exists and that 恋人 get an extra
        「デート申込み」 on each other's 交流メニュー; it says nothing about how a
        pair is made, refused or broken, and there is no handshake in the
        message table to read one off. Round 154 measured the other half and it
        is worse than unattested — see PROTOCOL 2.104:

          * the ring is **eight fixed slots**, menu item ids 0..7, built by the
            constructor at 0x6A6AE8 walking the 8-record table at 0xD85790;
          * slot 1 **is** デートチャット, 表示文「デート申込み」, and its 有効
            word in `menu_item.bin` is **0** -- the gate at 0x6A6E4F reads that
            byte (+0x39) and refuses;
          * slot 7 ＧＭチャット has a CanUse of ``xor al,al; ret 4``.

        ⇒ six items is a **ceiling in the client**, and no value of these two
        fields moves it. ⭐ What coupleFlag *does* drive is the pink heart on
        the right-click info box; loverCharaId drives nothing anyone has found.
        See characters.lover for both halves.

        ⭐ Both sides are written when both are reachable, because a couple with
        one arrow is not a state the game has a name for. When the other id
        belongs to no account here -- a probe, a stand-in -- only this side is
        set, and the reply says so rather than pretending it paired.

        ⚠️ Takes effect on an already-logged-in client only after the *other*
        character re-enters the scene: both fields ride in 0x6501 alone, which
        is asked once per character per 登校. The 74-byte 0x480F entry has no
        room for either, so _presence_refresh_onlookers cannot help here the way
        it does for friendGroupId.
        """
        me = session.chara_id
        mine = self._chars(session)
        what = args[0].lower() if args else ""

        def state() -> str:
            lover = mine.lover(me)
            if not lover:
                return "/couple 恋人なし (coupleFlag=0)"
            return f"/couple loverCharaId={lover:#x} (coupleFlag=1)"

        if not what:
            return self._say(session, sequence, state())
        if what == "clear":
            was = mine.lover(me)
            if not was:
                return self._say(session, sequence, "/couple 恋人なし (何もしていない)")
            mine.set_lover(me, 0)
            other = self.accounts.owner_of(was)
            if other is not None and other.lover(was) == me:
                other.set_lover(was, 0)
            return self._say(session, sequence, f"/couple cleared {was:#x} "
                                                f"(相手の再入場で反映)")
        try:
            other_id = int(what, 0)
        except ValueError:
            return self._say(session, sequence, f"/couple: unknown '{what}'")
        if other_id == me:
            return self._say(session, sequence, "/couple: 自分とは組めない")
        if not mine.set_lover(me, other_id):
            return self._say(session, sequence, "/couple: このキャラが見つからない")
        store = self.accounts.owner_of(other_id)
        both = store is not None and store.set_lover(other_id, me)
        return self._say(session, sequence, f"/couple loverCharaId={other_id:#x} "
                                            f"{'両側' if both else '片側のみ'} "
                                            f"(相手の再入場で反映)")

    def _apply_chat(self, session: "_Session", sequence: int, said: str) -> bytes:
        """Run one console line and pack whatever it asked for.

        Split out of the chat branch so that runtime/console.txt can reach the
        same commands — see _drain_console for why that had to exist.
        """
        if said.split()[:1] == ["/cb"]:
            return self._battle_probe(session, sequence, said.split()[1:])
        if said.split()[:1] == ["/seq"]:
            return self._seq_probe(session, sequence, said.split()[1:])
        if said.split()[:1] == ["/group"]:
            return self._group_console(session, sequence, said.split()[1:])
        if said.split()[:1] == ["/couple"]:
            return self._couple_console(session, sequence, said.split()[1:])
        reply = b""
        info = self._chars(session).find(session.chara_id)
        love = self._chars(session).romance(session.chara_id)
        card = self._chars(session).scorecard(session.chara_id)
        sheet = self._chars(session).ability(session.chara_id)
        member = self._chars(session).club(session.chara_id)
        inv = self._chars(session).items(session.chara_id)
        locker = self._locker(session)
        opts = self._chars(session).options(session.chara_id)
        cv = self._chars(session).career(session.chara_id)
        held = self._chars(session).posts(session.chara_id)
        answer = chat.respond(
            said, session.map_id, session.pos, love, card, session.lesson,
            sheet, session.in_class, session.exam, member, inv, locker, opts,
            cv, sum(card.attendance) if card is not None else 0,
            len(member.skills) if member is not None else 0, held,
        )
        if answer.romance_save and love is not None:
            self._chars(session).set_romance(session.chara_id, love)
        if answer.scorecard_save and card is not None:
            self._chars(session).set_scorecard(session.chara_id, card)
        if answer.ability_save and sheet is not None:
            self._chars(session).set_ability(session.chara_id, sheet)
        if answer.club_save and member is not None:
            self._chars(session).set_club(session.chara_id, member)
        if answer.item_save and inv is not None:
            self._chars(session).set_items(session.chara_id, inv)
        if answer.options_save and opts is not None:
            self._chars(session).set_options(session.chara_id, opts)
        if answer.career_save and cv is not None:
            self._chars(session).set_career(session.chara_id, cv)
        if answer.posts_save and held is not None:
            self._chars(session).set_posts(session.chara_id, held)
        if answer.debut is not None:
            self._chars(session).set_debut_pending(session.chara_id, answer.debut)
        if answer.locker_save:
            self.accounts.save_locker(session.account_id)
        if answer.npc_event is not None:
            session.npc_event = answer.npc_event
        if answer.sub_menu is not None:
            session.sub_menu = answer.sub_menu
        if answer.npc_event_end is not None:
            session.npc_event_end = answer.npc_event_end
        if answer.select is not None:
            # (-1, -1) is /sel with no arguments: hand the decision back to the
            # script's own option count rather than remembering a number.
            session.select_override = (
                None if answer.select == (-1, -1) else answer.select
            )
        for line in answer.lines:
            reply += self._answer(
                session,
                sequence,
                MSG_SV_NOTIFY_NORMAL_CHAT,
                chat.notify_params(session.chara_id, chat.SERVER_NAME, line),
            )
        if answer.action_probes and info is not None:
            # The same trick as the direction ruler, one field over. Its ids sit
            # in their own slice so a screen can hold both rulers at once.
            act_entries = [
                add_entry(
                    ACTION_PROBE_ID_BASE + index,
                    info,
                    pos=(pos_x, pos_y),
                    names=marker_names(label),
                    map_id=session.map_id,
                    action=value,
                )
                for index, (label, pos_x, pos_y, value) in enumerate(
                    answer.action_probes
                )
            ]
            print(
                f"[{self.tag}] action ruler: {len(act_entries)} stand-ins "
                f"on map {session.map_id} around {session.pos}"
            )
            for batch in range(0, len(act_entries), ADD_BATCH):
                part = act_entries[batch : batch + ADD_BATCH]
                reply += self._answer(
                    session,
                    sequence,
                    MSG_SV_NOTIFY_CHARACTER_ADD,
                    struct.pack(">H", len(part)) + b"".join(part),
                )
        if answer.probes and info is not None:
            # A ruler for the direction field, drawn without a reload:
            # nothing says MsgSvNotifyCharacterAdd may only be sent
            # once, and the stand-ins are new charaIds, so the client
            # adds them to the scene it already has.
            probe_entries = [
                add_entry(
                    DIRECTION_PROBE_ID_BASE + index,
                    info,
                    pos=(pos_x, pos_y),
                    names=marker_names(label),
                    map_id=session.map_id,
                    direction=direction,
                )
                for index, (label, pos_x, pos_y, direction) in enumerate(
                    answer.probes
                )
            ]
            print(
                f"[{self.tag}] direction ruler: {len(probe_entries)} stand-ins "
                f"on map {session.map_id} around {session.pos}"
            )
            for batch in range(0, len(probe_entries), ADD_BATCH):
                reply += self._answer(
                    session,
                    sequence,
                    MSG_SV_NOTIFY_CHARACTER_ADD,
                    struct.pack(">H", len(probe_entries[batch : batch + ADD_BATCH]))
                    + b"".join(probe_entries[batch : batch + ADD_BATCH]),
                )
        if answer.npc_clear:
            print(f"[{self.tag}] forgetting {len(session.npc_spawns)} NPC spawns")
            session.npc_spawns.clear()
        for msg_type, msg_params in answer.sends:
            # An NPC is spawned by one push and forgotten by the client the next
            # time it reloads the map — which a conversation now does every time
            # it ends, so talking to somebody used to make them vanish. Keeping
            # the pushes lets the 0x4000 branch put them back.
            if msg_type == chat.MSG_SV_NOTIFY_NPC_CONTROL:
                if msg_params not in session.npc_spawns:
                    session.npc_spawns.append(msg_params)
            # A hand-rung 本鈴 is a real one. Without this the bell goes out and
            # the door it is supposed to open never opens, because admit() has
            # no record of anyone having been invited — which is exactly what
            # refused the first attempt from inside the right classroom.
            if msg_type in (lesson.MSG_SV_NOTIFY_LESSON_READY,
                            exam.MSG_SV_NOTIFY_EXAM_READY):
                session.bell.rang(curriculum.current_subject())
            reply += self._answer(session, sequence, msg_type, msg_params)
        if answer.script is not None:
            reply += self._script_command(session, sequence, answer.script)
        if answer.warp is not None:
            # The same push the coordinate sweep used to ride on: the
            # client tears the scene down and runs the whole lobby load
            # again, so session state has to be right *before* it goes
            # out — the 0x4000 branch will re-add the character wherever
            # session says it is.
            map_id, pos_x, pos_y, direction = answer.warp
            session.map_id, session.pos = map_id, (pos_x, pos_y)
            session.direction = direction
            # The scene is torn down and rebuilt, and the character comes back
            # standing. Same reason as the move cast; see the pose branch there.
            session.pose = stress.POSE_STANDING
            session.sat_at = 0.0
            self._chars(session).set_position(session.chara_id, session.pos, map_id)
            print(
                f"[{self.tag}] chat warp charaId={session.chara_id} -> map "
                f"{map_id} ({MAP_NAMES.get(map_id, '?')}) at {session.pos} "
                f"dir={direction}"
            )
            reply += self._answer(
                session,
                sequence,
                MSG_SV_NOTIFY_GM_WARP,
                struct.pack(">HHHB", map_id, pos_x, pos_y, direction),
            )
        return reply

    # ------------------------------------------------------------------
    # 予鈴と本鈴
    # ------------------------------------------------------------------

    def _lesson_start(self, session: "_Session", seen: int, subject: int) -> bytes:
        """MsgSvNotifyLessonStart with one seat in it: the player's own.


        One seat, and that is not a compromise: the list is who to draw around
        the player, not who is enrolled, and a lesson with a single student is a
        lesson the original would have run too — nothing in the manual or in
        error_message.bin sets a minimum. The original would have had classmates
        to put in the other eight slots and this world has nobody else in it, so
        the other eight stay empty rather than being filled with invented
        students, which would be furniture rather than reconstruction.

        ⚠️ First contact for 0x6100. The layout is read out of the deserializer
        at 0x008E34F0 field by field and the counts are inside the client's own
        buffers, but nothing here has been drawn on a screen yet.
        """
        info = self._chars(session).find(session.chara_id)
        if info is None:
            print(f"[{self.tag}] lesson start: no charaId={session.chara_id}")
            return self._answer(
                session,
                seen,
                lesson.MSG_SV_NOTIFY_LESSON_START_IMPOSSIBLE,
                lesson.ng_params(lesson.REASON_NOT_IN_CLASSROOM),
            )
        fields = parse_create_info(info)
        card = self._chars(session).scorecard(session.chara_id)
        probe_id = lesson.PROBE["charaid"]
        seat = lesson.seat_params(
            seat_id=0,
            chara_id=session.chara_id if probe_id < 0 else probe_id,
            family_name=fields["familyName"],
            first_name=fields["firstName"],
            sex=fields["sex"],
            # ⭐ Zero-based on the wire. Measured: a seat sent with testLv 1 drew
            # 「試験レベル ２」 on the panel over the desk. Same convention as
            # MsgSvResultScoreCard's testLv, which the 通知表 settled the same way
            # a round earlier — and forgetting it here is the second time.
            test_lv=(
                lesson.PROBE["testlv"]
                if lesson.PROBE["testlv"] >= 0
                else (card.test_level() - 1 if card is not None else 0)
            ),
            stress=0,
            # 通算, not this period's — `p06_02` is explicit, and this is where
            # the 「正解率」 on the panel over the desk comes from. Zero until a
            # lesson has actually been sat; it used to be hardcoded zero because
            # there was nothing to count.
            question_count=card.asked[subject] if card is not None else 0,
            correct_count=card.right[subject] if card is not None else 0,
            looks=[fields[key] for key in LOOKS],
            accessory=[fields[key] for key in ACCESSORY],
        )
        # The teacher's opening line runs for a while and the client is told when
        # it ends, in its own clock. See lesson.start_params for why that is the
        # frame and why it may be the wrong reading.
        speech_end = session.client_now() + lesson.PROBE["speech_ms"]
        seats = [seat] * max(0, int(lesson.PROBE["seats"]))
        start_words = lesson.PROBE["words"]
        params = lesson.start_params(
            subject,
            seats,
            speech_end,
            start_words=None if start_words < 0 else start_words,
            lunch_count=max(0, int(lesson.PROBE["lunch"])),
        )
        print(
            f"[{self.tag}] lesson start: {curriculum.SUBJECTS[subject]}, "
            f"先生 {curriculum.SUBJECT_TEACHER[subject]}, "
            f"背景 {lesson.LESSON_BACKGROUND[subject]}, "
            f"startWordsId={struct.unpack_from('>H', params, 0)[0]}, "
            f"speechEndTime={speech_end}, {len(seats)} seat(s)"
        )
        # Ten questions start once the teacher has finished the 開始台詞. The
        # period drives itself from here on a deadline of its own; see
        # _drain_lesson. Without a question bank there is nothing to ask, so the
        # room is drawn and nothing follows — better than asking a quizId the
        # client cannot look up, and it says so in the log.
        if quiz.loaded():
            session.lesson = lesson.Lesson(subject, session.chara_id)
            # 授業中 goes up now, for the people still standing on the map.
            self._presence_refresh_onlookers(session)
        else:
            print(f"[{self.tag}] lesson start: no question bank, no questions")
        return self._answer(session, seen, lesson.MSG_SV_NOTIFY_LESSON_START, params)

    def _drains(self, session: "_Session") -> bytes:
        """Everything the server owes that nobody asked for, in order.

        Called from two places and it matters that they run the same list: after
        every arriving packet — any packet is a chance to flush, including the
        timesync that keeps coming while a script has the client's input locked —
        and when a deadline fires with the socket quiet, which is how a question
        gets its 正解発表 on time.
        """
        out = self._drain_console(session)
        out += self._drain_bells(session)
        out += self._drain_lesson(session)
        out += self._drain_exam(session)
        out += self._drain_battle(session)
        out += self._drain_vitals(session)
        out += self._drain_pending_say(session)
        return out

    def _drain_battle(self, session: "_Session") -> bytes:
        """Close a クラブ対戦 turn whose 制限時間 has run out.

        ⭐ RESTORED semantics, from the only place they are written down
        (p07_03): 「０になる前に入力を完了できなかった場合、キャラクターは行動
        しません。3）全員のコマンド入力終了後、全員の行動が実行されます」. A
        timeout does not end anything and does not refuse anything — it costs
        one participant their move and the round runs.

        ⚠️⚠️ Without this the fight hangs, and it hangs silently: the client
        takes its own command window away at zero and then waits for a server
        that is waiting for a command that can no longer be sent. Round 87 lost
        a whole battle to exactly that and blamed TURN_TIMEOUT_MS, which was
        never the thing at fault.

        ⚠️ The turn is resolved by whichever fighter's session wakes first;
        Battle.resolved is what stops the second one from playing it again.
        """
        if not session.battle_due or time.monotonic() < session.battle_due:
            return b""
        session.battle_due = 0.0
        battle = self.battles.battle_of(session.chara_id)
        if battle is None or battle.resolved:
            return b""
        missing = [f for f in battle.fighters if f.command is None]
        print(f"[{self.tag}] battle turn {battle.turn} timed out with "
              f"{len(missing)} of {len(battle.fighters)} still choosing: "
              + ", ".join(f"0x{f.chara_id:08x}" for f in missing))
        # ⭐⭐ Tell them so, and this is the one thing reason 2 can mean:
        # 「コマンド選択がゲームサーバ側の制限時間内に間に合いませんでした」
        # names the SERVER's time limit, so it is a sentence the server says on
        # its own initiative — nothing the client sends could prompt it.
        #
        # ⚠️⚠️ It is also what a client that ran out of time appears to be
        # waiting for. Round 88 sent the action stream to a client whose own
        # countdown had expired and watched it sit still: the actions were on
        # the wire, no 0x5C16 came back, and the opponent's 「decided」 marker
        # stayed up. The client had closed its command window at zero and had
        # not been told what became of the choice it never made.
        everyone = [f.chara_id for f in battle.fighters]
        out = b""
        for fighter in missing:
            out += self._tr_cast(
                session,
                0,
                clubbattle.MSG_SV_NOTIFY_BATTLE_COMMAND,
                clubbattle.command_params(
                    fighter.chara_id, clubbattle.COMMAND_TOO_LATE
                ),
                everyone,
            )
        return out + self._battle_resolve(session, battle)

    def _drain_vitals(self, session: "_Session") -> bytes:
        """Let a sitting player recover, and tell the client what changed.

        Rides on arriving packets like the bells do, so the resolution is one
        timesync — but unlike a bell this is a rate rather than an event, so
        being late costs nothing: the elapsed seconds are what is metered, and
        whatever they were worth is credited whenever the drain next runs.

        seen=0: neither notify answers a message of the client's.
        """
        if session.chara_id == 0:
            return b""
        sheet = self._chars(session).ability(session.chara_id)
        if sheet is None:
            return b""
        if session.pose == stress.POSE_SITTING and session.sat_at:
            now = time.monotonic()
            removed = stress.recover(sheet, now - session.sat_at, session.map_id)
            if removed:
                # Consume rather than reset, so the seconds that were not worth
                # a whole point stay owed instead of being dropped every drain.
                session.sat_at += removed * (
                    stress.HEALING_SECONDS_PER_POINT
                    if stress.healing(session.map_id)
                    else stress.SIT_SECONDS_PER_POINT
                )
                self._chars(session).set_ability(session.chara_id, sheet)
                print(
                    f"[{self.tag}] 休憩: ストレス -{removed} -> {sheet.stress} "
                    f"({stress.screen(sheet.stress)}/100), 体調 "
                    f"{stress.name(sheet.condition)}"
                )
        return self._push_vitals(session, sheet)

    def _neurotic(self, session: "_Session") -> bool:
        """Is this player currently barred from 学業?

        ドクターストップ is 「ノイローゼと怪我が重なった状態」, so it bars 学業
        as well; 怪我 alone bars クラブ活動 -- see _injured.
        """
        sheet = self._chars(session).ability(session.chara_id)
        return sheet is not None and sheet.condition in (
            stress.NEUROSIS, stress.DOCTOR_STOP
        )

    def _attends(self, session: "_Session", *, sitting: bool) -> bool:
        """Has this character opted in to 授業 (or, in 試験期間, to 試験)?

        オプション's first two rows, 授業の有無 and 試験の有無, are ON/OFF pairs
        the manual glosses as 出席する / 出席しない (`p05_02`). They reach this
        server as the first two bytes of 0x0703 and live on the character record
        — see options.py.

        ⚠️⚠️ ``sitting`` picks which of the two, and it has to: 試験期間 does not
        replace the timetable, it changes which pair of messages the same bells
        are (see _drain_bells). A character who sits exams but skips lessons is
        a setting the option screen offers, so the two are read separately even
        though everything downstream of them is shared.

        ⚠️⚠️ The two rows are also enforced by different ends of the wire — 授業
        here, 試験 by the client itself. _drain_bells has the measurement and
        what follows from it; the short version is that ``sitting=True`` reaches
        only a backstop, never a live decision.

        A character with nothing saved gets options.DEFAULTS, which is ON for
        both — so this cannot quietly stop anybody attending anything.
        """
        opts = self._chars(session).options(session.chara_id)
        if opts is None:
            return True
        return bool(opts["test" if sitting else "lesson"])

    def _injured(self, session: "_Session") -> bool:
        """Is this player currently barred from クラブ活動?

        ⚠️⚠️ The comment that used to stand above _neurotic said 怪我 bars
        「クラブ活動, which this server does not have」. That was true when it was
        written and had stopped being true by round 87 -- 自主トレ, the fight
        behind it and 部活デッキ are all here -- and nothing re-read it, so two
        of the four 体調 stayed unreachable for sixty rounds. Round 149 found it
        by reading the manual instead of the message table.
        ⭐ The general form (an earlier lesson): a rule's stated reason
        does not re-evaluate itself when the premise underneath it expires.
        """
        sheet = self._chars(session).ability(session.chara_id)
        return sheet is not None and stress.barred_from_club(sheet.condition)

    def _groups(self, session: "_Session", seen: int,
                msg_type: int, params: bytes) -> bytes:
        """仲良しグループ. See server/groups.py.

        ⭐ The toolbar's seventh icon opens a three-row menu -- グループ情報 /
        グループ解散 / グループ引継 -- and only the first of those is answered
        here. What made the menu appear at all is not a message: it is
        friendGroupId in the character's own 0x6501 record. Measured in round
        142, one field at a time: leaderQualificationFlag alone left the icon
        just as dead, and the id alone opened it.

        ⭐⭐ Round 143 added the 勧誘 handshake behind 「グループ登録申込み」. The
        icon needs the *inviter's* leaderAuthorityFlag set and the *target's*
        friendGroupId equal to -1; nothing else about either side is consulted,
        and in particular the client never checks the roster size, so 15 is
        enforced here (groups.MAX_MEMBERS) and nowhere else.

        ⭐⭐ Round 144 answered the two buttons inside the 仲良しグループ情報
        window itself -- ［更 新］ (0x620A) and ［除 名］ (0x6226) -- which until
        then hung the client on 「通信中」 when pressed.

        ⭐⭐⭐ Round 146 answered the menu itself: 解散 (0x6203), 引継
        (0x620D..0x6217) and 脱退 (0x6223). ⚠️ The third of those was not on
        anybody's list -- the menu was written down as three rows because that
        is what a *leader's* client draws, and 脱退 is the row a member gets
        where the leader has 解散 and 引継. Counting the unanswered client
        messages in the family rather than the rows on one screen is what found
        it, which is the cheap check: every MsgCl in a family either has a
        handler or has a reason written down for not having one.
        """
        book = self.accounts.groups
        me = session.chara_id
        if msg_type == groups.MSG_CL_REQUEST_CHARA_GROUP_UPDATE:
            return self._group_update(session, seen, params)
        if msg_type == groups.MSG_CL_REQUEST_CHARA_GROUP_KICK:
            return self._group_kick(session, seen, params)
        if msg_type == groups.MSG_CL_REQUEST_CHARA_GROUP_DESTROY:
            return self._group_destroy(session, seen, params)
        if msg_type == groups.MSG_CL_REQUEST_CHARA_GROUP_PART:
            return self._group_part(session, seen)
        if msg_type in groups.TRANSFER:
            return self._group_transfer(session, seen, msg_type, params)
        if msg_type != groups.MSG_CL_QUERY_CHARA_GROUP_INFO:
            return self._group_invite(session, seen, msg_type, params)
        group = book.of(me)
        if group is None:
            # The client should not be able to ask -- it only draws the menu for
            # somebody whose record carries an id -- but a record and a store
            # that disagree is exactly the case worth answering rather than
            # hanging, which is what an unanswered query does (see the 通信中 box).
            print(f"[{self.tag}] group info: charaId={me} is in no group, answering Error")
            return self._answer(
                session, seen, groups.MSG_SV_ERROR_CHARA_GROUP_INFO,
                struct.pack(">B", groups.REASON),
            )
        roster = []
        for member in group.members:
            info = self._peer_chara(member)
            if info is None:
                print(f"[{self.tag}] group info: no record for charaId={member}, "
                      f"skipping the row")
                continue
            fields = parse_create_info(info)
            roster.append((
                member,
                fields["familyName"],
                fields["firstName"],
                fields["sex"],
                1 if self._session_of(member) is not None else 0,
            ))
        print(f"[{self.tag}] group info for charaId={me}: {group.label()}, "
              f"{len(roster)} member row(s)")
        return self._answer(
            session, seen, groups.MSG_SV_RESULT_CHARA_GROUP_INFO,
            groups.result_params(group, roster),
        )

    def _group_update(self, session: "_Session", seen: int, params: bytes) -> bytes:
        """［更 新］ inside the 仲良しグループ情報 window: 0x620A → 0x620B/0x620C.

        ``publicFlag u8`` then the キャッチコピー as a counted string -- the same
        u16-length-then-bytes convention 0x6208 sends it back with, and *not*
        the 21-byte fixed field the character record spends on its own catchCopy
        (2.93). Both halves of the window's top block travel in this one
        message; nothing else in the family carries either of them.

        ⚠️ Leader only. The window opens for every member, and this end is the
        only place that can say no -- the button is not greyed on a member's
        screen, which is itself worth knowing: the client trusts the server for
        this one where it gates 「グループ登録申込み」 itself.

        ⭐ There is no notify in this family, so the other members do not learn
        about a new キャッチコピー until they reopen the window (0x6207 asks
        every time it opens, measured in round 142).
        """
        book = self.accounts.groups
        me = session.chara_id
        group = book.of(me)
        public = params[0] if params else 0
        catchcopy = groups.read_counted(params, 1)
        why = None
        if group is None:
            why = "in no group"
        elif group.leader != me:
            why = "not the leader"
        if why is not None:
            print(f"[{self.tag}] group update from charaId={me} refused: {why}")
            return self._answer(
                session, seen, groups.MSG_SV_NG_CHARA_GROUP_UPDATE,
                struct.pack(">B", groups.REASON),
            )
        assert group is not None
        # ⭐ The length is logged raw because it is the cheapest reading of the
        # client's own edit-box limit: type as much as the box takes, press the
        # button, and the number is here. Nothing else measures it -- the wire
        # field is counted, so the protocol does not state a maximum.
        shown = catchcopy.split(b"\x00")[0].decode("cp932", "replace")
        print(f"[{self.tag}] group update by charaId={me} on {group.label()}: "
              f"public={public} catchcopy[{len(catchcopy)}]={shown!r}")
        if len(catchcopy) > groups.MAX_CATCHCOPY:
            print(f"[{self.tag}]   ⚠️ keeping only the first "
                  f"{groups.MAX_CATCHCOPY} bytes of it")
        book.update(group.id, public, catchcopy)
        return self._answer(
            session, seen, groups.MSG_SV_OK_CHARA_GROUP_UPDATE, b"",
        )

    def _group_kick(self, session: "_Session", seen: int, params: bytes) -> bytes:
        """［除 名］ at the bottom of the same window: 0x6226 → 0x6227/0x6228.

        ``targetCharaId u32``, the row that was selected. 0x6229 goes to the
        character who was removed.

        ⚠️ 0x6229 carries no body, so it cannot say who it is about, and that
        decides who may receive it: pushing 「somebody was removed」 to the rest
        of the roster would arrive on their screens as 「you were removed」.
        Only the target gets one. ⭐ The join bell (0x621E) is empty for the same
        reason and goes the other way -- to everyone -- because there the
        sentence that fits every recipient is the general one.

        ⭐⭐ Measured in round 144 with a real client on each end: nothing at all
        happens on the removed player's screen when 0x6229 arrives, but the
        toolbar's seventh icon is 未所属 from that moment on -- one greyed row,
        zero bytes out. The client applies it to its own copy of the record and
        does not ask. ⚠️ That is not a contradiction of 「the four group fields
        are asked once, at 登校」 (round 142): that sentence is about what this
        end sends, not about what the client does to what it already holds.
        """
        book = self.accounts.groups
        me = session.chara_id
        target = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
        group = book.of(me)
        why = None
        if group is None or group.leader != me:
            why = "not the leader"
        elif target == me:
            why = "a leader leaves through 解散 or 引継, not 除名"
        elif target not in group.members:
            why = f"charaId={target} is not in this group"
        if why is not None:
            print(f"[{self.tag}] 除名 of {target} by charaId={me} refused: {why}")
            return self._answer(
                session, seen, groups.MSG_SV_NG_CHARA_GROUP_KICK,
                struct.pack(">B", groups.REASON),
            )
        assert group is not None
        book.kick(group.id, target)
        print(f"[{self.tag}] 除名: charaId={me} removed {target} "
              f"from {group.label()}")
        removed = self._session_of(target)
        if removed is not None:
            self._push(removed, self._answer(
                removed, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_KICK, b"",
            ))
            # ⚠️ 0x6229 fixes the removed player's *own* copy of the record;
            # everybody looking at them still holds the 0x480F entry that says
            # they are in this group, and that entry is what the PC menu reads.
            self._presence_refresh_onlookers(removed)
        # ⚠️⚠️ The Ok is built *after* that redraw, not before. Sequence numbers
        # are handed out by _answer at the moment it is called, and the redraw
        # goes out to the onlookers — this leader among them — the moment it is
        # asked for, while this reply waits to be returned. Building it first
        # put a lower number behind a higher one on the leader's own connection,
        # which is the one thing 0xA4C4D0 hangs up over (round 105, 2.60).
        return self._answer(
            session, seen, groups.MSG_SV_OK_CHARA_GROUP_KICK, b"",
        )

    def _group_destroy(self, session: "_Session", seen: int, params: bytes) -> bytes:
        """［グループ解散］, the icon menu's second row: 0x6203 -> 0x6204/0x6205.

        A counted comment and nothing else, and 0x6206 hands the same bytes on
        to everybody who was still in the group.

        ⭐ That body is what settles who gets the notify. 0x6229 could not say
        who it was about because it is empty; this one is not empty, but what it
        carries is the leader's farewell rather than an id, so the sentence is
        still 「the group you are in is gone」 -- true for every member except
        the one who typed it, and they have the Ok instead.

        ⚠️ Leader only. A member's client should be drawing 脱退 in this row
        rather than 解散, so a 0x6203 from one is a disagreement between the two
        ends and gets 0x6205 -- the same call _group_update and _group_kick
        make, for the same reason: refusing is the only way this end can say
        「that is not your row」 at all.
        """
        book = self.accounts.groups
        me = session.chara_id
        group = book.of(me)
        comment = groups.read_counted(params)
        why = None
        if group is None:
            why = "in no group"
        elif group.leader != me:
            why = "not the leader"
        if why is not None:
            print(f"[{self.tag}] 解散 by charaId={me} refused: {why}")
            return self._answer(
                session, seen, groups.MSG_SV_NG_CHARA_GROUP_DESTROY,
                struct.pack(">B", groups.REASON),
            )
        assert group is not None
        # ⭐ Logged raw for the reason _group_update logs its catchcopy length:
        # the wire field is counted, so nothing in the protocol states what the
        # client's own edit box takes -- the first real 解散 says it here.
        shown = comment.split(b"\x00")[0].decode("cp932", "replace")
        print(f"[{self.tag}] 解散: charaId={me} is dissolving {group.label()}: "
              f"comment[{len(comment)}]={shown!r}")
        told = [member for member in group.members if member != me]
        book.disband(group.id)
        self._forget_group_handshakes(session)
        body = groups.counted(comment[:groups.MAX_COMMENT])
        # Everybody who was in it is now 未所属, so every one of their 0x480F
        # entries is stale on every screen -- the leader's included.
        self._presence_refresh_onlookers(session)
        for member in told:
            peer = self._session_of(member)
            if peer is None:
                continue
            self._forget_group_handshakes(peer)
            self._push(peer, self._answer(
                peer, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_DESTROY, body,
            ))
            # ⚠️ This redraws a member for *their* onlookers, and the leader
            # standing beside them is one, so it reaches this connection too.
            self._presence_refresh_onlookers(peer)
        # ⚠️⚠️ Built last, for the reason spelled out in _group_kick: _answer
        # takes a sequence number when it is called, and everything above has
        # already gone out on this same socket.
        return self._answer(
            session, seen, groups.MSG_SV_OK_CHARA_GROUP_DESTROY, b"",
        )

    def _group_part(self, session: "_Session", seen: int) -> bytes:
        """［グループ脱退］: 0x6223 -> 0x6224/0x6225. Empty in both directions.

        ⚠️⚠️ The row a *member* is given where a leader has 解散 and 引継, and
        the only one of the three with no notify at all: nobody is told when
        somebody walks out. The roster catches up when the window is next
        opened, which asks 0x6207 every time (round 142). ⭐ That is ［更 新］'s
        shape and the opposite of 除名's 0x6229 -- what a message does about
        telling the others is decided one message at a time, not per family.

        ⚠️ A leader is refused. The manual gives them two doors of their own and
        a group whose leader had walked out would have nobody left who can kick,
        update or disband it. GroupBook.leave still folds the two together, but
        that is the console's shortcut and its docstring says so.
        """
        book = self.accounts.groups
        me = session.chara_id
        group = book.of(me)
        why = None
        if group is None:
            why = "in no group"
        elif group.leader == me:
            why = "a leader leaves through 解散 or 引継, not 脱退"
        if why is not None:
            print(f"[{self.tag}] 脱退 by charaId={me} refused: {why}")
            return self._answer(
                session, seen, groups.MSG_SV_NG_CHARA_GROUP_PART,
                struct.pack(">B", groups.REASON),
            )
        assert group is not None
        was = group.label()
        book.leave(me)
        self._forget_group_handshakes(session)
        print(f"[{self.tag}] 脱退: charaId={me} left {was}")
        # ⚠️ Nobody is told 「they walked out」 -- but the walker's own 0x480F
        # entry now says the wrong group on every screen it is drawn on, and
        # that is a redraw rather than a notify.
        self._presence_refresh_onlookers(session)
        return self._answer(
            session, seen, groups.MSG_SV_OK_CHARA_GROUP_PART, b"",
        )

    def _group_transfer(self, session: "_Session", seen: int,
                        msg_type: int, params: bytes) -> bytes:
        """［グループ引継］: 0x620D -> 0x6210 -> 0x6211/0x6212 -> 0x6213.

        The 勧誘 handshake with one field more on each half -- a counted comment
        rides with the offer and is handed on -- and held in the session for the
        same reason: the three answering messages carry no charaId, so each end
        can be in at most one handover at a time.

        ⚠️ The target has to be in the group already (GroupBook.hand_over says
        why), and this end does *not* require リーダー資格 of them: that is the
        exam that lets somebody create a group, and refusing here on a rule the
        real server may not have would be indistinguishable from a handshake
        that does not work.

        ⚠️⚠️ ［断 る］ sends 0x6211 too. See the branch below: the Ok/Ng pair in
        this family is not accept/decline, the answer byte is.

        ⭐⭐⭐ Both ends get the empty 0x6213, and round 146 measured why that is
        right rather than assuming it. The two screens show the same sentence --
        「仲良しグループリーダーの引継ぎが行われました」 -- and then each client
        flips its *own* leader flag in its own direction, with zero bytes going
        back up: the ex-leader's icon menu drops to 情報/脱退 and the new
        leader's grows to 情報/解散/引継. A bodyless notify can mean opposite
        things at its two ends when both of them were parties to the handshake,
        because each already knows which side it was on.

        ⚠️ Which is also why it must not go to the rest of the roster: a third
        member was not part of the handshake and has no side to flip. What they
        see is a new leaderId the next time they open the window.
        """
        book = self.accounts.groups
        me = session.chara_id
        first = params[0] if params else 0

        if msg_type == groups.MSG_CL_REQUEST_CHARA_GROUP_TRANSFER_REQUEST:
            target = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
            comment = groups.read_counted(params, 4)
            group = book.of(me)
            other = self._session_of(target) if target else None
            self._forget_stale_group(session)
            if other is not None:
                self._forget_stale_group(other)
            why = None
            if target in (0, me) or other is None:
                why = "no target" if target in (0, me) else "not online"
            elif group is None or group.leader != me:
                why = "not the leader"
            elif target not in group.members:
                why = f"charaId={target} is not in this group"
            elif (session.group_handover_to is not None
                  or other.group_handover_from is not None):
                why = "a handover is already open"
            if why is not None:
                print(f"[{self.tag}] 引継 from charaId={me} to {target} refused: {why}")
                return self._answer(
                    session, seen, groups.MSG_SV_NG_CHARA_GROUP_TRANSFER_REQUEST,
                    struct.pack(">B", groups.REASON),
                )
            assert other is not None and group is not None
            session.group_handover_to = target
            other.group_handover_from = me
            shown = comment.split(b"\x00")[0].decode("cp932", "replace")
            print(f"[{self.tag}] 引継: charaId={me} is offering {group.label()} "
                  f"to {target}: comment[{len(comment)}]={shown!r}")
            reply = self._answer(
                session, seen, groups.MSG_SV_OK_CHARA_GROUP_TRANSFER_REQUEST, b"",
            )
            self._push(other, self._answer(
                other, 0, groups.MSG_SV_REQUEST_CHARA_GROUP_TRANSFER_RESPONSE,
                struct.pack(">I", me) + groups.counted(comment[:groups.MAX_COMMENT]),
            ))
            return reply

        if (msg_type == groups.MSG_CL_OK_CHARA_GROUP_TRANSFER_RESPONSE
                and first != groups.ANSWER_YES):
            # ⚠️⚠️ ［断 る］ does NOT send the Ng message. Both buttons in the
            # 「引継ぎ依頼」 box send 0x6211 and the answer byte is the answer:
            # 1 from ［引き継ぐ］, 0 from ［断 る］ (round 146, one client on each
            # end, cursor screenshotted on the button before each click). The
            # names in the client's own dump say Ok/Ng, and reading the split
            # off those names is what put a handover through on a refusal here
            # twice before the byte was looked at. 0x6212 has never been seen.
            msg_type = groups.MSG_CL_NG_CHARA_GROUP_TRANSFER_RESPONSE

        if msg_type == groups.MSG_CL_OK_CHARA_GROUP_TRANSFER_RESPONSE:
            asker = session.group_handover_from
            leader = self._session_of(asker) if asker is not None else None
            group = book.of(asker) if asker is not None else None
            if asker is None or leader is None or group is None or group.leader != asker:
                print(f"[{self.tag}] 引継 accept from charaId={me}: "
                      f"nobody is handing anything over, ignoring")
                session.group_handover_from = None
                return b""
            session.group_handover_from = None
            leader.group_handover_to = None
            book.hand_over(group.id, me)
            print(f"[{self.tag}] 引継: charaId={me} accepted {asker} "
                  f"(answer={first}); {group.label()} is now led by {me}")
            self._push(leader, self._answer(
                leader, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_TRANSFER, b"",
            ))
            return self._answer(
                session, seen, groups.MSG_SV_NOTIFY_CHARA_GROUP_TRANSFER, b"",
            )

        if msg_type == groups.MSG_CL_NG_CHARA_GROUP_TRANSFER_RESPONSE:
            asker = session.group_handover_from
            session.group_handover_from = None
            leader = self._session_of(asker) if asker is not None else None
            if leader is not None:
                leader.group_handover_to = None
                # 0x6217 is the only message that tells the other end an offer
                # has ended, exactly as 0x6222 is for 勧誘 -- the family has no
                # 「they said no」 of its own.
                self._push(leader, self._answer(
                    leader, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_TRANSFER_CANCEL,
                    struct.pack(">B", first),
                ))
            print(f"[{self.tag}] 引継: charaId={me} declined {asker} "
                  f"(reason={first})")
            return b""

        # 0x6214, the leader withdrawing the offer. Empty request, empty Ok.
        target = session.group_handover_to
        if target is None:
            return self._answer(
                session, seen, groups.MSG_SV_NG_CHARA_GROUP_TRANSFER_CANCEL,
                struct.pack(">B", groups.REASON),
            )
        session.group_handover_to = None
        asked = self._session_of(target)
        if asked is not None:
            asked.group_handover_from = None
            self._push(asked, self._answer(
                asked, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_TRANSFER_CANCEL,
                struct.pack(">B", groups.REASON),
            ))
        print(f"[{self.tag}] 引継: charaId={me} withdrew the offer to {target}")
        return self._answer(
            session, seen, groups.MSG_SV_OK_CHARA_GROUP_TRANSFER_CANCEL, b"",
        )

    def _forget_stale_group(self, session: "_Session") -> None:
        """Drop either end of a 勧誘 or a 引継 whose other side has logged out.

        Both kinds in one place because they have one rule: an application is
        open exactly while both ends are connected. Nothing in either family can
        carry a question across a logout, so a stale id in a session is the only
        trace one leaves.
        """
        if (session.group_invited is not None
                and self._session_of(session.group_invited) is None):
            session.group_invited = None
        if (session.group_inviter is not None
                and self._session_of(session.group_inviter) is None):
            session.group_inviter = None
        if (session.group_handover_to is not None
                and self._session_of(session.group_handover_to) is None):
            session.group_handover_to = None
        if (session.group_handover_from is not None
                and self._session_of(session.group_handover_from) is None):
            session.group_handover_from = None

    def _forget_group_handshakes(self, session: "_Session") -> None:
        """Drop every application this session is an end of, both directions.

        ⚠️ Called when the group under it stops existing (解散) or it walks out
        of one (脱退). An application whose group is gone can still be answered
        by the other end, and that answer would be applied to whatever group the
        sender is in by then -- which is how a withdrawn invite turns into a
        join nobody asked for. Clearing both ends here is cheaper than
        re-checking the group in four more places.
        """
        me = session.chara_id
        for target in (session.group_invited, session.group_handover_to):
            other = self._session_of(target) if target is not None else None
            if other is None:
                continue
            if other.group_inviter == me:
                other.group_inviter = None
            if other.group_handover_from == me:
                other.group_handover_from = None
        for asker in (session.group_inviter, session.group_handover_from):
            other = self._session_of(asker) if asker is not None else None
            if other is None:
                continue
            if other.group_invited == me:
                other.group_invited = None
            if other.group_handover_to == me:
                other.group_handover_to = None
        session.group_invited = None
        session.group_inviter = None
        session.group_handover_to = None
        session.group_handover_from = None

    def _group_invite(self, session: "_Session", seen: int,
                      msg_type: int, params: bytes) -> bytes:
        """勧誘: 0x6218 → 0x621B → 0x621C/0x621D → 0x621E. See server/groups.py.

        Same shape as the 友達登録 handshake in _friends and refused on the same
        ground when the other side is offline: nothing in the family can carry
        an application across a logout, so writing one down would be writing
        down a question nobody can ever be asked.

        ⚠️ The one real difference is that the answering half carries no id, so
        each session holds at most one invite in each direction. A second 0x6218
        from a leader who is already waiting is refused rather than allowed to
        overwrite the first: the client would then have no way to say which one
        its 0x621C meant.

        ⚠️⚠️ Both buttons in the 「仲良し登録確認」 box send 0x621C. The answer
        byte is the answer; the Ok/Ng pair of messages is not. See the branch
        below -- and see groups.ANSWER_YES for how long that went unnoticed.
        """
        book = self.accounts.groups
        me = session.chara_id
        first = params[0] if params else 0

        if msg_type == groups.MSG_CL_REQUEST_CHARA_GROUP_INVITE_REQUEST:
            target = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
            group = book.of(me)
            other = self._session_of(target) if target else None
            # An application whose other end has logged out is over, and the
            # only trace of it is a stale id in a session. Clearing it here
            # rather than at logout keeps the rule in one place: an invite is
            # open exactly while both ends are connected.
            self._forget_stale_group(session)
            if other is not None:
                self._forget_stale_group(other)
            why = None
            if target in (0, me) or other is None:
                why = "no target" if target in (0, me) else "not online"
            elif group is None or group.leader != me:
                why = "not a leader"
            elif book.of(target) is not None:
                why = "already in a group"
            elif len(group.members) >= groups.MAX_MEMBERS:
                why = f"full ({groups.MAX_MEMBERS})"
            elif session.group_invited is not None or other.group_inviter is not None:
                why = "an application is already open"
            if why is not None:
                print(f"[{self.tag}] 勧誘 from charaId={me} to {target} refused: {why}")
                return self._answer(
                    session, seen, groups.MSG_SV_NG_CHARA_GROUP_INVITE_REQUEST,
                    struct.pack(">B", groups.REASON),
                )
            assert other is not None
            session.group_invited = target
            other.group_inviter = me
            print(f"[{self.tag}] 勧誘: charaId={me} is asking {target} "
                  f"into {group.label()}")
            reply = self._answer(
                session, seen, groups.MSG_SV_OK_CHARA_GROUP_INVITE_REQUEST, b"",
            )
            self._push(other, self._answer(
                other, 0, groups.MSG_SV_REQUEST_CHARA_GROUP_INVITE_RESPONSE,
                struct.pack(">I", me),
            ))
            return reply

        if (msg_type == groups.MSG_CL_OK_CHARA_GROUP_INVITE_RESPONSE
                and first != groups.ANSWER_YES):
            # ⚠️⚠️ ［いいえ］ in the 「仲良し登録確認」 box sends 0x621C with
            # answer=0, not 0x621D. Measured in round 146 with a real client on
            # the answering end; round 143 built this handshake against a script
            # that always accepted, and until this line existed a refusal put
            # the refuser into the group. 0x621D has never been seen.
            msg_type = groups.MSG_CL_NG_CHARA_GROUP_INVITE_RESPONSE

        if msg_type == groups.MSG_CL_OK_CHARA_GROUP_INVITE_RESPONSE:
            asker = session.group_inviter
            leader = self._session_of(asker) if asker is not None else None
            group = book.of(asker) if asker is not None else None
            # ⚠️ Leadership is re-checked here and not only when the invite was
            # sent: 引継 can hand the group away while an application is open,
            # and an accept that arrives after that would put somebody into a
            # group on the say-so of a character who no longer runs it.
            if (asker is None or leader is None or group is None
                    or group.leader != asker):
                print(f"[{self.tag}] 勧誘 accept from charaId={me}: "
                      f"nobody is asking, ignoring")
                session.group_inviter = None
                return b""
            session.group_inviter = None
            leader.group_invited = None
            book.join(group.id, me)
            print(f"[{self.tag}] 勧誘: charaId={me} accepted {asker} "
                  f"(answer={first}); {group.label()}")
            # ⭐ The joiner is now in a group, and the copy every onlooker holds
            # of them still says 未所属 -- which is exactly the copy the PC
            # menu's 「グループ登録申込み」 asks, so without this the invite
            # stays on offer to somebody who has just accepted one.
            self._presence_refresh_onlookers(session)
            # ⚠️ A bell with no payload, so it cannot say who joined. Everybody
            # already in the group gets one and re-opens the window to see the
            # row; the joiner needs a 登校 for its own record to change.
            for member in group.members:
                if member == me:
                    continue
                peer = self._session_of(member)
                if peer is not None:
                    self._push(peer, self._answer(
                        peer, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_JOIN, b"",
                    ))
            return self._answer(
                session, seen, groups.MSG_SV_NOTIFY_CHARA_GROUP_JOIN, b"",
            )

        if msg_type == groups.MSG_CL_NG_CHARA_GROUP_INVITE_RESPONSE:
            asker = session.group_inviter
            session.group_inviter = None
            leader = self._session_of(asker) if asker is not None else None
            if leader is not None:
                leader.group_invited = None
                # The same judgement call _friends makes for 0x640D: the family
                # has no 「they said no」 of its own and 0x6222 is the only
                # message that tells somebody an application has ended.
                self._push(leader, self._answer(
                    leader, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_INVITE_CANCEL,
                    struct.pack(">B", first),
                ))
            print(f"[{self.tag}] 勧誘: charaId={me} declined {asker} "
                  f"(reason={first})")
            return b""

        # 0x621F, the inviter withdrawing. Empty request, empty Ok.
        target = session.group_invited
        if target is None:
            return self._answer(
                session, seen, groups.MSG_SV_NG_CHARA_GROUP_INVITE_CANCEL,
                struct.pack(">B", groups.REASON),
            )
        session.group_invited = None
        asked = self._session_of(target)
        if asked is not None:
            asked.group_inviter = None
            self._push(asked, self._answer(
                asked, 0, groups.MSG_SV_NOTIFY_CHARA_GROUP_INVITE_CANCEL,
                struct.pack(">B", groups.REASON),
            ))
        print(f"[{self.tag}] 勧誘: charaId={me} withdrew the application to {target}")
        return self._answer(
            session, seen, groups.MSG_SV_OK_CHARA_GROUP_INVITE_CANCEL, b"",
        )

    def _friends(self, session: "_Session", seen: int,
                 msg_type: int, params: bytes) -> bytes:
        """アドレス帳 and the 友達登録 handshake. See server/friends.py.

        ⚠️ Both halves of an application have to be online at once, and that is
        the protocol's shape rather than a shortcut: 0x6403 is answered by a
        person, through 0x6407/0x6408, and there is no message in the family for
        an application that outlives the session it was sent from. So an offline
        target is refused here instead of being written down somewhere it could
        never be collected from.
        """
        book = self.accounts.friends
        me = session.chara_id
        target = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
        tail = params[4] if len(params) >= 5 else 0

        if msg_type == friends.MSG_CL_QUERY_FRIEND_LIST:
            # ⚠️ The one message that fills the window, sent once at login and
            # never again while the player walks around. Anything this end wants
            # in that list has to be in the store before 登校.
            rows = []
            for other in book.of(me):
                info = self._peer_chara(other)
                if info is None:
                    # The store points at somebody no account claims any more.
                    # Not fatal and not silent: a row cannot be built without a
                    # record, and knowing which id went missing is the whole
                    # value of noticing.
                    print(f"[{self.tag}] address book: no record for "
                          f"charaId={other}, skipping the row")
                    continue
                rows.append(friends.entry(other, info))
            print(f"[{self.tag}] address book for charaId={me}: {len(rows)} row(s)")
            return self._answer(
                session, seen, friends.MSG_SV_RESULT_FRIEND_LIST,
                friends.list_params(rows),
            )

        if msg_type == friends.MSG_CL_REQUEST_FRIEND_ADD_REQUEST:
            other = self._session_of(target) if target else None
            if target in (0, me) or book.linked(me, target) or other is None:
                why = (
                    "no target" if target in (0, me)
                    else "already friends" if book.linked(me, target)
                    else "not online"
                )
                print(f"[{self.tag}] 友達登録 from charaId={me} to {target} "
                      f"refused: {why}")
                return self._answer(
                    session, seen, friends.MSG_SV_NG_FRIEND_ADD_REQUEST,
                    struct.pack(">IB", target, friends.REASON),
                )
            session.friends_asked.add(target)
            other.friends_asking.add(me)
            print(f"[{self.tag}] 友達登録: charaId={me} is asking {target}")
            reply = self._answer(
                session, seen, friends.MSG_SV_OK_FRIEND_ADD_REQUEST,
                struct.pack(">I", target),
            )
            self._push(other, self._answer(
                other, 0, friends.MSG_SV_REQUEST_FRIEND_ADD_RESPONSE,
                struct.pack(">I", me),
            ))
            return reply

        if (msg_type == friends.MSG_CL_OK_FRIEND_RESPONSE
                and tail != friends.ANSWER_YES):
            # ⚠️⚠️ Round 146 caught the two 仲良しグループ handshakes doing exactly
            # what the comment that used to stand here assumed they could not:
            # both buttons of the confirmation box send the *Ok* message and put
            # the decision in its answer byte. This family has the same shape and
            # the same box, and its yes has been seen: a client that already had
            # the asker in its address book answered 0x6407 with answer=1 on its
            # own. So 0 is not this family's yes, whatever else it is.
            #
            # ⚠️ What has *not* been seen is a real client pressing ［いいえ］
            # here -- the right-click menu would not open on the third try and
            # the reading was dropped rather than guessed. Treating a non-yes as
            # a refusal is the safe half of that uncertainty: if ［いいえ］ turns
            # out to send 0x6408 after all, this branch is simply never taken.
            msg_type = friends.MSG_CL_NG_FRIEND_RESPONSE

        if msg_type == friends.MSG_CL_OK_FRIEND_RESPONSE:
            asker = self._session_of(target)
            if target not in session.friends_asking or asker is None:
                print(f"[{self.tag}] 友達登録 accept from charaId={me} for "
                      f"{target}: nothing was asked, ignoring")
                return b""
            session.friends_asking.discard(target)
            asker.friends_asked.discard(me)
            book.link(me, target)
            print(f"[{self.tag}] 友達登録: charaId={me} accepted {target} "
                  f"(answer={tail}); {book.summary()}")
            # Both sides are told, each about the other. The message carries one
            # id and no name, so this is only a bell -- the row itself comes out
            # of the store the next time the window is filled.
            self._push(asker, self._answer(
                asker, 0, friends.MSG_SV_NOTIFY_FRIEND_ADD, struct.pack(">I", me),
            ))
            return self._answer(
                session, seen, friends.MSG_SV_NOTIFY_FRIEND_ADD,
                struct.pack(">I", target),
            )

        if msg_type == friends.MSG_CL_NG_FRIEND_RESPONSE:
            asker = self._session_of(target)
            session.friends_asking.discard(target)
            if asker is not None:
                asker.friends_asked.discard(me)
                # ⚠️ A judgement call, not a reading. The family has no
                # "they said no" message of its own, and 0x640D is the only one
                # that tells somebody an application they were part of has
                # ended. A capture showing the original answering the asker some
                # other way is the thing that would replace this line.
                self._push(asker, self._answer(
                    asker, 0, friends.MSG_SV_NOTIFY_FRIEND_ADD_CANCEL,
                    struct.pack(">IB", me, tail),
                ))
            print(f"[{self.tag}] 友達登録: charaId={me} declined {target} "
                  f"(reason={tail})")
            return b""

        if msg_type == friends.MSG_CL_REQUEST_FRIEND_ADD_CANCEL:
            if target not in session.friends_asked:
                return self._answer(
                    session, seen, friends.MSG_SV_NG_FRIEND_ADD_CANCEL,
                    struct.pack(">IB", target, friends.REASON),
                )
            session.friends_asked.discard(target)
            asked = self._session_of(target)
            if asked is not None:
                asked.friends_asking.discard(me)
                self._push(asked, self._answer(
                    asked, 0, friends.MSG_SV_NOTIFY_FRIEND_ADD_CANCEL,
                    struct.pack(">IB", me, friends.REASON),
                ))
            print(f"[{self.tag}] 友達登録: charaId={me} withdrew the "
                  f"application to {target}")
            return self._answer(
                session, seen, friends.MSG_SV_OK_FRIEND_ADD_CANCEL,
                struct.pack(">I", target),
            )

        if msg_type == friends.MSG_CL_REQUEST_FRIEND_DEL:
            # The 消去 button under the list. Ok carries nothing (the shape reader:
            # 0x640f empty), Ng carries one reason byte.
            if not book.unlink(me, target):
                print(f"[{self.tag}] 消去: charaId={me} has no {target} to drop")
                return self._answer(
                    session, seen, friends.MSG_SV_NG_FRIEND_DEL,
                    struct.pack(">B", friends.REASON),
                )
            print(f"[{self.tag}] 消去: charaId={me} dropped {target}; "
                  f"{book.summary()}")
            return self._answer(session, seen, friends.MSG_SV_OK_FRIEND_DEL, b"")

        # MsgClQueryFriendState. Nothing has ever sent one here; it is answered
        # ahead of the client because the shape is known and a query left
        # hanging is how a window greys itself out forever.
        state = (
            friends.STATE_ONLINE if self._session_of(target)
            else friends.STATE_OFFLINE
        )
        return self._answer(
            session, seen, friends.MSG_SV_RESULT_FRIEND_STATE,
            struct.pack(">IB", target, state),
        )

    def _lesson_skill(self, session: "_Session", seen: int,
                      msg_type: int, params: bytes) -> bytes:
        """お助けスキル, all eight of them. See server/lesson_skill.py.

        Each one is: check the rules, apply the effect, answer the player, then
        push the Notify the whole classroom is meant to see. In this server the
        classroom is one seat, so the broadcast comes straight back — but it is
        still sent, because it is what carries the ストレス figure the bar under
        the character reads.

        ⚠️ The three targeted skills (カンニング, そっと応援, ティーチング) are
        wired but cannot succeed here: a lesson has one seat, so no `targetId`
        ever resolves and they refuse with the reason `error_message.bin` 540 /
        550 / 560 describes — 「選択されたキャラクターの情報を取得できませんでした」.
        That is the original's own answer to naming a classmate who is not there,
        not a stub.

        ✅ **Decided (2026-08-06): the other eight seats stay empty.** The
        original filled them with other players, so anyone this server seats is
        invented along with how well they answer, and staying identical to the
        original is worth more than making three skills reachable. When the
        server grows real accounts the seats fill themselves.
        """
        period = session.lesson
        sheet = self._chars(session).ability(session.chara_id)
        card = self._chars(session).scorecard(session.chara_id)
        test_level = card.test_level() if card is not None else 1
        question_no, target_id = lesson_skill.parse_request(msg_type, params)
        name = lesson_skill.NAMES.get(msg_type, "?")

        try:
            lesson_skill.check_common(period, msg_type, question_no, test_level)
            answer, notify = self._skill_effect(
                session, period, sheet, msg_type, target_id
            )
        except lesson_skill.Refused as refusal:
            print(f"[{self.tag}] skill {name} refused: {refusal.why} "
                  f"(reason={refusal.reason})")
            return self._answer(
                session, seen, lesson_skill.REFUSAL[msg_type],
                lesson_skill.error_params(refusal.reason),
            )

        out = b""
        if answer is not None:
            out += self._answer(session, seen, answer[0], answer[1])
        if notify is not None:
            out += self._answer(session, 0 if out else seen, notify[0], notify[1])
        if sheet is not None:
            self._chars(session).set_ability(session.chara_id, sheet)
            out += self._push_vitals(session, sheet)
        return out

    def _skill_effect(self, session: "_Session", period, sheet,
                      msg_type: int, target_id: int):
        """What one skill does. Returns (answer, notify), either may be None.

        `sheet` is mutated in place when a skill moves ストレス; the caller saves
        it. Raises lesson_skill.Refused for the per-skill rules — the ones every
        skill shares were already checked.
        """
        chara_id = session.chara_id
        subject = period.subject
        params_row = list(sheet.params) if sheet is not None else []

        def charge(amount: int) -> int:
            """Move ストレス by `amount` and return where it ended up."""
            if sheet is None:
                return 0
            if amount >= 0:
                stress.charge(sheet, amount)
            else:
                sheet.stress = max(0, sheet.stress + amount)
                if sheet.stress == 0:
                    sheet.condition = stress.HEALTHY
            return sheet.stress

        if msg_type == lesson_skill.MSG_CL_CAST_LESSON_HELP:
            # 「周りの生徒に助けを求めます」. Nothing happens to the caller — the
            # Notify carries `userId` and nothing else, so the original had no
            # figure to report either. What it is *for* is the classmates, who
            # may answer with そっと応援 or ティーチング; with one seat, nobody does.
            return None, (lesson_skill.MSG_SV_NOTIFY_LESSON_HELP,
                          lesson_skill.notify_help_params(chara_id))

        if msg_type == lesson_skill.MSG_CL_CAST_LESSON_LUNCH:
            if period.lunch <= 0:
                raise lesson_skill.Refused(msg_type, "お弁当を所持していない")
            if sheet is not None and sheet.stress <= 0:
                raise lesson_skill.Refused(msg_type, "ストレスがたまっていない")
            period.lunch -= 1
            ok = self._rng().random() < lesson_skill.LUNCH_SUCCESS
            level = charge(lesson_skill.STRESS_LUNCH if ok else 0)
            return None, (lesson_skill.MSG_SV_NOTIFY_LESSON_LUNCH,
                          lesson_skill.notify_lunch_params(chara_id, level, ok))

        if msg_type in (lesson_skill.MSG_CL_REQUEST_LESSON_FEELING,
                        lesson_skill.MSG_CL_REQUEST_LESSON_MEIKYOUSHISUI):
            # 直感 and 明鏡止水 are the same skill at two strengths, and the wire
            # says so: same body, same reply, same Notify without a successFlag.
            feeling = msg_type == lesson_skill.MSG_CL_REQUEST_LESSON_FEELING
            if len(lesson_skill.live_choices(period)) <= 1:
                raise lesson_skill.Refused(msg_type, "選択肢が１つしかない")
            band = (lesson_skill.FEELING_ACCURACY if feeling
                    else lesson_skill.MEIKYOU_ACCURACY)
            choice = lesson_skill.pick_answer(
                period, lesson_skill.chance(band, params_row, subject), self._rng()
            )
            level = charge(lesson_skill.STRESS_FEELING if feeling
                           else lesson_skill.STRESS_MEIKYOUSHISUI)
            ok_type = (lesson_skill.MSG_SV_OK_LESSON_FEELING if feeling
                       else lesson_skill.MSG_SV_OK_LESSON_MEIKYOUSHISUI)
            notify_type = (lesson_skill.MSG_SV_NOTIFY_LESSON_FEELING if feeling
                           else lesson_skill.MSG_SV_NOTIFY_LESSON_MEIKYOUSHISUI)
            return ((ok_type, lesson_skill.ok_choice_params(choice)),
                    (notify_type,
                     lesson_skill.notify_stress_params(chara_id, level)))

        if msg_type == lesson_skill.MSG_CL_REQUEST_LESSON_COOL:
            lesson_skill.check_not_narrowed(period, msg_type)
            ok = self._rng().random() < lesson_skill.chance(
                lesson_skill.COOL_SUCCESS, params_row, subject
            )
            if ok:
                period.narrowed = lesson_skill.narrow(period, self._rng())
            level = charge(lesson_skill.STRESS_COOL)
            kept = lesson_skill.live_choices(period)
            return ((lesson_skill.MSG_SV_OK_LESSON_COOL,
                     lesson_skill.ok_choice_list_params(kept)),
                    (lesson_skill.MSG_SV_NOTIFY_LESSON_COOL,
                     lesson_skill.notify_self_params(chara_id, level, ok)))

        # The three that need a classmate. `targetId` cannot resolve in a
        # one-seat lesson, and that is the honest refusal — see _lesson_skill.
        raise lesson_skill.Refused(
            msg_type, "対象が解決できない",
            f"targetId {target_id:#x}、座席は自分だけ",
        )

    @staticmethod
    def _rng():
        import random
        return random

    def _push_vitals(self, session: "_Session", sheet) -> bytes:
        """0x4811 / 0x4812, but only where the value has actually moved.

        Both are pushes with no request behind them, so sending them every drain
        would be thirty bytes a second saying nothing. Sending them on change
        also makes the log a record of what the screen was told, which is what a
        screenshot has to be checked against.
        """
        out = b""
        if sheet.stress != session.sent_stress:
            session.sent_stress = sheet.stress
            out += self._answer(
                session, 0, stress.MSG_SV_NOTIFY_CHARACTER_STRESS,
                stress.stress_params(sheet.stress),
            )
        if sheet.condition != session.sent_condition:
            session.sent_condition = sheet.condition
            out += self._answer(
                session, 0, stress.MSG_SV_NOTIFY_CHARACTER_CONDITION,
                stress.condition_params(sheet.condition),
            )
        return out

    def _drain_lesson(self, session: "_Session") -> bytes:
        """Push whatever the period in progress has become due for.

        seen=0: none of these answer a message of the client's. 0x6105 is the
        only thing it sends all lesson, and its reply is the 0x6106 that goes out
        when the timer ends rather than when the answer arrives.
        """
        period = session.lesson
        if period is None:
            return b""
        out = b""
        for msg_type, params in period.pump(datetime.now(), session.client_now()):
            name = MESSAGE_NAMES.get(msg_type, "?")
            print(f"[{self.tag}] lesson {period.question_no}/"
                  f"{lesson.QUESTIONS_PER_LESSON}: {name} (0x{msg_type:04x}) "
                  f"{params.hex()}")
            out += self._answer(session, 0, msg_type, params)
        if period.finished():
            out += self._lesson_end(session, period)
            session.lesson = None
            # …and comes down again. ⚠️ After the clear, not before: the icon
            # is computed from session.lesson.
            self._presence_refresh_onlookers(session)
        return out

    def _lesson_end(self, session: "_Session", period: "lesson.Lesson") -> bytes:
        """0x6102, the 結果発表, and the only place a lesson touches the save file.

        Four things are filed, and the split between them is the point:

        * 出席回数 — recovered. `p06_01` counts attendance towards 課程修了 and
          0x6102 carries the new total, so the client is told the number the
          server just wrote.
        * 通算 questions and correct answers — recovered as a quantity
          (`p06_02`: 「科目の通算正解率」), and they are what the panel over the
          desk prints next period.
        * 成績 — the arithmetic is INVENTED; see ScoreCard.ESTIMATION_BANDS.
        * 能力 — *which* abilities move is read off `lesson.bin`
          (curriculum.SUBJECT_ABILITY); *how much* is INVENTED, see
          lesson.ABILITY_STEP.

        Everything else in resultInfo is not modelled at all, which end_params
        spells out one field at a time.

        ⚠️ The ruler set by `/quiz ab` wins over all of it. It has to: reading a
        value off the 結果発表 means sending a value nothing else can perturb,
        and a lesson that quietly added 64 to one of the six would be exactly the
        perturbation. Whenever it is set, no ability is written to the save.
        """
        card = self._chars(session).scorecard(session.chara_id)
        attendance = 0
        if card is not None:
            attendance = card.attend(period.subject)
            card.answered(period.subject, period.asked, period.right)
            grade = card.regrade(period.subject)
            self._chars(session).set_scorecard(session.chara_id, card)
            print(f"[{self.tag}] lesson end: {curriculum.SUBJECTS[period.subject]} "
                  f"{period.summary()}, 出席 {attendance} 回, "
                  f"通算 {card.rate(period.subject):.0%}, "
                  f"成績 {curriculum.grade_letter(grade)}")
        else:
            print(f"[{self.tag}] lesson end: no charaId={session.chara_id}, "
                  f"nothing filed")
        after, before = lesson.END_ABILITY_AFTER, lesson.END_ABILITY_BEFORE
        # The ruler being set means this period is a measurement rather than a
        # lesson, and that has to hold for every value the message carries, not
        # only the six abilities it was named after: a 結果発表 read off the
        # must not have moved ストレス either.
        measuring = not (after is None and before is None)
        if not measuring:
            after, before = self._file_ability(session, period)
        sheet = self._chars(session).ability(session.chara_id)
        stress_now, condition_now = 0, stress.HEALTHY
        if sheet is not None and measuring:
            stress_now, condition_now = sheet.stress, sheet.condition
        elif sheet is not None:
            added, condition_now = stress.after_lesson(sheet)
            stress_now = sheet.stress
            self._chars(session).set_ability(session.chara_id, sheet)
            print(f"[{self.tag}] lesson end: ストレス +{added} -> {stress_now} "
                  f"({stress.screen(stress_now)}/100), 体調 "
                  f"{stress.name(condition_now)}")
        out = self._answer(
            session,
            0,
            lesson.MSG_SV_NOTIFY_LESSON_END,
            lesson.end_params(period.end_words(), attendance,
                              stress=stress_now, condition=condition_now,
                              ability=after, before_ability=before),
        )
        # The 結果発表 carries both values itself, but that screen goes away and
        # the bar under the character does not — and the client was told about
        # the bar by 0x4811, not by this. So push the pair as well.
        if sheet is not None:
            out += self._push_vitals(session, sheet)
        return out

    def _file_ability(
        self, session: "_Session", period: "lesson.Lesson"
    ) -> "tuple[list[int] | None, list[int] | None]":
        """Apply this lesson's 能力増減 to the save. Returns (after, before).

        Both arrays go to 0x6102, and they are the same six values before and
        after the step, so the client draws the bar climbing from one to the
        other — that animation is the only place a player is told the lesson did
        anything, since the キャラメニュー sheet just shows a total.

        Clamped to a u16 at both ends: the field is unsigned on the wire, so a
        run of bad lessons stops at zero rather than wrapping to レベル 256.
        """
        sheet = self._chars(session).ability(session.chara_id)
        if sheet is None:
            return None, None
        before = list(sheet.params)
        delta = lesson.ability_delta(period.subject, period.right, period.asked)
        sheet.params = [
            max(0, min(0xFFFF, value + step)) for value, step in zip(before, delta)
        ]
        self._chars(session).set_ability(session.chara_id, sheet)
        moved = " ".join(
            f"{name} {before[index]}→{sheet.params[index]}"
            for index, name in enumerate(ability.ABILITIES)
            if before[index] != sheet.params[index]
        )
        print(f"[{self.tag}] lesson end: 能力 {moved or 'unchanged'}")
        return list(sheet.params), before

    # ------------------------------------------------------------------
    # 試験
    # ------------------------------------------------------------------

    def _exam_ready(self, session: "_Session", seen: int) -> bytes:
        """0x6602 → 0x6603 MsgSvOkExamReady, or 0x6604 and a lost connection.

        The admission rule is 授業's, reused rather than restated: `p06_03` says
        outright 「試験は、授業と同じように開始時間に教室に待機していることで参加
        できます」, so lesson.Bell.admit already holds four conditions. The two
        that are the exam's own — 「１科目につき１回しか受けられません」 and an
        empty question bank — are checked here.

        ⚠️⚠️ ``attends`` reads 試験の有無, not 授業の有無 (separate rows; a
        character may have one on and the other off) — and unlike 授業's, this
        check is **unreachable with the real client**, which declines the bell
        itself rather than sending 0x6602. Measured in round 153; see
        _drain_bells. It is kept because the manual's rule is a rule about
        attendance and not about who happens to enforce it, and because the
        round that removed a check on the strength of "the client does it"
        would be repeating the mistake this very check was added to fix. ⚠️ Do
        not cite it as evidence of anything: nothing has ever come through it.

        ⚠️⚠️ admit() answers in lesson.py's numbering and this hands it straight
        to exam.ng_params, whose table numbers the same names differently
        (lesson's ノイローゼ is 3, this block's is 2). Harmless on the wire —
        0x6604's byte draws the same dialog whatever it says, measured — but the
        `reason=` this logs is a lesson.py number, so read it against that
        table and not the one in exam.py. Renumbering either would make a
        recovered-looking table out of two invented ones.

        ⚠️ Refusing costs the connection exactly as 0x6003 does, which is why
        _drain_bells checks the same conditions *before* ringing 0x6601.
        """
        refusal = session.bell.admit(
            session.map_id, session.in_class, neurotic=self._neurotic(session),
            attends=self._attends(session, sitting=True),
        )
        subject = session.bell.rang_subject
        if refusal is None and session.exam.taken(subject):
            refusal = exam.REASON_ALREADY_SAT
        card = self._chars(session).scorecard(session.chara_id)
        course = exam.course_of(card) if card is not None else 0
        if refusal is None and not exam.has_questions(subject, course):
            refusal = exam.REASON_NO_QUESTIONS
        if refusal is not None:
            print(f"[{self.tag}] exam ready refused, reason={refusal}")
            return self._answer(
                session, seen, exam.MSG_SV_NG_EXAM_READY, exam.ng_params(refusal)
            )
        print(f"[{self.tag}] exam ready ok: {curriculum.SUBJECTS[subject]} "
              f"段階{course + 1} (testLv={course}) in map {session.map_id}")
        return self._answer(
            session,
            seen,
            exam.MSG_SV_OK_EXAM_READY,
            exam.ready_params(EXAM_SCHOOL_ID, subject, course),
        )

    def _exam_start(self, session: "_Session", seen: int) -> bytes:
        """0x6A00 → 0x6A01 MsgSvOkExamStart: the whole paper, and its deadline.

        All twenty questions go out at once, which is the shape of the thing:
        a マークシート with page-turn buttons is not a quiz asked one question at
        a time, and there is no per-question message in this block to ask them
        with. The server keeps the same twenty in order so that the choiceId at
        index *i* on the way back is an answer to question *i*.
        """
        subject = session.bell.subject if session.bell.subject >= 0 else \
            session.bell.rang_subject
        card = self._chars(session).scorecard(session.chara_id)
        course = exam.course_of(card) if card is not None else 0
        questions = exam.draw(subject, course)
        if not questions:
            print(f"[{self.tag}] exam start: no questions for "
                  f"{curriculum.SUBJECTS[subject]} at level {course}")
            return self._answer(
                session, seen, exam.MSG_SV_NG_EXAM_START,
                exam.ng_params(exam.REASON_NO_QUESTIONS),
            )
        paper = exam.Paper(subject, course, questions, datetime.now())
        session.exam.paper = paper
        # The client's own clock, as 0x6100's speechEndTime is: the deadline is
        # a moment in the frame the timesync maintains, not a duration.
        end_time = session.client_now() + exam.LIMIT_SECONDS * 1000
        kinds = "".join("○" if q.quiz_type == quiz.TYPE_TRUEFALSE else "４"
                        for q in questions)
        print(f"[{self.tag}] exam start: {curriculum.SUBJECTS[subject]} "
              f"段階{course + 1}, {len(questions)}問 [{kinds}], "
              f"締切 {paper.due:%H:%M:%S} (endTime={end_time})")
        return self._answer(
            session, seen, exam.MSG_SV_OK_EXAM_START,
            exam.start_params(end_time, questions),
        )

    def _exam_sheet(self, session: "_Session", params: bytes, why: str) -> bytes:
        """Take in a mark sheet from 0x6A04 or 0x6A05. Answers nothing.

        ⚠️ inClass is printed on every one of these on purpose: it is the only
        way to find out what an unwritten クラス arrives as, which is the half of
        `p06_03`'s zero rule this server cannot yet enforce. See exam.CLASS_BLANK.
        """
        paper = session.exam.paper
        sheet = exam.parse_sheet(params)
        if sheet is None:
            print(f"[{self.tag}] exam {why}: unparsable, {len(params)} bytes "
                  f"{params[:24].hex()}")
            return b""
        family = sheet["familyName"].split(b"\x00")[0]
        first = sheet["firstName"].split(b"\x00")[0]
        print(f"[{self.tag}] exam {why}: inClass={sheet['inClass']} "
              f"氏名={family.decode('shift_jis', 'replace')}"
              f"{first.decode('shift_jis', 'replace')!r} "
              f"choiceId[{len(sheet['choiceId'])}]={sheet['choiceId']}")
        if paper is not None:
            paper.sheet = sheet
        return b""

    def _exam_part(self, session: "_Session", seen: int, params: bytes) -> bytes:
        """0x6A05 退出 → mark the paper, file it, and 0x6A06 back.

        This is the only place an exam touches the save file, and the one place
        the 試験 half of カリキュラム meets the 授業 half: ScoreCard.record_exam
        files the score, and ScoreCard.completed then has all three of
        `p06_01`'s conditions to compare — score, 成績 and 出席回数 — where
        before today it never had the first and no 課程 could ever be 修了.

        ⚠️ Nothing is shown to the player here. 「自分の結果は、試験期間終了後に
        通知表で確認することができます」, and the block has no result message to
        show one with; the two numbers 0x6A06 does carry are ストレス and 体調.
        """
        out = self._exam_sheet(session, params, "part (退出)")
        paper = session.exam.paper
        if paper is None:
            print(f"[{self.tag}] exam part: no paper in progress")
            return out + self._answer(
                session, seen, exam.MSG_SV_NG_EXAM_PART,
                exam.ng_params(exam.REASON_ALREADY_STARTED),
            )
        session.exam.paper = None
        session.exam.sat.add(paper.subject)
        name = curriculum.SUBJECTS[paper.subject]
        if paper.sheet is None:
            marked, right = 0, 0
            print(f"[{self.tag}] exam end: {name}, no sheet was ever sent — 0 点")
        else:
            marked, right = exam.score(paper.questions, paper.sheet)
            card = self._chars(session).scorecard(session.chara_id)
            if card is not None:
                last, best = card.record_exam(paper.subject, paper.course, marked)
                self._chars(session).set_scorecard(session.chara_id, card)
                done = card.completed(paper.subject, paper.course)
                print(f"[{self.tag}] exam end: {name} 段階{paper.course + 1} "
                      f"{right}/{len(paper.questions)}問正解 → {marked} 点 "
                      f"(前回 {last}, 最高 {best}, 修了 {'済' if done else 'まだ'}, "
                      f"試験レベル {card.test_level()})")
            else:
                print(f"[{self.tag}] exam end: no charaId={session.chara_id}, "
                      f"{marked} 点 filed nowhere")
        # `p05_09` lists 試験 among the things that add ストレス, in the same
        # sentence as 授業 and with no quantity for either.
        sheet = self._chars(session).ability(session.chara_id)
        stress_now, condition_now = 0, stress.HEALTHY
        if sheet is not None:
            added, condition_now = stress.charge(sheet, exam.STRESS_PER_EXAM)
            stress_now = sheet.stress
            self._chars(session).set_ability(session.chara_id, sheet)
            print(f"[{self.tag}] exam end: ストレス +{added} -> {stress_now} "
                  f"({stress.screen(stress_now)}/100), 体調 "
                  f"{stress.name(condition_now)}")
        out += self._answer(
            session, seen, exam.MSG_SV_OK_EXAM_PART,
            exam.part_params(stress_now, condition_now),
        )
        if sheet is not None:
            out += self._push_vitals(session, sheet)
        return out

    def _drain_exam(self, session: "_Session") -> bytes:
        """0x6A03 when the ten minutes are up. seen=0: it answers nothing.

        Only the bell goes out. What the client does with it — hand the sheet in
        with 0x6A04, ask to leave with 0x6A05, or both — is its business, and
        whichever arrives is handled above. The paper stays open until one does,
        so a client that says nothing loses nothing.
        """
        paper = session.exam.paper
        if paper is None or paper.called or not paper.expired():
            return b""
        paper.called = True
        print(f"[{self.tag}] exam: 制限時間 {exam.LIMIT_SECONDS} 秒 終了 "
              f"({paper.summary()})")
        return self._answer(session, 0, exam.MSG_SV_NOTIFY_EXAM_END, b"")

    def _drain_bells(self, session: "_Session") -> bytes:
        """Ring whatever the wall clock has made due.

        Rides on arriving packets for the same reason _drain_console does: this
        server has no timer, and the client's timesync every 30 seconds is the
        heartbeat that stands in for one. So a bell is never early and can be up
        to one timesync late — acceptable against a 15-minute period and a
        5-minute warning, and the reason lesson.GRACE_SECONDS exists.

        ⭐ 試験期間 changes which pair of messages the same two bells are, and
        nothing else: `p06_03` says entry works 「授業と同じように」, the 0x66xx
        block mirrors the 0x60xx one message for message, and the timetable that
        decides the subject is the same timetable. So the schedule, the
        admission rule and the skip logic are shared, and only the id sent
        differs. See exam.Period for what is invented about the period itself.

        seen=0: these answer no message of the client's.
        """
        if session.chara_id == 0:
            return b""
        out = b""
        sitting = session.exam.on
        # Whether this player could be let in if the 本鈴 rang this instant.
        # Bell.poll needs it up front, because ringing at someone who would be
        # refused logs them out — the client asks to come in on its own and
        # closes the connection when told no. See Bell.poll.
        neurotic = self._neurotic(session)
        # ⚠️⚠️ The option screen's two 出席 rows are honoured on OPPOSITE SIDES of
        # the wire, which round 153 found by ringing each bell with its own row
        # turned OFF and watching what came back:
        #
        #   授業の有無 OFF → the client answers 0x6000 with 0x6001 exactly as it
        #     does with the row ON, and sits the whole lesson. Nothing over there
        #     honours it, so this side has to: the 本鈴 is suppressed below.
        #
        #   試験の有無 OFF → the client takes 0x6601, reloads the lobby and never
        #     sends 0x6602. It declines by itself. ⭐ And the existence of that
        #     path is the evidence that the original rang anyway — a client does
        #     not carry handling for a message it was never sent. So the 試験
        #     bell is NOT suppressed here; doing so would override a measured
        #     behaviour with a guess, and cost the player nothing but the scene
        #     reload the client itself chose to do.
        #
        # ⚠️ _exam_ready still refuses on the flag. That is a backstop against a
        # client that does not do what this one does, and with this one it is
        # unreachable — which is why it must not be read as a measurement.
        attends = sitting or self._attends(session, sitting=False)
        admits = (
            attends
            and session.map_id == lesson.classroom_of(session.in_class)
            and not neurotic
        )
        for kind, subject in session.bell.poll(admits=admits):
            name = curriculum.SUBJECTS[subject]
            # 「１科目につき１回しか受けられません」 has to suppress the bell and
            # not merely the entry, for the same reason every other condition
            # does: a 本鈴 the client answers and is refused for is a logout.
            if sitting and kind == "start" and session.exam.taken(subject):
                print(f"[{self.tag}] 試験 {name}: not ringing, already sat this 期間")
                continue
            if kind == "skip":
                why = (
                    # Only ever 授業's row: 試験's is left to the client, above.
                    "オプション 授業の有無 is OFF" if not attends
                    else "player is ノイローゼ" if neurotic
                    else f"player is on map {session.map_id}, not classroom "
                         f"{lesson.classroom_of(session.in_class)}"
                )
                print(f"[{self.tag}] {'試験' if sitting else '本鈴'} {name}: "
                      f"not ringing, {why}")
                continue
            if kind == "pre":
                print(f"[{self.tag}] 予鈴: 次は{name}{'の試験' if sitting else ''}")
                out += self._answer(
                    session,
                    0,
                    exam.MSG_SV_NOTIFY_BEFORE_EXAM_START if sitting
                    else lesson.MSG_SV_NOTIFY_BEFORE_LESSON_START,
                    exam.before_start_params(subject) if sitting
                    else lesson.before_lesson_start_params(subject),
                )
                # Say it in the chat bar as well. The 予鈴 is a sound and an
                # icon in the original and this server cannot make either yet,
                # so until the client is seen reacting to 0x6005 on its own this
                # is the only part of the warning a player can actually notice.
                out += self._say(
                    session,
                    0,
                    f"予鈴。次は{name}{'の試験' if sitting else ''}、"
                    f"{lesson.classroom_of(session.in_class)}番の教室へ",
                )
            else:
                print(f"[{self.tag}] {'試験開始' if sitting else '本鈴'}: {name}")
                out += self._answer(
                    session, 0,
                    exam.MSG_SV_NOTIFY_EXAM_READY if sitting
                    else lesson.MSG_SV_NOTIFY_LESSON_READY,
                    b"",
                )
        return out

    # ------------------------------------------------------------------
    # A console that does not go through the chat bar
    # ------------------------------------------------------------------

    def _drain_console(self, session: "_Session") -> bytes:
        """Lines appended to runtime/console.txt, run as if typed in chat.

        The chat bar has been this server's console since round 21, and that was
        fine until the first script went out: **a running script locks the
        client's input**, which is exactly the moment the next command is most
        needed. The first live attempt ended with the player unable to type
        ``/sce``, and nothing to do but kill the client and log in again.

        So: the same commands, reachable from a shell. There is no timer behind
        it — the file is re-read whenever a packet arrives, and the client sends
        a timesync every 30 seconds even when it is doing nothing else, which is
        the only reason this works while the game is frozen.
        """
        if session.chara_id == 0:
            return b""
        try:
            text = self.console_path.read_text(encoding="utf-8")
        except OSError:
            return b""
        if len(text) <= session.console_at:
            return b""
        fresh, session.console_at = text[session.console_at :], len(text)
        reply = b""
        for line in fresh.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            print(f"[{self.tag}] console: {line}")
            # seen=0: take_seq only ever moves forward, so a push that answers
            # no message of its own is safe to number this way.
            reply += self._apply_chat(session, 0, line)
        return reply

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        print(f"[{self.tag}] listening on {self.config.host}:{self.config.port}")
        return server
