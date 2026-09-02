#!/usr/bin/env python3
"""Export the game's scripts out of your own copy, into `runtime/scripts/`.

A scripted scene runs on both ends at once. The client plays it out of its own
copy of the game; this server has to know the same instruction stream, because
the questions the client stops on -- which way a branch goes, which choice box
it just showed, what a string register holds -- are questions about that
stream, and the client asks them without saying anything about the script
beyond a number and a cursor.

Nothing in this repository answers them on its own, and nothing in it can: the
scripts are the game's content, they live in your copy, and they stay there.
What this script does is read your copy and write out the part this server
needs, next to it, on your machine. `runtime/` is not tracked, so what comes
out of here goes no further than the disk it was written on.

    python3 export_scripts.py                     everything, a few seconds
    python3 export_scripts.py amm_c011 lck_s102   just these
    python3 export_scripts.py --list              what your copy contains
    python3 export_scripts.py --game-dir PATH     when the guess is wrong

Two files come out per script, because this server reads a script twice over.
`<name>.json` carries the cast, the instruction stream in a form meant to be
read by a person, the branch targets, each choice box's own wording and each
free-text box's answers; it is what `/sc` drives a scene from.
`<name>.gs3.json` carries the same stream in
the form the interpreter in `server/gs3vm.py` runs, which is the register
machine the original server had and the client never did -- the client's own
instructions for the arithmetic are logging stubs that evaluate nothing. The
first is written for the 683 client scenarios; the second for those and for the
95 scripts that were the original server's own, which use the same bytecode
from the other side of the wire.

Four layers stand between the installed game and an instruction:

  1. `Data/script/*.arc` are ARC0 archives, one script each, plus
     `Data/idlist/idlist.arc`, which holds the table that gives a script its
     number.
  2. An archived payload beginning `TMOC` is enciphered. See below.
  3. The plaintext is a script container: `SSC Version 0.9x` for the client's
     scenarios, `GSC Version 1.00` for the original server's. Neither carries a
     table of contents; both have their sections found by an identity that
     holds over the whole set and nowhere else in a file.
  4. Inside is bytecode, 209 commands of fixed length each, listed in
     `reference/ssc_ops.tsv`.

  The cipher and its key
  ---------------------
  A TMOC payload is Blowfish in CBC mode: stock tables, block halves read
  big-endian, 16-byte key, 8-byte IV. Neither the key nor the IV is written
  down here, and neither needs to be -- both are in your copy of the game, and
  this script takes them from there.

  The key is built one byte at a time onto the stack, so it is not a run of
  bytes anyone can search for; what is searchable is the shape of the code that
  builds it. `mov byte [esp+d], imm` is five bytes, the displacements run
  consecutively, and a run long enough to be a key occurs exactly twice in the
  executable this was written against -- at 0x8C90F6 and 0xA51A06 -- because
  two subsystems each keep one. Which of the two opens the scripts is not
  something this script is told: it tries each against a payload you have, and
  keeps the one that produces a version string.

  The IV then falls out of the same payload. CBC recovers every block after the
  first without it, so the first block is the only unknown, and its plaintext
  is known already -- every script starts `SSC Vers` or `GSC Vers`. Deciphering
  the first block and XORing that in gives the IV, which is then checked
  against a second archive before anything is exported.

  So this reads the game you own with the game you own, and if a differently
  built copy turns up where the search is ambiguous it stops and says so rather
  than guessing. `--key` and `--iv` are there for that case.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPCODE_TABLE = HERE / "reference" / "ssc_ops.tsv"
OUT_DIR = HERE / "runtime" / "scripts"

GAME_EXE = "tmo.exe"


def say(text: str = "") -> None:
    print(text, flush=True)


# --------------------------------------------------------------- the archives


def arc_entries(blob: bytes):
    """Yield `(inner name, payload)` for every entry of an ARC0 archive.

    All little-endian u32. The header names three regions -- an entry table of
    32-byte records at 0x04/0x08, a name table at 0x0C/0x18 and a data region
    at 0x1C/0x20 -- but the offsets inside a record are absolute, so only the
    entry table's own position is needed to walk the whole thing.

        record: hash, timestamp, name offset, name length,
                data offset, stored size, original size, 0
    """
    if blob[:4] != b"ARC0":
        raise ValueError("not an ARC0 archive")
    table, size = struct.unpack_from("<II", blob, 4)
    for i in range(size // 32):
        _, _, name_at, name_len, data_at, stored, _, _ = struct.unpack_from(
            "<8I", blob, table + i * 32
        )
        name = blob[name_at:name_at + name_len].split(b"\0")[0]
        yield name.decode("ascii", "replace"), blob[data_at:data_at + stored]


# ----------------------------------------------------------------- the cipher


_N_WORDS = 18 + 4 * 256
_MASK = 0xFFFFFFFF


def _pi_bytes(count: int) -> bytes:
    """The first `count` bytes of pi's fractional part, base 16.

    Blowfish seeds P and its four S-boxes with these. Machin's formula in
    scaled integers; 16 guard digits are dropped at the end. `server/
    mps_cipher.py` computes the same digits for the network cipher, which is
    the same algorithm with a build-specific alteration this layer does not
    have -- so the two are kept apart rather than shared.
    """
    scale = 1 << (4 * (2 * count + 16))

    def atan_inv(x: int) -> int:
        total = term = scale // x
        x2, k = x * x, 1
        while term:
            term //= x2
            total += -term // (2 * k + 1) if k % 2 else term // (2 * k + 1)
            k += 1
        return total

    pi = 16 * atan_inv(5) - 4 * atan_inv(239)
    return ((pi - 3 * scale) >> 64).to_bytes(count, "big")


_TABLES = list(struct.unpack(f">{_N_WORDS}I", _pi_bytes(4 * _N_WORDS)))


class Blowfish:
    """Textbook Blowfish, block halves big-endian, with CBC decryption."""

    __slots__ = ("p", "s")

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("empty key")
        self.p = _TABLES[:18]
        self.s = [_TABLES[18 + 256 * i:18 + 256 * (i + 1)] for i in range(4)]

        n = len(key)
        for i in range(18):
            word = 0
            for j in range(4):
                word = (word << 8) | key[(4 * i + j) % n]
            self.p[i] ^= word

        left = right = 0
        for i in range(0, 18, 2):
            left, right = self._encrypt_block(left, right)
            self.p[i], self.p[i + 1] = left, right
        for box in self.s:
            for i in range(0, 256, 2):
                left, right = self._encrypt_block(left, right)
                box[i], box[i + 1] = left, right

    def _f(self, x: int) -> int:
        s0, s1, s2, s3 = self.s
        acc = (s0[x >> 24] + s1[(x >> 16) & 0xFF]) & _MASK
        acc ^= s2[(x >> 8) & 0xFF]
        return (acc + s3[x & 0xFF]) & _MASK

    def _encrypt_block(self, left: int, right: int) -> tuple[int, int]:
        p = self.p
        for i in range(16):
            left ^= p[i]
            right ^= self._f(left)
            left, right = right, left
        left, right = right, left
        return left ^ p[17], right ^ p[16]

    def _decrypt_block(self, left: int, right: int) -> tuple[int, int]:
        p = self.p
        for i in range(17, 1, -1):
            left ^= p[i]
            right ^= self._f(left)
            left, right = right, left
        left, right = right, left
        return left ^ p[0], right ^ p[1]

    def block(self, cipher: bytes) -> bytes:
        """One block through the cipher, before CBC's XOR is applied to it."""
        return struct.pack(">II", *self._decrypt_block(*struct.unpack(">II", cipher)))

    def cbc(self, data: bytes, iv: bytes) -> bytes:
        """P[i] = D(C[i]) XOR C[i-1], with the IV standing in as C[-1]."""
        if len(data) % 8:
            raise ValueError(f"cipher text is {len(data)}B, not a multiple of 8")
        out = bytearray(len(data))
        prev = struct.unpack(">II", iv)
        for off in range(0, len(data), 8):
            block = struct.unpack_from(">II", data, off)
            left, right = self._decrypt_block(*block)
            struct.pack_into(">II", out, off, left ^ prev[0], right ^ prev[1])
            prev = block
        return bytes(out)


