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
nothing, so a list that changed *behind the client's back* does not refresh
until the window is closed and opened again. Measured: the list was regranted
twice with the window open and the rows on screen never moved until it was
reopened. ⚠️ An answer to something the client asked for is the other case and
does repaint -- see 0x4D0E below. The one that does neither is 0x4D09, whose
remain_count never reaches the list, so a used item reads one too high until the
window is reopened.

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
Restored: the ids, the field layout, the tab mapping, the page size, what 使用
does to the character who uses it (ITEM_EFFECTS), and the two refusal reasons
-- `error_message.bin` gives 0x4D02 exactly two sentences,
「キャラクター情報の取得に失敗しました。」 (reason 0) and 「アイテム一覧の取得に
失敗しました。」 (reason 1), so an unknown character answers the first and
nothing else can currently answer the second.

Invented: that a character owns anything at all. Every route by which the
original hands an item over is missing here -- 装飾 and 消費 come from shops and
events, an 「奥義の書」 from クラブ練習 against an NPC, 合成アイテム from using a
キーワード during クラブ活動 -- so /item grants directly, the same door /kw and
/cs open for キーワード and 部活奥義, and on the same terms: the grant is
invented, the wire is not.

What can be done to a row
-------------------------
0x4D04..0x4D0F are the same family and are what the buttons under the list send.
Four operations, each a request and a pair of answers, and every shape below is
read off the client's own reader (the shape reader) with the field names off
each class's dump function (the field-name extractor) -- none of them is guessed:

    0x4D04 MsgClCastItemEquip           itemId{cat u16, id u16} equip u8
        -> 0x4D06 MsgSvNotifyItemEquip  charaId u32 itemId equip u8
        -> 0x4D05 MsgSvErrorItemEquip   reason u8   (ten sentences)
    0x4D07 MsgClCastItemUse             itemId
        -> 0x4D09 MsgSvNotifyItemUse    charaId u32 itemId remain_count u8
        -> 0x4D08 MsgSvErrorItemUse     reason u8   (five)
    0x4D0A MsgClRequestItemPutInLocker  itemId nNum u16
        -> 0x4D0B MsgSvOkItemPutInLocker itemId nNum u16
        -> 0x4D0C MsgSvNgItemPutInLocker reason u8  (six)
    0x4D0D MsgClRequestItemDel          itemId nNum u16
        -> 0x4D0E MsgSvOkItemDel        itemId nNum u16
        -> 0x4D0F MsgSvNgItemDel        reason u8   (five)

⭐ The two Notify answers carry a charaId and the two Ok answers do not, which
is the split the message names already announce: Cast goes out to everyone who
can see the character, Request is answered to the asker alone. Equipping and
using are things other players watch happen; putting away and throwing out are
bookkeeping. So the first two are relayed to peers and the last two are not.

⭐⭐ WHICH NUMBER nNum CARRIES is a reading, not a measurement, and the evidence
for it is a naming contrast inside this one binary: where the client's dump
functions mean "how many are left" they say so -- `remain_count` on
MsgSvNotifyItemUse, `remain` on MsgSvNgClubEnter -- while all eight of this
family's Request/Ok pairs (item del, item put-in-locker, locker take, locker
del) carry a field list that is IDENTICAL on both halves, request and answer
alike, down to the name nNum. An answer whose fields are a verbatim copy of the
request's is an echo of what was done, not a report of what is left. So 0x4D0E
and 0x4D0B send back the quantity actually removed, and only 0x4D09 -- the one
message in the family whose field is named for it -- sends back the remainder.

⚠️ Three things were measured about these while the list was being verified, and
they decide how any of it can be tested:

  * 0x4D0D goes out as itemId then a u16 quantity -- 「捨てる」 opens a
    「捨てるアイテムの数を入力」 spinner first, and the number it settles on is
    that third field. Measured live: ウサ耳 (2:0) at quantity 2 put
    `0002 0000 0002` on the wire. 「ロッカーにしまう」 opens the same spinner.
  * ⭐ THE CLIENT MAKES NO OPTIMISTIC EDIT -- ⚠️ AND THAT IS ONLY TRUE WHILE THE
    REQUEST IS UNANSWERED, which is how it was first measured and how it was
    first written down without the clause. Answered, the client edits the row
    in place at once: holding 5 and throwing 2 away turned the 5 into a 3 with
    the window still open, no reopen needed. Both halves matter -- the number on
    screen is always the server's, and it moves as soon as the server says so.
  * ⚠️ AND THE REQUESTS ARE SERIALISED. After one went unanswered, the next
    button press only raised 「通信中 サーバーからの返答待ちです」 and sent
    nothing at all -- so an unanswered request costs the whole window, not just
    itself. ⭐⭐ THIS IS WHY THE FAMILY IS IMPLEMENTED IN ONE PIECE rather than
    a message at a time: a window with one live button and three dead ones is
    not a smaller version of a working window, it is a window that wedges on
    the first wrong click.

What the refusals can and cannot say
------------------------------------
Every reason below is a real sentence out of `error_message.bin`, and the ones
this server never sends are marked as such rather than dropped -- the numbering
is the file's, so leaving a gap out would renumber the rest.

⭐⭐⭐ TWO OF THEM WERE FOUND BY WATCHING THE CLIENT GREY ITS OWN BUTTONS, which
is worth stating because it is the only route to a per-item flag that this
project has: selecting a row leaves 「捨てる」 live or dead, so the window reads
one bit of `item.bin` out loud, once per item. NO_DISCARD and NO_UNEQUIP below
are what that produced. ⚠️ Both are enforced here anyway even though an honest
client never sends the request -- the refusal exists for the client that does.

