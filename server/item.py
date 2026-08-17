"""アイテム: what a character is carrying, and the window that lists it.

One exchange, opened by the fourth icon on the main toolbar (tooltip アイテム)
and repeated by every tab click inside the window that icon opens:

    0x4D00 MsgClQueryItemList    itemCategoryId u16
        -> 0x4D01 MsgSvResultItemList   nItemNum u16
        -> 0x4D03 MsgSvNotifyItemList   itemInfo[]{itemId{categoryId u16,
                                                          id u16},
                                                   param{count u8}}
        -> 0x4D02 MsgSvErrorItemList    reason u8

Ids and shapes come from the client's own message classes; field names from
each class's dump function. The Result/Notify split is the same one the 部活
デッキ window's two inventory queries use: a count on its own, then the rows in
a separate notify, which is what lets one query be answered by several notifies.

⚠️ THE WINDOW WILL NOT CHANGE TABS WHILE A QUERY IS UNANSWERED. Measured: with
0x4D00 unanswered, clicking a tab does nothing at all — no repaint, nothing on
the wire, twice, including the hover-then-click that the client normally needs.
Answer the first one and the same click switches tabs immediately. So a dead tab
is a symptom of an unanswered query, not of a missed click.

⭐ EACH TAB IS QUERIED ONCE PER OPENING OF THE WINDOW. Going back to a tab that
has already been answered redraws it from what the client kept and sends
nothing, so a list that changed server-side does not refresh until the window is
closed and opened again. Measured: the list was regranted twice with the window
open and the rows on screen never moved until it was reopened.

⚠️ The names in this window are NOT the names in `item.bin`'s name column. Each
record carries a second string, and that second one is what the client draws:
key 0:0 is 「制服きらめき」 in the table and 「きらめき」 on screen, 1:0 is
「リボンきらめき」 and 「リボン００１」. Two different transformations, so this
is a different field rather than a name being trimmed. It matters here only for
reading a screenshot back: the wire carries keys, not names.

itemCategoryId is a TAB INDEX, not an item's own categoryId
-----------------------------------------------------------
⭐⭐⭐ The one thing about this exchange that cannot be read off the message.
The window has six tabs and each click sends 0x4D00 with a small number, but the
number is the tab's position and not the category of the items it draws:

    tab 0 装飾   tab 1 消費   tab 2 奥義   tab 3 合成   tab 4 行事   tab 5 経歴

MEASURED, by clicking: 装飾 sends 0, 奥義 sends 2, 合成 sends 3. Meanwhile the
rows that drew under those tabs carry categoryId 0, 17..24 and 32..40 — none of
which is the tab number they arrived on. TABS below maps one to the other.

⭐⭐ THE CLIENT FILTERS THE ROWS AGAIN ON ITS OWN, which is what makes the
mapping measurable at all: one row with categoryId 32 was sent to the 装飾 tab
and to the 合成 tab, and only the second one drew it. So a server that sends too
much does not smear rows across tabs -- but it also cannot lean on that, since
the client will not draw a row the tab does not own, however the count is
phrased. The rows go out filtered, and PROBE_ALL_TABS exists to turn that off
when the mapping itself is the question.

Two tables behind one list
--------------------------
The rows drawn under 奥義 come out of a different table from every other tab's:
`item.bin` holds 装飾, 消費 and 合成 (223 records, categoryId 0..3, 8..12 and
32..40), while `item_skillbook.bin` holds the 「奥義の書」 (57 records,
categoryId 17..24). They share one key space and one wire format, so the split
only shows up in which keys exist -- ITEM_KEYS below is both tables at once, and
a key in neither is refused rather than sent on. That refusal is the same one
`club.Membership` applies to クラブ keys and for the same reason: three client
crashes so far have all been this server sending a key the client's own tables
do not have.

RESTORED and INVENTED
---------------------
Restored: the ids, the field layout, the tab mapping, the page size, and the two
refusal reasons -- `error_message.bin` gives 0x4D02 exactly two sentences,
「キャラクター情報の取得に失敗しました。」 (reason 0) and 「アイテム一覧の取得に
失敗しました。」 (reason 1), so an unknown character answers the first and
nothing else can currently answer the second.

Invented: that a character owns anything at all. Every route by which the
original hands an item over is missing here -- 装飾 and 消費 come from shops and
events, an 「奥義の書」 from クラブ練習 against an NPC, 合成アイテム from using a
キーワード during クラブ活動 -- so /item grants directly, the same door /kw and
/cs open for キーワード and 部活奥義, and on the same terms: the grant is
invented, the wire is not.

⚠️ NOT YET IMPLEMENTED, and deliberately: 0x4D04..0x4D0F (装備 / 使用 /
ロッカーにしまう / 捨てる) are the same family and are what the two buttons under
the list send. The list has to exist before any of them has something to act on.
Three things about them were measured while the list was being verified, and are
written down here because they decide the shape of that work:

  * 0x4D0D MsgClRequestItemDel goes out as itemId{categoryId u16, id u16} then a
    u16 quantity -- 「捨てる」 opens a 「捨てるアイテムの数を入力」 spinner first,
    and the number it settles on is that third field. Measured live: ウサ耳
    (2:0) at quantity 2 put `0002 0000 0002` on the wire. 「ロッカーにしまう」
    opens the same spinner for 0x4D0A, whose reader takes the same 2+2+2.
  * ⭐ THE CLIENT CHANGES NOTHING LOCALLY. With the request unanswered the row
    kept its old 個数 and the list did not move: the count on screen is the
    server's answer, not an optimistic edit.
  * ⚠️ AND THE REQUESTS ARE SERIALISED. After one went unanswered, the next
    button press only raised 「通信中 サーバーからの返答待ちです」 and sent
    nothing at all -- so an unanswered request costs the whole window, not just
    itself, and the second message never reaches the wire to be read.
"""

