"""チャットルーム: the temporary group the 看板 window's second choice makes.

Fifteen messages, 0x4C80-0x4C8E. Open a room, look at somebody's from outside,
join it, talk in it, leave it.

⭐⭐⭐ THE WINDOW IS THE SPLITTER (measured, round 293), and this is its middle
choice. The toolbar's fifth icon opens 看板作成, and its 看板の種類 dropdown
picks which family ［作成］ sends:

    お知らせ        -> 0x4B00  billboard.py
    チャットルーム  -> 0x4C80  this file
    自主トレ        -> 0x5800  trainingroom.py

⭐⭐ Selecting チャットルーム lights the 参加人数 dropdown beside it that
instant, at 2 -- which is the window saying what the shape dump says, that
0x4C80 carries a 見出し and a cap where 0x4B00 carries only the 見出し. The
press was captured as

    0x4c80 seq=13 params=0006 52 32 39 33 42 00 02
                             ^^^^ u16 = 6      "R293B\\0"  ^^ limit

byte for byte 0x5800's body. The client's own message dumper prints it as
「MsgClRequestChatroomAdd(0x4C80), name[6]={R293B}limit=2」.

⭐ So this family and 自主トレ are the same subsystem wearing two hats, and
almost everything below is trainingroom.py with the club-battle half removed:
no teams, no 準備ＯＫ, no 開始, no kick. What is left is a roster and a line of
chat. ⚠️ The two rules 0x580C cost a round each are NOT assumed to carry over
-- see roster_params.

THE DOOR IN, stated outright by the manual (`p05_08`, the 行動アイコン list):

    「チャット募集中」
    チャットルームを作成したプレイヤーのマップキャラに表示されます。
    このアイコンを右クリックすると内容を見ることができ、
    ［参加する］を押すとチャットに参加できます。

⇒ right-click the icon over the owner's head (0x4C83), then ［参加する］
(0x4C86). ⚠️ RIGHT-click: a left click falls through to the map and walks the
player instead, which is how the 看板 icon behaved when it was measured
(round 294) and how マップオブジェクト behaved the round before.

WHAT THE MANUAL FIXES
---------------------
`p05_02`, about the 看板 button, and it covers both rooms in one sentence:

    「チャットルーム」や「自主トレルーム」を作成する際は、
    参加できる人数を２〜２０人の間で選択する必要があります。

⇒ MIN_MEMBERS/MAX_MEMBERS below are stated rather than read off a dropdown,
and the client agrees from a third direction: its 0x4C8A roster array holds
exactly twenty rows (see MAX_ROWS).

`p05_05`, in the list of chat kinds:

    「ルームチャット」…メインメニュー内の「看板」で２〜２０人の一時的な
    グループを作成して行うチャットです。チャットが終了すると、このグループ
    は解散されます。

⇒ a room is temporary and unsaved, like the 自主トレ room and the 看板.

Message table
-------------
Shapes from the frozen shape dump, field names from each class's own dump
function, buffer sizes from the client's deserializers, refusals from
`error_message.bin`.

    0x4C80 MsgClRequestChatroomAdd    name[u16], limit u8
    0x4C81 MsgSvOkChatroomAdd         ()
    0x4C82 MsgSvNgChatroomAdd         reason u8
    0x4C83 MsgClRequestChatroomInfo   ownerId u32
    0x4C84 MsgSvOkChatroomInfo        ownerId u32, name[u16], limit u8, entry u8
    0x4C85 MsgSvNgChatroomInfo        reason u8
    0x4C86 MsgClRequestChatroomJoin   ownerId u32
    0x4C87 MsgSvOkChatroomJoin        ownerId u32, name[u16], limit u8
    0x4C88 MsgSvNgChatroomJoin        reason u8
    0x4C89 MsgClCastChatroomPart      ()
    0x4C8A MsgSvNotifyChatroomJoin    namelist[u16]{charaId u32, name[u16]}
    0x4C8B MsgSvNotifyChatroomPart    charId u32
    0x4C8C MsgClCastChatroomChat      utterance[u16]
    0x4C8D MsgSvNotifyChatroomChat    senderId u32, name[u16], utterance[u16]
    0x4C8E MsgSvErrorChatroomChat     reason u8

⚠️ There is no room id: a character owns at most one room, so 0x4C83 and 0x4C86
name an **ownerId** and everything sent from inside (Part, Chat) is empty of
address. That is 自主トレ's leaderId arrangement under another field name, and
it has one consequence worth writing down -- see Board.part.

⚠️ ONE DIFFERENCE FROM 自主トレ THAT IS NOT COSMETIC: 0x4C84 ends in a single
`entry`, not in the two side counts 0x5804 carries. There are no teams here, so
the 看板 outside shows one number and it is the whole room.

What the client's own readers fix
---------------------------------
Four of these carry strings, and none of the readers bounds-checks one: each
pulls a u16 off the wire and hands it straight to the byte copier, so the
buffer is the gap between where the string lands and where its own length field
was stored, and keeping inside it is this end's job. Read off the
deserializers:

* 0x4C84 (0x8D5AC0) and 0x4C87 (0x8D5CC0): headline to obj+0x08, its length at
  obj+0x4A ⇒ **66 bytes**. ⭐ 0x5804's reader (0x8D75B0) is the same code with
  one more byte on the end, so 自主トレ's 見出し has the same room.
* 0x4C8A (0x8D5E80): a count at obj+0x234, then rows from obj+0x04 stepping
  0x1C. Per row the charaId lands at row+0x00 and the name at row+0x04 with its
  length at row+0x1A ⇒ **22 bytes** of name. ⭐⭐ And the count is compared
  against nothing: (0x234 - 0x04) / 0x1C = **20 rows**, which is where MAX_ROWS
  comes from and which is the manual's 「２〜２０人」 arriving from the client
  side.
* 0x4C8D: its deserializer **is** 0x8D6230, the very function 0x4901 normal chat
  uses -- not a lookalike, the same address off both vtables. ⇒ its two strings
  are clamped to chat.NAME_MAX and chat.TEXT_MAX because they are literally the
  same buffers, and chat.notify_params packs this message unchanged. (0x5006
  ツーショットチャット was admitted to that set the same way.)

Refusals (`error_message.bin`; the reason *is* the index within each message's
own run)
-----------------------------------------------------------------------------
0x4C82 作成:  2 参加許容人数もしくは見出しテキストのサイズが不正です。
              3 既に別のチャットルームに入室していますので、…作成できません。
              5 今の状態では、チャットルームを作成することはできません。
  ⭐ 2 is a REAL sentence here, unlike the 0x4B02 it sits beside -- this family
  has a cap to get wrong, so it has a sentence for getting it wrong. 4 is
  marked 未使用; 6/7/8/10 are 「送信に失敗」「取得に失敗」 server faults this
  end does not have; 9 「現在、ルームチャットを行うことができません」 is an
  operator's switch, and inventing an occasion for it would be inventing policy.

0x4C85 参照:  2 チャットルーム情報の取得に失敗しました。   ← no such room
              4 キャラクター情報の取得に失敗しました。     ← no such character

0x4C88 参加:  2 既にチャットルームに入室していますので、…入室することはできません。
              3 今の状態では、チャットルームを入ることはできません。
              4 チャットルーム情報の取得に失敗しました。   ← the room is gone
              9 参加できません。選択されたチャットルームは満員です。
             10 現在、別の機能を実行していますので、参加することはできません。
  ⭐ 10 is the sentence this project has wanted at four other doors: it names
  「別の機能」 outright, so a character sitting in a 自主トレルーム can be told
  why rather than being handed 「今の状態では」.

0x4C8E 発言:  2 チャットルーム情報の取得に失敗しました。   ← said outside a room
  6 「現在、ルームチャットを行うことができません」 is the same switch as
  0x4C82's 9 and is not sent either.

⚠️ 満員 (0x4C88 reason 9) is probably unreachable from a real client for the
same reason 0x5808's was: the 看板 window greys its own ［参加する］ out once
参加者 reaches 定員, and nothing was sent when that was measured on the 自主トレ
side. It is answered anyway -- this end does not get to assume the client is
the only thing that will ever connect.
"""
from __future__ import annotations

