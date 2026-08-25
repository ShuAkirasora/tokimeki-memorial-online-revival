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
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "runtime" / "scripts"


class UnsupportedOp(Exception):
    """An opcode this machine has not been taught. Never guessed at."""


class UnknownCell(Exception):
    """A data cell the caller did not supply. Never read as zero."""


class Runaway(Exception):
    """The step budget ran out -- a loop this machine cannot get out of."""


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
OP_JP, OP_BR, OP_BA = 0x9080, 0x9081, 0x9082
OP_RTN, OP_END, OP_JS = 0x9083, 0x9084, 0x9085
OP_EVENT_CALL = 0x9180

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

ARITHMETIC = {
    0x9002: lambda a, b: a + b,
    0x9003: lambda a, b: a - b,
    0x9004: lambda a, b: a * b,
    0x9007: lambda a, b: 1 if (a or b) else 0,
    0x9008: lambda a, b: 1 if (a and b) else 0,
    0x9009: lambda a, b: 1 if a == b else 0,
    0x900A: lambda a, b: 1 if a != b else 0,
    0x900B: lambda a, b: 1 if a > b else 0,
    0x900C: lambda a, b: 1 if a >= b else 0,
    0x900D: lambda a, b: 1 if a < b else 0,
    0x900E: lambda a, b: 1 if a <= b else 0,
}


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
        self.labels = list(doc["labels"])
        self.code = [(ip, op, bytes.fromhex(args)) for ip, op, args in doc["code"]]
        self.index = {ip: i for i, (ip, _, _) in enumerate(self.code)}


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


class Result:
    """What one run produced: menu keys offered, events called, cells written."""

    def __init__(self) -> None:
        self.menus: list[int] = []
        self.events: list[tuple[int, int]] = []
        self.writes: dict[tuple[str, int], int] = {}

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
            where = (f"{address[0]:#06x}@{address[1]:#04x}"
                     if isinstance(address, tuple) else f"{address:#06x}")
            raise UnknownCell(f"{self.script.name}: {family}[{where}]") from None

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
            self.registers[result] = ARITHMETIC[op](self._get(left), self._get(right))
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
                self.result.writes[key] = value
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
            if condition:
                return self.script.index.get(_jump_target(args))
            return i + 1

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

        raise UnsupportedOp(f"{self.script.name}: op {op:#06x} at ip={ip}")

    def run(self) -> Result:
        i: int | None = 0
        for _ in range(self.STEP_BUDGET):
            if i is None or not 0 <= i < len(self.script.code):
                return self.result
            i = self._step(i)
        raise Runaway(f"{self.script.name}: {self.STEP_BUDGET} steps and still going")


def run(name: str, cells: dict[tuple[str, int], int]) -> Result | None:
    """Load and run one script. None when the script is not on this machine."""
    script = load(name)
    return Machine(script, cells).run() if script else None
