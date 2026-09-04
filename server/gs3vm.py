"""The GS3 bytecode machine, on the side of the wire that always ran it.

⭐ Why this belongs here and not in the client: the client's decoder table has a
slot function per command, and for the whole `OP_STR` / arithmetic family that
slot does two things and stops -- it formats the operands into the debug log and
pushes the instruction cursor past them. The `*_DATA_REFER` family is the same
stub. So the client never evaluates a script's arithmetic; when it reaches an
`OP_BR` it *asks*. The register file, the player-data reads and the branch
answers were always this end's job.

What runs on it, today, is the pair of scripts behind the row of lockers:

  lck_s103   menu_item 403 ロッカー開く -- decides whether there is a letter
             waiting, puts one there when the conditions are met, and emits the
             `sub_menu.bin` key the player should be offered.
  lck_s102   menu_item 404 -- reads which letter is waiting and calls the
             matching `<キャラ>_e011`.

Both are GSC files: the *original server's* own scripts, same bytecode as the
683 client scenarios. Running them is not a reimplementation of their rules --
the thresholds, the character ordering and the two-group split all stay in the
game's data where they were found.

The code they run over is written by the script exporter into
`runtime/scripts/<name>.gs3.json`, which -- like every other file under
`runtime/` -- is a local feed and reaches no repository.

⚠️ Deliberately unforgiving in two places, because a wrong answer here is worse
than no answer:

  * An opcode this module has not been taught raises `UnsupportedOp`.
  * A data cell the caller did not supply raises `UnknownCell` rather than
    reading as zero. The caller catches it, logs, and falls back to the
    behaviour that predates this module.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "runtime" / "scripts"


class UnsupportedOp(Exception):
    """An opcode this machine has not been taught. Never guessed at."""


class UnknownCell(Exception):
    """A data cell the caller did not supply. Never read as zero."""


class Runaway(Exception):
    """The step budget ran out -- a loop this machine cannot get out of."""


class _Top:
    """A value this machine cannot produce. Never a number, never falsy-by-luck.

    ⭐ It exists so that "I do not know" can travel through an expression
    instead of being rounded to zero somewhere in the middle of one. Anything
    arithmetic touches it with comes out as TOP again, and a branch that ends up
    testing it is a branch this end cannot answer -- which is a thing worth
    saying out loud rather than a coin to flip.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "⊤"

    def __bool__(self):
        raise UnsupportedOp("the truth of an unknown value was asked for")


TOP = _Top()


class _Die(_Top):
    """A `_Top` this end is *allowed* to settle: what an `OP_RAND` produced.

    ⭐⭐ The distinction is not a shade of confidence, it is about ownership.
    An ordinary TOP stands for a value that exists somewhere this end cannot
    see, so answering a branch over it would be guessing at somebody else's
    fact. A die has no owner at all: the client's slot for `OP_RAND` -- like
    every other arithmetic slot -- is a stub that pushes the cursor and logs
    (`reference/ssc_fields.tsv`), so *nobody* rolls it. Refusing is therefore
    not「leave it to the side that knows」, it is「answer fall-through, every
    time, forever」, which is what made the tutorial hand every player the same
    six キーワード (2.150).

    ⚠️⚠️ It settles the **branch**, never the register: the range `OP_RAND`
    draws from is still unread (its 143 sites dispatch on constants that a
    corpus scan cannot separate from register reuse), and inventing one would
    put a made-up number where a measured one belongs. A two-armed `OP_BR` is a
    two-way choice whatever the range is, so a coin at the branch needs no range.
    ⚠️ The cost, written down rather than hidden: an n-way ladder built out of
    two-armed branches comes out 1/2, 1/4, 1/4 … instead of uniform.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "\u22a4(die)"


DIE = _Die()


def _unknown(value) -> bool:
    """Is this one of the two things that are not a number?"""
    return isinstance(value, _Top)


def _merge_unknown(*values):
    """None if every value is a number; else DIE if every unknown is a die.

    ⭐ A die mixed with an ordinary unknown is an ordinary unknown: knowing what
    was rolled would still not settle the expression.
    """
    unknowns = [v for v in values if isinstance(v, _Top)]
    if not unknowns:
        return None
    return DIE if all(v is DIE for v in unknowns) else TOP


# Register categories, as the client's own decoder splits a 16-bit operand
# field: bits 0-6 are the number and bits 7-9 the category. 7 is not a category
# at all, it is "the number *is* the value".
CAT_IMMEDIATE = 7

# DECL_VARIABLE packs its two fields the other way round: the low 3 bits are the
# category and bits 3-9 the count. That split is read out of the client's slot
# for it (0x735b07), not fitted to the corpus -- fitting it to the corpus is how
# it was got wrong the first time.
DECL_CAT_MASK = 0x7
DECL_COUNT_MASK = 0x3F8
DECL_COUNT_SHIFT = 3

OP_DECL_VARIABLE = 0x9000
OP_STR = 0x9001
OP_RAND = 0x9010
OP_SYNC_VARIABLE = 0x903F
OP_JP, OP_BR, OP_BA = 0x9080, 0x9081, 0x9082
# ⭐ `ARITHMETIC` already knows what it does; it is named here because the
# 季節 switch is recognised by its shape and this is one of the three opcodes
# that shape is made of. See `Script.season_register`.
OP_EQ = 0x9009
OP_RTN, OP_END, OP_JS = 0x9083, 0x9084, 0x9085
OP_BA_END = 0x90C0
OP_EVENT_CALL = 0x9180

# ⭐⭐⭐ The last thing a ドラマイベント does before OP_END: it reports its own
# 結果. Round 234 read the 14-byte operand out of the client's decoder slot for
# it (0x7369BA), and the four fields are named by the client's own debug format
# 「評価ポイント名：%1%\n評価文：%2%\n入手キーワード数：%3%\n入手アイテム数：%4%\n」:
#
#     +2   u16   ⚠️ the client never reads these two bytes
#     +4   u32   (string-pool word offset << 12) | word length -> 評価文  (%2%)
#     +8   u32   the same encoding                             -> 評価ポイント名 (%1%)
#     +12  u32   bits 0-3 = 入手キーワード数 (%3%), bits 4-7 = 入手アイテム数 (%4%)
#
# ⚠️ %1% and %2% are the other way round from the operand: the slot feeds +8
# to the format first. ⛔️ Do not name them by offset order.
#
# ⭐ Three self-checks over all 296 occurrences in the 683 scenarios, no
# exceptions: both pool references' lengths match what the pool actually holds
# there; the second string always starts exactly where the first one ends; and
# +12 is zero everywhere ⇒ **this build hands out no keyword and no item here**.
#
# ⭐⭐ The unread +2, split the way every other register field is split (number
# in bits 0-6, category in bits 7-9), is always a 16BIT register -- and it is
# either one the scenario's own DECL_VARIABLE declared (16 of the 38 scenarios;
# B1..B12, written by the script and then compared with OP_GT/OP_LT to pick
# which ending plays) or B99, the temporary the compiler hands out from the top
# down (the other 22). ⇒ read as "which register holds this play's 評価ポイント",
# with B99 meaning the author bound no variable to it.
# ⚠️⚠️ That last one is a reading, not a measurement: the client never looks at
# the field, so this end is the only side that can use it -- and the only side
# that can ever prove it wrong.
OP_RESULT_MULTI_PLAYER_EVENT = 0x9200

# The choice box. The client stops dead on it and asks (0x721c); the answer is
# a bitmask, one bit per option, and the options' own on/off flags are the
# `SELITEM_DISP_FLAG` registers the script writes just before it. See
# `Follower.select`.
#
# ⭐⭐⭐ Its three operands, read in round 236 off the decoding slot's own field
# list (the field table, slot 153 at 0x734fc5: accesses at
# +2, +4 and +16, and the debug format string 「選択肢数：%1%\n制限時間(秒)：
# %2%\n選択者数(自分含む)：%3%」):
#
#   +2   u16  `(choosers << 12) | seconds` -- 選択者数(自分含む) and 制限時間.
#              Three values in the whole export: 0x1000 (1 chooser, no limit)
#              on all 31 boxes of the 10 solo scenarios, 0x103C (1 chooser,
#              60s) and 0x203C (2 choosers, 60s) in the ドラマイベント.
#   +4   u16  ⭐⭐⭐ **Which 役柄 is being asked** -- the same mask `OP_BA` uses,
#              bit n for 役柄 n. Not in the format string; the command object
#              carries it to the executor.
#   +16  u32  `(auxiliary word offset << 12) | option count`. See `select`.
#
# ⭐⭐ The mask at +4 is read, not guessed, and two independent alignments say
# so over the 709 boxes of the 37 exported scenarios, both with no exceptions:
#
#   * **Reachability.** A box only 役柄 0 can walk to never carries a mask
#     without bit 0 (54 of them are `1`, 42 are `3`), and a box only 役柄 1 can
#     reach never carries one without bit 1 (52 `2`, 42 `3`). All 31 boxes of
#     the solo scenarios -- where the only player is 役柄 0 -- are `1`.
#   * **Where the answer is read back.** The `OP_STR const; OP_EQ; OP_BR` chain
#     a script spells a selection out as reads `E<n>` for exactly the bit set:
#     mask 1 -> E0 on all 321 of them, mask 2 -> E1 on all 304, and the 84 with
#     mask 3 read both. E2 does not occur anywhere in the export.
#   * And the chooser count at +2 agrees on its own: mask 3 says two choosers
#     on all 84 of them, and every other box says one.
#
# ⇒ **A player's answer belongs in `E<their 役柄>`**, which is what `chose`
# does. ⛔️ Writing every answer into E0 -- what this end did before round 236
# -- leaves E1 empty for good, so every chain over a 役柄-1 box reads 0 and
# resolves to option 0 no matter what was clicked. Offline over the 22
# ドラマイベント that is not a subtle wrong answer: `un010`, `un117` and
# `un127` each have a 役柄-1 menu whose option 0 loops back to itself, so the
# play never ends (a 20-follower sweep over the scripts).
OP_INPUT_SELECT = 0x7000

# ⭐ The free-text box, and its two unused twins. The client stops on one the
# same way it stops on INPUT_SELECT -- a 0x721c Begin, and it sits there -- so
# a walk that steps over an unreported one has gone somewhere the client did
# not, which is the only thing STOPS is for.
#
# ⭐⭐⭐ **What comes out of one is the typed line itself, and the operand does
# say where it goes.** Round 248 read the client's own decoder for the command
# (0x73537a) rather than the operand's shape: `+2`'s low byte is the time limit
# in seconds and its top nibble the 役柄 whose box it is, `+4` is a register
# field shifted five bits left with the character limit in the five bits
# underneath, `+8` is the prompt and `+12` the answers the box offers.
#
# ⛔️ The 「選択肢番号：%1% = %2%」 line that round 245 read as *the result* is
# not one: it is printed in a loop over the answer list, once per answer, as
# part of the command's own dump. Nothing anywhere hands the script a number.
# ⭐ The scenarios settle it by themselves -- `un111` fills S0 with one player's
# guess at their partner's hobby and S1 with the partner's own answer and then
# compares the two registers, and `un122` compares its box's register against a
# surname of its own. ⇒ `typed` puts the line in the register and walks on.
OP_INPUT_STRING = 0x7001
OP_INPUT_STRING_PAGE = 0x7002
OP_INPUT_STRING_LOVE = 0x7003
INPUT_STRING_OPS = (OP_INPUT_STRING, OP_INPUT_STRING_PAGE, OP_INPUT_STRING_LOVE)

# ⭐⭐ The three commands that make a 日常会話's setting: which background is
# loaded, which ambient loop plays over it, and the fade-in. They are the whole
# of what a 進行度 switch's taken road contains, which is why `_scenery_road`
# recognises that switch by asking for a background. ⚠️ Since round 192 that is
# its only job: the gate deciding whether this end may answer a branch out of
# the script's own arithmetic is `_decided_road`, and it asks a different
# question.
OP_EVENT_BG_LOAD = 0x5100
# ⭐⭐ 台詞. Round 192 put it in `_undecidable`, round 193 took it back out
# (there: refusing a branch is not abstaining from it). ⚠️ Kept as a name
# because the road-gate study imports it from here (round 193 -- it had
# copied the literal) and its variants C/D still measure the set that forbids
# it. ⛔️ Deleting it would leave the tool that audits this decision unable to
# state the alternative it was weighed against.
OP_TALK_ON_EVENT = 0x5380
OP_EVENT_BG_DISP_ON = 0x5101
OP_SD_ENV_PLAY = 0x6080

# ⭐⭐ 春夏秋冬, numbered the way the game numbers them: `season.bin` is a real
# table with exactly four rows, 0=春 1=夏 2=秋 3=冬, and that is the numbering
# five of the 683 scenarios compare a 16-bit register against to pick which
# picture of one place to open with.
#
# ⭐⭐⭐ **The season was a live quantity in the original, not a constant.** Two
# official statements and one client-side reading say so: the manual's date-chat
# page notes 「※現在、学校外の背景に関しては、季節に対応しておりません」 -- a
# caveat with no meaning unless the *school* backgrounds did correspond -- the
# beta-2 report says 「β２テストは雪の中行われました。この季節しか体験できない
# 雪」, and the client reads `season.bin` through one accessor whose season key
# comes from a property named `SeasonName`, sitting in the string table beside
# `sakura` / `leaf` / `snow` / `fog` / `lobby_sakura`, a whole set of seasonal
# effects.
#
# ⚠️⚠️ **What is missing is only how that value reached the register.** The
# register file lives on this side of the wire (2.144, round 190), so the
# *original* server executed the scripts' own `OP_STR B0 = #<k>` and answered
# the four branches itself; whatever overrode `B0` lived in its code, which
# nobody has.
# ⛔️ So the constant in the .ssb is a development-time default, not the way the
# game looked: within one build the two tutorials pin 冬 and the three daily
# conversations pin 春, and the switch's default arm -- reachable only when `B0`
# is *not* 0..3 -- carries a `SYNC_VARIABLE B0` and the line 「季節＝＝$v00」
# under the speaker name 「デバッグ表示」.
#
# ⚠️⚠️ **That default arm is not hypothetical, and a player is what finds it.**
# A server with no exports gives all four arms the standing "no"
# (`script.Runner.resolve_branch`), the client walks past them into the debug
# line, and the `SYNC_VARIABLE` it carries is answered with an empty list, so
# the number it prints is the client's own untouched 0. `reference/
# season_switch.json` exists so that no copy of this server does that -- see
# `script._load_season_switch`.
# See `Script.season_register` and `Follower.season`.
SEASONS = 4
SEASON_NAMES = ("春", "夏", "秋", "冬")

# Two register categories this end has to name, out of the eight the operand
# encoding allows. 5 is SELITEM_DISP_FLAG -- one register per option of the
# next choice box, and the low five bits of the number are the option number
# (round 175). 6 is SELECT, where the client's answer lands.
#
# ⭐⭐⭐ **E<n> is 役柄 n's answer**, which round 236 read off the choice box's
# own 役柄 mask -- see `OP_INPUT_SELECT` above for the alignment. That is where
# the old note here ("the 38 scenarios that also use E1 are all multi-player
# events, which is a hint and not a reading") comes out: E1 is the second
# player's click, and this end now writes it.
CAT_SELITEM = 5
CAT_SELECT = 6

# The two string categories. The client keeps them as fixed-width buffers --
# 52 bytes for SSTRING and 148 for LSTRING, read straight off the write slots
# at 0x9f1e17 -- while this end keeps a reference into the .ssb's string pool,
# which `Script.strings` turns back into text. Nothing in the 683 scenarios
# ever synchronises an LSTRING; it is here because the client's own dispatch
# has it, not because it has been seen.
CAT_SSTRING, CAT_LSTRING = 3, 4
STRING_CATEGORIES = (CAT_SSTRING, CAT_LSTRING)

# What the client reports as it plays, and what that does *not* include.
#
# ⭐ Four of the five control-flow opcodes are reported every time they are
# passed. `OP_BA` is not: its slot (0x735d27) reports only on the branch it
# takes, and the fall-through half sends nothing at all. `OP_BA_END` is the
# same shape and is not a branch to begin with. So a walk that steps over an
# unreported `OP_BA` is not out of step -- the silence *is* the answer, which
# is why `Follower` needs no 役柄 ID (see there).
ALWAYS_REPORTED = {OP_JP, OP_BR, OP_RTN, OP_JS}

# The three that exist only in the 95 server-side scripts. 0xc000/0xc001 are a
# read/write pair over a slot space that is not player data -- it is what the
# engine handed the script for this call, so this module calls it CTX.
#
# ⭐⭐ A CTX address is two-dimensional: `(slot, subject)`, the subject being the
# u16 at +4. The corpus sorts itself: 0xd900 (a candidate's 進行度) only ever
# pairs with 16-20, 0xe100/0xe101 only with 0-4, and 0x8000/0x8103 only with 0 --
# which is exactly `capture_npc_event`'s two parallel category runs over the same
# five people (メインイベント = index, 日常会話 = index + 16). So the subject says
# *whose* value, and lck_s103's five blocks each read their own
# (0x11/0x12/0x10/0x13/0x14 = 春日/弥生/天宮/桜井/犬飼, in subroutine order).
#
# 0xa000
# carries one u16 and the whole 95-file corpus only ever gives it 0, 1, 2 or
# 0xffff; the three non-terminator values live in lck_s103 alone and they are
# exactly the sub_menu.bin keys 0 ロッカー起動 / 1 手紙イベント起動 /
# 2 ロッカー・手紙メニュー.
OP_CTX_REFER, OP_CTX_UPDATE = 0xC000, 0xC001
OP_EMIT = 0xA000
EMIT_END = 0xFFFF

# Even is a read, odd is the matching write, for every one of these families.
DATA_READ = {
    0x8000: "SYSTEM", 0x8080: "SCHOOL", 0x8100: "PLAYER", 0x8180: "PC",
    0x8182: "PCITEM", 0x8184: "PCKEY", 0x8201: "PCEV", 0x8203: "PCEV32",
}
DATA_WRITE = {op + 1: family for op, family in DATA_READ.items()}

# ⭐ The キーワード pair, named apart because `Machine` decodes their operands
# by a layout of their own (see the KEYWORD_OPS case). ⚠️ They stay in
# DATA_READ/DATA_WRITE as well: for every purpose but one, 0x8185 is exactly
# what it looks like -- a write that persists, and `Result.keywords` is how it
# reaches a save.
# ⚠️⚠️ The one exception is `_undecidable`, which since round 195 lets a branch
# through whose road writes ONLY this. ⛔️ That is argued there and nowhere
# else; do not read it back into this comment as 「キーワード is not a write」.
OP_KEYWORD_REFER, OP_KEYWORD_UPDATE = 0x8184, 0x8185
KEYWORD_OPS = (OP_KEYWORD_REFER, OP_KEYWORD_UPDATE)


def _quotient(a: int, b: int) -> int:
    """C truncating division, which is not Python's floor division."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