What is still missing, and why:

  * WHICH ITEMS CANNOT GO IN A LOCKER (0x4D0C reason 2). ⚠️ NOT the same bit as
    NO_DISCARD: 0:119 and 1:236 carry that one and still had 「ロッカーにしまう」
    live, so this is a third flag with no sample yet.
  * WHICH ITEMS ARE ONE GENDER'S (0x4D05 reasons 5 and 6). Undecoded, and the
    obvious probe misfired -- a boy could not equip 1:237 ＧＭ用ネクタイ either,
    and a necktie is not the girls' half of that pair, so whatever stops those
    two is not gender.
  * HOW BIG A LOCKER IS (0x4D0C reason 4). See LOCKER_CAPACITY.

INVENTED, beyond the grant itself
---------------------------------
  * ONE WORN ITEM PER CATEGORY. 装飾 is four categories -- 制服, リボン, ウサ耳,
    チーク by their first rows -- which reads like four slots, so wearing a
    second item of a category takes the first one off. The client is told about
    both changes. ⚠️ Not measured; what IS settled is the equip flag's meaning,
    since 0x4D05 spends two of its ten sentences on 「既に身に付けています」 and
    「身に付けていません」, which only make sense for a toggle.

⭐⭐ WHAT 使用 DOES IS NOT ON THAT LIST, and used to be. This section read
「the wire is complete; the consequence is absent」 for as long as `item.bin`'s
tail was undecoded, and both halves of it are decoded now: which 能力 a 種
raises and by how much, and how much ストレス a meal takes off. ITEM_EFFECTS
holds them and mps_session._item_effect applies them, so 使用 is restoration
down to the numbers. ⚠️ The one thing in it that is a reading rather than a
measurement is the *unit* of the ability figure -- see ITEM_EFFECTS, which
takes it literally on purpose.
"""

from __future__ import annotations

import struct

MSG_CL_QUERY_ITEM_LIST = 0x4D00
MSG_SV_RESULT_ITEM_LIST = 0x4D01
MSG_SV_ERROR_ITEM_LIST = 0x4D02
MSG_SV_NOTIFY_ITEM_LIST = 0x4D03
MSG_CL_CAST_ITEM_EQUIP = 0x4D04
MSG_SV_ERROR_ITEM_EQUIP = 0x4D05
MSG_SV_NOTIFY_ITEM_EQUIP = 0x4D06
MSG_CL_CAST_ITEM_USE = 0x4D07
MSG_SV_ERROR_ITEM_USE = 0x4D08
MSG_SV_NOTIFY_ITEM_USE = 0x4D09
MSG_CL_REQUEST_ITEM_PUT_IN_LOCKER = 0x4D0A
MSG_SV_OK_ITEM_PUT_IN_LOCKER = 0x4D0B
MSG_SV_NG_ITEM_PUT_IN_LOCKER = 0x4D0C
MSG_CL_REQUEST_ITEM_DEL = 0x4D0D
MSG_SV_OK_ITEM_DEL = 0x4D0E
MSG_SV_NG_ITEM_DEL = 0x4D0F

# The two answers that every peer gets a copy of, for the reason in the module
# docstring: they carry a charaId and the Ok answers do not.
RELAYED = (MSG_SV_NOTIFY_ITEM_EQUIP, MSG_SV_NOTIFY_ITEM_USE)

# `error_message.bin`, the run of sentences belonging to 0x4D02. Two, and the
# index within that run is the reason. Unlike most of this game's refusals
# neither of them is a 未使用 placeholder.
ERROR_NO_CHARACTER = 0
ERROR_NO_LIST = 1

# 0x4D05 MsgSvErrorItemEquip, ten sentences.
EQUIP_NO_CHARACTER = 0      # キャラクター情報の取得に失敗しました。
EQUIP_BAD_ITEM = 1          # 選択されたアイテムの情報もしくは…操作情報が不正です。
EQUIP_NOT_HELD = 2          # 選択されたアイテムを所持していません。
EQUIP_ALREADY_WORN = 3      # 選択された装飾品は既に身に付けています。
EQUIP_NOT_WORN = 4          # 選択された装飾品は身に付けていません。
EQUIP_MALE_ONLY = 5         # ⚠️ never sent: no gender flag decoded
EQUIP_FEMALE_ONLY = 6       # ⚠️ never sent: no gender flag decoded
EQUIP_NOT_WEARABLE = 7      # 身に付けられるアイテムではありません。
EQUIP_CANNOT_REMOVE = 8     # その装飾品を外すことはできません。(NO_UNEQUIP)
EQUIP_OTHER_PC = 9          # ⚠️ never sent: nothing here equips another player

# 0x4D08 MsgSvErrorItemUse, five. ⚠️ reason 4 is a 未使用 placeholder in the
# file itself (「未使用：：：その他のエラー」), so four are usable.
USE_NO_CHARACTER = 0
USE_BAD_ITEM = 1            # 選択されたアイテムの情報が不正です。
USE_NOT_USABLE = 2          # 使用できるアイテムではありません。
USE_NOT_HELD = 3            # 選択されたアイテムを所持していません。

# 0x4D0C MsgSvNgItemPutInLocker, six.
PUT_NO_CHARACTER = 0
PUT_BAD_ITEM = 1            # 選択されたアイテムの情報が不正です。
PUT_NOT_STORABLE = 2        # ⚠️ never sent: no per-item flag decoded
PUT_NOT_ENOUGH = 3          # 指定された個数を所持していません。
PUT_LOCKER_FULL = 4         # ⚠️ never sent while LOCKER_CAPACITY is None
PUT_CANNOT_REMOVE = 5       # ⚠️ only for a worn item in NO_UNEQUIP

# 0x4D0F MsgSvNgItemDel, five.
DEL_NO_CHARACTER = 0
DEL_BAD_ITEM = 1            # 選択されたアイテムの情報が不正です。
DEL_CANNOT_DROP = 2         # 選択されたアイテムを捨てることはできません。(NO_DISCARD)
DEL_NOT_ENOUGH = 3          # 指定された個数を所持していません。
DEL_CANNOT_REMOVE = 4       # ⚠️ only for a worn item in NO_UNEQUIP

# The tabs whose categories mean something to an operation. Both are readings of
# the tab names, and both are the only readings the refusal sentences leave
# room for: 装飾 is what 身に付ける applies to and 消費 is what 使用 applies to.
WEARABLE_TAB = 0
CONSUMABLE_TAB = 1

# Worn items that cannot be taken off, as {categoryId: ((first, last), ...)}.
# ⚠️ ONE MEASURED MEMBER AND NO WAY YET TO FIND THE REST. Double-clicking a worn
# row toggles it -- measured both ways on 2:0, which sent equip=1 and then
# equip=0 -- but doing the same to a worn 0:118 ＧＭ制服 put NOTHING on the wire
# at all, twice, with the same click that works on its neighbours. So the client
# knows that one cannot come off. Whether that is the same flag as NO_DISCARD
# below is untested: the obvious next case, 1:236, cannot even be put ON (see
# that entry), so it cannot be asked the question.
NO_UNEQUIP: "dict[int, tuple[tuple[int, int], ...]]" = {
    0: ((118, 118),),
}

# Items the client will not let a player throw away, as key runs.
#
# ⭐⭐⭐ MEASURED THROUGH THE CLIENT'S OWN GREY-OUT, then predicted and
# confirmed. Selecting a row lights 「捨てる」 or leaves it dead, which makes the
# window an oracle for a per-item flag: 0:118 and 0:119 are dead, 0:0, 1:0, 2:0
# and 8:0 are live. Diffing `item.bin`'s 188-byte tails for a byte that splits
# those six left four candidate offsets; offset 142 (and its twin at 143, which
# never differs from it anywhere in the table) marks exactly 19 records, and
# they read as one family: every ＧＭ, ＳＰゲスト and 友達 uniform, ribbon and
# necktie -- the staff and NPC wardrobe -- plus 2:23, the single record in the
# whole table with no display name, which is a placeholder.
#
# ⭐ The prediction that settled it: offsets 130 and 131 pick out almost the same
# set but also include 11:3 草, so granting 草 and looking at the button
# separates them. 草's 「捨てる」 was live, and so was 0:16's; 1:236's was dead.
# Four items, four calls right, and two of the four candidate offsets killed.
#
# ⚠️ THIS IS NOT THE LOCKER'S FLAG. 1:236 and 0:119 are both undiscardable and
# both had 「ロッカーにしまう」 live, so 0x4D0C's 「ロッカーに格納できない
# アイテムです」 belongs to some other bit and stays unsent.
NO_DISCARD: "dict[int, tuple[tuple[int, int], ...]]" = {
    0: ((118, 119), (240, 245)),
    1: ((236, 245),),
    2: ((23, 23),),
}

# How many distinct rows one account's ロッカー holds, or None for no limit.
# ⚠️ There WAS a limit -- 0x4D0C spends a sentence on 「ロッカーがいっぱいです」
# -- but its value is not recovered, and picking a number would be inventing a
# rule players run into. None keeps the refusal written and unsent.
LOCKER_CAPACITY: "int | None" = None

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

# The largest 個数 one row can say, because the row says it in a u8. Not a
# design decision and not a guess about the original's carrying rules -- just
# the width of the field, which is why it is the one carry limit here that is
# not invented. See Inventory.receive.
ROW_MAX = 0xFF

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

# What 使用 does, as `item.bin`'s own three columns:
#
#     {(categoryId, id): (ability, amount, stress)}
#
#     ability   which 能力 goes up: a `chara_ability_type.bin` key, 0 文系 …
#               5 スタミナ, from +0xA8 -- None where that column is 0xFFFF
#     amount    how far it goes up, from +0xAE
#     stress    how much ストレス comes off, from +0xB0
#
# Fourteen of the 223 records carry one; a key that is not here has all three
# columns at zero, and using it takes it off the list and does nothing else.
#
# ⭐⭐⭐ RESTORED, AND MACHINE-CHECKED RATHER THAN TRUSTED. Every number below
# is transcribed out of the game's own table, and a transcription drifts --
# silently, and while still reading perfectly. `the item-effect check check` in
# the other tree re-reads `item.bin` and compares this dict to it key by key,
# the same drift check `shop.GOODS` has for `store_item.bin`.
#
# ⭐⭐ THE CLIENT READS NONE OF THE THREE. Of this record's 212 bytes the
# client touches five offsets in total -- +0x00 and +0x02 (the key), +0xAA (the
# 合成 group), +0xB6 (the 装備部位) and +0xBB (the name it draws) -- and no
# effect column is among them. So the consequence of 使用 cannot happen on that
# end. It is this end's arithmetic, exactly as 授業's 能力増減 is, which is
# also what settles what has to go back on the wire: see use_replies.
#
# ⚠️ THE UNIT OF `amount` IS THE LITERAL ONE, and that is a reading. abilityParam
# is 8.8 fixed point (lesson.ABILITY_STEP), so a 種's 5 is 5/256 of a level --
# it moves the bar by 2% and fifty of them make a レベル. Reading the 5 as
# levels, or as a percentage, would multiply it by a factor no table carries,
# and inventing a factor is the one thing this row of the roadmap is not.
#
# ⚠️ 9:5 本命チョコ's 255 is the odd one: a 消費 item whose description is about
# giving it away, carrying a stress figure that empties any bar 0x4811 can draw
# (that notify is a u8, so 255 is every value it can report). It is applied as
# the number it is rather than as a 「全快」 special case -- the only visible
# difference is a sheet sitting at stress.FULL (257), which 255 leaves at 2.
ITEM_EFFECTS: "dict[tuple[int, int], tuple[int | None, int, int]]" = {
    (8, 0): (None, 0, 10),              # お弁当
    (8, 1): (None, 0, 10),              # 焼きそばパン
    (8, 2): (None, 0, 20),              # ゲンコツおにぎり
    (8, 3): (None, 0, 20),              # トレビアンサンド
    (8, 4): (None, 0, 20),              # 新鮮茶葉使用お茶
    (8, 5): (None, 0, 20),              # 濃厚牛乳
    (8, 6): (None, 0, 5),               # オレンジバニラマロン
    (9, 5): (None, 0, 255),             # 本命チョコ
    (10, 0): (0, 5, 0),                 # 文学の種        → 文系
    (10, 1): (1, 5, 0),                 # 科学の種        → 理系
    (10, 2): (3, 5, 0),                 # 雑学の種        → 雑学
    (10, 3): (2, 5, 0),                 # 感性の種        → 芸術
    (10, 4): (4, 5, 0),                 # スポーツ万能薬  → 運動
    (10, 5): (5, 5, 0),                 # パワフルプロテイン → スタミナ
}

# What a key with no row in ITEM_EFFECTS is worth.
NO_EFFECT: "tuple[int | None, int, int]" = (None, 0, 0)

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


def _in_runs(runs: "dict[int, tuple[tuple[int, int], ...]]",
             category: int, item_id: int) -> bool:
    return any(first <= item_id <= last
               for first, last in runs.get(category, ()))


def can_discard(category: int, item_id: int) -> bool:
    """May a player throw this away? See NO_DISCARD."""
    return not _in_runs(NO_DISCARD, category, item_id)


def effect_of(category: int, item_id: int) -> "tuple[int | None, int, int]":
    """What using this item does: ``(ability, amount, stress)``. See ITEM_EFFECTS.

    Every key answers, including one that has no effect and one the tables do
    not have at all -- the caller has already decided whether the item may be
    used, and this only says what happens when it is.
    """
    return ITEM_EFFECTS.get((category, item_id), NO_EFFECT)


def can_unequip(category: int, item_id: int) -> bool:
    """May a worn item come off? See NO_UNEQUIP."""
    return not _in_runs(NO_UNEQUIP, category, item_id)


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


def list_body(rows: "list[list[int]]") -> bytes:
    """0x4D03's body: count u16 then five bytes per row.

    ⭐ 0x0409 MsgSvNotifyLockerList uses this too, and not by analogy: its
    deserializer is literally the same function as 0x4D03's (vtable slot 0 of
    both Input classes is 0x8FC990), so the row width and the 32-row ceiling
    are the same fact and not two facts that happen to agree.
    """
    out = struct.pack(">H", len(rows))
    for category, item_id, count in rows:
        out += struct.pack(">HHB", category, item_id, count)
    return out


def row_pages(rows: "list[list[int]]") -> "list[bytes]":
    """The same body, split into messages the client's reader can hold.

    One empty page when there is nothing, because the window is waiting for a
    notify and not merely for a count -- see ITEM_LIST_PAGE for what the 33rd
    row in one message does.
    """
    return [list_body(rows[start:start + ITEM_LIST_PAGE])
            for start in range(0, max(len(rows), 1), ITEM_LIST_PAGE)]


def filter_tab(rows: "list[list[int]]", tab: int) -> "list[list[int]]":
    """The rows a tab draws, for either list.

    ⚠️ A categoryId no tab claims is carried but never listed. That is a thing
    this server can produce and the original probably could not, since every key
    it could hand out belonged to some tab; /item add is what makes it
    reachable, and dropping such a row silently here would make it look like the
    grant had failed.
    """
    if PROBE_ALL_TABS:
        return list(rows)
    if not 0 <= tab < len(TABS):
        return []
    categories = TABS[tab][1]
    return [row for row in rows if row[0] in categories]


def parse_quantity(params: bytes) -> "tuple[int, int, int] | None":
    """``(categoryId, id, nNum)`` off a 2+2+2 request, or None if it is short.

    0x4D0D and 0x4D0A both. ⚠️ A short body is not a quantity of zero: it is a
    message this server does not understand, and the caller refuses it rather
    than acting on a default.
    """
    if len(params) < 6:
        return None
    return struct.unpack_from(">HHH", params, 0)


def parse_equip(params: bytes) -> "tuple[int, int, int] | None":
    """``(categoryId, id, equip)`` off 0x4D04's 2+2+1."""
    if len(params) < 5:
        return None
    return struct.unpack_from(">HHB", params, 0)


