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

import accounts
from auth_http_server import AuthHttpServer
from common import ServiceConfig, parse_ipv4
from konami_id import TokenDesk
from llb_server import LlbServer
from login_server import LoginServer
from mps_session import GAME_PORT, SCHOOL_PORT, MpsServer
from registration_site import RegistrationSite
from throttle import Throttle
from updater_server import UpdaterServer
from world_server import WorldServer

# Login-lobby ports from tmo.exe config defaults (0x406A40): 0x8AF5 / 0x63E5.
# 35573 answers the MsgClQueryLoginServer lookup; 25573 is the login server the
# client is then redirected to, which speaks the tagged MPS packet layer.
LLB_QUERY_PORT = 35573
MPS_LOGIN_PORT = 25573

# The 登録 form, which is ours and not the client's -- nothing dials it, a person
# opens it in a browser. Plain HTTP and out of the way of every port the client
# knows about; see registration_site.py for why it cannot share the auth service's
# TLS.
REGISTRATION_PORT = 12013

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
    ap.add_argument(
        "--adopt-code",
        metavar="CODE",
        help=(
            "attach this レジストレーションコード to account 1, for a server "
            "upgrading from before accounts existed. Use the code on the "
            "client's login screen, with the groups run together and no dashes. "
            "Ignored once account 1 has an owner, so leaving it on does nothing."
        ),
    )
    return ap.parse_args(argv)


async def main(
    advertise_ip: str = DEFAULT_ADVERTISE_IP, adopt_code: str | None = None
) -> None:
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
    # One set of accounts and one ticket desk across all three ports. Both have
    # to be shared: a character created on the school connection has to show up
    # in the list the game connection answers, and the authCode that names an
    # account is minted on one port and redeemed on the next.
    accountstore = accounts.AccountStore(root, adopt_code=adopt_code)
    tickets = accounts.TicketDesk()
    # Minted by whichever auth port the client dialled, redeemed on the login
    # port: one desk, or the token does not survive the hop between them.
    tokens = TokenDesk()
    # And one set of books for slowing things down: the registration form's
    # addresses, the day's fuse, and login.php's failure streaks. Six auth ports
    # answer the same client, so a streak counted per port would be six streaks.
    limits = Throttle(accountstore.codes.dir / "registrations.json")
    print(f"[system] accounts: {accountstore.summary()}")
    mps_login = MpsServer(
        root,
        ServiceConfig(host=BIND_HOST, port=MPS_LOGIN_PORT),
        "mpslogin",
        accountstore=accountstore,
        tickets=tickets,
        tokens=tokens,
        advertise_ip=advertise_ip,
    )
    # The game connection skips 4 bytes before the tag on everything it reads;
    # the login connection skips none. See MpsServer's packet().
    mps_game = MpsServer(
        root,
        ServiceConfig(host=BIND_HOST, port=GAME_PORT),
        "mpsgame",
        header_size=4,
        accountstore=accountstore,
        tickets=tickets,
        tokens=tokens,
        advertise_ip=advertise_ip,
    )
    # The school server the client hops to after picking a school. Assumed to
    # use the same 4-byte skip as 25574 until the logs say otherwise.
    mps_school = MpsServer(
        root,
        ServiceConfig(host=BIND_HOST, port=SCHOOL_PORT),
        "mpsschool",
        header_size=4,
        accountstore=accountstore,
        tickets=tickets,
        tokens=tokens,
        advertise_ip=advertise_ip,
    )
    # Client https URL uses default 443; sctrl port string is 0050 (=50).
    auth = {
        "advertise_ip": advertise_ip,
        "directory": accountstore.konami_ids,
        "tokens": tokens,
        "throttle": limits,
    }
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

    registration = RegistrationSite(
        root,
        ServiceConfig(host=BIND_HOST, port=REGISTRATION_PORT),
        directory=accountstore.konami_ids,
        table=accountstore.codes,
        advertise_ip=advertise_ip,
        throttle=limits,
    )

    servers = [
        await updater.run(),
        await login.run(),
        await world.run(),
        await auth_8011.run(),
        await auth_12011.run(),
        await auth_plain.run(),
        await registration.run(),
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
    _args = parse_args()
    asyncio.run(main(_args.advertise_ip, _args.adopt_code))