TMOC = b"TMOC"
#: `mov byte [esp+disp8], imm8`, six or more in a row. Long enough that a run
#: this length is the key material and not an ordinary short string being
#: assembled; the key is 16 bytes plus its terminator.
_STACK_STORE = re.compile(rb"(?:\xc6\x44\x24.{2}){6,}", re.S)


def stack_built_constants(exe: bytes, length: int = 16) -> list[bytes]:
    """Every `length`-byte constant the executable writes onto the stack.

    A run counts only when the displacements are consecutive, which is what
    separates a constant being laid down in order from unrelated stores that
    happen to sit together.
    """
    out = []
    for match in _STACK_STORE.finditer(exe):
        raw = match.group()
        n = len(raw) // 5
        disp = [raw[5 * i + 3] for i in range(n)]
        if any((disp[i] + 1) & 0xFF != disp[i + 1] for i in range(n - 1)):
            continue
        imm = bytes(raw[5 * i + 4] for i in range(n))
        # A C string: the terminator is stored with the rest, and is not key.
        if len(imm) >= length + 1 and imm[length] == 0:
            out.append(imm[:length])
    return out


def unwrap_header(payload: bytes) -> tuple[int, bytes] | None:
    """`(plaintext length, cipher text)` for a TMOC payload, else None.

    Header is `TMOC`, u32 plaintext length, u32 cipher length rounded up to a
    multiple of the block size.
    """
    if payload[:4] != TMOC:
        return None
    plain_len, cipher_len = struct.unpack_from("<II", payload, 4)
    return plain_len, payload[12:12 + cipher_len]


MAGICS = (b"SSC Vers", b"GSC Vers")


def find_cipher(exe: bytes, samples: list[bytes]) -> tuple[bytes, bytes]:
    """The key and IV your copy uses, or a SystemExit saying why not.

    `samples` are cipher texts of at least two blocks each, from at least two
    archives. A candidate key is kept when every sample's *second* block --
    which CBC recovers without an IV -- comes out as the tail of a version
    string. The IV is then read off the first block, whose plaintext is one of
    the two magics, and has to agree across the samples.
    """
    candidates = stack_built_constants(exe)
    if not candidates:
        raise SystemExit(
            "no key-shaped constant found in the executable.\n"
            "Pass --key and --iv if you know them for this build."
        )

    for key in candidates:
        cipher = Blowfish(key)
        second = [
            bytes(a ^ b for a, b in zip(cipher.block(s[8:16]), s[0:8]))
            for s in samples
        ]
        if not all(part.startswith(b"ion ") for part in second):
            continue
        for magic in MAGICS:
            ivs = {
                bytes(a ^ b for a, b in zip(cipher.block(s[0:8]), magic))
                for s in samples
            }
            if len(ivs) != 1:
                continue
            iv = ivs.pop()
            if all(cipher.cbc(s[:16], iv)[:12] in
                   (b"SSC Version ", b"GSC Version ") for s in samples):
                return key, iv

    raise SystemExit(
        "found key-shaped constants, but none of them opens a script.\n"
        "This copy may be built differently; pass --key and --iv if you know "
        "them for it."
    )