def parse_use(params: bytes) -> "tuple[int, int] | None":
    """``(categoryId, id)`` off 0x4D07's 2+2."""
    if len(params) < 4:
        return None
    return struct.unpack_from(">HH", params, 0)


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
        # Which of those rows are being worn, as [categoryId, id] pairs. Kept
        # apart from the count rather than as a fifth number on the row, because
        # 個数 is what the wire's row carries and nothing on it says "worn" --
        # the window draws no such column. ⚠️ A pair naming an item that is not
        # carried is dropped: the two can only disagree if a save was edited by
        # hand, and a worn item nobody holds would refuse to come off.
        self.worn: "list[list[int]]" = []
        for pair in saved.get("worn") or ():
            try:
                category, item_id = (int(x) for x in pair)
            except (TypeError, ValueError):
                continue
            if not self.held(category, item_id):
                print(f"[item] worn {category}:{item_id} is not carried, dropping")
                continue
            if [category, item_id] not in self.worn:
                self.worn.append([category, item_id])

    def to_json(self) -> dict:
        return {"carried": [list(row) for row in self.rows],
                "worn": [list(pair) for pair in self.worn]}

    def summary(self) -> str:
        per_tab = []
        for index in range(len(TABS)):
            held = len(self.for_tab(index))
            if held:
                per_tab.append(f"{tab_name(index)}={held}")
        return (f"アイテム {len(self.rows)} 種 "
                + (" ".join(per_tab) if per_tab else "なし")
                + (f" 装備{len(self.worn)}" if self.worn else ""))

    def clear(self) -> None:
        """Drop everything, worn included. ⚠️ Clearing ``rows`` on its own would
        leave a worn pair pointing at an item nobody holds."""
        self.rows.clear()
        self.worn.clear()

    def held(self, category: int, item_id: int) -> int:
        """How many of this item are carried. 0 for one that is not."""
        for existing in self.rows:
            if existing[:2] == [category, item_id]:
                return existing[2]
        return 0

    def is_worn(self, category: int, item_id: int) -> bool:
        return [category, item_id] in self.worn

    def wear(self, category: int, item_id: int) -> "list[list[int]]":
        """Put this on and return everything that came off to make room.

        ⚠️ ONE PER CATEGORY IS INVENTED -- see the module docstring. The return
        value is what makes it visible rather than silent: the caller owes the
        client a 0x4D06 with equip=0 for each pair in it, so a slot changing
        hands is two messages and not one.
        """
        removed = [pair for pair in self.worn if pair[0] == category]
        self.worn = [pair for pair in self.worn if pair[0] != category]
        self.worn.append([category, item_id])
        return removed

    def take_off(self, category: int, item_id: int) -> bool:
        before = len(self.worn)
        self.worn = [pair for pair in self.worn if pair != [category, item_id]]
        return len(self.worn) != before

    def take(self, category: int, item_id: int, count: int) -> "int | None":
        """Remove ``count`` of this item and return what is left, or None.

        None means the character does not hold that many, which is one refusal
        for all four operations -- 「指定された個数を所持していません」 for the
        two that name a quantity and 「所持していません」 for the two that do
        not. A row that reaches zero leaves the list rather than sitting there
        as an empty line, and a worn item that leaves comes off on the way out.
        """
        for index, existing in enumerate(self.rows):
            if existing[:2] != [category, item_id]:
                continue
            if count <= 0 or existing[2] < count:
                return None
            existing[2] -= count
            if existing[2] == 0:
                del self.rows[index]
                self.take_off(category, item_id)
            return existing[2]
        return None

    def receive(self, category: int, item_id: int, count: int) -> bool:
        """Add ``count`` to what is carried, or False if it will not fit.

        ⭐ THE ONLY CARRY LIMIT THIS SERVER CAN JUSTIFY, and it is not invented:
        the row's 個数 goes on the wire as a u8 (0x4D03 entries are 2+2+1), so a
        row cannot say more than 255 whatever the original's real rule was. That
        is exactly what 0x040C's 「これ以上アイテムを持ち歩くことはできません」
        refuses, which is why taking too much out of the locker has a real
        refusal to send while putting too much in does not.
        """
        if not exists(category, item_id) or count <= 0:
            return False
        for existing in self.rows:
            if existing[:2] == [category, item_id]:
                if existing[2] + count > ROW_MAX:
                    return False
                existing[2] += count
                return True
        if count > ROW_MAX:
            return False
        self.rows.append([category, item_id, count])
        return True

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
        self.take_off(category, item_id)
        return len(self.rows) != before

    def for_tab(self, tab: int) -> "list[list[int]]":
        """The rows this tab draws."""
        return filter_tab(self.rows, tab)

    def list_rows(self, rows: "list[list[int]]") -> bytes:
        return list_body(rows)

    def row_pages(self, rows: "list[list[int]]") -> "list[bytes]":
        return row_pages(rows)


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


