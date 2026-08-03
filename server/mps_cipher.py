"""Blowfish as ``mtBlowfishCipherModule`` implements it (tmo.exe 0xA4A5D0 ff.).

Three things differ from a textbook Blowfish, and all three have to match or the
client drops the connection before any message is exchanged:

1. **The initial tables are not the standard ones.** Blowfish seeds P and the
   four S-boxes with the fractional hex digits of pi; this build adds 1 to every
   *byte* of those constants (0x243f6a88 -> 0x25406b89, and so on for all 1042
   words). They sit in .data at 0xE32440 (P) and 0xE32508 (S0..S3), stored as
   ``value ^ 0x91`` and de-obfuscated in place on first use by the loop at
   0xA4AD3E, guarded by the once-flag at 0x220D500.

   Nothing here is copied out of the executable: ``_pi_bytes`` recomputes the
   digits of pi and ``_TABLES`` applies the +1. The two were checked against the
   de-obfuscated .data word for word.

2. **A block's two halves are read little-endian.** 0xA4A5D0 takes ``&out[0]``
   and ``&out[4]`` and dereferences them as x86 dwords, so L = LE32(b[0:4]).
   Most implementations pack big-endian here.

3. **The key schedule is standard** (0xA4AD30): key bytes are cycled modulo the
   key length and packed big-endian into the words XORed onto P, then the P and S
   words are replaced by successive encryptions of an all-zero block.

``BOOTSTRAP_KEY`` is the key every MPS connection starts with. It is a plain
ASCII string at 0xBF1FCC, passed with length 11 by the connection factory at
0x8CB099, and is what phase 1 of the key exchange is enciphered under. The
16-byte key that phase 1 *carries* is a per-connection random value the client
draws from ``rand()`` (0xA46267) and announces, so it needs no reproducing.
"""
from __future__ import annotations

import struct

BOOTSTRAP_KEY = b"yAhOoGoOGLe"

_N_WORDS = 18 + 4 * 256


def _pi_bytes(count: int) -> bytes:
    """The first ``count`` bytes of pi's fractional part, base 16.

    Machin's formula in scaled integers; 16 guard digits are dropped at the end.
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


def _init_tables() -> list[int]:
    words = struct.unpack(f">{_N_WORDS}I", _pi_bytes(4 * _N_WORDS))
    return [
        sum((((w >> shift) & 0xFF) + 1 & 0xFF) << shift for shift in (0, 8, 16, 24))
        for w in words
    ]


_TABLES = _init_tables()
_MASK = 0xFFFFFFFF


class Blowfish:
    """One keyed cipher module. Not thread-safe; each connection makes its own."""

    __slots__ = ("p", "s")

    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("empty key")
        self.p = _TABLES[:18]
        self.s = [_TABLES[18 + 256 * i : 18 + 256 * (i + 1)] for i in range(4)]

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

    def encipher(self, data: bytes) -> bytes:
        """Zero-pad to a multiple of 8 and encrypt every block, as 0xA4B190 does.

        The padding is why parsers downstream have to tolerate trailing zeros:
        the sender computes its checksum over the logical body, before this runs.
        """
        data = bytes(data) + b"\x00" * (-len(data) % 8)
        out = bytearray(len(data))
        for off in range(0, len(data), 8):
            left, right = struct.unpack_from("<II", data, off)
            struct.pack_into("<II", out, off, *self._encrypt_block(left, right))
        return bytes(out)

    def decipher(self, data: bytes) -> bytes:
        """Decrypt every block. 0xA4B300 rejects a length that is not a multiple
        of 8 outright, and the client logs ``illegal param2`` when we send one."""
        if len(data) % 8:
            raise ValueError(f"cipher text is {len(data)}B, not a multiple of 8")
        out = bytearray(len(data))
        for off in range(0, len(data), 8):
            left, right = struct.unpack_from("<II", data, off)
            struct.pack_into("<II", out, off, *self._decrypt_block(left, right))
        return bytes(out)
