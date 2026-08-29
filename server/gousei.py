"""部活奥義の体得: 奥義合成, the 0x53xx family.

The last segment of a chain the rest of which was already running. p07_05 draws
it in one line -- キーワード played in クラブ活動 yield 合成アイテム, a 練習 win
yields an 奥義の書, and the book's recipe turns the materials into one of the 57
部活奥義 -- and every link but this one has been on screen since round 223.

    顧問やキャプテンの交流メニュー中の「奥義合成」から、「奥義の書」と合成アイテム
    を使って部活奥義を合成できます。

WHAT THE MANUAL SETTLES, sentence by sentence, because most of this module is
restoration and it is worth being able to see which parts are not:

  * 「『奥義の書』には部活奥義を合成するためのレシピが書いてあり、そのレシピ通りの
    合成アイテムを用意する必要があります」
        -- the recipe lives on the BOOK, which is why `item_skillbook.bin` and
           not `clubskill.bin` is the table this reads (2.158 三).
  * 「部活レベルによって合成できるアイテムの種類数が決まっていますので、規定レベル
    に達していないとアイテムが揃っていても合成はできません」, with the screenshot
    caption 「部活レベルが低いために合成できるアイテムの種類が2種類までに制限され
    ています。そのため、たとえアイテムを全部そろえていても、この奥義は合成できま
    せん」
        -- ⭐⭐⭐ MEASURED round 226: the number is drawn in the 奥義合成 window
           as 「N／M」 where M is 0x5301's nGouseiEntryMax and N is how many
           KINDS are currently registered, and the client refuses the one that
           would make N exceed M with a line of its own (「アイテムの種類が
           多すぎます」). So the cap counts registered kinds -- recipe materials
           and 消費アイテム TOGETHER -- and the caption's player is refused
           because the recipe cannot fit under M, not by a separate rule.
           ⇒ both checks live in _gousei: too many registered is reason 7, and
           a recipe that cannot fit under M is reason 7 as well, because that
           is the case the caption's sentence is about.
           clubbattle.gousei_entry_max owns the number.
  * 「部活レベルに応じた成功率で部活奥義の合成が成功します」
        -- a success roll exists and 部活レベル is its input. The CURVE is
           invented; see GOUSEI_RATE_MIN.
  * 「合成する際、消費アイテムを加えると、加えたアイテムの種類や数によって完成度が
    変動します（登録可能な消費アイテムは最大３種類です）。完成度は、レベル１〜１０
    まであり、完成度が高くなればなるほど、部活奥義の効果（攻撃力、成功率等）が上が
    ります。この消費アイテム（種類や適切な個数）は「奥義の書」には書かれていません
    ので、完成度を上げたい場合は、プレイヤー自身が合成を繰り返して見つけていく必要
    があります」
        -- ⭐⭐⭐ 完成度 IS 1-10 ON SCREEN, RESTORED. ⚠️⚠️ NOT ON THE WIRE: 2.86
           二 measured Lv = max(1, ceil(completeness / 10)), so 0x5307 carries a
           PERCENTAGE. See COMPLETENESS_PER_LEVEL -- round 226 sent the manual's
           number down the wire unconverted and the screen said Lv.1.
           The rule that MOVES it is invented and cannot be otherwise: the
           original deliberately did not write it down.
  * 「● 部活奥義の合成に失敗すると / 登録した「奥義の書」・合成アイテム・消費アイテム
    が全てなくなります」
        -- ⭐⭐⭐ failure eats EVERYTHING INCLUDING THE BOOK. The client ships the
           same sentence (msg_text 501 「合成に失敗しました！\\n登録アイテムは、
           すべてなくなりました」), so this is two witnesses and not one.
        -- ⚠️ That paragraph is in the 正式 manual and NOT in the β one, which
           is the asymmetry the invention rule�� warns about: β is an abridged edition, not
           an older one, and only the client can prove an absence. Here the
           client proves the presence.

WHAT THE REFUSAL TABLE SETTLES. `error_message.bin` 318-341 is, as usual, a rule
sheet rather than wording -- it names the conditions the original checked and,
by the codes it does NOT have, some it did not:

  * 0x5302 (the door) has codes for 「not in this club」 and 「already open」 and
    ⭐⭐⭐ NO CODE FOR 怪我, where the 練習 door one message away has one
    (0x5D02 reason 11 「怪我をしているため、部活に参加できません」).
  * p05_09 says the same thing from the other side: its ストレス list has three
    entries (授業・試験 / クラブ活動 / 奥義合成) and its 体調不良 list has two,
    naming 授業や試験 for ノイローゼ and クラブ活動 for 怪我. 奥義合成 is on
    neither.
    ⇒ ⭐⭐ TWO INDEPENDENT WITNESSES, from a table and from prose: 合成 COSTS
      ストレス BUT DOES NOT BREAK YOU, AND BEING BROKEN DOES NOT BAR IT. So
      stress.after_gousei charges without a break, and nothing here consults
      stress.barred_from_club. ⚠️ This is deliberately not symmetric with
      trainingroom.py and _npcbattle, both of which do bar 怪我 -- see an earlier lesson:
      the missing code is a reading, and the reading has a second witness.
  * 0x5308 reason 6 (「登録された合成アイテムを所持していない…」) is marked
    未使用 in the table, so the original never sent it. That is legible: the
    合成 window is filled from the player's own inventory, so 「you do not hold
    what you just registered」 cannot arise from play. It can arise from a
    /raw probe here, and the code sent for it is reason 12 「アイテムデータの
    操作…に失敗しました」, which is what a consumption that could not happen is.

THE WIRE, read out of the deserializers rather than off the field names -- 2.179
三 cost a round to the assumption that a field called npcId is the same width in
two messages, so every width below was taken from the reader itself:

    0x5300 MsgClRequestGouseiStart   u32 npcId          0x8D86A0, call [eax+0x24]
    0x5301 MsgSvOkGouseiStart        u8  nGouseiEntryMax
    0x5302 MsgSvNgGouseiStart        u8  reason
    0x5303 MsgClRequestGouseiEnd     (empty)
    0x5304 MsgSvOkGouseiEnd          (empty)
    0x5305 MsgSvNgGouseiEnd          (empty)  ⚠️ see NG_END_BODY
    0x5306 MsgClRequestGousei        u16 bookCategoryId, u16 bookId, u16 n,
                                     n x (u16 categoryId, u16 id, u8 count)
    0x5307 MsgSvOkGousei             u16 skillCategoryId, u16 skillId, u8 完成度
    0x5308 MsgSvNgGousei             u8  reason
    0x5309 MsgSvNotifyGouseiEnd      (empty)

⭐⭐⭐ 0x5306's ENTRY IS FIVE BYTES, not the nine `the shape reader` reports. 0x910F90
reads two u16 into [msg+4] and [msg+6], one u16 into [msg+0x44], and then loops
(u16, u16, u8) six bytes apart from [msg+8] -- so the 9 is this classifier adding
the four-byte prefix to the five-byte entry, the same kind of mistake it made on
0x5606 and 0x5C05. 2.87 一 said not to copy that number, and it was right.
⚠️ Incidentally measured: the client's own array is TEN entries ((0x44-8)/6), so
ten is the most it can ever put on the wire.

⭐⭐ THE FLAT LIST DOES NOT SAY WHICH ENTRY IS WHICH, and it does not have to:
p07_05 has two kinds of thing going into one window -- 合成アイテム (the recipe)
and 消費アイテム (the 完成度 booster) -- and the wire carries one undifferentiated
itemInfo[]. The RECIPE is what separates them. Anything the book names is a
material, anything else is a booster, and that is a partition the server can
compute rather than a field it has to be told.

⚠️⚠️ ONE THING DOES NOT ADD UP AND IS LEFT UNRESOLVED: a recipe may use eight
kinds and the manual allows three boosters, which is eleven, and the client's
array holds ten. ⭐ Round 224 narrowed it without closing it -- since the 「N／M」
counter is over ALL registered kinds, eleven can only ever be asked for by a
player at nGouseiEntryMax 11, which the 2-to-8 ramp never reaches. So the two
caps cannot both be saturated in the first place, and nothing here has to pick
which end to bend.
"""
from __future__ import annotations

