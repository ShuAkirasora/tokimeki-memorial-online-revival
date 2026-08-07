"""自主トレ: the 看板 room, and the only club-battle entry that has no NPC in it.

Thirty messages, 0x5800-0x581D. They build and run the room that 自主トレ
(PC-vs-PC practice) is fought out of: create it, look at it, join it, pick a
team, chat, say you are ready, start, kick, leave.

⭐⭐ WHY THIS FAMILY AND NOT 練習. クラブ対戦 has three doors and the manual
names each one's entry point:

    練習 (NPC対戦)   p07_03  顧問またはキャプテンの交流メニュー
    フリー対戦        p07_06  顧問またはキャプテンの交流メニュー
    自主トレ (PC対戦) p07_04  メインメニュー中の「看板」から

The first two are unreachable here and not because of anything in this
subsystem: 顧問 and キャプテン are in the 44 ちびキャラ scripts that carry no
MAP_CHARA_DISP_ON, and NpcControl can only ever place the five 恋愛候補生
(2.24). 自主トレ is the one that opens off the toolbar instead, the same way
the 部活デッキ window turned out to (2.35) — and 「自主トレの流れは、ＮＰＣと
の練習と同じです」, so it runs the same 0x5C** battle the other two do.

⭐ The window exists in this build. `tmo.exe` carries 「看板作成」 and
「他の行動中は看板を作成できません」 as its own strings, which is also a note
that some of the gating on this is client-side and will never reach us.

Shapes from the frozen shape dump, field names from each class's own
dump function, refusals from `error_message.bin`. No disassembly, the same
loop rounds 62-66 used.

    0x5800 MsgClRequestTrainingroomAdd         name[u16], limit u8
    0x5801 MsgSvOkTrainingroomAdd              ()
    0x5802 MsgSvNgTrainingroomAdd              reason u8
    0x5803 MsgClRequestTrainingroomInfo        leaderId u32
    0x5804 MsgSvOkTrainingroomInfo             leaderId u32, name[u16], limit u8,
                                               team1 u8, team2 u8
    0x5805 MsgSvNgTrainingroomInfo             reason u8
    0x5806 MsgClRequestTrainingroomJoin        leaderId u32
    0x5807 MsgSvOkTrainingroomJoin             leaderId u32, name[u16], limit u8
    0x5808 MsgSvNgTrainingroomJoin             reason u8
    0x5809 MsgClRequestTrainingroomPart        ()
    0x580A MsgSvOkTrainingroomPart             ()
    0x580B MsgSvNgTrainingroomPart             reason u8
    0x580C MsgSvNotifyTrainingroomJoin         team1charas[u16]{charaId u32,
                                                 name{familyName[11],
                                                      firstName[11]}, ready u8},
                                               team2charas[u16]{same}
    0x580D MsgSvNotifyTrainingroomPart         charId u32, leaderId u32, reason u8
    0x580E MsgClCastTrainingroom               message[u16]
    0x580F MsgSvNotifyTrainingroom             charaId u32, familyName[11],
                                               firstName[11], message[u16]
    0x5810 MsgSvErrorTrainingroom              reason u8
    0x5811 MsgClCastTrainingroomReady          ready u8
    0x5812 MsgSvNotifyTrainingroomReady        charaId u32, ready u8
    0x5813 MsgSvErrorTrainingroomReady         reason u8
    0x5814 MsgClRequestTrainingroomTeamSelect  team u8
    0x5815 MsgSvOkTrainingroomTeamSelect       ()
    0x5816 MsgSvNgTrainingroomTeamSelect       reason u8
    0x5817 MsgSvNotifyTrainingroomTeam         charaId u32, team u8
    0x5818 MsgClCastTrainingroomClubBattleStart    ()
    0x5819 MsgSvNotifyTrainingroomClubBattleStart  ()
    0x581A MsgSvErrorTrainingroomClubBattleStart   reason u8
    0x581B MsgClNotifyTrainingroomBattleStart  ()      client -> server, no reply
    0x581C MsgClCastTrainingroomKick           charaId u32
    0x581D MsgSvErrorTrainingroomKick          reason u8

⚠️ 0x5804's two trailing u8 are named ``team1`` and ``team2`` by the dump and
sit where the shape reader reports two more single bytes. They are read here as the
head-counts the 看板 shows for each side, which is what a room listing needs
and what the Join reply pointedly leaves out. NOT CONFIRMED ON SCREEN — if the
board ever prints two numbers that look like ids rather than counts, this is
the pair to suspect.

A room of one
-------------
Every Notify here goes back down the connection it came from, the same
arrangement 0x4901 chat uses. That is not a simplification: this server has one
player, so a room's whole membership is the one session, and reflecting is
exactly right for it. ⚠️ It is also the ceiling — 自主トレ is 最大１０人対１０人
and none of the multi-player half can be exercised until account isolation
exists at all (the CharacterStore is one shared list; see the README).

RESTORED: the refusals
----------------------
89 sentences across the family's nine error messages, and the reason *is* the
index within each message's own run (2.34). The ones this server can reach are
named below; the rest are written down so the next round need not look them up.

⚠️ 0x581D is the odd one: its reason 0 is a real sentence
(「キャラクター情報が不正です」) rather than the 未使用 placeholder every other
message in the family starts with. Do not assume 0 is always "no error".

0x5802 自主トレルーム作成, fifteen sentences:

     0  未使用: エラーなし
     1  未使用: キャラクターデータが不正
     2  参加許容人数もしくは見出しテキストのサイズが不正です。
     3  既に自主トレルームに入っているため、自主トレルームを作成できません。
     4  自主トレルームの作成に失敗しました。
     5  今の状態では、自主トレルームを作成することはできません。
     6  サーバーエラー: 作成情報の送信に失敗
     7  キャラクター情報が不正です。
     8  キャラクター情報の取得に失敗しました。
     9  現在、自主トレチャットを行うことはできません。
    10  キャラクターデータの取得に失敗しました。
    11  怪我をしていると、自主トレに参加することはできません。
    12  マップ情報が不正です。
    13  この場所は自主トレ禁止エリアです。別の場所で自主トレしましょう。
    14  未使用: 未定義のエラー

0x5808 参加, thirteen: 1 情報が不正 / 2 既に別の room に入っている /
3 今の状態では入れない / 4 room の情報を取得できず / 5 サーバーエラー /
6, 7 キャラクター情報・データの取得失敗 / 8 チャット不可 /
9 満員 / 10 怪我 / 11 他の同時実行できない動作を行っている / 12 未定義。

0x5805 情報照会: 2 情報の取得に失敗 / 3 サーバーエラー。
0x580B 退室: 1 情報が不正 / 3 今の状態では出られない / 4 退室に失敗 /
6, 7 取得失敗。
0x5810 発言: 2 発言に失敗 / 4, 5 取得失敗 / 6 チャット不可。
0x5813 準備: 2 準備に失敗 / 4, 5 取得失敗。
0x5816 チーム移動: 3 移動先チームの情報が不正 / 4 移動に失敗 / 7, 8, 10 取得失敗。
0x581A 開始: 1 情報が不正 / 2 開始に失敗 / 4, 5 取得失敗 /
7 参加者全員の開始準備ができていません。
0x581D 強制退室: 0 情報が不正 / 1 失敗 / 2 リーダー以外に権限なし /
3 強制退室不可能なキャラクター / 4 システムエラー。

⭐ 0x5802 reason 13 and the manual agree with each other:
「（一般教室など、自主トレが禁止されている場所もあります）」. ⚠️ IT IS NOT
ENFORCED HERE, on purpose. `map.bin`'s record ends in two bytes this project
had not decoded, and the last one splits the 93 maps into a 0 set (every
一般教室校舎 room, the corridors, the 屋上踊り場, 職員室, 理事長室) and a 1 set
(outdoors, the 部室, 体育館, プール, 食堂, 図書室, 多目的室 …). That 0 set is a
very good fit for 「一般教室など」 — and it fits 「indoor spaces you can hold an
activity in」 just as well, and nothing on hand separates the two readings. A
rule invented off the better-sounding of two fits is still invented, so this
sends no reason 13 and says so. ⭐ The byte *before* it is not in doubt: it is
0 / 1 / 2 for no restriction / 男子 / 女子, which is exactly the six 男子トイレ・
男子更衣室 and six 女子トイレ・女子更衣室 and nothing else.

RESTORED: why a member left
---------------------------
0x580D's ``reason`` is not in `error_message.bin` — it is not a refusal. The
client carries the table itself, as the three strings its own party dumper
prints after 「パーティから離脱しました。\\n理由：」:

    0  自分自身の要求による      -> 0x5809 Part
    1  リーダーに排除された      -> 0x581C Kick
    2  切断による                -> the connection dropped

⭐ Three causes, and this family has exactly three ways out of a room. What
justifies reading that debug table as this field: it is the only ordered
three-way 「理由」 in the binary that names a リーダー, and ``leaderId`` is the
field 0x580D carries beside it.

MEASURED OFF THE SCREEN: what ``limit`` counts
----------------------------------------------
⭐⭐ The 看板作成 window's 参加人数 is a dropdown, and a dropdown enumerates its
own legal values — so this is read rather than reasoned. It runs **2 to 20**,
starting at 2 and with nothing below it.

⚠️ That corrects the obvious reading of 「最大１０人対１０人で対戦が可能です」
(p07_04). Ten-a-side is twenty in the room, and ``limit`` is the WHOLE room's
capacity, not one side's: the teams are picked from inside the room
(「最初は自動的にどちらかのチームに振り分けられます」), so there is one pool to
cap. A first cut here had ``MAX_MEMBERS = 10`` per side, taken from that manual
sentence alone, and the dropdown refuted it. When a manual sentence and a guess
about what it counts disagree, the guess is what is wrong.

⭐ The floor is data too: 2 is the smallest room offered, which is the window
saying a 自主トレ needs somebody to train against.

The 見出し is length-checked only against the body that carried it — no
character cap is invented, since nothing on hand states one.
"""
from __future__ import annotations