class Locker:
    """What one ACCOUNT has put away, shared by all of its characters.

    ⭐⭐ ACCOUNT AND NOT CHARACTER, and the client's own refusal sentences are
    what settle it: the two locker-side refusals spend a reason each on
    「アカウントデータの取得に失敗しました。」 (0x0408 reason 1, 0x040C reason 2)
    while every refusal on the carried side says 「キャラクター情報」 -- 0x4D02,
    0x4D05, 0x4D08, 0x4D0C reason 0. Two different words for two different
    stores, written by the same hand into one file, for the two halves of one
    transfer. So the locker is where a player moves something to hand it to
    their own next character, which is also what a school locker is for.

    Rows are [categoryId, id, count], the same shape Inventory keeps and the
    same shape 0x0409 puts on the wire -- the two lists share a deserializer.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.rows: "list[list[int]]" = []
        for row in saved.get("stored") or ():
            try:
                category, item_id, count = (int(x) for x in row)
            except (TypeError, ValueError):
                continue
            if not exists(category, item_id):
                print(f"[item] locker {category}:{item_id} is not in item.bin or "
                      "item_skillbook.bin, dropping")
                continue
            if any(existing[:2] == [category, item_id] for existing in self.rows):
                continue
            self.rows.append([category, item_id, count & 0xFF])

    def to_json(self) -> dict:
        return {"stored": [list(row) for row in self.rows]}

    def summary(self) -> str:
        return (f"ロッカー {len(self.rows)} 種"
                if self.rows else "ロッカーは空")

    def full(self) -> bool:
        """⚠️ Always False while LOCKER_CAPACITY is None -- see that constant."""
        return LOCKER_CAPACITY is not None and len(self.rows) >= LOCKER_CAPACITY

    def held(self, category: int, item_id: int) -> int:
        for existing in self.rows:
            if existing[:2] == [category, item_id]:
                return existing[2]
        return 0

    def receive(self, category: int, item_id: int, count: int) -> bool:
        """Put ``count`` away. False if the row would overflow its u8 個数."""
        if not exists(category, item_id) or count <= 0:
            return False
        for existing in self.rows:
            if existing[:2] == [category, item_id]:
                if existing[2] + count > ROW_MAX:
                    return False
                existing[2] += count
                return True
        if count > ROW_MAX or self.full():
            return False
        self.rows.append([category, item_id, count])
        return True

    def take(self, category: int, item_id: int, count: int) -> "int | None":
        """Take ``count`` back out and return what is left, or None."""
        for index, existing in enumerate(self.rows):
            if existing[:2] != [category, item_id]:
                continue
            if count <= 0 or existing[2] < count:
                return None
            existing[2] -= count
            if existing[2] == 0:
                del self.rows[index]
            return existing[2]
        return None

    def for_tab(self, tab: int) -> "list[list[int]]":
        return filter_tab(self.rows, tab)


def _refusal(msg_type: int, reason: int) -> "tuple[list[tuple[int, bytes]], bool]":
    """One refusal and nothing written. Every path out of the four operations
    below goes through this or through a success, because the one thing none of
    them may do is return nothing -- an unanswered request wedges the window."""
    return ([(msg_type, struct.pack(">B", reason))], False)


def equip_replies(
    inv: "Inventory | None", chara_id: int, params: bytes
) -> "tuple[list[tuple[int, bytes]], bool]":
    """0x4D04 -> one or more 0x4D06, or 0x4D05. ``(replies, changed)``.

    ⭐ More than one 0x4D06 is the normal case for putting something on: the
    item that was in that slot comes off first and the client is told about it
    with equip=0, then the new one goes on with equip=1. See Inventory.wear for
    why there is a slot at all, and for the fact that the slot is invented.
    """
    fields = parse_equip(params)
    if inv is None:
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_NO_CHARACTER)
    if fields is None:
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_BAD_ITEM)
    category, item_id, equip = fields
    if not exists(category, item_id):
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_BAD_ITEM)
    if not inv.held(category, item_id):
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_NOT_HELD)
    if tab_of(category) != WEARABLE_TAB:
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_NOT_WEARABLE)
    worn = inv.is_worn(category, item_id)
    if equip and worn:
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_ALREADY_WORN)
    if not equip and not worn:
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_NOT_WORN)
    if not equip and not can_unequip(category, item_id):
        return _refusal(MSG_SV_ERROR_ITEM_EQUIP, EQUIP_CANNOT_REMOVE)
    replies = []
    if equip:
        for was_category, was_id in inv.wear(category, item_id):
            replies.append((MSG_SV_NOTIFY_ITEM_EQUIP,
                            equip_params(chara_id, was_category, was_id, 0)))
    else:
        inv.take_off(category, item_id)
    replies.append((MSG_SV_NOTIFY_ITEM_EQUIP,
                    equip_params(chara_id, category, item_id, 1 if equip else 0)))
    return (replies, True)


def equip_params(chara_id: int, category: int, item_id: int, equip: int) -> bytes:
    """0x4D06's body: charaId u32, itemId, equip u8."""
    return struct.pack(">IHHB", chara_id, category, item_id, equip)


