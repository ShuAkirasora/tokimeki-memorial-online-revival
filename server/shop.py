"""商品交換: the 購買部 counter, which sells nothing and barters everything.

One bracket with one operation inside it, opened from the NPC menu the
購買部のおねえさん carries (`menu.bin` (0,7), whose only item is `menu_item.bin`
18 「下取り」) and closed when the window goes away:

    0x4F00 MsgClRequestShopStart    (no body)
        -> 0x4F01 MsgSvOkShopStart      nNum u16
        -> 0x4F03 MsgSvNotifyShopList   shopGoodsInfo[]
        -> 0x4F02 MsgSvNgShopStart      reason u8
    0x4F07 MsgClRequestShopTrade    nGoodsNo u16
        -> 0x4F08 MsgSvOkShopTrade      nGoodsNo u16
        -> 0x4F0A MsgSvNotifyShopUpdate shopGoodsInfo      (see below)
        -> 0x4F09 MsgSvNgShopTrade      reason u8
    0x4F04 MsgClRequestShopEnd      (no body)
        -> 0x4F05 MsgSvOkShopEnd        (no body)
        -> 0x4F06 MsgSvNgShopEnd        reason u8

Ids from the client's own parser tables, field names from each class's dump
function, widths from each class's deserializer -- the same three tools the
アイテム window's family was read with, and nothing here is guessed from a name.

NOT A SHOP THAT TAKES MONEY
---------------------------
⭐⭐⭐ There is no currency anywhere in this exchange, and that is not an
omission this server is making: the row the client reads carries a LIST OF ITEMS
as its price. `MsgSvNotifyShopList`'s own dump function prints

    shopGoodsInfo[n]={{nGoodsNo, itemInfo={itemId={categoryId,id} param={count}}
                       tradeItemInfo[m]={{itemId={categoryId,id} param={count}}}
                       state}}

-- `itemInfo` is what you walk away with and `tradeItemInfo` is what you hand
over. The client's own refusal for a price it cannot pay says the same thing in
words: 「交換するためのアイテムを所持していないか、所持数が足りません」. The menu
item that opens the window is 「下取り」 and the refusals call the mode
商品交換, not 購入. So barter is the mechanism, and 「価格」 in this subsystem
means a bill of items.

WHERE THE FIVE ROWS COME FROM
-----------------------------
`store_item.bin`, five 56-byte records, and this server does not read the file:
GOODS below is that table transcribed. Each record is a u16 key, a 20-byte name,
and a 34-byte tail whose shape lines up with the wire's row field for field:

    +0x18 u16 +0x1a u16   the goods, as an `item.bin` key -- 8:0, 8:1, 9:3, 9:4
                          and 9:5, all five in the 消費 tab's categories
    +0x24..+0x33          FOUR (categoryId, id) slots, 0xffff for an unused one
    +0x34..+0x37          FOUR u8 counts, one per slot, 0 for an unused one

⭐⭐⭐ THE FOUR IS NOT A READING OF THE DATA -- IT IS THE CLIENT'S ARRAY. The
deserializer at 0x913A20 walks `tradeItemInfo` into a fixed array that starts at
+0x08 of a 0x24-byte row and is followed at +0x20 by the very count it just
read, so four six-byte entries fill it exactly. It re-reads that count every
iteration and bounds-checks nothing, which is the same shape the アイテム list's
32-row ceiling has: a fifth entry would write over the count itself. So the
table's four slots and the client's four slots are one fact, and TRADE_SLOT_MAX
is a hard ceiling rather than a table-sized coincidence.

The same reading holds for every row with no exceptions: the number of slots
that are not 0xffff equals the number of counts that are not zero, in all five
records. Four rows cost one kind of item and the fifth costs three.

WHAT IS NOT IN THAT TABLE
-------------------------
⚠️ Five records cannot separate a constant from a coincidence, and four fields
of the tail are constant across all five: +0x16 is 0, +0x1c and +0x1e are
0xffff, +0x22 is 0xffff, and +0x20 counts 0..4 exactly as the key does. So they
are UNCLAIMED here -- not "unused", just not separable by this table. Whichever
of them is a display order, a period, or a stock number, a five-row table with
one distinct value per column says nothing about it.

⚠️ ONE FIELD ON THE WIRE HAS NO COLUMN AT ALL: `itemInfo.param.count`, how many
you get for the price. Nothing in the record varies with it, so GOODS_COUNT is
this server's reading (one per exchange) rather than a restored number, and it
is the only number in this module that is not off the table or off the client.

RESTORED and INVENTED
---------------------
Restored: the ids, the field layout of all seven messages, the four-slot
ceiling, the five rows with their goods and their bills, the door the window
opens from, and the refusal sentences -- `error_message.bin` gives 0x4F02 seven,
0x4F06 three and 0x4F09 eleven, and marks with 「未使用：：：」 the ones the
original server never sent, which is why several constants below are defined and
never used.

Invented: nothing here restocks, ages, or runs out. `state` and 0x4F0A exist for
a shop whose rows change under the player, and this one's do not -- see
GOODS_STATE_AVAILABLE for what that costs.
"""
from __future__ import annotations