import struct

MSG_CL_REQUEST_ADD = 0x5800
MSG_SV_OK_ADD = 0x5801
MSG_SV_NG_ADD = 0x5802
MSG_CL_REQUEST_INFO = 0x5803
MSG_SV_OK_INFO = 0x5804
MSG_SV_NG_INFO = 0x5805
MSG_CL_REQUEST_JOIN = 0x5806
MSG_SV_OK_JOIN = 0x5807
MSG_SV_NG_JOIN = 0x5808
MSG_CL_REQUEST_PART = 0x5809
MSG_SV_OK_PART = 0x580A
MSG_SV_NG_PART = 0x580B
MSG_SV_NOTIFY_JOIN = 0x580C
MSG_SV_NOTIFY_PART = 0x580D
MSG_CL_CAST_CHAT = 0x580E
MSG_SV_NOTIFY_CHAT = 0x580F
MSG_SV_ERROR_CHAT = 0x5810
MSG_CL_CAST_READY = 0x5811
MSG_SV_NOTIFY_READY = 0x5812
MSG_SV_ERROR_READY = 0x5813
MSG_CL_REQUEST_TEAM_SELECT = 0x5814
MSG_SV_OK_TEAM_SELECT = 0x5815
MSG_SV_NG_TEAM_SELECT = 0x5816
MSG_SV_NOTIFY_TEAM = 0x5817
MSG_CL_CAST_BATTLE_START = 0x5818
MSG_SV_NOTIFY_BATTLE_START = 0x5819
MSG_SV_ERROR_BATTLE_START = 0x581A
MSG_CL_NOTIFY_BATTLE_START = 0x581B
MSG_CL_CAST_KICK = 0x581C
MSG_SV_ERROR_KICK = 0x581D

