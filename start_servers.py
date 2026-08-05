#!/usr/bin/env python3
"""Detach revival servers into a new session so IDE shells cannot reap them.

Arguments are handed to server/run_all.py untouched, so a public deployment is

    python3 start_servers.py --advertise-ip 203.0.113.7

with the address players reach this machine at. See run_all.py for why that
cannot be worked out from the sockets.

Whichever interpreter runs this file is the one run_all.py is started with, so
it has to be a Python with a real OpenSSL: the macOS system python3 is built
against LibreSSL and cannot start the TLS listeners. stop_servers.py is run
the same way.

Runs on Windows and on Linux as well. Three things below cannot be asked the
same way everywhere -- what holds a port, whether a pid is alive, and how to
detach the child -- and each is marked where it happens. Everything else,
including every path in this file, is what it is on all three.
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

WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")


def _pid_alive_windows(pid: int) -> bool:
    """Is that pid a live process? Asked without touching it.

    os.kill(pid, 0) is not this question on Windows. There are no signals, so
    CPython turns every value except the two console events into
    TerminateProcess(handle, sig) -- os.kill(pid, 0) would *kill* the server and
    hand it exit code 0. The POSIX probe is a live round here, so ask the
    process object instead: waiting zero milliseconds on a handle times out
    while the process runs and succeeds once it has exited.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x102

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Without these the default restype of c_int truncates a 64-bit HANDLE, and
    # CloseHandle is then called on a number that is not the handle we opened.
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
    )
    if not handle:
        # No such process, or one this account may not open. Either way there is
        # nothing here we could be about to start a second copy of.
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if WINDOWS:
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _run(argv: list[str]) -> str:
    """Output of a query command, or "" if it could not be asked.

    A failure to ask is not an error here: on a machine without lsof, or with
    netstat locked down, the answer is simply that nothing is known to hold the
    port, and the bind that follows is the real test.
    """
    try:
        return subprocess.check_output(
            argv,
            text=True,
            errors="replace",  # netstat's headers are localised, in the OEM codepage
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""


def _listener_pids_lsof(ports: tuple[int, ...]) -> list[int]:
    """lsof: it takes the filter itself and answers with pids and nothing else,
    so one call per port costs nothing and its output is the list."""
    pids: list[int] = []
    for port in ports:
        out = _run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
        pids += [int(tok) for tok in out.split() if tok.isdigit()]
    return pids


def _listener_pids_netstat(ports: tuple[int, ...]) -> list[int]:
    """Windows: netstat's -o adds the owning pid to each row, and it is on every
    Windows there is, which is why it is preferred to Get-NetTCPConnection -- no
    PowerShell in the path, nothing to install. It cannot filter by port, so it
    is asked once for everything and the ports are picked out here; asking it
    thirteen times would be thirteen full snapshots of the connection table."""
    wanted = {str(port) for port in ports}
    pids: list[int] = []
    # proto, local address, foreign address, state, pid -- and UDP rows, which
    # have no state and no business here, are dropped by the column count.
    for line in _run(["netstat", "-ano"]).splitlines():
        cols = line.split()
        if len(cols) < 5 or cols[0].upper() not in ("TCP", "TCPV6"):
            continue
        if cols[3].upper() != "LISTENING":
            continue
        # host:port, where host is 0.0.0.0, [::] or an interface address, so the
        # port is whatever follows the last colon.
        _, sep, tail = cols[1].rpartition(":")
        if sep and tail in wanted and cols[4].isdigit():
            pids.append(int(cols[4]))
    return pids


def _listening_inodes(ports: tuple[int, ...]) -> set[str] | None:
    """Linux: inodes of the sockets listening on ``ports``. None if /proc cannot say.

    /proc/net/tcp and its v6 twin are the table lsof, ss and netstat all read on
    this platform, so going to it directly is not a lesser answer -- it is the
    same one without the dependency. Both files are read because the socket
    holding a port need not be this server's: something bound to :: holds the
    port for v4 as well, on the usual setting of net.ipv6.bindv6only, and it
    appears in the second file only.

    The row names its socket only by inode; which process holds it is the next
    function's question, and nothing in the kernel's table answers it.
    """
    inodes: set[str] = set()
    answered = False
    for name in ("tcp", "tcp6"):
        try:
            rows = Path("/proc/net", name).read_text().splitlines()
        except OSError:
            continue  # no /proc, or this kernel has no IPv6 -- try the other
        answered = True
        # sl, local_address, rem_address, st, tx:rx, tr:when, retrnsmt, uid,
        # timeout, inode. Addresses and state are hex; 0A is TCP_LISTEN.
        for row in rows[1:]:
            cols = row.split()
            if len(cols) < 10 or cols[3] != "0A":
                continue
            _, _, port_hex = cols[1].rpartition(":")
            try:
                port = int(port_hex, 16)
            except ValueError:
                continue
            if port in ports:
                inodes.add(cols[9])
    return inodes if answered else None


def _pids_holding(inodes: set[str]) -> list[int]:
    """Linux: which processes have those sockets open.

    An fd in /proc/<pid>/fd is a symlink reading "socket:[<inode>]", and that
    scan is the whole of the inode-to-pid mapping -- it is what lsof does here
    too. Processes belonging to another user have an fd directory this account
    cannot read and are skipped, which is the blind spot lsof has without
    privileges as well, and never covers the server this script started.
    """
    wanted = {f"socket:[{inode}]" for inode in inodes}
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fds = list((entry / "fd").iterdir())
        except OSError:
            continue  # not ours to look at, or it exited while we were looking
        for fd in fds:
            try:
                held = os.readlink(fd)
            except OSError:
                continue  # closed between the listing and the read
            if held in wanted:
                pids.append(int(entry.name))
                break
    return pids


def _listener_pids(ports: tuple[int, ...]) -> list[int]:
    """Pids listening on any of ``ports``, however this platform is asked.

    Linux goes to /proc rather than to lsof because lsof is not on a Linux
    machine unless somebody installed it, and a stop that quietly finds nothing
    is worse than one that fails: the ports would stay held and the next start
    would lose the bind. lsof stays as the fallback for a host where /proc is
    not mounted.
    """
    if WINDOWS:
        return _listener_pids_netstat(ports)
    if LINUX:
        inodes = _listening_inodes(ports)
        if inodes is not None:
            return _pids_holding(inodes) if inodes else []
    return _listener_pids_lsof(ports)


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

    On Windows the same os.kill() call is TerminateProcess, and there is no
    gentler option: a detached process has no console for a Ctrl-Break to arrive
    at, and nothing else is deliverable. That is not the demotion it looks like
    -- nothing here installs a SIGTERM handler either, and an unhandled SIGTERM
    does not unwind a stack any more than TerminateProcess does. Both leave
    everything that matters on disk, because no service writes its state on the
    way out: characters.json is rewritten at each change, so what is there when
    the process stops is what it knew.
    """
    killed: list[int] = []
    for pid in _listener_pids(PORTS):
        if pid in killed:              # the same process, holding another port
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
        killed.append(pid)
    return killed


def _log_tail(nbytes: int) -> str:
    """The end of the log, read as what the server writes: UTF-8.

    Not the locale's encoding, which is what read_text() would pick. The log
    carries the Japanese the client sends and the server prints back -- a bell,
    a chosen line of dialogue -- and under a Windows locale that decodes as
    cp1252 or cp932 and raises before printing a single line of an otherwise
    healthy startup. run_all.py writes UTF-8 whatever it is attached to; this
    reads it back the same way, and replaces rather than raises on a truncated
    tail.
    """
    return LOG.read_text(encoding="utf-8", errors="replace")[-nbytes:]


def main(argv: list[str]) -> int:
    # Printing that tail is the last thing this does, and the same Japanese that
    # had to be decoded has to go back out again: a Windows console is on UTF-8
    # already, but a redirected stdout is on the locale's codepage and print()
    # would raise on the first line carrying any. Say UTF-8 rather than inherit
    # an answer.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

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

    # DETACHED_PROCESS is what start_new_session means on Windows: no console,
    # so a Ctrl-C in the shell that launched this -- or that shell's window being
    # closed -- does not travel to the server. CREATE_NEW_PROCESS_GROUP goes with
    # it so no console event aimed at the launcher's group can reach it either.
    # start_new_session is not an error there, it is simply ignored, which would
    # leave the server tied to the console it was started from.
    if WINDOWS:
        detach = {
            "creationflags": subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        }
    else:
        detach = {"start_new_session": True}

    log_f = open(LOG, "a", buffering=1, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "server" / "run_all.py"), *argv],
        cwd=str(ROOT),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        **detach,
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
        print(_log_tail(2000))
        # Leaving the pidfile behind would point start_servers.py at a pid that is
        # not ours the moment the number is recycled; see stop_servers.py.
        PIDFILE.unlink(missing_ok=True)
        return 1
    print(f"started pid={proc.pid}")
    print(_log_tail(1500))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
