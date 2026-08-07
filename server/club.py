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
# ⚠️ BOTH LISTS ARE EMPTY, and that is a restored answer rather than a stub.
# キーワード are earned by using them in クラブ活動 and 部活奥義 by 奥義合成 at
# a 顧問; this server has neither, so a character owns none of either. `p07_02`
# is explicit that a デッキ is built out of these two lists, so an empty pair is
# what the original sent a student who had just enrolled. Same shape as 早弁's
# 「お弁当がない」: the refusal is the original's, not a gap in ours.
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
# ⚠️ THE ITEM LAYOUT IS NOT SETTLED. listshape reports 1+2+1+6+1 for the whole
# message and the dump names only `kind` inside the entry, so the six bytes
# after it are unaccounted for — and listshape has mis-split a fixed inner loop
# twice before (the 試験 family). Sending an EMPTY deck sidesteps it entirely:
# with count = 0 the loop body is never on the wire, so the reply is
# deckId u8 + count u16 + useType u8 and nothing is being guessed.
#
# That is also the honest content. A deck is built out of キーワード and
# 部活奥義 (`p07_02`), a character here owns none of either, so every deck is
# empty — the same reasoning as the two lists above.
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

    def to_json(self) -> dict:
        return {
            "inClub": self.in_club,
            "left": {str(key): value for key, value in sorted(self.left.items())},
            "deckUse": {str(key): value for key, value in sorted(self.deck_use.items())},
        }

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
        return f"クラブ {name(self.in_club)}" + (f" | 退部 {waits}" if waits else "")


def ng_enter_params(reason: int, remain: int = 0) -> bytes:
    """0x5A02 MsgSvNgClubEnter: reason u8, remain u16."""
    return struct.pack(">BH", reason & 0xFF, max(0, min(0xFFFF, remain)))


def ng_part_params(reason: int) -> bytes:
    """0x5A05 MsgSvNgClubPart: reason u8."""
    return struct.pack(">B", reason & 0xFF)


def inventory_replies(owned: int = 0) -> "list[tuple[int, bytes]]":
    """The two messages one 部活デッキ inventory query is answered with.

    ``owned`` is the row count; there is no path to a non-zero one yet, and it
    is a parameter so that the day there is, the Result and the Notify cannot
    drift apart — they are the same number said twice.
    """
    return [(MSG_SV_RESULT_KEYWORD_LIST, struct.pack(">I", owned)),
            (MSG_SV_NOTIFY_KEYWORD_LIST, struct.pack(">H", owned))]


def skill_replies(owned: int = 0) -> "list[tuple[int, bytes]]":
    """Same, for the 部活奥義 half of the window."""
    return [(MSG_SV_RESULT_CLUB_SKILL_LIST, struct.pack(">I", owned)),
            (MSG_SV_NOTIFY_CLUB_SKILL_LIST, struct.pack(">H", owned))]


def deck_reply(deck_id: int, use_type: int = USE_TYPE_NONE) -> bytes:
    """0x5B01 for an empty deck: deckId u8, count u16 = 0, useType u8."""
    return struct.pack(">BHB", deck_id & 0xFF, 0, use_type & 0xFF)


def parse_deck_query(params: bytes) -> int:
    """0x5B00's deckId. Absent body reads as deck 0, which is what it asks for."""
    return params[0] if params else 0


def parse_deck_update(params: bytes) -> "tuple[int, int, int] | None":
    """0x5B03 -> ``(deckId, itemCount, useType)``, or None if it is not our shape.

    ⚠️ Only the empty-deck form is read: deckId u8 + count u16 + useType u8.
    A non-zero count means the client put items in, and the entry layout is not
    settled (see above) — say so rather than mis-parse it.
    """
    if len(params) < 4:
        return None
    deck_id, count = struct.unpack_from(">BH", params, 0)
    if count:
        return (deck_id, count, params[-1])
    return (deck_id, 0, params[3])


def parse_enter(params: bytes) -> "int | None":
    """0x5A00's clubId, or None if the body is not the one u16 it should be."""
    if len(params) < 2:
        return None
    return struct.unpack_from(">H", params, 0)[0]
