"""恋愛候補生の状態: 登場したか、どれだけ親密か、何話まで進んだか。

The official manual describes the loop in four sentences (`manual/p09_01.html`
§1–3), and they divide cleanly into what the game's own data can tell us and
what it cannot:

    1. 「天宮」と「桜井」は、初登校の学校説明で出会います。
       （天宮は男子キャラクターを作成した場合、桜井は女子キャラクターを作成した場合に登場）
    2. その他のキャラクターは、最初からは登場していません。
       特定のドラマイベントの、ある役柄をプレイすると、その中で登場するようになっています。
    3. 恋愛メインイベントを見るためには、日常会話を繰り返して、
       恋愛候補生と親密になっていく必要があります。
       ※一日に何度も日常会話を繰り返しても、あまり親密さは上がりません。
    4. 校内マップで恋愛候補生が立っている位置は、
       メインイベントを一つ見るごとに変わるようになっています。

All four are **recoverable**, and as of round 171 all four have been recovered.
(1), (2) and (4) were always easy: the debut event is a field in the game's own
`capture_npc` record and the placement rule is stated outright. (3) — 親密さ —
was the hard one, and for a long time this file carried three invented numbers
for it under a banner saying so.

⭐ They are gone. The numbers were never missing; they were in a place nothing
searched. The manual gives no figures, `capture_npc` has no threshold field and
親密さ never crosses the wire — all true, all checked — but the *scripts* have
it twice over, on both sides of the old client/server line:

  * the original server's GS3 scripts gate each メインイベント on
    ``PC[0x3920+i] >= 72 * progress`` (the opcode table's gates);
  * the client's own SSC 日常会話 scripts **add to that very same slot**, and
    implement the manual's 「一日に何度も…あまり上がりません」 themselves
    (read off the scripts' own intimacy writes).

Same slot on both sides, so no unit conversion is needed or wanted. The
numbers are under RESTORED below; how they were read out is written up on the
reverse-engineering side, under 恋愛 in the protocol notes.

⭐ The lesson kept from round 39 was «check the sources before reverse
engineering». Its other half was «when the sources stop, say so in the file
rather than letting a plausible constant pass for a recovered one» — and this
file did say so, in the three places it had to. What round 171 adds is the
third half: **a source that has stopped is not the same as a source that has
been looked at.** The banner should name the places already searched, so the
next reader can see which one is still missing. It did, and the missing one was
the scripts.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import NamedTuple

# ⚠️ One-way, and it stays that way: `gs3vm` imports nothing from here. This
# module asks it one question -- which cells a scenario date-stamps -- and asks
# it of an export that may not exist, so everything below it still works on a
# copy of this server that has no scripts at all.
import gs3vm

SEX_MALE, SEX_FEMALE = 0, 1  # chara_sex.bin: 0 男 / 1 女 / 2 不詳


class Candidate(NamedTuple):
    """One 恋愛候補生, as five numbers rather than as a row of game content.

    ``base``/``spots`` are her block in `cibi_control_script` (4:0–4:178): N
    scattered spots and then 26 classrooms, contiguous. ``sex`` is her own, read
    off `capture_npc` +24. ``debut`` is her 初期登場イベント from `capture_npc`
    +394 — a `capture_npc_event` key for the two who are there from the first
    day, ``None`` for the three a drama event has to introduce. ``events`` is how
    many メインイベント she has (その１…その１２, minus the ones she does not
    start with; the two おまけ are not counted).

    All of it is checked against the game's tables in the other tree, which
    is the reason it can live here as constants instead of as a file to load.
    """

    base: int
    spots: int
    events: int
    sex: int
    debut: tuple[int, int] | None


# 春日 has nine spots where everyone else has ten, and eleven main events where
# 天宮 and 桜井 have twelve — she and 弥生 and 犬飼 start at その２ because their
# その１ is the drama event that introduces them. Nothing here is a rounding of
# anything; it is what the tables say.
CANDIDATES = {
    "天宮": Candidate(base=0, spots=10, events=12, sex=SEX_FEMALE, debut=(0, 0)),
    "春日": Candidate(base=36, spots=9, events=11, sex=SEX_FEMALE, debut=None),
    "弥生": Candidate(base=71, spots=10, events=11, sex=SEX_FEMALE, debut=None),
    "桜井": Candidate(base=107, spots=10, events=12, sex=SEX_MALE, debut=(3, 0)),
    "犬飼": Candidate(base=143, spots=10, events=11, sex=SEX_MALE, debut=None),
}

CIBI_EVENT_CATEGORY = 4  # every cibi_control_script key is 4:something
CIBI_SCRIPT_COUNT = 223  # 4:0–4:178 these five, 4:179–4:222 teachers and staff

# `capture_npc_event` is keyed by category, and the categories are two parallel
# runs over the same five people in the same order as CANDIDATES: 0–4 are their
# メインイベント (その１…その１２ plus two おまけ) and 16–20 their 日常会話
# (c01x…c10x). Each record also carries the owning capture_npc index at +22,
# which is what lets that check verify these two numbers rather than take
# them on faith.
MAIN_EVENT_CATEGORY_BASE = 0
TALK_CATEGORY_BASE = 16


def whose_event(category: int) -> tuple[str, str] | None:
    """``(name, "main"|"talk")`` for a capture_npc_event category, or None.

    None covers every category that is not one of these ten — the general and
    extra NPCs have their own tables, and a conversation with one of them is not
    a step in anybody's 恋愛.
    """
    names = list(CANDIDATES)
    for base, kind in ((MAIN_EVENT_CATEGORY_BASE, "main"), (TALK_CATEGORY_BASE, "talk")):
        if base <= category < base + len(names):
            return names[category - base], kind
    return None

# ── RESTORED (round 171) ────────────────────────────────────────────────────
# 親密さ, end to end. Three slots carry it, and both sides of the old
# client/server line read the same one, so everything below is in one unit:
#
#   PC[0x3920+i]     親密さ for candidate i. The original server's GS3 scripts
#                    gate on it; the client's 日常会話 scripts add to it.
#   PCEV[0x6040+i]   the day her last 日常会話 landed, packed as
#                    (year-2000)*512 + month*32 + day
#   PCEV[0x6060+i]   the largest single grant already made to her *that day*
#
# ⚠️ It is a running total: nothing in either script set ever subtracts from it
# or resets it, and the gates are absolute (`>=`), not per-step.
GAIN_BEST = 15    # the best answer in a 日常会話 that offers a choice
GAIN_PLAIN = 12   # a 日常会話 with no choice at all, and the middle answer
GAIN_WORST = 10   # the worst answer
#
# Those three are every value that occurs: 304 client 日常会話 scripts, one
# parameter register each, 463 immediates between them, all 10 / 12 / 15, and
# not one of those immediates comes from anywhere but a constant. Two thirds of
# the scripts have no choice and grant a flat 12; the rest offer two or three
# answers. Which conversation grants what is in reference/intimacy.json — see
# TALK_GAINS below, and note that a fourth value, 0, lives only there.
#
# The daily rule is NOT «less the second time». Each script ends with the same
# routine, and what it does is keep the best single grant of the day:
#
#     if PCEV[day] != today:  PC[intimacy] += X;  PCEV[day] = today
#                             PCEV[best] = X
#     elif PCEV[best] < X:    PC[intimacy] += X - PCEV[best]
#                             PCEV[best] = X
#     else:                   nothing at all
#
# So a second conversation the same day is worth the difference and no more,
# and a third worse one is worth nothing. 「一日に何度も日常会話を繰り返しても、
# あまり親密さは上がりません」, implemented rather than approximated.
INTIMACY_STEP = 72  # the ladder the original server's gates climb

# ⭐⭐⭐ Round 468: the two cells that routine keeps its day on are supplied by
# this end, so the routine runs **where it was written** instead of being
# transcribed into `talk` below. What makes that safe is that there is one
# routine and not 304: a scan of every 日常会話 script normalises the stretch
# from the first `SYSTEM[0]` read to the closing `OP_RTN` to a single shape --
# 304 of 304, same opcodes, same immediates, same order -- and the index in all
# three cells is always the candidate whose script it is, never another's.
# ⚠️ Re-run that scan rather than trusting this sentence; it is a scan and not
# a reading, which is the only reason one script may be read for all of them.
PCEV_TALK_DAY_BASE = 0x6040   # the day her last 日常会話 landed, packed
PCEV_TALK_BEST_BASE = 0x6060  # the largest single grant made to her that day

# The packing is the scripts' own arithmetic, read off the bytecode:
# `(SYSTEM[0] - 2000) * 16 * 32 + SYSTEM[1] * 32 + SYSTEM[2]`.
# ⚠️⚠️ It is NOT the other date packing in the corpus. `<name>_s102` builds a
# `month * 100 + day` and compares that against a CTX cell of its own, and the
# two must never be mixed up. Both are fed from the same three SYSTEM cells,
# which is why this end supplies year, month and day raw and packs nothing:
# each script does its own packing, and this constant exists only so that a
# save's day can be handed back in the form the cell holds it in.
TALK_DAY_YEAR_BASE = 2000
TALK_DAY_MONTH_STEP = 32
TALK_DAY_YEAR_STEP = 16 * TALK_DAY_MONTH_STEP


#: Year, month and day, one cell each. ⭐ Raw rather than packed, because the
#: two packings in the corpus disagree and each script builds its own out of
#: these three (see the comment above `TALK_DAY_YEAR_BASE`).
SYSTEM_YEAR = 0
SYSTEM_MONTH = 1
SYSTEM_DAY = 2


def date_cells(today: "date | None" = None) -> dict:
    """The three `SYSTEM` cells that carry the date, for any script that asks.

    ⭐⭐⭐ Round 468: supplied to every scenario, not just to the 会話 chooser
    that used to be the only caller. Nothing else in the corpus reads them --
    325 scenarios do and every one of them is a `<name>_cNNN` 日常会話 -- so
    「every scenario」 and 「the 会話 family」 name the same set here, and the
    narrower fence would only have been a fence against a script that does not
    exist.

    ⚠️ The clock is this end's real one. The game had a clock of its own
    (校内マップ has seasons) and this end does not model one, so borrowing the
    real date is what keeps 「毎日少しずつ」 meaning something rather than
    nothing. ⛔️ One clock, not two: everything that decides 「is it a new
    day」 -- the daily rule, the 会話 slots, this -- reads it through here.
    """
    today = today or date.today()
    return {("SYSTEM", SYSTEM_YEAR): today.year,
            ("SYSTEM", SYSTEM_MONTH): today.month,
            ("SYSTEM", SYSTEM_DAY): today.day}


def pack_talk_day(day: "date | None") -> int:
    """`PCEV[0x6040+i]` for a calendar day; 0 for 「she has never been talked to」.

    ⭐ The 0 is not a number picked to mean something, which is the test every
    cell this end supplies has to pass. The cell is only ever compared for
    equality against a packed real date; a real date has a month of at least 1
    and a day of at least 1, so it packs to at least 33. Every value below that
    is equally 「not today」, none of them is reachable by the packing, and
    nothing can tell them apart -- so the choice among them has no observable
    consequence, and 0 is the one an event variable nobody has written holds.
    """
    if day is None:
        return 0
    return ((day.year - TALK_DAY_YEAR_BASE) * TALK_DAY_YEAR_STEP
            + day.month * TALK_DAY_MONTH_STEP + day.day)


def unpack_talk_day(packed: int) -> "date | None":
    """The calendar day a `PCEV[0x6040+i]` value stands for, or None.

    ⚠️ The inverse exists because the day makes the round trip: this end hands
    the cell down packed, the script writes a packed day back, and the save
    keeps an ISO date. The packing is injective over real dates -- day < 32 and
    month * 32 + day < 512, so the three fields never carry into each other --
    but it is not onto: a value the scripts could not have produced (0 above,
    or a month of 13) comes back as None rather than as a date this end made up.
    """
    if packed < TALK_DAY_YEAR_STEP:
        return None
    year = packed // TALK_DAY_YEAR_STEP + TALK_DAY_YEAR_BASE
    rest = packed % TALK_DAY_YEAR_STEP
    try:
        return date(year, rest // TALK_DAY_MONTH_STEP, rest % TALK_DAY_MONTH_STEP)
    except ValueError:
        return None


# ── Which conversation is worth what ────────────────────────────────────────
# The three constants above are the whole value range, but they are not a rule:
# each 日常会話 script carries its own number, and this end knows which script
# just played — the client asks for a conversation by its capture_npc_event key
# and that key is what mps_session hands back at NotifyScriptEnd. So the table
# is keyed the way the protocol is, `"category:id"`, and holds nothing else.
#
# 326 of the game's 327 日常会話, and four values between them:
#
#   [12]           two thirds of them: one answer, one number
#   [10, 15]       … or [10, 12, 15]: the answers are worth different amounts
#   [0]            22 conversations that never touch 親密さ at all: the opening
#                  lines of the two candidates who are there from the first day,
#                  and one trio (c301-c303) belonging to each of the five
#
# The 327th names a script that is not in the client archive, and is left out
# rather than guessed at: absent is not the same as worth nothing.
#
# `byChoice` is the second table, and it says which answer is worth which of
# those values — 96 conversations, 31 that ask two lines and 65 that ask three.
# It exists because the client reports the line the player clicked and this end
# now carries that number to the end of the script; before round 173 it did not,
# and a table nobody could read would have been shipped for nothing.
#
# ⚠️ The two are not the same fact seen twice. `gains` is what the script can
# grant by any route, `byChoice` only what a click leads to, and three rows have
# a value that is reachable but not by clicking anything — ink_c091 and its two
# neighbours offer three answers all worth 12 and keep their 10 behind a gate of
# their own. Two more rows ask a question whose answers are all worth the same,
# which `gains` alone cannot tell apart from a conversation that never asked.
TALK_GAIN_PATH = Path(__file__).resolve().parent.parent / "reference" / "intimacy.json"


def _load_talk_gains() -> tuple[dict, dict]:
    """``({key: every gain it can grant}, {key: the gain per answer})``.

    Two tables side by side rather than one table of pairs: the first has a row
    for all 326 conversations, the second only for the 96 that ask something,
    and keeping them apart is what makes a re-export show up in a diff as the
    lines that actually changed.

    Silent when the file is absent, the way script.py's branch loader is: with
    no table every conversation falls back to GAIN_PLAIN, which is exactly what
    this server credited before the table existed.
    """
    try:
        raw = json.loads(TALK_GAIN_PATH.read_text(encoding="utf-8"))
        blocks = (raw["gains"], raw["byChoice"])
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}
    out: list[dict] = []
    for block in blocks:
        rows = {}
        for key, gains in block.items():
            category, num = key.split(":")
            rows[(int(category), int(num))] = list(gains)
        out.append(rows)
    return out[0], out[1]


TALK_GAINS, TALK_BY_CHOICE = _load_talk_gains()


def talk_gain(key: tuple[int, int] | None, choice: int | None = None) -> int:
    """What the 日常会話 behind a capture_npc_event key is worth, this end's best.

    Exact for the 232 conversations that can only grant one number, which is
    most of them and includes the 22 worth nothing at all — and, since round
    173, exact for the 94 that offer a choice as well, provided the player made
    one. ``choice`` is the line the client reported in
    MsgClResultScriptCommandSelect, and the scripts number their answers the
    same way the wire does: each spells its choice out as an ascending run of
    `E == 0`, `E == 1`, … comparisons, 96 scripts with no exception, which is
    also what lets script.py's OP_BR chain heuristic count positions instead.

    ⚠️ With no choice to go on this returns the **smallest** of the values, and
    that is a floor rather than a reading. It is what a conversation with
    answers falls back to when the select never arrives — the player closed the
    box, or the script asked in a way this end did not follow. The floor is
    chosen over the old flat 12 for two reasons: for 32 of the 94, 12 is not
    among the possible values at all, so the old answer was one the script could
    never have given; and crediting too little is something tomorrow's
    conversation repairs while crediting too much is not.

    A choice for a conversation that has no answer table, or one past the end of
    the answers it does have, falls back the same way rather than guessing —
    which of the two is a diagnostic worth keeping, so the caller logs it.

    An unknown key — nothing started by hand has one — falls back to GAIN_PLAIN.
    """
    gains = TALK_GAINS.get(key) if key is not None else None
    if choice is not None:
        answers = TALK_BY_CHOICE.get(key) if key is not None else None
        if answers and 0 <= choice < len(answers):
            return answers[choice]
    return min(gains) if gains else GAIN_PLAIN


def talk_answers(key: tuple[int, int] | None) -> int:
    """How many answers that conversation offers; 0 for the ones that just play.

    Only the log uses it, and only to say whether a missing select is a
    conversation that never asked or an answer that did not arrive.
    """
    return len(TALK_BY_CHOICE.get(key, ())) if key is not None else 0


# ── The locker letter, and the ending it leads to ──────────────────────────
#
# ⭐ None of the rules below are restated here, because this end does not decide
# them: `lck_s103` and `lck_s102` -- the original server's own scripts -- are
# run as bytecode by `gs3vm`, and all this section does is say which save field
# is which data cell. Which 進行度 a letter waits for, how much 親密さ it takes,
# the order the five are checked in and the two-group split are all read out of
# those scripts at run time and are written down nowhere on this side.
#
# A cell number here is the little-endian u16 the operand carries.
PC_DEBUT_BASE = 0x3900     # per candidate; zero means she is not in play yet
PC_LETTER_BASE = 0x3910    # per candidate; 1 means her letter is in the locker
PC_INTIMACY_BASE = 0x3920  # per candidate; the 親密さ the gates read
PC_LETTER_EVENT = 0x3A04   # which candidate's letter event is running, -1 for none
NO_LETTER_EVENT = -1       # what sys_s000 -- the new-game reset -- writes there

# The client's own 683 scripts keep 進行度 in a cell of their own, and it is on
# neither of the two rulers above.
#
#   PCEV[0x6020+i]   進行度 as those scripts count it. `<name>_e0NN` writes NN
#                    when it finishes -- 57 writes across the corpus, one per
#                    メインイベント, and nothing else in either script set ever
#                    touches the cell.
#
# ⭐⭐ It runs exactly one *behind* the CTX cell -- not level with it, and not
# two behind. `<name>_s102` fires `<name>_e0k` when `c000[0xd900] == k`, and
# that script then writes k, so a k in this cell means the ladder now stands at
# k+1. The three same-shaped readings were measured against each other rather
# than argued about: walk the real ladder (running all five `_s102` and
# `lck_s103` for every rung) and feed each rung's outcome back through the
# corpus's own writes:
#
#   PCEV = CTX      every rung re-fires the event that just played:   0 of 10
#   PCEV = CTX - 1  その２ … その１１, in order, once each:           10 of 10
#   PCEV = CTX - 2  every second メインイベント is unreachable:        5 of 10
#
# and both ends of the corpus agree with the winner: the constants the client
# scripts test this cell against run 1-10 (64 of 桜井's have a `== 1` arm),
# while the constants the server scripts test the CTX cell against run 2-11.
# One apart, at both ends, across two script sets that share no bytes.
#
# ⚠️ The bottom rung is the one place they are not a plain shift. 天宮 and 桜井
# have an `_e001` -- their 初登校 -- and it writes 1; the other three are
# introduced by a drama event that writes nothing at all, so they sit at 0.
# Both map to the same `c000[0xd900] == 2`, so the ladder cannot tell them
# apart, but the 日常会話 can: that `== 1` arm of 桜井's is what it selects.
#
# ⚠️⚠️ Read-only, deliberately -- and round 193 makes the pairing worth stating,
# because the cell right next to it stopped being so. `absorb` now takes
# `PC[0x3900+i]` (登場) out of a script run and refuses `PCEV[0x6020+i]` (進行度),
# which is not an oversight but the whole shape of the split:
#
#   * **登場 is a fact the script owns.** `<name>_e001` is her 初登校 and there
#     is nothing for this end to decide -- it either played or it did not.
#   * **進行度 is a count this end owns.** `see_main_event` advances it, and
#     the spot table counts main events *after* the debut, so letting `_e001`
#     write it too would count that rung twice. ⇒ the value the script writes
#     here (1) is already exactly what `progress_cell(name, 0, True)` returns,
#     so taking it would gain nothing and risk double counting.
PCEV_PROGRESS_BASE = 0x6020

#: ⭐⭐⭐ The fifteen cells the 日常会話 daily rule is written over: 親密さ and
#: the two the routine keeps its day on, one of each per candidate. This end
#: supplies all fifteen (`data_cells`) and takes all fifteen back
#: (`absorb_talk_day`), which is the undertaking `gs3vm.Machine.kept_cells`
#: asks for before it will let a road that writes one of them be answered.
#: ⛔️ Not a list of 「cells this end is sure about」: 進行度 sits right next to
#: these and is deliberately **not** here, because this end computes that one
#: itself (see the comment above `PCEV_PROGRESS_BASE`) and a script's write of
#: it is refused rather than kept.
#: ⭐⭐ The ten that MARK a run as this routine's, kept apart from the fifteen
#: on purpose. 親密さ is written from two places in the corpus -- this routine
#: and the メインイベント grants -- while these ten are written from one, so
#: 「does this scenario carry the routine」 has to be asked of these and not of
#: the wider set. ⛔️ Ask it of the fifteen and every メインイベント answers yes.
TALK_DAY_MARK_CELLS = frozenset(
    [("PCEV", PCEV_TALK_DAY_BASE + i) for i in range(len(CANDIDATES))]
    + [("PCEV", PCEV_TALK_BEST_BASE + i) for i in range(len(CANDIDATES))])

TALK_DAY_CELLS = TALK_DAY_MARK_CELLS | frozenset(
    ("PC", PC_INTIMACY_BASE + i) for i in range(len(CANDIDATES)))


def scene_day_cells(script) -> "frozenset[tuple[str, int]]":
    """The day-stamp cells of `script` that are this record's to keep.

    ⭐⭐⭐ Round 469: 「同じ日常会話は一日一回」. A scenario opens by comparing
    its own cell against 今日 and walks straight out when they match -- a
    different, one-line scene and OP_END, no choices and no 親密さ -- and ends
    by writing 今日 into it. Until this end kept that cell the gate could never
    be answered, so the same conversation replayed for ever.

    ⭐ Which cells those are is `gs3vm.Script.day_stamps`, read off the
    bytecode by shape. ⛔️ Nothing here names an address: 275 of them exist
    across 325 scenarios and a table of them would be one more thing to trust.

    ⚠️ `TALK_DAY_MARK_CELLS` comes back out, and not because it would be wrong
    to keep them -- `PCEV[0x6040+i]` is a day stamp by exactly this shape. It
    is because `data_cells` already answers those five out of ``lastTalk`` and
    `absorb_talk_day` already takes them back, and one cell answered from two
    saved fields is the bug this avoids rather than the feature it looks like.

    Empty for a scenario this end has no export of, which is every copy of this
    server but the one that made them -- and then the gate is ⊤ as before.
    """
    if script is None:
        return frozenset()
    return script.day_stamps - TALK_DAY_MARK_CELLS


#: Every day-stamp cell one candidate's scenarios use, worked out once. ⭐ The
#: partition is measured, not assumed: across the exports each of these cells is
#: stamped by scenarios of exactly one candidate, so 「forget her scenes」 is a
#: question with an answer. ⚠️ Cached because the answer is a property of the
#: export directory, which does not change while a server runs.
_SCENE_DAY_BY_NAME: "dict[str, frozenset[tuple[str, int]]] | None" = None


def scene_day_cells_of(name: str) -> "frozenset[tuple[str, int]]":
    """The day-stamp cells of `name`'s own scenarios. Empty without exports."""
    global _SCENE_DAY_BY_NAME
    if _SCENE_DAY_BY_NAME is None:
        found: dict[str, set] = {who: set() for who in CANDIDATES}
        by_stem = {stem: who for who, stem in SCRIPT_STEMS.items()}
        for path in sorted(gs3vm.SCRIPT_DIR.glob("*.gs3.json")):
            who = by_stem.get(path.name[:3])
            if who is None:
                continue
            loaded = gs3vm.load(path.name[: -len(".gs3.json")])
            if loaded is not None:
                found[who] |= scene_day_cells(loaded)
        _SCENE_DAY_BY_NAME = {who: frozenset(cells)
                              for who, cells in found.items()}
    return _SCENE_DAY_BY_NAME.get(name, frozenset())