import struct

import item


# The bracket and the one operation inside it.
MSG_CL_REQUEST_SHOP_START = 0x4F00
MSG_SV_OK_SHOP_START = 0x4F01
MSG_SV_NG_SHOP_START = 0x4F02
MSG_SV_NOTIFY_SHOP_LIST = 0x4F03
MSG_CL_REQUEST_SHOP_END = 0x4F04
MSG_SV_OK_SHOP_END = 0x4F05
MSG_SV_NG_SHOP_END = 0x4F06
MSG_CL_REQUEST_SHOP_TRADE = 0x4F07
MSG_SV_OK_SHOP_TRADE = 0x4F08
MSG_SV_NG_SHOP_TRADE = 0x4F09
MSG_SV_NOTIFY_SHOP_UPDATE = 0x4F0A

REQUESTS = (MSG_CL_REQUEST_SHOP_START,
            MSG_CL_REQUEST_SHOP_END,
            MSG_CL_REQUEST_SHOP_TRADE)

# 0x4F02's reasons. Two of the seven are sendable from here; the rest carry the
# 「未使用：：：」 marker in the client's own table, which is the original saying
# it never sent them either.
START_NO_CHARACTER = 0      # キャラクター情報の取得に失敗しました。
START_BAD_NPC = 1           # ⚠️ 未使用
START_NPC_UNSUPPORTED = 2   # ⚠️ 未使用
START_CANNOT_TRADE = 3      # 現在、商品交換をすることはできません。
START_ALREADY_OPEN = 4      # ⚠️ 未使用
START_LIST_FAILED = 5       # ⚠️ 未使用
START_UNDEFINED = 6         # ⚠️ 未使用

# 0x4F06's three.
END_NO_CHARACTER = 0        # キャラクター情報の取得に失敗しました。
END_NOT_OPEN = 1            # 商品交換モードを開始していません。
END_UNDEFINED = 2           # ⚠️ 未使用

# 0x4F09's eleven. ⭐ Seven of them are reachable, which is what makes this
# exchange worth implementing carefully: the client has a sentence for every way
# a barter can fail, so a refusal never has to be approximated.
TRADE_NO_CHARACTER = 0      # キャラクター情報の取得に失敗しました。
TRADE_BAD_NPC = 1           # ⚠️ 未使用
TRADE_NPC_UNSUPPORTED = 2   # ⚠️ 未使用
TRADE_CANNOT_TRADE = 3      # 現在、商品交換をすることはできません。
TRADE_NO_SUCH_GOODS = 4     # 選択された商品の情報が見つかりませんでした。
TRADE_NO_SUCH_ITEM = 5      # 選択された商品のデータが見つかりませんでした。
TRADE_CANNOT_PAY = 6        # 交換するためのアイテムを所持していないか、所持数が足りません。
TRADE_SOLD_OUT = 7          # 選択された商品は品切れ中です。
TRADE_CANNOT_CARRY = 8      # 選択されたアイテムをこれ以上持ち歩くことはできません。
TRADE_ITEM_FAILED = 9       # アイテムデータの操作に失敗しました。
TRADE_UNDEFINED = 10        # ⚠️ 未使用

# ⭐⭐⭐ THE CLIENT'S OWN ARRAY, not a size read off the table. See the module
# docstring: `tradeItemInfo` lands in four six-byte entries with the count
# sitting immediately behind them, so a fifth entry overwrites the count.
TRADE_SLOT_MAX = 4

# How many rows one 0x4F03 may carry, by the same arithmetic one message class
# further up: the shopGoodsInfo array starts at +0x04 with a 0x24-byte stride
# and its count sits at +0x484, so (0x484 - 4) / 0x24 == 32 rows fill it and the
# 33rd writes over the count. Five rows never come near it; the ceiling is here
# because a table that grows would reach it silently.
SHOP_LIST_PAGE = 32

# ⚠️ A READING, NOT A RESTORED NUMBER. Nothing in `store_item.bin` varies with
# `itemInfo.param.count`, so one-per-exchange is what this server sends and the
# original's number for it is not recovered. It is one constant rather than a
# column so that a measurement can replace it in one place.
GOODS_COUNT = 1

