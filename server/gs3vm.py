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

The code they run over is written by `the script exporter` into
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
OP_RTN, OP_END, OP_JS = 0x9083, 0x9084, 0x9085
OP_BA_END = 0x90C0
OP_EVENT_CALL = 0x9180

# The choice box. The client stops dead on it and asks (0x721c); the answer is
# a bitmask, one bit per option, and the options' own on/off flags are the
# `SELITEM_DISP_FLAG` registers the script writes just before it. See
# `Follower.select`.
OP_INPUT_SELECT = 0x7000

# ⭐⭐ The three commands that make a 日常会話's setting: which background is
# loaded, which ambient loop plays over it, and the fade-in. They are the whole
# of what a 進行度 switch's taken road contains -- see `Follower.scenery_road`,
# which is the one place this end is allowed to answer a branch out of the
# script's own arithmetic.
OP_EVENT_BG_LOAD = 0x5100
OP_EVENT_BG_DISP_ON = 0x5101
OP_SD_ENV_PLAY = 0x6080

# Two register categories this end has to name, out of the eight the operand
# encoding allows. 5 is SELITEM_DISP_FLAG -- one register per option of the
# next choice box, and the low five bits of the number are the option number
# (round 175). 6 is SELECT, where the client's answer lands: every one of the
# 683 scenarios uses E0 for it, and the 38 that also use E1 are all multi-player
# events -- which is a hint about where E1 comes from and not a reading of it,
# so nothing here writes E1.
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
# `the opcode table` next door: F0 is a flag, B2 a 16-bit, S0 a short string.
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
        return ("writes: " + (" ".join(parts) if parts else "none")
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
            self.registers[result] = (
                TOP if a is TOP or b is TOP else ARITHMETIC[op](a, b)
            )
            return i + 1

        if op == OP_NOT:
            # The one arithmetic instruction with a single source, read out of
            # the same operand block as the rest.
            result, left, _ = _arith_registers(args)
            a = self._get(left)
            self.registers[result] = TOP if a is TOP else (1 if a == 0 else 0)
            return i + 1

        if op == OP_RAND:
            # ⭐ Taught rather than left to `_uninstructed`, and taught as
            # unknown. The die belongs to this end -- the client's slot for it
            # is a log stub like the rest of the arithmetic family -- but a
            # machine that is *watching* a conversation and rolls its own would
            # be reasoning about a different conversation from the one on the
            # screen. "I do not know what it rolled" is the true answer here,
            # and the day this end drives instead of watches is the day it
            # becomes the wrong one.
            self.registers[_arith_registers(args)[0]] = TOP
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
                    f"this export does not carry (re-run the script exporter)"
                )
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
                if value is TOP:
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
            if condition is TOP:
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
STOPS = {OP_END, OP_INPUT_SELECT, OP_SYNC_VARIABLE}


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

    ⭐ **The walk is not new here and was not fitted here.** ``the script evaluator
    replay`` drove exactly it over 48 real traces out of this server's own logs,
    2051 reported instructions, and 36 of the 48 matched the client's own ip
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

    def __init__(self, script: Script, cells: dict | None = None) -> None:
        super().__init__(script, cells or {})
        self.pos = 0
        # Why this end lost its place, once it has. A shadow that no longer
        # knows where it is must stop talking rather than start guessing, so
        # every entry point below returns early once this is set.
        self.lost: str | None = None
        self.missing: Counter = Counter()      # cell name -> times asked for
        self.selects: list[tuple[int, int, int, int]] = []
        self.reported = 0

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
        return super()._step(i)

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
            if here_op in ALWAYS_REPORTED or here_op in STOPS:
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
                value = None if value is TOP else self.script.strings.get(value)
            elif value is TOP:
                value = None
            out.append((category, number, value))
        return out

    def branch(self) -> tuple:
        """`(condition, where it would go)` for the OP_BR the client is on.

        The condition is a number, or ``TOP`` when this end could not work it
        out. ⚠️ Reports only. `script.Runner.resolve_branch` still answers the
        client, byte for byte what it answered before this class existed.
        """
        if self.lost or self.script.code[self.pos][1] != OP_BR:
            return None, None
        args = self.script.code[self.pos][2]
        try:
            condition = self._get(_register(int.from_bytes(args[0:2], "little")))
        except UnsupportedOp as exc:
            self._lose(str(exc))
            return None, None
        return condition, _jump_target(args)

    def scenery_road(self) -> bool:
        """Does taking the OP_BR the client is on change nothing but scenery?

        ⭐⭐ This is the whole of what lets one branch family be answered out of
        the script's own arithmetic while every other branch keeps the standing
        "no" (`script.Runner.resolve_branch`). The test is on the *road*, not on
        the condition: walk where the branch would go and ask whether anything
        on it can be seen by the save or by the story. Concretely it must load a
        background and it must not contain a data-cell write, an `EVENT_CALL`,
        a choice box, or an `OP_BA`.

        ⚠️ Measured over the whole corpus before it was wired to anything: of
        the 2756 `OP_BR` whose condition reads nothing but `PCEV[0x6020+i]`,
        2589 are this shape and **4** reach a `PCEV` write (`ink_c511`/`c513`/
        `c515`, `ksg_c511`). ⛔️ So "the condition is 進行度" is *not* a safe
        test on its own, which is why this one looks at the destination.

        ⚠️ `OP_JP` ends the walk rather than being followed: it is where the
        switch arm rejoins the scenario, and everything past that point is the
        conversation itself, which this branch did not decide.
        """
        if self.lost or self.script.code[self.pos][1] != OP_BR:
            return False
        start = self.script.index.get(_jump_target(self.script.code[self.pos][2]))
        if start is None:
            return False
        forbidden = set(DATA_WRITE) | {OP_EVENT_CALL, OP_INPUT_SELECT,
                                       OP_BA, OP_BR}
        loads_background = False
        pending, seen = [start], set()
        while pending:
            i = pending.pop()
            if i is None or i in seen or not 0 <= i < len(self.script.code):
                continue
            seen.add(i)
            op = self.script.code[i][1]
            if op in forbidden:
                return False
            if op == OP_EVENT_BG_LOAD:
                loads_background = True
            if op in (OP_RTN, OP_END, OP_JP):
                continue
            if op == OP_JS:
                number = int.from_bytes(self.script.code[i][2][0:2], "little") & 0x3FF
                if not 1 <= number <= len(self.script.labels):
                    return False
                pending.append(self.script.index.get(self.script.labels[number - 1]))
            pending.append(i + 1)
        return loads_background

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
        """
        if self.lost or self.script.code[self.pos][1] != OP_INPUT_SELECT:
            return 0, 0, 0
        ip, _, args = self.script.code[self.pos]
        # `+16` in the instruction is `(auxiliary word offset << 12) | count`,
        # the same packing SYNC_VARIABLE uses; the operands here begin at `+2`.
        options = int.from_bytes(args[14:18], "little") & 0x3F
        mask = unknown = 0
        for k in range(options):
            value = self.registers.get((CAT_SELITEM, k), TOP)
            if value is TOP:
                unknown |= 1 << k
            elif value:
                mask |= 1 << k
        self.selects.append((ip, mask, unknown, options))
        return mask, unknown, options

    def chose(self, option: int) -> str | None:
        """The player clicked a line: it lands in E0 and the box is over."""
        if self.lost:
            return self.lost
        if self.script.code[self.pos][1] != OP_INPUT_SELECT:
            return self._lose("a choice came back but this end is not on a box")
        self.registers[(CAT_SELECT, 0)] = option
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


def follow(script_id: int, cells: dict | None = None) -> Follower | None:
    """A follower for the scenario the client just asked to play, or None.

    None means this machine has no export for that id, which is the ordinary
    case for every copy of this server but the one that made them -- the same
    way `mapgraph`'s graph and the branch table are optional.
    """
    script = by_script_id(script_id)
    return Follower(script, cells) if script is not None else None


def run(name: str, cells: dict[tuple[str, int], int]) -> Result | None:
    """Load and run one script. None when the script is not on this machine."""
    script = load(name)
    return Machine(script, cells).run() if script else None