def scene_tally_cells(script) -> "frozenset[tuple[str, int]]":
    """The cells `script` counts its own playings in.

    ⭐⭐⭐ Round 470: 「how many times these four have played」. `ink_c091`
    through `c094` share one cell and branch on it twice -- 0 sends the play
    to one scene, 6 or more to another, and anything between to the everyday
    one -- then each arm adds one to it on the way out. Until this end kept
    that cell both gates read ⊤, so the first scene and the late scene could
    never play at all and every conversation was the middle one.

    ⭐ Which cell that is comes off the bytecode (`gs3vm.Script.tallies`), the
    way the day stamps do. ⛔️ Nothing here names an address.

    Empty for a scenario this end has no export of, and then the gates are ⊤
    as before.
    """
    if script is None:
        return frozenset()
    return script.tallies


#: The tally cells of one candidate's scenarios, worked out once, for
#: `scene_day_cells_of`'s reason and measured the same way: across the exports
#: the one cell there is belongs to 犬飼's four and to nothing else.
_SCENE_TALLY_BY_NAME: "dict[str, frozenset[tuple[str, int]]] | None" = None


def scene_tally_cells_of(name: str) -> "frozenset[tuple[str, int]]":
    """The tally cells of `name`'s own scenarios. Empty without exports."""
    global _SCENE_TALLY_BY_NAME
    if _SCENE_TALLY_BY_NAME is None:
        found: dict[str, set] = {who: set() for who in CANDIDATES}
        by_stem = {stem: who for who, stem in SCRIPT_STEMS.items()}
        for path in sorted(gs3vm.SCRIPT_DIR.glob("*.gs3.json")):
            who = by_stem.get(path.name[:3])
            if who is None:
                continue
            loaded = gs3vm.load(path.name[: -len(".gs3.json")])
            if loaded is not None:
                found[who] |= scene_tally_cells(loaded)
        _SCENE_TALLY_BY_NAME = {who: frozenset(cells)
                                for who, cells in found.items()}
    return _SCENE_TALLY_BY_NAME.get(name, frozenset())


