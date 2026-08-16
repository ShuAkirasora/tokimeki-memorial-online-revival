"""クラブ: joining and leaving one, and the club a character shows as being in.

Two exchanges, both of them opened by the player right-clicking a club's
顧問 or キャプテン and picking 「入部／退部」 off the interaction menu:

    0x5A00 MsgClRequestClubEnter -> 0x5A01 MsgSvOkClubEnter
                                 -> 0x5A02 MsgSvNgClubEnter
    0x5A03 MsgClRequestClubPart  -> 0x5A04 MsgSvOkClubPart
                                 -> 0x5A05 MsgSvNgClubPart

Field names come from each class's own dump function, shapes from the
deserializer walk:

    0x5A00  clubId          u16
    0x5A01  (no parameters)
    0x5A02  reason u8, remain u16
    0x5A03  (no parameters)
    0x5A04  (no parameters)
    0x5A05  reason u8

⚠️ The client never says *which* club a 退部 is from, and it does not have to:
a character is in at most one, so 0x5A03 leaving no room for a clubId is the
protocol agreeing with 「所属クラブ」 being singular everywhere else.

That the request comes off an NPC is what makes ``clubId`` trustworthy without
the server checking it against anything: `p05_06` says 「右クリックしたＮＰＣが
所属するクラブに入部」, and `common_npc.bin` carries each キャプテン's club in
its own record — 石打 1, 大珠 2, 神野 3, 内海 4, matching `club.bin`'s 野球部,
バレーボール部, 陸上部, 水泳部. The client reads the id off the NPC it was
clicked on; it is not free text.

RESTORED, all of it
-------------------
Every rule below is read out of the client's own data rather than invented, the
same way お助けスキル's thresholds were. `error_message.bin` stores each record
as ``(u16 id, u16 message, u8 reason)`` followed by the sentence, so a refusal
string that exists is proof the original server had a reason code that selects
it, and the reason *is* the index within that message's own run of sentences.

0x5A02 入部, seven sentences:

    0  未使用: エラーなし
    1  未使用: parameters are wrong
    2  入部に失敗しました。
    3  サーバーとの通信に失敗しました。
    4  未使用: undefined error
    5  入部に失敗しました。           (same text as 2)
    6  退部してから１０日間が経過していません。

0x5A05 退部, seven sentences:

    0  未使用: エラーなし
    1  未使用: parameters are wrong
    2  退部に失敗しました。
    3  サーバーとの通信に失敗しました。
    4  未使用: undefined error
    5  退部に失敗しました。           (same text as 2)
    6  クラブ行事に参加している状態では退部できません。

⭐ Reason 6 on each side is the whole of the subsystem's policy, and each is
confirmed twice over. The ten-day wait appears in `p07_01` (「一度退部したクラブ
には、退部後１０日間経過しないと再入部できません」) and again in `p05_06`, and
here in the data. The 行事 lock appears *only* here — the manual says
「入退部は自由」 and never mentions it — which is the same shape as そっと応援's
undocumented threshold: the pages lag the build, the strings do not.

⚠️ There are no クラブ行事 on this server, so 0x5A05 reason 6 can never fire.
It is written down because the rule is real, not because anything reaches it.

Reasons 2 and 5 carry the same sentence, so the wire cannot tell them apart and
neither can the screen. Everything that is not the ten-day wait answers 2.

INVENTED — one field, and it is small
-------------------------------------
``remain``, the u16 riding along with 0x5A02. It exists only for reason 6, and
nothing says what unit it is in; the sentence it decorates counts 日, so days
is the reading this sends. ⚠️ NOT CONFIRMED ON SCREEN. If the refusal box ever
prints a number that is ten times what it should be, this is the field to
suspect — the other candidate is hours. Every other reason sends 0.

Which clubs a character may be in
---------------------------------
`club.bin` has sixteen records and `tmn::NUM_OF_CLUB` is 16, but only eight are
real: key 0 is 無所属, keys 1-8 are the clubs `p07_01` lists (野球, バレー,
陸上, 水泳 on the 体育系 side; 文芸, 科学, 総合演劇, 家庭科 on the 文化系
side), keys 9-14 are 未定部１…６ placeholders and key 15 is 番長. That split is
not a guess about the data — the ability sheet's 部活 tab draws exactly keys
1-8 and ignores the rest whatever they hold, which is the same eight arrived at
from the screen.

⚠️ Refuse anything outside 1-8 rather than storing it. Three client crashes so
far have all been the server sending a key its own tables do not have, and
``inClub`` goes straight into two records the client renders.

The day counter
---------------
The wait is measured in real calendar days, matching `romance.py`'s ``lastTalk``
— this server's clock is the host's wall clock and there is no separate in-game
calendar to count against.

キーワード, and what a 部活デッキ is made of
--------------------------------------------
A デッキ is a command list built out of キーワード and 部活奥義 (`p07_02`), and
until now this server owned neither, so every list and every deck went out
empty. The empty answer was right — a student who has just enrolled owns
nothing — but it also meant the client could never enable 「ＯＫ」 on the deck
window, which is the current suspect for why pressing 開始 in a 自主トレルーム
produces no battle. So キーワード are now grantable, and a deck can hold things.

⭐ THE ENTRY LAYOUT IS NOW SETTLED, out of the client's own reader rather than
by guessing. 0x5B01 and 0x5B03 share one deserializer (0x8D9430) and it reads:

    deckId  u8
    count   u16
    count × { kind u8, six bytes copied verbatim }
    useType u8

⚠️ This SUPERSEDES the earlier 「1+2+1+6+1, item layout unknown」 note. That
reading came from a linear walk that counted the loop body once and reported the
total as if the message were flat; the six bytes are not a field of the message,
they are the payload of one entry. Seven bytes per entry, and the six are
copied by the bulk reader (0xA49610) rather than parsed, which is what a union
looks like from the outside: whichever half of the window an item came from, its
own six bytes travel unexamined.

⭐⭐ The union is now MEASURED for the キーワード half: with four keywords
registered into デッキ３ the client sent kind = 0 and the same
(keywordId, useCount, clubSource) triple the 0x4305 row carries — ⚠️ but
LITTLE-ENDIAN, the only place in this protocol where anything is. The six bytes
are the client's in-memory struct, handed to the bulk copier rather than parsed
field by field, and the client is x86. See DECK_ITEM_KEYWORD.

That is also why this server stores the six bytes VERBATIM and echoes them back
instead of re-packing them: round-tripping bytes it has not parsed cannot send
the client a key its tables lack — the shape of all three crashes so far —
because every byte came from the client. The endianness being wrong in the log
for one round is exactly the kind of mistake that policy absorbs.

`keyword.bin`: 261 rows, and the ids are NOT 0-260
--------------------------------------------------
They arrive in six contiguous blocks on a stride of 150:

    0-39   150-183   300-345   450-502   600-645   750-791

Six blocks, and `drama_event_genre.bin` has exactly six rows (非部活系,
校舎外非部活系, 屋外運動部系, 屋内運動部・総演部系, 文化部系, 校外系), so the
stride is one block per genre with room to grow into. ⚠️ Anything outside the
blocks is not a key the client can look up; grants go through ``keyword_exists``
for the same reason ``inClub`` is range-checked.

⭐ Independent confirmation that these ids are what a deck holds:
`npc_clubdeck.bin` (200 rows, 「野球部初級攻撃系デッキ」 and friends) ends in a
58-byte tail that reads as 25 × u16 with 0xFFFF for an empty slot, and across
all 200 rows every one of the 2418 non-0xFFFF values in those 25 slots is a
legal keyword id — 25/25 slots at 100%. The four u16 after them are something
else (about half land outside the id set), and 25 is a deck's capacity as the
original filled it. NOT USED by anything here yet; it is the sample to check a
real deck against the day 練習 is implemented.

    0x4303 -> 0x4304 nNum u32
           -> 0x4305 list[count] × { keywordId u16, useCount u16,
                                     clubSource u16 }        6B, all three u16
                                                             read through +0x28

⭐ ``useCount`` is 習熟度 and the manual says how it moves: 「クラブ活動で
キーワードを使用するとアップする」, and it is drawn as a gauge rather than a
number, which is why the field is a count rather than a level. ⚠️ ITS FULL-SCALE
VALUE IS NOT MEASURED — nothing says what fills the gauge, so /kw takes it as an
argument instead of the server picking.

⚠️ ``clubSource`` is NOT a restriction. `p07_02` is explicit that キーワード do
not depend on a club (「キーワードはクラブに依存しないため、どちらの用途でも
全てのキーワードを登録することができます」), so it cannot be a filter on where
a keyword may be registered. The likeliest reading is 「取得できるクラブの素」 —
the synthesis item that keyword can yield, which the window hides behind ？？？
until it has been obtained once, and which therefore has to be per-character.
⚠️ THAT IS A GUESS. It goes out as 0 unless /kw is told otherwise.

INVENTED: that a character can own a キーワード at all
------------------------------------------------------
The ids, the wire layout and the field meanings above are restored. What is
invented is the grant: in the original a キーワード arrives by using one in
クラブ活動 until 習熟度 fills, and there is no クラブ活動 here to use one in. So
/kw is a knob in the same family as /ab and /card — it puts the character into a
state the original would have reached by playing, so that the screens which read
that state can be checked. Nothing on the wire is invented by it.
"""
from __future__ import annotations

