"""看板（お知らせ）: the notice a character stands under, for anyone to read.

Nine messages, 0x4B00-0x4B08. Put one up, take it down, read somebody else's.
There is no room and no roster here — this is the smallest of the three things
the 看板作成 window can make, and the only one with nothing to join.

⭐⭐⭐ THE WINDOW IS THE SPLITTER (measured, round 293). The toolbar's fifth
icon opens 看板作成, and its 看板の種類 dropdown picks which family the ［作成］
button sends:

    お知らせ        -> 0x4B00  this file
    チャットルーム  -> 0x4C80  chatroom.py
    自主トレ        -> 0x5800  trainingroom.py

⭐⭐ お知らせ is the dropdown's factory setting, and with it selected the
参加人数 dropdown beside it is **greyed out and empty** — which is the window
saying the same thing the shape dump says: 0x4B00 carries a 見出し and no cap.
Switching the dropdown to チャットルーム lights 参加人数 up at 2 that instant.
The press was captured as

    0x4b00 seq=12 params=0006 52 32 39 33 41 00
                             ^^^^ u16 = 6      "R293A\\0"

so the count includes the terminator, the same as every other counted string on
this wire. The client's own message dumper prints it as
「MsgClRequestBillboardAdd(0x4b00), name[6]={R293A}」.

⚠️ Until that press this family was on the 「never seen it fly」 list, and the
list was right at the time: nothing here answered 0x4B00, so the client had
never been given a reason to send a second one. What the press settled is that
the family is alive in this build rather than shipped dead — a refusal sent
back to it went to its own BillboardMessageProcedure, so both directions work.

⭐⭐⭐ THE WINDOW IS THE BOARD (measured, round 294, and it decides what the
refusals below can ever be for). 0x4B01 carries nothing, and the moment it
arrives the 看板作成 window turns into a 「お知らせ看板」 window holding the
見出し and one ［閉じる］ button. That window is not a receipt:

* it stays up the whole time the board is up, and while it is up the toolbar's
  看板 icon opens nothing (it only shows its tooltip);
* ［閉じる］ sends 0x4B03 — closing the window IS taking the board down;
* the owner never sees the icon over their own head, so this window is the
  only 0x4B03 the client has.

⇒ ⚠️ A real client therefore never sends a second 0x4B00 while one is up.
The 「already holding one」 refusal below is a backstop, not a path anybody
walks, and no refusal in this family has been seen drawn on screen.

⭐ How a reader gets in: RIGHT-click the 看板 icon over the owner's head. A
left click falls through to the map and walks the player instead, and the
six-icon ring that right-clicking the *person* opens has no 看板 in it.

Message table
-------------
Shapes from the frozen shape dump, field names from each class's own dump
function, refusals from `error_message.bin`. No disassembly.

    0x4B00 MsgClRequestBillboardAdd    name[u16]
    0x4B01 MsgSvOkBillboardAdd         ()
    0x4B02 MsgSvNgBillboardAdd         reason u8
    0x4B03 MsgClRequestBillboardDel    ()
    0x4B04 MsgSvOkBillboardDel         ()
    0x4B05 MsgSvNgBillboardDel         reason u8
    0x4B06 MsgClRequestBillboardInfo   ownerId u32
    0x4B07 MsgSvOkBillboardInfo        name[u16]
    0x4B08 MsgSvNgBillboardInfo        reason u8

⚠️ 0x4B03 and 0x4B06 are why this needs no id of its own. Del is empty — a
character has at most one 看板, so there is nothing to name — and Info names an
**ownerId**, which is the field name the client's dumper prints. So a 看板 is
addressed by whose head it is over, exactly the way a 自主トレルーム is
addressed by its leader.

⭐ What puts that ownerId in a reader's hands is the icon: `p05_08` says the
看板 icon 「看板を出しているプレイヤーのマップキャラに表示されます」, and the
map character it is drawn on is the one a reader right-clicks. That is the
whole entry path, and it is why the icon is not decoration here — without it
0x4B06 has nothing to name.

Refusals (`error_message.bin`, and the reason *is* the index within each
message's own run)
------------------------------------------------------------------------
0x4B02 看板作成, seven sentences:

     0  未使用: エラーなし
     1  未使用: パラメータが不正です。
     2  未使用: キャラクターデータが不正です。
     3  今の状態では、看板を立てることはできません。
     4  サーバーエラーが発生しました。看板作成情報の送信に失敗しました。
     5  現在、看板作成が禁止されています。
     6  未使用: 未定義のエラーが発生しました。

0x4B05 看板削除: 3 今の状態では、看板を削除することはできません。/
4 サーバーエラー: 削除情報の送信に失敗。 0, 1, 2 and 5 are 未使用.

0x4B08 看板参照: 2 キャラクターデータが不正です。/ 3 今の状態では、看板の内容
を参照することはできません。 ⚠️ 2 is a **real** sentence here, unlike the 2 in
the other two messages — this family does not have one 未使用 prefix length.

⚠️ 「パラメータが不正です」 is marked 未使用 in all three, so a malformed body
cannot be answered with the sentence written for it. Reason 3 carries the
malformed cases as well: 「今の状態では」 is the only sendable sentence that
does not claim something this end has not checked.

⛔️ Reason 5 (「現在、看板作成が禁止されています」) is a switch nothing here
turns on. It reads as an operator's 「no boards today」, and inventing an
occasion for it would be inventing policy rather than restoring it.

What is NOT enforced
--------------------
No length cap on the 見出し. Nothing on hand states one — the window's own
field is not a dropdown, so unlike 参加人数 it enumerates nothing — and this
end will not make one up. The text is length-checked only against the body that
carried it.
"""
from __future__ import annotations

