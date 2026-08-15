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
import clubbattle
import mps_session
from auth_http_server import AuthHttpServer
from common import PACKET_LOG_ENV, ServiceConfig, packet_log_enabled, parse_ipv4
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
#   bind host     which interfaces to accept connections on.
#   advertise ip  what the login lookup and the two relay tickets *say*, i.e.
#                 where the client is told to connect for the next hop. The
#                 client dials that literally, so on a public deployment it has
#                 to be an address reachable from the client's side: leaving it
#                 at 127.0.0.1 sends every remote player back to their own
#                 machine, which is what limited this to one local player.
#
# The advertise address cannot be derived from the socket. Behind NAT the
# address a client must use is not one this host can see on any interface of
# its own, so it is configured: --advertise-ip, or TMO_ADVERTISE_IP.
#
# ⭐ The bind host is the other way round -- it follows from the advertise
# address, and so it is not a second thing to remember. Advertising 127.0.0.1
# tells every client to dial its own machine, so a socket open to the network
# under that setting serves nobody: whoever reached it would be sent home on the
# next hop. Listening wide is therefore not the generous default it looks like,
# it is surface with no one behind it. --bind overrides when the derivation is
# wrong for you.
LOOPBACK = "127.0.0.1"
DEFAULT_ADVERTISE_IP = LOOPBACK
ALL_INTERFACES = "0.0.0.0"


