#!/usr/bin/env python3
"""Fix the client's own bugs, for handing out through the updater.

Two fixes, one file -- the client is a single tmo.exe, so whatever is fixed in
it goes out together:

  * the 試験結果 page of the school paper (twenty bytes, below);
  * the title screen's おまけ button, which this build never draws (four
    bytes, after that).

The paper's 試験結果 tab draws the exam rankings from six files this server
publishes (server/newspaper.py). The client that shipped reads every score in
them as a SIGNED byte: each of the twenty loads that feed the table is a
``movsx``. A score of 0..100 survives that, but

  * 合, the eight scores added up, is put together as ``high << 8 | low`` from
    two sign-extended bytes, so any total whose low byte is 0x80 or more -- 200,
    450, 480, roughly half of them -- is drawn as a negative number;
  * a subject the sitter did not take is marked 0xFF, and the client compares
    the loaded value with 0xFF to draw 「　－　」 instead of a number -- after the
    sign extension it is -1, so the dash is never drawn and "-1" is.

Twenty one-byte changes fix both: ``0F BE`` (movsx) becomes ``0F B6`` (movzx)
at each load, and nothing else moves. 合 then reads 0..800 as written, and the
dash appears where the format says it should. (A total of exactly 255 also
reads as the marker and draws a dash; that is the format's own choice of
marker, and the fix keeps it rather than invent another.)

  The おまけ button
  ----------------
  The manual describes おまけ as part of this game (p02_06, p02_07, p09_02:
  a gallery of the scenes a character has seen and the endings received), and
  two of the operator's notices fixed bugs in it (2006-04-19 and 04-26). The
  client that shipped builds the title menu with the button and then, four
  bytes later, takes it away again: at 0x6895DD ``mov byte [ebp+0x13], 0``
  clears the "draw おまけ" flag whenever the nVersion property reads 1..5,
  and this build's own data sets it to 5. Those four bytes become NOPs. The
  other half of the condition is left as it is: the button still appears only
  once some character of the account has received a confession (the 0x0316
  list is not empty), as the client always meant it to.

  ⚠️ Why not raise nVersion instead: the same property also opens 転校 (moving
  to another school), which the manual never mentions and this build shipped
  closed. Changing the client's test changes only the button.

  How it reaches players, and why that way
  ----------------------------------------
  The way the operated game shipped client fixes. Its updater runs before the
  client on every start, and replaces whole files -- nothing in it edits part
  of one -- so a change to the client's code was a new tmo.exe, in place from
  the next start. Its own notices say as much: a fix to a crash on leaving a
  card game, 2007-03-03, "本修正は、一度ゲームを終了した後、再度起動することで
  適用（アップデート）されます". This tool makes that file and puts it where
  server/updater_server.py hands files out from (runtime/update/), and every
  client fetches it on its next start.

  ⚠️ The file is the client, so it is made from your own copy and never kept
  anywhere but your server's runtime/update/: this tree carries the twenty
  bytes, not the program. Your copy has to be the build this was written
  against, give or take the four bytes set_auth_address.py writes; anything
  else -- another build, a copy carrying other changes -- is refused rather
  than handed to every player who connects.

  ⚠️ The four authentication bytes. The copy that is handed out is the one the
  client then runs, so it has to carry the address your players' clients are
  pointed at -- the same one they gave Play.cmd / set_auth_address.py. Give it
  as --address; it is written exactly as set_auth_address.py writes it, so a
  client set up for this server sees nothing to change and fetches the file
  once. A client pointed elsewhere gets this server's address with the file.

Usage::

    python3 ranking_fix.py --game-dir <folder with tmo.exe> --address <server address>
    python3 ranking_fix.py --game-dir ... --address ... --check   # say what it would write
    python3 ranking_fix.py --remove                               # stop handing it out

The server needs no restart: the updater reads runtime/update/ at every check.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import set_auth_address as auth

HERE = Path(__file__).resolve().parent
UPDATE_DIR = HERE / "runtime" / "update"
TARGET = "tmo.exe"

#: SHA-256 of the build this was written against, as it shipped (2006012300).
RETAIL_SHA256 = "df6652613021f554f09bebda6de890d2cee3fc8133e9f096817255e31bc6608b"

IMAGE_BASE = 0x400000
MOVSX, MOVZX = 0xBE, 0xB6

#: The おまけ button's gate: the instruction that clears its flag, as shipped.
OMAKE_GATE = 0x6895DD
OMAKE_GATE_SHIPPED = "c6451300"
NOP = 0x90

#: The twenty loads, by address, with the instruction as shipped. The paper's
#: ranking drawer (0x60CA11) reads a クラス row's eight averages and 合 first,
#: then a 個人 row's eight scores and 合.
SITES = {
    0x60CF89: "0fbe4002", 0x60D008: "0fbe4003", 0x60D08D: "0fbe4004", 0x60D112: "0fbe4005",
    0x60D197: "0fbe4006", 0x60D21C: "0fbe4007", 0x60D2A1: "0fbe4008", 0x60D326: "0fbe4009",
    0x60D3AE: "0fbe410b", 0x60D3B2: "0fbe4a0a",
    0x60D525: "0fbe4018", 0x60D5AA: "0fbe4019", 0x60D635: "0fbe401a", 0x60D6C0: "0fbe401b",
    0x60D74B: "0fbe401c", 0x60D7D6: "0fbe401d", 0x60D861: "0fbe401e", 0x60D8EC: "0fbe401f",
    0x60D97B: "0fbe4121", 0x60D97F: "0fbe4a20",
}


def offset(va: int) -> int:
    """File offset of a .text address (raw and virtual coincide there)."""
    return va - IMAGE_BASE


def as_shipped(data: bytes) -> bytes:
    """The file with the authentication address and both fixes put back.

    So a copy already fixed -- by an earlier run of this tool, with or without
    the おまけ button -- is recognised as the build it was made from.
    """
    out = bytearray(data)
    site = auth.find_site(bytes(out))
    for k, octet in enumerate(auth.parse_ipv4(auth.ORIGINAL_ADDRESS)):
        out[site + 4 + 5 * k] = octet
    for va in SITES:
        out[offset(va) + 1] = MOVSX
    at = offset(OMAKE_GATE)
    if out[at:at + 4] == bytes([NOP] * 4):
        out[at:at + 4] = bytes.fromhex(OMAKE_GATE_SHIPPED)
    return bytes(out)


def fixed(data: bytes, address: bytes) -> bytes:
    """The build as shipped, pointed at ``address``, with both fixes made."""
    if hashlib.sha256(as_shipped(data)).hexdigest() != RETAIL_SHA256:
        raise ValueError(
            "this tmo.exe is not the build this fix was written for, or carries "
            "changes besides the authentication address -- refusing to hand it out")
    out = bytearray(as_shipped(data))
    for va, shipped in SITES.items():
        at = offset(va)
        if out[at:at + 4] != bytes.fromhex(shipped):  # pragma: no cover - hash covers it
            raise ValueError(f"unexpected instruction at {va:#x}")
        out[at + 1] = MOVZX
    at = offset(OMAKE_GATE)
    if out[at:at + 4] != bytes.fromhex(OMAKE_GATE_SHIPPED):  # pragma: no cover - hash covers it
        raise ValueError(f"unexpected instruction at {OMAKE_GATE:#x}")
    out[at:at + 4] = bytes([NOP] * 4)
    site = auth.find_site(bytes(out))
    for k, octet in enumerate(address):
        out[site + 4 + 5 * k] = octet
    return bytes(out)


def find_exe(game_dir: str) -> Path:
    path = Path(game_dir).expanduser()
    if path.is_dir():
        path = path / TARGET
    if not path.is_file():
        raise SystemExit(f"no {TARGET} at {path}")
    return path


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix the client's own bugs (試験結果 page, おまけ button), for handing out through the updater.")
    parser.add_argument("--game-dir", help="the folder that holds tmo.exe (or tmo.exe itself)")
    parser.add_argument("--address", help="the server address players' clients are pointed at")
    parser.add_argument("--update-dir", default=str(UPDATE_DIR),
                        help=f"where the updater's files live (default {UPDATE_DIR})")
    parser.add_argument("--check", action="store_true", help="say what would be written, write nothing")
    parser.add_argument("--remove", action="store_true", help="stop handing the fixed client out")
    args = parser.parse_args(argv)

    dest = Path(args.update_dir) / TARGET
    if args.remove:
        if dest.exists():
            dest.unlink()
            print(f"removed {dest}; clients that already fetched it keep it")
        else:
            print(f"nothing at {dest}")
        return 0
    if not args.game_dir or not args.address:
        parser.error("--game-dir and --address are both needed")

    source = find_exe(args.game_dir)
    shown, _resolved = auth.resolve_server(args.address)
    address = auth.parse_ipv4(shown)
    try:
        out = fixed(source.read_bytes(), address)
    except (ValueError, LookupError) as exc:
        print(f"{source}: {exc}", file=sys.stderr)
        return 1
    print(f"{source}: the shipped build; authentication address {shown}, "
          f"{len(SITES)} score loads and the おまけ button fixed")
    if args.check:
        print(f"would write {dest} ({len(out)} bytes, sha256 {hashlib.sha256(out).hexdigest()[:16]}…)")
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)
    print(f"wrote {dest}; every client fetches it on its next start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