ARITHMETIC = {
    0x9002: lambda a, b: a + b,
    0x9003: lambda a, b: a - b,
    0x9004: lambda a, b: a * b,
    # ⚠️ Division by zero is a value nobody can name, so it becomes TOP rather
    # than an invented answer or an exception -- the same rule as a cell this
    # machine was not given.
    0x9005: lambda a, b: TOP if b == 0 else _quotient(a, b),
    0x9006: lambda a, b: TOP if b == 0 else a - _quotient(a, b) * b,
    0x9007: lambda a, b: 1 if (a or b) else 0,
    0x9008: lambda a, b: 1 if (a and b) else 0,
    0x9009: lambda a, b: 1 if a == b else 0,
    0x900A: lambda a, b: 1 if a != b else 0,
    0x900B: lambda a, b: 1 if a > b else 0,
    0x900C: lambda a, b: 1 if a >= b else 0,
    0x900D: lambda a, b: 1 if a < b else 0,
    0x900E: lambda a, b: 1 if a <= b else 0,
}

#: The two of them that mean anything over text: `==` and `!=`. See
#: `Machine._as_text`.
STRING_COMPARISONS = (0x9009, 0x900A)

# OP_NOT is the one that reads a single operand out of the same block.
OP_NOT = 0x900F


def _register(field: int) -> tuple[int, int]:
    """A 16-bit operand field -> (category, number)."""
    return (field >> 7) & 7, field & 0x7F


def _arith_registers(args: bytes) -> tuple[tuple, tuple, tuple]:
    """An arithmetic operand block -> (result, left, right)."""
    a = int.from_bytes(args[0:2], "little")
    b = int.from_bytes(args[2:4], "little")
    return (
        _register(a),
        ((a >> 10) & 7, b & 0x7F),
        ((a >> 13) & 7, (b >> 7) & 0x7F),
    )


def _refer_register(args: bytes):
    """The register end of a data-family instruction, or None for a sentinel.

    This family is a stub in the client, so the layout was matched rather than
    read: the same encoding shifted left by five. The 0xffff sentinels are the
    reason for the mask -- they are not registers.
    """
    field = int.from_bytes(args[0:2], "little")
    return None if field & 0x1E else _register(field >> 5)


# The letters the client's own debug strings use for the eight operand
# categories, so that a log line here reads the same as one out of
# the opcode table next door: F0 is a flag, B2 a 16-bit, S0 a short string.
REGISTER_LETTERS = {0: "F", 1: "B", 2: "D", 3: "S", 4: "L", 5: "P", 6: "E"}


def register_name(reg: tuple[int, int]) -> str:
    """`(category, number)` as `B2` / `S0`, or `#n` for an immediate."""
    category, number = reg
    if category == CAT_IMMEDIATE:
        return f"#{number}"
    return f"{REGISTER_LETTERS.get(category, '?')}{number}"


def cell_name(family: str, address) -> str:
    """`PC[0x3a04]` / `CTX[0xd900@0x11]` -- how a data cell is named in a log."""
    where = (f"{address[0]:#06x}@{address[1]:#04x}"
             if isinstance(address, tuple) else f"{address:#06x}")
    return f"{family}[{where}]"


def _ctx_address(args: bytes) -> tuple[int, int]:
    """A 0xc000 / 0xc001 address: (slot, subject). See the OP_CTX_* comment."""
    return int.from_bytes(args[2:4], "little"), int.from_bytes(args[4:6], "little")


def _jump_target(args: bytes) -> int:
    """Where an OP_JP / OP_BR goes. ip counts u16 words."""
    return int.from_bytes(args[3:6], "little") >> 4