import struct
from datetime import date

MSG_CL_REQUEST_CLUB_ENTER = 0x5A00
MSG_SV_OK_CLUB_ENTER = 0x5A01
MSG_SV_NG_CLUB_ENTER = 0x5A02
MSG_CL_REQUEST_CLUB_PART = 0x5A03
MSG_SV_OK_CLUB_PART = 0x5A04
MSG_SV_NG_CLUB_PART = 0x5A05

# The 部活デッキ window's two inventory queries. Both are opened by the second
# icon on the main toolbar — no NPC involved, which is what makes them the one
# part of this subsystem the player can reach right now.
#
# Each is a Query with no body answered by a Result carrying only a count and a
# separate Notify carrying the rows, the same split MsgSvResultLockerList and
# MsgSvNotifyLockerList use:
#
#     0x4303 -> 0x4304 nNum u32
#            -> 0x4305 list[count] = {keywordId, param{useCount, clubSource}}    6B
#     0x4306 -> 0x4307 nNum u32
#            -> 0x4308 list[count] = {clubSkillId{categoryId, id},
#                                     param{completeness}}                       5B
#
# ⭐ The 5-byte entry is a second, independent confirmation of the 4308 layout:
# categoryId u16 + id u16 + completeness u8 is exactly five, and `clubskill.bin`
# keys really are the pair (「1:0」重いコンダラ).
#
# ⚠️ THE 部活奥義 LIST WAS ALWAYS EMPTY, and that was a restored answer rather
# than a stub: 奥義 are obtained by 奥義合成 at a 顧問 out of an 「奥義の書」 and
# synthesis items, and none of those exist here. Same shape as 早弁's
# 「お弁当がない」 — the refusal is the original's, not a gap in ours. /cs now
# opens the same door /kw opened in the キーワード half, for the same kind of
# reason and with the same boundary: the grant is invented, the wire is not.
#
# ⭐ WHAT ``completeness`` MEANS IS RESTORED, from the manual rather than from
# the wire. `p07_02` lists it as one of three 部活奥義 parameters shown in the
# detail window a right-click opens (クラブ属性 / 完成度 / 性別属性), and
# `p07_05` says what it is and what it does:
#
#     完成度は、レベル１〜１０まであり、完成度が高くなればなるほど、
#     部活奥義の効果（攻撃力、成功率等）が上がります。
#
# It is decided once, at 奥義合成 time, by which consumable items went into the
# synthesis.
#
# ⭐⭐⭐ 1..10 IS THE DISPLAYED LEVEL, NOT THE ENCODING — the byte is a
# PERCENTAGE, and the window's レベル column draws
#
#     Lv = max(1, ceil(completeness / 10))
#
# with no upper clamp. MEASURED: ten rows in one list, one value each (/cs
# ruler). 10 → Lv.1 but 11 → Lv.2 rules out floor(c/10)+1 and rounding; 0 →
# Lv.1 gives the lower clamp; ⭐ 255 → Lv.26 shows there is no upper one. So
# 100 really is this field's full value — which is what every probe before
# this had been sending, and why nothing had ever seen the byte move.
#
# ⚠️⚠️ IT IS ALSO A FIELD THIS SERVER CANNOT CHECK BY PLAYING: everything the
# manual says it raises — damage dealt, the success rate of sleep/confusion,
# how far a パラメータダウン goes — is arithmetic the SERVER does. The client
# is only told the result, in 0x5C11. So the one place a client has to read
# this byte is the deck window, not a battle.
# ⚠️ And the manual is wrong about WHERE: it lists 完成度 among the parameters
# the right-click detail window shows, but that window has only クラブ属性 /
# 性別 / 説明文. 完成度 is the list's レベル column.
#
# The キーワード list is no longer always empty. It was, for the same reason,
# until it turned out to be the likely reason the deck window's ＯＫ never
# enables and so the likely reason 開始 in a 自主トレルーム does nothing; /kw
# grants them now. See the module docstring for what is restored (the ids, the
# layout, the field meanings) and what is invented (the grant).
MSG_CL_QUERY_KEYWORD_LIST = 0x4303
MSG_SV_RESULT_KEYWORD_LIST = 0x4304
MSG_SV_NOTIFY_KEYWORD_LIST = 0x4305
MSG_CL_QUERY_CLUB_SKILL_LIST = 0x4306
MSG_SV_RESULT_CLUB_SKILL_LIST = 0x4307
MSG_SV_NOTIFY_CLUB_SKILL_LIST = 0x4308

