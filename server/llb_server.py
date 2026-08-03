from __future__ import annotations

import asyncio
import struct
import subprocess
from pathlib import Path

from common import ServiceConfig, ensure_runtime_dirs, write_packet_log
from updater_server import mps_packet, parse_mps_packets

# The debug format strings embed a *group* id ("MsgSvResultLoginServer(0x0b00)");
# the wire id adds an offset, same as the updater's 0x6810 -> 0x6811.
#
# The decisive evidence is how the client fails: replying 0x0B01 with an empty
# body *crashes* it, which only happens if it recognised the id and ran the
# Result deserializer (0x8F1840, reads u32 + u16) against too few bytes. Replying
# 0x0B00 instead is read off the socket and silently dropped. .text has no
# comparison against these ids because dispatch goes through a lookup table.
MSG_QUERY_LOGIN_SERVER = 0x0B00
MSG_RESULT_LOGIN_SERVER = 0x0B01
MSG_ERROR_LOGIN_SERVER = 0x0B02

MSG_LOGIN_SERVER_LOGIN = 0x7000

# Between the packet type and the message parameters sits a 4-byte field.
#
# Measured with the tmo.exe probe on lock_parameter_input_buffer: replying
# ``PS=0008 PT=0b01`` + the 6 parameter bytes ``0100007f63e5`` made the client
# report ``id=010b sz=00000002 bf=63e5…`` — it took the *last* two bytes as the
# whole parameter block, i.e. paramSize = PS - 6 and the parameters start four
# bytes after PT. So a message carrying N parameter bytes needs PS = 6 + N.
#
# The field's meaning is still open (it is not a length: we sent 0100007f there
# and the client still used PS to size the block), so candidates are tried in
# order until the client acts on one.
PARAM_HEADER_CANDIDATES = (b"\x00\x00\x00\x00", b"\x00\x00\x00\x06")


def result_login_server_payload(ip: str, port: int, *, inet_order: bool = False) -> bytes:
    """Body of MsgSvResultLoginServer: u32 address + u16 port, 6 bytes.

    Confirmed from both directions:
      Output_…::serialize   (0x900180) writes [obj+4] via stream+0x28 (u32),
                                             [obj+8] via stream+0x2c (u16)
      Input_…::deserialize  (0x8F1840) reads  into [obj+4] via stream+0x24 (u32),
                                             into [obj+8] via stream+0x28 (u16)

    The address byte order is the open question. A server that stores
    inet_addr()'s result holds 0x0100007F for 127.0.0.1, which a big-endian
    stream emits as 01 00 00 7f (``inet_order=True``); writing the dotted-quad
    reading order 7f 00 00 01 instead makes the client dial 1.0.0.127.
    """
    octets = [int(part) for part in ip.split(".")]
    if inet_order:
        octets.reverse()
    return bytes(octets) + struct.pack(">H", port)