def _scenery_road(script: "Script", index: int) -> bool:
    """Does taking the OP_BR at `index` change nothing but the scenery?

    ⭐⭐ This is the whole of what lets one branch family be answered out of the
    script's own arithmetic while every other branch keeps the standing "no"
    (`script.Runner.resolve_branch`). The test is on the *road*, not on the
    condition: walk where the branch would go and ask whether anything on it can
    be seen by the save or by the story. Concretely it must load a background
    and it must not contain a data-cell write, an `EVENT_CALL`, a choice box, or
    an `OP_BA`.

    ⚠️ Measured over the whole corpus before it was wired to anything: of the
    2756 `OP_BR` whose condition reads nothing but `PCEV[0x6020+i]`, 2589 are
    this shape and **4** reach a `PCEV` write (`ink_c511`/`c513`/`c515`,
    `ksg_c511`). ⛔️ So "the condition is 進行度" is *not* a safe test on its
    own, which is why this one looks at the destination.

    ⚠️ `OP_JP` ends the walk rather than being followed: it is where the switch
    arm rejoins the scenario, and everything past that point is the conversation
    itself, which this branch did not decide.

    ⭐ Module-level rather than a method because `Script.season_register` asks
    the same question of a branch nobody is standing on yet.
    """
    if not 0 <= index < len(script.code) or script.code[index][1] != OP_BR:
        return False
    start = script.index.get(_jump_target(script.code[index][2]))
    if start is None:
        return False
    forbidden = set(DATA_WRITE) | {OP_EVENT_CALL, OP_INPUT_SELECT, OP_BA, OP_BR}
    loads_background = False
    pending, seen = [start], set()
    while pending:
        i = pending.pop()
        if i is None or i in seen or not 0 <= i < len(script.code):
            continue
        seen.add(i)
        op = script.code[i][1]
        if op in forbidden:
            return False
        if op == OP_EVENT_BG_LOAD:
            loads_background = True
        if op in (OP_RTN, OP_END, OP_JP):
            continue
        if op == OP_JS:
            number = int.from_bytes(script.code[i][2][0:2], "little") & 0x3FF
            if not 1 <= number <= len(script.labels):
                return False
            pending.append(script.index.get(script.labels[number - 1]))
        pending.append(i + 1)
    return loads_background


#: One of these on the road and this end must not answer the branch. Three
#: separate reasons, deliberately named apart: the save can see it
#: (`DATA_WRITE`); another event can start from it (`OP_EVENT_CALL`); or this
#: end simply does not know (`OP_INPUT_SELECT` is the player's answer, `OP_BA`
#: is a 役柄 test whose result only the client holds).
#: ⚠️ 台詞 used to be a fourth reason and is not one any more -- see the
#: docstring, and the road-gate study for what that cost and bought.
def _undecidable(op: int) -> bool:
    """Does this instruction put the branch that reaches it out of reach here?

    ⚠️⚠️ `OP_TALK_ON_EVENT` was in this set until round 193, on the reading
    「a branch that decides who says what decides the *story*」. ⛔️ What that
    reading leaves out is that refusing is not abstaining: nothing else answers
    an `OP_BR` this end declines, so the client is sent fall-through -- the same
    arm, every run, forever. The tutorial is the case that made the cost
    visible: `amm_e001` ip=1676 guards 「キーワード【$s02】を手に入れた。」, the
    evaluator works its condition out exactly (`vm cond=1`), and six times per
    run the line was suppressed by a constant (2.150). ⇒ the choice is not
    「decide or leave it alone」, it is 「a computed answer or a fixed one」.

    ⭐⭐⭐ Round 195 applied that same sentence to ONE opcode of the write half,
    `PC_KEYWORD_UPDATE`, because the same tutorial turned out to be paying for
    it in the save rather than on the screen (2.151):

      * `amm_e001` ip=554 and `skr_e001` ip=640 guard 「`F1 == 0` ⇒ hand out the
        six」 -- the tail fallback for a player the scenario has not already
        given them to. The evaluator answers it exactly (`vm cond=1`), this gate
        refused it because `PC_KEYWORD_UPDATE` sits on the road, and the client
        was sent the other arm ⇒ a character who plays the long tutorial and
        answers 「説明してもらわなくていい」 ended it with **none**. Round 194 saw
        exactly that on a real client and read it as a scenario condition.
      * ⛔️ There is no such condition. `<name>_e001` calls the granting
        subroutine from THREE places -- the skip arm, the mid-scenario
        explanation, and this fallback -- and between them they cover every
        route the scenario can end on. The original granted on all of them.

    ⭐⭐ Why this opcode and not the family it sits in, which stays forbidden:

      * This end already hands out キーワード from a scenario (`_script_keywords`,
        round 193), and the six `OP_RAND` branches INSIDE that very subroutine
        have always been answered here, because `_Die` is deliberately not gated
        by `_decided_road`. Deciding WHICH キーワード while refusing to decide
        WHETHER any is handed over at all is one policy, not two.
      * A キーワード is SET MEMBERSHIP and `Membership.owns_keyword` gates the
        grant, so the worst a wrong answer does is add one the scenario itself
        names on that road. The rest of `DATA_WRITE` is QUANTITY -- 親密さ,
        進行度, the per-day gain ceiling -- where a wrong answer moves a number
        and no idempotence catches it.
      * ⭐ Measured, which is why the line is at one opcode: dropping the whole
        family admits far more, and the overwhelming majority of those extra
        roads write `PC[0x392x]` / `PCEV[0x606x]`, the 日常会話 好感度 machinery,
        which is gameplay, and not this end's to decide.

    ⭐ What protects a save here is not this test but the one before it:
    `_decided_road` is consulted only when the shadow's verdict is definite, and
    definite means computed over registers the scenario itself declared
    (`OP_DECL_VARIABLE` zero-fills them, so `F1 == 0` is the scenario's own
    starting value and not an assumption made here) plus cells this end actually
    supplied -- an unsupplied cell reads ⊤ and refuses on its own.

    ⭐ The road-gate study prints all of it: variant E is the set before
    this change, F the whole family dropped, G this one. ⚠️ Re-run, do not quote.
    """
    if op == OP_KEYWORD_UPDATE:
        return False
    return op in DATA_WRITE or op in (OP_EVENT_CALL, OP_INPUT_SELECT, OP_BA)


def _successors(script: "Script", i: int) -> list:
    """Where control can go from `i`.

    ⚠️ Both arms of an `OP_BR`, and an `OP_JS` counts as 「into the subroutine
    *and* on to the next instruction」 -- a caller that only followed one of the
    two would certify a road it had half walked.
    """
    op, args = script.code[i][1], script.code[i][2]
    if op in (OP_RTN, OP_END):
        return []
    if op == OP_JP:
        return [script.index.get(_jump_target(args))]
    out = [i + 1]
    if op == OP_BR:
        out.append(script.index.get(_jump_target(args)))
    elif op == OP_JS:
        number = int.from_bytes(args[0:2], "little") & 0x3FF
        out.append(script.index.get(script.labels[number - 1])
                   if 1 <= number <= len(script.labels) else None)
    return out


def _reachable(script: "Script", start: int) -> set:
    seen, pending = set(), [start]
    while pending:
        i = pending.pop()
        if i is None or i in seen or not 0 <= i < len(script.code):
            continue
        seen.add(i)
        pending.extend(_successors(script, i))
    return seen


def _decided_road(script: "Script", index: int):
    """What taking the `OP_BR` at `index` decides, or None if this end may not.

    ⭐⭐⭐ The gate `_scenery_road` used to be, done properly. Same principle --
    judge the *destination*, not the condition -- and two fixes to how the
    destination is bounded, both measured in round 192 (2.147 八, and
    the road-gate study reproduces the numbers):

    ⚠️ **`OP_JP` used to end the walk**, on the reading 「that is where the
    switch arm rejoins the scenario」. True for the 進行度 switch and false in
    both directions elsewhere:

      * **Under-reach.** In a dispatch tree the `OP_JP`s are the tree's own
        plumbing, so the walk stopped after ONE instruction and then refused for
        lack of a background. That is what kept 自分のクラス falling through and
        the tutorial walking the player to the wrong floor.
      * **Over-reach.** When an arm's `OP_JP` went somewhere the fall-through
        cannot reach, the old walk ran on into the rest of the scenario -- 74
        instructions on average where the real road is 68, and in 17 branches of
        `un043`/`un066` it sailed past an `OP_BA` it should have seen. ⛔️ Those
        were being admitted, which is exactly what 2.137 五 warned about.

    ⭐ The bound that is right for both: **stop where the fall-through can also
    get to.** That is the branch's merge point, and it costs one extra
    reachability walk rather than a dominator tree. It provably cannot shorten
    the 進行度 switch's road, because that arm's rejoin *is* reachable from the
    fall-through.

    ⚠️ The other change is that 「the road must load a background」 is gone. It
    was a shape filter, not a safety one -- and a leaky filter, since the
    over-reaching walk would find a background 200 instructions downstream that
    the branch had nothing to do with. What replaces it is `_undecidable`.

    ⭐ Corpus (778 scripts, 16313 `OP_BR`; ⚠️ re-run rather than quoting):
    `_scenery_road` admits 2861, this admits 7966, and the 199 the old one
    admitted that this one does not are **all** in `unNNN` (183) and `_eNNN`
    (16) -- **not one is in the `_cNNN` 日常会話 family**, which is the only one
    2.137 ever ran on a screen. So the feature that exists keeps every branch it
    had.

    ⚠️⚠️ `_scenery_road` is deliberately left standing: `Script.season_register`
    uses it as a *shape* recogniser, and its 「the arms only swap backgrounds」
    half is what keeps that from matching the 24 scripts where a four-armed
    0..3 switch is 曜日 or 学年 instead.
    """
    start = script.index.get(_jump_target(script.code[index][2]))
    if start is None:
        return None
    merge = _reachable(script, index + 1)
    pending, seen = [start], set()
    while pending:
        i = pending.pop()
        if i is None or i in seen or not 0 <= i < len(script.code):
            continue
        if i in merge:
            continue  # the two arms have rejoined; past here is not this branch
        seen.add(i)
        if _undecidable(script.code[i][1]):
            return None
        pending.extend(_successors(script, i))
    return seen