# ------------------------------------------------------------- the containers


def _u16(b: bytes, off: int) -> int:
    return struct.unpack_from("<H", b, off)[0]


def _u32(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]


def _sjis(raw: bytes) -> str:
    return raw.split(b"\0")[0].decode("cp932", "replace")


def ssc_sections(b: bytes) -> dict | None:
    """The four regions of an SSC file, found by an identity, not a pointer.

    A header of four dword counts sits somewhere past the variable-length
    metadata, and two equations have to hold at once for it: the first count
    times four lands exactly on the end of the file, and it equals four plus
    the other three. Scanning every aligned position, that pair holds exactly
    once per file over all 683 scenarios and never in a GSC file, which is a
    different container. So the boundaries are worked out rather than guessed.
    """
    for p in range(0, len(b) - 16, 4):
        total = _u32(b, p)
        if total * 4 + p != len(b):
            continue
        code_dw, aux_dw, str_dw = (_u32(b, p + i * 4) for i in (1, 2, 3))
        if total != 4 + code_dw + aux_dw + str_dw:
            continue
        code = p + 16
        aux = code + 4 * code_dw
        return {"hdr": p, "code": code, "aux": aux, "pool": aux + 4 * aux_dw,
                "code_dw": code_dw, "aux_dw": aux_dw, "pool_dw": str_dw}
    return None


#: A label number is ten bits wide. The client's own decoder for the
#: subroutine call takes it as `(u16 & 0x3ff) << 2`, and both containers agree.
#: Bits 10 and 11 carry something else that nothing here reads.
LABEL_MASK = 0x3FF


def ssc_labels(b: bytes, hdr: int) -> list[int]:
    """The label table, which ends where the section header begins.

    Each entry is `(ip << 12) | flags | number`, numbered from one upwards, so
    the start is found by walking backwards until the numbering comes out as
    1, 2, 3, ... exactly filling the gap. An incomplete run means the table was
    not found; that returns empty rather than picking a base that half fits.
    """
    for start in range(hdr - 4, -1, -4):
        offsets, o = [], start
        while o < hdr:
            v = _u32(b, o)
            if (v & LABEL_MASK) != len(offsets) + 1:
                break
            offsets.append(v >> 12)
            o += 4
        if o == hdr and offsets:
            return offsets
    return []