import struct

import chat
import trainingroom

MSG_CL_REQUEST_ADD = 0x4C80
MSG_SV_OK_ADD = 0x4C81
MSG_SV_NG_ADD = 0x4C82
MSG_CL_REQUEST_INFO = 0x4C83
MSG_SV_OK_INFO = 0x4C84
MSG_SV_NG_INFO = 0x4C85
MSG_CL_REQUEST_JOIN = 0x4C86
MSG_SV_OK_JOIN = 0x4C87
MSG_SV_NG_JOIN = 0x4C88
MSG_CL_CAST_PART = 0x4C89
MSG_SV_NOTIFY_JOIN = 0x4C8A
MSG_SV_NOTIFY_PART = 0x4C8B
MSG_CL_CAST_CHAT = 0x4C8C
MSG_SV_NOTIFY_CHAT = 0x4C8D
MSG_SV_ERROR_CHAT = 0x4C8E

# Reason codes, named for what the sentence says rather than for why it is sent.
NG_ADD_BAD_SIZE = 2
NG_ADD_ALREADY_IN_ROOM = 3
NG_ADD_CANNOT_NOW = 5
NG_ADD_FORBIDDEN = 9  # not sent; see the module docstring

NG_INFO_NOT_FOUND = 2
NG_INFO_BAD_CHARACTER = 4