import os
import struct

MSG_CL_REQUEST_GOUSEI_START = 0x5300
MSG_SV_OK_GOUSEI_START = 0x5301
MSG_SV_NG_GOUSEI_START = 0x5302
MSG_CL_REQUEST_GOUSEI_END = 0x5303
MSG_SV_OK_GOUSEI_END = 0x5304
MSG_SV_NG_GOUSEI_END = 0x5305
MSG_CL_REQUEST_GOUSEI = 0x5306
MSG_SV_OK_GOUSEI = 0x5307
MSG_SV_NG_GOUSEI = 0x5308
MSG_SV_NOTIFY_GOUSEI_END = 0x5309

# 0x5302, `error_message.bin` 318-324. The two marked 未使用 are named so that
# 「there is no code for this」 stays distinguishable from 「I did not look」.
START_NO_PLAYER = 0     # プレイヤー情報が不正です。
START_BAD_NPC = 1       # 選択されたＮＰＣの情報が不正です。
START_NOT_IN_CLUB = 2   # このクラブに所属していませんので、奥義合成はできません。
START_NO_SUPPORT = 3    # 未使用：：：現在、顧問・キャプテンとの交流機能は…
START_CANNOT_NOW = 4    # 現在、部活奥義を合成することはできません。
START_ALREADY = 5       # 既に部活奥義を合成できる状態になっています。
START_UNDEFINED = 6     # 未使用：：：未定義のエラーが発生しました。