def scene_flag_cells(script) -> "frozenset[tuple[str, int]]":
    """The numbered-state cells `script` asks about and sets.

    ⭐⭐⭐ Round 471: 「has this happened yet」. 弥生's seven 日常会話 share one
    cell, open by asking whether it is still 0, and every arm sets it to 1 on
    the way out -- so the run that finds 0 is the first meeting and no other
    run can be. 38 cells across the corpus work like this, and until this end
    kept them every one of those gates read ⊤ and the 「first time」 scene was
    unreachable, the way round 470's opening scene was.

    ⭐⭐ Round 472 widened the family from 「a yes/no」 to 「a small numbered
    state」 and two more cells came in, both 犬飼's: three of his 日常会話 share
    `PCEV[0x6084]`, whose three 選択肢 write 1, 2 and 3 on the way out, and
    `ink_c511` does the same with `PCEV[0x60a4]` and 0, 1, 2. Both are read
    back only by the 「we have already talked today」 arm, which plays a line
    about the answer you gave -- so the cell is 「which one did you pick」 and
    it needs nothing from this end but its value back. See `gs3vm.FLAG_MAX`
    for why the bound is where it is.

    ⭐ Which cells those are is `gs3vm.Script.flags`, read off the bytecode by
    shape, the way the day stamps and the tally are. ⛔️ Nothing here names an
    address.

    Empty for a scenario this end has no export of, and then the gates are ⊤
    as before.
    """
    if script is None:
        return frozenset()
    return script.flags


#: The flag cells of one candidate's scenarios, worked out once, for
#: `scene_day_cells_of`'s reason and measured the same way: across the exports
#: every one of the 38 is touched by scenarios of a single prefix, so 「forget
#: her scenes」 has an answer here too. ⚠️ Eight of them belong to `hsn`/`hsy`,
#: which are nobody's -- they stay put through a reset, like everything else
#: outside the five.
_SCENE_FLAG_BY_NAME: "dict[str, frozenset[tuple[str, int]]] | None" = None


def scene_flag_cells_of(name: str) -> "frozenset[tuple[str, int]]":
    """The flag cells of `name`'s own scenarios. Empty without exports."""
    global _SCENE_FLAG_BY_NAME
    if _SCENE_FLAG_BY_NAME is None:
        found: dict[str, set] = {who: set() for who in CANDIDATES}
        by_stem = {stem: who for who, stem in SCRIPT_STEMS.items()}
        for path in sorted(gs3vm.SCRIPT_DIR.glob("*.gs3.json")):
            who = by_stem.get(path.name[:3])
            if who is None:
                continue
            loaded = gs3vm.load(path.name[: -len(".gs3.json")])
            if loaded is not None:
                found[who] |= scene_flag_cells(loaded)
        _SCENE_FLAG_BY_NAME = {who: frozenset(cells)
                               for who, cells in found.items()}
    return _SCENE_FLAG_BY_NAME.get(name, frozenset())


def scene_text_cells(script) -> "frozenset[tuple[str, int]]":
    """The cells `script` keeps a piece of text in.

    ⭐⭐⭐ Round 473. `amm_c092` is a 日常会話 whose three 選択肢 are three
    words -- ケーキ / カフェに行くの / 牛丼屋さん -- and each arm writes **its
    own word** into a cell on the way out. Come back the same day and the arm
    the 日付スタンプ sends you down opens by reading that cell and saying the
    word back to you. Until this end kept it the cell read ⊤ and the line went
    out with a hole where the word should be.

    ⭐ Which cell that is comes off the bytecode (`gs3vm.Script.texts`), the
    way the day stamps, the tally and the flags do, and by an even shorter
    rule: the operand of a data instruction names the register it moves the
    cell through, and this is the one `PCEV` cell the corpus only ever moves
    through a string register. ⛔️ Nothing here names an address.

    Empty for a scenario this end has no export of, and then the line keeps
    its hole, as before.
    """
    if script is None:
        return frozenset()
    return script.texts


#: The text cells of one candidate's scenarios, worked out once, for
#: `scene_day_cells_of`'s reason and measured the same way: the one cell there
#: is belongs to 天宮's `amm_c092` and to nothing else.
_SCENE_TEXT_BY_NAME: "dict[str, frozenset[tuple[str, int]]] | None" = None


def scene_text_cells_of(name: str) -> "frozenset[tuple[str, int]]":
    """The text cells of `name`'s own scenarios. Empty without exports."""
    global _SCENE_TEXT_BY_NAME
    if _SCENE_TEXT_BY_NAME is None:
        found: dict[str, set] = {who: set() for who in CANDIDATES}
        by_stem = {stem: who for who, stem in SCRIPT_STEMS.items()}
        for path in sorted(gs3vm.SCRIPT_DIR.glob("*.gs3.json")):
            who = by_stem.get(path.name[:3])
            if who is None:
                continue
            loaded = gs3vm.load(path.name[: -len(".gs3.json")])
            if loaded is not None:
                found[who] |= scene_text_cells(loaded)
        _SCENE_TEXT_BY_NAME = {who: frozenset(cells)
                               for who, cells in found.items()}
    return _SCENE_TEXT_BY_NAME.get(name, frozenset())


# ⚠️ Which of the two groups the locker scripts check is `PC[0x3013]`, and the
# split is 天宮/春日/弥生 against 桜井/犬飼 -- exactly the female candidates
# against the male ones. So this end sends the player's own sex, and an
# opposite-sex cast falls out of the script rather than out of a rule here.
# ⛔️ That the cell *is* the player's sex is a reading, not a name read off
# anything: nothing writes it in either script set. It is the only 3-2 split of
# these five that any table supports.
PC_PLAYER_SEX = 0x3013

