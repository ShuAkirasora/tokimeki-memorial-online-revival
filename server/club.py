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

⭐⭐⭐ Six blocks, one per 能力属性 -- the field the client draws in the
キーワード detail window as 「能力属性」 and the manual defines (p07_02) as
「クラブ活動中に使用した場合に、アップする能力パラメータの種類」. The block a
key falls in is also written in the record at `+0x2c`, and the client feeds
that byte to `chara_ability_type.bin`'s accessor (0x7b26b1 -> 0x7b2e82 ->
0x7e6f91, which reads manager member +0x68 = that table). Its six rows are
文系 / 理系 / 芸術 / 雑学 / 運動 / スタミナ, and the contents agree throughout:
0-39 is 文芸部・新聞部, 150-183 科学部・ＰＣ, 300-345 総合演劇部・軽音,
450-502 家庭科・料理・放送, 600-645 the four sports clubs, 750-791 合宿・食.

⚠️⚠️ This paragraph used to read 「one block per `drama_event_genre.bin` row」.
That was wrong and only ever rested on both tables having six rows: a drama
event's genre and its keyword's block are not in step (`un032`, genre 1
校舎外非部活系, hands out 600 心眼キャッチ, which is block 4). Corrected in
round 198.

⚠️ Anything outside the blocks is not a key the client can look up; grants go
through ``keyword_exists`` for the same reason ``inClub`` is range-checked.

⭐ Independent confirmation that these ids are what a deck holds:
`npc_clubdeck.bin` (200 rows, 「野球部初級攻撃系デッキ」 and friends) ends in a
58-byte tail, and part of it is キーワード ids.

⚠️⚠️ THIS PARAGRAPH USED TO READ 「25 × u16, and all 2418 non-0xFFFF values
across the 200 rows are legal keyword ids — 25/25 slots at 100%」. That was
WRONG, and it is worth recording HOW it was wrong, because the number looked
perfect. A 部活奥義 is keyed by a PAIR, `categoryId` 1..8 then `id` 0..7, and
BOTH of those land inside the keyword block 0..39 — so 「is it a legal keyword
id」 is a ruler that cannot fail on this tail no matter what is in it. Checking
against a second ruler (the 57 keys of `clubskill.bin`) is what took it apart.
Corrected in round 200.

The tail is three runs, each of which does check out with no exceptions:

    +0x00  u16          always 0
    +0x02  u16 × 8      キーワード id, 0xFFFF for an empty slot
    +0x12  (u16,u16)×8  部活奥義 key, 0xFFFFFFFF for an empty slot;
                        the categoryId is always this deck's own club
    +0x32  u8  × 8      完成度 (percent) of the 部活奥義 in that slot, 0 if empty

So a deck as the original filled it is 8 キーワード + 8 部活奥義, not 25 of
anything. ⚠️ That is what the NPC table holds; it is NOT a measurement of what
the CLIENT will accept, so it is not a reason to move DECK_CAPACITY.

⭐ The 完成度 run is also a second witness for the deck item's fifth byte: see
DECK_ITEM_CLUB_SKILL below, where every probe so far has sent 0x64 without
knowing what it was. 0x64 is 100, and 100 is this field's full value.

NOT USED by anything here yet; it is the sample to check a real deck against
the day 練習 is implemented.

    0x4303 -> 0x4304 nNum u32
           -> 0x4305 list[count] × { keywordId u16, useCount u16,
                                     clubSource u16 }        6B, all three u16
                                                             read through +0x28

⭐ ``useCount`` is 習熟度 and the manual says how it moves: 「クラブ活動で
キーワードを使用するとアップする」, and it is drawn as a gauge rather than a
number, which is why the field is a count rather than a level.

