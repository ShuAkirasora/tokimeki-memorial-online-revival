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
import secrets
import struct
import time
from datetime import datetime
from pathlib import Path

from characters import (
    LOOKS,
    ACCESSORY,
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
import chat
import club
import curriculum
import exam
import facing
import lesson
import lesson_skill
import mapgraph
import mps_cipher
import quiz
import romance
import script
import stress
import trainingroom
from common import ServiceConfig, ensure_runtime_dirs, inet_u32, write_packet_log

# All 675 ids, recovered from tmo.exe's parser tables and the category base each
# message's own debug string prints. Regenerate with tools/msgids.py --python.
from message_names import MESSAGE_NAMES

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
# guess: tools/listshape.py walks each Input_<reply> deserializer and reports
# the ones that read a u16 and then loop (``counted``).
EMPTY_LIST_REPLIES = {
    0x0312: 0x0313,  # MsgClQueryGalleryList  -> MsgSvResultGalleryList
    0x0315: 0x0316,  # MsgClQueryEndingList   -> MsgSvResultEndingList
    0x6400: 0x6401,  # MsgClQueryFriendList   -> MsgSvResultFriendList (28B entries)
    # MsgSvResultLockerList is the odd one out: listshape.py calls it "empty",
    # i.e. its reader takes nothing off the wire at all. The items presumably
    # arrive separately as MsgSvNotifyLockerList (0x0409), which *is* counted,
    # with 5-byte entries.
    0x0406: 0x0407,  # MsgClQueryLockerList   -> MsgSvResultLockerList
}

# Requests answered with a constant parameter block. Each layout comes from
# tools/listshape.py plus the field names in the reply's dump function.
FIXED_REPLIES = {
    # MsgClQueryOption -> MsgSvResultOption: four u8 flags, named lesson, test,
    # scorecard and career by the dump at 0x8DA0D0. They are settings the client
    # can push back with MsgClRequestGameOptionUpdate (0x0703, same four bytes).
    # The manual page manual/p05_02 spells them out as ON/OFF pairs, so all-zero
    # is not neutral — it means skipping lessons and exams. Attend both; keep the
    # two 公開 flags off, which is the private-by-default reading.
    0x0700: (0x0701, bytes((1, 1, 0, 0))),  # lesson, test, scorecard, career
    # The lobby handshake that follows 登校. All six messages of the two trios
    # are "empty" by listshape, and Input_MsgSvOkLobbyDataStart's vtable[0] is
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
    # listshape called the reply empty; it is not. Input_MsgSvResultGMCallList's
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
    0x5603: (0x5604, b""),  # MsgClRequestNpcEventEnd   -> MsgSvOkNpcEventEnd
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

# How many 74-byte entries go into one MsgSvNotifyCharacterAdd. Sixteen keeps a
# batch at 1186 bytes of parameters — the same order as the messages already
# known to arrive intact — while 屋外's 72 doorways in one push would be 5.3 KB.
ADD_BATCH = 16

# The direction ruler's stand-ins, kept clear of the doorway markers so the two
# sets can share a scene: reusing an id would tell the client to move a marker
# rather than to add anything, and the ruler would come out with holes in it.
DIRECTION_PROBE_ID_BASE = PROBE_ID_BASE + 100

# What the client sends while the player moves around, decoded rather than left
# as a hex blob because these carry the only coordinates the client ever states
# itself. Shapes are listshape.py's read widths:
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
    script.MSG_CL_REQUEST_NPC_EVENT_START,
    script.MSG_CL_REQUEST_DRAMA_EVENT_START,
}

NOTIFICATIONS = {
    0x0020,  # MsgClNotifyAuthCode
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
# That matters for the account isolation this server does not do. The client
# never names the account it is asking about — MsgClQueryCharacterListFromAccount
# goes out with no parameters at all — so a server that wanted to keep players
# apart would have to bind connection to account itself, and these two are the
# only tokens that arrive early enough to bind with: 0x0020 is the first message
# on the game connection and 0x0200 is the second. Neither is a secret and
# neither is validated, so this is addressing, not authentication.
AUTH_CODE = 0x1234ABCD
ACCOUNT_ID = 1


def ok_login_params(host_be: int = 0x0100007F, port: int = GAME_PORT) -> bytes:
    """Build MsgSvOkLoginServerLogin's parameters.

    The client's own trace names every field::

        paramSize=0, relay_server_auth={ip=16777343, port=25574, authCode=0},
        accountId=0, accountType=0

    so the layout is u16 paramSize, then the relay ticket (u32 ip, u16 port,
    u32 authCode), then u32 accountId and u8 accountType. The address is stored
    the way inet_addr() keeps it, so 127.0.0.1 is 0x0100007F. The client hands
    authCode straight back to the game server as MsgClNotifyAuthCode.
    """
    return struct.pack(">HIHIIB", 0, host_be, port, AUTH_CODE, ACCOUNT_ID, 0)


def ok_school_select_params(host_be: int = 0x0100007F, port: int = SCHOOL_PORT) -> bytes:
    """Build MsgSvOkSchoolSelect's parameters.

    Output_MsgSvOkSchoolSelect::serialize (0x8F7470) writes u32, u16, u32 —
    the same shape as the relay ticket inside MsgSvOkLoginServerLogin, and the
    screen it drives (「学校に接続しています」) wants exactly that: address, port
    and the authCode the client will echo back as MsgClNotifyAuthCode.
    """
    return struct.pack(">IHI", host_be, port, AUTH_CODE)


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
        self.chara_id = 0  # whoever MsgClRequestSchoolLogin named, 0 before 登校
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
        # MsgSvNotifyNpcControl bodies /npc has pushed, so that a map reload can
        # put the same chibis back. Bodies rather than parsed pairs: nothing
        # here needs to read them, only to send them again.
        self.npc_spawns: list[bytes] = []
        # The capture_npc_event key of the conversation currently running,
        # or None when the script on air was started some other way. Only set by
        # the NPC_EVENT_START branch, so that /sc-ing a conversation script by
        # hand does not count as having talked to anybody.
        self.talking_about: tuple[int, int] | None = None
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
        if due is None:
            return None
        return max(0.0, (due - datetime.now()).total_seconds())

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
        characters: CharacterStore | None = None,
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
        # Shared with the other ports when run_all.py passes one in: the client
        # creates a character on the school server and may ask any connection
        # for the list.
        self.characters = characters or CharacterStore(root / "runtime" / "characters.json")
        # 自主トレルーム, held by the server rather than the session because a
        # room outlives whoever asks about it. Not persisted: a 看板 is up only
        # while its leader is logged in, and 0x580D reason 2 (切断による) is the
        # protocol saying so.
        self.trainingrooms = trainingroom.Board()
        # Bytes to put before the tag on everything we send; see packet().
        self.header = b"\x00" * header_size
        runtime, self.packet_dir = ensure_runtime_dirs(root)
        # The out-of-band console; see _drain_console.
        self.console_path = runtime / "console.txt"
        self.tag = f"{name}{config.port}"

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

    def _script_start(
        self,
        session: "_Session",
        seen: int,
        found: "script.Script",
        ctrl: int,
        npc_infos: list[tuple[int, int]],
    ) -> bytes:
        """Arm a script and offer it to the client with MsgSvRequestScriptReady.

        Shared by /sc and by the NPC-event door, so that a script the client
        asked for and a script we pushed by hand go out identically — if they
        behave differently, that difference is about the state the client is in
        and not about which line of ours sent it.
        """
        if found.script_id is None:
            return b""
        session.script = script.Runner(found, ctrl, npc_infos)
        print(
            f"[{self.tag}] script start {found.file} id={found.script_id} "
            f"ctrl={ctrl} npcInfo={npc_infos} ({len(found)} instructions)"
        )
        return self._answer(
            session,
            seen,
            script.MSG_SV_REQUEST_SCRIPT_READY,
            script.ready_params(found.script_id, npc_infos),
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

        Which candidate comes from the capture_npc_event category we handed back
        when the talk started — not from who is standing nearby, which the server
        does not know, and not from the chibi's npcId, which is 1:0 for all of
        them. Anything started by hand (/sc) has no key and credits nobody.
        """
        talking_about, session.talking_about = session.talking_about, None
        if talking_about is None:
            return b""
        found = romance.whose_event(talking_about[0])
        if found is None:
            return b""
        name, kind = found
        love = self.characters.romance(session.chara_id)
        if love is None:
            return b""
        if kind == "main":
            changed, note = love.see_main_event(name), "メインイベント"
        else:
            changed, advanced = love.talk(name)
            note = "日常会話" + (" -> メインイベント!" if advanced else "")
        if not changed:
            return b""
        self.characters.set_romance(session.chara_id, love)
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
            return self._answer(
                session, seen, script.MSG_SV_OK_NPC_MAP_OBJECT_EVENT,
                script.npc_map_object_event_params(session.npc_event, npc_id),
            )

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
            here = found.at(found.local_ip(wire_ip))
            where = f"ip={found.local_ip(wire_ip)} (wire {wire_ip})"
            print(f"[{self.tag}] script at {where} op=0x{op:04x} "
                  f"{here[2] + ' ' + here[3] if here else '<not an instruction start>'}")
            if op == script.OP_END:
                # ⭐ The script says it is over, and until the server agrees the
                # client holds the event screen up with nothing on it — a black
                # screen that looks exactly like a crash and is not one. Sending
                # this makes the client ask for the map back with 0x4000 of its
                # own accord, which is how the player gets out of the cutscene.
                print(f"[{self.tag}] script reached OP_END -> NotifyScriptEnd")
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
            other = "" if taken is None else f" 分岐先は ip={found.local_ip(taken)}"
            print(f"[{self.tag}] script branch -> wire {target} "
                  f"(ip={found.local_ip(target)}, {why}){other}")
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
            print(f"[{self.tag}] ⭐ 選択肢 {result} が選ばれた")
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

    def _script_select(self, session: "_Session", seen: int, local_ip: int) -> bytes:
        """Answer a stopped INPUT_SELECT with MsgSvQueryScriptCommandSelect."""
        select, timer = script.select_query()
        if session.select_override is not None:
            select, timer = session.select_override
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

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.conn_seq += 1
        print(f"[{self.tag}] ACCEPT peer={peer} (conn #{self.conn_seq})")
        session = _Session()
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
                        reader.read(65536), timeout=due if due is not None else 300.0
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
            if session.chara_id and self.trainingrooms.room_of(session.chara_id):
                self.trainingrooms.part(session.chara_id)
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
                print(
                    f"[{self.tag}] next hop {self.advertise_ip}:{GAME_PORT}, "
                    f"authCode={AUTH_CODE:#x}"
                )
                return self._answer(
                    session,
                    sequence,
                    MSG_SV_OK_LOGIN,
                    ok_login_params(self.advertise_host_be),
                )
            if msg_type == MSG_CL_REQUEST_GAME_LOGIN:
                # Input_MsgSvOkGameServerLogin::deserialize (0x8DB8E0) reads a
                # single u16, which the client's own trace names schoolId.
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
                if self.characters.full():
                    print(
                        f"[{self.tag}] create refused: account already has "
                        f"{MAX_CHARACTERS}; {self.characters.summary()}"
                    )
                    return self._answer(
                        session, sequence, MSG_SV_NG_CHARACTER_CREATE, NG_REASON
                    )
                # Output_MsgSvOkCharacterCreate::serialize (0x8DCD80) writes one
                # u32 through the stream's write-u32 slot, and nothing else.
                chara_id = self.characters.add(params)
                print(f"[{self.tag}] character #{chara_id}: {describe(params)}")
                return self._answer(
                    session, sequence, MSG_SV_OK_CHARACTER_CREATE, struct.pack(">I", chara_id)
                )
            if msg_type == MSG_CL_REQUEST_CHARACTER_DESTROY:
                # 「キャラクターを削除しています」. The request is one u32 charaId
                # (listshape: 0x030f scalar reads=4). Ok takes nothing off the
                # wire — Input_MsgSvOkCharacterDestroy's deserializer is 0x8CB9A0,
                # the same ``xor eax,eax; ret 8`` stub MsgSvOkSchoolLogin uses —
                # but Ng is not that stub and does read one byte, so it goes out
                # with NG_REASON. Either way an unknown id gets an answer rather
                # than silence, which would leave the dialog spinning forever.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                if self.characters.remove(chara_id):
                    print(f"[{self.tag}] deleted charaId={chara_id}; left: {self.characters.summary()}")
                    return self._answer(session, sequence, MSG_SV_OK_CHARACTER_DESTROY, b"")
                print(f"[{self.tag}] destroy: no charaId={chara_id}, answering Ng")
                return self._answer(session, sequence, MSG_SV_NG_CHARACTER_DESTROY, NG_REASON)
            if msg_type == MSG_CL_REQUEST_REENTRANCE:
                # 「再入学しています」, the 再入学する button on the character-select
                # screen. Request is one u32 charaId (listshape: 0x031b scalar
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
                if self.characters.find(chara_id) is None:
                    print(f"[{self.tag}] reentrance: no charaId={chara_id}, answering Ng")
                    return self._answer(session, sequence, MSG_SV_NG_REENTRANCE, bytes(1))
                print(f"[{self.tag}] reentrance for charaId={chara_id} (no romance state to clear)")
                return self._answer(session, sequence, MSG_SV_OK_REENTRANCE, b"")
            if msg_type == MSG_CL_QUERY_CHARACTER_LIST:
                # 238 bytes per entry; see characters.py for where each field
                # came from. An empty list here is what sent the client back to
                # the school screen right after it made a character.
                print(f"[{self.tag}] characters: {self.characters.summary()}")
                return self._answer(
                    session, sequence, MSG_SV_RESULT_CHARACTER_LIST, self.characters.entries()
                )
            if msg_type == 0x0303:
                # Reply ids run Request/Ok/Ng in threes (0x0200/01/02 did), so
                # MsgClRequestSchoolSelect(0x0303) answers as 0x0304.
                print(
                    f"[{self.tag}] school hop {self.advertise_ip}:{SCHOOL_PORT}, "
                    f"authCode={AUTH_CODE:#x}"
                )
                return self._answer(
                    session,
                    sequence,
                    0x0304,
                    ok_school_select_params(self.advertise_host_be),
                )
            if msg_type == MSG_CL_REQUEST_SCHOOL_LOGIN:
                # 「登校処理を行っています」. The request carries the u32 charaId
                # picked on the character screen; the answer carries nothing at
                # all — Input_MsgSvOkSchoolLogin's deserializer is 0x8CB9A0,
                # the shared ``xor eax,eax; ret 8`` stub, and its dump function
                # (0x8F75F0) prints the message name and no fields.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                session.chara_id = chara_id
                session.map_id, *pos = self.characters.location(chara_id)
                session.pos = (pos[0], pos[1])
                # Swallow the bells for the lesson already under way, so that
                # 登校 at 14:53 does not ring the 14:45 本鈴 at someone who
                # could not have attended it anyway.
                session.bell.prime()
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
                # ⚠️ A 看板 has to come down here and not only on disconnect:
                # 「ゲームを中断（キャラクター選択画面に戻る）しても、退出する
                # ことになります」 (p07_06), and clearing chara_id below would
                # otherwise strand the room where nothing can reach it again.
                if session.chara_id and self.trainingrooms.room_of(session.chara_id):
                    self.trainingrooms.part(session.chara_id)
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
                info = self.characters.find(session.chara_id)
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
                print(
                    f"[{self.tag}] lobby: adding charaId={session.chara_id}{extra} to map "
                    f"{session.map_id} ({MAP_NAMES.get(session.map_id, '?')}) at {session.pos}"
                    f", in {-(-len(entries) // ADD_BATCH)} batches"
                )
                return reply
            if msg_type == MSG_CL_QUERY_CHARA_INFO:
                # 「サーバーからの返答待ちです」 in the lobby: the client asks this
                # about every character it has been told to draw, one u32 charaId
                # at a time, and the answer carries the record with no id echoed
                # back. The Error reply takes a single byte — listshape calls it
                # empty, but its reader is the shared 0x8D84A0, which reads one
                # field through the stream vtable's +0x1C slot (0xA49960, one byte),
                # a slot listshape does not know about.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                info = self.characters.find(chara_id)
                if info is None and PROBE_ID_BASE <= chara_id < PROBE_ID_LIMIT:
                    # A stand-in — a doorway marker or a direction probe. None of
                    # them has a record of its own; hand back the player's, since
                    # all the client wants is something to draw. The test is the
                    # whole id range rather than the marker count because the
                    # ruler's ids sit past the markers', and a stand-in that gets
                    # an Error back is one the client draws nothing for.
                    info = self.characters.find(session.chara_id)
                if info is None:
                    print(f"[{self.tag}] chara info: no charaId={chara_id}, answering Error")
                    return self._answer(session, sequence, MSG_SV_ERROR_CHARA_INFO, bytes(1))
                print(f"[{self.tag}] chara info for charaId={chara_id}")
                return self._answer(
                    session,
                    sequence,
                    MSG_SV_RESULT_CHARA_INFO,
                    chara_info(info, in_club=self.characters.in_club(chara_id)),
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
            if msg_type == curriculum.MSG_CL_QUERY_SCORE_CARD:
                # 「生徒情報」→「通知表」. One u32 charaId, because a player can
                # look at someone else's if their 通知表公開 option is on — ours
                # is off (FIXED_REPLIES 0x0700), which costs nothing here since
                # the only characters that exist are this account's.
                #
                # The three 必要 columns are absent from the answer on purpose:
                # they are not on the wire at all, and the client fills them
                # from lesson.bin. Whether it really does is what opening this
                # screen is meant to show.
                chara_id = struct.unpack_from(">I", params, 0)[0] if len(params) >= 4 else 0
                card = self.characters.scorecard(chara_id)
                names = self.characters.full_name(chara_id)
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
                sheet = self.characters.ability(chara_id)
                card = self.characters.scorecard(chara_id)
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
            if msg_type in (club.MSG_CL_QUERY_KEYWORD_LIST,
                            club.MSG_CL_QUERY_CLUB_SKILL_LIST):
                # The 部活デッキ window, opened from the toolbar. Two queries,
                # each answered with a count and then the rows; both counts are
                # zero here because nothing on this server grants a キーワード or
                # a 部活奥義. See club.py for why zero is the original's answer.
                pairs = (club.inventory_replies()
                         if msg_type == club.MSG_CL_QUERY_KEYWORD_LIST
                         else club.skill_replies())
                out = b""
                for reply_type, reply_params in pairs:
                    out += self._answer(session, sequence, reply_type, reply_params)
                return out
            if msg_type == club.MSG_CL_QUERY_CLUB_DECK_LIST:
                # The third of the 部活デッキ window's queries, and the one it
                # retries until answered. Empty deck; see club.py for why that
                # avoids guessing at the entry layout.
                deck_id = club.parse_deck_query(params)
                member = self.characters.club(session.chara_id)
                use = member.use_type(deck_id) if member else club.USE_TYPE_NONE
                print(f"[{self.tag}] club deck {deck_id}: empty, useType={use:#04x}")
                return self._answer(
                    session,
                    sequence,
                    club.MSG_SV_RESULT_CLUB_DECK_LIST,
                    club.deck_reply(deck_id, use),
                )
            if msg_type == club.MSG_CL_REQUEST_CLUB_DECK_UPDATE:
                # 「更 新」. ⭐ This is the only place the client ever spells out
                # a useType, which makes answering it the way to measure that
                # byte — it comes back on the next 0x5B01 and the window draws
                # whatever we were told.
                parsed = club.parse_deck_update(params)
                if parsed is None:
                    print(f"[{self.tag}] club deck update: short body {params.hex()}")
                    return self._answer(
                        session,
                        sequence,
                        club.MSG_SV_NG_CLUB_DECK_UPDATE,
                        struct.pack(">BH", club.NG_DECK_NOT_FOUND, 0),
                    )
                deck_id, count, use = parsed
                if count:
                    # Nothing here can own an item, so a non-empty deck means the
                    # entry layout finally has a sample on the wire. Log it and
                    # refuse rather than store bytes we cannot parse.
                    print(
                        f"[{self.tag}] club deck update {deck_id}: count={count} "
                        f"UNEXPECTED, raw={params.hex()}"
                    )
                    return self._answer(
                        session,
                        sequence,
                        club.MSG_SV_NG_CLUB_DECK_UPDATE,
                        struct.pack(">BH", club.NG_DECK_KEYWORD_NOT_OWNED, 0),
                    )
                member = self.characters.club(session.chara_id)
                if member is None:
                    return self._answer(
                        session,
                        sequence,
                        club.MSG_SV_NG_CLUB_DECK_UPDATE,
                        struct.pack(">BH", club.NG_DECK_NOT_FOUND, 0),
                    )
                member.deck_use[deck_id] = use
                self.characters.set_club(session.chara_id, member)
                print(f"[{self.tag}] club deck update {deck_id}: useType={use:#04x}")
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
                return self._answer(
                    session,
                    sequence,
                    stress.MSG_SV_NOTIFY_CHARA_POSE,
                    stress.pose_params(session.chara_id, session.pose),
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
                    return self._answer(
                        session,
                        sequence,
                        MSG_SV_NOTIFY_CHARA_TURN,
                        struct.pack(">IB", session.chara_id, session.direction),
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
                    # mapdata.py's docstring is wrong and should be taken apart.
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
                if self.characters.set_position(
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
                    # reads rather than trusting listshape's "empty".
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
                    # 18 bytes, not the 10 listshape reports: after charaId, the
                    # two coordinates, status and direction comes arrivalTime,
                    # read through the stream vtable's +0x10 slot, which 0xA49A50
                    # shows taking eight bytes. listshape does not know that slot,
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
                    return self._answer(
                        session,
                        sequence,
                        MSG_SV_NOTIFY_CHARA_MOVE,
                        struct.pack(
                            ">IHHBBQ",
                            session.chara_id,
                            pos_x,
                            pos_y,
                            status,
                            session.direction,
                            arrival,
                        ),
                    )
                return None
            if msg_type == MSG_CL_CAST_NORMAL_CHAT:
                # A cast, so nothing appears until the server broadcasts it back:
                # the speaker's own words reach them the same way everyone else's
                # would. See chat.py for both messages' layouts and for why the
                # server, not the client, has to keep the strings short.
                said = chat.parse_cast(params)
                info = self.characters.find(session.chara_id)
                who = display_name(info) if info else "?"
                print(f"[{self.tag}] chat {who}: {said!r}")
                reply = self._answer(
                    session,
                    sequence,
                    MSG_SV_NOTIFY_NORMAL_CHAT,
                    chat.notify_params(session.chara_id, who, said),
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
        state = self.characters.club(session.chara_id)
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
        self.characters.set_club(session.chara_id, state)
        print(f"[{self.tag}] club enter charaId={session.chara_id} -> {state.summary()}")
        return self._answer(session, sequence, club.MSG_SV_OK_CLUB_ENTER, b"")

    def _club_part(self, session: "_Session", sequence: int) -> bytes:
        """0x5A03 -> 0x5A04 MsgSvOkClubPart, or 0x5A05 with a reason.

        Leaving stamps the day so the ten-day wait can be measured; nothing else
        on this server reads that stamp, which is the point of writing it now.
        """
        state = self.characters.club(session.chara_id)
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
        self.characters.set_club(session.chara_id, state)
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
        """The two fixed-width name halves 0x580C and 0x580F carry."""
        names = self.characters.full_name(chara_id)
        return names if names else (b"\x00" * trainingroom.NAME_LEN,) * 2

    def _tr_roster(self, session: "_Session", room: "trainingroom.Room") -> bytes:
        """0x580C. seen=0 because it answers nothing — it follows a change.

        ⚠️ The recipient is left out; see Room.roster_params for the two things
        the room window did when they were not.
        """
        return self._answer(
            session,
            0,
            trainingroom.MSG_SV_NOTIFY_JOIN,
            room.roster_params(without=session.chara_id),
        )

    def _trainingroom(
        self, session: "_Session", sequence: int, msg_type: int, params: bytes
    ) -> "bytes | None":
        """The whole 0x58xx family, dispatched off one branch.

        Every Notify goes back down this same connection: a room here has one
        member, so reflecting is the whole broadcast. See trainingroom.py.
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
            reason = board.add_refusal(chara_id, headline, limit)
            if reason is not None:
                return ng(trainingroom.MSG_SV_NG_ADD, reason, f"add {params.hex()}")
            family, first = self._tr_names(chara_id)
            room = board.open(chara_id, headline, limit, family, first)
            print(f"[{self.tag}] trainingroom opened {room.summary()}")
            out = self._answer(session, sequence, trainingroom.MSG_SV_OK_ADD, b"")
            return out + self._tr_roster(session, room)

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
            reason = board.join_refusal(chara_id, leader_id)
            if reason is not None:
                return ng(
                    trainingroom.MSG_SV_NG_JOIN, reason, f"join leaderId={leader_id:#x}"
                )
            room = board.rooms[leader_id]
            family, first = self._tr_names(chara_id)
            room.add(chara_id, family, first)
            print(f"[{self.tag}] trainingroom joined {room.summary()}")
            out = self._answer(
                session, sequence, trainingroom.MSG_SV_OK_JOIN, room.join_params()
            )
            return out + self._tr_roster(session, room)

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
            out = self._answer(session, sequence, trainingroom.MSG_SV_OK_PART, b"")
            # ⚠️ The Notify goes out even though the leaver is the only member:
            # it is what tells a client its own row is gone, and with one player
            #「自分自身の要求による」 is the reason every time.
            return out + self._answer(
                session,
                0,
                trainingroom.MSG_SV_NOTIFY_PART,
                trainingroom.notify_part_params(
                    chara_id, leader_id, trainingroom.PART_REASON_SELF
                ),
            )

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
            return self._answer(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_CHAT,
                trainingroom.notify_chat_params(chara_id, family, first, said),
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
            return self._answer(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_READY,
                trainingroom.notify_ready_params(chara_id, member.ready),
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
            out += self._answer(
                session,
                0,
                trainingroom.MSG_SV_NOTIFY_TEAM,
                trainingroom.notify_team_params(chara_id, team),
            )
            return out + self._tr_roster(session, room)

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
            # battle is the 0x5C** family, and NONE of it is implemented — the
            # client is expected to answer this with 0x581B and then start
            # asking. That first unanswered id is the finding this branch is for.
            print(f"[{self.tag}] trainingroom battle start: {room.summary()}")
            return self._answer(
                session, sequence, trainingroom.MSG_SV_NOTIFY_BATTLE_START, b""
            )

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
            board.part(target)
            print(f"[{self.tag}] trainingroom kicked {target:#x}, now {board.summary()}")
            out = self._answer(
                session,
                sequence,
                trainingroom.MSG_SV_NOTIFY_PART,
                trainingroom.notify_part_params(
                    target, room.leader_id, trainingroom.PART_REASON_KICKED
                ),
            )
            return out + self._tr_roster(session, room)

        print(f"[{self.tag}] no reply implemented for 0x{msg_type:04x} yet")
        return None

    def _apply_chat(self, session: "_Session", sequence: int, said: str) -> bytes:
        """Run one console line and pack whatever it asked for.

        Split out of the chat branch so that runtime/console.txt can reach the
        same commands — see _drain_console for why that had to exist.
        """
        reply = b""
        info = self.characters.find(session.chara_id)
        love = self.characters.romance(session.chara_id)
        card = self.characters.scorecard(session.chara_id)
        sheet = self.characters.ability(session.chara_id)
        member = self.characters.club(session.chara_id)
        answer = chat.respond(
            said, session.map_id, session.pos, love, card, session.lesson,
            sheet, session.in_class, session.exam, member,
        )
        if answer.romance_save and love is not None:
            self.characters.set_romance(session.chara_id, love)
        if answer.scorecard_save and card is not None:
            self.characters.set_scorecard(session.chara_id, card)
        if answer.ability_save and sheet is not None:
            self.characters.set_ability(session.chara_id, sheet)
        if answer.club_save and member is not None:
            self.characters.set_club(session.chara_id, member)
        if answer.npc_event is not None:
            session.npc_event = answer.npc_event
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
            self.characters.set_position(session.chara_id, session.pos, map_id)
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
        info = self.characters.find(session.chara_id)
        if info is None:
            print(f"[{self.tag}] lesson start: no charaId={session.chara_id}")
            return self._answer(
                session,
                seen,
                lesson.MSG_SV_NOTIFY_LESSON_START_IMPOSSIBLE,
                lesson.ng_params(lesson.REASON_NOT_IN_CLASSROOM),
            )
        fields = parse_create_info(info)
        card = self.characters.scorecard(session.chara_id)
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
        out += self._drain_vitals(session)
        out += self._drain_pending_say(session)
        return out

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
        sheet = self.characters.ability(session.chara_id)
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
                self.characters.set_ability(session.chara_id, sheet)
                print(
                    f"[{self.tag}] 休憩: ストレス -{removed} -> {sheet.stress} "
                    f"({stress.screen(sheet.stress)}/100), 体調 "
                    f"{stress.name(sheet.condition)}"
                )
        return self._push_vitals(session, sheet)

    def _neurotic(self, session: "_Session") -> bool:
        """Is this player currently barred from 学業?

        ドクターストップ is 「ノイローゼと怪我が重なった状態」, so it bars 学業
        as well; 怪我 alone bars クラブ活動, which this server does not have.
        """
        sheet = self.characters.ability(session.chara_id)
        return sheet is not None and sheet.condition in (
            stress.NEUROSIS, stress.DOCTOR_STOP
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
        sheet = self.characters.ability(session.chara_id)
        card = self.characters.scorecard(session.chara_id)
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
            self.characters.set_ability(session.chara_id, sheet)
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
        card = self.characters.scorecard(session.chara_id)
        attendance = 0
        if card is not None:
            attendance = card.attend(period.subject)
            card.answered(period.subject, period.asked, period.right)
            grade = card.regrade(period.subject)
            self.characters.set_scorecard(session.chara_id, card)
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
        sheet = self.characters.ability(session.chara_id)
        stress_now, condition_now = 0, stress.HEALTHY
        if sheet is not None and measuring:
            stress_now, condition_now = sheet.stress, sheet.condition
        elif sheet is not None:
            added, condition_now = stress.after_lesson(sheet)
            stress_now = sheet.stress
            self.characters.set_ability(session.chara_id, sheet)
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
        sheet = self.characters.ability(session.chara_id)
        if sheet is None:
            return None, None
        before = list(sheet.params)
        delta = lesson.ability_delta(period.subject, period.right, period.asked)
        sheet.params = [
            max(0, min(0xFFFF, value + step)) for value, step in zip(before, delta)
        ]
        self.characters.set_ability(session.chara_id, sheet)
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
        できます」, so lesson.Bell.admit already holds three of the four
        conditions. The fourth is the exam's own — 「１科目につき１回しか受けら
        れません」 — and it is checked here.

        ⚠️ Refusing costs the connection exactly as 0x6003 does, which is why
        _drain_bells checks the same conditions *before* ringing 0x6601.
        """
        refusal = session.bell.admit(
            session.map_id, session.in_class, neurotic=self._neurotic(session),
        )
        subject = session.bell.rang_subject
        if refusal is None and session.exam.taken(subject):
            refusal = exam.REASON_ALREADY_SAT
        card = self.characters.scorecard(session.chara_id)
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
        card = self.characters.scorecard(session.chara_id)
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
            card = self.characters.scorecard(session.chara_id)
            if card is not None:
                last, best = card.record_exam(paper.subject, paper.course, marked)
                self.characters.set_scorecard(session.chara_id, card)
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
        sheet = self.characters.ability(session.chara_id)
        stress_now, condition_now = 0, stress.HEALTHY
        if sheet is not None:
            added, condition_now = stress.charge(sheet, exam.STRESS_PER_EXAM)
            stress_now = sheet.stress
            self.characters.set_ability(session.chara_id, sheet)
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
        admits = (
            session.map_id == lesson.classroom_of(session.in_class) and not neurotic
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
                    "player is ノイローゼ" if neurotic
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
