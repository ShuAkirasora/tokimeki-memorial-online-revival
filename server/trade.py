"""アイテムトレード: the PC 交流メニュー's sixth icon and the window behind it.

Right-click another player, pick 「トレード」, and the client sends one u32. That
much was measured in round 151, together with the other three icons; what it got
back until now was a refusal, because a whole subsystem is not a message. This
is the subsystem.

WHAT THE RULE IS -- and it is the manual's, not ours
----------------------------------------------------
`manual/p05_05` section 5 「アイテム交換」 writes it out in three sentences:

    アイテム交換は、両者が交換するアイテムを出し合った後、両者が了承すること
    で成立します。（一方がＯＫしただけでは成立しません）
    また、どちらか一方がアイテムを出さなくても、両者が了承すれば交換が成立
    しますので、他の生徒にアイテムをプレゼントすることもできます。

So: both tables are filled, both sides confirm, and only then does anything
move. One side confirming is not enough, and an empty table is legal -- which is
how a player makes a present. Every one of those clauses is enforced below.

⭐ And the same page is why this family matters beyond itself: `manual/p05_12`
says a カップル is made by 「カップルアイテムを交換する」 -- メモリアルリング for
the boy, ときめきリング for the girl. トレード is the door C3 stands behind.

THE HANDSHAKE, read off the client's own message classes
--------------------------------------------------------
Shapes from the shape reader (the client's deserialisers), names from each
class's dump function (the field-name extractor). Nothing here is guessed:

    0x5100 Cl RequestTradeRequest   targetId u32      SEEN (round 151)
    0x5101 Sv OkTradeRequest        --                the asker's receipt
    0x5102 Sv NgTradeRequest        reason u8
    0x5103 Sv RequestTradeResponse  targetId u32      the other side is asked
    0x5104 Cl OkTradeResponse       reply u8          they accept
    0x5105 Cl NgTradeResponse       reason u8         they decline
    0x510C Sv NotifyTradeStart      --                the window opens
    0x510F Cl CastTradeItemPush     itemId{cat u16, id u16} nNum u8
    0x5110 Sv ErrorTradeItemPush    reason u8
    0x5111 Sv NotifyTradeItemPush   charaId u32 itemId param{count u8}
    0x5112 Cl CastTradeItemRecall   itemId nNum u8    take one back off
    0x5113 Sv ErrorTradeItemRecall  reason u8
    0x5114 Sv NotifyTradeItemRecall charaId u32 itemId param{count u8}
    0x5115 Cl CastTradeReady        readyState u8     the 確定 button
    0x5116 Sv ErrorTradeReady       reason u8
    0x5117 Sv NotifyTradeReady      charaId u32 readyState u8
    0x5118 Sv NotifyTradeExecute    --                成立
    0x5106 Cl RequestTradeCancel    --   -> 0x5107/0x5108, peer gets 0x510E
    0x5109 Cl RequestTradeEnd       --   -> 0x510A/0x510B, peer gets 0x510D

⚠️ 0x5103's field is named targetId by the original's own dump even though, at
the end it arrives on, it carries the *asker*. The twoshot family's matching
message (0x5003) names the same position senderId. The name below is ours; the
wire position is the original's.

⭐⭐ THE POST-成立 STATE IS NOT A GUESS. 0x5118 is a Notify with no payload and
there is no Sv message that ends the trade by itself, so something has to keep
the window alive until a player closes it -- and REASON_ALREADY_SETTLED,
「既にアイテムトレードが成立していますので、交換するアイテムを変更することは
できません」, is a sentence that can only be said in that state. The client's own
error table is the evidence that a settled-but-open trade exists.

WHERE THE REFUSALS COME FROM -- ⭐⭐⭐ and this is new
-----------------------------------------------------
`error_message.bin` files a sentence under (message id, reason), and this
family has **no entries under any of its own ids**. Its 26 sentences sit under
the pseudo id **0xFF09** instead, and the neighbours make the pattern plain:

    0xFF05  ツーショットチャット      0xFF08  友達登録
    0xFF09  アイテムトレード          0xFF0A  ＧＭチャット

-- one list per 申し込み subsystem, all four sharing the same first ten reasons
(「自分自身に申し込むことはできません」, 「既に申し込んでいます」, ...) and each
adding its own tail. The client reads that table at run time: round 189 watched
it put 「errorcode ff0b:32」 on screen when a 0xFF0B sentence was missing.

⚠️⚠️ SO THE REASON BYTE IS AN INDEX, and every refusal this server has sent so
far has been a placeholder 0 -- which in all four lists is 「未使用：：：エラー
なし」, a slot the original's own developers marked dead. The codes below are the
real ones.

⭐⭐⭐ AND THAT IS MEASURED, not argued. The round this file was written sent
0x5116 with reason 21 by accident (see READY_EXECUTE) and the client put
「既にアイテムトレードが成立していますので、交換するアイテムを変更することは
できません。」 on screen -- the 0xFF09 row for 21, word for word. So the client
really does look this table up by (pseudo id, reason), and a refusal that goes
out with 0 says nothing at all to the player.

⚠️ Only this family's codes were changed. The other three lists still get 0
from friends.py, groups.py and NG_REASON, which means their refusals are silent
or wrong on screen -- known, not unknown, and each needs its own look at a real
client before it moves.

WHAT IS NOT SENT, AND WHY
-------------------------
Three sentences in the list need a number this project has not read:

  * REASON_TOO_MANY_KINDS (13) 「これ以上、交換するアイテムの種類を増やすことは
    できません」 -- how many rows the trade table holds. That is the window's row
    count, and nothing on this end has seen the window.
  * REASON_TOO_MANY_OF_ONE (14) 「これ以上、交換するアイテムの個数を増やすことは
    できません」 -- a per-row cap. ⭐ The only hard bound is the wire's: nNum is a
    u8 and Inventory.ROW_MAX already refuses more than a row can hold.
  * REASON_ITEM_NOT_TRADEABLE (16) 「選択されたアイテムは交換不可能なアイテム
    です」 -- a per-item flag. ⚠️ NOT read as item.NO_DISCARD: the locker taught
    that lesson once already (0:119 and 1:236 are undiscardable and go in a
    locker fine), so a third flag with no sample is a third flag. What IS sent
    under this reason is the one case that is derived rather than guessed: an
    item being worn that item.NO_UNEQUIP says cannot come off.

Sending a cap this end invented would refuse a trade the original allowed, which
is worse than allowing one it refused; so these stay unsent and stay written
down. See the smallest-invention rule.

NOTHING HERE IS SAVED
---------------------
A trade is two people standing in front of each other, exactly like the 友達登録
and 勧誘 handshakes: every bit of it lives on the two sessions and dies with
either connection. The only thing that outlives it is the item move itself, and
that goes through the ordinary character store -- both stores, since the two
players need not share an account.
"""

