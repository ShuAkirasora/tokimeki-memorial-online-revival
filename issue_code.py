#!/usr/bin/env python3
"""Hand out registration codes, and take them back.

A registration code is the twenty characters a player types into the five boxes
at the bottom of the login screen, and on this server it is the whole of their
identity: the account it names, the characters under that account, and -- once
the table this script writes exists -- whether they are let in at all.

  Where codes came from originally
  --------------------------------
  In the box. KONAMI printed them, recorded them, and the player bound theirs to
  a KONAMI ID on the website before it would work; the client's own refusal texts
  still carry that shape, with separate answers for a code that was never printed
  and a code that was printed but never bound. server/codes.py sets out the
  evidence for that reading and the two states this script uses because of it.

  This script is the printing press. Nothing is printed, so a code is shown on a
  terminal instead, which changes where the paper was and nothing else: the same
  generator, the same table, the same two stages.

  The two stages
  --------------
  A code starts as `issued` -- generated and recorded, claimed by nobody, and
  refused at the login screen with 「レジストレーションコードが登録されていません」
  -- and becomes `active` when somebody claims it. That claim is the step KONAMI
  put on their website, and this server has it too: the 登録 form on port 12013,
  where a player enters their KONAMI ID and the code, and which is the only path
  that records who a code belongs to.

  So the everyday shape is `issue_code.py --unregistered`, hand the code over,
  and let them register it. Issuing without that flag marks the code claimed
  immediately and by nobody -- convenient when handing one straight to somebody
  at the same machine, but it leaves no owner, and a code with no owner is one
  anybody can log in with. --activate is the same shortcut applied later.

  Usage
  -----
      issue_code.py                        issue one code, ready to use
      issue_code.py --note "for Kei"       ... with a reminder of who has it
      issue_code.py --count 10             ... ten of them
      issue_code.py --expires 2026-12-31   ... that stop working after a date
      issue_code.py --unregistered         ... left for the player to register

      issue_code.py --list                 every code, with state and note
      issue_code.py --activate CODE        claim a code without an owner
      issue_code.py --unregister CODE      undo a registration; it is unclaimed again
      issue_code.py --revoke CODE          stop it being used, keep the save
      issue_code.py --restore CODE         undo a revoke

  Codes may be given with or without the dashes and in any case. Revoking never
  touches the characters saved under the account: the two are separate files for
  that reason, so a code can be withdrawn and given back without risk to a save.

  The server reads the table on every login, so nothing here needs a restart.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
# The server package is not installed, and this has to agree with how run_all.py
# reaches its own siblings: by putting server/ on the path rather than by making
# it a package. One implementation of the table, used by both.
sys.path.insert(0, str(ROOT / "server"))

import codes  # noqa: E402


STATE_LABEL = {
    codes.STATE_ISSUED: "unregistered",
    codes.STATE_ACTIVE: "active",
    codes.STATE_SUSPENDED: "revoked",
}


def show(key: str, entry: dict) -> str:
    state = STATE_LABEL.get(entry.get("state", ""), entry.get("state", "?"))
    parts = [f"{codes.format_code(key)}  {state:<12}"]
    owner = entry.get("konami_id")
    if owner:
        parts.append(f"-> {owner}")
    expires = entry.get("expires")
    if expires:
        parts.append(f"until {expires}")
    note = entry.get("note")
    if note:
        parts.append(f"({note})")
    return "  ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--count", type=int, default=1, help="how many to issue")
    ap.add_argument("--note", default="", help="a reminder of who this is for")
    ap.add_argument("--expires", help="last day it works, as YYYY-MM-DD")
    ap.add_argument(
        "--unregistered",
        action="store_true",
        help="leave the code for the player to register on the form",
    )
    ap.add_argument("--list", action="store_true", help="show every code")
    ap.add_argument("--activate", metavar="CODE", help="claim a code, with no owner")
    ap.add_argument("--unregister", metavar="CODE", help="undo a code's registration")
    ap.add_argument("--revoke", metavar="CODE", help="stop a code being used")
    ap.add_argument("--restore", metavar="CODE", help="undo a revoke")
    args = ap.parse_args()

    table = codes.CodeTable(ROOT / "runtime" / "accounts")

    if args.list:
        if not table.table:
            print("no codes issued yet")
            return 0
        for key in sorted(table.table):
            print(show(key, table.table[key]))
        return 0

    if args.unregister:
        key = codes.normalise(args.unregister)
        if not table.unregister(key):
            print(f"no such code: {codes.format_code(key)}", file=sys.stderr)
            return 1
        print(show(key, table.table[key]))
        return 0

    for flag, state in (
        ("activate", codes.STATE_ACTIVE),
        ("revoke", codes.STATE_SUSPENDED),
        ("restore", codes.STATE_ACTIVE),
    ):
        given = getattr(args, flag)
        if not given:
            continue
        key = codes.normalise(given)
        if not table.set_state(key, state):
            print(f"no such code: {codes.format_code(key)}", file=sys.stderr)
            return 1
        print(show(key, table.table[key]))
        return 0

    if args.expires:
        # Fail here rather than write a date the server will trip over on the
        # first login after it.
        try:
            from datetime import date

            date.fromisoformat(args.expires)
        except ValueError:
            print(f"--expires wants YYYY-MM-DD, not {args.expires!r}", file=sys.stderr)
            return 1

    state = codes.STATE_ISSUED if args.unregistered else codes.STATE_ACTIVE
    for _ in range(max(1, args.count)):
        key = table.issue(state=state, note=args.note, expires=args.expires)
        print(show(key, table.table[key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