# The third query the same window makes, and the one that actually opens it.
# Measured live: clicking the toolbar icon sends 0x4303 once, 0x4306 twice, then
# 0x5B00 over and over until it is answered — the client retries this one.
#
#     0x5B00 MsgClQueryClubDeckList    deckId u8
#       -> 0x5B01 MsgSvResultClubDeckList
#            deckId u8, clubDeck{item[count]={kind, …}}, useType u8
#       -> 0x5B02 MsgSvErrorClubDeckList  reason u8
#
# ⭐ THE ITEM LAYOUT IS SETTLED: ``kind u8`` then six bytes copied verbatim,
# seven per entry, read out of the shared deserializer at 0x8D9430. The earlier
# 「1+2+1+6+1, unknown」 note is SUPERSEDED — see the module docstring. This
# server stores the six bytes as they arrived and echoes them back rather than
# interpreting them, so nothing here can hand the client a key it lacks.
#
# ⭐⭐ ``useType`` IS A BIT FIELD, and all four values have been read back off
# the screen — the window draws it as two checkboxes at its bottom right:
#
#     0x00  neither          デッキ3, both boxes empty
#     0x01  部活用           デッキ2 after ticking only 部活用
#     0x02  行事用           デッキ1 once the client moved 部活用 away
#     0x03  both             the state all three start in
#
# ⭐ The client spells the byte itself in 0x5B03, which is the only place it
# ever does; answering 0x5B03 is what makes the boxes settable at all, so this
# could not be measured until MSG_SV_OK_CLUB_DECK_UPDATE existed.
#
# ⭐⭐ The client also enforces 「one deck per use」 on its own: ticking 部活用
# on deck 1 made it send 0x01 for deck 1 **and 0x02 for deck 0**, taking the bit
# off the deck that had it. That is `error_message.bin` 482
# (「部活用もしくは行事用の部活デッキが複数存在します」) seen from the client
# side, and it means a server that simply stores what it is told cannot violate
# that rule — the client never asks it to.
#
# ⚠️ 0xFF is NOT a fourth state. Sending it draws both boxes ticked (the same
# as 0x03) but the client normalises it away: with 0xFF on all three decks it
# reported 0x03 / 0x00 / 0x00 back. Do not read the earlier 「0xFF is what the
# client reports」 note as an encoding — that reading is superseded.
MSG_CL_QUERY_CLUB_DECK_LIST = 0x5B00
MSG_SV_RESULT_CLUB_DECK_LIST = 0x5B01
MSG_SV_ERROR_CLUB_DECK_LIST = 0x5B02