from __future__ import annotations

import struct

import item

MSG_CL_REQUEST_TRADE_REQUEST = 0x5100
MSG_SV_OK_TRADE_REQUEST = 0x5101
MSG_SV_NG_TRADE_REQUEST = 0x5102
MSG_SV_REQUEST_TRADE_RESPONSE = 0x5103
MSG_CL_OK_TRADE_RESPONSE = 0x5104
MSG_CL_NG_TRADE_RESPONSE = 0x5105
MSG_CL_REQUEST_TRADE_CANCEL = 0x5106
MSG_SV_OK_TRADE_CANCEL = 0x5107
MSG_SV_NG_TRADE_CANCEL = 0x5108
MSG_CL_REQUEST_TRADE_END = 0x5109
MSG_SV_OK_TRADE_END = 0x510A
MSG_SV_NG_TRADE_END = 0x510B
MSG_SV_NOTIFY_TRADE_START = 0x510C
MSG_SV_NOTIFY_TRADE_END = 0x510D
MSG_SV_NOTIFY_TRADE_CANCEL = 0x510E
MSG_CL_CAST_TRADE_ITEM_PUSH = 0x510F
MSG_SV_ERROR_TRADE_ITEM_PUSH = 0x5110
MSG_SV_NOTIFY_TRADE_ITEM_PUSH = 0x5111
MSG_CL_CAST_TRADE_ITEM_RECALL = 0x5112
MSG_SV_ERROR_TRADE_ITEM_RECALL = 0x5113
MSG_SV_NOTIFY_TRADE_ITEM_RECALL = 0x5114
MSG_CL_CAST_TRADE_READY = 0x5115
MSG_SV_ERROR_TRADE_READY = 0x5116
MSG_SV_NOTIFY_TRADE_READY = 0x5117
MSG_SV_NOTIFY_TRADE_EXECUTE = 0x5118