# Reason codes, named for what the sentence says rather than for why we send it.
NG_ADD_BAD_SIZE = 2
NG_ADD_ALREADY_IN_ROOM = 3
NG_ADD_FAILED = 4
NG_ADD_INJURED = 11
NG_ADD_FORBIDDEN_AREA = 13  # not sent; see the module docstring

NG_INFO_NOT_FOUND = 2

NG_JOIN_ALREADY_IN_ROOM = 2
NG_JOIN_NOT_FOUND = 4
NG_JOIN_FULL = 9
NG_JOIN_INJURED = 10

NG_PART_NOT_IN_ROOM = 3
NG_PART_FAILED = 4

ERROR_CHAT_FAILED = 2
ERROR_READY_FAILED = 2

NG_TEAM_BAD_TEAM = 3
NG_TEAM_FAILED = 4

ERROR_START_FAILED = 2
ERROR_START_NOT_ALL_READY = 7

ERROR_KICK_BAD_CHARACTER = 0
ERROR_KICK_NOT_LEADER = 2
ERROR_KICK_UNKICKABLE = 3

# 0x580D's reason, out of the client's own party dumper. See the docstring.
PART_REASON_SELF = 0
PART_REASON_KICKED = 1
PART_REASON_DISCONNECTED = 2

# Both ends read straight off the 参加人数 dropdown, which lists 2 … 20 and
# nothing else. This is the room's total, both teams together; see the docstring
# for why the manual's 「１０人対１０人」 is the same number said differently.
MIN_MEMBERS = 2
MAX_MEMBERS = 20