def use_replies(
    inv: "Inventory | None", chara_id: int, params: bytes
) -> "tuple[list[tuple[int, bytes]], bool]":
    """0x4D07 -> 0x4D09, or 0x4D08.

    ⚠️ ONE PER PRESS. 0x4D07 carries no quantity -- it is the only message in
    the family that does not -- so using is not spinner-driven the way throwing
    out and putting away are, and the count that comes back is what is left.

    ⚠️ WHAT THE ITEM DOES IS NOT DECIDED HERE and does not show up in these
    replies: the decrement and the remainder are the whole of what 0x4D07 puts
    on the wire, and the ストレス or 能力 the item is worth (ITEM_EFFECTS) is
    applied against the character sheet by mps_session._item_effect, which is
    where the sheet is. ⭐ So a refusal above is also a refusal of the effect --
    there is one door and the count is what goes through it.

    ⭐⭐ AND THE QUESTION THIS DOCSTRING USED TO PARK THE WORK BEHIND IS
    ANSWERED WITHOUT A CLIENT. It used to read 「nobody has watched a live
    client to see whether 使用 has to be followed by 0x4811 / 0x4310」, which is
    an experiment; the same thing is settled by asking what code could carry
    the change instead. 0x4310 is the *answer* to the client's own 0x430F and
    the 0x43xx menu family has no notify at all, so an ability is re-read when
    the sheet is next opened and there is nothing to push; ストレス does have a
    push, and _push_vitals already sends it whenever the value moves. Two
    lookups, no server, no VM.
    """
    fields = parse_use(params)
    if inv is None:
        return _refusal(MSG_SV_ERROR_ITEM_USE, USE_NO_CHARACTER)
    if fields is None:
        return _refusal(MSG_SV_ERROR_ITEM_USE, USE_BAD_ITEM)
    category, item_id = fields
    if not exists(category, item_id):
        return _refusal(MSG_SV_ERROR_ITEM_USE, USE_BAD_ITEM)
    if tab_of(category) != CONSUMABLE_TAB:
        return _refusal(MSG_SV_ERROR_ITEM_USE, USE_NOT_USABLE)
    remain = inv.take(category, item_id, 1)
    if remain is None:
        return _refusal(MSG_SV_ERROR_ITEM_USE, USE_NOT_HELD)
    return ([(MSG_SV_NOTIFY_ITEM_USE,
              struct.pack(">IHHB", chara_id, category, item_id, remain))], True)