⭐⭐⭐ ROUND 196: its full scale IS measured now, and it is per-keyword —
`keyword.bin` record +0x78, the byte the client divides `useCount` by. Four
values across the 261 rows (64 for 251 of them, then 80/90/100), and the gauge
fills exactly at it. See KEYWORD_FULL_SCALE. ⚠️ What one *use* adds is NOT
measured and never will be from this side -- round 198 put a decided number
there instead (USE_COUNT_PER_USE), framed as the invention it is. /kw goes on
taking `useCount` as an argument: a probe that can only add 1 at a time cannot
put a row at 満 to look at.

⚠️ ``clubSource`` is NOT a restriction. `p07_02` is explicit that キーワード do
not depend on a club (「キーワードはクラブに依存しないため、どちらの用途でも
全てのキーワードを登録することができます」), so it cannot be a filter on where
a keyword may be registered. The likeliest reading is 「取得できるクラブの素」 —
the synthesis item that keyword can yield, which the window hides behind ？？？
until it has been obtained once, and which therefore has to be per-character.
⚠️ THAT IS A GUESS. It goes out as 0 unless /kw is told otherwise.

RESTORED in round 193: how a キーワード is granted
--------------------------------------------------
⭐⭐⭐ This heading used to read 「INVENTED: that a character can own a
キーワード at all」. It does not any more, because the original's own grant is
in the scripts: `PC_KEYWORD_UPDATE` (0x8185), 127 of them across 38 scenarios,
whose slot operand is `keywordId << 5`. Both チュートリアル open a character's
account with six of them — one per category below, each chosen by a coin flip
between two — and 36 ドラマイベント hand out two to six more. The wiring is
`mps_session._script_keywords`; the reading and its evidence are 2.150.

⚠️ **What is still invented is 習熟度**, and only that: in the original
`use_count` is filled by using a キーワード in クラブ活動 until it rises.
⭐ Round 196 took the ceiling off that (KEYWORD_FULL_SCALE is measured), and
round 198 wired the rest of it up: 自主トレ now raises the count for every card
it plays (mps_session._battle_mastery). So what is left invented is the STEP and
nothing else -- see USE_COUNT_PER_USE. A grant still lands at `use_count = 0`,
which is the honest value rather than a flattering one.

⭐ /kw stays, and its job is unchanged: it is a knob in the same family as /ab
and /card — it puts a character into a state the original would have reached by
playing, so that the screens which read that state can be checked. ⚠️ It is no
longer the *only* way in, so 「this character has キーワード」 is no longer
evidence that somebody typed one.
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

# How many rows one 0x4308 may carry. Not a guess, and no longer just a
# measurement either: it is the capacity of a fixed array inside the client's
# own message class. Its deserializer stores the row count at +0xC4 and the
# rows from +0x04 at six bytes each (five on the wire, one byte of padding),
# so the array is exactly (0xC4 - 4) / 6 == 32 entries long, with the count
# sitting immediately behind it and no bounds check anywhere.
#
# That is also why row 33 hangs rather than crashes: its first field lands on
# the count itself, and the loop re-reads the count every iteration, so it
# stops early and the remaining bytes are never consumed.
# (Membership.club_skill_row_pages records how the limit was first measured.)
CLUB_SKILL_LIST_PAGE = 32

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