# tmn::MAX_CHARA_FAMILYNAME + 1, the fixed width both name halves travel at.
NAME_LEN = 11

# ⭐⭐ MEASURED (round 67): teams are 0-BASED, and the window names them
# 「Ａチーム」「Ｂチーム」. Two independent sides agree — clicking the Ｂチーム
# header (its tooltip is 「Ｂチームに入る」) sent 0x5814 team = **1**, and a
# 0x5817 carrying team = 1 put its row in Ｂ. So team1charas is Ａ and it is 0.
#
# ⚠️ The earlier reading here was 1 and 2, from the dump's names alone. Logging
# the raw byte on every request is what caught it — the same trick that measured
# useType (2.35): answer the request, then read what the control says back.
TEAM_A = 0
TEAM_B = 1
TEAMS = (TEAM_A, TEAM_B)


def _string(raw: bytes) -> bytes:
    """A counted string the way this protocol writes them: u16 length, then bytes.

    The count includes the NUL, matching chat.notify_params — the client's own
    casts carry their terminator and its copier writes exactly the counted bytes.
    """
    body = raw.split(b"\x00", 1)[0] + b"\x00"
    return struct.pack(">H", len(body)) + body


def parse_string(params: bytes, offset: int = 0) -> "tuple[bytes, int] | None":
    """``(text, next offset)`` for a counted string, or None if it overruns.

    Cut at the first NUL for the same reason chat.parse_cast does: the count
    includes the terminator, and str.strip() does not treat NUL as whitespace.
    """
    if len(params) < offset + 2:
        return None
    (length,) = struct.unpack_from(">H", params, offset)
    end = offset + 2 + length
    if len(params) < end:
        return None
    return params[offset + 2 : end].split(b"\x00", 1)[0], end


def parse_add(params: bytes) -> "tuple[bytes, int] | None":
    """0x5800 -> ``(headline, limit)``, or None if the body is not that shape."""
    read = parse_string(params)
    if read is None:
        return None
    headline, offset = read
    if len(params) < offset + 1:
        return None
    return headline, params[offset]


def parse_leader(params: bytes) -> "int | None":
    """The leaderId 0x5803 and 0x5806 name, or None if the body is short."""
    if len(params) < 4:
        return None
    return struct.unpack_from(">I", params, 0)[0]


# ⭐⭐ MEASURED (round 67), and it is INVERTED from what the field name suggests.
# The button is a toggle and the room window says which state it is in:
#
#     press 「準備ＯＫ」 -> wire 0 -> row gets an OK badge, button becomes 「再準備」
#     press 「再準備」   -> wire 1 -> badge clears,          button becomes 「準備ＯＫ」
#
# So on the wire **0 is ready**. Reading the byte as a plain boolean would have
# every readiness gate backwards, which is 0x581A reason 7's whole job.
#
# ⚠️ What is NOT separated: whether the badge is drawn off our 0x5812 or off the
# client's own press. This server echoes back what it was sent, so both stories
# fit. The test for a later round: echo the opposite value once and see which
# the badge follows. It matters only when a second player exists to be told.
READY_ON = 0
READY_OFF = 1


def parse_ready(params: bytes) -> bool:
    """0x5811 -> is this character ready? An absent body reads as not ready."""
    return bool(params) and params[0] == READY_ON


def parse_team(params: bytes) -> "int | None":
    """0x5814's team, unvalidated — the caller decides what is in range."""
    return params[0] if params else None


class Member:
    """One character sitting in a room."""

    def __init__(self, chara_id: int, family: bytes, first: bytes, team: int) -> None:
        self.chara_id = chara_id
        self.family = family[:NAME_LEN].ljust(NAME_LEN, b"\x00")
        self.first = first[:NAME_LEN].ljust(NAME_LEN, b"\x00")
        self.team = team
        self.ready = False

    def entry(self) -> bytes:
        """One row of 0x580C: charaId u32, two fixed names, ready u8."""
        return (
            struct.pack(">I", self.chara_id)
            + self.family
            + self.first
            + struct.pack(">B", READY_ON if self.ready else READY_OFF)
        )