# ── The 告白 register block: PLAYER[0x2100+i] … PLAYER[0x2210+i] ───────────
#
# ⭐⭐⭐ RESTORED (round 467). Nine bases, five cells each -- one per candidate,
# at the same index every other per-candidate cell here uses -- and those 45
# cells are the whole of the corpus's PLAYER writes, which the smoke test
# re-counts over every exported scenario rather than trusting this comment.
# Six of the nine are one straight-line block in `<キャラ>_e011`, her 告白,
# on the arm the player answers 「はい」 on:
#
#   PLAYER[0x2100+i] = 1                 it happened
#   PLAYER[0x2110+i] = SCHOOL[0x1001]    at which school       (text)
#   PLAYER[0x2120+i] = PC[0x301c]        in which 組
#   PLAYER[0x2130+i] = PC[0x3010]        under which 姓        (text)
#   PLAYER[0x2140+i] = PC[0x3011]        ... 名                (text)
#   PLAYER[0x2150+i] = PC[0x3012]        ... ニックネーム       (text)
#
# The other three are flags her メインイベント raise: each `<キャラ>_e0NN`
# writes `PLAYER[0x2160+i] = 1` as it opens, and two of them further in.
#
# ⭐⭐⭐ **The block has a reader, and it is a different scenario.** `yyi_o012`
# reads `PLAYER[0x2132]` -- the 姓 written down at 弥生's 告白 -- compares it
# with 「一ノ瀬」 and spells that NPC 「一ノ宮」 when they collide. That is the
# 同姓回避 ladder of 2.380 三 again, except the surname comes out of the record
# rather than out of the save's current name: one scenario writes, another
# reads, and nothing shorter than a save can carry it between them.
#
# ⭐⭐ Why the whole space rather than the six that have a reading: this end
# does not interpret any of it. The value kept is the value the scenario
# computed, the address is the scenario's own, and it is handed back as that
# same cell next time. Saying what `0x2200+i` *means* would be a reading;
# keeping what was written there is not one.
#
# ⚠️ Only cells a scenario actually wrote are supplied back. A candidate with
# no 告白 behind her leaves `0x2130+i` unsupplied ⇒ ⊤ ⇒ the ladder falls
# through to the plain spelling -- which is what a zero-filled original would
# also do, and the honest answer either way. ⛔️ 「nobody answers it」 is not
# 「it should be answered」: a 0 invented here would be PC[0x3201] over again.
PLAYER_RECORD_BASES = (0x2100, 0x2110, 0x2120, 0x2130, 0x2140, 0x2150,
                       0x2160, 0x2200, 0x2210)


def _saved_record(saved) -> dict:
    """One candidate's register block as it comes back out of a save.

    ⚠️ Filtered against `PLAYER_RECORD_BASES` rather than taken as read: what
    goes back into `data_cells` becomes a scenario's answer, so a key a save
    picked up some other way must not turn into a cell. Keys are the base
    address as a decimal string; values are whatever the scenario wrote, which
    for four of the nine bases is text.
    """
    return {str(base): saved[str(base)]
            for base in PLAYER_RECORD_BASES
            if isinstance(saved, dict) and str(base) in saved}


def _saved_scene_tally(saved) -> dict:
    """``{cell address: count}`` as it comes back out of a save.

    ⚠️ `_saved_scene_day`'s keying exactly -- decimal-string addresses in the
    file, ints in here -- and its tolerance: a key that is not a number or a
    count that is not a non-negative integer is dropped. A scenario only ever
    adds one to these, so anything else is a save this end did not write.
    """
    if not isinstance(saved, dict):
        return {}
    kept: dict[int, int] = {}
    for key, value in saved.items():
        try:
            address, count = int(key), int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            kept[address] = count
    return kept


def _saved_scene_flag(saved) -> dict:
    """``{cell address: 0..gs3vm.FLAG_MAX}`` as it comes back out of a save.

    ⚠️ `_saved_scene_tally`'s keying and its tolerance, one notch tighter:
    these scenarios write a plain small number into these cells and nothing
    else (`gs3vm.Script.flags` is that shape), so anything out of range is a
    save this end did not write.
    """
    if not isinstance(saved, dict):
        return {}
    kept: dict[int, int] = {}
    for key, value in saved.items():
        try:
            address, flag = int(key), int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= flag <= gs3vm.FLAG_MAX:
            kept[address] = flag
    return kept


def _saved_scene_text(saved) -> dict:
    """``{cell address: the reference a scenario wrote}`` out of a save.

    ⚠️ `_saved_scene_tally`'s keying, and its tolerance widened by exactly what
    `gs3vm.Machine` can have put in one of these registers: a pool reference,
    which is a non-negative int, or a line the player typed, which `Follower`
    puts in as `str` and `sync_values` hands on as it stands. ⛔️ Neither is
    resolved here -- a reference means something only against the pool of the
    scenario that wrote it, and that scenario is the one that reads it back.
    """
    if not isinstance(saved, dict):
        return {}
    kept: dict[int, object] = {}
    for key, value in saved.items():
        try:
            address = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, str):
            kept[address] = value
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            kept[address] = value
    return kept


def _saved_scene_day(saved) -> dict:
    """``{cell address: "YYYY-MM-DD"}`` as it comes back out of a save.

    ⚠️ Keys are the PCEV address as a decimal string in the file (JSON has no
    integer keys) and an int in here, which is how the cells are keyed
    everywhere else. A key that is not a number, or a value that is not a day
    this end can read back, is dropped rather than carried: what goes back into
    a scenario's answer must be a day something wrote, and `_saved_day` is the
    same tolerance ``lastTalk`` gets.
    """
    if not isinstance(saved, dict):
        return {}
    kept: dict[int, str] = {}
    for key, value in saved.items():
        try:
            address = int(key)
        except (TypeError, ValueError):
            continue
        day = _saved_day(str(value))
        if day is not None:
            kept[address] = day.isoformat()
    return kept


def talk_day_writes(writes: dict) -> dict:
    """``{candidate index: {"day"/"best"/"intimacy": value}}`` from a run.

    Empty unless one of the two PCEV families was written -- see
    `Romance.absorb_talk_day` for why that, and not the 親密さ cell, is the
    fence. ⚠️ Non-integer values are dropped: these three are quantities, and
    the only writes that reach here at all are ones the run could compute.
    """
    # ⚠️ Triples rather than a dict keyed by base, so that no line here reads
    # like a cell key: the audit that asks 「which cells does this end answer」
    # scrapes this source for a family name paired with a slot, and a pair
    # whose second half is a *label* would be one more thing for it to fail on.
    bases = ((PCEV_TALK_DAY_BASE, "PCEV", "day"),
             (PCEV_TALK_BEST_BASE, "PCEV", "best"),
             (PC_INTIMACY_BASE, "PC", "intimacy"))
    found: dict = {}
    for (family, address), value in writes.items():
        if isinstance(address, tuple) or not isinstance(value, int):
            continue
        for base, want, what in bases:
            index = address - base
            if family == want and 0 <= index < len(CANDIDATES):
                found.setdefault(index, {})[what] = value
    return {index: wrote for index, wrote in found.items()
            if "day" in wrote or "best" in wrote}


def _saved_day(text: str) -> "date | None":
    """The `lastTalk` a save holds, as a day; None when there is not one.

    ⚠️ Tolerant on purpose, in the one direction that matters: the empty
    string is what a character who has never been talked to carries, and
    `talk`'s `today` argument is a caller's string, so anything that is not a
    date reads as 「no day」 rather than raising in the middle of a script run.
    """
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


# The CTX side. `c000[0xd900]` is a candidate's 進行度 as the scripts count it,
# which is this end's `progress` plus two (see `intimacy_needed`), and its
# subject is her 日常会話 category. `c000[0x8103]` is the menu_item that started
# the call and has no subject.
CTX_PROGRESS = 0xD900
CTX_MENU_ITEM = 0x8103
#: The same slot, read by a different script for a different thing: the
#: ちびキャラ管理 scripts (`_s101`) test it against a map id. It is the one
#: cell the engine rather than the save supplies -- 「the argument」 -- and each
#: script family knows what it was handed. Two names, one address, on purpose.
CTX_ENGINE_ARG = CTX_MENU_ITEM
PROGRESS_OFFSET = 2

# ⭐⭐⭐ RESTORED (round 346) -- the 会話 bookkeeping `<name>_s102` keeps, one
# row of it per candidate. These are the CTX cells the original server's own
# scripts read and write around a right-click on her (2.287 四):
# the subject of the e1xx slots is her roster index, the subject of d8/d9 is
# her 日常会話 category (16 + index), and every one of them starts at 0 -- the
# value `sys_s000`, the original's new-game reset, writes -- so a save from
# before this round needs no migration.
CTX_TALK_SLOTS = {
    "lastDaily": 0xE100,     # last 日常会話 (base + draw); -1 = a メイン was just answered
    "lastSpecial": 0xE101,   # last 特別 draw, 0 = the last one was not 特別
    "todayTalks": 0xE102,    # talks today; 15 + draw once しつこい has taken over
    "lastMonthDay": 0xE103,  # month * 100 + day of the last talk
    "lastYear": 0xE104,      # year of the last talk
}
#: 1 from the moment `_s104` books a メイン until `_s101` places her again;
#: while it is 1 a right-click on a new day gets 「no 会話」 from `_s102`.
CTX_MAIN_SEEN = 0xD800
TALK_SLOT_DEFAULTS = {**dict.fromkeys(CTX_TALK_SLOTS, 0), "mainSeen": 0}
#: The three-letter stem every one of her scripts is filed under.
SCRIPT_STEMS = {"天宮": "amm", "春日": "ksg", "弥生": "yyi", "桜井": "skr", "犬飼": "ink"}
TALK_SCRIPT = "s102"       # right-click 会話: which segment, if any
MAIN_SEEN_SCRIPT = "s104"  # after a メイン played: the bookkeeping
#: PC[0x3100+j]: the five 能力 as レベル. 天宮's and 桜井's `_s102` read them at
#: 進行度 0, and ABILITY_GATES below is the same thresholds read off those scripts.
PC_ABILITY_BASE = 0x3100
#: NPC kind 1 -- `capture_npc`, the five candidates; `capturenpc.NPC_KIND_CAPTURE`.
NPC_KIND_CAPTURE = 1


def candidate_of_npc(npc_id: int) -> str | None:
    """Her name for the four bytes a spawn or a 0x6304 carries, or None.

    `1 << 16 | rosterIndex`, and the roster is CANDIDATES in order -- the
    same numbering PC[0x3900+i] and friends count on (capturenpc.py).
    """
    if npc_id >> 16 != NPC_KIND_CAPTURE:
        return None
    names = list(CANDIDATES)
    index = npc_id & 0xFFFF
    return names[index] if index < len(names) else None

# The two menu_item ids the locker answers to. 403 is 「ロッカー開く」; 404 is the
# one behind it. ⚠️ Each script gates on its own id, so sending the wrong pair
# is not a silent mistake -- the script falls through and offers nothing.
LOCKER_OPEN_ITEM = 403
LOCKER_LETTER_ITEM = 404
LOCKER_SCRIPTS = {LOCKER_OPEN_ITEM: "lck_s103", LOCKER_LETTER_ITEM: "lck_s102"}


def candidate_index(name: str) -> int:
    return list(CANDIDATES).index(name)


def progress_cell(name: str, progress: int, debut: bool) -> int:
    """`PCEV[0x6020+i]` -- 進行度 on the client scripts' ruler, not this one.

    See the comment above PCEV_PROGRESS_BASE for why it is `progress + 1` and
    not `progress` or `progress + 2`, and why the two candidates with an
    `_e001` start a rung above the three without one.
    """
    if progress:
        return progress + 1
    return 1 if debut and CANDIDATES[name].debut is not None else 0


