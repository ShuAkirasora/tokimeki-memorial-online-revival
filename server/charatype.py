"""体型変更: 0x5900's exchange, and the u16 the character record has always had.

    0x5900 MsgClRequestCharaTypeChange (u16 charatype)
        -> 0x5901 MsgSvOkRequestCharaTypeChange   (empty)
        -> 0x5902 MsgSvNgRequestCharaTypeChange   (u8 reason)
        -> 0x5903 MsgSvNotifyCharaTypeChange      (u32 charaId, u16 charatype)

⭐ WHERE THE DOOR IS. `menu_item` 16 体型変更, and it hangs off **the 教頭** --
not off the player's own menu. Every NPC who has a function of her own carries
it as her `c001`, which is 入退部 for a キャプテン, 恋愛候補生紹介 for the
保健の先生 and this for the 教頭 (see script.py's NPC_OWN_EVENT_ID). The
predicate at +0x08 is 0x6FC3DE (`!0x6FFE31(mgr+8)`), the same shape and the
same stretch of code as 14 同好会 (0x6FC37E) and 15 多目的室 (0x6FC3AE), both of
which have been walked to on a real client; it is not one of the 0x9C1ACD
constants that are false for every build. Behind it:

    menu_item 16 -> 動作 0x6FD7B9 -> 0x6F5ACD opens the list window
      -> the button reads the selection out of the control at +0xa4 (0x4F16D6)
        -> 0x6F5CF3(charatype) -> 0x6B2BC5 puts up the 体型変更確認 box
          -> each button news an action 0x6ACAF5(charatype)
            -> vt 0xBCD5A4's builder 0x6AF2EB -> the ordinary delivery door

and that box takes its four lines out of `msg_text` by id, which is what nails
the chain down: 779 体型変更確認, 780 体型を変更してよろしいですか？,
781 体型を変更します, 782 体型を変更しません. ⭐ On a real client the ring item's
tooltip and the window are `win_text` 406 体型変更 and 407 変更可能な体型, the
confirmation box says 779 and 780 word for word, and the result box that follows
a successful 0x5901 is `msg_text` 783 体型変更 + 784 登録しました！.

⭐ THE SHAPES ARE READ OFF THE CLIENT'S OWN READERS, all four:

  * Input_MsgClRequestCharaTypeChange::deserialize (0x8DB8E0) makes exactly one
    call, through the stream vtable's +0x28 slot -- u16 -- into the message at
    +4. The body is two bytes and nothing else.
  * Input_MsgSvOkRequestCharaTypeChange::deserialize (0x8CB9A0) is `xor eax,eax;
    ret 8`: it reads nothing, so the Ok is empty.
  * Input_MsgSvNgRequestCharaTypeChange::deserialize (0x8D84A0) reads one byte
    through +0x1C (int8_t) -- a reason, and see below for why it is never sent.
  * Input_MsgSvNotifyCharaTypeChange::deserialize (0x8F1840) reads u32 through
    +0x24 into +4 and u16 through +0x28 into +8: charaId then charatype, six
    bytes.

⭐ WHAT THE VALUE IS. `charatype` is `chara_body_type`, the three-row IdBn table
(標準 / がっちり / 華奢), and NOT `chara_type.bin`, however much the field name
in the create message suggests otherwise -- the create block's last u16 carries
it and this is the message that finally changes it. ⚠️ The only two columns the
client reads are +0x13 and +0x24 (0x7FDCA2 and 0x7FDC7C, picked by an argument
that is 0 or 1), and in this build's data both spell the rows 標準 / 長身 / 小柄,
so those are the words on the screen rather than the first column's.

⭐⭐ WHERE IT SHOWS: the full-length 立ち絵 behind 生徒情報 →［容 姿］, which is a
different drawing for each of the three rows -- 長身 with a hand on the hip,
小柄 with a hand at the chest, 標準 with both arms down -- and it changes on the
spot, with no relog in between, so this message reaches the living character
rather than only the saved one. ⚠️ Two places do NOT redraw: the map's ちび
character, because 0x480F carries sex and the sixteen looks/accessory slots and
no charaType at all (which is exactly why 0x5903 has to exist), and the card on
the character-select screen. ⚠️⚠️ And whether anybody ELSE ever sees it is not
measured: the PC menu a player opens on a peer has no 容姿 of its own, so the
only candidate left is ツーショット, where two 立ち絵 share a screen.

⚠️ NO VALIDATION, and no clamping either. The list the player picks from is
built by the client out of that same three-row table, so 0/1/2 is all that can
arrive; a value outside it would mean something ahead of this misread the
stream, and storing what came keeps that visible instead of hiding it behind a
silent 0. The width is the record's own u16 and that is the only thing enforced.

⚠️⚠️ THE Ng SIDE IS NOT A CHANNEL, same as 0x4314. `0x5902` has three rows and
two of them open with the developers' 未使用 marker -- a marker that is part of
the string and not a switch, so a client handed one draws it, colons and all.
The one row without it, reason 0, is
「サーバーエラーが発生しました。体型の変更に失敗しました。」, which is what it
says it is: an error, not an answer. So this end sends it only for the two
states that really are errors -- no character to write to, and a body too short
to have come from the client's two-byte reader -- neither of which a playing
client can reach, and never as a way of saying "that body is not allowed".

⚠️ NOTHING HERE IS MADE UP (inventions:skip -- this line says there is no entry
for this module in that ledger, rather than declaring one). The widths are the
client's readers', the value space is the client's table, the door is the
client's own menu item.
"""
from __future__ import annotations

import struct

MSG_CL_REQUEST_CHARA_TYPE_CHANGE = 0x5900
MSG_SV_OK_REQUEST_CHARA_TYPE_CHANGE = 0x5901
MSG_SV_NG_REQUEST_CHARA_TYPE_CHANGE = 0x5902
MSG_SV_NOTIFY_CHARA_TYPE_CHANGE = 0x5903

#: 0x5902's only row that is not marked 未使用 by the developers, and the
#: docstring says why nothing else may send it.
NG_NO_CHARACTER = 0

#: `chara_body_type.bin`, in table order. The first spelling is the column the
#: client never reads, kept here because it is what the table calls the row; the
#: second is what both of the columns it does read say, i.e. what a player sees.
BODY_TYPES = {
    0: ("標準", "標準"),
    1: ("がっちり", "長身"),
    2: ("華奢", "小柄"),
}


def parse(params: bytes) -> int:
    """The body type out of a 0x5900 body: one u16.

    ⚠️ A short body raises rather than defaulting to 0: the client's reader
    takes exactly two bytes, so anything shorter did not come from it.
    """
    return struct.unpack_from(">H", bytes(params), 0)[0]


def ng_params(reason: int = NG_NO_CHARACTER) -> bytes:
    """0x5902's body: one reason byte."""
    return struct.pack(">B", reason & 0xFF)


def notify_params(chara_id: int, body_type: int) -> bytes:
    """0x5903's body: u32 charaId then u16 charatype, six bytes."""
    return struct.pack(">IH", chara_id & 0xFFFFFFFF, body_type & 0xFFFF)


def describe(body_type: int) -> str:
    """What went into the record, for the log."""
    names = BODY_TYPES.get(body_type)
    return f"{body_type} ({names[1]})" if names else f"{body_type} (not in the table)"