class Room:
    """One 自主トレルーム: its headline, its per-side cap, and who is in it.

    The leader is the character who created it, and ``leaderId`` is how every
    other message names the room — there is no separate room id anywhere in the
    family, which is the protocol agreeing with 「フリー対戦ルームを作成した
    キャラクター」 being the thing you right-click to join.
    """

    def __init__(self, leader_id: int, headline: bytes, limit: int) -> None:
        self.leader_id = leader_id
        self.headline = headline
        self.limit = limit
        self.members: "list[Member]" = []

    def find(self, chara_id: int) -> "Member | None":
        for member in self.members:
            if member.chara_id == chara_id:
                return member
        return None

    def team(self, team: int) -> "list[Member]":
        return [m for m in self.members if m.team == team]

    def full(self) -> bool:
        """0x5808 reason 9's condition: 「選択された自主トレルームは満員です」.

        ⚠️ Against the room's total, not one side's — see the docstring on what
        the 参加人数 dropdown turned out to be counting. Nothing caps a single
        team, and the manual does not either: an 8-versus-2 room is legal, it is
        just a bad idea.
        """
        return len(self.members) >= self.limit

    def smaller_team(self) -> int:
        """Which side to drop a joiner on: 「最初は自動的にどちらかのチームに
        振り分けられます」 (p07_04). Evening the sides is this server's reading
        of 「自動的に」; the manual does not say which one it picks.
        """
        return TEAM_A if len(self.team(TEAM_A)) <= len(self.team(TEAM_B)) else TEAM_B

    def add(self, chara_id: int, family: bytes, first: bytes) -> "Member":
        member = Member(chara_id, family, first, self.smaller_team())
        self.members.append(member)
        return member

    def remove(self, chara_id: int) -> bool:
        member = self.find(chara_id)
        if member is None:
            return False
        self.members.remove(member)
        return True

    def all_ready(self) -> bool:
        """0x581A reason 7's condition: 「参加者全員の開始準備ができていません」.

        ⚠️ The leader is excluded. 「リーダー以外の参加者は『準備ＯＫ』を押して」
        (p07_06) — the leader's button is 「開始」, not 「準備ＯＫ」, so a leader
        is never waiting on themselves.
        """
        return all(m.ready for m in self.members if m.chara_id != self.leader_id)

    def info_params(self) -> bytes:
        """0x5804: leaderId u32, headline, limit u8, team1 u8, team2 u8."""
        return (
            struct.pack(">I", self.leader_id)
            + _string(self.headline)
            + struct.pack(
                ">BBB",
                self.limit & 0xFF,
                min(0xFF, len(self.team(TEAM_A))),
                min(0xFF, len(self.team(TEAM_B))),
            )
        )

    def join_params(self) -> bytes:
        """0x5807: the same head, without the two counts."""
        return (
            struct.pack(">I", self.leader_id)
            + _string(self.headline)
            + struct.pack(">B", self.limit & 0xFF)
        )

    def roster_params(self, without: "int | None" = None) -> bytes:
        """0x580C: both team rosters, each a u16 count then 27-byte rows.

        It is the only message that carries names — 0x5812 and 0x5817 only carry
        a charaId — so a client that missed one would have nothing to draw a row
        with.

        ⚠️⚠️ ``without`` IS NOT OPTIONAL IN PRACTICE: pass the recipient. Two
        things were read off the room window (round 67) and both say so:

        * The client seats **itself** without being told to. A room whose only
          member is the recipient, sent a one-row roster, drew 「参加者：２名」
          and the same 試験 太郎 twice.
        * The lists are **merged in, not swapped in**. A second identical send
          took the count to three rather than leaving it at two.

        So this message answers 「who else is here」, and the recipient is never
        part of the answer. ⭐ It is the mirror of a trap this project has fallen
        into three times in the other direction — a Notify that must reach the
        player themselves to take effect. Here the Notify must leave them out.
        """
        out = b""
        for team in TEAMS:
            rows = [m for m in self.team(team) if m.chara_id != without]
            out += struct.pack(">H", len(rows)) + b"".join(m.entry() for m in rows)
        return out

    def summary(self) -> str:
        headline = self.headline.decode("cp932", "replace")
        sides = "/".join(str(len(self.team(t))) for t in TEAMS)
        return f"「{headline}」 leader={self.leader_id:#x} Ａ/Ｂ={sides} (定員 {self.limit})"