class Script:
    """One exported script: its instructions and its label table."""

    def __init__(self, doc: dict) -> None:
        self.name = doc["name"]
        # ⭐ "GSC" is one of the original server's own 95 scripts, "SSC" one of
        # the client's 683 scenarios. Same bytecode, opposite sides of the wire,
        # and that difference is the whole of `_uninstructed` below.
        self.container = doc.get("container", "GSC")
        # The two fields the 0x72xx handshake needs and the bytecode does not:
        # the client names a scenario by number and reports its cursor in file
        # bytes, while everything in here counts u16 words from the code
        # section. None/0 for a server script, which the client never names.
        self.script_id = doc.get("scriptId")
        self.code_base = doc.get("codeBase", 0)
        self.labels = list(doc["labels"])
        self.code = [(ip, op, bytes.fromhex(args)) for ip, op, args in doc["code"]]
        self.index = {ip: i for i, (ip, _, _) in enumerate(self.code)}
        # The two things a SYNC_VARIABLE needs and the instruction stream does
        # not carry. Which registers it synchronises lives in the .ssb's
        # auxiliary table, and a string register's value is a reference into
        # the .ssb's string pool -- neither of which this end has, or wants to
        # have (the export exists so that no .ssb parser lives here). Both are
        # optional: an export made before round 190 has neither, and a script
        # with no SYNC_VARIABLE in it needs neither.
        self.sync = {int(ip): [tuple(r) for r in regs]
                     for ip, regs in doc.get("sync", {}).items()}
        self.strings = {int(v): text for v, text in doc.get("strings", {}).items()}
        # ⭐ The free-text boxes, by ip: `{"register": (category, number),
        # "characters": limit, "actor": whose box it is, "answers": [what the
        # box offers]}`. Optional the same way `sync` and `strings` are -- an
        # export made before round 248 has none, and a follower then stands down
        # at a box rather than inventing a destination for what was typed
        # (`Follower.typed`). ⚠️ `actor` arrived one round later still, so it is
        # None rather than 0 when the export predates it: 0 would be a claim,
        # and `Follower.at` reads the absence as "cannot say" (see there).
        self.inputs = {
            int(ip): {"register": tuple(box["register"]),
                      "characters": box.get("characters", 0),
                      "actor": box.get("actor"),
                      "answers": list(box.get("answers", ()))}
            for ip, box in doc.get("inputs", {}).items()
        }
        # ⭐ Which register, if any, this script picks its backgrounds' season
        # out of. Computed here because it is a property of the instruction
        # stream and nothing else, and asked for at most once per script.
        self.season_register = self._season_register()
        # ⭐ How big this scenario's register file is, per category, out of its
        # own DECL_VARIABLE prologue. Read here rather than off `Machine`'s
        # registers because presence there cannot tell a declared register from
        # a compiler temporary: both have been written by the time anything
        # asks. The one caller is `Follower.event_result`, which has to tell
        # exactly those two apart.
        self.declared: dict[int, int] = {}
        for _, op, args in self.code:
            if op != OP_DECL_VARIABLE:
                break                      # the prologue, and nothing after it
            field = int.from_bytes(args[0:2], "little")
            self.declared[field & DECL_CAT_MASK] = (
                (field & DECL_COUNT_MASK) >> DECL_COUNT_SHIFT
            )

    def _season_register(self) -> tuple[int, int] | None:
        """The register a four-armed 春夏秋冬 switch tests here, or None.

        ⭐⭐ Recognised by shape, ⛔️ not by a table of script names, because a
        table would have to be trusted and this can be re-derived:

            OP_STR  Fx = #k            k = 0, then 1, then 2, then 3
            OP_EQ   Fy = (R == Fx)     the same R every time
            OP_JP   -> the OP_BR that tests Fy
            OP_BR   Fy, and its taken road is `_scenery_road`

        ⭐ Run over all 683 scenarios it answers exactly five of them, and the
        register is `B0` in all five: `amm_e001` and `skr_e001` (the two
        tutorials, four switches each -- one per scene, all on the same
        register) and `isu_c002`/`kmn_c002`/`tik_c002`. That is the same five
        that a completely different criterion found -- the only places where one
        location has more than one seasonal background in `bg.bin` -- which is
        what makes this a reading rather than a pattern that happened to fit.

        ⚠️ Without the `_scenery_road` half the same shape answers 24 scripts:
        a four-armed switch on 0..3 is also how 曜日 and 学年 are tested. ⛔️ So
        the shape alone is not the criterion; where the arms *go* is.
        """
        by_register: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
        for i, (_, op, args) in enumerate(self.code):
            if op != OP_STR or i + 2 >= len(self.code):
                continue
            field = int.from_bytes(args[0:2], "little")
            if (field >> 10) & 7 != CAT_IMMEDIATE:
                continue
            value = int.from_bytes(args[2:6], "little")
            if value >= SEASONS:
                continue
            constant = _register(field)
            if self.code[i + 1][1] != OP_EQ:
                continue
            result, left, right = _arith_registers(self.code[i + 1][2])
            if right != constant or left[0] == CAT_IMMEDIATE:
                continue
            if self.code[i + 2][1] != OP_JP:
                continue
            branch = self.index.get(_jump_target(self.code[i + 2][2]))
            if branch is None or self.code[branch][1] != OP_BR:
                continue
            tested = _register(int.from_bytes(self.code[branch][2][0:2], "little"))
            if tested != result:
                continue
            by_register.setdefault(left, []).append((i, value, branch))
        for register, arms in by_register.items():
            arms.sort()
            for n in range(len(arms) - SEASONS + 1):
                run = arms[n:n + SEASONS]
                if [value for _, value, _ in run] != list(range(SEASONS)):
                    continue
                if all(_scenery_road(self, branch) for _, _, branch in run):
                    return register
        return None

    def local_ip(self, wire: int) -> int:
        """The client's cursor (file bytes) in this module's unit (u16 words)."""
        return (wire - self.code_base) // 2

    def wire_ip(self, ip: int) -> int:
        return self.code_base + ip * 2