# ⭐⭐⭐ 習熟度's full scale, MEASURED in round 196. It is per-keyword and it
# lives in the client's own table: `keyword.bin` record +0x78, one byte, which
# the client divides `useCount` by to get the gauge's fill ratio:
#
#     0x0049fdf2  movzx eax, word ptr [eax + 2]      ; useCount, from 0x4305
#     0x0049fdf9  movzx eax, byte ptr [ebx + 0x78]   ; this keyword's full scale
#     0x0049fdfd  fild  dword ptr [ebp - 0x18]       ; float(useCount)
#     0x0049fe08  fidiv dword ptr [ebp - 0x18]       ; useCount / full scale
#     0x0049fe0b  fstp  dword ptr [ecx + 0x14]       ; -> the gauge widget
#
# The column takes four values across all 261 rows, 64 being the default, and
# the ten exceptions below are the ones the original made harder to master.
# ⭐ The boundary is on the screen, not inferred: at 満 − 1 the bar stops short
# and at 満 it jumps to full, checked at all four values (see 2.152).
# ⚠️ This says what fills the gauge. It does NOT say how much one use adds --
# that number is the server's and nothing here knows it yet.
KEYWORD_FULL_SCALE_DEFAULT = 64
KEYWORD_FULL_SCALE = {
    0: 80,    # ベストエンドは二人の秘密
    38: 90,   # 嘘からでた真
    183: 90,  # 人生のワイルドカード
    345: 90,  # ラテンの心
    502: 80,  # ジャーナリズムの血
    624: 80,  # チームワークの勝利
    633: 80,  # 好敵手と書いて『とも』と読む
    645: 100,  # ワンフォアオール
    762: 80,  # 悪への怒りは爆発寸前
    791: 90,  # マウス・トゥ・マウス
}

# ⚠️⚠️ INVENTED — how much one use of a キーワード adds to its 習熟度.
# ⚠️ (the smallest-invention rule), and it is the ONLY invented number in this
# loop — everything else around it is restored. How much one use of a
# キーワード in クラブ活動 adds to its 習熟度.
#
# ⭐ WHERE IT WAS LOOKED FOR AND NOT FOUND, so nobody repeats the search:
#   - the client: every offset it reads out of `keyword.bin` was enumerated in
#     round 196 (+0x00 +0x02 +0x2c +0x2e +0x30 +0x6c +0x78) and none is a step;
#     習熟 is decided server-side, so the client cannot know this number;
#   - the manual: p07_02 and p08_01 say 「使用するとアップする」 and 「何度も
#     使い」 — that it counts USES rather than battles, but never how much;
#   - the operator-era player material mirrored here (fansites, press, video):
#     zero hits for 習熟 of any kind.
#
# ⭐ WHY 1 RATHER THAN ANYTHING ELSE — the choice that invents least:
#   1 makes KEYWORD_FULL_SCALE mean exactly what it reads like, a number of
#   uses; any other step adds a second made-up number on top of a restored
#   table. It also lands on every scale exactly (a step of 3 would overshoot
#   64, 80 and 100), and the default 64 comes out as 8 uses × 8 battles, where
#   8 is the RESTORED turn limit (clubbattle.TURN_LIMIT). Pacing, for the
#   record: 8 battles to master one keyword if it is played every single turn,
#   about 22 at three plays a battle.
#
# ⭐ WHAT WOULD OVERTURN IT (the invention rule asks for this in writing): any operator-era
# source that counts plays or battles to a 習熟度 MAX; a surviving server-side
# table; or a client build that displays 習熟度 as a number instead of a gauge.
USE_COUNT_PER_USE = 1

# ⚠️ INVENTED alongside it, and a separate decision: 習熟度 stops at the full
# scale rather than counting on past it. It is not only a gate — p07_02 says
# 「『習熟度』が高いと、キーワードによる攻撃や防御のパワーがアップします」 —
# so a count that kept climbing would keep raising a keyword's power with
# nothing on screen to show it. 「習熟度がＭＡＸになると」 reads as a finished
# state, and this makes it one.
USE_COUNT_CLAMPS_AT_FULL_SCALE = True

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
# far has sent, and 255 is the whole byte. ⚠️ Values, not steps — the ruler rule: ask
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
# ⚠️ Used only to refuse an absurd count, not as a rule the client is known to
# obey. It was originally read off `npc_clubdeck.bin` as 「25 slots」, and round
# 200 took that reading apart (see the module docstring: the NPC decks are
# 8 + 8). The number is LEFT AS IT WAS ON PURPOSE — nothing measured what the
# client's own deck window will accept, so lowering the sanity limit to 16
# would be inventing a restriction, not restoring one.
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