NG_JOIN_ALREADY_IN_ROOM = 2
NG_JOIN_CANNOT_NOW = 3
NG_JOIN_NOT_FOUND = 4
NG_JOIN_FULL = 9
NG_JOIN_OTHER_FEATURE = 10

ERROR_CHAT_NO_ROOM = 2
ERROR_CHAT_FORBIDDEN = 6  # not sent, same switch as NG_ADD_FORBIDDEN

# 「参加できる人数を２〜２０人の間で選択する必要があります」 (p05_02), said of
# this room and the 自主トレ one together.
MIN_MEMBERS = 2
MAX_MEMBERS = 20

# The client's 0x4C8A roster array: twenty rows, and the count it is given is
# compared against nothing. See the module docstring for where the twenty comes
# from. A 21st row would land on the count field itself.
MAX_ROWS = 20

# Capacities of the client's own receive buffers, likewise from its readers.
HEADLINE_MAX = 66
ROSTER_NAME_MAX = 22


def _counted(text: str, limit: int) -> bytes:
    """A counted string clipped to one of those buffers, terminator included.

    Cut by character before encoding, so a double-byte pair is never halved --
    the care chat.clip takes, for the same reason. The count includes the NUL
    the way every counted string on this wire does.
    """
    return trainingroom.counted_string(chat.clip(text, limit - 1))


def parse_add(params: bytes) -> "tuple[bytes, int] | None":
    """0x4C80 -> ``(headline, limit)``, or None if the body is not that shape."""
    return trainingroom.parse_add(params)


def parse_owner(params: bytes) -> "int | None":
    """The ownerId 0x4C83 and 0x4C86 name, or None if the body is short."""
    if len(params) < 4:
        return None
    return struct.unpack_from(">I", params, 0)[0]


def ng_params(reason: int) -> bytes:
    """Every Ng and Error in the family: a single reason byte."""
    return struct.pack(">B", reason & 0xFF)


def notify_part_params(chara_id: int) -> bytes:
    """0x4C8B: one charaId and nothing else.

    ⚠️ Narrower than 0x580D, which carries a leaderId and a reason beside it.
    There is no 「理由：」 sentence to pick here and no way to say whose room
    this was about, which is what Board.part has to work around.
    """
    return struct.pack(">I", chara_id)


class Member:
    """One character sitting in a room: an id and the name a roster row draws."""

    def __init__(self, chara_id: int, name: str) -> None:
        self.chara_id = chara_id
        self.name = name

    def entry(self) -> bytes:
        """One row of 0x4C8A: charaId u32, then the counted name."""
        return struct.pack(">I", self.chara_id) + _counted(
            self.name, ROSTER_NAME_MAX
        )


class Room:
    """One チャットルーム: its 見出し, its cap, and who is in it.

    The owner is whoever created it, and ``ownerId`` is how the two messages
    from outside name the room. Nothing sent from inside names it at all.
    """

    def __init__(self, owner_id: int, headline: bytes, limit: int) -> None:
        self.owner_id = owner_id
        self.headline = headline
        self.limit = limit
        self.members: "list[Member]" = []

    def find(self, chara_id: int) -> "Member | None":
        for member in self.members:
            if member.chara_id == chara_id:
                return member
        return None

    def full(self) -> bool:
        """0x4C88 reason 9's condition, against the room's one and only cap."""
        return len(self.members) >= self.limit

    def add(self, chara_id: int, name: str) -> "Member":
        member = Member(chara_id, name)
        self.members.append(member)
        return member

    def remove(self, chara_id: int) -> bool:
        member = self.find(chara_id)
        if member is None:
            return False
        self.members.remove(member)
        return True

    def headline_params(self) -> bytes:
        """ownerId and the 見出し, the head both 0x4C84 and 0x4C87 open with."""
        return struct.pack(">I", self.owner_id) + _counted(
            self.headline.decode("cp932", "replace"), HEADLINE_MAX
        )

    def info_params(self) -> bytes:
        """0x4C84: the head, the cap, and how many are in there now.

        ⚠️ ``entry`` is the whole room. 0x5804 spends its last two bytes on the
        two sides and the 看板 outside adds them up; here there is one number
        and it is already the sum.
        """
        return self.headline_params() + struct.pack(
            ">BB", self.limit & 0xFF, min(0xFF, len(self.members))
        )

    def join_params(self) -> bytes:
        """0x4C87: the same head and the cap, without the count."""
        return self.headline_params() + struct.pack(">B", self.limit & 0xFF)

    def roster_rows(self, members: "list[Member]") -> bytes:
        """0x4C8A's body for exactly these rows: a u16 count, then the rows.

        Clipped to MAX_ROWS because the client's array is that long and it
        checks nothing. The cap cannot bite while MAX_MEMBERS is what the
        manual says it is -- it is here so that the two numbers have to be
        wrong together rather than separately.
        """
        rows = members[:MAX_ROWS]
        return struct.pack(">H", len(rows)) + b"".join(m.entry() for m in rows)

    def roster_params(self, without: "int | None" = None) -> bytes:
        """0x4C8A: the roster, optionally with one recipient left out of it.

        Two rules came over from 0x580C, the same message one subsystem over
        (measured round 67), and round 295 checked both on a real client here:

        * the lists are **merged in, not swapped in** ✅ carries over -- which
          is why everybody already seated is sent the arriving row ALONE;
        * the client seats **itself** ⚠️ carries over **only for the client that
          created the room**. See _cr_seat in the session for the two screens
          that separate those, and for why ``without`` is not always the
          recipient.
        """
        return self.roster_rows(
            [m for m in self.members if m.chara_id != without]
        )

    def summary(self) -> str:
        headline = self.headline.decode("cp932", "replace")
        return (f"「{headline}」 owner={self.owner_id:#x} "
                f"{len(self.members)}/{self.limit}名")


