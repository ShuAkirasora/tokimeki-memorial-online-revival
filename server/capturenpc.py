"""The 名簿: 0x4400's exchange, and who is on it.

    0x4400 MsgClQueryCaptureNpcList   -> 0x4401 MsgSvResultCaptureNpcList
                                      -> 0x4402 MsgSvErrorCaptureNpcList  (i8 reason)

⭐ WHAT THIS SCREEN IS, in the game's own words. The manual's staff page says of
the 保健の先生's ring item 「名簿」:

    「名簿」…既に登場している恋愛候補生の情報を見ることができます。

So the list is not a roster of players and not the whole cast: it is the
恋愛候補生 **who have already appeared** for this character, which is a fact this
server already keeps -- see `romance.Romance.on_stage` -- rather than one that
has to be invented to fill the message out.

⭐⭐ THE CLIENT SAYS THE SAME THING FROM A SECOND DIRECTION, and it was read
before the manual was: every sentence filed under 0x4402 in the error table is
about 恋愛候補生, and two of them name this very list --

    reason 3  恋愛候補生のリストを取得できませんでした。
    reason 4  恋愛候補生のＩＤリストが見つかりませんでした。   (marked 未使用)

⇒ 「ＮＰＣ情報参照」 in the menu table, 「名簿を見る」 on the tooltip, and
「恋愛候補生のＩＤリスト」 in the error table are three names for one thing.

⭐ THE LAYOUT IS READ OFF THE CLIENT'S OWN READER (Input_MsgSvResultCaptureNpcList
::deserialize at 0x8F9410), through the stream vtable's read slots, the same way
couple.py's and career.py's were:

    u16  nCaptureNpcNum          vt+0x28 -> +0x2C
    u32  captureNpcId[n]         vt+0x24 -> +0x04, stride 4

and the message's own dump (0x915490) prints exactly those two, with the count
as the array's length: `captureNpcId[%d]={%d,%d,...}`. ⚠️ Unlike the カップル
family, this one has NO Notify: count and rows travel together in 0x4401, so
there is nothing to page and nothing to push unasked.

⭐ THE ROW LIMIT IS READ, NOT GUESSED, and it lands exactly where the cast list
does: the count sits at +0x2C and the rows start at +0x04 with stride 4, so the
array holds (0x2C - 4) / 4 == 10 rows, and `capture_npc` has 10 rows, 1:0-1:9.
⚠️⚠️ There is no bounds check behind the count -- row 10 would be written over
the count field itself -- so CAPTURE_NPC_LIST_MAX is a ceiling to respect here,
not one the client will enforce.

⭐ WHAT A captureNpcId IS: an npcId of kind 1, i.e. `1 << 16 | rosterIndex`, the
same four bytes a spawn or a 0x6304 carries for the same character. The roster
index is the one every PC cell in romance.py already counts on -- PC[0x3900+i]
登場, PC[0x3920+i] 親密さ -- because `capture_npc` 1:0-1:4 is 天宮 春日 弥生
桜井 犬飼 in that order, which is the order romance.CANDIDATES is written in.
⚠️ The upper five rows (1:5-1:9 高峰 沢木 ？？？？ 佐名木 蓮見) have no events,
no placement scripts and no cells in this build, so nothing here can put them on
a list; they are why the array is ten long and the cast is five.

⚠️ WHERE THE DOOR IS. `menu_item` 17 ＮＰＣ情報参照 is type 0, which makes it a
0x6304 event request rather than a screen the client opens by itself, and the
one menu that carries it is the 保健先生's. What that event runs is the nurse's
own `c001`, 保科恋愛候補生紹介 -- a scenario that opens by reading PC[0x3900+i]
for all five candidates, which is the same question this message asks. See
script.MENU_ITEM_NPC_ROSTER for the pairing and for why it is an elimination
rather than a guess.

⚠️ NOTHING HERE IS MADE UP (inventions:skip -- this line says there is no entry
for this module in that ledger, rather than declaring one). The list is
`on_stage`, the ids are npcIds, the widths and the cap are the client's. The one thing this module chooses is which
refusal to send when there is no character to answer for, and both values it can
send are sentences the shipped error table already has (the ones NOT marked
未使用): 0 プレイヤー情報が不正です and 3 恋愛候補生のリストを取得できませんでした.
"""
from __future__ import annotations

import struct

MSG_CL_QUERY_CAPTURE_NPC_LIST = 0x4400
MSG_SV_RESULT_CAPTURE_NPC_LIST = 0x4401
MSG_SV_ERROR_CAPTURE_NPC_LIST = 0x4402

#: NPC kind 1 -- `capture_npc`. The same high half a spawn or a 0x6304 carries.
NPC_KIND_CAPTURE = 1

#: How many ids one 0x4401 may carry: (0x2C - 4) / 4, read off the deserializer
#: at 0x8F9410. ⚠️ The eleventh row would land on the count. See the docstring.
CAPTURE_NPC_LIST_MAX = 10

#: 「プレイヤー情報が不正です。」 -- no character to build a list for.
NG_NO_PLAYER = 0
#: 「恋愛候補生のリストを取得できませんでした。」 -- the list itself failed.
NG_NO_LIST = 3


def npc_id(roster_index: int) -> int:
    """The npcId of `capture_npc` 1:index, as the wire carries it."""
    return (NPC_KIND_CAPTURE << 16) | (roster_index & 0xFFFF)


def result_params(ids: "list[int]") -> bytes:
    """0x4401's body: u16 count then one u32 per id.

    ⚠️ Clipped at CAPTURE_NPC_LIST_MAX rather than trusted to the caller: the
    client has no bounds check, so a longer list would not be refused, it would
    be written over the count and read back as a different list.
    """
    kept = list(ids)[:CAPTURE_NPC_LIST_MAX]
    out = struct.pack(">H", len(kept))
    for value in kept:
        out += struct.pack(">I", value & 0xFFFFFFFF)
    return out


def error_params(reason: int = NG_NO_LIST) -> bytes:
    """0x4402's body: i8 reason. Signed, like every other Error in this range."""
    return struct.pack(">b", max(-0x80, min(0x7F, reason)))


def describe(body: bytes) -> str:
    """Decode a 0x4401 body back for the log.

    Decoded out of the bytes rather than printed off the records, for couple.py's
    reason: a log that does not say what actually went out cannot be used to read
    the screen.
    """
    if len(body) < 2:
        return "(short)"
    count = struct.unpack_from(">H", body, 0)[0]
    parts = []
    for i in range(count):
        off = 2 + i * 4
        if off + 4 > len(body):
            parts.append("(truncated)")
            break
        value = struct.unpack_from(">I", body, off)[0]
        parts.append(f"{value >> 16}:{value & 0xFFFF}")
    return f"{count} 名: " + " ".join(parts) if parts else "0 名"