def intimacy_needed(progress: int) -> int:
    """親密さ required before the メインイベント after `progress` will play.

    ``c000[00d9] == progress + 2 AND PC[0x3920+i] >= 72 * (c000[00d9] - 2)``,
    i.e. 0, 72, 144, … — a straight line, not a constant.

    ⭐ The ``+2`` is not assumed. `<name>_s101` — the script that answers «where
    does she stand» — is a table of `(c000[00d9], map id)` pairs, and lining
    those up against the placement keys in `cibi_control_script` matches on all
    48 rows across the five candidates, with `c000[00d9] - 2` as the index into
    her spots. Two tables that share no bytes agree on the offset.
    """
    return INTIMACY_STEP * max(0, progress)


# メインイベント scripts grant 親密さ too, 0 / 12 / 24 by answer — but which
# answer the player picked is not something this end sees yet, so see_main_event
# grants nothing. ⚠️ That is a gap, not a decision: it is the one number in this
# file that is known and still unused.
# ────────────────────────────────────────────────────────────────────────────

# 「プレイヤーの能力が低い間は見られないメインイベントもあります（そこからさらに
# 仲良くなることはできません）」— the manual's other gate, and in the scripts it
# is an `OP_RTN`: `<name>_s102` returns before the EVENT_CALL unless every 能力
# it lists clears its number.
#
# ⭐ Which slots those are was open for three rounds. `PC[0x310i]` is
# ``abilityParam[i]``, from the client's own dump string for fixedCharaData:
#
#     param = { abilityParam[tmn::NUM_OF_CHARA_ABILITY]              six
#               personalityParam[tmn::CHARA_PERSONALITY_PLUS_TYPE]   four
#               virtue, charm, stress, charaCondition, vitality, energy,
#               agility, tokimekido[tmn::NUM_OF_CAPTURE_NPC] }       five
#
# Only two of those arrays are five long or more, and the five-long one —
# ときめき度, one per candidate — is already `PC[0x392+i]`, the slot 日常会話
# adds to. Reading 0x310i as that one would have 天宮's first event demand a
# feeling for all five candidates at once, which is not a threshold, it is
# nonsense. The four-long one is ruled out by the index: `amm_s102` reads
# 0x3100 through 0x3104, one further than four axes go.
#
# ⭐⭐ The neighbouring family settles it from the other side. `PC[0x320i]` is
# ``personalityParam[i]`` — un065 gates one choice on `>= 0` and another on
# `< 0`, a pair that is only meaningful for a signed value, and abilityParam is
# u16 on the wire. The axis it reads is 3, and axis 3 of
# chara_personality_plus/minus_type is 良い子 / 悪い子; the two choices are
# 「代わりに答える」above zero and 「先生に飛び蹴り」below it. Named axes, named
# order, and the script agrees with both.
#
# ⚠️ レベル or raw value is NOT settled, and this end picks レベル. abilityParam
# is 8.8 fixed point, so read raw these thresholds — 3, 4, 5, and 10 in un043's
# バレンタイン — are cleared by a character who has never been to a lesson,
# leaving the manual's sentence saying nothing. That is a judgement about which
# reading leaves the gate a gate, not a decode of the shift.
ABILITY_GATES = {
    "天宮": {0: 5, 1: 3, 2: 5, 3: 3, 4: 5},
    "桜井": {0: 4, 2: 3, 3: 4},
}


def ability_gate(name: str, progress: int) -> dict:
    """``{ability index: レベル needed}`` before her next メインイベント plays.

    Empty for the three candidates whose `_s102` carries no such test, and empty
    at every step but the first, which is why this takes a progress and not just
    a name. In both scripts that do carry one, the comparisons sit inside the
    `c000[00d9] == 2` arm — 進行度 0 — between that test and `EVENT_CALL 0:1`
    (`3:1` for 桜井). Her later events are gated on 親密さ alone.

    ⭐ `0:1` is その２, not その１: `_s102` pairs `c000[00d9] == k` with event
    id `k - 1` all the way up its ladder, so id = progress + 1, and 2.121 read
    `0:10` off `lck_s102` as `amm_e011` = その１１ — ids are 0-based where その
    is 1-based. その１ is id 0, which is exactly what `capture_npc` +394 names
    as her 登場イベント. So the gate stands in front of the first main event
    *after* her debut, and — a second source for the question see_main_event
    leaves open — 進行度 counts events after that debut, not including it.
    """
    return dict(ABILITY_GATES.get(name, {})) if progress == 0 else {}


def ability_short(name: str, progress: int, levels: "list[int] | None") -> dict:
    """``{index: (have, need)}`` for the gated 能力 still below their number.

    ``levels`` is AbilitySheet.levels(). ⚠️ ``None`` means the caller had no
    sheet to read, and then this reports nothing rather than everything: a
    character record this end failed to load is a fault here, and it should not
    turn into a player who can never see an event.
    """
    if levels is None:
        return {}
    short = {}
    for index, need in sorted(ability_gate(name, progress).items()):
        have = levels[index] if index < len(levels) else 0
        if have < need:
            short[index] = (have, need)
    return short
# ────────────────────────────────────────────────────────────────────────────


def initial_cast(player_sex: int) -> set[str]:
    """Who a save that predates 初登校 has to be *assumed* to have met.

    Derived, not listed: a candidate is there from the start iff she has a debut
    event at all, and she is *this* player's iff her sex is the other one. That
    reproduces the manual's parenthesis (天宮 for a male character, 桜井 for a
    female one) without stating it a second time in a place that could drift.

    ⚠️⚠️ Round 194 demoted this from *the* answer to the *fallback* answer, and
    that is the whole of what round 194 changed. Until then every character
    started with this set on stage, so the 初登校 that actually introduces her
    changed nothing — she was there before it played. Now `<name>_e001` writes
    `PC[0x3900+i]`, `absorb()` takes it, and a character created from here on
    starts with an empty campus that the tutorial fills.

    ⇒ this rule now applies to exactly one thing: a record written before that
    path existed, which is to say one with no ``romance`` key at all. Deciding
    which those are is `CharacterStore.romance()`'s job, not this module's —
    and two writers over there (``add`` at creation, ``declare_empty_cast`` at
    登校) keep «no key» a fact about *when* the record was written rather than a
    guess about what happened to its owner.
    """
    return {
        name
        for name, who in CANDIDATES.items()
        if who.debut is not None and who.sex != player_sex
    }


def cibi_key(name: str, progress: int) -> int:
    """Which spot she stands on, given how many main events have been seen.

    「校内マップで恋愛候補生が立っている位置は、メインイベントを一つ見るごとに
    変わるようになっています」. Spot 0 is where she stands once she has appeared;
    each main event moves her one along. Her last two main events (その１１ /
    その１２, the two with おまけ) are the confession and after, which is why
    twelve events fit ten spots.

    ⚠️ Since round 335 this is the *table* form of the rule, used to print her
    state; what actually seats her is her own ちびキャラ管理 script, run per
    lobby load (cibispawns). The two agree spot for spot where the script has
    a door, and differ where it has none: past her last spot the script places
    nobody (her remaining events come through the locker), while this clamps.
    """
    who = CANDIDATES[name]
    return who.base + max(0, min(progress, who.spots - 1))


def classroom_key(name: str, class_index: int) -> int:
    """Her seat, in whichever of the 26 classrooms is the one that matters.

    The 26 keys are not 26 places: the coordinate is identical across all of
    them, and the five sit side by side (x=3..7, y=10). One room, chosen from
    outside; not a spot she wanders to, which is why it is not in cibi_key().

    ⚠️ Nothing calls this, and nothing in the game data calls these keys
    either: none of the 95 server scripts and none of the 683 client scripts
    names a classroom placement key (round 335 scanned every EVENT_CALL). The
    seat exists in the data and no known occasion puts her in it.
    """
    who = CANDIDATES[name]
    return who.base + who.spots + class_index % 26


