#!/usr/bin/env python3
"""Make every fix this server hands out through the updater, in one run.

There are two, each with its own tool and its own section in the README:

  * confession_fix.py -- the confession scenes, Amamiya's epilogue and her
    events 5-10: eleven script archives into runtime/update/, and the same
    eleven scripts exported again into runtime/scripts/; and the おまけ
    gallery's pictures: idlist.arc, into runtime/update/;
  * ranking_fix.py -- the client's own bugs: a tmo.exe with the 試験結果 page's
    twenty score loads fixed, the おまけ button let through, the gallery's
    expression photos reachable, its Epilogue opening, イベント中断
    working in a one-player event, Esc ending an おまけ staff roll and no
    あとがき after an おまけ confession is left, into runtime/update/.

This runs the first and then the second against the same copy of the game, and
says at the end which of them went through. Each tool still runs on its own,
with the options it documents; this one only passes the shared ones along.

  ⚠️ --address is asked for, never guessed. The fixed tmo.exe is the client
  every player then runs, so it carries the address their clients are pointed
  at -- the one they gave Play.cmd. The address already written in your own
  copy is only where *your* client points, which on a server's own machine is
  often not where players connect; handing that out would point every player
  somewhere else. If it is missing, this stops before writing anything and
  shows what your copy carries, so the right one can be passed.

Usage::

    python3 apply_fixes.py --address <your server's address>
    python3 apply_fixes.py --address ... --game-dir <folder with tmo.exe>
    python3 apply_fixes.py --address ... --check     # say what would be written

The server needs no restart: the updater reads runtime/update/ at every check,
and the server reads each export as the scene starts. To take a fix back, see
that fix's own section in the README.
"""
from __future__ import annotations

import argparse
import sys

import confession_fix
import ranking_fix
import set_auth_address as auth
from export_scripts import find_game_folder


def copy_address(folder) -> str:
    """The address the copy in ``folder`` is pointed at now, for the error message."""
    try:
        data = ranking_fix.find_exe(str(folder)).read_bytes()
        return auth.read_address(data, auth.find_site(data))
    except (SystemExit, OSError, ValueError, LookupError):
        return "unreadable"


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Make every updater-delivered fix, in one run.")
    parser.add_argument("--game-dir", help="the folder that holds tmo.exe (found as export_scripts.py finds it if left out)")
    parser.add_argument("--address", help="the server address players' clients are pointed at")
    parser.add_argument("--check", action="store_true", help="say what would be written, write nothing")
    parser.add_argument("--update-dir", default=str(ranking_fix.UPDATE_DIR),
                        help=f"where the updater's files live (default {ranking_fix.UPDATE_DIR})")
    parser.add_argument("--scripts-dir", default=str(confession_fix.SCRIPT_DIR),
                        help=f"where the server's exports go (default {confession_fix.SCRIPT_DIR})")
    args = parser.parse_args(argv)

    folder = find_game_folder(args.game_dir)
    if not args.address:
        parser.error(f"--address is needed: the fixed tmo.exe goes to every player, so it has to "
                     f"carry the address their clients connect to (your copy in {folder} "
                     f"is pointed at {copy_address(folder)})")
    common = ["--game-dir", str(folder), "--update-dir", args.update_dir, *(["--check"] if args.check else [])]

    results = []
    print("== confession scenes and gallery (confession_fix.py)")
    results.append(("confession scenes and gallery",
                    confession_fix.main([*common, "--scripts-dir", args.scripts_dir])))
    print("\n== the client: exam rankings page, おまけ button, 表情 photos, Epilogue, イベント中断, おまけ staff roll, あとがき (ranking_fix.py)")
    results.append(("the client",
                    ranking_fix.main([*common, "--address", args.address])))

    print()
    for name, code in results:
        print(f"  {'ok    ' if code == 0 else 'FAILED'}  {name}")
    return 1 if any(code for _, code in results) else 0


if __name__ == "__main__":
    sys.exit(main())
