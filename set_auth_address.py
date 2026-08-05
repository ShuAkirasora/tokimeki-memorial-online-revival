#!/usr/bin/env python3
"""Point the client's account-authentication step at a different address.

The client reaches its login, game and school servers by name, and reaches the
account-authentication service by a fixed IPv4 address with no name involved.
Name resolution cannot redirect an address, so a copy of the client that is to
talk to a server on your own machine has to be told the new address directly.

This script changes that address, and nothing else.  It writes four bytes.

  What the client does
  --------------------
  It builds the address one octet at a time, straight onto the stack, and hands
  the result to connect():

      mov byte [esp+0x28], 133      ; the four immediates below
      mov byte [esp+0x29], 221
      mov byte [esp+0x2a], 34
      mov byte [esp+0x2b], 229
      mov byte [esp+0x2c], bl       ; bl is zero here

  Those four immediates are the entire target.  Each octet is an independent
  byte, so any IPv4 address fits; there is no length limit to work around, no
  instruction to rewrite, no check to remove.  The authentication code itself is
  left exactly as it shipped and runs to completion on its own.

  How the site is found
  ---------------------
  Not by a hardcoded offset.  The script scans the whole file for that shape --
  four byte-stores to consecutive stack slots followed by the terminator store
  -- and requires it to occur exactly once.  In the build this was written
  against it occurs once, at 0x8A3A65.  If a differently-patched build turns up
  where the sequence is missing or ambiguous, the script stops rather than guess
  which bytes to overwrite.

  The other half: two names
  -------------------------
  Pointing the authentication step at your server is necessary but not
  sufficient.  The client also looks up tmollb.tokimekionline.com (which tells
  it where the login, game and school servers are) and tmoupd.tokimekionline.com
  (the update check), and those are names, so they belong to your resolver
  rather than to this script.  Give them to your hosts file and both arrive.

  Because forgetting that half looks exactly like a server that will not answer,
  the script resolves the two names after it is done and tells you what they
  currently point at.  That is one DNS lookup each and nothing else; --no-lookup
  turns it off.

  Usage
  -----
      set_auth_address.py <tmo.exe>              print the address it currently uses
      set_auth_address.py <tmo.exe> 192.168.1.5  point it at that address
      set_auth_address.py <tmo.exe> --revert     put the original address back
      set_auth_address.py <tmo.exe> ... -n       say what would change, write nothing

  The original file is copied to <tmo.exe>.orig before the first write, and an
  existing .orig is never overwritten.  --revert restores the address the client
  shipped with, which -- since these four bytes are the only ones touched --
  leaves the file byte-for-byte as it was.

This script ships no part of the client and contains no code from it.  It edits a
copy you already own.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import socket
import sys
from pathlib import Path

IMAGE_BASE = 0x400000

# The address the client was built to reach.  KONAMI's service ended in 2007 and
# nothing answers there now; whoever holds the address today has nothing to do
# with this game.
ORIGINAL_ADDRESS = "133.221.34.229"

# The two names the client resolves for itself.  Nothing in this script writes
# them; they are listed so it can tell you where they currently lead.
CLIENT_NAMES = ("tmollb.tokimekionline.com", "tmoupd.tokimekionline.com")

STORE_IMM = b"\xc6\x44\x24"  # mov byte [esp+disp8], imm8
STORE_BL = b"\x88\x5c\x24"  # mov byte [esp+disp8], bl


def parse_ipv4(text: str) -> bytes:
    parts = text.split(".")
    if len(parts) != 4:
        raise ValueError(f"{text!r} is not an IPv4 address")
    out = bytearray()
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part[0] == "0"):
            raise ValueError(f"{text!r} is not an IPv4 address")
        value = int(part)
        if not 0 <= value <= 255:
            raise ValueError(f"{text!r} has an octet outside 0-255")
        out.append(value)
    return bytes(out)


def find_site(data: bytes) -> int:
    """File offset of the first of the four address stores.

    Raises LookupError unless the shape occurs exactly once.
    """
    hits: list[int] = []
    pos = data.find(STORE_IMM)
    while pos >= 0:
        base = data[pos + 3]
        stores = all(
            data[pos + 5 * k : pos + 5 * k + 3] == STORE_IMM
            and data[pos + 5 * k + 3] == (base + k) & 0xFF
            for k in range(4)
        )
        terminator = (
            data[pos + 20 : pos + 23] == STORE_BL
            and data[pos + 23] == (base + 4) & 0xFF
        )
        if stores and terminator:
            hits.append(pos)
        pos = data.find(STORE_IMM, pos + 1)

    if not hits:
        raise LookupError(
            "the address-building sequence is not in this file -- this is either "
            "not tmo.exe, or a build this script does not know how to read"
        )
    if len(hits) > 1:
        found = ", ".join(hex(h + IMAGE_BASE) for h in hits)
        raise LookupError(
            f"the address-building sequence occurs {len(hits)} times ({found}); "
            "refusing to guess which one is the authentication address"
        )
    return hits[0]


def read_address(data: bytes, site: int) -> str:
    return ".".join(str(data[site + 4 + 5 * k]) for k in range(4))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def report_names(expected: str | None) -> None:
    """Say where the two names the client resolves currently lead.

    `expected` is the address they ought to reach, or None when there is nothing
    to compare against -- a client still pointed at the original address is not
    pointed at anybody's server, so no verdict is possible.
    """
    print("  the two names the client resolves for itself:")
    wrong = []
    for name in CLIENT_NAMES:
        try:
            answer: str | None = socket.gethostbyname(name)
        except OSError:
            answer = None
        verdict = ""
        if expected is not None:
            if answer == expected:
                verdict = "  ok"
            else:
                verdict = "  <- not your server"
                wrong.append(name)
        print(f"    {name:26s} -> {answer or 'no answer':15s}{verdict}".rstrip())

    if not wrong:
        return

    print()
    print("  Those have to reach the server too, and only your resolver can send")
    print("  them there.  Put these in your hosts file:")
    for name in wrong:
        print(f"      {expected}  {name}")
    print("  which is /etc/hosts, or on Windows")
    print(r"  C:\Windows\System32\drivers\etc\hosts (editable as administrator).")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Point the client's authentication step at a different address.",
    )
    ap.add_argument("exe", type=Path, help="path to your own copy of tmo.exe")
    ap.add_argument(
        "address",
        nargs="?",
        help="IPv4 address of the machine running the server, e.g. 192.168.1.5",
    )
    ap.add_argument(
        "--revert",
        action="store_true",
        help=f"restore the original address ({ORIGINAL_ADDRESS})",
    )
    ap.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing",
    )
    ap.add_argument(
        "--no-lookup",
        action="store_true",
        help="skip the check on the two names the client resolves for itself",
    )
    args = ap.parse_args()

    if args.revert and args.address:
        ap.error("give an address or --revert, not both")

    target = ORIGINAL_ADDRESS if args.revert else args.address
    octets = b""
    if target is not None:
        try:
            octets = parse_ipv4(target)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1

    try:
        data = bytearray(args.exe.read_bytes())
    except OSError as exc:
        print(f"cannot read {args.exe}: {exc}", file=sys.stderr)
        return 1

    try:
        site = find_site(data)
    except LookupError as exc:
        print(f"{args.exe.name}: {exc}", file=sys.stderr)
        return 1

    current = read_address(data, site)
    va = site + IMAGE_BASE
    print(f"{args.exe.name}  sha256 {digest(data)}")
    print(f"  authentication address {current}  (built at {va:#x})")

    # What the names ought to answer: where we are about to point this copy, or
    # where it already points.  A copy still on the original address is not
    # pointed at a server at all, so there is nothing to hold the names to.
    expected = target if target is not None else current
    if expected == ORIGINAL_ADDRESS:
        expected = None

    def done(code: int = 0) -> int:
        if not args.no_lookup:
            print()
            report_names(expected)
        return code

    if target is None:
        return done()

    if current == target:
        print(f"  already {target}; nothing to do")
        return done()

    print(f"  writing 4 bytes -> {target}")
    for k in range(4):
        offset = site + 4 + 5 * k
        print(
            f"    {offset + IMAGE_BASE:#x}  {data[offset]:3d} -> {octets[k]:3d}"
            f"   (file offset {offset:#x})"
        )

    if args.dry_run:
        print("  dry run, nothing written")
        return done()

    backup = args.exe.with_name(args.exe.name + ".orig")
    if backup.exists():
        print(f"  backup already exists, keeping it: {backup.name}")
    else:
        try:
            shutil.copy2(args.exe, backup)
        except OSError as exc:
            print(f"cannot write the backup {backup}: {exc}", file=sys.stderr)
            print("refusing to modify the executable without one", file=sys.stderr)
            return 1
        print(f"  backup -> {backup.name}")

    for k in range(4):
        data[site + 4 + 5 * k] = octets[k]

    try:
        args.exe.write_bytes(bytes(data))
    except OSError as exc:
        print(f"cannot write {args.exe}: {exc}", file=sys.stderr)
        return 1

    print(f"  done  sha256 {digest(data)}")
    return done()


if __name__ == "__main__":
    sys.exit(main())