class Board:
    """Every チャットルーム currently open, keyed by its owner.

    ⚠️ Held per port by the server rather than by a session, like the room board
    and the 看板 board: what is in here is reached from connections other than
    the one that made it.

    Not persisted. 「チャットが終了すると、このグループは解散されます」
    (p05_05) -- a room lives as long as somebody is in it and no longer.
    """

    def __init__(self) -> None:
        self.rooms: "dict[int, Room]" = {}

    def room_of(self, chara_id: int) -> "Room | None":
        """The room this character is in, whether or not they own it."""
        for room in self.rooms.values():
            if room.find(chara_id) is not None:
                return room
        return None

    def add_refusal(
        self, chara_id: int, headline: "bytes | None", limit: int
    ) -> "int | None":
        """A reason to refuse 0x4C80, or None to allow it."""
        if headline is None or not MIN_MEMBERS <= limit <= MAX_MEMBERS:
            return NG_ADD_BAD_SIZE
        if self.room_of(chara_id) is not None:
            return NG_ADD_ALREADY_IN_ROOM
        return None

    def open(self, owner_id: int, headline: bytes, limit: int, name: str) -> "Room":
        """Create the room and seat its owner. Callers check add_refusal first.

        ⭐ The owner is a participant, not a host standing outside: the 看板's
        「参加者Ｎ名」 counts them, which is how the 自主トレ board behaved when
        its counts were measured against a room holding only its leader.
        """
        room = Room(owner_id, headline, limit)
        room.add(owner_id, name)
        self.rooms[owner_id] = room
        return room

    def join_refusal(self, chara_id: int, owner_id: int) -> "int | None":
        """A reason to refuse 0x4C86, or None to allow it."""
        if self.room_of(chara_id) is not None:
            return NG_JOIN_ALREADY_IN_ROOM
        room = self.rooms.get(owner_id)
        if room is None:
            return NG_JOIN_NOT_FOUND
        if room.full():
            return NG_JOIN_FULL
        return None

    def part(self, chara_id: int) -> "Room | None":
        """Take this character out of whatever room they are in.

        Returns the room they left, already updated.

        ⚠️ INVENTED, and it is the one decision in this file that had to be
        made without anything to read: what happens to a room whose **owner**
        leaves. The manual promotes somebody in both places it discusses the
        question -- 「残っている参加者の中から自動的にリーダーが選出されます」
        for the 自主トレ room, and the 仲良しグループ rules for that -- but it
        says nothing at all here, and 0x4C8B cannot say it: it carries one
        charaId, where 0x580D at least carries the room's leaderId.

        This end promotes, for two reasons that are about this family rather
        than about the sibling:

        * ⭐ promotion is invisible from inside. Nothing sent from within a room
          names it: Part is empty and Chat is one string. So the people left
          behind never have to be told, and their windows keep working. A
          disband would leave them holding a window whose next line comes back
          as 0x4C8E.
        * the icon is the only door, and moving it to whoever is still in there
          keeps the room joinable, which is what a room with people in it is
          for.

        ⚠️ What would overturn it: a capture of the real client after an owner
        walks out -- if the remaining window closes itself, the client already
        believes the room is gone and this end is disagreeing with it.
        """
        room = self.room_of(chara_id)
        if room is None:
            return None
        room.remove(chara_id)
        if not room.members:
            self.rooms.pop(room.owner_id, None)
        elif chara_id == room.owner_id:
            promoted = room.members[0]
            self.rooms.pop(room.owner_id, None)
            room.owner_id = promoted.chara_id
            self.rooms[room.owner_id] = room
        return room

    def summary(self) -> str:
        if not self.rooms:
            return "チャットルーム なし"
        return " | ".join(room.summary() for room in self.rooms.values())