def derive_bind(advertise_ip: str) -> str:
    """Where to listen, given who we are telling clients to dial."""
    return LOOPBACK if advertise_ip.startswith("127.") else ALL_INTERFACES


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
        "--bind",
        default=os.environ.get("TMO_BIND"),
        type=parse_ipv4,
        metavar="IPV4",
        help=(
            "interface to listen on, for the ports a client dials. Derived from "
            "--advertise-ip when not given: 127.0.0.1 for a game on this machine, "
            "0.0.0.0 otherwise. 0.0.0.0 means every interface. The ports nothing "
            "but this project's own tests dial stay on 127.0.0.1 either way."
        ),
    )
    ap.add_argument(
        "--packet-log",
        action="store_true",
        default=packet_log_enabled(),
        help=(
            "write one JSON hex-dump per packet to runtime/packets/, for tracing "
            "the protocol. Off by default: it is a synchronous disk write on the "
            "event loop and one inode per packet, so it is for debugging, not for "
            "a server carrying players. Also settable with $TMO_PACKET_LOG."
        ),
    )
    ap.add_argument(
        "--registration-cert",
        default=os.environ.get("TMO_REGISTRATION_CERT"),
        metavar="PATH",
        help=(
            "serve the registration form (port 12013) over HTTPS with this "
            "certificate, so a browser reaches it without a warning and the "
            "personal key does not cross in the clear. A modern certificate for "
            "the name players type, e.g. a Let's Encrypt fullchain.pem -- separate "
            "from the RSA-1024 certificate the game client speaks to. Plain HTTP "
            "when not given. Also settable with $TMO_REGISTRATION_CERT."
        ),
    )
    ap.add_argument(
        "--registration-key",
        default=os.environ.get("TMO_REGISTRATION_KEY"),
        metavar="PATH",
        help=(
            "private key for --registration-cert when it is a separate file, as "
            "Let's Encrypt lays it out (privkey.pem). Omit if the key is in the "
            "certificate file. Also settable with $TMO_REGISTRATION_KEY."
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
    advertise_ip: str = DEFAULT_ADVERTISE_IP,
    adopt_code: str | None = None,
    bind: str | None = None,
    registration_cert: str | None = None,
    registration_key: str | None = None,
) -> None:
    root = Path(__file__).resolve().parents[1]
    # ⭐ Two groups, and the split is the whole of what keeps this small. OPEN is
    # what a client or a browser dials, and it goes wherever `bind` says. HOME is
    # everything only this project's own tests and probes have ever dialled --
    # every one of the six spare authentication ports, and the two stubs whose
    # protocol was never aligned -- and it stays on loopback no matter what bind
    # says, because there is no setting under which somebody else should reach
    # it. Forty-seven rounds of logs say which is which: the client has connected
    # to 443 and to nothing else in that family.
    open_host = bind or derive_bind(advertise_ip)
    print(f"[system] bind {open_host}, advertising {advertise_ip} to clients")
    # ⚠️ Say so, loudly, when this run is NOT the shipping behaviour. Both of
    # these exist for measuring with a paused client (see their constants) and
    # both are the kind of thing that is set once and then forgotten — at which
    # point a later session debugs a timeout that was moved on purpose, or reads
    # a fight that never timed out as evidence about the game. Printing them
    # only when they differ keeps a normal start quiet and makes a doctored one
    # impossible to miss. ⭐ It is also the only way to tell from the outside
    # whether a restart actually picked the variables up.
    # ⚠️ TURN_TIMEOUT_MS is compared against the STOCK constant, not against
    # itself: it is a knob now too, and a knob that is its own default can
    # never report anything. The deadline below stays relative to the effective
    # wire value, because what is worth shouting about there is the two of them
    # disagreeing.
    for name, value, default in (
        ("TMO_IDLE_S", mps_session.IDLE_TIMEOUT_S, 300.0),
        ("TMO_TURN_TIMEOUT_MS", clubbattle.TURN_TIMEOUT_MS,
         clubbattle.TURN_TIMEOUT_MS_STOCK),
        ("TMO_TURN_DEADLINE_S", clubbattle.TURN_DEADLINE_S,
         clubbattle.TURN_TIMEOUT_MS / 1000),
    ):
        if value != default:
            print(f"[system] ⚠️ {name}={value:g} (stock is {default:g}) -- "
                  f"measuring knob, NOT shipping behaviour")
    if open_host == LOOPBACK:
        print(
            "[system] loopback only -- a game on another machine reaches nothing."
            " Pass --advertise-ip <this machine's address> for that, which opens"
            " these too."
        )
    updater = UpdaterServer(root, ServiceConfig(host=open_host, port=12000))
    login = LoginServer(
        root, ServiceConfig(host=LOOPBACK, port=12010), advertise_ip=advertise_ip
    )
    world = WorldServer(root, ServiceConfig(host=LOOPBACK, port=12020))
    llb = LlbServer(
        root,
        ServiceConfig(host=open_host, port=LLB_QUERY_PORT),
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
        ServiceConfig(host=open_host, port=MPS_LOGIN_PORT),
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
        ServiceConfig(host=open_host, port=GAME_PORT),
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
        ServiceConfig(host=open_host, port=SCHOOL_PORT),
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
    auth_443 = AuthHttpServer(root, ServiceConfig(host=open_host, port=443), use_tls=True, **auth)
    auth_50 = AuthHttpServer(root, ServiceConfig(host=LOOPBACK, port=50), use_tls=True, **auth)
    auth_8011 = AuthHttpServer(root, ServiceConfig(host=LOOPBACK, port=8011), use_tls=True, **auth)
    auth_12011 = AuthHttpServer(
        root, ServiceConfig(host=LOOPBACK, port=12011), use_tls=True, **auth
    )
    auth_plain = AuthHttpServer(
        root, ServiceConfig(host=LOOPBACK, port=12012), use_tls=False, **auth
    )
    auth_80 = AuthHttpServer(root, ServiceConfig(host=LOOPBACK, port=80), use_tls=False, **auth)

    registration = RegistrationSite(
        root,
        ServiceConfig(host=open_host, port=REGISTRATION_PORT),
        directory=accountstore.konami_ids,
        table=accountstore.codes,
        advertise_ip=advertise_ip,
        throttle=limits,
        tls_cert=Path(registration_cert) if registration_cert else None,
        tls_key=Path(registration_key) if registration_key else None,
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
    # ⚠️⚠️ Low ports, and macOS does not follow the rule everybody knows. Measured
    # here as an ordinary user, and the same for 443, 50 and 80 in both address
    # families: binding 0.0.0.0:443 succeeds and binding 127.0.0.1:443 is refused
    # with EACCES. The wildcard is the *permitted* one, which is the opposite of
    # the intuition that a narrower bind asks for less. (Linux refuses both
    # without privileges; Windows refuses neither.)
    #
    # That lands on the one port the client actually dials, so 443 widens rather
    # than disappears, and says so in the log. A working authentication step is
    # worth more than a closed socket on a machine that is telling every client
    # to dial itself. ⭐ 50 and 80 do not widen: nothing has ever connected to
    # either of them, and opening a debug port to the network in order to keep a
    # debug port alive is the wrong way round.
    denied: list[int] = []
    for srv, may_widen in ((auth_443, True), (auth_50, False), (auth_80, False)):
        port, host = srv.config.port, srv.config.host
        try:
            servers.append(await srv.run())
            continue
        except OSError as exc:
            refused = exc
        widen = (
            may_widen
            and isinstance(refused, PermissionError)
            and host != ALL_INTERFACES
        )
        if widen:
            try:
                wider = AuthHttpServer(
                    root,
                    ServiceConfig(host=ALL_INTERFACES, port=port),
                    use_tls=srv.use_tls,
                    loopback_only=True,
                    **auth,
                )
                servers.append(await wider.run())
                print(
                    f"[authhttp] :{port} would not take {host} on this OS, so the"
                    f" socket is on {ALL_INTERFACES} and the service is not:"
                    " anything not from this machine is closed unread"
                )
                continue
            except OSError as exc:
                refused = exc
        print(f"[authhttp] skip :{port} ({refused})")
        if isinstance(refused, PermissionError):
            denied.append(port)

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
    # write_packet_log reads this from the environment, so a --packet-log on the
    # command line becomes the variable the rest of the process already watches.
    if _args.packet_log:
        os.environ[PACKET_LOG_ENV] = "1"
    asyncio.run(
        main(
            _args.advertise_ip,
            _args.adopt_code,
            _args.bind,
            _args.registration_cert,
            _args.registration_key,
        )
    )
