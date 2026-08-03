#!/usr/bin/env python3
"""Stop the servers by port, and clear the pidfile behind them.

``kill "$(cat runtime/run_all.pid)"`` works too, and is what the README shows
because it needs no explanation. This is for when that is not enough: the
pidfile was lost, or was never written because run_all.py was started by hand.

The port list and the killing itself live in start_servers.py -- see
stop_listeners() there for why it goes by port and not by process name.
"""
from __future__ import annotations

from start_servers import PIDFILE, stop_listeners


def main() -> int:
    stopped = stop_listeners()
    if stopped:
        print("stopped: " + " ".join(str(pid) for pid in stopped))
    else:
        print("no server process is listening")

    # Always, even when nothing was running. A pidfile left pointing at a dead
    # process is harmless until the number is recycled, at which point
    # start_servers.py sees a live pid, reports "already running" and refuses to
    # start something that is not up.
    if PIDFILE.exists():
        PIDFILE.unlink()
        print(f"removed {PIDFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