def ssc_pool(b: bytes, start: int) -> dict[int, tuple[int, bytes]]:
    """The string pool: `{word offset: (word length, raw bytes)}`.

    Entries are NUL-terminated and step by `align2(len + 1)` words. Stepping by
    the terminator alone would read a padding byte as the next entry's first
    character, and the padding is not zeroed.
    """
    pool, o = {}, start
    while o < len(b) - 1:
        end = b.find(b"\0", o)
        if end < 0:
            break
        words = (end - o + 2) // 2
        pool[(o - start) // 2] = (words, b[o:end])
        o += words * 2
    return pool


#: The four cast declarations, and how long each one's record is. The lengths
#: differ by kind, which is why a fixed stride reads the wrong number of them.
_ACTOR_OPS = {0x0080: ("PC", 64), 0x0081: ("NPC", 52),
              0x0082: ("TMPNPC", 68), 0x0083: ("BGNPC", 56)}


def ssc_actors(b: bytes, stop: int) -> list[dict]:
    """The cast, declared at 0x100 as a short run of ordinary instructions.

    `type` and `id` are the same pair the protocol uses to name an NPC. The
    type is the low nibble at +0x2C; the id is at +4 shifted right one, except
    for type 3, where the client reads it out of the low nibble at +5 instead.
    """
    out, o = [], 0x100
    while o + 4 <= stop:
        op = _u16(b, o)
        if op not in _ACTOR_OPS:
            break
        category, size = _ACTOR_OPS[op]
        kind = _u32(b, o + 0x2C) & 0xF
        out.append({
            "category": category,
            "sei": _sjis(b[o + 6:o + 0x12]),
            "mei": _sjis(b[o + 0x12:o + 0x1E]),
            "type": kind,
            "id": (b[o + 5] & 0xF) if kind == 3 else (b[o + 4] >> 1),
        })
        o += size
    return out


def gsc_code_section(b: bytes) -> int:
    """Where a GSC file's code starts. Worked out, not pointed at.

    The dword before the code says how many dwords follow it, itself included,
    so the start is the one aligned position where `v == (len - (p+4))//4 + 1`.
    That holds at exactly one position in each of the 95 files; anything else
    raises rather than picking one.
    """
    hits = [p for p in range(0, len(b) - 4, 4)
            if (v := _u32(b, p))
            and (len(b) - (p + 4)) % 4 == 0
            and v == (len(b) - (p + 4)) // 4 + 1]
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} candidate code sections, expected 1")
    return hits[0] + 4


def gsc_labels(b: bytes, code: int) -> list[int]:
    """A GSC label table, collected backwards from just before the code.

    Same entry shape as an SSC one but stored the other way round, so the walk
    counts down to 1 instead of up from it. Raw entries: the caller shifts.
    """
    out, o, want = [], code - 8, None
    while o >= 0:
        v = _u32(b, o)
        index = v & LABEL_MASK
        if want is None:
            if index == 0:
                return []
            want = index
        if index != want:
            break
        out.append(v)
        want -= 1
        if want == 0:
            break
        o -= 4
    out.reverse()
    return out


# ---------------------------------------------------------------- the opcodes


#: Three commands only the original server's scripts use. They are not in the
#: table because the table was read out of the client, which has no decoder for
#: them; their length is eight, which is what makes all 95 files come out even.
GS3_ONLY = {0xC000: 8, 0xC001: 8, 0xA000: 4}


def load_opcodes() -> dict[int, tuple[int, str]]:
    """`{op: (length, name)}` from `reference/ssc_ops.tsv`."""
    out = {}
    for line in OPCODE_TABLE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        op, _slot, size, name = line.split("\t")
        out[int(op, 16)] = (int(size), name)
    return out


def decode(b: bytes, start: int, end: int, ops: dict):
    """Walk a code section, yielding `(byte offset, op, name, operands)`.

    An op is the whole little-endian u16 at the instruction, not a field of it,
    and every command has one fixed length. Instructions are four-byte aligned,
    and a u16 zero on an odd word boundary is the padding that gets them there
    rather than the command whose number is zero. Anything unaccounted for
    raises: a stream that does not come out even has been misread.
    """
    pos = start
    while pos < end:
        op = _u16(b, pos)
        if op == 0 and (pos - start) % 4 == 2:
            pos += 2
            continue
        size = GS3_ONLY.get(op) or (ops[op][0] if op in ops else None)
        if size is None:
            raise ValueError(f"unknown op {op:#06x} at +{pos - start}")
        if pos + size > end:
            raise ValueError(f"op {op:#06x} at +{pos - start} runs past the code")
        name = ops[op][1] if op in ops else "<GS3 op>"
        yield pos - start, op, name, b[pos + 2:pos + size]
        pos += size
    if pos != end:
        raise ValueError(f"code section ends {pos - end} bytes out")


# --------------------------------------------------------------- the operands


#: A register field: seven bits of number, three of category. Category 7 means
#: the field is an immediate rather than a register number.
REG_ABBR = {0: "F", 1: "B", 2: "D", 3: "S", 4: "L", 5: "P", 6: "E", 7: "#"}
CAT_SSTRING, CAT_LSTRING, CAT_IMM = 3, 4, 7


def reg(field: int) -> tuple[int, int]:
    return (field >> 7) & 7, field & 0x7F


def regname(r: tuple[int, int] | None) -> str:
    if r is None:
        return "?"
    category, number = r
    return f"#{number}" if category == CAT_IMM else f"{REG_ABBR.get(category, '?')}{number}"


def str_regs(args: bytes) -> tuple[tuple[int, int], tuple[int, int]]:
    """A move: `(destination, source)`. A source in category 7 is a literal."""
    a = int.from_bytes(args[0:2], "little")
    v = int.from_bytes(args[2:6], "little")
    return reg(a), ((a >> 10) & 7, v)


#: How the cast is addressed from an instruction: three bits of kind, five of
#: number. The numbering is one-based into that kind's declarations.
CATEGORIES = ("PC", "NPC", "TMPNPC", "BGNPC")


def actor(v: int) -> str:
    kind = v >> 5
    return f"{CATEGORIES[kind] if kind < 4 else kind}#{v & 0x1F}"


def _bits(mask: int, width: int) -> list[int]:
    return [i for i in range(width) if mask >> i & 1]


def talk_speakers(b: bytes, a: int) -> list[str]:
    """Who a line of dialogue is for: four masks, one per kind of cast member,
    16 or 32 bits wide as the client's own expansion of them reads them."""
    out = []
    for kind, (off, wide) in enumerate(((2, 16), (4, 32), (8, 32), (0xC, 16))):
        mask = struct.unpack_from("<I" if wide == 32 else "<H", b, a + off)[0]
        out += [f"{CATEGORIES[kind]}#{i}" for i in _bits(mask, wide)]
    return out


def talk_lines(b: bytes, sec: dict, pool: dict, a: int) -> list[str] | None:
    """The dialogue itself, or None when the reading does not check out.

    +0x14 is the word offset of the first line in the string pool; +0x18 is an
    auxiliary-table reference with the number of lines in its low six bits.
    Each auxiliary entry's low nine bits are that line's padded word length, so
    the lines are stepped through one after another. Every step is checked
    against the pool's own length for that entry, which is what makes this
    self-verifying rather than a shape that happens to fit.
    """
    aux_ref = _u32(b, a + 0x18)
    w = _u32(b, a + 0x14) >> 12
    out = []
    for j in range(aux_ref & 0x3F):
        n = _u16(b, sec["aux"] + 2 * (aux_ref >> 12) + 2 * j) & 0x1FF
        entry = pool.get(w)
        if entry is None or entry[0] != n:
            return None
        out.append(entry[1].decode("cp932", "replace"))
        w += n
    return out


def branch_target(b: bytes, a: int) -> int:
    """Where a conditional branch goes when its condition holds.

    +2 is the condition, +4 is `target << 12`. The unit is the one the labels
    and jumps inside the file agree on: u16 words from the code section. The
    client reports its cursor in file bytes instead; `script.py` converts.
    """
    return _u32(b, a + 4) >> 12


def select_options(b: bytes, pool: dict, a: int) -> tuple[str, list[str]] | None:
    """A choice box's prompt and its options, or None if it does not check out.

    +12 is `(prompt word offset << 12) | word length`; +16 holds the number of
    options in its low six bits. The options are the pool entries following the
    prompt, one after another, so this walks the pool rather than the auxiliary
    table. The prompt's length has to match the pool's own, which is the check.
    """
    head = _u32(b, a + 12)
    w, n = head >> 12, head & 0xFFF
    entry = pool.get(w)
    if entry is None or entry[0] != n:
        return None
    out, w = [], w + n
    for _ in range(_u32(b, a + 16) & 0x3F):
        nxt = pool.get(w)
        if nxt is None:
            return None
        out.append(nxt[1].decode("cp932", "replace"))
        w += nxt[0]
    return entry[1].decode("cp932", "replace"), out


#: The free-text box, and the two twins of it that no scenario uses. Only
#: 0x7001 carries a list of answers: the client decodes 0x7002's `+12` as a
#: single pool reference and calls it a default line -- its own debug print
#: says 「デフォルト文」 where 0x7001's says 「選択肢数」 -- so the two are not
#: the same command with a flag, and neither twin occurs in the 683 scenarios.
OP_INPUT_STRING = 0x7001
OP_INPUT_STRING_PAGE = 0x7002
OP_INPUT_STRING_LOVE = 0x7003


def input_box(b: bytes, sec: dict | None, pool: dict, a: int) -> dict | None:
    """A free-text box: its prompt, its limits and the answers it accepts.

    Every field is read off the client's own decoder for the command rather
    than matched against the data: `+2`'s low byte is the time limit in
    seconds and its top nibble the part whose box this is -- the decoder
    compares that nibble against the player's own part and puts up nothing when
    they differ -- `+4` is an ordinary register field shifted left by five with
    the character limit in the five bits underneath, `+8` is the prompt as a
    pool reference, and `+12` is `(auxiliary word offset << 12) | count` with
    the count five bits wide. Each auxiliary entry is one dword and is itself a
    pool reference: one answer the box accepts.

    ⭐⭐ **The register is the point of exporting this at all.** What the
    player typed goes into it verbatim, and the scenarios then compare that
    register -- against a literal of their own (`un122` asks for a surname and
    follows the box with `S31 = #<城崎>` / `F99 = S1 == S31`) or against the
    other player's box (`un111` fills S0 with one player's guess at their
    partner's hobby and S1 with the partner's own answer, then compares the
    two). The client can do neither: its arithmetic slots are logging stubs, so
    that comparison only ever ran on a server.

    ⚠️ **The answers are what the box offers, not what the register may hold.**
    They are suggestions on the client's side and the player is free to type
    something else -- which is exactly what `un122` is built around, since the
    surname it is fishing for (城崎) is not one of the two it offers. So they
    are exported to be read, and nothing decides anything by them.

    None when the prompt's length does not match the pool's own or an answer
    does not resolve, which is the same check `select_options` makes.
    """
    if sec is None:
        return None
    head = _u32(b, a + 8)
    prompt = pool.get(head >> 12)
    if prompt is None or prompt[0] != (head & 0xFFF):
        return None
    listed = _u32(b, a + 12)
    word, count = listed >> 12, listed & 0x1F
    answers = []
    for k in range(count):
        at = sec["aux"] + 2 * (word + 2 * k)
        if at + 4 > len(b):
            return None
        ref = _u32(b, at)
        entry = pool.get(ref >> 12)
        if entry is None or entry[0] != (ref & 0xFFF):
            return None
        answers.append((ref, entry[1].decode("cp932", "replace")))
    limits = _u16(b, a + 4)
    return {
        "prompt": prompt[1].decode("cp932", "replace"),
        "register": reg(limits >> 5),
        "characters": limits & 0x1F,
        "seconds": b[a + 2],
        "actor": _u16(b, a + 2) >> 12,
        "answers": answers,
    }


def event_result(b: bytes, pool: dict, a: int) -> dict | None:
    """What a multi-player scene awards, or None if it does not check out.

    Read off the client's own formatting of it, whose four slots are, in the
    order it feeds them: the name of the score at +8, the sentence at +4, and
    at +12 a count of keywords in the low nibble and of items in the next.
    Memory order and print order disagree, hence the crossed offsets. +2 is a
    register field naming where the score is kept.
    """
    got = {}
    for key, ref in (("point", _u32(b, a + 8)), ("text", _u32(b, a + 4))):
        entry = pool.get(ref >> 12)
        if entry is None or entry[0] != (ref & 0xFFF):
            return None
        got[key] = entry[1].decode("cp932", "replace")
    counts = _u32(b, a + 12)
    got["register"] = reg(_u16(b, a + 2))
    got["keywords"] = counts & 0xF
    got["items"] = (counts >> 4) & 0xF
    return got


def operand_text(b: bytes, sec: dict | None, pool: dict, a: int,
                 op: int, size: int) -> str:
    """One instruction's operands in words, for the ones whose layout is known.

    Everything else prints as hex. A field nobody has read is not given a name
    here just to have one.
    """
    if op in (0x4081, 0x40C1, 0x408A):                  # DISP ON/OFF, MOVE_WAIT
        return actor(b[a + 2])
    if op == 0x4083:                                    # MAP_CHARA_POSITION
        return f"{actor(b[a + 2])} map={b[a + 3]} x={_u16(b, a + 4)} y={_u16(b, a + 8)}"
    if op == 0x4084:                                    # MAP_CHARA_MOTION
        return f"{actor(b[a + 2])} motion={b[a + 3] & 0x7F} loop={b[a + 3] >> 7}"
    if op == 0x4085:                                    # MAP_CHARA_DIRECTION
        return f"{actor(b[a + 2])} dir={b[a + 3] & 0xF}"
    if op == 0x5380 and sec is not None:                # TALK_ON_EVENT
        who = "+".join(talk_speakers(b, a)) or "(nobody)"
        lines = talk_lines(b, sec, pool, a)
        if lines is None:
            return f"{who}  <lines do not check out>"
        return f"{who}  " + " / ".join(t.replace("\n", "\\n") for t in lines)
    if op == 0x7000:                                    # INPUT_SELECT
        got = select_options(b, pool, a)
        if got is None:
            return f"<options do not check out> {b[a + 2:a + size].hex(' ')}"
        prompt, options = got
        return f"[{prompt}] " + " / ".join(t.replace("\n", "\\n") for t in options)
    if op == OP_INPUT_STRING:                           # free-text box
        got = input_box(b, sec, pool, a)
        if got is None:
            return f"<answers do not check out> {b[a + 2:a + size].hex(' ')}"
        return (f"-> {regname(got['register'])} ({got['characters']} chars, "
                f"{got['seconds']}s) [{got['prompt']}] "
                + " / ".join(t.replace("\n", "\\n") for _ref, t in got["answers"]))
    if op == 0x9080:                                    # jump
        return f"-> ip={_u32(b, a + 4) >> 12}"
    if op == 0x9081:                                    # branch
        return f"cond={_u16(b, a + 2):#06x} taken -> ip={branch_target(b, a)}"
    if op == 0x9082:                                    # branch on part played
        return (f"parts={_u16(b, a + 2):#06x} taken -> ip="
                f"{_u32(b, a + 4) >> 12}")
    if op == 0x90C0:                                    # end of that block
        return f"parts={_u16(b, a + 2):#06x} (marker, does not jump)"
    if op == 0x9100:                                    # PLAYER_SYNC
        return f"parts={_u16(b, a + 2):#06x}"
    if op in (0x9101, 0x9103):                          # PLAYER_WAIT_TIME
        v = _u16(b, a + 2)
        return f"wait={v} ({v / 100:g}s)"
    if op == 0x9200:                                    # RESULT_MULTI_PLAYER_EVENT
        got = event_result(b, pool, a)
        if got is None:
            return f"<result does not check out> {b[a + 2:a + size].hex(' ')}"
        return (f"{regname(got['register'])} [{got['point']}]"
                f" keywords={got['keywords']} items={got['items']}  "
                + got["text"].replace("\n", "\\n"))
    return b[a + 2:a + size].hex(" ")


# ----------------------------------------------------------------- a script


OP_STR = 0x9001
OP_SYNC_VARIABLE = 0x903F
OP_INPUT_SELECT = 0x7000
OP_BR = 0x9081
OP_RESULT_MULTI_PLAYER_EVENT = 0x9200


class Script:
    """One decrypted script, decoded far enough to be written out twice."""

    def __init__(self, name: str, blob: bytes, ops: dict) -> None:
        self.name = name
        self.b = blob
        self.gsc = blob[:3] == b"GSC"
        if self.gsc:
            self.sections = None
            self.code = gsc_code_section(blob)
            self.pool: dict[int, tuple[int, bytes]] = {}
            self.actors: list[dict] = []
            self.labels = [v >> 12 for v in gsc_labels(blob, self.code)]
            end = len(blob)
        else:
            sec = ssc_sections(blob)
            if sec is None:
                raise ValueError("no section header found")
            self.sections = sec
            self.code = sec["code"]
            self.pool = ssc_pool(blob, sec["pool"])
            self.actors = ssc_actors(blob, sec["hdr"])
            self.labels = ssc_labels(blob, sec["hdr"])
            end = sec["code"] + 4 * sec["code_dw"]
        self.instructions = list(decode(blob, self.code, end, ops))

    # ------------------------------------------------------------ the two bits
    # the instruction stream does not carry

    def sync_registers(self, off: int) -> list[tuple[int, int]]:
        """Which registers a synchronisation point synchronises.

        The instruction does not say: +4 is `(auxiliary word offset << 12) |
        count`, the same encoding a choice box uses for its option count, and
        the entries themselves are in the auxiliary table in ordinary register
        form. A GSC file has no auxiliary table and no synchronisation points.
        """
        if self.gsc or self.sections is None:
            return []
        v = _u32(self.b, self.code + off + 4)
        w, n = v >> 12, v & 0xFFF
        return [reg(_u16(self.b, self.sections["aux"] + 2 * (w + k)))
                for k in range(n) if 0 <= w + k < self.sections["aux_dw"] * 2]

    def string_literal(self, v: int) -> str | None:
        """A string register's literal: `(pool word offset << 12) | length`.

        The length is checked against the pool's own, so a value that is not a
        pool reference reads as None instead of as whatever sits at that
        offset. The client cannot fill these in for itself -- its instruction
        for the move is a logging stub that writes no register -- so a line
        with a placeholder in it is filled from this end or not at all.
        """
        if self.gsc or not isinstance(v, int) or v < 0:
            return None
        entry = self.pool.get(v >> 12)
        if entry is None or entry[0] != (v & 0xFFF):
            return None
        return entry[1].decode("cp932", "replace")

    def input_boxes(self) -> dict[int, dict]:
        """`{byte offset: box}` for every free-text box this script puts up.

        Empty for a GSC file: the original server's own scripts have neither an
        auxiliary table nor a string pool, and none of them holds one of these.
        """
        out = {}
        for off, op, _name, _args in self.instructions:
            if op != OP_INPUT_STRING:
                continue
            got = input_box(self.b, self.sections, self.pool, self.code + off)
            if got is not None:
                out[off] = got
        return out

    def string_literals(self) -> dict[int, str]:
        """`{literal: text}` for every literal moved into a string register.

        A scene's result carries two more of the same references -- the name of
        the score and its sentence -- so they go into the same table rather
        than into a field of their own.
        """
        out: dict[int, str] = {}
        for _off, op, _name, args in self.instructions:
            if op == OP_RESULT_MULTI_PLAYER_EVENT:
                for at in (2, 6):
                    v = int.from_bytes(args[at:at + 4], "little")
                    text = self.string_literal(v)
                    if text is not None:
                        out[v] = text
                continue
            if op != OP_STR:
                continue
            dest, (source_cat, value) = str_regs(args)
            if dest[0] not in (CAT_SSTRING, CAT_LSTRING) or source_cat != CAT_IMM:
                continue
            text = self.string_literal(value)
            if text is not None:
                out[value] = text
        return out


# ------------------------------------------------------------- the two exports


def vm_doc(script: Script, script_id: int | None) -> dict:
    """What `server/gs3vm.py` runs: the stream, and the two things around it.

    Deliberately container-agnostic -- the label table is already resolved to
    ips and operands are hex -- so that no parser for the game's own files has
    to exist on the server side.
    """
    return {
        "name": script.name,
        "container": "GSC" if script.gsc else "SSC",
        "scriptId": None if script.gsc else script_id,
        "codeBase": script.code,
        "labels": list(script.labels),
        "code": [[off // 2, op, args.hex()]
                 for off, op, _name, args in script.instructions],
        "sync": {str(off // 2): [list(r) for r in script.sync_registers(off)]
                 for off, op, _n, _a in script.instructions
                 if op == OP_SYNC_VARIABLE},
        # The one thing a free-text box needs and the stream does not carry:
        # which register the typed line goes into. It sits in the operand in
        # the same encoding a data reference uses -- shifted five bits left,
        # with the character limit underneath -- and the interpreter is given
        # it already decoded, along with the answers the box offers so that a
        # log line can say what the player was looking at.
        "inputs": {str(off // 2): {"register": list(box["register"]),
                                   "characters": box["characters"],
                                   "answers": [t for _ref, t in box["answers"]]}
                   for off, box in script.input_boxes().items()},
        "strings": {str(v): text for v, text in script.string_literals().items()},
    }


def script_doc(script: Script, script_id: int | None) -> dict:
    """What `/sc` drives a scene from: the cast, the stream, and the two
    things the client stops to ask about.

    The branch targets and the choice boxes are resolved here, where the file
    is open, so that the server never has to open one.
    """
    b, sec, pool = script.b, script.sections, script.pool
    instructions, branches, selects = [], {}, {}
    for off, op, name, args in script.instructions:
        a = script.code + off
        size = len(args) + 2
        instructions.append([off // 2, op, name,
                             operand_text(b, sec, pool, a, op, size)])
        if op == OP_BR:
            branches[str(off // 2)] = branch_target(b, a)
        elif op == OP_INPUT_SELECT:
            got = select_options(b, pool, a)
            if got is not None:
                selects[str(off // 2)] = {"prompt": got[0], "options": got[1]}
    inputs = {str(off // 2): {"prompt": box["prompt"],
                              "register": regname(box["register"]),
                              "characters": box["characters"],
                              "seconds": box["seconds"],
                              "actor": box["actor"],
                              "answers": [t for _ref, t in box["answers"]]}
              for off, box in script.input_boxes().items()}
    return {
        "file": f"{script.name}.ssb",
        "scriptId": script_id,
        # Byte offset of the code inside the file. The client reports its
        # cursor in those units; everything here counts u16 words from it.
        "codeBase": script.code,
        "actors": [
            {"actorId": i, "category": a["category"], "name": a["sei"] + a["mei"],
             "type": a["type"], "id": a["id"]}
            for i, a in enumerate(script.actors, 1)
        ],
        "instructions": instructions,
        "branches": branches,
        "selects": selects,
        # A free-text box is the third thing the client stops to ask about,
        # and the only one whose wording it does not decide by itself.
        "inputs": inputs,
    }


# --------------------------------------------------------------- your copy


def game_data_dirs(folder: Path) -> tuple[Path, Path | None]:
    """`(the script folder, the id-table folder)` under an installed copy.

    An install keeps its data one level down, but a copy someone has unpacked
    by hand may not, so both shapes are accepted and neither is required to be
    the one the installer makes.
    """
    for base in (folder / "Data", folder):
        scripts = base / "script"
        if scripts.is_dir():
            ids = base / "idlist"
            return scripts, ids if ids.is_dir() else None
    raise SystemExit(
        f"{folder} has no script folder in it.\n"
        "Point --game-dir at the folder that holds tmo.exe."
    )


def find_game_folder(given: str | None) -> Path:
    """Your copy of the game: what you said, what play.py remembers, or a guess."""
    if given:
        folder = Path(given).expanduser()
        if not (folder / GAME_EXE).is_file():
            raise SystemExit(f"{folder} has no {GAME_EXE} in it")
        return folder
    try:
        import play
    except Exception:                                 # pragma: no cover
        play = None
    if play is not None:
        remembered = play.load_config().get("game_dir")
        found = play.resolve_game_folder(None, remembered)
        if found is not None:
            return found
    raise SystemExit("cannot find the game; pass --game-dir")


def script_ids(idlist_dir: Path | None, cipher: Blowfish, iv: bytes) -> dict[str, int]:
    """`{'amm_s001.ssb': 57344, ...}` -- the numbers the client names scripts by.

    From `script.bin` in the id archive, which is one of the game's index
    tables: a count at +4, the width of the name field at +0x0C and +0x0E, the
    record length at +0x10, records from +0x20. The key is what precedes the
    name in a record. Missing means the exports go out without ids, which costs
    only the ability to answer a scene the client starts by number.
    """
    if idlist_dir is None:
        return {}
    for archive in sorted(idlist_dir.glob("*.arc")):
        for name, payload in arc_entries(archive.read_bytes()):
            if Path(name).name != "script.bin":
                continue
            head = unwrap_header(payload)
            b = cipher.cbc(head[1], iv)[:head[0]] if head else payload
            if b[:4] != b"IdBn":
                continue
            count = _u32(b, 4)
            name_at, name_len, record = struct.unpack_from("<HHH", b, 0x0C)
            out = {}
            for i in range(count):
                r = b[0x20 + i * record:0x20 + (i + 1) * record]
                key = int.from_bytes(r[:name_at], "little")
                stem = _sjis(r[name_at:name_at + name_len])
                if stem:
                    out[stem] = key
            return out
    return {}


def archive_scripts(script_dir: Path) -> dict[str, Path]:
    """`{name: archive}` for every script your copy has, by the name you type."""
    return {p.stem: p for p in sorted(script_dir.glob("*.arc"))}


def read_script(archive: Path, cipher: Blowfish, iv: bytes) -> bytes | None:
    """The one script inside an archive, deciphered. None if it holds none.

    Forty of the archives carry the source a script was compiled from rather
    than the script; those have nothing here to run.
    """
    for name, payload in arc_entries(archive.read_bytes()):
        if not name.lower().endswith(".ssb"):
            continue
        head = unwrap_header(payload)
        if head is None:
            return payload
        return cipher.cbc(head[1], iv)[:head[0]]
    return None


# ------------------------------------------------------------------- the run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the game's scripts into runtime/scripts/.",
        epilog="Run with no names to export everything your copy contains.",
    )
    parser.add_argument("names", nargs="*", help="script names, e.g. amm_c011")
    parser.add_argument("--game-dir", help="the folder that holds tmo.exe")
    parser.add_argument("--list", action="store_true",
                        help="print what your copy contains and stop")
    parser.add_argument("--out", default=str(OUT_DIR),
                        help=f"where to write (default {OUT_DIR})")
    parser.add_argument("--key", help="16-byte container key, hex")
    parser.add_argument("--iv", help="8-byte container IV, hex")
    args = parser.parse_args(argv)

    folder = find_game_folder(args.game_dir)
    script_dir, idlist_dir = game_data_dirs(folder)
    archives = archive_scripts(script_dir)
    if not archives:
        raise SystemExit(f"{script_dir} holds no archives")

    if args.list:
        say(f"{len(archives)} scripts in {script_dir}")
        for name in sorted(archives):
            say(f"  {name}")
        return 0

    if args.key and args.iv:
        key, iv = bytes.fromhex(args.key), bytes.fromhex(args.iv)
    else:
        exe = (folder / GAME_EXE).read_bytes()
        # One sample per archive, two archives, so that the IV has to agree
        # across files rather than across two entries of the same one.
        samples = []
        for path in sorted(archives.values()):
            for _name, payload in arc_entries(path.read_bytes()):
                head = unwrap_header(payload)
                if head is not None and len(head[1]) >= 16:
                    samples.append(head[1])
                    break
            if len(samples) >= 2:
                break
        if len(samples) < 2:
            raise SystemExit("no enciphered scripts to work the key out from")
        key, iv = find_cipher(exe, samples)
    cipher = Blowfish(key)

    ids = script_ids(idlist_dir, cipher, iv)
    say(f"  {len(archives)} archives, {len(ids)} numbered scripts")

    ops = load_opcodes()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted = args.names or sorted(archives)
    written = skipped = failed = 0
    for name in wanted:
        archive = archives.get(name) or archives.get(name.replace(".ssb", ""))
        if archive is None:
            say(f"  ? {name}: your copy has no such script")
            failed += 1
            continue
        blob = read_script(archive, cipher, iv)
        if blob is None:
            skipped += 1
            continue
        try:
            script = Script(archive.stem, blob, ops)
        except (ValueError, KeyError, struct.error, IndexError) as exc:
            say(f"  ! {name}: {exc}")
            failed += 1
            continue
        script_id = ids.get(f"{script.name}.ssb")
        (out_dir / f"{script.name}.gs3.json").write_text(
            json.dumps(vm_doc(script, script_id), separators=(",", ":")),
            encoding="utf-8")
        if not script.gsc:
            (out_dir / f"{script.name}.json").write_text(
                json.dumps(script_doc(script, script_id),
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
        written += 1
        if len(wanted) <= 20:
            say(f"  {script.name}  {'GSC' if script.gsc else 'SSC'} "
                f"id={script_id} codeBase={script.code} "
                f"{len(script.instructions)} instructions, "
                f"{len(script.labels)} labels")
        elif written % 100 == 0:
            say(f"  ... {written}")

    say(f"  {written} exported into {out_dir}"
        + (f", {skipped} archives held no script" if skipped else "")
        + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