class Romance:
    """Per-character 恋愛 state, the whole of it: five names, three numbers each.

    Lives in the character's record in runtime/characters.json — same tier as
    ``pos`` and ``map``, which is to say derived state that belongs to a save and
    reaches neither repository. Mutating methods return True when something
    changed, so the caller knows whether to write the file.
    """

    def __init__(self, player_sex: int, saved: dict | None = None,
                 assume_initial_cast: bool = False) -> None:
        self.player_sex = player_sex
        # ⚠️ Empty by default, since round 194: 登場 belongs to the script that
        # writes it (see `absorb`), and a character who has not had her 初登校
        # has met nobody. ``assume_initial_cast`` is the one exception and it is
        # for old records only — see `initial_cast`. It cannot override a
        # ``saved`` row, which carries its own "debut" either way.
        started = initial_cast(player_sex) if assume_initial_cast else set()
        self.state: dict[str, dict] = {}
        for name in CANDIDATES:
            row = (saved or {}).get(name, {})
            self.state[name] = {
                "debut": bool(row.get("debut", name in started)),
                "intimacy": int(row.get("intimacy", 0)),
                "progress": int(row.get("progress", 0)),
                "lastTalk": str(row.get("lastTalk", "")),
                # The best single grant already made today — PCEV[0x6060+i].
                # Absent from saves written before round 171; 0 is the value a
                # fresh day would have anyway, so no migration is needed.
                "todayBest": int(row.get("todayBest", 0)),
                # PC[0x3910+i]: her letter is sitting in the locker. Written by
                # lck_s103 when the gates open, cleared only by a new game.
                "letter": int(row.get("letter", 0)),
                # ⭐ Round 347: her confession has been received -- the moment
                # 0x5606 named her and the credits rolled. This is what the
                # title screen's おまけ→エンディング list is made of (p02_07:
                # 「過去に告白を受けたことがある恋愛候補生」), so it is kept per
                # candidate and never cleared by anything short of a new game.
                # Absent from saves before round 347; 0 is what nobody has yet.
                "ending": int(row.get("ending", 0)),
                # The 会話 bookkeeping her `_s102`/`_s104` keep (CTX_TALK_SLOTS
                # and CTX_MAIN_SEEN). Absent from saves before round 346; 0 is
                # what the original's new-game reset writes anyway.
                "talk": {**TALK_SLOT_DEFAULTS,
                         **{key: int(value) for key, value in
                            dict(row.get("talk", {})).items()
                            if key in TALK_SLOT_DEFAULTS}},
                # ⭐ Round 467: what her `_e011` and `_e0NN` wrote into the
                # PLAYER register block, keyed by the base address as a decimal
                # string (JSON has no integer keys). ⚠️ Sparse on purpose --
                # see PLAYER_RECORD_BASES; an absent base is a cell nothing has
                # written yet and is not supplied at all. Absent from saves
                # before round 467, and an empty record is what a new game has.
                "record": _saved_record(row.get("record")),
            }
        # PC[0x3a04]: whose letter event is running. -1 is what the new-game
        # reset writes, and it is what 「手紙を読まない」 puts back.
        self.letter_event = int((saved or {}).get("letterEvent", NO_LETTER_EVENT))
        # ⭐⭐⭐ Round 469: the day each scenario last played, by the cell the
        # scenario stamps it into (`scene_day_cells`) and as a date the same
        # way ``lastTalk`` is one. ⚠️ Kept here rather than per candidate on
        # purpose: these cells belong to a *scene*, not to a person -- four of
        # 天宮's share one cell, and the fifteen `<キャラ>_c20N` stamp cells
        # nothing in the corpus ever reads. Sparse, like ``record``: a cell
        # absent here is a scene nobody has played, which `pack_talk_day`
        # renders as 0, and 0 is not any day. Absent from saves before round
        # 469, which is exactly a save where nothing has been played yet.
        self.scene_day: dict[int, str] = _saved_scene_day(
            (saved or {}).get("sceneDay"))
        # ⭐⭐⭐ Round 470: how many times each scene has played, by the cell
        # the scenario counts into (`scene_tally_cells`). Kept beside
        # ``sceneDay`` and for its reasons: these belong to a scene rather
        # than to a person, and the store is sparse. ⚠️ But an absent cell
        # reads 0 here rather than 「no answer」, because 0 is what a count of
        # a thing that has not happened is -- and the scenarios say so
        # themselves by branching on `== 0`. Absent from saves before round
        # 470, which is exactly a save where none of them has played.
        self.scene_tally: dict[int, int] = _saved_scene_tally(
            (saved or {}).get("sceneTally"))
        # ⭐⭐⭐ Round 471: whether each 「has this happened yet」 cell has been
        # set, by the cell the scenario asks about (`scene_flag_cells`). Beside
        # its two neighbours and for their reasons -- a scene's, not a person's,
        # and sparse. ⚠️ An absent cell reads 0, for ``sceneTally``'s reason
        # exactly: the scenarios branch on `== 0` themselves, so 0 is the answer
        # they ask for by name rather than a number invented here. Absent from
        # saves before round 471, which is a save where none of them has been
        # set.
        self.scene_flag: dict[int, int] = _saved_scene_flag(
            (saved or {}).get("sceneFlag"))
        # ⭐⭐⭐ Round 473: the word each scenario wrote down, by the cell it
        # wrote it into (`scene_text_cells`). Beside its three neighbours and
        # for their reasons -- a scene's, not a person's, and sparse -- with
        # one difference that matters: ⛔️ an absent cell is **not** read as 0.
        # The only read of one is a `SYNC_VARIABLE`, not a gate, so there is no
        # value a scene that has never played 「asks for by name」; a cell
        # nothing has written is left unanswered and the 台詞 keeps the hole a
        # zero-filled original would leave it. Absent from saves before round
        # 473, which is exactly a save where nothing has been written.
        self.scene_text: dict[int, object] = _saved_scene_text(
            (saved or {}).get("sceneText"))

    # ── reading ────────────────────────────────────────────────────────────
    def on_stage(self) -> list[str]:
        """The candidates who are actually standing on a map, in key order.

        Before her debut a candidate is nowhere: 「その他のキャラクターは、最初
        からは登場していません」, and p09_02 says the map characters of everyone
        the player never met are simply not drawn. So this — not the whole cast —
        is what a spawn push is allowed to contain.
        """
        return [name for name in CANDIDATES if self.state[name]["debut"]]

    def keys(self) -> list[tuple[str, int]]:
        """``(name, cibi key)`` for everyone on stage, at her own progress."""
        return [(name, cibi_key(name, self.state[name]["progress"])) for name in self.on_stage()]

    def line(self, name: str) -> str:
        row = self.state[name]
        if not row["debut"]:
            return f"{name}=未登場"
        talk = row["talk"]
        return (
            f"{name}=進行{row['progress']}/{CANDIDATES[name].events}"
            f" 親密{row['intimacy']}/{intimacy_needed(row['progress'])}"
            f" 位置4:{cibi_key(name, row['progress'])}"
            # The `_s102` slots, in the order the script writes them:
            # last 日常 / last 特別 / talks today @ last day, and d8 if set.
            f" 会話{talk['lastDaily']}/{talk['lastSpecial']}/{talk['todayTalks']}"
            f"@{talk['lastYear']}-{talk['lastMonthDay']:04d}"
            + ("·d8" if talk["mainSeen"] else "")
            + (" ED済" if row["ending"] else "")
            # ⭐ How many of the nine PLAYER bases her scenarios have filled in;
            # 6 is a 告白 gone through, the rest are メインイベント flags.
            + (f" 記録{len(row['record'])}" if row["record"] else "")
        )

    def endings(self) -> list[int]:
        """Candidate indices whose confession this character has received.

        In roster order, which is also the order the ending list goes out in.
        """
        return [candidate_index(name) for name in CANDIDATES
                if self.state[name]["ending"]]

    def debuts(self) -> list[int]:
        """Candidate indices who have appeared to this character.

        In roster order. The title screen's gallery list (0x0313) is made of
        this: p02_07 opens おまけ to 「ゲーム中に登場した恋愛候補生」, and
        登場 here is the same debut flag `on_stage` reads.
        """
        return [candidate_index(name) for name in CANDIDATES
                if self.state[name]["debut"]]

    def gallery(self) -> dict[int, int]:
        """Candidate index -> her 進行度, for everyone who has appeared.

        What the gallery list's photo bits are made of: 進行度 is how many
        メイン events she has shown this character after her debut.
        """
        return {candidate_index(name): self.state[name]["progress"]
                for name in CANDIDATES if self.state[name]["debut"]}

    # ── writing ────────────────────────────────────────────────────────────
    def debut(self, name: str) -> bool:
        """Mark her as having appeared, by hand (the /rom console command).

        The real trigger is a script write that `absorb` takes: her 初登校 for
        天宮 and 桜井, and for the other three the one ドラマイベント whose
        role writes her 登場 flag (春日 ← 『よろしくタイムマシーン』 役柄 1,
        弥生 ← 『キャプテンはお留守中』, 犬飼 ← 『家庭科部奉仕活動の日』; round
        232 read them off the scripts). This stays for steering a test.
        """
        if self.state[name]["debut"]:
            return False
        self.state[name]["debut"] = True
        return True

    def see_ending(self, name: str) -> bool:
        """Book her confession as received. True if this is the first time.

        Written by the one server-driven exit from her `_e011` -- 0x5606 with
        her index in it, which is what plays the credits -- and by hand from
        /rom <名前> ed for steering a test. ⚠️ Not by reading the letter: the
        manual's word is 告白, and 「読まない」 never gets there.
        """
        row = self.state[name]
        if row["ending"]:
            return False
        row["ending"] = 1
        return True

    def talk(self, name: str, today: str | None = None,
             gain: int = GAIN_PLAIN) -> bool:
        """One 日常会話 worth of 親密さ. True if the number moved.

        ⭐⭐⭐ Round 468 made this the **fallback**, and left it standing on
        purpose. The rule below is a transcription of the routine every
        日常会話 script ends with, and since round 468 the script runs that
        routine itself over cells this end supplies (`data_cells`,
        `absorb_talk_day`) -- so where there is an export, the game's own code
        is what credits and this is not called. It is still what a server with
        no exports does, and it is still what `/rom <名前> talk` pokes.
        ⛔️ Two readings of one rule is exactly what this project does not
        keep, so this is not a second opinion: the smoke test walks all 304
        scripts against it and a disagreement is a failure, not a choice.

        ``gain`` is what the script that just played is worth, which the caller
        gets from talk_gain(): a flat number for the 232 conversations that have
        only one, and since round 173 the value of the answer the player clicked
        for the 94 that offer several. Callers that pass nothing get GAIN_PLAIN,
        the flat 12 that two thirds of the scripts grant anyway.

        The day is the server's own calendar day. The game surely had its own
        clock — 校内マップ has seasons — but this end does not model one yet, and
        borrowing the real date keeps 「毎日少しずつ」 meaning something instead
        of nothing. Swap it when a game clock exists.

        ⚠️ The daily rule is the scripts' own: keep the best single grant of the
        day, so a repeat is worth the difference and a worse repeat is worth
        nothing. Returning False for that case is not an error — it is the
        manual's sentence happening.

        ⭐⭐⭐ Round 346: this credits and nothing more. Whether the number is
        now enough for her next メインイベント -- the 親密さ rung and, at
        進行度 0, the 能力 gate -- is her own `_s102`'s question, asked on the
        next right-click of a new day (`talk_cells`), and the step itself is
        booked by `_s104` when that event has played (`absorb_talk`). Until
        round 345 this method stepped 進行度 the moment the rung was reached,
        which is a reading nothing in the scripts supports: 親密さ is a
        running total, and the gates are absolute, so a rung once reached
        stays reached.
        """
        row = self.state[name]
        if not row["debut"]:
            return False
        today = today or date.today().isoformat()
        if row["lastTalk"] != today:
            row["lastTalk"] = today
            row["todayBest"] = 0
        credit = max(0, gain - row["todayBest"])
        if credit == 0:
            return False
        row["intimacy"] += credit
        row["todayBest"] = gain
        return True

    def gate_of(self, name: str) -> dict:
        """``{ability index: レベル needed}`` at her current 進行度, or ``{}``.

        The module-level ability_gate() takes a progress because that is what it
        keys on; this is the same question asked of a live sheet, and it exists
        so callers do not have to reach into ``state`` to find the progress.
        """
        return ability_gate(name, self.state[name]["progress"])

    def blocked_by_ability(self, name: str, levels: "list[int] | None") -> dict:
        """``{index: (have, need)}`` when 能力 is what is holding her back.

        Empty while 親密さ is still short of the rung: the two gates are both
        real, but only one of them is ever the answer to 「なぜイベントが出ない」
        at a time, and reporting the ability one before the intimacy one is met
        would name a reason that is not yet operative.
        """
        row = self.state[name]
        if not row["debut"] or row["intimacy"] < intimacy_needed(row["progress"]):
            return {}
        return ability_short(name, row["progress"], levels)

    def see_main_event(self, name: str) -> bool:
        """Step her 進行度 by hand (/rom ev), or when `_s104` cannot be run.

        ⭐⭐⭐ Round 346: this is no longer how a watched メインイベント counts.
        The original books it in `<name>_s104` -- run after the event ends,
        it steps `c000[0xd900]` only when `_s102` left -1 in `e100`, i.e.
        when the event it answered was the メイン -- and `absorb_talk` takes
        that write. So the count and its guard both live in the data; this
        stays for steering a test and as the fallback `_romance_credit`
        takes when the script is not on the machine.

        ⚠️ The round-171 question -- her debut event is itself a メイン (その１,
        category 0 id 0) and would count as a step if it came through here --
        is closed by the same move: 初登校 reaches nothing that runs `_s104`,
        and `_s104` counts nothing whose `e100` is not -1.
        """
        row = self.state[name]
        if not row["debut"] or row["progress"] >= CANDIDATES[name].events:
            return False
        row["progress"] += 1
        return True

    def set_progress(self, name: str, progress: int) -> bool:
        """Jump straight to a spot. Debut first — a story cannot be part-way
        along for somebody the player has not met, and letting it be would put a
        number in the save that /npca can never act on."""
        row = self.state[name]
        if not row["debut"]:
            return False
        want = max(0, min(progress, CANDIDATES[name].events))
        if row["progress"] == want:
            return False
        row["progress"] = want
        return True

    def set_intimacy(self, name: str, value: int) -> bool:
        """Put 親密さ at a number. The counterpart of set_progress, and needed
        for the same reason plus one more: the restored daily rule caps a day at
        one conversation's worth, so climbing a 72-step ladder by talking would
        take a rung per real day. Debut first, as with set_progress."""
        row = self.state[name]
        if not row["debut"] or row["intimacy"] == max(0, value):
            return False
        row["intimacy"] = max(0, value)
        return True

    def to_json(self) -> dict:
        return {**self.state, "letterEvent": self.letter_event,
                "sceneDay": {str(address): day
                             for address, day in sorted(self.scene_day.items())},
                "sceneTally": {str(address): count for address, count
                               in sorted(self.scene_tally.items())},
                "sceneFlag": {str(address): flag for address, flag
                              in sorted(self.scene_flag.items())},
                "sceneText": {str(address): value for address, value
                              in sorted(self.scene_text.items())}}

    # ── the scripts' view of all this ─────────────────────────────────────
    def data_cells(self) -> dict:
        """Every data cell this record can answer, as `gs3vm` wants them keyed.

        ⭐ Everything here is a number the save already holds; nothing is
        invented to fill a hole. A script that asks for a cell not in here gets
        `UnknownCell` from `gs3vm.Machine` or ⊤ from `gs3vm.Follower`, and both
        of those are better than a zero that reads like an answer.
        """
        cells: dict = {
            ("PC", PC_PLAYER_SEX): self.player_sex,
            ("PC", PC_LETTER_EVENT): self.letter_event,
        }
        for name, row in self.state.items():
            i = candidate_index(name)
            cells[("PC", PC_DEBUT_BASE + i)] = 1 if row["debut"] else 0
            cells[("PC", PC_LETTER_BASE + i)] = row["letter"]
            cells[("PC", PC_INTIMACY_BASE + i)] = row["intimacy"]
            cells[("PCEV", PCEV_PROGRESS_BASE + i)] = progress_cell(
                name, row["progress"], row["debut"]
            )
            cells[("CTX", (CTX_PROGRESS, TALK_CATEGORY_BASE + i))] = (
                row["progress"] + PROGRESS_OFFSET
            )
            # ⭐⭐⭐ Round 468: the 日常会話 daily rule's own two cells. Both are
            # numbers the save already holds -- `lastTalk` re-packed and
            # `todayBest` as it stands -- and supplying them is what lets the
            # script's own routine decide, instead of `talk` re-deciding it in
            # Python. ⚠️ Supplied unconditionally, unlike the register block
            # above: 「she has never been talked to」 is a state `pack_talk_day`
            # represents rather than a hole, and leaving the cell out would
            # make the routine undecidable on the very first conversation.
            cells[("PCEV", PCEV_TALK_DAY_BASE + i)] = pack_talk_day(
                _saved_day(row["lastTalk"]))
            cells[("PCEV", PCEV_TALK_BEST_BASE + i)] = row["todayBest"]
        # ⭐⭐ Round 467: the 告白 register block, and only the cells some
        # scenario has actually written. ⚠️ Sparse deliberately -- a cell
        # nobody has written reads ⊤, which is the whole reason the rest of
        # this method can be trusted (see the docstring above).
        cells.update(self.record_cells())
        return cells

    def scene_cells(self, cells: "frozenset[tuple[str, int]]") -> dict:
        """The day stamps of one scenario, as `gs3vm` wants them keyed.

        ⭐⭐⭐ Round 469. `cells` is what `scene_day_cells` read off that one
        scenario's bytecode, so nothing here decides which addresses exist --
        the scenario names them and this only says what is in them.

        ⚠️⚠️ Every one of them is answered, ⛔️ not just the ones the save has
        seen -- and that is the opposite of `record_cells` next door on
        purpose. 「this scene has never played」 is a state the packing
        represents (0, which is no day at all: `pack_talk_day(None)`), not a
        hole, and leaving the cell out would make the gate undecidable on the
        very first playing -- which is the whole of what was wrong before.
        """
        return {cell: pack_talk_day(_saved_day(self.scene_day.get(cell[1], "")))
                for cell in cells}

    def absorb_scene_day(self, writes: dict,
                         cells: "frozenset[tuple[str, int]]") -> bool:
        """Take a scenario's 「played today」 stamps back. True if one moved.

        ⭐⭐⭐ Round 469, and the sibling of `absorb_talk_day`: the number in
        the write is one the scenario's own arithmetic produced, so this only
        unpacks it and puts it where the next playing will read it.

        ⚠️ Fenced by `cells` -- the stamps of the scenario that ran, and not
        every PCEV a run wrote -- for `absorb_record`'s reason: several
        absorbers walk one `Result` and each must take only what is its own.

        ⚠️ A value this end cannot read back as a day is dropped rather than
        stored. The scenarios write 今日 and nothing else, so one that does not
        unpack is a run this end has not understood, and a save is the last
        place to put something like that.
        """
        changed = False
        for cell in sorted(cells):
            if cell not in writes:
                continue
            value = writes[cell]
            day = unpack_talk_day(value) if isinstance(value, int) else None
            if day is None:
                continue
            text = day.isoformat()
            changed |= self.scene_day.get(cell[1]) != text
            self.scene_day[cell[1]] = text
        return changed

    def tally_cells(self, cells: "frozenset[tuple[str, int]]") -> dict:
        """The play counts of one scenario, as `gs3vm` wants them keyed.

        ⭐⭐⭐ Round 470, and `scene_cells`' twin: `cells` is what
        `scene_tally_cells` read off that scenario's own bytecode, so nothing
        here decides which addresses exist.

        ⚠️⚠️ Every one of them is answered, ⛔️ not just the ones the save has
        seen, and the reason is stronger here than next door: the scenario's
        first gate is `== 0`, so 「never played」 is a number it asks for by
        name. A missing cell leaves that gate ⊤ and the opening scene
        unreachable, which is exactly what this round is fixing.
        """
        return {cell: self.scene_tally.get(cell[1], 0) for cell in cells}

    def absorb_tally(self, writes: dict,
                     cells: "frozenset[tuple[str, int]]") -> bool:
        """Take a scenario's 「played once more」 back. True if one moved.

        ⭐⭐⭐ Round 470. The number in the write is the one the scenario's own
        `+ 1` produced from what this end supplied, so this stores it as it
        stands rather than counting anything itself.

        ⚠️ Fenced by `cells` for `absorb_scene_day`'s reason, and a value that
        is not a non-negative integer is dropped rather than stored -- these
        scenarios add one to a count and nothing else, so anything else is a
        run this end has not understood.
        """
        changed = False
        for cell in sorted(cells):
            if cell not in writes:
                continue
            value = writes[cell]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                continue
            changed |= self.scene_tally.get(cell[1]) != value
            self.scene_tally[cell[1]] = value
        return changed

    def flag_cells(self, cells: "frozenset[tuple[str, int]]") -> dict:
        """The numbered-state cells of one scenario, as `gs3vm` wants them keyed.

        ⭐⭐⭐ Round 471, and `tally_cells`' twin down to the reason every one
        of them is answered rather than only the ones the save has seen: the
        gate these scenarios open with is `== 0`, so 「not yet」 is a value they
        name. Leave one out and that gate is ⊤ and the scene behind it never
        plays.
        """
        return {cell: self.scene_flag.get(cell[1], 0) for cell in cells}

    def absorb_flag(self, writes: dict,
                    cells: "frozenset[tuple[str, int]]") -> bool:
        """Take a scenario's 「it is this now」 back. True if one moved.

        ⚠️ Fenced by `cells` for `absorb_scene_day`'s reason, and a value out
        of 0..`gs3vm.FLAG_MAX` is dropped rather than stored -- these scenarios
        set these cells to one of a handful of small numbers and nothing else,
        which is the shape that recognised them in the first place.
        """
        changed = False
        for cell in sorted(cells):
            if cell not in writes:
                continue
            value = writes[cell]
            if (isinstance(value, bool) or not isinstance(value, int)
                    or not 0 <= value <= gs3vm.FLAG_MAX):
                continue
            changed |= self.scene_flag.get(cell[1]) != value
            self.scene_flag[cell[1]] = value
        return changed

    def text_cells(self, cells: "frozenset[tuple[str, int]]") -> dict:
        """The text cells of one scenario, as `gs3vm` wants them keyed.

        ⭐⭐⭐ Round 473, and `flag_cells`' twin except on the one point that
        divides them: ⛔️ **only cells the save actually holds are answered.**
        Its three neighbours answer every cell of their family because the
        scenarios gate on `== 0` and 0 is a value they name; nothing gates on
        this one -- the single read hands it to `SYNC_VARIABLE` -- so there is
        no 「not yet」 value to supply and a made-up one would be `PC[0x3201]`
        over again. An unanswered cell reads ⊤, `sync_values` sends the entry
        empty, and the 台詞 says what a zero-filled original's would.
        """
        return {cell: self.scene_text[cell[1]] for cell in cells
                if cell[1] in self.scene_text}

    def absorb_text(self, writes: dict,
                    cells: "frozenset[tuple[str, int]]") -> bool:
        """Take the word a scenario wrote down back. True if one moved.

        ⚠️ Fenced by `cells` for `absorb_flag`'s reason, and what passes is
        `_saved_scene_text`'s tolerance exactly: a pool reference or a typed
        line. ⛔️ Nothing here asks what the reference says -- the scenario
        that wrote it is the one that reads it back, and its own pool is where
        it means anything.
        """
        changed = False
        for cell in sorted(cells):
            if cell not in writes:
                continue
            value = writes[cell]
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                continue
            if isinstance(value, int) and value < 0:
                continue
            changed |= self.scene_text.get(cell[1]) != value
            self.scene_text[cell[1]] = value
        return changed

    def record_cells(self) -> dict:
        """Just the `PLAYER` half of `data_cells`, keyed the same way.

        ⭐ Its own method so that a caller can hand the block to a scenario
        without the rest of `data_cells` -- and so that 「what does this record
        answer」 has one place to be read from.
        """
        cells: dict = {}
        for name, row in self.state.items():
            i = candidate_index(name)
            for base in PLAYER_RECORD_BASES:
                value = row["record"].get(str(base))
                if value is not None:
                    cells[("PLAYER", base + i)] = value
        return cells

    def locker_cells(self, menu_item: int) -> dict:
        """`data_cells` plus the one thing the engine, not the save, supplies.

        ⚠️ Deliberately complete rather than lazy: `gs3vm` raises on a cell it
        was not given, and a missing cell should surface as a log line and a
        fallback, not as a branch quietly taken the wrong way.
        """
        return {**self.data_cells(), ("CTX", (CTX_MENU_ITEM, 0)): menu_item}

    def talk_cells(self, menu_item: int, levels: "list[int] | None",
                   today: "date | None" = None) -> dict:
        """Everything `<name>_s102` / `_s104` read: `locker_cells` plus the 会話
        slots of all five, today's date, and the 能力 レベル.

        ⭐ The date is the server's real one, the same clock `talk` keeps its
        daily rule on -- the script wants year, month and day as three SYSTEM
        cells and compares them with the ones it wrote last time, which is
        how 「a new day」 and 「more than a week」 are decided (2.287 二).
        ⚠️ ``levels`` may be None when there is no 能力 sheet to read; then the
        cells are simply not supplied, and a script that reads them (天宮's
        and 桜井's at 進行度 0) stops with UnknownCell rather than being
        told every レベル is 0 -- a fallback and a log line, not a gate
        quietly failed.
        """
        cells = self.locker_cells(menu_item)
        cells.update(date_cells(today))
        for name, row in self.state.items():
            i = candidate_index(name)
            talk = row["talk"]
            for key, slot in CTX_TALK_SLOTS.items():
                cells[("CTX", (slot, i))] = talk[key]
            cells[("CTX", (CTX_MAIN_SEEN, TALK_CATEGORY_BASE + i))] = talk["mainSeen"]
        if levels is not None:
            for j in range(5):
                cells[("PC", PC_ABILITY_BASE + j)] = levels[j] if j < len(levels) else 0
        return cells

    def absorb(self, writes: dict) -> bool:
        """Take a script run's cell writes back into the save. True if changed.

        ⚠️ `PC` only, and only the two ranges below. What is deliberately left
        out -- above all `PCEV[0x6020+i]` -- is argued where those constants
        are defined, not here, and the `PLAYER` register block has a method of
        its own for a reason `absorb_record` states.
        """
        names = list(CANDIDATES)
        changed = False
        for (family, address), value in writes.items():
            if family != "PC" or isinstance(address, tuple):
                continue
            if PC_DEBUT_BASE <= address < PC_DEBUT_BASE + len(names):
                # ⭐ Round 193: 初登校 drives this. Five scripts write it and
                # they are the five debuts (2.121 三) -- 天宮←amm_e001,
                # 桜井←skr_e001, the other three from a ドラマイベント.
                # ⚠️ Taken faithfully, including a 0: `sys_s000`, the original's
                # own new-game reset, is what clears them, and this end must not
                # decide that a debut is irreversible when the corpus says
                # otherwise. ⛔️ No script that reaches this path writes 0 today.
                row = self.state[names[address - PC_DEBUT_BASE]]
                changed |= row["debut"] != bool(value)
                row["debut"] = bool(value)
            elif PC_LETTER_BASE <= address < PC_LETTER_BASE + len(names):
                row = self.state[names[address - PC_LETTER_BASE]]
                changed |= row["letter"] != value
                row["letter"] = value
            elif address == PC_LETTER_EVENT:
                changed |= self.letter_event != value
                self.letter_event = value
        return changed

    def absorb_record(self, writes: dict) -> bool:
        """Take a run's `PLAYER[base+i]` writes into the register block.

        ⚠️⚠️ A method of its own rather than a third arm of `absorb`, and the
        reason is the caller and not the cells: `mps_session` runs three
        absorbers over one `Result` and each has to be able to say whether
        **its** record moved. While this lived in `absorb`, whichever sibling
        ran first swept the PLAYER writes up with its own and wrote the save,
        so the one whose block it actually was could only ever report 「already
        the same value」. ⭐ One absorber, one family, one verdict.

        ⚠️ Values go in exactly as the scenario computed them, text included,
        and an address outside `PLAYER_RECORD_BASES` is dropped rather than
        stored: the corpus writes those 45 cells and no others, so anything
        else is a scenario this end has never read, and guessing a home for it
        would be worse than losing it in a log line.
        """
        names = list(CANDIDATES)
        changed = False
        for (family, address), value in writes.items():
            if family == "PLAYER" and not isinstance(address, tuple):
                changed |= self._absorb_record_cell(names, address, value)
        return changed

    def _absorb_record_cell(self, names: list, address: int, value) -> bool:
        """One `PLAYER[base+i]` write into candidate i's block. True if moved."""
        for base in PLAYER_RECORD_BASES:
            index = address - base
            if not 0 <= index < len(names):
                continue
            record = self.state[names[index]]["record"]
            key = str(base)
            if record.get(key) == value:
                return False
            record[key] = value
            return True
        return False

    def absorb_talk_day(self, writes: dict) -> bool:
        """Take a 日常会話's own 親密さ arithmetic back. True if it moved.

        ⭐⭐⭐ Round 468, and it is what retires the transcription in `talk`:
        the three cells the daily rule is written over -- `PC[0x3920+i]`,
        `PCEV[0x6040+i]`, `PCEV[0x6060+i]` -- come back out of the run that
        computed them, so the rule is the scripts' and not a paraphrase of it.

        ⚠️⚠️ **Fenced by the two PCEV families, not by script id**, and that is
        the whole of the safety here. `PC[0x3920+i]` is written from two places
        in the corpus: this routine, and the メインイベント grants that
        `absorb_talk` books through 進行度 instead. The two PCEV families are
        written from **one** -- the 304 copies of this routine and nothing else
        in either script set -- so a run that wrote one of them is a 日常会話
        that reached its tail, and only then is the 親密さ write next to it
        this routine's. ⛔️ Take `PC[0x3920+i]` on its own and a メインイベント
        would be credited twice, once here and once as a rung.

        ⚠️ Three arms and only two of them write: 「a better answer today」
        moves 親密さ and the ceiling but not the day, and 「no better than
        today's best」 writes nothing at all, so no writes is the rule
        happening rather than a miss -- the same sentence `talk` returns False
        for.

        ⚠️ An index that does not agree across the cells is dropped rather than
        reconciled: the scan says all three carry the candidate the script
        belongs to, so a run where they disagree is one this end has not read.
        """
        names = list(CANDIDATES)
        touched = talk_day_writes(writes)
        changed = False
        for index, wrote in sorted(touched.items()):
            row = self.state[names[index]]
            if "day" in wrote:
                day = unpack_talk_day(wrote["day"])
                text = day.isoformat() if day is not None else ""
                changed |= row["lastTalk"] != text
                row["lastTalk"] = text
            if "best" in wrote:
                changed |= row["todayBest"] != wrote["best"]
                row["todayBest"] = wrote["best"]
            if "intimacy" in wrote:
                changed |= row["intimacy"] != wrote["intimacy"]
                row["intimacy"] = wrote["intimacy"]
        return changed

    def absorb_talk(self, writes: dict) -> bool:
        """Take the CTX writes of `_s102` / `_s104` / `_s101` back. True if changed.

        ⭐⭐⭐ Three scripts, three kinds of write, and 進行度 is the one that
        matters: `_s104` steps `c000[0xd900]` after a メイン played, and this
        is where that becomes ``progress`` (minus PROGRESS_OFFSET, clamped to
        her event count). `_s101` clears `d8` as it places her; `_s102` keeps
        the five e1xx slots. Anything else a run wrote (`0x8000` 「ran」, and
        the PC cells `absorb` handles) is left alone here.
        """
        names = list(CANDIDATES)
        by_slot = {slot: key for key, slot in CTX_TALK_SLOTS.items()}
        changed = False
        for (family, address), value in writes.items():
            if family != "CTX" or not isinstance(address, tuple):
                continue
            slot, subject = address
            value = int(value)
            if slot in by_slot and 0 <= subject < len(names):
                talk = self.state[names[subject]]["talk"]
                key = by_slot[slot]
                changed |= talk[key] != value
                talk[key] = value
            elif TALK_CATEGORY_BASE <= subject < TALK_CATEGORY_BASE + len(names):
                row = self.state[names[subject - TALK_CATEGORY_BASE]]
                if slot == CTX_MAIN_SEEN:
                    changed |= row["talk"]["mainSeen"] != value
                    row["talk"]["mainSeen"] = value
                elif slot == CTX_PROGRESS:
                    name = names[subject - TALK_CATEGORY_BASE]
                    want = max(0, min(value - PROGRESS_OFFSET, CANDIDATES[name].events))
                    changed |= row["progress"] != want
                    row["progress"] = want
        return changed

    def reset_talk(self, name: str) -> bool:
        """Put her 会話 slots back to what a new game has (/rom <名前> x).

        For steering a test: with the last-talk date at 0 the next right-click
        is 「a new day, first time ever」, which is the one that offers her
        メイン if 親密さ is there.

        ⭐ Round 468 puts the 日常会話 daily rule's own two cells back as well,
        and it is the same sentence rather than a second feature: a new game
        has never been talked to, so 「her 会話 slots」 includes 「no day, no
        ceiling」. ⛔️ Without this there is no way to steer a test of that
        rule at all -- it is the scenario that writes those two now, and a
        save stuck at today's ceiling makes every further conversation the
        third arm.
        """
        row = self.state[name]
        # ⭐ Round 469 adds her scenes' own stamps, and for round 468's reason
        # rather than a new one: a new game has played none of them, and with
        # her stamps left at today every one of her 日常会話 answers 「already
        # played」 and walks out at its first branch. ⛔️ Hers only -- the
        # partition is what `scene_day_cells_of` is for.
        mine = {cell[1] for cell in scene_day_cells_of(name)}
        stale = mine & set(self.scene_day)
        # ⭐ Round 470 adds her scenes' play counts on the same sentence: a new
        # game has played none of them, and a count left where it was makes the
        # opening scene unreachable for good -- it is the one arm that can only
        # play at 0.
        counted = {cell[1] for cell in scene_tally_cells_of(name)}
        stale_tally = counted & set(self.scene_tally)
        # ⭐ Round 471 adds her scenes' yes/no cells on the same sentence and
        # for the same reason: a new game has met her for the first time, and a
        # flag left set makes that scene unreachable for good.
        flagged = {cell[1] for cell in scene_flag_cells_of(name)}
        stale_flag = flagged & set(self.scene_flag)
        # ⭐ Round 473 adds her scenes' text cells on the same sentence, and
        # ⚠️ on its own it changes nothing observable: the arm that reads one
        # is behind the day stamp being cleared two lines up. It is here
        # because a row that has forgotten her must not still be holding the
        # word the player picked in a life she is no longer in.
        worded = {cell[1] for cell in scene_text_cells_of(name)}
        stale_text = worded & set(self.scene_text)
        if (row["talk"] == TALK_SLOT_DEFAULTS and not row["lastTalk"]
                and not row["todayBest"] and not stale and not stale_tally
                and not stale_flag and not stale_text):
            return False
        row["talk"] = dict(TALK_SLOT_DEFAULTS)
        row["lastTalk"] = ""
        row["todayBest"] = 0
        for address in stale:
            del self.scene_day[address]
        for address in stale_tally:
            del self.scene_tally[address]
        for address in stale_flag:
            del self.scene_flag[address]
        for address in stale_text:
            del self.scene_text[address]
        return True

    def waiting_letter(self) -> str | None:
        """Whose letter is in the locker, if anyone's."""
        for name, row in self.state.items():
            if row["letter"]:
                return name
        return None