def del_replies(
    inv: "Inventory | None", params: bytes
) -> "tuple[list[tuple[int, bytes]], bool]":
    """0x4D0D -> 0x4D0E, or 0x4D0F.

    ⚠️ 0x4D0E echoes the request rather than reporting the remainder; the module
    docstring has the naming evidence for that reading and the experiment that
    can overturn it.
    """
    fields = parse_quantity(params)
    if inv is None:
        return _refusal(MSG_SV_NG_ITEM_DEL, DEL_NO_CHARACTER)
    if fields is None:
        return _refusal(MSG_SV_NG_ITEM_DEL, DEL_BAD_ITEM)
    category, item_id, count = fields
    if not exists(category, item_id) or count == 0:
        return _refusal(MSG_SV_NG_ITEM_DEL, DEL_BAD_ITEM)
    if not can_discard(category, item_id):
        return _refusal(MSG_SV_NG_ITEM_DEL, DEL_CANNOT_DROP)
    if inv.is_worn(category, item_id) and not can_unequip(category, item_id):
        return _refusal(MSG_SV_NG_ITEM_DEL, DEL_CANNOT_REMOVE)
    if inv.take(category, item_id, count) is None:
        return _refusal(MSG_SV_NG_ITEM_DEL, DEL_NOT_ENOUGH)
    return ([(MSG_SV_OK_ITEM_DEL,
              struct.pack(">HHH", category, item_id, count))], True)


