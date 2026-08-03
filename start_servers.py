#!/usr/bin/env python3
"""Detach revival servers into a new session so IDE shells cannot reap them.

Arguments are handed to server/run_all.py untouched, so a public deployment is

    .venv/bin/python start_servers.py --advertise-ip 203.0.113.7

with the address players reach this machine at. See run_all.py for why that
cannot be worked out from the sockets.

Name the interpreter rather than relying on the shebang: on macOS that would
pick the system python3, which is built against LibreSSL and cannot start the
TLS listeners. stop_servers.py is run the same way.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "runtime" / "run_all.log"
PIDFILE = ROOT / "runtime" / "run_all.pid"
PORTS = (12000, 12010, 12011, 12012, 12020, 8011, 443, 50, 80, 35573, 25573, 25574, 25575)




def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_listeners() -> list[int]:
    """SIGTERM whatever is listening on our ports. Returns the pids signalled.

    Shared with stop_servers.py, which is this and a pidfile removal and nothing
    else: clearing the ports before a start and stopping the server are the same
    operation, so there is one port list and one way of killing rather than a
    second copy that can drift out of step.

    Ports rather than a process name, because a name match would also catch an
    editor with run_all.py open. Everything binds in one process, so one hit is
    normally the whole server; the rest of the list is what catches an instance
    that failed partway through binding.
    """
    killed: list[int] = []
    for port in PORTS:
        try:
            out = subprocess.check_output(
                ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            continue
        for line in out.split():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid in killed:          # the same process, holding another port
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
            killed.append(pid)
    return killed


def main(argv: list[str]) -> int:
    ROOT.joinpath("runtime").mkdir(parents=True, exist_ok=True)
    if PIDFILE.exists():
        try:
            old = int(PIDFILE.read_text().strip())
        except ValueError:
            old = 0
        if old and _pid_alive(old):
            print(f"already running pid={old}")
            return 0

    stop_listeners()
    time.sleep(0.5)

    log_f = open(LOG, "a", buffering=1)
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "server" / "run_all.py"), *argv],
        cwd=str(ROOT),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    PIDFILE.write_text(str(proc.pid))
    time.sleep(1.2)
    # poll(), not _pid_alive(): this one is our own child, and a child that has
    # exited but not been waited on is a zombie. A zombie still answers kill(pid, 0),
    # so the probe above would call a server that died on startup a live one --
    # which is what happens on a LibreSSL-backed Python, where run_all.py raises
    # before it binds anything. poll() reaps it and gives the real exit status.
    if proc.poll() is not None:
        print(f"failed to start (exit {proc.returncode}); log tail:")
        print(LOG.read_text()[-2000:])
        # Leaving the pidfile behind would point start_servers.py at a pid that is
        # not ours the moment the number is recycled; see scripts/stop_servers.sh.
        PIDFILE.unlink(missing_ok=True)
        return 1
    print(f"started pid={proc.pid}")
    print(LOG.read_text()[-1500:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