def keyword_full_scale(keyword_id: int) -> int:
    """`useCount` at which this キーワード's 習熟度 gauge reads full.

    See KEYWORD_FULL_SCALE: the value is the client's own, read out of
    `keyword.bin` and confirmed on the screen at all four of its values.
    ⚠️ Nothing sends 0x5C17 on reaching it yet -- see the module docstring.
    """
    return KEYWORD_FULL_SCALE.get(keyword_id, KEYWORD_FULL_SCALE_DEFAULT)


def use_count_after_use(use_count: int, keyword_id: int) -> int:
    """What one play of this キーワード in クラブ活動 leaves 習熟度 at.

    ⚠️ The step is INVENTED and the clamp is a second decision -- both are
    argued where they are defined, USE_COUNT_PER_USE just above.
    ⭐ WIRED UP in round 198: mps_session._battle_mastery calls this for every
    card in a 0x5C0E action stream and stores what comes back. ⚠️ Once per
    turn -- a replayed stream is not a second use (clubbattle.Battle.mastery_turn).
    """
    full = keyword_full_scale(keyword_id)
    raised = use_count + USE_COUNT_PER_USE
    return min(raised, full) if USE_COUNT_CLAMPS_AT_FULL_SCALE else raised


def keyword_is_mastered(use_count: int, keyword_id: int) -> bool:
    """Has this キーワード reached 習熟度 MAX -- the gauge full, 0x5C17 due?"""
    return use_count >= keyword_full_scale(keyword_id)


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

        Returns False for a key `keyword.bin` does not have.

        ⭐ Round 193: the *grant* is no longer invented — the scripts do it
        themselves through `PC_KEYWORD_UPDATE`, and this is the method they
        reach (`mps_session._script_keywords`, 2.150). ⭐ Round 198: a granted
        row no longer stays at 0 either — playing the card in 自主トレ raises it
        (`mps_session._battle_mastery`). ⚠️ What one use adds is still the one
        invented number in that loop; see the module docstring.
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

    def club_skill_rows(self, rows: "list[list] | None" = None) -> bytes:
        """0x4308's body: count u16 then five bytes per row.

        ⚠️ BIG-ENDIAN, unlike the deck payload for the same 部活奥義. These are
        message fields and go through the ordinary readers; the six bytes in a
        デッキ entry are an opaque blob and are little-endian. See
        DECK_ITEM_KEYWORD for how that was caught.
        """
        rows = self.skills if rows is None else rows
        out = struct.pack(">H", len(rows))
        for category, skill_id, completeness in rows:
            out += struct.pack(">HHB", category, skill_id, completeness)
        return out

    def club_skill_row_pages(self) -> "list[bytes]":
        """The same body, split into messages the client's reader can hold.

        ⚠️ A single 0x4308 carrying more than CLUB_SKILL_LIST_PAGE rows hangs
        the client for good: the 部活デッキ window never opens, 通信中 stays up,
        and the 0x5B00 that normally follows is never sent. Measured on the
        real client, one row at a time: 32 rows fine, 33 rows hung. Paging is
        what 0x4307 is for — it carries the total on its own, so the notify
        does not have to be the whole list in one message.
        """
        pages = []
        for start in range(0, max(len(self.skills), 1), CLUB_SKILL_LIST_PAGE):
            pages.append(self.club_skill_rows(
                self.skills[start:start + CLUB_SKILL_LIST_PAGE]))
        return pages

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
    """Same, for the 部活奥義 half of the window.

    One Result carrying the total, then as many notifies as the list needs --
    see Membership.club_skill_row_pages for why it cannot go in one.
    """
    pages = (member.club_skill_row_pages() if member is not None
             else [struct.pack(">H", 0)])
    owned = sum(struct.unpack_from(">H", page, 0)[0] for page in pages)
    return ([(MSG_SV_RESULT_CLUB_SKILL_LIST, struct.pack(">I", owned))]
            + [(MSG_SV_NOTIFY_CLUB_SKILL_LIST, page) for page in pages])


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
