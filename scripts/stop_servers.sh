#!/usr/bin/env bash
# Stop the servers by port, and clear the pidfile behind them.
#
# `kill "$(cat runtime/run_all.pid)"` works too, and is what the README shows because
# it needs no explanation. This is for when that is not enough: the pidfile was lost,
# or was never written because the process was started by hand.
#
# Ports rather than a process name, because a name match would also catch an editor
# with run_all.py open. Everything binds in one process, so any one hit is the whole
# server; the full list is here so that a partially-bound instance — one that failed
# after taking some ports — is still caught.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$ROOT/runtime/run_all.pid"
PORTS=(12000 12010 12011 12012 12020 8011 443 50 80 35573 25573 25574 25575)

ARGS=()
for port in "${PORTS[@]}"; do
    ARGS+=(-i "tcp:$port")
done

# lsof -t already reports each pid once, however many of the ports it holds.
PIDS="$(lsof -t "${ARGS[@]}" -sTCP:LISTEN || true)"

if [[ -z "$PIDS" ]]; then
    echo "no server process is listening"
else
    # SIGTERM: run_all.py closes its listeners and flushes on the way out.
    echo "$PIDS" | xargs kill
    echo "stopped: $PIDS"
fi

# Always, even when nothing was running. A pidfile left pointing at a dead process is
# harmless until the number is recycled, at which point start_servers.py sees a live
# pid, reports "already running" and refuses to start something that is not up.
if [[ -f "$PIDFILE" ]]; then
    rm -f "$PIDFILE"
    echo "removed $PIDFILE"
fi