import struct

import trainingroom

MSG_CL_REQUEST_ADD = 0x4B00
MSG_SV_OK_ADD = 0x4B01
MSG_SV_NG_ADD = 0x4B02
MSG_CL_REQUEST_DEL = 0x4B03
MSG_SV_OK_DEL = 0x4B04
MSG_SV_NG_DEL = 0x4B05
MSG_CL_REQUEST_INFO = 0x4B06
MSG_SV_OK_INFO = 0x4B07
MSG_SV_NG_INFO = 0x4B08

# Reason codes, named for what the sentence says rather than for why we send it.
NG_ADD_CANNOT_NOW = 3
NG_ADD_SEND_FAILED = 4  # not sent: nothing here fails halfway through an add
NG_ADD_FORBIDDEN = 5  # not sent; see the module docstring

NG_DEL_CANNOT_NOW = 3
NG_DEL_SEND_FAILED = 4  # not sent, same reason as NG_ADD_SEND_FAILED

NG_INFO_BAD_CHARACTER = 2
NG_INFO_CANNOT_NOW = 3


def parse_add(params: bytes) -> "bytes | None":
    """0x4B00 -> the 見出し, or None if the body is not a counted string.

    The same primitive the rest of this wire's strings use, so it is read with
    the same reader rather than a second copy of it.
    """
    read = trainingroom.parse_string(params)
    return None if read is None else read[0]


def parse_owner(params: bytes) -> "int | None":
    """The ownerId 0x4B06 names, or None if the body is short."""
    if len(params) < 4:
        return None
    return struct.unpack_from(">I", params, 0)[0]


def info_params(headline: bytes) -> bytes:
    """0x4B07: the 見出し and nothing else.

    ⚠️ It does not repeat the ownerId the request named. The reader asked about
    one character and gets one line back, so the reply is only ever about the
    request it is answering — which is also why this family can get away with
    having no id.
    """
    return trainingroom.counted_string(headline)


def ng_params(reason: int) -> bytes:
    """Every Ng in the family: a single reason byte."""
    return struct.pack(">B", reason & 0xFF)


class Sign:
    """One 看板: whose it is and what it says."""

    def __init__(self, owner_id: int, headline: bytes) -> None:
        self.owner_id = owner_id
        self.headline = headline

    def summary(self) -> str:
        headline = self.headline.decode("cp932", "replace")
        return f"「{headline}」 owner={self.owner_id:#x}"


class Board:
    """Every 看板 currently up, keyed by the character standing under it.

    ⚠️ Held per port by the server rather than by a session, like the room
    board and for the same reason: a 看板 is a thing other players look at, so
    it has to be reachable from a connection other than the one that made it.

    Not persisted. A 看板 is up only while its owner is logged in — the same
    rule the room board follows, and p07_06 states it for the 看板 in so many
    words: 「ゲームを中断（キャラクター選択画面に戻る）しても、退出すること
    になります」.
    """

    def __init__(self) -> None:
        self.signs: "dict[int, Sign]" = {}

    def sign_of(self, chara_id: int) -> "Sign | None":
        return self.signs.get(chara_id)

    def add_refusal(self, chara_id: int, headline: "bytes | None") -> "int | None":
        """A reason to refuse 0x4B00, or None to allow it.

        ⚠️ 「already holding one」 is the interesting case and it is refused
        rather than quietly replaced: the dict is keyed by owner, so an
        overwrite would change what a reader sees with nothing on screen having
        said so. tmo.exe carries 「他の行動中は看板を作成できません」 as its own
        string, so the client says no to some of these before they ever get
        here — which is why this end sees the second press only when something
        has already gone wrong.
        """
        if headline is None:
            return NG_ADD_CANNOT_NOW
        if chara_id in self.signs:
            return NG_ADD_CANNOT_NOW
        return None

    def put_up(self, owner_id: int, headline: bytes) -> "Sign":
        """Raise the 看板. Callers check add_refusal first."""
        sign = Sign(owner_id, headline)
        self.signs[owner_id] = sign
        return sign

    def take_down(self, chara_id: int) -> "Sign | None":
        """Drop this character's 看板, returning it, or None if there was none."""
        return self.signs.pop(chara_id, None)

    def summary(self) -> str:
        if not self.signs:
            return "看板 なし"
        return " | ".join(sign.summary() for sign in self.signs.values())