# ⚠️ THE ENCODING OF `state` IS UNCLAIMED, and this is the only field on the
# wire this server sends without knowing what its value means. What IS known is
# that the field is about stock: 0x4F09 spends a sentence on 「選択された商品は
# 品切れ中です」, so a row can be sold out, and `state` is the only field in the
# row that could say so. Which value means which is not read out of anything --
# the client's grey-out is the oracle, and /shop state exists to ask it.
#
# 0 is what this server sends for all five rows: it is what a table with no
# stock model has to say, and every row saying the same thing is at least
# consistent whichever way round the encoding turns out to be.
GOODS_STATE_AVAILABLE = 0
GOODS_STATE_SOLD_OUT = 1

# The five rows of `store_item.bin`, as
#
#     nGoodsNo, (categoryId, id) of the goods, ((categoryId, id, count), ...)
#
# with the bill in table order. All five goods are `item.bin` keys in the 消費
# tab's categories and all nine bill entries are in the 合成 tab's -- the shop
# turns what クラブ activity drops into what a character can eat or give away.
#
# ⭐ nGoodsNo is the record's own key, which is also the only thing 0x4F07 sends
# back: the client picks a row and names it by this number, so the server never
# has to match on an item key to know what was bought.
GOODS: "tuple[tuple[int, tuple[int, int], tuple[tuple[int, int, int], ...]], ...]" = (
    (0, (8, 0), ((32, 0, 10),)),
    (1, (8, 1), ((32, 0, 10),)),
    (2, (9, 3), ((32, 1, 3),)),
    (3, (9, 4), ((32, 6, 5),)),
    (4, (9, 5), ((33, 10, 1), (32, 9, 5), (32, 7, 5))),
)

# Rows currently out of stock, as a set of nGoodsNo. Empty and stays empty
# unless /shop sells one out for a measurement: it lives in memory and nowhere
# else, so a restart puts the shipped shop back rather than leaving a knob
# turned. Nothing in the game moves this -- see the module docstring.
SOLD_OUT: "set[int]" = set()


def goods_numbers() -> "list[int]":
    return [number for number, _, _ in GOODS]


def find(number: int) -> "tuple[int, tuple[int, int], tuple[tuple[int, int, int], ...]] | None":
    """The row the client named, or None for a number the table does not have."""
    for row in GOODS:
        if row[0] == number:
            return row
    return None


def state_of(number: int) -> int:
    return GOODS_STATE_SOLD_OUT if number in SOLD_OUT else GOODS_STATE_AVAILABLE


def parse_goods_no(params: bytes) -> "int | None":
    """0x4F07's nGoodsNo, or None if the body is short.

    ⚠️ A short body is not goods 0: it is a message this server does not
    understand, and the caller refuses it rather than acting on a default. Same
    treatment item.parse_quantity gives its own short bodies.
    """
    if len(params) < 2:
        return None
    return struct.unpack_from(">H", params, 0)[0]


def goods_row(row: "tuple[int, tuple[int, int], tuple[tuple[int, int, int], ...]]") -> bytes:
    """One shopGoodsInfo, the shape both 0x4F03's entries and 0x4F0A's body use.

    ⚠️ The bill is clipped at TRADE_SLOT_MAX rather than sent whole: a longer
    one would land past the client's array and over the count behind it. Five
    rows cannot reach that today, which is exactly why the clip is here and not
    left to be noticed later.
    """
    number, (category, item_id), bill = row
    kept = bill[:TRADE_SLOT_MAX]
    out = struct.pack(">HHHB", number, category, item_id, GOODS_COUNT)
    out += struct.pack(">H", len(kept))
    for pay_category, pay_id, count in kept:
        out += struct.pack(">HHB", pay_category, pay_id, count)
    out += struct.pack(">b", state_of(number))
    return out


def list_body(rows: "tuple | list") -> bytes:
    """0x4F03's body: count u16 then that many shopGoodsInfo."""
    out = struct.pack(">H", len(rows))
    for row in rows:
        out += goods_row(row)
    return out


def row_pages(rows: "tuple | list") -> "list[bytes]":
    """The same body split into messages the client's reader can hold.

    One empty page when there is nothing, because the window is waiting for a
    notify and not merely for a count -- the same arrangement the アイテム list
    needs, and for the same reason.
    """
    rows = list(rows)
    return [list_body(rows[start:start + SHOP_LIST_PAGE])
            for start in range(0, max(len(rows), 1), SHOP_LIST_PAGE)]


