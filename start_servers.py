#!/usr/bin/env python3
"""Detach revival servers into a new session so IDE shells cannot reap them.

Arguments are handed to server/run_all.py untouched, so a public deployment is

    ./start_servers.py --advertise-ip 203.0.113.7

with the address players reach this machine at. See run_all.py for why that
cannot be worked out from the sockets.
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


def _free_ports() -> None:
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
                os.kill(int(line.strip()), signal.SIGTERM)
            except (ValueError, OSError):
                pass


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

    _free_ports()
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
    if not _pid_alive(proc.pid):
        print("failed to start; log tail:")
        print(LOG.read_text()[-2000:])
        return 1
    print(f"started pid={proc.pid}")
    print(LOG.read_text()[-1500:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