# 0x5305, `error_message.bin` 325-327. ⚠️ NAMED BUT NEVER SENT AS BYTES -- see
# NG_END_BODY. Kept because the wording is what says the End is stateful.
END_NO_PLAYER = 0       # プレイヤー情報が不正です。
END_NOT_STARTED = 1     # 部活奥義の合成は開始されていません。
END_UNDEFINED = 2       # 未使用：：：未定義のエラーが発生しました。

# 0x5308, `error_message.bin` 328-341.
NG_NO_PLAYER = 0        # プレイヤー情報が不正です。
NG_BAD_NPC = 1          # 未使用：：：選択されたＮＰＣの情報が不正です。
NG_NO_SUPPORT = 2       # 未使用：：：現在、顧問・キャプテンとの交流機能は…
NG_CANNOT_NOW = 3       # 現在、部活奥義を合成することはできません。
NG_BAD_BOOK = 4         # 「奥義の書」の情報が不正です。
NG_BOOK_NOT_HELD = 5    # 選択された「奥義の書」を所持していません。
NG_MAT_NOT_HELD = 6     # 未使用：：：登録された合成アイテムを所持していない…
NG_TOO_MANY_KINDS = 7   # これ以上合成アイテムを登録することはできません。
                        # （部活レベルが足りません）
NG_WRONG_RECIPE = 8     # 合成アイテムの組み合わせが間違っています。
NG_OVER_CAPACITY = 9    # 未使用：：：所持アイテム限界数を超えた
NG_ID_LIST_FAILED = 10  # サーバーエラーが発生しました。（IDリスト取得失敗）
NG_BOOK_CONTENT = 11    # 奥義の書の内容が正常でない
NG_WRITE_FAILED = 12    # アイテムデータの操作もしくは部活奥義データの登録に失敗…
NG_UNDEFINED = 13       # 未使用：：：未定義のエラーが発生しました。

#: ⚠️⚠️ 0x5305 GOES OUT EMPTY, and the two witnesses disagree about that. The
#: class's own dump string prints `reason=%d`, so a byte was clearly intended;
#: the deserializer at the client end reads nothing at all (the shape reader: `empty`).
#: The reader wins, because it is what decides whether a byte is looked at --
#: 2.9's rule, and the same one that settled 0x5306's entry width. So the reason
#: constants above are for the log, and the wire carries none of them.
NG_END_BODY = b""