class LlbServer:
    """Login-lobby (LLB) observer/stub.

    Default host/port come from tmo.exe's config defaults at 0x406A40:
    ``tmollb.tokimekionline.com`` / ``221.116.3.90`` followed by the u16
    literals 0x8AF5 (35573) and 0x63E5 (25573).

    The real payload layout is still unknown, so this server's first job is to
    capture bytes: it holds the connection open, logs every frame, and answers
    ``type + 1`` so we can observe whether the client advances or retries.
    """

    def __init__(
        self,
        root: Path,
        config: ServiceConfig,
        *,
        reply: bool = True,
        login_ip: str = "127.0.0.1",
        login_port: int = 25573,
        resend_interval: float = 0.0,
        resend_count: int = 0,
    ) -> None:
        self.root = root
        self.config = config
        self.reply = reply
        self.login_ip = login_ip
        self.login_port = login_port
        self.resend_interval = resend_interval
        self.resend_count = resend_count
        # Alternate the address byte order per connection so a client retry
        # exercises the other encoding without needing another manual login.
        self.conn_seq = 0
        _, self.packet_dir = ensure_runtime_dirs(root)
        self.tag = f"llb{config.port}"

    def _recv_q(self, peer_port: int) -> int | None:
        """Bytes sitting unread in the *client's* kernel receive queue."""
        try:
            out = subprocess.run(
                ["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, timeout=5
            ).stdout
        except (subprocess.TimeoutExpired, OSError):
            return None
        for line in out.splitlines():
            cols = line.split()
            if len(cols) < 6:
                continue
            # local side of the client end, e.g. 127.0.0.1.62522
            if cols[3].endswith(f".{peer_port}") and str(self.config.port) in cols[4]:
                try:
                    return int(cols[1])
                except ValueError:
                    return None
        return None

    def _queues(self, peer_port: int, label: str) -> None:
        """Log kernel socket queues, to see which side data is sitting on."""
        try:
            out = subprocess.run(
                ["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, timeout=5
            ).stdout
        except (subprocess.TimeoutExpired, OSError):
            return
        for line in out.splitlines():
            if f".{peer_port} " in line or line.rstrip().endswith(f".{peer_port}"):
                print(f"[{self.tag}] netstat({label}) {' '.join(line.split())}")

    def _describe(self, msg_type: int) -> str:
        if msg_type == MSG_QUERY_LOGIN_SERVER:
            return "MsgClQueryLoginServer"
        if msg_type == MSG_LOGIN_SERVER_LOGIN:
            return "MsgClRequestLoginServerLogin"
        return "unknown"

    def _build_reply(self, msg_type: int) -> list[bytes]:
        if msg_type == MSG_QUERY_LOGIN_SERVER:
            # dotted-quad order was tried twice and the client never dialled;
            # inet_addr order is what a server storing inet_addr() would emit,
            # and the stream's u32 read runs it through ntohl.
            params = result_login_server_payload(self.login_ip, self.login_port, inet_order=True)
            print(
                f"[{self.tag}] -> MsgSvResultLoginServer(0x{MSG_RESULT_LOGIN_SERVER:04x}) "
                f"{self.login_ip}:{self.login_port} params={params.hex()}"
            )
            return [
                mps_packet(MSG_RESULT_LOGIN_SERVER, header + params)
                for header in PARAM_HEADER_CANDIDATES
            ]
        print(f"[{self.tag}] no reply implemented for 0x{msg_type:04x}")
        return []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self.conn_seq += 1
        print(f"[{self.tag}] ACCEPT peer={peer} (conn #{self.conn_seq})")
        write_packet_log(self.packet_dir, self.tag, "accept", b"")
        buf = b""
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=300.0)
                except asyncio.TimeoutError:
                    print(f"[{self.tag}] idle timeout peer={peer}")
                    break
                if not chunk:
                    print(f"[{self.tag}] EOF peer={peer}")
                    break
                write_packet_log(self.packet_dir, self.tag, "in", chunk)
                print(f"[{self.tag}] recv {len(chunk)}B: {chunk.hex()}")
                buf += chunk

                frames = parse_mps_packets(buf)
                if not frames:
                    print(f"[{self.tag}] no complete MPS frame yet (buffered {len(buf)}B)")
                    continue
                consumed = sum(4 + len(p) for _, p in frames)
                buf = buf[consumed:]

                for msg_type, payload in frames:
                    print(
                        f"[{self.tag}] frame type=0x{msg_type:04x} "
                        f"({self._describe(msg_type)}) payload={payload.hex() or '-'}"
                    )
                    if not self.reply:
                        continue
                    candidates = self._build_reply(msg_type)
                    if not candidates:
                        continue
                    peer_port = peer[1] if peer else 0
                    asyncio.create_task(self._send_candidates(writer, candidates, peer_port))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[{self.tag}] closed {peer}")

    async def _send_candidates(
        self, writer: asyncio.StreamWriter, candidates: list[bytes], peer_port: int
    ) -> None:
        """Try each framing candidate, pausing so the client can act on one.

        The client asks once per login click, so getting a single shot per manual
        attempt is the bottleneck. Sending the next candidate only after a pause
        keeps the good one first while still exercising the rest if it is wrong.
        """
        for index, resp in enumerate(candidates):
            if writer.is_closing():
                print(f"[{self.tag}] peer closed before candidate #{index}")
                return
            write_packet_log(self.packet_dir, self.tag, "out", resp)
            try:
                writer.write(resp)
                await writer.drain()
            except (ConnectionError, OSError) as exc:
                print(f"[{self.tag}] candidate #{index} write failed: {exc}")
                return
            print(f"[{self.tag}] sent candidate #{index} {len(resp)}B: {resp.hex()}")
            await self._confirm_read(peer_port, len(resp))
            await asyncio.sleep(3.0)

    async def _confirm_read(self, peer_port: int, nbytes: int) -> None:
        await asyncio.sleep(2.0)
        q = self._recv_q(peer_port)
        if q == 0:
            print(f"[{self.tag}] client consumed the {nbytes}B reply")
        else:
            print(f"[{self.tag}] reply still unread: peer Recv-Q={q}")

    async def _resend(self, writer: asyncio.StreamWriter, resp: bytes, peer_port: int) -> None:
        """Find out why the client never drains its receive queue.

        The reply reaches the client's kernel buffer (netstat shows Recv-Q=10) yet
        its recv keeps reporting no data. Grow the amount pending in steps: if the
        queue suddenly drains at some size, the client was waiting for a minimum
        byte count rather than being unable to read at all. Finally send FIN,
        which changes the socket's readable state.
        """
        pending = len(resp)
        for target in (64, 256, 1024, 4096):
            await asyncio.sleep(2.0)
            if writer.is_closing():
                print(f"[{self.tag}] probe: peer closed at pending={pending}")
                return
            q = self._recv_q(peer_port)
            print(f"[{self.tag}] probe: pending={pending} peer Recv-Q={q}")
            if q == 0:
                print(f"[{self.tag}] probe: client DRAINED queue at pending={pending}")
                return
            pad = target - pending
            if pad <= 0:
                continue
            try:
                writer.write(b"\x00" * pad)
                await writer.drain()
            except (ConnectionError, OSError) as exc:
                print(f"[{self.tag}] probe: write failed: {exc}")
                return
            pending = target
            print(f"[{self.tag}] probe: padded to {pending}B")

        await asyncio.sleep(2.0)
        print(f"[{self.tag}] probe: peer Recv-Q={self._recv_q(peer_port)} -> sending FIN")
        try:
            writer.write_eof()
        except (ConnectionError, OSError, NotImplementedError) as exc:
            print(f"[{self.tag}] probe: write_eof failed: {exc}")
            return
        await asyncio.sleep(2.0)
        print(f"[{self.tag}] probe: after FIN peer Recv-Q={self._recv_q(peer_port)}")

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        print(f"[{self.tag}] listening on {self.config.host}:{self.config.port}")
        return server