class Board:
    """Every 自主トレルーム currently up, keyed by its leader.

    ⚠️ There is only ever one player here, so this holds at most one room. It is
    a mapping rather than a single slot so that 0x5803 and 0x5806 can answer
    「選択された自主トレルームの情報の取得に失敗しました」 honestly for a
    leaderId that is not a room, instead of handing back whatever exists.
    """

    def __init__(self) -> None:
        self.rooms: "dict[int, Room]" = {}

    def room_of(self, chara_id: int) -> "Room | None":
        """The room this character is in, whether or not they lead it."""
        for room in self.rooms.values():
            if room.find(chara_id) is not None:
                return room
        return None

    def add_refusal(self, chara_id: int, headline: "bytes | None", limit: int) -> "int | None":
        """A reason to refuse 0x5800, or None to allow it."""
        if headline is None or not MIN_MEMBERS <= limit <= MAX_MEMBERS:
            return NG_ADD_BAD_SIZE
        if self.room_of(chara_id) is not None:
            return NG_ADD_ALREADY_IN_ROOM
        return None

    def open(self, leader_id: int, headline: bytes, limit: int,
             family: bytes, first: bytes) -> "Room":
        """Create the room and seat its leader. Callers check add_refusal first."""
        room = Room(leader_id, headline, limit)
        room.add(leader_id, family, first)
        self.rooms[leader_id] = room
        return room

    def join_refusal(self, chara_id: int, leader_id: int) -> "int | None":
        """A reason to refuse 0x5806, or None to allow it."""
        if self.room_of(chara_id) is not None:
            return NG_JOIN_ALREADY_IN_ROOM
        room = self.rooms.get(leader_id)
        if room is None:
            return NG_JOIN_NOT_FOUND
        if room.full():
            return NG_JOIN_FULL
        return None

    def part(self, chara_id: int) -> "Room | None":
        """Take this character out of whatever room they are in.

        Returns the room they left, already updated. ⚠️ A leader leaving takes
        the room with them only when they are the last one in it: 「リーダー以外
        に参加者がいる場合、残っている参加者の中から自動的にリーダーが選出され
        ます」 (p07_06). With one player those are the same event, but the rule
        is the manual's and the code follows it rather than the coincidence.
        """
        room = self.room_of(chara_id)
        if room is None:
            return None
        room.remove(chara_id)
        if not room.members:
            self.rooms.pop(room.leader_id, None)
        elif chara_id == room.leader_id:
            promoted = room.members[0]
            self.rooms.pop(room.leader_id, None)
            room.leader_id = promoted.chara_id
            self.rooms[room.leader_id] = room
        return room

    def summary(self) -> str:
        if not self.rooms:
            return "自主トレルーム なし"
        return " | ".join(room.summary() for room in self.rooms.values())


def ng_params(reason: int) -> bytes:
    """Every Ng and Error in the family: a single reason byte."""
    return struct.pack(">B", reason & 0xFF)


def notify_part_params(chara_id: int, leader_id: int, reason: int) -> bytes:
    """0x580D: charId u32, leaderId u32, reason u8."""
    return struct.pack(">IIB", chara_id, leader_id, reason & 0xFF)


def notify_chat_params(chara_id: int, family: bytes, first: bytes, text: bytes) -> bytes:
    """0x580F: charaId u32, two fixed-width names, then the counted line."""
    return (
        struct.pack(">I", chara_id)
        + family[:NAME_LEN].ljust(NAME_LEN, b"\x00")
        + first[:NAME_LEN].ljust(NAME_LEN, b"\x00")
        + _string(text)
    )


def notify_ready_params(chara_id: int, ready: bool) -> bytes:
    """0x5812: charaId u32, ready u8 — and 0 is the ready one, see READY_ON."""
    return struct.pack(">IB", chara_id, READY_ON if ready else READY_OFF)


def notify_team_params(chara_id: int, team: int) -> bytes:
    """0x5817: charaId u32, team u8."""
    return struct.pack(">IB", chara_id, team & 0xFF)