def put_in_locker_replies(
    inv: "Inventory | None", locker: "Locker | None", params: bytes
) -> "tuple[list[tuple[int, bytes]], bool]":
    """0x4D0A -> 0x4D0B, or 0x4D0C.

    ⚠️ THE ONE OPERATION THAT TOUCHES BOTH STORES, so it is also the one that
    can half-succeed. The order is receive-then-take, with the receive undone if
    the take somehow fails: the outcome worth writing code to avoid is an item
    that left the character and never arrived, and putting the arrival first
    means the only reachable failure is the harmless direction.
    """
    fields = parse_quantity(params)
    if inv is None or locker is None:
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_NO_CHARACTER)
    if fields is None:
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_BAD_ITEM)
    category, item_id, count = fields
    if not exists(category, item_id) or count == 0:
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_BAD_ITEM)
    # ⚠️ NOT NO_DISCARD here: an undiscardable item still had
    # 「ロッカーにしまう」 live on screen, so the two flags are different bits
    # and PUT_NOT_STORABLE stays unsent. Only being stuck on the character
    # stops it.
    if inv.is_worn(category, item_id) and not can_unequip(category, item_id):
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_CANNOT_REMOVE)
    if inv.held(category, item_id) < count or count <= 0:
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_NOT_ENOUGH)
    if not locker.receive(category, item_id, count):
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_LOCKER_FULL)
    if inv.take(category, item_id, count) is None:      # cannot happen; see above
        locker.take(category, item_id, count)
        return _refusal(MSG_SV_NG_ITEM_PUT_IN_LOCKER, PUT_NOT_ENOUGH)
    return ([(MSG_SV_OK_ITEM_PUT_IN_LOCKER,
              struct.pack(">HHH", category, item_id, count))], True)


# ロッカー's own messages, 0x0400..0x040F. A different family id from the item
# window's because it is a different window -- opened off an NPC's menu
# (menu_item.bin row 403 ロッカー開く) rather than off the toolbar -- but the
# same rows, the same reader, and the store the item window's 「ロッカーに
# しまう」 button moves things into.
MSG_CL_REQUEST_LOCKER_ACCESS_START = 0x0400
MSG_SV_OK_LOCKER_ACCESS_START = 0x0401
MSG_SV_NG_LOCKER_ACCESS_START = 0x0402
MSG_CL_REQUEST_LOCKER_ACCESS_END = 0x0403
MSG_SV_OK_LOCKER_ACCESS_END = 0x0404
MSG_SV_NG_LOCKER_ACCESS_END = 0x0405
MSG_CL_QUERY_LOCKER_LIST = 0x0406
MSG_SV_RESULT_LOCKER_LIST = 0x0407
MSG_SV_ERROR_LOCKER_LIST = 0x0408
MSG_SV_NOTIFY_LOCKER_LIST = 0x0409
MSG_CL_REQUEST_LOCKER_TAKE = 0x040A
MSG_SV_OK_LOCKER_TAKE = 0x040B
MSG_SV_NG_LOCKER_TAKE = 0x040C
MSG_CL_REQUEST_LOCKER_DEL = 0x040D
MSG_SV_OK_LOCKER_DEL = 0x040E
MSG_SV_NG_LOCKER_DEL = 0x040F

# 0x0408 MsgSvErrorLockerList, three.
LOCKER_LIST_BAD_ITEM = 0    # 選択されたアイテムの情報が不正です。
LOCKER_LIST_NO_ACCOUNT = 1  # アカウントデータの取得に失敗しました。
LOCKER_LIST_NO_LIST = 2     # ロッカー内のアイテム一覧の取得に失敗しました。