#: ⭐⭐⭐ RESTORED: 完成度 は、レベル１〜１０まであり (p07_05, both editions).
#: The floor is also restored, by the same sentence read the other way: 消費
#: アイテム are what MOVE it, so a 合成 without any is at the bottom of the range.
LEVEL_MIN = 1
LEVEL_MAX = 10

#: ⚠️⚠️ AND THE WIRE IS NOT IN THOSE UNITS. 2.86 二 measured the conversion with
#: a ten-value ruler and no exceptions: the 部活デッキ window draws
#: ``Lv = max(1, ceil(completeness / 10))``, so 10 shows as Lv.1, 11 as Lv.2,
#: 100 as Lv.10 and 255 as Lv.26 -- the byte is a PERCENTAGE and 「レベル１〜
#: １０」 is the display layer folding it into ten.
#: ⚠️ Round 224 sent the manual's 1-10 straight down this wire and the screen
#: said Lv.1 for a 完成度 of 4, which is the whole reason this constant exists.
#: ⭐ The lesson generalises: a manual's number is in the PLAYER's units and a
#: measured conversion outranks it for the wire -- the manual is still the
#: semantic authority (an earlier lesson), it is simply not talking about bytes.
COMPLETENESS_PER_LEVEL = 10
COMPLETENESS_MIN = LEVEL_MIN * COMPLETENESS_PER_LEVEL
COMPLETENESS_MAX = LEVEL_MAX * COMPLETENESS_PER_LEVEL

#: ⭐ RESTORED: 登録可能な消費アイテムは最大３種類です (p07_05, 正式 only -- the β
#: page stops one clause earlier). ⚠️ Not refused with, because no code in the
#: 0x5308 table says it and the client is what enforces registration; kinds
#: beyond this are simply not counted toward 完成度, and the log says so.
BOOSTER_KINDS_MAX = 3

# ── INVENTED — 合成 の成功率 (「部活レベルに応じた成功率」, p07_05) ──────────
#: The manual says a success rate exists and that 部活レベル is what it depends
#: on. It gives no figure, and nothing in the client's tables is a 合成 rate.
#:
#: ⭐⭐ THE RULER IS NOT INVENTED, only the line drawn on it. `clubskill.bin`
#: +0xc3 is this game's own idea of a percentage success rate and its 57 rows
#: take six values: 40, 50, 60, 70, 80, 100. So 40 is the lowest odds this game
#: is willing to offer a player and 100 is the top, and a 合成 rate outside that
#: range would be in a unit the game does not use (the invention rule��).
#: ⭐ INEQUALITIES it has to satisfy, in the order they bind: rate rises with
#: 部活レベル (the manual's only statement about it) · rate ∈ [40, 100] (the
#: ruler) · a brand-new member (部活レベル 0) can still succeed sometimes,
#: because 練習 hands out books long before level 99 and a book that can never
#: be used is a dead item · a maxed club reaches certainty, because the ruler's
#: top value is 100 and 44 of its 57 rows sit there.
#: ⭐ The straight line between the two ends is the smallest thing that
#: satisfies all four (the invention rule��). The tightest of them is the ruler.
#: ⭐ What would overturn it: any account, screenshot or 攻略 page naming an
#: observed 合成 success rate at a known 部活レベル.
#: Knob: TMO_CLUB_GOUSEI_RATE_MIN / TMO_CLUB_GOUSEI_RATE_MAX.
GOUSEI_RATE_MIN = max(0, min(100, int(
    os.environ.get("TMO_CLUB_GOUSEI_RATE_MIN") or 40)))
#: ⚠️ INVENTED — the top end of that same line: the 成功率 a maxed 部活レベル
#: reaches. 100 is the ruler's own top value and where 44 of `clubskill.bin`'s
#: 57 rows sit. See GOUSEI_RATE_MIN for the inequalities and the redemption.
#: Knob: TMO_CLUB_GOUSEI_RATE_MAX.
GOUSEI_RATE_MAX = max(0, min(100, int(
    os.environ.get("TMO_CLUB_GOUSEI_RATE_MAX") or 100)))