def load(name: str) -> Script | None:
    """`runtime/scripts/<name>.gs3.json`, or None when it is simply not there.

    Missing means "nothing known", the same way mapgraph's graph and the branch
    table mean it. A server with no exported scripts keeps the behaviour it had
    before this module existed.
    """
    try:
        doc = json.loads((SCRIPT_DIR / f"{name}.gs3.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Script(doc)


def by_script_id(script_id: int) -> Script | None:
    """The exported scenario the client is asking for, by the only name it uses.

    Linear over a directory of a handful of files, like `script.by_script_id`
    next door, and for the same reason: exports exist only on a machine that
    made them, and a machine that made them has a few.
    """
    if not SCRIPT_DIR.is_dir():
        return None
    for path in sorted(SCRIPT_DIR.glob("*.gs3.json")):
        found = load(path.name[: -len(".gs3.json")])
        if found is not None and found.script_id == script_id:
            return found
    return None


class Result:
    """What one run produced: menu keys offered, events called, cells written."""

    def __init__(self) -> None:
        self.menus: list[int] = []
        self.events: list[tuple[int, int]] = []
        self.writes: dict[tuple[str, int], int] = {}
        # Cells the script wrote a value this machine could not produce into.
        # Kept out of `writes` on purpose -- see the DATA_WRITE case.
        self.unknown_writes: set[tuple[str, int]] = set()
        # ⭐ `(actorIndex, keywordId)` per PC_KEYWORD_UPDATE, in script order.
        # Apart from `writes` because it is not a cell with a value -- the
        # instruction carries no value operand at all, it hands somebody a
        # キーワード -- and because the caller persists it through a different
        # record (`club.Membership.grant_keyword`) than the 恋愛 cells.
        self.keywords: list[tuple[int, int]] = []
        # {opcode: how often it was stepped over}. See `Machine._uninstructed`.
        self.passed: Counter = Counter()

    @property
    def menu(self) -> int | None:
        """The key to answer a sub-menu request with: the last one offered.

        lck_s103 offers 1 then 2 on the run that puts a new letter in the
        locker, and 2 alone when one is already there. Both runs end at the same
        screen -- ロッカー・手紙メニュー, the parent of ロッカー起動 and
        手紙イベント起動 -- so the last key is the one to send, and it is also
        the one this server sent unconditionally before it could ask.
        """
        offered = [key for key in self.menus if key != EMIT_END]
        return offered[-1] if offered else None

    @property
    def event(self) -> tuple[int, int] | None:
        """The first `capture_npc_event` key called, or None if there was none."""
        return self.events[0] if self.events else None

    def __repr__(self) -> str:
        return (
            f"menus={[hex(m) for m in self.menus]} "
            f"events={self.events} writes={sorted(self.writes)}"
        )

    def summary(self) -> str:
        """One line for a log: what a run produced, unknowns included."""
        parts = [f"{family}[{slot:#06x}]={value}"
                 for (family, slot), value in sorted(self.writes.items())]
        parts += [f"{family}[{slot:#06x}]=⊤"
                  for family, slot in sorted(self.unknown_writes)]
        got = " ".join(f"{actor}:{keyword_id}" for actor, keyword_id in self.keywords)
        return ("writes: " + (" ".join(parts) if parts else "none")
                + (f" · keywords (actor:id) {got}" if got else "")
                + f" · stepped over {sum(self.passed.values())} client commands"
                + f" ({len(self.passed)} kinds)")


class Machine:
    """One run of one script over one set of data cells.

    `cells` is `{(family, slot): value}` -- with CTX keyed by `(slot, subject)`
    instead -- and is read-only: everything the script
    writes lands in `Result.writes` for the caller to persist, so a run that
    throws half way leaves nothing behind.
    """

    STEP_BUDGET = 200_000

    def __init__(self, script: Script, cells: dict[tuple[str, int], int]) -> None:
        self.script = script
        self.cells = dict(cells)
        self.registers: dict[tuple[int, int], int] = {}
        self.stack: list[int] = []
        self.result = Result()

    # ── values ────────────────────────────────────────────────────────────
    def _get(self, reg: tuple[int, int]) -> int:
        category, number = reg
        if category == CAT_IMMEDIATE:
            return number
        try:
            return self.registers[reg]
        except KeyError:
            # Only a declared register has a defined starting value. Anything
            # else is a compiler temporary, which is always written before it is
            # read -- so reaching this is a bug in the machine, not in the data.
            raise UnsupportedOp(
                f"{self.script.name}: read of undeclared register {reg}"
            ) from None

    def _as_text(self, op: int, value):
        """One side of a comparison a player's own words are on the other of.

        ⭐⭐ A string register normally holds a reference into the .ssb's string
        pool, and two of them are equal when the references are. A line the
        player typed has no reference -- it never was in the pool -- so it is
        kept as the text it is (`Follower.typed`), and the moment one turns up
        in a comparison the *other* side has to be read as text too or a
        scenario would be told its own literal is not what was typed no matter
        what was typed. `un122` is exactly that comparison and `un111`'s is the
        one with a typed line on both sides.

        ⚠️ Only equality. Nothing orders two strings on this wire, and a `<`
        over one would be this end inventing a collation; TOP says so instead.
        ⚠️ A reference the export carries no text for is TOP for the same
        reason -- the answer is knowable and this copy does not know it.

        ⚠️⚠️ INVENTED: that two strings are the same one when their characters
        are, exactly, with nothing folded. The original server is the only side
        that ever ran this comparison -- the client's arithmetic slots are
        stubs -- so its rule went with it, and this is the smallest thing that
        can stand in its place. ⭐ It matters in play: it decides whether a
        player who typed カフェテリア for 「おいおい、それは○○だろう？」 is told
        they are right. ⛔️ The competing reading is one call away and was NOT
        taken -- `ngwords.fold` folds kana and case for the banned-word table,
        on evidence from that table itself, and there is no such evidence here.
        """
        if op not in STRING_COMPARISONS:
            return TOP
        if isinstance(value, str):
            return value
        return self.script.strings.get(value, TOP)

    def _cell(self, family: str, address) -> int:
        try:
            return self.cells[(family, address)]
        except KeyError:
            raise UnknownCell(
                f"{self.script.name}: {cell_name(family, address)}"
            ) from None

    # ── one instruction ───────────────────────────────────────────────────
    def _step(self, i: int) -> int | None:
        """Execute instruction `i`; return the next index, or None to stop."""
        ip, op, args = self.script.code[i]

        if op == OP_DECL_VARIABLE:
            field = int.from_bytes(args[0:2], "little")
            category = field & DECL_CAT_MASK
            count = (field & DECL_COUNT_MASK) >> DECL_COUNT_SHIFT
            for number in range(count):
                self.registers[(category, number)] = 0
            return i + 1

        if op == OP_STR:
            field = int.from_bytes(args[0:2], "little")
            value = int.from_bytes(args[2:6], "little")
            source_category = (field >> 10) & 7
            self.registers[_register(field)] = (
                value if source_category == CAT_IMMEDIATE
                else self._get((source_category, value))
            )
            return i + 1

        if op in ARITHMETIC:
            result, left, right = _arith_registers(args)
            a, b = self._get(left), self._get(right)
            unknown = _merge_unknown(a, b)
            if unknown is None and (isinstance(a, str) or isinstance(b, str)):
                a, b = self._as_text(op, a), self._as_text(op, b)
                unknown = _merge_unknown(a, b)
            self.registers[result] = (
                unknown if unknown is not None else ARITHMETIC[op](a, b)
            )
            return i + 1

        if op == OP_NOT:
            # The one arithmetic instruction with a single source, read out of
            # the same operand block as the rest.
            result, left, _ = _arith_registers(args)
            a = self._get(left)
            unknown = _merge_unknown(a)
            self.registers[result] = (
                unknown if unknown is not None else (1 if a == 0 else 0))
            return i + 1

        if op == OP_RAND:
            # ⭐ Taught rather than left to `_uninstructed`, and still taught
            # as unknown: this machine does not produce the number, because the
            # range the operand names has never been read (see `_Die`). What
            # changed in round 193 is only that the unknown says *whose* it is.
            # ⚠️ A `Machine` -- which runs a script on its own -- is unchanged
            # by that: `OP_BR` over a die still raises, because nothing there is
            # watching a screen that a coin would have to agree with. Only
            # `Follower`, which is in step with a client stopped on the branch,
            # may settle one.
            self.registers[_arith_registers(args)[0]] = DIE
            return i + 1

        if op == OP_SYNC_VARIABLE:
            # ⭐⭐⭐ It sends, it does not receive -- and that is the whole
            # reason this instruction exists. The client's slots for OP_STR and
            # for the whole arithmetic family are stubs that push the cursor and
            # log (round 169), so a register file only ever exists on *this*
            # side; SYNC_VARIABLE is where the script hands the client the few
            # registers its next line of dialogue is about to interpolate.
            # Measured end to end in amm_e001: ip=3791..3819 write S0/S1 to a
            # class name and a floor, ip=3845/3865 synchronise them, and
            # ip=3849/3869 say 「確か$s00組」/「$s01階ね」. So passing it through
            # with the values this end computed is not a guess about what the
            # other player wrote -- there is nothing to receive.
            #
            # ⚠️ Which registers, though, is not in the operands: it is a run of
            # entries in the .ssb's auxiliary table, carried by the export as
            # `Script.sync` since round 190. An export without it cannot say,
            # and says so rather than passing silently -- the client is stopped
            # on this instruction waiting to be told, and answering with the
            # wrong registers is worse than not answering.
            if ip not in self.script.sync:
                raise UnsupportedOp(
                    f"{self.script.name}: SYNC_VARIABLE at ip={ip} -- its "
                    f"register list lives in the .ssb's auxiliary table, which "
                    f"this export does not carry (re-run the export)"
                )
            return i + 1

        if op in KEYWORD_OPS:
            # ⭐⭐⭐ The one data family whose operands are *not* the shifted
            # register block the rest of 0x81xx uses, and the corpus says so:
            # across all 778 scripts `PC_KEYWORD_REFER` is always `80 c3` and
            # `PC_KEYWORD_UPDATE` is `80 80` or `81 80` -- a fixed second byte
            # and a first byte that runs 0x80, 0x81. `un081` grants the same
            # slot twice in a row, once with each, which is what names them:
            # **which player**, not which register. (2.150)
            #
            # ⭐⭐ And the slot is `keywordId << 5`: all 58 distinct slots in
            # the corpus are multiples of 32 and every `slot >> 5` is an id
            # `keyword.bin` actually has -- 58 of 58, against a file that holds
            # 261 of the 792 ids in range, so a wrong reading would have missed.
            #
            # ⚠️ REFER is a no-op here rather than a read, and that is a
            # statement about the corpus, not a shortcut: its 24 occurrences are
            # all in the two tutorials, each one immediately before an UPDATE of
            # the same slot, and not one of them is ever read back.
            if op == OP_KEYWORD_UPDATE:
                self.result.keywords.append(
                    (args[0] & 0x7F,
                     int.from_bytes(args[2:4], "little") >> 5))
            return i + 1

        if op in DATA_READ:
            reg = _refer_register(args)
            if reg is not None:
                slot = int.from_bytes(args[2:4], "little")
                self.registers[reg] = self._cell(DATA_READ[op], slot)
            return i + 1

        if op in DATA_WRITE:
            reg = _refer_register(args)
            if reg is not None:
                slot = int.from_bytes(args[2:4], "little")
                key = (DATA_WRITE[op], slot)
                value = self._get(reg)
                self.cells[key] = value
                # ⚠️ A write of an unknown value is recorded apart from the
                # rest, never among them: `Result.writes` is what a caller
                # persists, and "the script wrote something here and this end
                # could not say what" must not reach a save file as a number.
                if _unknown(value):
                    self.result.unknown_writes.add(key)
                    self.result.writes.pop(key, None)
                else:
                    self.result.writes[key] = value
                    self.result.unknown_writes.discard(key)
            return i + 1

        if op == OP_CTX_REFER:
            reg = _refer_register(args)
            if reg is not None:
                self.registers[reg] = self._cell("CTX", _ctx_address(args))
            return i + 1

        if op == OP_CTX_UPDATE:
            reg = _refer_register(args)
            if reg is not None:
                self.cells[("CTX", _ctx_address(args))] = self._get(reg)
            return i + 1

        if op == OP_EMIT:
            self.result.menus.append(int.from_bytes(args[0:2], "little"))
            return i + 1

        if op == OP_EVENT_CALL:
            field = int.from_bytes(args[0:2], "little")
            if field != EMIT_END:
                # (id << 5) | categoryId -- five bits for the category because
                # categories run to 20 and four bits do not hold that.
                self.result.events.append((field & 0x1F, field >> 5))
            return i + 1

        if op == OP_JP:
            return self.script.index.get(_jump_target(args))

        if op == OP_BR:
            condition = self._get(_register(int.from_bytes(args[0:2], "little")))
            if _unknown(condition):
                raise UnknownCell(
                    f"{self.script.name}: OP_BR at ip={ip} tests a value this "
                    f"machine could not produce"
                )
            if condition:
                return self.script.index.get(_jump_target(args))
            return i + 1

        if op == OP_BA:
            # 役柄 -- which part in the scene this client is playing -- is a
            # byte the client reads out of itself (slot 0x735d27) and never
            # puts on the wire. A machine running a script on its own cannot
            # take this branch and will not invent a part to play. `Follower`
            # can take it, and not by guessing either: see there.
            raise UnsupportedOp(
                f"{self.script.name}: OP_BA at ip={ip} needs a 役柄 ID this end "
                f"was never told"
            )

        if op == OP_BA_END:
            # ⛔️ Not a branch, despite the family it prints with. Its slot
            # (0x73633d) tests the same 役柄 condition as OP_BA and then adds 4
            # to the cursor either way; all the condition changes is which log
            # line it writes and whether it reports.
            return i + 1

        if op == OP_INPUT_SELECT:
            # A question for a player. A machine running by itself has nobody
            # to ask, so it stops rather than picking a line.
            raise UnsupportedOp(
                f"{self.script.name}: INPUT_SELECT at ip={ip} is a question for "
                f"a player"
            )

        if op == OP_JS:
            number = int.from_bytes(args[0:2], "little") & 0x3FF
            if not 1 <= number <= len(self.script.labels):
                raise UnsupportedOp(f"{self.script.name}: OP_JS label {number}")
            self.stack.append(i + 1)
            return self.script.index.get(self.script.labels[number - 1])

        if op == OP_RTN:
            return self.stack.pop() if self.stack else None

        if op == OP_END:
            return None

        return self._uninstructed(i, ip, op)

    # ── the opcodes this machine does not implement ───────────────────────
    def _uninstructed(self, i: int, ip: int, op: int) -> int:
        """What to do about an instruction this module was never taught.

        ⚠️ A rule, deliberately, and not a list of opcodes that are safe to
        step over. A list would have to grow by hand every time a scenario used
        a command no earlier one had, and the run it stopped would say nothing
        about why.

        The rule is *which side of the wire the script belongs to*, and the
        container says which:

        ``GSC``
            One of the original server's own 95 scripts. There is no client
            half. Every command in one of those was this end's work, so a
            command this module has not been taught is a hole in this module --
            and the answer it would otherwise produce would be wrong in a way
            nothing downstream could detect. It raises.

        ``SSC``
            One of the client's 683 scenarios. The client plays these: it loads
            the backgrounds, moves the waist-ups, plays the sound, prints the
            line, fades the screen. What it does *not* do is the arithmetic --
            round 175 measured that the whole ``OP_STR``/arithmetic and
            ``*_DATA_REFER`` family decodes to a log-and-advance stub, which is
            why the register file was ever this end's business at all. So a
            command this module has not been taught is, by that same reading,
            one the client is doing itself, and the whole of this end's part in
            it is to move the cursor past it.

        ⚠️ "By that same reading" is where this could be wrong, so it is not
        silent: every skip is counted by opcode in ``Result.passed``. The first
        time a scenario command turns out to touch a register or a data cell,
        its number is already in the log next to how often it went by.
        """
        if self.script.container != "SSC":
            raise UnsupportedOp(f"{self.script.name}: op {op:#06x} at ip={ip}")
        self.result.passed[op] += 1
        return i + 1

    def run(self) -> Result:
        i: int | None = 0
        for _ in range(self.STEP_BUDGET):
            if i is None or not 0 <= i < len(self.script.code):
                return self.result
            i = self._step(i)
        raise Runaway(f"{self.script.name}: {self.STEP_BUDGET} steps and still going")


# The two instructions the client stops dead on and waits for this end.
# ⭐ SYNC_VARIABLE joins these two as of round 190. It is reported through the
# ordinary 0x721b and then the client sits on it -- measured twice in one run of
# amm_e001, once on a black screen and once on a fully drawn page of dialogue
# that would not turn (round 189). So a walk that steps over an unreported one
# has gone somewhere the client did not.
# ⭐ RESULT_MULTI_PLAYER_EVENT joins them as of round 234, on the same evidence
# the other three are here on: the client sends a 0x721c Begin for it and sits
# there until the server answers (measured round 233, un081 ip=23606). So a walk
# that steps over an unreported one has gone somewhere the client did not.
# ⭐ The three INPUT_STRING ops join them as of round 245, on the same evidence:
# the client sends a 0x721c Begin for one and waits (see OP_INPUT_STRING).
STOPS = ({OP_END, OP_INPUT_SELECT, OP_SYNC_VARIABLE, OP_RESULT_MULTI_PLAYER_EVENT}
         | set(INPUT_STRING_OPS))


class Follower(Machine):
    """The same machine, walking in step with a client that plays the script.

    The client runs a scenario out of its own copy of the .ssb and calls home
    only when it reaches something it may not decide (round 37): it reports
    ``OP_JP`` / ``OP_BR`` / ``OP_RTN`` / ``OP_JS`` as it passes them, reports
    ``OP_BA`` and ``OP_BA_END`` only when their 役柄 test hits, and stops on
    ``OP_BR`` and on the choice box until it is answered. Between two reports it
    has executed a run of straight-line commands, and this class executes that
    same run -- which is how a register file appears on this end without the
    client ever sending one.

    ⭐ **The walk is not new here and was not fitted here.** A replay drove
    exactly it over 48 real traces out of this server's own logs, 2051
    reported instructions, and 36 of the 48 matched the client's own ip
    sequence from the first instruction to the last. (The other 12 are log
    fragments that do not begin at the top of a script, not disagreements.)

    ⭐⭐ **It needs no 役柄 ID, and not by assuming one.** ``OP_BA``'s
    fall-through sends nothing at all, so silence and a report are the two
    answers to that test, and the client supplies whichever one applies. Worth
    saying, because the obvious alternative -- assume the player is part 0 --
    is right for a solo cutscene and silently wrong for a multi-player event.

    ⚠️⚠️ **It follows, it does not steer.** Every branch goes where the server
    actually sent the client, never where this machine's own arithmetic would
    have gone; ``branch()`` reports the difference and changes nothing. That is
    what makes this a shadow rather than a second opinion nobody asked for.

    ⚠️ A cell nobody supplied reads as ``TOP`` here and is counted in
    ``missing``, which is the opposite of ``Machine``'s rule. Deliberate:
    ``Machine`` answers one question and a hole invalidates the answer, while
    this one walks a whole conversation and a hole invalidates one branch of
    it. Finding out which holes there are is most of what this mode is for.
    """

    def __init__(self, script: Script, cells: dict | None = None,
                 registers: dict | None = None, actor: int = 0) -> None:
        super().__init__(script, cells or {})
        #: ⭐ Which 役柄 of the play this follower's player is. Only `chose`
        #: uses it, and only to put the answer in the right `E<n>` -- see
        #: `OP_INPUT_SELECT`. ⚠️ 0 for a solo script, which is not a fallback:
        #: the single player of a 日常会話 *is* 役柄 0, and all 31 choice boxes
        #: of the exported solo scenarios carry the mask that says so.
        self.actor = actor
        # ⭐⭐⭐ **Whose register file this is.** Passed in and kept by reference
        # -- not copied -- so that every member of a ドラマパーティ computes over
        # one file while each keeps its own cursor, stack and data cells. That
        # split is read off the scripts, not chosen here; the argument is in
        # `mps_session._drama_light`.
        # ⚠️ None is a file of this follower's own, which is what a solo script
        # wants and what every caller before round 233 got.
        if registers is not None:
            self.registers = registers
        #: ⭐ True when this follower is one of a ドラマパーティ's, computing over
        #: the party's own register file rather than a private one. Read at the
        #: one place a branch is answered (`mps_session._script_incoming`);
        #: the argument for why that changes anything is there.
        self.in_party = registers is not None
        self.pos = 0
        # Why this end lost its place, once it has. A shadow that no longer
        # knows where it is must stop talking rather than start guessing, so
        # every entry point below returns early once this is set.
        self.lost: str | None = None
        self.missing: Counter = Counter()      # cell name -> times asked for
        self.selects: list[tuple[int, int, int, int]] = []
        self.reported = 0
        # ⭐ Which season the four-armed switch should see, or None to let the
        # script's own constant stand. ⚠️ None is not "the original": it is what
        # a server that only evaluates the bytecode would do, and the original
        # did more than that (see `SEASONS`). Overriding at the write is the
        # only place anything outside the script can reach that register -- the
        # write sits after the script starts and before the switch, so a value
        # pushed down the wire ahead of it would be overwritten.
        # ⚠️ *That* this end overrides at all, and where the year is cut into
        # four, are inventions (the smallest-invention rule); that the switch
        # moves with the calendar is not. See `Script.season_register`.
        self.season: int | None = None
        # ⭐⭐⭐ **This cursor's own copy of every register it wrote** (round
        # 254). The register file is the party's, one for all its members, and
        # that is right for the variables the script declares -- `un081`'s `B1`
        # is decremented inside `OP_BA 01` and read by the other 役柄, and
        # `un066`'s `B5`/`B6` are 「where did each of you say to go」. It is
        # wrong for the compiler's temporaries, which belong to whoever
        # computed them, and the corpus says an `OP_BR` condition is *always*
        # one of those: over all 778 exported scenarios, all 16313 of them read
        # `F99`/`F98`/`F97` or `F7`/`F6`/`F5` -- none of which the scenario
        # declares -- or `P31`, which is written 5516 times, every one of them
        # by the comparison in front of a branch, and read 5516 times, every
        # one of them by that branch. ⛔️ Not one reads a declared register.
        # See `branch`, which is the only reader.
        self.own: dict[tuple[int, int], object] = {}

    # -- the two rules that differ from a machine running on its own -------
    def _cell(self, family: str, address) -> int:
        if (family, address) not in self.cells:
            self.missing[cell_name(family, address)] += 1
            return TOP
        return self.cells[(family, address)]

    def _step(self, i: int) -> int | None:
        if self.script.code[i][1] == OP_BA:
            # Stepped over rather than reported => its 役柄 test did not hit
            # => it fell through. `flowed` has the other half.
            return i + 1
        if self.script.code[i][1] == OP_DECL_VARIABLE and self._prologue_done(i):
            # ⭐⭐⭐ **The prologue's zero-fill is the party's, not a cursor's**,
            # and a party has one register file with a cursor per member. Each
            # member's client plays the scenario from the top, so without this
            # the second cursor to start walking re-runs the zero-fill and
            # wipes whatever the first one has already put in the declared
            # registers.
            #
            # ⚠️ That is not hypothetical and not a tie-break between two
            # readings: `un010` sets `B1`/`B2`/`B3` inside an `OP_BA 01`
            # bracket -- 役柄 0 only, the same "let one writer do it" idiom
            # `un081` uses for `B1` -- and *before* the first `PLAYER_SYNC`, so
            # nothing orders it against the other member's first report. `B3`
            # is the チョコ回収 round counter: set to 4, decremented once per
            # round inside `OP_BA 01`, and the loop at ip=26984..27407 leaves
            # only when it reaches 0 or the 3 chocolates are in. Zeroed behind
            # 役柄 0's back it counts 0, -1, -2, ... and the loop never ends.
            # Played out over one register file, 6 of 12 random runs hang in
            # that loop with the zero-fill left per-cursor; with it done once
            # all 6 of them count 4, 3, 2, 1, 0 and reach `OP_END`.
            #
            # ⚠️ It is not the only way that scenario hangs, and this does not
            # claim to be: 3 of those 12 still end with one cursor waiting at a
            # barrier while the other circles a loop of its own -- two members
            # a barrier apart, which is `_keep_own`'s subject and not this one.
            #
            # ⚠️ Scenarios that write their shared registers on the main line
            # are immune either way -- the second cursor wipes and rewrites
            # them as it walks the same instructions -- which is why this stayed
            # invisible: `un081` and `un066` play identically with and without
            # it (12 random runs each, same endings, same counts).
            return i + 1
        nxt = super()._step(i)
        if self.season is not None:
            self._reseason(i)
        self._keep_own(i)
        return nxt

    def _prologue_done(self, i: int) -> bool:
        """True when another cursor of this party already ran this zero-fill.

        ⭐ Read off the file itself rather than kept as a flag: the zero-fill
        writes `(category, 0 .. count-1)`, so `(category, 0)` being present is
        exactly "somebody has been here". Nothing else can have written it
        first -- the prologue is the run of `OP_DECL_VARIABLE` at the top of
        the script, ahead of every other instruction.

        ⭐ Both halves of that were checked over the corpus rather than
        assumed: of all 778 exported scenarios, none declares the same
        category twice -- so a second `OP_DECL_VARIABLE` for a category can
        only be another cursor's -- and none carries an `OP_DECL_VARIABLE`
        anywhere but that opening run.

        ⚠️ A solo follower has a register file of its own and walks the
        prologue exactly once, so this never fires for one; `in_party` says
        which case this is.
        """
        if not self.in_party:
            return False
        field = int.from_bytes(self.script.code[i][2][0:2], "little")
        return (field & DECL_CAT_MASK, 0) in self.registers

    def _written_register(self, i: int) -> "tuple[int, int] | None":
        """The register instruction `i` writes, or None if it writes none.

        ⛔️ `OP_DECL_VARIABLE` is deliberately not here: the prologue's
        zero-fill is the party's, not a cursor's.
        """
        op, args = self.script.code[i][1], self.script.code[i][2]
        if op == OP_STR and len(args) >= 2:
            return _register(int.from_bytes(args[0:2], "little"))
        if op in (OP_NOT, OP_RAND) or op in ARITHMETIC:
            return _arith_registers(args)[0] if len(args) >= 4 else None
        return None

    def _keep_own(self, i: int) -> None:
        """Remember what this cursor just put in a register.

        ⭐⭐⭐ Round 254: the shadow used to read an `OP_BR`'s condition at
        *answer* time, and the comparison that produced it happened at *report*
        time -- a network round trip earlier, with the other member's cursor
        free to run in between. `un066` ip=3306 is the case: both 役柄 compute
        `F99 = (B5 == B6)` just after the rendezvous at ip=3300, 役柄 1 is
        answered first, walks on into ip=3823 `OP_STR F99 = 1` -- an unrelated
        rung reusing the same scratch flag -- and 役柄 0's branch then reads
        that 1 and leaves the 「息を合わせる」 loop while its partner stays in it.
        ⇒ once they are a barrier apart the `any` release rule keeps them
        there: measured off one fixture, 56 of 59 rendezvous released with the
        two of them on different instructions, and only one of the two roles
        reached `OP_END`. With this the play takes the road it was written
        for: 52 rendezvous, every one released with both on the same
        instruction, and both roles finish.
        """
        register = self._written_register(i)
        if register is not None and register in self.registers:
            self.own[register] = self.registers[register]

    def _reseason(self, i: int) -> None:
        """Overwrite the season constant this instruction just wrote, if it did.

        ⚠️ Guarded three ways, because `B0` is a general-purpose register that
        most of the 683 scenarios use for something else: the script has to have
        a four-armed scenery switch at all (`Script.season_register`), the
        instruction has to write *that* register, and it has to be writing an
        immediate rather than copying another register.
        """
        register = self.script.season_register
        if register is None or self.script.code[i][1] != OP_STR:
            return
        field = int.from_bytes(self.script.code[i][2][0:2], "little")
        if _register(field) != register or (field >> 10) & 7 != CAT_IMMEDIATE:
            return
        self.registers[register] = self.season

    # -- being told where the client is -----------------------------------
    def _lose(self, why: str) -> str:
        self.lost = why
        return why

    def at(self, ip: int, op: int) -> str | None:
        """Walk to the instruction the client says it has reached.

        None when this end arrived there too; otherwise the reason it could
        not, which is also the end of this follower.
        """
        if self.lost:
            return self.lost
        self.reported += 1
        target = self.script.index.get(ip)
        if target is None:
            return self._lose(f"ip={ip} is not an instruction start")
        while self.pos != target:
            here_ip, here_op, _ = self.script.code[self.pos]
            if ((here_op in ALWAYS_REPORTED or here_op in STOPS)
                    and not self._someone_elses_box(here_ip, here_op)):
                return self._lose(
                    f"walked onto {here_op:#06x} at ip={here_ip} on the way to "
                    f"ip={ip}, and the client never reported it"
                )
            try:
                nxt = self._step(self.pos)
            except (UnsupportedOp, UnknownCell, Runaway) as exc:
                return self._lose(str(exc))
            if nxt is None or not 0 <= nxt < len(self.script.code):
                return self._lose(f"ran off the end on the way to ip={ip}")
            self.pos = nxt
        here_op = self.script.code[self.pos][1]
        if here_op != op:
            return self._lose(f"ip={ip}: the client says {op:#06x}, "
                              f"the export says {here_op:#06x}")
        return None

    def _someone_elses_box(self, ip: int, op: int) -> bool:
        """Is this a free-text box addressed to one of the other 役柄?

        ⭐⭐⭐ A scene written for two puts boxes in the stream for both of
        them, and only the player it names ever sees one: the client compares
        the 役柄 in the instruction against its own and draws nothing when they
        differ (round 248 read that comparison out of the decoder at 0x73537a).
        A client that draws nothing reports nothing, so for everybody else the
        box is a straight-line command like any other and this walk has to step
        over it -- exactly the way it already steps over an `OP_BA` whose mask
        misses.

        ⚠️⚠️ Round 249 measured what happens otherwise, on the screen. Playing
        `un111` with the real client as 役柄 0, the shadow reached the box at
        ip=10234 -- 役柄 1's -- treated it as a stop and gave up, so the
        `SYNC_VARIABLE` twenty instructions later went out empty and the line
        「俺のお気に入りの場所は「」です。」 was drawn with a hole where the
        player's own answer belonged.

        ⛔️ False when the export cannot say whose box it is (`actor` is None,
        which every export made before round 249 is). Standing down there is
        the older, louder failure and it stays: guessing 0 would silently step
        over 役柄 0's own boxes on a stale export.
        """
        if op not in INPUT_STRING_OPS:
            return False
        box = self.script.inputs.get(ip)
        return box is not None and box["actor"] is not None \
            and box["actor"] != self.actor

    def flowed(self) -> str | None:
        """Follow the control-flow instruction the client resolved by itself."""
        if self.lost:
            return self.lost
        ip, op, args = self.script.code[self.pos]
        if op == OP_BA:
            # Reported at all means it hit, so this is the branch half. The
            # client has just said what its 役柄 is, in the only way this end
            # ever gets to hear it.
            nxt = self.script.index.get(_jump_target(args))
        else:
            try:
                nxt = self._step(self.pos)
            except (UnsupportedOp, UnknownCell, Runaway) as exc:
                return self._lose(str(exc))
        if nxt is None or not 0 <= nxt < len(self.script.code):
            return self._lose(f"{op:#06x} at ip={ip} led nowhere this end knows")
        self.pos = nxt
        return None

    def resumed(self, ip: int) -> str | None:
        """Where the server has just sent the client. The shadow goes there."""
        if self.lost:
            return self.lost
        found = self.script.index.get(ip)
        if found is None:
            return self._lose(f"the server answered ip={ip}, which is not an "
                              f"instruction start")
        self.pos = found
        return None

    # -- the two things worth reporting -----------------------------------
    def sync_values(self) -> list[tuple[int, int, object]]:
        """`[(category, number, value)]` for the SYNC_VARIABLE the client is on.

        ⭐⭐ The one place this shadow *speaks*, and the reason it is allowed to:
        every other stop asks the server to decide something, while this one
        asks it to report what it already computed. The client cannot compute
        it -- its OP_STR and arithmetic slots are logging stubs -- so a register
        this end does not know is a register nobody knows.

        A value of ``None`` is exactly that case: TOP, or a string reference the
        export cannot resolve. The caller sends it as an empty value rather than
        dropping the entry, because the entry count is what releases the client
        and a short list would leave a register holding whatever was in it.
        """
        if self.lost:
            return []
        ip, op, _ = self.script.code[self.pos]
        if op != OP_SYNC_VARIABLE:
            return []
        out: list[tuple[int, int, object]] = []
        for category, number in self.script.sync.get(ip, ()):
            try:
                value = self._get((category, number))
            except UnsupportedOp:
                value = TOP
            if category in STRING_CATEGORIES:
                # ⭐ A line the player typed is already the text; anything else
                # is a pool reference this end has to read back. Sending the
                # typed line on is the point of the synchronisation that
                # follows a box in `un183`: the other member of the party never
                # saw it typed and its client has nothing in that register.
                if _unknown(value):
                    value = None
                elif not isinstance(value, str):
                    value = self.script.strings.get(value)
            elif _unknown(value):
                value = None
            out.append((category, number, value))
        return out

    def event_result(self) -> dict | None:
        """What the `RESULT_MULTI_PLAYER_EVENT` the client is stopped on says.

        ⭐⭐⭐ The second place this shadow *speaks* rather than follows, and for
        the same reason `sync_values` does: the operand names a register, and
        the register exists only on this end. ⛔️ Nothing is decided here --
        the caller records the number and releases the client either way.

        ``None`` when this end is not standing on one. Otherwise::

            {"point": 評価ポイント名 or None, "text": 評価文 or None,
             "register": (category, number), "bound": bool,
             "value": int or None, "keywords": int, "items": int}

        ``bound`` is False for the compiler temporary (B99 and its neighbours):
        the ending's score is not held in a variable the scenario declared.

        ⭐⭐⭐ ``value`` is filled in anyway when the temporary was written by a
        literal on the way in -- see `_literal_score`, which is what 227 of the
        corpus's 296 endings do. ⚠️ The earlier reading here was that an unbound
        operand meant "no score", and it cost the record on three endings out of
        four: an ending whose score is a constant has no reason to spend a
        declared variable on it, so the compiler leaves the constant in scratch
        and the operand names the scratch. ⛔️ It is still None for a temporary
        nobody wrote a literal into -- that number really would be whatever the
        last expression left behind.

        ⚠️ ``point``/``text`` are None when the export carries no string for the
        reference. That is a scenario exported before round 234 (the
        exporter collects them as of then), ⛔️ not a scenario without a result.
        """
        if self.lost:
            return None
        _, op, args = self.script.code[self.pos]
        if op != OP_RESULT_MULTI_PLAYER_EVENT:
            return None
        register = _register(int.from_bytes(args[0:2], "little"))
        category, number = register
        bound = number < self.script.declared.get(category, 0)
        value = None
        if bound:
            try:
                held = self._get(register)
            except UnsupportedOp:
                held = TOP
            value = None if _unknown(held) or isinstance(held, str) else held
        else:
            value = self._literal_score(register)
        counts = int.from_bytes(args[10:14], "little")
        return {
            "point": self.script.strings.get(int.from_bytes(args[6:10], "little")),
            "text": self.script.strings.get(int.from_bytes(args[2:6], "little")),
            "register": register,
            "bound": bound,
            "value": value,
            "keywords": counts & 0xF,
            "items": (counts >> 4) & 0xF,
        }

    def _literal_score(self, register: tuple[int, int]) -> int | None:
        """The constant an ending hands `RESULT_MULTI_PLAYER_EVENT`, if it does.

        ⭐⭐⭐ The shape, which is why this is a reading and not a guess::

            OP_STR        <r> = #k        k is 0..5, the five-star scale
            SYNC_VARIABLE <r>             the same register, to the client
            RESULT_MULTI_PLAYER_EVENT <r>

        Measured over every exported scenario: **all 296** of the corpus's
        `0x9200` are preceded by a `SYNC_VARIABLE` on the very register the
        result names, and of the 227 whose register is a temporary, **227**
        have that `OP_STR <r> = #k` two instructions back, with no exceptions
        and no value outside 0..5. ⇒ The scratch register is where a
        constant score lives, not where a stale one was left.

        ⚠️ The whole shape is required, not just the write: a temporary this
        scenario merely happened to leave a number in is exactly the case this
        must keep saying None about, and the `SYNC_VARIABLE` in between is the
        scenario's own statement that this number is the one it means.

        ⚠️ It reads the instruction stream rather than the register file on
        purpose. `self._get(register)` would answer for *any* temporary, which
        is the failure this is guarding against.
        """
        i = self.pos
        if i < 2:
            return None
        _, sync_op, sync_args = self.script.code[i - 1]
        if sync_op != OP_SYNC_VARIABLE:
            return None
        _, str_op, str_args = self.script.code[i - 2]
        if str_op != OP_STR or len(str_args) < 6:
            return None
        field = int.from_bytes(str_args[0:2], "little")
        if _register(field) != register or (field >> 10) & 7 != CAT_IMMEDIATE:
            return None
        return int.from_bytes(str_args[2:6], "little")

    def branch(self) -> tuple:
        """`(condition, where it would go)` for the OP_BR the client is on.

        The condition is a number, or ``TOP`` when this end could not work it
        out. ⚠️ Reports only. `script.Runner.resolve_branch` still answers the
        client, byte for byte what it answered before this class existed.

        ⭐⭐⭐ **The condition is this cursor's own** (round 254, see `own`):
        the comparison in front of a branch runs a round trip before the branch
        is answered, and in a party the other member's cursor runs in that gap
        over rungs that reuse the same scratch flag. Falling back to the shared
        file is not a special case -- it is what a cursor that has not written
        the register itself has always read, which is every solo script and
        every branch whose rung this end could not walk.
        """
        if self.lost or self.script.code[self.pos][1] != OP_BR:
            return None, None
        args = self.script.code[self.pos][2]
        register = _register(int.from_bytes(args[0:2], "little"))
        if register in self.own:
            return self.own[register], _jump_target(args)
        try:
            condition = self._get(register)
        except UnsupportedOp as exc:
            self._lose(str(exc))
            return None, None
        return condition, _jump_target(args)

    def stolen_condition(self) -> "tuple[object, object] | None":
        """`(mine, the file's)` when somebody else overwrote this branch's flag.

        ⭐ The detector for what `own` fixes, kept separate from the fix so the
        disease stays countable: a party where this never fires is a party
        whose members never trod on each other's scratch registers.
        """
        if self.lost or self.script.code[self.pos][1] != OP_BR:
            return None
        register = _register(int.from_bytes(
            self.script.code[self.pos][2][0:2], "little"))
        if register not in self.own:
            return None
        theirs = self.registers.get(register)
        mine = self.own[register]
        return None if theirs == mine else (mine, theirs)

    #: How far back `branch_clicks` looks for the instruction that wrote the
    #: condition. The ladder idiom puts it one or two instructions in front of
    #: the `OP_BR`, and a short window is the point: this is a reading of that
    #: idiom, ⛔️ not a general dataflow analysis.
    CONDITION_LOOKBACK = 6

    def branch_clicks(self) -> set[int]:
        """Whose 選択肢 answer the `OP_BR` the client is on reads, by 役柄.

        ⭐⭐⭐ Scripts spell a selection out as `OP_STR B = #k; OP_EQ P = (E<n>
        == B); OP_BR P`, one rung per option, and **`n` says whose click the
        rung is about** -- the same `(CAT_SELECT, 役柄)` register `chose` writes.
        In a two-role scenario a rung is very often about the *other* member:
        `un111` walks both roles down the ladder at ip=1358, and every rung of
        it reads `E0`. Round 250 counted it over the 22 ドラマイベント: all 22
        compare against both `E0` and `E1`, 991 sites and 1160 sites.

        ⭐ Empty for every branch that is not one of these, which is what makes
        it usable as a fence: the caller only has to wait when the answer it is
        about to read belongs to somebody who has not given it yet.
        """
        if self.lost or self.script.code[self.pos][1] != OP_BR:
            return set()
        args = self.script.code[self.pos][2]
        condition = _register(int.from_bytes(args[0:2], "little"))
        stop = max(-1, self.pos - self.CONDITION_LOOKBACK)
        for j in range(self.pos - 1, stop, -1):
            _, op, operands = self.script.code[j]
            if op not in ARITHMETIC or len(operands) < 4:
                continue
            result, left, right = _arith_registers(operands)
            if result != condition:
                continue
            return {number for category, number in (left, right)
                    if category == CAT_SELECT}
        return set()

    #: What a ladder rung is made of: the constant into the compare register
    #: and the comparison itself. ⭐ Nothing in here writes a save cell or
    #: sends anything, which is what makes running one a second time safe.
    RUNG_OPS = frozenset({OP_STR}) | frozenset(ARITHMETIC)

    def recompute_condition(self) -> str | None:
        """Run the rung in front of this `OP_BR` again, on today's registers.

        ⭐⭐⭐ **Holding the branch is one instruction too late** (round 252).
        A rung is `OP_STR B99 = #k; OP_EQ P31 = (E<n> == B99); OP_BR P31`, and
        the comparison is *already done* by the time the client reports the
        `OP_BR` -- `_shadow_at` has walked the shadow over it. So a member that
        arrives before the click it reads has been given bakes the stale answer
        into `P31`, and `mps_session._click_fence` holding the branch until the
        click arrives does not undo that: `branch()` only re-reads `P31`.

        ⭐⭐ `un010` ip=703/707/710 caught it: 役柄 1 walked past 役柄 0's box at
        ip=687, compared `E0` against 0 while `E0` still held the previous
        round's answer, was held at the branch, and on release read back its
        own stale comparison -- while 役柄 0, running the same three
        instructions after clicking, got the other road. Two members, one
        shared register, the same rung, two verdicts.

        ⚠️ Bounded by the same `CONDITION_LOOKBACK` window and the same idiom
        `branch_clicks` reads, and it re-runs **only** `OP_STR`/arithmetic, so
        it cannot re-fire anything that reaches the save or the wire. ⛔️ It is
        not a general re-execution: a rung written some other way is left
        exactly as it was.
        """
        if self.lost or self.script.code[self.pos][1] != OP_BR:
            return None
        stop = max(0, self.pos - self.CONDITION_LOOKBACK)
        start = self.pos
        while start > stop and self.script.code[start - 1][1] in self.RUNG_OPS:
            start -= 1
        if start == self.pos:
            return None
        here = self.pos
        try:
            for j in range(start, here):
                self._step(j)
        except (UnsupportedOp, UnknownCell, Runaway) as exc:
            self.pos = here
            return self._lose(str(exc))
        self.pos = here
        return None

    def decided_road(self) -> bool:
        """May this end answer the `OP_BR` the client is stopped on?

        The walk itself is `_decided_road`; this half only refuses once this end
        has lost its place -- a shadow that does not know where it is must not
        be steering anything.
        """
        if self.lost:
            return False
        return _decided_road(self.script, self.pos) is not None

    def select(self) -> tuple[int, int, int]:
        """The mask for the choice box the client is stopped on, right now.

        `(mask, unknown, options)`, one bit per option in each of the first two;
        `unknown` marks the options this end could not work out.

        ⛔️ Computed at the moment the box goes up and never stored. The flags a
        script writes in front of a choice box are mostly `F<n> == 0` over
        registers the script itself sets as the conversation goes -- "has this
        answer been used yet" -- so *the mask of this select* is not a quantity
        that exists. A loop that redraws the same box gets a different answer
        the second time round, which is the whole reason this class walks along
        instead of a table having been built once.

        ⚠️⚠️ **Option `k` is not register number `k`.** Only the low five
        bits of a SELITEM number are the option number; the two bits above
        them pick one of two banks, and a script that writes a computed flag
        often writes it to the high bank -- 113 of the 1853 choice boxes in
        the export do, 314 options across 24 scenarios, and a box mixes the
        banks freely (`un007` ip=6803 writes options 0, 1, 2 to numbers 32, 1
        and 34). Reading `(CAT_SELITEM, k)` for those does not read the flag
        the script just wrote: it reads whatever the **previous** box left at
        that number, which is a stale value and not a hole, so it does not
        degrade into "offer the line" the way ⊤ does. `_selitem_numbers`
        pairs each option with the number its own flag went to.
        """
        if self.lost or self.script.code[self.pos][1] != OP_INPUT_SELECT:
            return 0, 0, 0
        ip, _, args = self.script.code[self.pos]
        # `+16` in the instruction is `(auxiliary word offset << 12) | count`,
        # the same packing SYNC_VARIABLE uses; the operands here begin at `+2`.
        options = int.from_bytes(args[14:18], "little") & 0x3F
        numbers = self._selitem_numbers(options)
        mask = unknown = 0
        for k in range(options):
            number = numbers.get(k)
            value = TOP if number is None else self.registers.get(
                (CAT_SELITEM, number), TOP)
            if _unknown(value):
                unknown |= 1 << k
            elif value:
                mask |= 1 << k
        self.selects.append((ip, mask, unknown, options))
        return mask, unknown, options

    def _selitem_numbers(self, options: int) -> dict[int, int]:
        """Option index -> the SELITEM register number this box's flag is in.

        The run of `OP_STR` writes immediately in front of an
        `OP_INPUT_SELECT` is that box's flags, one per option, and the low
        five bits of the number are the option number. Both halves of that are
        measured rather than assumed: over the whole export every choice box
        has exactly as many such writes in front of it as it declares options,
        and their low five bits are exactly a permutation of `0..n-1` -- no
        exceptions, no duplicates, no gaps, for counts from 2 to 21.

        ⭐ Walking backwards from the box is the same rule read from the same
        end, and it needs no state: a loop that comes round and rewrites the
        flags rewrites them in the same place, so the answer is right for the
        second pass over a box as well as the first.

        ⚠️ An option whose write this cannot find is left out, and `select`
        reads that as ⊤ -- "this end could not work out that line" is exactly
        what a missing flag is, and ⊤ is the half of the two that degrades
        into offering the line rather than hiding it.
        """
        numbers: dict[int, int] = {}
        for j in range(self.pos - 1, -1, -1):
            op, args = self.script.code[j][1], self.script.code[j][2]
            if op == OP_INPUT_SELECT:
                break
            if op != OP_STR or len(args) < 2:
                continue
            category, number = _register(
                int.from_bytes(args[0:2], "little"))
            if category != CAT_SELITEM:
                continue
            option = number & 0x1F
            if option < options:
                numbers.setdefault(option, number)
                if len(numbers) == options:
                    break
        return numbers

    def select_actors(self) -> int | None:
        """Which 役柄 the choice box the client is stopped on is addressed to.

        `OP_INPUT_SELECT`'s `+4`, bit n for 役柄 n -- the field read in round
        236 to settle where an answer lands. None when this end is not on a
        box, which is the caller's cue to leave the box alone.

        ⚠️ This is not `select`'s mask: that one is over the box's *options*
        and changes every time the box is redrawn, while this one is over the
        *players* and is a constant of the instruction.
        """
        if self.lost or self.script.code[self.pos][1] != OP_INPUT_SELECT:
            return None
        return int.from_bytes(self.script.code[self.pos][2][2:4], "little")

    def passed_box(self) -> str | None:
        """Step over a choice box without an answer: it was somebody else's.

        The other-役柄 counterpart of `chose`, and the same single step -- what
        it leaves out is the register write, because nobody clicked anything
        here. `_someone_elses_box` does this for a free-text box without ever
        being told, since a client that draws nothing reports nothing; a choice
        box is reported by everyone who walks onto it, so this end is told and
        steps on demand.
        """
        if self.lost:
            return self.lost
        if self.script.code[self.pos][1] != OP_INPUT_SELECT:
            return self._lose("asked to step over a box this end is not on")
        self.pos += 1
        return None

    def chose(self, option: int) -> str | None:
        """The player clicked a line: it lands in `E<this player's 役柄>`.

        ⚠️⚠️ Not E0. In a ドラマパーティ the register file is one per party
        (`__init__`), so putting both members' clicks in E0 would have the
        second one overwrite the first and leave E1 -- which is where every
        役柄-1 box's chain looks -- empty for the whole play. The reading of the
        box's own 役柄 mask that settles this is at `OP_INPUT_SELECT`.
        """
        if self.lost:
            return self.lost
        if self.script.code[self.pos][1] != OP_INPUT_SELECT:
            return self._lose("a choice came back but this end is not on a box")
        self.registers[(CAT_SELECT, self.actor)] = option
        self.pos += 1
        return None

    def typed(self, text: str) -> str | None:
        """A free-text box was answered: the line goes into its register.

        ⭐⭐⭐ **Verbatim, and that is the whole of it.** The box does not turn
        what was typed into a number -- see `OP_INPUT_STRING` for the reading
        that says so -- so there is nothing here to match, look up or score.
        The scenario does its own comparing afterwards, over the same register,
        and `Machine._as_text` is what lets a line that never was in the string
        pool be compared against a literal that was.

        ⚠️ Still stands down when this copy's export has no box at this ip: an
        export made before round 248 carries no destination, and a follower
        that walked on would leave the register holding the zero
        `DECL_VARIABLE` gave it and then answer a later `OP_BR` **confidently
        and wrongly**. That is worse than not answering, because the standing
        "no" is a road the caller already knows how to take.
        """
        if self.lost:
            return self.lost
        ip, op, _ = self.script.code[self.pos]
        if op not in INPUT_STRING_OPS:
            return self._lose("typed text came back but this end is not on a box")
        box = self.script.inputs.get(ip)
        if box is None:
            return self._lose(f"a text box was answered at ip={ip}, and this "
                              f"export does not say which register it fills")
        self.registers[box["register"]] = text
        self.pos += 1
        return None

    def describe(self) -> str:
        """One line for the log: what this shadow has and has not got."""
        if self.lost:
            return f"out of step: {self.lost}"
        where = (self.script.code[self.pos][0]
                 if self.pos < len(self.script.code) else "-")
        missing = ", ".join(f"{name}x{n}" for name, n in self.missing.most_common(8))
        return (f"{self.script.name} ip={where} · {self.reported} reports · "
                + (f"cells nobody supplied: {missing}" if missing
                   else "every cell it asked for was supplied"))


def follow(script_id: int, cells: dict | None = None,
           registers: dict | None = None, actor: int = 0) -> Follower | None:
    """A follower for the scenario the client just asked to play, or None.

    None means this machine has no export for that id, which is the ordinary
    case for every copy of this server but the one that made them -- the same
    way `mapgraph`'s graph and the branch table are optional.

    `registers` is a file to share with the other members of the same party and
    `actor` this player's 役柄 in it; see `Follower.__init__`.
    """
    script = by_script_id(script_id)
    return (Follower(script, cells, registers, actor)
            if script is not None else None)


def run(name: str, cells: dict[tuple[str, int], int]) -> Result | None:
    """Load and run one script. None when the script is not on this machine."""
    script = load(name)
    return Machine(script, cells).run() if script else None