def start_replies(inv) -> "list[tuple[int, bytes]]":
    """What one 0x4F00 is answered with.

    The Ok's count and the pages' counts come off one list so they cannot drift
    apart. ⚠️ nNum is read here as the number of ROWS, the same reading
    0x4D01's nItemNum gets and for the same reason: it is the only total the
    window could want, and the rows carry their own lengths.
    """
    if inv is None:
        return [(MSG_SV_NG_SHOP_START, struct.pack(">B", START_NO_CHARACTER))]
    return ([(MSG_SV_OK_SHOP_START, struct.pack(">H", len(GOODS)))]
            + [(MSG_SV_NOTIFY_SHOP_LIST, page) for page in row_pages(GOODS)])


def end_replies(inv, was_open: bool) -> "list[tuple[int, bytes]]":
    """What one 0x4F04 is answered with.

    ⭐ Both halves read nothing off the wire, so the only decision here is
    whether the mode was open -- and that one the client has a sentence for.
    """
    if inv is None:
        return [(MSG_SV_NG_SHOP_END, struct.pack(">B", END_NO_CHARACTER))]
    if not was_open:
        return [(MSG_SV_NG_SHOP_END, struct.pack(">B", END_NOT_OPEN))]
    return [(MSG_SV_OK_SHOP_END, b"")]


def trade_replies(inv, params: bytes, is_open: bool) -> "tuple[list[tuple[int, bytes]], bool]":
    """One 「交換」 button press. Returns the replies and whether stock moved.

    ⭐⭐ THE BILL IS CHECKED IN FULL BEFORE ANY OF IT IS TAKEN. A three-entry
    bill paid halfway is a character robbed of two items for nothing, and the
    client's own refusal 「交換するためのアイテムを所持していないか、所持数が
    足りません」 is one sentence for the whole bill rather than one per line --
    so the whole bill is a single yes or no here too.

    ⚠️ The carry check is made the same way round: `Inventory.receive` refuses a
    row that would pass 255, so it is asked BEFORE the bill is taken, not after.
    """
    if inv is None:
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_NO_CHARACTER))], False
    if not is_open:
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_CANNOT_TRADE))], False
    number = parse_goods_no(params)
    if number is None:
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_NO_SUCH_GOODS))], False
    row = find(number)
    if row is None:
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_NO_SUCH_GOODS))], False
    _, (category, item_id), bill = row
    if number in SOLD_OUT:
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_SOLD_OUT))], False
    # ⚠️ The second of the two "missing" sentences, and it is not the same as
    # the first: 4 is a row the shop does not have, 5 is a row whose goods are
    # not a key `item.bin` or `item_skillbook.bin` has. The five shipped rows
    # can never take this branch; a hand-edited GOODS can.
    if not item.exists(category, item_id):
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_NO_SUCH_ITEM))], False
    for pay_category, pay_id, count in bill:
        if inv.held(pay_category, pay_id) < count:
            return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_CANNOT_PAY))], False
    if inv.held(category, item_id) + GOODS_COUNT > 0xFF:
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_CANNOT_CARRY))], False
    for pay_category, pay_id, count in bill:
        if inv.take(pay_category, pay_id, count) is None:
            # Unreachable behind the check above, and answered rather than
            # crashed: 「アイテムデータの操作に失敗しました」 is the client's own
            # sentence for a bookkeeping failure, and a half-paid bill is
            # exactly what it is for.
            return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_ITEM_FAILED))], True
    if not inv.receive(category, item_id, GOODS_COUNT):
        return [(MSG_SV_NG_SHOP_TRADE, struct.pack(">B", TRADE_ITEM_FAILED))], True
    # ⚠️ 0x4F0A IS NOT SENT. It carries one shopGoodsInfo, which is a row that
    # CHANGED -- stock running down, a price moving -- and nothing here changes:
    # the five rows are the same before and after. Sending an unchanged row
    # would be inventing a restock model in the one place a player could see it.
    # goods_row() builds the body, so the message is ready for a shop that has
    # something to notify.
    return [(MSG_SV_OK_SHOP_TRADE, struct.pack(">H", number))], True


def update_reply(number: int) -> "tuple[int, bytes] | None":
    """0x4F0A for one row, for when there is a change worth notifying.

    Nothing calls this yet; see trade_replies for why.
    """
    row = find(number)
    return None if row is None else (MSG_SV_NOTIFY_SHOP_UPDATE, goods_row(row))


def summary() -> str:
    sold = f", 品切れ {sorted(SOLD_OUT)}" if SOLD_OUT else ""
    return f"商品 {len(GOODS)} 種{sold}"