#: Every MsgCl in the family. The whole family is handled in one piece for the
#: reason item.py spells out for its own window: a window with one live button
#: and three dead ones is not a smaller working window, it is a window that
#: wedges on the first wrong click.
HANDLED = frozenset(
    {
        MSG_CL_REQUEST_TRADE_REQUEST,
        MSG_CL_OK_TRADE_RESPONSE,
        MSG_CL_NG_TRADE_RESPONSE,
        MSG_CL_REQUEST_TRADE_CANCEL,
        MSG_CL_REQUEST_TRADE_END,
        MSG_CL_CAST_TRADE_ITEM_PUSH,
        MSG_CL_CAST_TRADE_ITEM_RECALL,
        MSG_CL_CAST_TRADE_READY,
    }
)

# ---------------------------------------------------------------------------
# The reasons, verbatim from error_message.bin's 0xFF09 list. The numbering is
# the file's: slots the original marked 未使用 are named and left unsent rather
# than dropped, because dropping one would renumber the rest.
# ---------------------------------------------------------------------------
REASON_NONE = 0                 # 未使用：：：エラーなし
REASON_TARGET_BUSY = 1          # 指定されたキャラクターは、現在申し込みを受けられる状態ではありません。
REASON_REQUEST_FAILED = 2       # アイテムトレードの申し込みに失敗しました。
REASON_TARGET_NOT_ASKED = 3     # 指定されたキャラクターは、現在申し込みを受けていません。
REASON_SEND_ERROR = 4           # 未使用：：：送信エラーが発生しました。
REASON_BAD_CHARA = 5            # キャラクターの情報が不正です。
REASON_WRONG_MODE = 6           # 未使用：：：モードが異なる。
REASON_SELF = 7                 # 自分自身に申し込むことはできません。
REASON_ALREADY_ASKED = 8        # 既に申し込んでいます。
REASON_NO_CHARA_DATA = 9        # キャラクターデータの取得に失敗しました。
REASON_NO_CHARA_INFO = 10       # キャラクター情報の取得に失敗しました。
REASON_NOT_TRADING = 11         # まだアイテムトレードを開始していません。
REASON_ALREADY_TRADING = 12     # 既にアイテムトレードを開始しています。
REASON_TOO_MANY_KINDS = 13      # これ以上、交換するアイテムの種類を増やすことはできません。
REASON_TOO_MANY_OF_ONE = 14     # これ以上、交換するアイテムの個数を増やすことはできません。
REASON_BAD_ITEM_INFO = 15       # 交換するアイテムの情報が不正です。
REASON_ITEM_NOT_TRADEABLE = 16  # 選択されたアイテムは交換不可能なアイテムです。
REASON_ITEM_NOT_OFFERED = 17    # 交換するアイテムの中に出品されていないアイテムが含まれています。
REASON_BAD_QUANTITY = 18        # 交換するアイテムの個数が正しくありません。
REASON_NOT_ENOUGH_HELD = 19     # 交換するアイテムの所持数が足りません。
REASON_NOT_CONFIRMED = 20       # 交換するアイテムを確定していませんので、アイテムトレードは成立しません。
REASON_ALREADY_SETTLED = 21     # 既にアイテムトレードが成立していますので、交換するアイテムを変更することはできません。
REASON_STATE_ERROR = 22         # サーバーエラーが発生しました。（トレード状態遷移失敗）
REASON_ITEMS_LOCKED = 23        # 現在、アイテムの操作が禁止されています。
REASON_BAD_TRADE_INFO = 24      # アイテムトレードに失敗しました。（トレード情報が不正）
REASON_ITEM_UPDATE_FAILED = 25  # アイテムトレードに失敗しました。（アイテム情報変更失敗）

#: 0x5104's ``reply``. ⚠️ The 勧誘 handshake taught that both buttons of a
#: confirmation box can send the Ok message and put the answer in the byte
#: (groups.ANSWER_YES, round 146, three rounds after the handshake was built
#: against a script that always said yes) -- so this end reads the byte rather
#: than the message id.
ANSWER_YES = 1

# 0x5115's ``readyState``. ⭐⭐⭐ THREE VALUES, NOT TWO, AND THE THIRD ONE IS THE
# ONE THAT MATTERS. Measured on a real client in round 213, which is also the
# round that first wrote this as a bool and watched the screen say otherwise:
#
#   1  ［決 定］. A green 「OK」 appears beside that side's list and
#      「トレードから解除」 greys out. Both sides at 1 is NOT 成立.
#   2  ⭐ When both sides are at 1, each client puts up its own
#      「この内容で取引しますか？」 box. ［は い］ sends readyState=2 and the box
#      becomes 「相手の応答を待っています」 -- so this is the half that waits for
#      the *other* player, and both sides at 2 is 成立.
#   0  解除, taking a side back to unconfirmed.
#
# ⭐⭐ AND THIS IS WHAT MAKES REASON 20 LEGIBLE. 「交換するアイテムを確定して
# いませんので、アイテムトレードは成立しません」 spends one sentence on both words:
# 確定 is state 1 and 成立 is state 2, and the refusal is for a 2 that arrives
# from a side which never sent a 1. A two-valued flag has no room for that
# sentence at all, which in hindsight is the tell.
READY_OFF = 0
READY_CONFIRMED = 1
READY_EXECUTE = 2


