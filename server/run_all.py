#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _utf8_output() -> None:
    """Say what encoding this server's output is in, rather than inheriting one.

    Half of what gets printed here is Japanese -- the name of a lesson, a line of
    dialogue the client stopped on, which bell just rang -- and none of it is
    optional decoration: it is the content of the messages being traced.

    Redirected into start_servers.py's log file, print() encodes with the
    locale's encoding, and on Windows that is cp1252 or cp932, neither of which
    can hold all of it. The first bell would then end the log in a
    UnicodeEncodeError rather than a line. Attached to a console instead, Python
    is already on UTF-8 and this changes nothing.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # already replaced with something that is not a text stream

from auth_http_server import AuthHttpServer
from characters import CharacterStore
from common import ServiceConfig, parse_ipv4
from llb_server import LlbServer
from login_server import LoginServer
from mps_session import GAME_PORT, SCHOOL_PORT, MpsServer
from updater_server import UpdaterServer
from world_server import WorldServer

# Login-lobby ports from tmo.exe config defaults (0x406A40): 0x8AF5 / 0x63E5.
# 35573 answers the MsgClQueryLoginServer lookup; 25573 is the login server the
# client is then redirected to, which speaks the tagged MPS packet layer.
LLB_QUERY_PORT = 35573
MPS_LOGIN_PORT = 25573

# Two different addresses, and they are not interchangeable.
#
#   BIND_HOST     which interfaces to accept connections on. 0.0.0.0 already,
#                 so a client on another machine can reach the sockets.
#   advertise ip  what the login lookup and the two relay tickets *say*, i.e.
#                 where the client is told to connect for the next hop. The
#                 client dials that literally, so on a public deployment it has
#                 to be an address reachable from the client's side: leaving it
#                 at 127.0.0.1 sends every remote player back to their own
#                 machine, which is what limited this to one local player.
#
# It cannot be derived from the socket. Behind NAT the address a client must
# use is not one this host can see on any interface of its own, so it is
# configured: --advertise-ip, or TMO_ADVERTISE_IP in the environment.
BIND_HOST = "0.0.0.0"
DEFAULT_ADVERTISE_IP = "127.0.0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run every revival service in one loop.")
    ap.add_argument(
        "--advertise-ip",
        default=os.environ.get("TMO_ADVERTISE_IP", DEFAULT_ADVERTISE_IP),
        type=parse_ipv4,
        metavar="IPV4",
        help=(
            "address clients are told to use for the login, game and school hops "
            f"(default: $TMO_ADVERTISE_IP or {DEFAULT_ADVERTISE_IP}). On a public "
            "deployment this is the address players reach this machine at."
        ),
    )
    return ap.parse_args(argv)


async def main(advertise_ip: str = DEFAULT_ADVERTISE_IP) -> None:
    root = Path(__file__).resolve().parents[1]
    print(f"[system] bind {BIND_HOST}, advertising {advertise_ip} to clients")
    updater = UpdaterServer(root, ServiceConfig(host=BIND_HOST, port=12000))
    login = LoginServer(
        root, ServiceConfig(host=BIND_HOST, port=12010), advertise_ip=advertise_ip
    )
    world = WorldServer(root, ServiceConfig(host=BIND_HOST, port=12020))
    llb = LlbServer(
        root,
        ServiceConfig(host=BIND_HOST, port=LLB_QUERY_PORT),
        login_ip=advertise_ip,
        login_port=MPS_LOGIN_PORT,
        resend_count=0,
    )
    # One account, one set of characters, whichever port is asked for the list.
    characters = CharacterStore(root / "runtime" / "characters.json")
    mps_login = MpsServer(
        root,
        ServiceConfig(host=BIND_HOST, port=MPS_LOGIN_PORT),
        "mpslogin",
        characters=characters,
        advertise_ip=advertise_ip,
    )
    # The game connection skips 4 bytes before the tag on everything it reads;
    # the login connection skips none. See MpsServer's packet().
    mps_game = MpsServer(
        root,
        ServiceConfig(host=BIND_HOST, port=GAME_PORT),
        "mpsgame",
        header_size=4,
        characters=characters,
        advertise_ip=advertise_ip,
    )
    # The school server the client hops to after picking a school. Assumed to
    # use the same 4-byte skip as 25574 until the logs say otherwise.
    mps_school = MpsServer(
        root,
        ServiceConfig(host=BIND_HOST, port=SCHOOL_PORT),
        "mpsschool",
        header_size=4,
        characters=characters,
        advertise_ip=advertise_ip,
    )
    # Client https URL uses default 443; sctrl port string is 0050 (=50).
    auth = {"advertise_ip": advertise_ip}
    auth_443 = AuthHttpServer(root, ServiceConfig(host=BIND_HOST, port=443), use_tls=True, **auth)
    auth_50 = AuthHttpServer(root, ServiceConfig(host=BIND_HOST, port=50), use_tls=True, **auth)
    auth_8011 = AuthHttpServer(root, ServiceConfig(host=BIND_HOST, port=8011), use_tls=True, **auth)
    auth_12011 = AuthHttpServer(
        root, ServiceConfig(host=BIND_HOST, port=12011), use_tls=True, **auth
    )
    auth_plain = AuthHttpServer(
        root, ServiceConfig(host=BIND_HOST, port=12012), use_tls=False, **auth
    )
    auth_80 = AuthHttpServer(root, ServiceConfig(host=BIND_HOST, port=80), use_tls=False, **auth)

    servers = [
        await updater.run(),
        await login.run(),
        await world.run(),
        await auth_8011.run(),
        await auth_12011.run(),
        await auth_plain.run(),
    ]
    servers.append(await llb.run())
    servers.append(await mps_login.run())
    servers.append(await mps_game.run())
    servers.append(await mps_school.run())
    denied: list[int] = []
    for srv in (auth_443, auth_50, auth_80):
        try:
            servers.append(await srv.run())
        except OSError as exc:
            print(f"[authhttp] skip :{srv.config.port} ({exc})")
            if isinstance(exc, PermissionError):
                denied.append(srv.config.port)

    # A refused low port is not fatal -- only the endpoint a given client dials
    # has to be up -- but on Linux it is refused for a reason with a one-line
    # answer, and whoever is reading this log is the one who can apply it. Said
    # only there: macOS has the same restriction and no such switch, Windows
    # never had the restriction, and a port refused for being taken rather than
    # for being privileged is a different problem with a different fix.
    if denied and sys.platform.startswith("linux") and os.geteuid() != 0:
        lowest = min(denied)
        print(
            f"[system] {', '.join(str(p) for p in denied)}: ports under 1024 need"
            " privileges on Linux. Either start this as root, or lower the bar"
            " for everyone once with `sudo sysctl -w"
            f" net.ipv4.ip_unprivileged_port_start={lowest}` (a file in"
            " /etc/sysctl.d/ keeps it across reboots)."
        )

    print("[system] all services started")

    try:
        await asyncio.gather(*(srv.serve_forever() for srv in servers))
    finally:
        for srv in servers:
            srv.close()
            await srv.wait_closed()


if __name__ == "__main__":
    _utf8_output()
    asyncio.run(main(parse_args().advertise_ip))