# 「更 新」 in the same window. Same body as 0x5B01, which is what makes it the
# measuring instrument for useType: whatever the client believes a deck's use
# to be, it spells it here in the byte we cannot otherwise read.
#
#     0x5B03 MsgClRequestClubDeckUpdate  deckId u8, clubDeck{…}, useType u8
#       -> 0x5B04 MsgSvOkClubDeckUpdate  deckId u8
#       -> 0x5B05 MsgSvNgClubDeckUpdate  reason u8, errorDeckItemNum[count]
#
# ⚠️ One press of 更新 sends one of these PER DECK, three in all, not just for
# the deck on screen.
#
# The first reading taken here — that the 0xFF the client sent for all three
# decks was an encoding for 「both boxes ticked」 — is SUPERSEDED. It was 0xFF
# because the server had sent 0xFF, and the client normalises that away; see
# the bit-field block above for what the byte actually holds.
DECK_COUNT = 3
MSG_CL_REQUEST_CLUB_DECK_UPDATE = 0x5B03
MSG_SV_OK_CLUB_DECK_UPDATE = 0x5B04
MSG_SV_NG_CLUB_DECK_UPDATE = 0x5B05

# The two bits, and the state a deck starts in. RESTORED: every one of the four
# combinations was read off the checkboxes, see the block above.
USE_TYPE_NONE = 0x00
USE_TYPE_PRACTICE = 0x01  # 部活用
USE_TYPE_EVENT = 0x02  # 行事用

# `club.bin` in key order. Index is the wire value of inClub.
CLUB_NAMES = (
    "無所属",
    "野球部",
    "バレーボール部",
    "陸上部",
    "水泳部",
    "文芸部",
    "科学部",
    "総合演劇部",
    "家庭科部",
    "未定部１",
    "未定部２",
    "未定部３",
    "未定部４",
    "未定部５",
    "未定部６",
    "番長",
)

NO_CLUB = 0
FIRST_CLUB = 1
LAST_CLUB = 8  # 家庭科部; 9 and up are placeholders, see the module docstring

# `keyword.bin`'s 261 keys, as the six blocks they actually come in. See the
# module docstring: the stride is 150 and there is one block per
# `drama_event_genre`, so the gaps are room the original left rather than a
# reading error. Inclusive on both ends.
KEYWORD_BLOCKS = (
    (0, 39),      # 非部活系
    (150, 183),   # 校舎外非部活系
    (300, 345),   # 屋外運動部系
    (450, 502),   # 屋内運動部・総演部系
    (600, 645),   # 文化部系
    (750, 791),   # 校外系
)
KEYWORD_COUNT = sum(last - first + 1 for first, last in KEYWORD_BLOCKS)  # 261

# `clubskill.bin`'s 57 keys. The key is the pair (categoryId, id) and the
# category is the club, so this is simply "how many 部活奥義 each club has":
# seven each, except 野球部 which has eight. Indexed by categoryId, and
# category 0 does not exist (FIRST_CLUB is 1), so the first entry is a hole.
CLUB_SKILL_PER_CLUB = (0, 8, 7, 7, 7, 7, 7, 7, 7)
CLUB_SKILL_COUNT = sum(CLUB_SKILL_PER_CLUB)  # 57

# What /cs ruler hands out, one 部活奥義 per value. Chosen to tell readings of
# ``completeness`` apart on one screen rather than to walk a range: the manual
# calls it a level from 1 to 10, so the run 1/2/5/9/10 shows whether the byte
# is drawn as itself, 0 and 11 sit just outside it, 100 is what every probe so
# far has sent, and 255 is the whole byte. ⚠️ Values, not steps — §3.1: ask
# what it drives before asking how to convert it.
CLUB_SKILL_RULER = (1, 2, 5, 9, 10, 0, 11, 50, 100, 255)