def reason(code: int) -> bytes:
    """One refusal byte. ⚠️ The client's reader is read-int8, i.e. signed; every
    code in the 0xFF09 list is far below 128, so none of them wraps."""
    return struct.pack(">B", code & 0xFF)


def parse_target(params: bytes) -> int:
    """0x5100's one u32. 0 for a body too short to hold one."""
    if len(params) < 4:
        return 0
    return struct.unpack_from(">I", params, 0)[0]


def parse_answer(params: bytes) -> int:
    """0x5104/0x5105's one u8."""
    return params[0] if params else 0


def parse_item(params: bytes) -> "tuple[int, int, int] | None":
    """0x510F/0x5112's ``itemId{cat u16, id u16} nNum u8``. None if short."""
    if len(params) < 5:
        return None
    category, item_id = struct.unpack_from(">HH", params, 0)
    return category, item_id, params[4]


def response_params(chara_id: int) -> bytes:
    """0x5103's u32: whom this application is from."""
    return struct.pack(">I", chara_id)


def item_params(chara_id: int, category: int, item_id: int, count: int) -> bytes:
    """0x5111/0x5114: charaId u32, itemId{cat u16, id u16}, param{count u8}."""
    return struct.pack(">IHHB", chara_id, category, item_id, count & 0xFF)


def ready_params(chara_id: int, ready: int) -> bytes:
    """0x5117: charaId u32, readyState u8."""
    return struct.pack(">IB", chara_id, ready & 0xFF)


class Table:
    """What one side has put on the trade table, and whether it is 確定.

    Rows are kept in the order they were pushed, which is the order the client
    was told about them; nothing reorders them, because a Notify is the only
    thing that draws a row and there is no message that redraws the table.
    """

    def __init__(self) -> None:
        self.rows: "list[list[int]]" = []   # [categoryId, id, count]
        #: READY_OFF / READY_CONFIRMED / READY_EXECUTE -- see the constants.
        self.state = READY_OFF
        self.settled = False

    def offered(self, category: int, item_id: int) -> int:
        for row in self.rows:
            if row[:2] == [category, item_id]:
                return row[2]
        return 0

    def push(self, category: int, item_id: int, count: int) -> int:
        """Put ``count`` more on the table and return the row's new total."""
        for row in self.rows:
            if row[:2] == [category, item_id]:
                row[2] += count
                return row[2]
        self.rows.append([category, item_id, count])
        return count

    def recall(self, category: int, item_id: int, count: int) -> "int | None":
        """Take ``count`` back off, or None if that many are not on the table.

        A row that reaches zero leaves, the same way Inventory.take drops one:
        the client is told 「recall」 with the number that came off and redraws
        from that, so an empty row left sitting here would only be able to
        disagree with the screen.
        """
        for index, row in enumerate(self.rows):
            if row[:2] != [category, item_id]:
                continue
            if count <= 0 or row[2] < count:
                return None
            row[2] -= count
            if row[2] == 0:
                del self.rows[index]
                return 0
            return row[2]
        return None

    def clear(self) -> None:
        self.rows.clear()
        self.state = READY_OFF
        self.settled = False

    def summary(self) -> str:
        if not self.rows:
            return "なし"
        return " ".join(f"{c}:{i}×{n}" for c, i, n in self.rows)


def may_offer(inv: "item.Inventory", category: int, item_id: int) -> "int | None":
    """The refusal for putting this item on the table, or None if it may go.

    Two checks, and neither is invented:

      * the key has to be one the client's own tables have, or the row the
        Notify draws names an item the client cannot look up -- the same refusal
        item.py applies everywhere, after three crashes that were all this
        server sending a key `item.bin` does not have;
      * ⭐ a worn item that item.NO_UNEQUIP says cannot come off cannot be given
        away either, since handing it over takes it off. That is derived from
        the flag the client reads out loud by greying its own button, not from a
        trade flag nobody has sampled -- see the module docstring on 16.
    """
    if not item.exists(category, item_id):
        return REASON_BAD_ITEM_INFO
    if inv.is_worn(category, item_id) and not item.can_unequip(category, item_id):
        return REASON_ITEM_NOT_TRADEABLE
    return None