from __future__ import annotations

import struct

MSG_CL_QUERY_ITEM_LIST = 0x4D00
MSG_SV_RESULT_ITEM_LIST = 0x4D01
MSG_SV_ERROR_ITEM_LIST = 0x4D02
MSG_SV_NOTIFY_ITEM_LIST = 0x4D03

# `error_message.bin`, the run of sentences belonging to 0x4D02. Two, and the
# index within that run is the reason. Unlike most of this game's refusals
# neither of them is a 未使用 placeholder.
ERROR_NO_CHARACTER = 0
ERROR_NO_LIST = 1

# How many rows one 0x4D03 may carry.
#
# ⭐⭐⭐ NOT A MEASUREMENT AND NOT A GUESS: 0x4D03's deserializer is the SAME
# FUNCTION as 0x4308's, at one address (0x8FC990) that three message classes'
# vtables all point their slot 0 at -- MsgSvNotifyItemList,
# MsgSvNotifyCharaMenuClubSkillList and MsgSvNotifyLockerList, all three with an
# identical 2+2+1 row. It reads the count into +0xC4 and then walks rows of six
# bytes (five on the wire, one of padding) from +0x04, re-reading the count
# every iteration and bounds-checking nothing, so the row array is exactly
# (0xC4 - 4) / 6 == 32 entries with the count sitting immediately behind it.
#
# Row 33 therefore writes its categoryId over the count itself. On 0x4308 that
# was measured as a permanent hang rather than a crash -- the window never
# opens, 通信中 stays on screen -- and since it is the same code, the same is
# true here. Paging is what the Result message is for: it carries the total on
# its own, so the notify does not have to be the whole list in one message.
ITEM_LIST_PAGE = 32

# The window's tabs, in the order they are drawn, with the categoryId values
# each one owns. The index into this tuple is what 0x4D00 carries.
#
# ⭐⭐⭐ MEASURED, ALL SIX AT ONCE, and the client's own filter is what measured
# them: with PROBE_ALL_TABS on, one item per categoryId (26 rows) was answered
# to every tab, and each tab drew exactly the rows below. 装飾 drew 4, 消費 5,
# 奥義 8, 合成 9 -- 26 of 26, no row drawn twice and none left over.
#
# ⚠️ 行事 and 経歴 drew NOTHING out of those 26, which is a stronger statement
# than "unknown": every categoryId `item.bin` and `item_skillbook.bin` have is
# spoken for by the first four tabs, so whatever those two draw is keyed
# somewhere else entirely. Empty is the honest answer, and it is not a gap
# waiting on a guess about item keys.
TABS = (
    ("装飾", (0, 1, 2, 3)),
    ("消費", (8, 9, 10, 11, 12)),
    ("奥義", (17, 18, 19, 20, 21, 22, 23, 24)),
    ("合成", (32, 33, 34, 35, 36, 37, 38, 39, 40)),
    ("行事", ()),
    ("経歴", ()),
)