# One entry of a デッキ on the wire: ``kind`` and then six bytes this server
# stores without interpreting.
#
# ⭐⭐ kind = 0 IS キーワード, MEASURED: with ids 0/1/2/3 all at useCount 32
# registered into デッキ３, the client sent kind=0 four times with payloads
# 000020000000 / 010020000000 / 020020000000 / 030020000000.
#
# ⚠️⚠️ AND THOSE ARE LITTLE-ENDIAN — the only little-endian field group in this
# whole protocol. `0000`/`0100`/`0200`/`0300` are ids 0-3 and `2000` is 32, both
# byte-swapped relative to every other message. The reason is that the six bytes
# are never parsed as message fields: the deserialiser hands them to the bulk
# copier (0xA49610) and the client is x86, so what travels is its in-memory
# struct. That also settles the union — the struct is the same
# (keywordId, useCount, clubSource) triple the 0x4305 row carries, which the
# client read big-endian off the wire and now writes back host-order.
#
# ⭐⭐ kind = 1 IS 部活奥義, MEASURED — and the first four of the six bytes are
# the `clubskill.bin` key, `categoryId u16` then `id u16`, same little-endian.
# Nothing here can own one, so no 0x5B03 has ever carried one; what settled it
# was doctoring a live 0x5C0E instead (`/cb card`, see Battle.card_probe). Sent
# `01 00 00 00 64 00`, the client read it back out of its own data file and
# said 「野球部奥義【重いコンダラ】を使用した！」 — that skill's own sentence,
# which is row 1:0 of the table.
#
# ⚠️ The LAST TWO bytes are still unread: every probe so far sent `64 00` and
# nothing on screen depended on them.
DECK_ITEM_BYTES = 6
DECK_ITEM_KEYWORD = 0
DECK_ITEM_CLUB_SKILL = 1
# 25 slots is what `npc_clubdeck.bin` uses; see the module docstring. ⚠️ Used
# only to refuse an absurd count, not as a rule the client is known to obey.
DECK_CAPACITY = 25

# error_message.bin 462: the sentence counts 日.
REJOIN_DAYS = 10

# Reason codes, both messages. Named for what the sentence says, not for what
# the server means by sending it.
NG_ENTER_FAILED = 2
NG_ENTER_REJOIN_WAIT = 6
NG_PART_FAILED = 2
NG_PART_IN_EVENT = 6

# 0x5B05, twelve sentences — the whole of the deck-update rulebook, restored the
# same way. Only the two this server can reach are named; the rest are listed
# here so the next round does not have to look them up again.
#
#     0  この用途では登録できない部活奥義がある
#     1  そのキーワードは既に登録されている
#     2  その部活奥義は既に登録されている
#     3  その部活奥義には性別制限がある
#     4  「部活用」に所属クラブ以外の部活奥義は登録できない
#     5  未使用: パラメータが不正
#     6  そのキーワードを所持していない
#     7  その部活奥義を所持していない
#     8  部活用もしくは行事用の部活デッキが複数存在する
#     9  部活デッキの登録内容を変更できなかった
#    10  選択された部活デッキが見つからない
#    11  未使用: 未定義のエラー
NG_DECK_KEYWORD_NOT_OWNED = 6
NG_DECK_NOT_FOUND = 10


def name(club_id: int) -> str:
    """The club's own name, or a marker if the id is not one `club.bin` has."""
    if 0 <= club_id < len(CLUB_NAMES):
        return CLUB_NAMES[club_id]
    return f"?{club_id}"


def keyword_exists(keyword_id: int) -> bool:
    """Is this a key `keyword.bin` actually has? See KEYWORD_BLOCKS."""
    return any(first <= keyword_id <= last for first, last in KEYWORD_BLOCKS)


def keyword_ids() -> "list[int]":
    """Every legal キーワード id, in order."""
    return [i for first, last in KEYWORD_BLOCKS for i in range(first, last + 1)]


def club_skill_exists(category: int, skill_id: int) -> bool:
    """Is this a key `clubskill.bin` actually has? See CLUB_SKILL_PER_CLUB."""
    if not 0 <= category < len(CLUB_SKILL_PER_CLUB):
        return False
    return 0 <= skill_id < CLUB_SKILL_PER_CLUB[category]


def club_skill_keys() -> "list[tuple[int, int]]":
    """Every legal 部活奥義 key, in `clubskill.bin` order."""
    return [(category, skill_id)
            for category, count in enumerate(CLUB_SKILL_PER_CLUB)
            for skill_id in range(count)]


def playable(club_id: int) -> bool:
    """One of the eight a character can actually join."""
    return FIRST_CLUB <= club_id <= LAST_CLUB