#: ⚠️ INVENTED — how much one 消費アイテム moves 完成度, and this one is invented
#: BY DESIGN AT THE OTHER END TOO: 「この消費アイテム（種類や適切な個数）は「奥義
#: の書」には書かれていませんので、…プレイヤー自身が合成を繰り返して見つけていく
#: 必要があります」. The original hid the rule from the player on purpose, so
#: there is no page anywhere that could carry it and no table it could be read
#: off. ⛔️ That makes it the one number here that cannot be redeemed by finding
#: a better source, only by an account of what someone actually observed.
#: ⭐ INEQUALITIES: 完成度 ∈ [1, 10] (restored) · no boosters ⇒ exactly 1
#: (restored, read off 「加えると…変動します」) · non-decreasing in the number of
#: KINDS and in the number of items, because the manual names both 「種類や数」 ·
#: DETERMINISTIC, because 「繰り返して見つけていく」 is only possible if there is
#: something stable to find · reachable, because a ceiling nobody can touch is
#: the same as not having one.
#: ⭐ 1 + kinds + total is the smallest expression satisfying all five, and its
#: tightest constraint is the last: the maximum arrives at three kinds of two,
#: which is exactly the 3-kind registration limit being fully used.
#: ⚠️ The manual's 「適切な個数」 hints that the original had a right ANSWER per
#: book rather than a monotone ramp. That is a different shape, not a different
#: number, and it stays unbuilt rather than half-built -- the invention rule��'s Ⅲ.
#: ⚠️ In DISPLAY levels, not in wire units -- the invented rule is stated in the
#: units the manual and the player use, and completeness() converts once at the
#: end. Stating it in percent would make the 1-10 range invisible in the number.
#: Knob: TMO_CLUB_GOUSEI_COMPLETENESS_PER_ITEM.
COMPLETENESS_PER_ITEM = max(0, int(
    os.environ.get("TMO_CLUB_GOUSEI_COMPLETENESS_PER_ITEM") or 1))
# ── end INVENTED (inventions:skip) ────────────────────────────────────────


def success_rate(club_level: int) -> int:
    """「部活レベルに応じた成功率」 as a percentage. See GOUSEI_RATE_MIN."""
    level = max(0, min(99, club_level))
    span = GOUSEI_RATE_MAX - GOUSEI_RATE_MIN
    return GOUSEI_RATE_MIN + span * level // 99


def completeness(boosters: "list[tuple[int, int, int]]") -> int:
    """完成度 for this many 消費アイテム. See COMPLETENESS_PER_ITEM.

    ⚠️ RETURNS THE WIRE VALUE (10-100), not the 1-10 the manual talks about.
    See COMPLETENESS_PER_LEVEL for why those are two different numbers.

    ``boosters`` is the part of the request the recipe did not claim, as
    ``(category, itemId, count)``. ⚠️ Only the first BOOSTER_KINDS_MAX kinds
    count, in the order the client sent them -- the manual caps registration at
    three and the client is what enforces it, so a fourth arriving here is a
    probe rather than a player and is ignored instead of refused.
    """
    kept = boosters[:BOOSTER_KINDS_MAX]
    total = sum(count for _c, _i, count in kept)
    level = LEVEL_MIN + COMPLETENESS_PER_ITEM * (len(kept) + total)
    return max(LEVEL_MIN, min(LEVEL_MAX, level)) * COMPLETENESS_PER_LEVEL


def parse_start(params: bytes) -> "int | None":
    """0x5300's npcId, or None for a short body.

    ⚠️⚠️ u32, and that is READ rather than assumed: the deserializer 0x8D86A0
    takes the uint32 slot (`call [eax+0x24]`), where 0x5D00's 0x8DB8E0 one door
    away takes uint16. 2.179 三 is the round that established the two can differ
    with the field name identical, so this one was disassembled before it was
    written down. It means this message CAN carry the whole charaId -- category
    in the high half, row in the low -- which 0x5D00's sixteen bits cannot.
    """
    if len(params) < 4:
        return None
    return struct.unpack_from(">I", params, 0)[0]