# 0x040C MsgSvNgLockerTake, five. ⚠️ NOTE WHAT IS MISSING: there is no
# 「指定された個数を所持していません」 here, though both of the carried side's
# quantity refusals have one. Asking for more than the locker holds therefore
# goes out as reason 1, 「操作されたアイテムの情報が不正です。」 -- the request
# named a quantity that is not there, which is the closest sentence the client
# owns and is why this mapping is written down rather than left to look obvious.
TAKE_NO_CHARACTER = 0
TAKE_BAD_ITEM = 1
TAKE_NO_ACCOUNT = 2         # ⚠️ never sent: the store is always readable here
TAKE_NO_CHARACTER_DATA = 3  # ⚠️ never sent: same
TAKE_CANNOT_CARRY = 4       # これ以上アイテムを持ち歩くことはできません。

# 0x040F MsgSvNgLockerDel, four. Same gap as 0x040C, same mapping onto reason 1.
LOCKER_DEL_NO_CHARACTER = 0
LOCKER_DEL_BAD_ITEM = 1
LOCKER_DEL_NO_ACCOUNT = 2   # ⚠️ never sent
# ⚠️ reason 3 is 「選択されたアイテムは削除できないアイテムです。」 and NO_DISCARD
# is the obvious candidate -- but that flag was measured against 「捨てる」 in the
# item window, and this is a different verb in a different window that no click
# has ever reached. Left unsent rather than assumed to be the same bit.
LOCKER_DEL_UNDELETABLE = 3


def parse_locker_quantity(params: bytes) -> "tuple[int, int, int] | None":
    """``(categoryId, id, nNum)`` off 0x040A/0x040D's 2+2+**1**.

    ⭐⭐ ONE BYTE, NOT TWO, and that is not a typo on this side: the client's own
    readers say 2+2+2 for 0x4D0A/0x4D0D and 2+2+1 for 0x040A/0x040D. The pair
    that moves items OUT of the locker counts in a u8 and the pair that moves
    them IN counts in a u16, in the same game, for the same rows -- so a reader
    written once and reused for all four would be wrong for half of them.
    """
    if len(params) < 5:
        return None
    return struct.unpack_from(">HHB", params, 0)


def locker_list_replies(
    locker: "Locker | None", tab: int
) -> "list[tuple[int, bytes]]":
    """0x0406 -> 0x0407 + 0x0409, or 0x0408.

    ⚠️ THE u16 IS READ AS A TAB, by analogy with 0x4D00 and by nothing else.
    Both queries are one u16 answered by the same paging deserializer, and the
    locker window is the item window's other half, so the same six tabs are the
    only reading with anything behind it -- but no click has been watched here.
    ⭐ It is cheap to falsify the moment the window opens: a locker holding one
    item per category draws each row under exactly one tab if this is right.
    """
    if locker is None:
        return [(MSG_SV_ERROR_LOCKER_LIST,
                 struct.pack(">B", LOCKER_LIST_NO_ACCOUNT))]
    rows = locker.for_tab(tab)
    return ([(MSG_SV_RESULT_LOCKER_LIST, struct.pack(">H", len(rows)))]
            + [(MSG_SV_NOTIFY_LOCKER_LIST, page) for page in row_pages(rows)])


def locker_take_replies(
    inv: "Inventory | None", locker: "Locker | None", params: bytes
) -> "tuple[list[tuple[int, bytes]], bool]":
    """0x040A -> 0x040B, or 0x040C. The other direction of 0x4D0A.

    ⭐ This is where ROW_MAX earns its keep: 「これ以上アイテムを持ち歩くことは
    できません」 is a refusal this server can honestly send, because a carried
    row's 個数 is a u8 on the wire whatever the original's rules were.
    """
    fields = parse_locker_quantity(params)
    if inv is None or locker is None:
        return _refusal(MSG_SV_NG_LOCKER_TAKE, TAKE_NO_CHARACTER)
    if fields is None:
        return _refusal(MSG_SV_NG_LOCKER_TAKE, TAKE_BAD_ITEM)
    category, item_id, count = fields
    if not exists(category, item_id) or count == 0:
        return _refusal(MSG_SV_NG_LOCKER_TAKE, TAKE_BAD_ITEM)
    if locker.held(category, item_id) < count:
        return _refusal(MSG_SV_NG_LOCKER_TAKE, TAKE_BAD_ITEM)
    if not inv.receive(category, item_id, count):
        return _refusal(MSG_SV_NG_LOCKER_TAKE, TAKE_CANNOT_CARRY)
    if locker.take(category, item_id, count) is None:   # cannot happen; see above
        inv.take(category, item_id, count)
        return _refusal(MSG_SV_NG_LOCKER_TAKE, TAKE_BAD_ITEM)
    return ([(MSG_SV_OK_LOCKER_TAKE,
              struct.pack(">HHB", category, item_id, count))], True)


def locker_del_replies(
    locker: "Locker | None", params: bytes
) -> "tuple[list[tuple[int, bytes]], bool]":
    """0x040D -> 0x040E, or 0x040F. 捨てる without taking it out first."""
    fields = parse_locker_quantity(params)
    if locker is None:
        return _refusal(MSG_SV_NG_LOCKER_DEL, LOCKER_DEL_NO_CHARACTER)
    if fields is None:
        return _refusal(MSG_SV_NG_LOCKER_DEL, LOCKER_DEL_BAD_ITEM)
    category, item_id, count = fields
    if not exists(category, item_id) or count == 0:
        return _refusal(MSG_SV_NG_LOCKER_DEL, LOCKER_DEL_BAD_ITEM)
    if locker.take(category, item_id, count) is None:
        return _refusal(MSG_SV_NG_LOCKER_DEL, LOCKER_DEL_BAD_ITEM)
    return ([(MSG_SV_OK_LOCKER_DEL,
              struct.pack(">HHB", category, item_id, count))], True)