class Membership:
    """One character's クラブ state: which one, and when each was left.

    Stored on the character record under "club" and rebuilt from that dict each
    time, the same arrangement Romance, ScoreCard and AbilitySheet use.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.in_club = int(saved.get("inClub", NO_CLUB))
        if not (self.in_club == NO_CLUB or playable(self.in_club)):
            # A file written by hand, or by a future version with more clubs.
            # Dropping to 無所属 beats sending a key the client cannot look up.
            print(f"[club] inClub {self.in_club} is not a joinable club, reading as 無所属")
            self.in_club = NO_CLUB
        left = saved.get("left")
        self.left: "dict[int, str]" = {}
        if isinstance(left, dict):
            for key, value in left.items():
                try:
                    self.left[int(key)] = str(value)
                except (TypeError, ValueError):
                    continue
        # Per-deck useType, kept only so that what the player set comes back on
        # the next 0x5B01. The decks themselves are still always empty.
        decks = saved.get("deckUse")
        self.deck_use: "dict[int, int]" = {}
        if isinstance(decks, dict):
            for key, value in decks.items():
                try:
                    self.deck_use[int(key)] = int(value) & 0xFF
                except (TypeError, ValueError):
                    continue
        # Owned キーワード, in the order 0x4305 will send them: one
        # [keywordId, useCount, clubSource] triple per row. A key the client's
        # own table does not have is dropped rather than sent on, the same
        # treatment inClub gets and for the same reason.
        self.keywords: "list[list[int]]" = []
        for row in saved.get("keywords") or ():
            try:
                keyword_id, use_count, club_source = (int(x) for x in row)
            except (TypeError, ValueError):
                continue
            if not keyword_exists(keyword_id):
                print(f"[club] keyword {keyword_id} is not in keyword.bin, dropping")
                continue
            if any(existing[0] == keyword_id for existing in self.keywords):
                continue
            self.keywords.append([keyword_id, use_count & 0xFFFF, club_source & 0xFFFF])
        # Owned 部活奥義, in the order 0x4308 will send them: one
        # [categoryId, id, completeness] triple per row. Same treatment as
        # キーワード — a key `clubskill.bin` does not have is dropped rather
        # than sent on.
        self.skills: "list[list[int]]" = []
        for row in saved.get("clubSkills") or ():
            try:
                category, skill_id, completeness = (int(x) for x in row)
            except (TypeError, ValueError):
                continue
            if not club_skill_exists(category, skill_id):
                print(f"[club] club skill {category}:{skill_id} is not in "
                      "clubskill.bin, dropping")
                continue
            if any(existing[:2] == [category, skill_id] for existing in self.skills):
                continue
            self.skills.append([category, skill_id, completeness & 0xFF])
        # Deck contents, as {deckId: [[kind, six-byte payload as hex], …]}. Hex
        # rather than a parsed record on purpose: the payload is a union this
        # server does not read, and storing it verbatim is what makes echoing it
        # back safe. See the module docstring.
        self.deck_items: "dict[int, list[list]]" = {}
        stored = saved.get("deckItems")
        if isinstance(stored, dict):
            for key, rows in stored.items():
                try:
                    deck_id = int(key)
                except (TypeError, ValueError):
                    continue
                items: "list[list]" = []
                for row in rows or ():
                    try:
                        kind, payload = int(row[0]) & 0xFF, bytes.fromhex(str(row[1]))
                    except (TypeError, ValueError, IndexError):
                        continue
                    if len(payload) == DECK_ITEM_BYTES:
                        items.append([kind, payload.hex()])
                if items:
                    self.deck_items[deck_id] = items

    def to_json(self) -> dict:
        return {
            "inClub": self.in_club,
            "left": {str(key): value for key, value in sorted(self.left.items())},
            "deckUse": {str(key): value for key, value in sorted(self.deck_use.items())},
            "keywords": [list(row) for row in self.keywords],
            "clubSkills": [list(row) for row in self.skills],
            "deckItems": {
                str(key): [list(row) for row in value]
                for key, value in sorted(self.deck_items.items())
            },
        }

    # ------------------------------------------------------------ キーワード

    def owns_keyword(self, keyword_id: int) -> bool:
        return any(row[0] == keyword_id for row in self.keywords)

    def grant_keyword(self, keyword_id: int, use_count: int = 0,
                      club_source: int = 0) -> bool:
        """Give this character a キーワード, or update the one it already has.

        Returns False for a key `keyword.bin` does not have. INVENTED that this
        happens at all — see the module docstring; the original fills 習熟度 by
        playing クラブ活動, which does not exist here.
        """
        if not keyword_exists(keyword_id):
            return False
        row = [keyword_id, use_count & 0xFFFF, club_source & 0xFFFF]
        for index, existing in enumerate(self.keywords):
            if existing[0] == keyword_id:
                self.keywords[index] = row
                return True
        self.keywords.append(row)
        return True

    def revoke_keyword(self, keyword_id: int) -> bool:
        before = len(self.keywords)
        self.keywords = [row for row in self.keywords if row[0] != keyword_id]
        return len(self.keywords) != before

    def keyword_rows(self) -> bytes:
        """0x4305's body: count u16 then six bytes per row."""
        out = struct.pack(">H", len(self.keywords))
        for keyword_id, use_count, club_source in self.keywords:
            out += struct.pack(">HHH", keyword_id, use_count, club_source)
        return out

    # ------------------------------------------------------------ 部活奥義

    def grant_club_skill(self, category: int, skill_id: int,
                         completeness: int = 1) -> bool:
        """Give this character a 部活奥義, or update the one it already has.

        Returns False for a key `clubskill.bin` does not have. INVENTED that
        this happens at all, exactly as for grant_keyword and for the same
        reason: the original gets here through 奥義合成 at a 顧問, out of an
        「奥義の書」 and synthesis items, and none of those exist here.
        """
        if not club_skill_exists(category, skill_id):
            return False
        row = [category, skill_id, completeness & 0xFF]
        for index, existing in enumerate(self.skills):
            if existing[:2] == [category, skill_id]:
                self.skills[index] = row
                return True
        self.skills.append(row)
        return True

    def revoke_club_skill(self, category: int, skill_id: int) -> bool:
        before = len(self.skills)
        self.skills = [row for row in self.skills if row[:2] != [category, skill_id]]
        return len(self.skills) != before

    def club_skill_rows(self) -> bytes:
        """0x4308's body: count u16 then five bytes per row.

        ⚠️ BIG-ENDIAN, unlike the deck payload for the same 部活奥義. These are
        message fields and go through the ordinary readers; the six bytes in a
        デッキ entry are an opaque blob and are little-endian. See
        DECK_ITEM_KEYWORD for how that was caught.
        """
        out = struct.pack(">H", len(self.skills))
        for category, skill_id, completeness in self.skills:
            out += struct.pack(">HHB", category, skill_id, completeness)
        return out

    # ------------------------------------------------------------ 部活デッキ

    def deck(self, deck_id: int) -> "list[list]":
        return self.deck_items.get(deck_id, [])

    def keyword_deck_item(self, keyword_id: int) -> "tuple[int, bytes] | None":
        """Build the entry the client would have sent for an owned キーワード.

        ⚠️ LITTLE-ENDIAN on purpose — see DECK_ITEM_KEYWORD. This is the one
        place that composes a payload rather than echoing one, so it is also the
        one place the endianness reading can be wrong in a way that shows up on
        screen. Only an owned keyword can go in: a deck entry for something the
        キーワード list did not mention is a key the client cannot look up.
        """
        for owned_id, use_count, club_source in self.keywords:
            if owned_id == keyword_id:
                return (DECK_ITEM_KEYWORD,
                        struct.pack("<HHH", owned_id, use_count, club_source))
        return None

    def club_skill_deck_item(self, category: int,
                             skill_id: int) -> "tuple[int, bytes] | None":
        """The same, for an owned 部活奥義.

        ⚠️ LITTLE-ENDIAN like the キーワード branch, and one byte shorter than
        the six the union holds: 0x4308's row is categoryId u16 + id u16 +
        completeness u8, which is five. The sixth byte is what the union costs
        to hold the six-byte キーワード branch, so it goes out as zero — every
        probe so far has sent it as zero too, and nothing has ever read it.
        """
        for owned_category, owned_id, completeness in self.skills:
            if (owned_category, owned_id) == (category, skill_id):
                return (DECK_ITEM_CLUB_SKILL,
                        struct.pack("<HHBB", owned_category, owned_id,
                                    completeness, 0))
        return None

    def set_deck(self, deck_id: int, items: "list[tuple[int, bytes]]") -> None:
        if items:
            self.deck_items[deck_id] = [[kind, payload.hex()] for kind, payload in items]
        else:
            self.deck_items.pop(deck_id, None)

    def use_type(self, deck_id: int) -> int:
        """What to report for this deck, defaulting to what the client sends."""
        return self.deck_use.get(deck_id, USE_TYPE_NONE)

    def days_since_leaving(self, club_id: int, today: "date | None" = None) -> "int | None":
        """Days since this club was last left, or None if it never was."""
        stamp = self.left.get(club_id)
        if not stamp:
            return None
        try:
            then = date.fromisoformat(stamp)
        except ValueError:
            # An unparseable stamp should not lock a club forever.
            print(f"[club] cannot read leave date {stamp!r} for {name(club_id)}, ignoring it")
            return None
        return ((today or date.today()) - then).days

    def enter_refusal(self, club_id: int, today: "date | None" = None
                      ) -> "tuple[int, int] | None":
        """``(reason, remain)`` to refuse this 入部 with, or None to allow it.

        Order matters only in that the ten-day wait is the specific answer and
        everything else falls to 2; no request can trip both.
        """
        if not playable(club_id):
            return (NG_ENTER_FAILED, 0)
        if self.in_club != NO_CLUB:
            # Already in one. The original had no sentence for this because the
            # menu on a 顧問 offers 退部 rather than 入部 once you are a member,
            # so it is a state the client is not expected to ask from.
            return (NG_ENTER_FAILED, 0)
        since = self.days_since_leaving(club_id, today)
        if since is not None and since < REJOIN_DAYS:
            return (NG_ENTER_REJOIN_WAIT, REJOIN_DAYS - since)
        return None

    def enter(self, club_id: int) -> None:
        """Join. Callers check ``enter_refusal`` first."""
        self.in_club = club_id
        # The stamp is spent: rejoining clears the wait it was there to enforce.
        self.left.pop(club_id, None)

    def part_refusal(self) -> "int | None":
        """A reason to refuse this 退部, or None to allow it."""
        if self.in_club == NO_CLUB:
            return NG_PART_FAILED
        return None

    def part(self, today: "date | None" = None) -> int:
        """Leave, stamping today so the ten-day wait can be measured.

        Returns the club just left.
        """
        left = self.in_club
        if left != NO_CLUB:
            self.left[left] = (today or date.today()).isoformat()
        self.in_club = NO_CLUB
        return left

    def summary(self) -> str:
        waits = " ".join(
            f"{name(club_id)}:{stamp}" for club_id, stamp in sorted(self.left.items())
        )
        decks = " ".join(
            f"{deck_id}:{len(self.deck(deck_id))}枚/{self.use_type(deck_id):#04x}"
            for deck_id in range(DECK_COUNT)
        )
        return (f"クラブ {name(self.in_club)}"
                + (f" | 退部 {waits}" if waits else "")
                + f" | キーワード {len(self.keywords)}"
                + f" | 奥義 {len(self.skills)}"
                + f" | デッキ {decks}")