def parse_request(params: bytes) -> "tuple[tuple[int, int], list[tuple[int, int, int]]] | None":
    """0x5306: ``((bookCategory, bookId), [(category, itemId, count), ...])``.

    None for a body that does not hold what its own count says it does. See the
    module docstring for where the five-byte entry came from and why it is not
    the nine `the shape reader` reports.

    ⚠️ Duplicate keys are NOT merged. The client sends one row per registered
    kind, so two rows naming the same item is a probe or a bug, and merging them
    here would hide it from the log at the exact moment it matters.
    """
    if len(params) < 6:
        return None
    book_category, book_id, count = struct.unpack_from(">HHH", params, 0)
    entries = []
    for index in range(count):
        offset = 6 + index * 5
        if offset + 5 > len(params):
            return None
        category, item_id, quantity = struct.unpack_from(">HHB", params, offset)
        entries.append((category, item_id, quantity))
    return ((book_category, book_id), entries)


def ok_start_params(entry_max: int) -> bytes:
    """0x5301: 合成可アイテム数. One byte, clubbattle.gousei_entry_max's answer."""
    return struct.pack(">B", max(0, min(0xFF, entry_max)))


def ng_start_params(reason: int) -> bytes:
    """0x5302."""
    return struct.pack(">B", reason & 0xFF)


def ng_params(reason: int) -> bytes:
    """0x5308."""
    return struct.pack(">B", reason & 0xFF)


def ok_params(category: int, skill_id: int, level: int) -> bytes:
    """0x5307: the 部活奥義 that came out, and its 完成度."""
    return struct.pack(">HHB", category & 0xFFFF, skill_id & 0xFFFF,
                       max(0, min(0xFF, level)))


#: ⭐⭐⭐ 0x5307's OTHER MEANING: the same message carries failure, as a sentinel
#: rather than as a message of its own. FUN_0075A8AA reads its first and third
#: u16 and draws msg_text 501 「合成に失敗しました！\n登録アイテムは、すべてなく
#: なりました」 when either is 0xFFFF, and msg_text 500 「奥義「%1%」が完成しま
#: した！」 otherwise (2.87 二). ⛔️ So a failed 合成 is NOT a 0x5308 -- the Ng
#: messages are refusals to try, and this is a try that did not work.
FAIL_SENTINEL = 0xFFFF


def fail_params() -> bytes:
    """0x5307 saying 「合成に失敗しました！」. See FAIL_SENTINEL."""
    return ok_params(FAIL_SENTINEL, FAIL_SENTINEL, 0)


def split_registered(
    recipe: "list[tuple[int, int, int]]",
    registered: "list[tuple[int, int, int]]",
) -> "tuple[list[tuple[int, int, int]], list[tuple[int, int, int]], bool]":
    """Separate 合成アイテム from 消費アイテム. See the module docstring.

    Returns ``(materials, boosters, matches)``. ``matches`` is whether the
    registered items satisfy the recipe exactly -- every key the book names,
    present, with that exact count.

    ⚠️ EXACT rather than 「at least」, and the choice is forced by the ambiguity
    it removes: with 「at least」, a surplus of a key the recipe also names would
    be both a material and a booster, and nothing on the wire says which. 「その
    レシピ通りの合成アイテムを用意する必要があります」 reads as exactness anyway.
    """
    wanted = {(category, item_id): count for category, item_id, count in recipe}
    materials, boosters = [], []
    seen: "dict[tuple[int, int], int]" = {}
    for category, item_id, count in registered:
        key = (category, item_id)
        if key in wanted:
            materials.append((category, item_id, count))
            seen[key] = seen.get(key, 0) + count
        else:
            boosters.append((category, item_id, count))
    return materials, boosters, seen == wanted


def describe(entries: "list[tuple[int, int, int]]") -> str:
    """``32:1x2 40:0x3`` for the log."""
    return " ".join(f"{c}:{i}x{n}" for c, i, n in entries) or "なし"