# Every key the two tables have, as the runs they come in. `item.bin`'s ids are
# NOT contiguous within a category -- 0 and 1 both jump to a high block, which
# is why this is runs and not counts. 223 keys in `item.bin` (categoryId 0..3,
# 8..12, 32..40) and 57 in `item_skillbook.bin` (17..24), 280 in total.
ITEM_KEYS = {
    0: ((0, 16), (118, 119), (240, 245)),
    1: ((0, 33), (236, 245)),
    2: ((0, 23),),
    3: ((0, 8),),
    8: ((0, 6),),
    9: ((0, 6),),
    10: ((0, 5),),
    11: ((0, 3),),
    12: ((0, 2),),
    17: ((0, 7),),
    18: ((0, 6),),
    19: ((0, 6),),
    20: ((0, 6),),
    21: ((0, 6),),
    22: ((0, 6),),
    23: ((0, 6),),
    24: ((0, 6),),
    32: ((0, 9),),
    33: ((0, 10),),
    34: ((0, 8),),
    35: ((0, 8),),
    36: ((0, 8),),
    37: ((0, 10),),
    38: ((0, 10),),
    39: ((0, 11),),
    40: ((0, 11),),
}

ITEM_COUNT = sum(last - first + 1
                 for runs in ITEM_KEYS.values() for first, last in runs)

# ⚠️⚠️ AN EXPERIMENT'S KNOB, AND IT IS OFF. With this on, every tab is answered
# with the whole inventory instead of that tab's share, which turns the client's
# own filter into the oracle for the mapping in TABS: grant one item per
# category, click each tab, and the rows that draw name the tab they belong to.
#
# It lives in memory and nowhere else, so a restart puts it back -- the default
# here is the shipped behaviour, not a state to remember to undo. /item probe
# is the only thing that moves it.
PROBE_ALL_TABS = False


def exists(category: int, item_id: int) -> bool:
    """Is this a key `item.bin` or `item_skillbook.bin` actually has?"""
    return any(first <= item_id <= last
               for first, last in ITEM_KEYS.get(category, ()))


def keys() -> "list[tuple[int, int]]":
    """Every legal item key, in table order."""
    return [(category, item_id)
            for category in sorted(ITEM_KEYS)
            for first, last in ITEM_KEYS[category]
            for item_id in range(first, last + 1)]


def category_keys() -> "list[tuple[int, int]]":
    """The first key of every category -- one item per category, in order.

    What /item sample hands out: 26 rows, under the page limit, one per group
    the client could sort into a tab.
    """
    return [(category, ITEM_KEYS[category][0][0]) for category in sorted(ITEM_KEYS)]


def tab_of(category: int) -> "int | None":
    """Which tab draws this categoryId, or None if no tab claims it."""
    for index, (_, categories) in enumerate(TABS):
        if category in categories:
            return index
    return None


def tab_name(tab: int) -> str:
    """The tab's own label, or a marker for an index the window does not have."""
    return TABS[tab][0] if 0 <= tab < len(TABS) else f"?{tab}"


def parse_query(params: bytes) -> int:
    """0x4D00's itemCategoryId. An absent body reads as tab 0, which is the
    one the window opens on."""
    return struct.unpack_from(">H", params, 0)[0] if len(params) >= 2 else 0