def ng_enter_params(reason: int, remain: int = 0) -> bytes:
    """0x5A02 MsgSvNgClubEnter: reason u8, remain u16."""
    return struct.pack(">BH", reason & 0xFF, max(0, min(0xFFFF, remain)))


def ng_part_params(reason: int) -> bytes:
    """0x5A05 MsgSvNgClubPart: reason u8."""
    return struct.pack(">B", reason & 0xFF)


def keyword_replies(member: "Membership | None") -> "list[tuple[int, bytes]]":
    """The two messages the キーワード inventory query is answered with.

    The Result's count and the Notify's count are the same number said twice, so
    both come off one list and cannot drift apart.
    """
    rows = member.keyword_rows() if member is not None else struct.pack(">H", 0)
    owned = struct.unpack_from(">H", rows, 0)[0]
    return [(MSG_SV_RESULT_KEYWORD_LIST, struct.pack(">I", owned)),
            (MSG_SV_NOTIFY_KEYWORD_LIST, rows)]


def skill_replies(member: "Membership | None") -> "list[tuple[int, bytes]]":
    """Same, for the 部活奥義 half of the window."""
    rows = member.club_skill_rows() if member is not None else struct.pack(">H", 0)
    owned = struct.unpack_from(">H", rows, 0)[0]
    return [(MSG_SV_RESULT_CLUB_SKILL_LIST, struct.pack(">I", owned)),
            (MSG_SV_NOTIFY_CLUB_SKILL_LIST, rows)]


def deck_reply(deck_id: int, use_type: int = USE_TYPE_NONE,
               items: "list[list] | None" = None) -> bytes:
    """0x5B01: deckId u8, count u16, count × (kind u8 + 6 bytes), useType u8.

    ``items`` is what ``Membership.deck`` stores — (kind, payload-as-hex) pairs
    that came off a 0x5B03 unchanged. Anything that is not six bytes long is
    dropped rather than padded: a short payload would desynchronise the client's
    reader for every entry after it.
    """
    body = b""
    count = 0
    for kind, payload_hex in items or ():
        payload = bytes.fromhex(payload_hex)
        if len(payload) != DECK_ITEM_BYTES:
            continue
        body += struct.pack(">B", kind & 0xFF) + payload
        count += 1
    return (struct.pack(">BH", deck_id & 0xFF, count) + body
            + struct.pack(">B", use_type & 0xFF))


def parse_deck_query(params: bytes) -> int:
    """0x5B00's deckId. Absent body reads as deck 0, which is what it asks for."""
    return params[0] if params else 0


def parse_deck_update(params: bytes) -> "tuple[int, list[tuple[int, bytes]], int] | None":
    """0x5B03 -> ``(deckId, items, useType)``, or None if the body does not fit.

    ``items`` is (kind, six raw bytes) per entry, exactly as the client sent
    them. The whole body has to add up — deckId u8 + count u16 + count × 7 +
    useType u8 — and a length that does not is refused rather than truncated,
    because a wrong count read as right would store garbage under a deck the
    player is about to see.
    """
    if len(params) < 4:
        return None
    deck_id, count = struct.unpack_from(">BH", params, 0)
    if count > DECK_CAPACITY:
        return None
    entry = 1 + DECK_ITEM_BYTES
    if len(params) != 3 + count * entry + 1:
        return None
    items: "list[tuple[int, bytes]]" = []
    for index in range(count):
        at = 3 + index * entry
        items.append((params[at], params[at + 1:at + entry]))
    return (deck_id, items, params[-1])


def describe_deck_item(kind: int, payload: bytes) -> str:
    """One log line for an entry, decoded as well as raw.

    ⚠️⚠️ LITTLE-ENDIAN, and that is measured rather than assumed — see
    DECK_ITEM_KEYWORD. Everything else in this protocol is big-endian; these six
    bytes are not, because they are never parsed as message fields. The payload
    is stored and re-sent verbatim whatever this prints, so a wrong reading here
    could not corrupt a deck — which is how the endianness got caught.
    """
    raw = f"kind={kind} payload={payload.hex()}"
    if len(payload) != DECK_ITEM_BYTES:
        return raw
    if kind == DECK_ITEM_KEYWORD:
        keyword_id, use_count, club_source = struct.unpack("<HHH", payload)
        known = "" if keyword_exists(keyword_id) else " NOT IN keyword.bin"
        return (f"{raw} (keyword id={keyword_id}{known} "
                f"useCount={use_count} clubSource={club_source})")
    if kind == DECK_ITEM_CLUB_SKILL:
        # ⭐ The first two u16 ARE MEASURED — they are the `clubskill.bin` key,
        # and the client names the skill they point at (see DECK_ITEM_KEYWORD).
        # ⚠️ The remaining byte-and-a-half is not: `completeness` follows the
        # 0x4308 row (5B) plus one byte, and every probe so far sent 100.
        category, skill_id, completeness = struct.unpack("<HHB", payload[:5])
        return (f"{raw} (clubSkill? {category}:{skill_id} "
                f"completeness={completeness} tail={payload[5]:#04x})")
    return raw


def parse_enter(params: bytes) -> "int | None":
    """0x5A00's clubId, or None if the body is not the one u16 it should be."""
    if len(params) < 2:
        return None
    return struct.unpack_from(">H", params, 0)[0]