class Inventory:
    """What one character is carrying.

    Stored on the character record under "items" and rebuilt from that dict each
    time, the same arrangement Romance, ScoreCard, AbilitySheet and Membership
    use.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        # Rows in the order 0x4D03 will send them: [categoryId, id, count].
        # A key neither table has is dropped rather than sent on, the same
        # treatment クラブ keys get and for the same reason.
        self.rows: "list[list[int]]" = []
        for row in saved.get("carried") or ():
            try:
                category, item_id, count = (int(x) for x in row)
            except (TypeError, ValueError):
                continue
            if not exists(category, item_id):
                print(f"[item] {category}:{item_id} is not in item.bin or "
                      "item_skillbook.bin, dropping")
                continue
            if any(existing[:2] == [category, item_id] for existing in self.rows):
                continue
            self.rows.append([category, item_id, count & 0xFF])

    def to_json(self) -> dict:
        return {"carried": [list(row) for row in self.rows]}

    def summary(self) -> str:
        per_tab = []
        for index in range(len(TABS)):
            held = len(self.for_tab(index))
            if held:
                per_tab.append(f"{tab_name(index)}={held}")
        return (f"アイテム {len(self.rows)} 種 "
                + (" ".join(per_tab) if per_tab else "なし"))

    def grant(self, category: int, item_id: int, count: int = 1) -> bool:
        """Give this character an item, or set the count of one it already has.

        Returns False for a key neither table has. INVENTED that this happens at
        all -- see the module docstring.
        """
        if not exists(category, item_id):
            return False
        row = [category, item_id, count & 0xFF]
        for index, existing in enumerate(self.rows):
            if existing[:2] == [category, item_id]:
                self.rows[index] = row
                return True
        self.rows.append(row)
        return True

    def revoke(self, category: int, item_id: int) -> bool:
        before = len(self.rows)
        self.rows = [row for row in self.rows if row[:2] != [category, item_id]]
        return len(self.rows) != before

    def for_tab(self, tab: int) -> "list[list[int]]":
        """The rows this tab draws.

        ⚠️ A categoryId no tab claims is carried but never listed. That is a
        thing this server can produce and the original probably could not, since
        every key it could hand out belonged to some tab; /item add is what
        makes it reachable, and dropping such a row silently here would make it
        look like the grant had failed.
        """
        if PROBE_ALL_TABS:
            return list(self.rows)
        if not 0 <= tab < len(TABS):
            return []
        categories = TABS[tab][1]
        return [row for row in self.rows if row[0] in categories]

    def list_rows(self, rows: "list[list[int]]") -> bytes:
        """0x4D03's body: count u16 then five bytes per row."""
        out = struct.pack(">H", len(rows))
        for category, item_id, count in rows:
            out += struct.pack(">HHB", category, item_id, count)
        return out

    def row_pages(self, rows: "list[list[int]]") -> "list[bytes]":
        """The same body, split into messages the client's reader can hold.

        One empty page when there is nothing, because the window is waiting for
        a notify and not merely for a count -- see ITEM_LIST_PAGE for what the
        33rd row in one message does.
        """
        pages = []
        for start in range(0, max(len(rows), 1), ITEM_LIST_PAGE):
            pages.append(self.list_rows(rows[start:start + ITEM_LIST_PAGE]))
        return pages


def list_replies(inv: "Inventory | None", tab: int) -> "list[tuple[int, bytes]]":
    """The messages one 0x4D00 is answered with.

    The Result's count and the pages' counts come off one list of rows so they
    cannot drift apart; ⚠️ the Result carries the TOTAL and each page carries
    its own length, which is the arrangement 0x4307/0x4308 was measured to need.

    ⚠️ nItemNum is read here as a row count, not as a sum of 個数. Nothing on
    screen has told the two apart yet -- the window draws 個数 per row and no
    total anywhere -- so this is the reading the sibling message settles rather
    than one this exchange has confirmed.
    """
    if inv is None:
        return [(MSG_SV_ERROR_ITEM_LIST, struct.pack(">B", ERROR_NO_CHARACTER))]
    rows = inv.for_tab(tab)
    return ([(MSG_SV_RESULT_ITEM_LIST, struct.pack(">H", len(rows)))]
            + [(MSG_SV_NOTIFY_ITEM_LIST, page) for page in inv.row_pages(rows)])
