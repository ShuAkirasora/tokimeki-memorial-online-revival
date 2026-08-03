from __future__ import annotations

import asyncio
import struct
from pathlib import Path

from common import ServiceConfig, ensure_runtime_dirs, write_packet_log


def mps_packet(msg_type: int, payload: bytes = b"") -> bytes:
    """Build a MassplayerSystem packet: PS(2) PT(2) PD... (big-endian).

    PS = total_size - 2, matching MultiTerm MPS framing used by TMO.
    """
    body = struct.pack(">H", msg_type & 0xFFFF) + payload
    total = 2 + len(body)
    return struct.pack(">H", total - 2) + body


def parse_mps_packets(data: bytes) -> list[tuple[int, bytes]]:
    packets: list[tuple[int, bytes]] = []
    off = 0
    while off + 4 <= len(data):
        ps = struct.unpack_from(">H", data, off)[0]
        total = ps + 2
        if total < 4 or off + total > len(data):
            break
        msg_type = struct.unpack_from(">H", data, off + 2)[0]
        payload = data[off + 4 : off + total]
        packets.append((msg_type, payload))
        off += total
    return packets


class UpdaterServer:
    """Local Multiterm/MPS updater stub for UpdateClient.exe.

    Observed flow:
      C:0x6810 -> S:0x6811
      C:0x6820(version u32) -> S:0x6821(count=0)
      C:0x6830 -> S:0x6831(update info ok, mode=1)
      C:0x6830 -> S:0x6822 (complete; client state=8)
    """

    MSG_CLIENT_HELLO = 0x6810
    MSG_CLIENT_VERSION = 0x6820
    MSG_GET_UPDATE_INFO = 0x6830

    MSG_SERVER_HELLO = 0x6811
    MSG_FILE_LIST = 0x6821
    MSG_UPDATE_DONE = 0x6822
    MSG_UPDATE_INFO_OK = 0x6831

    def __init__(self, root: Path, config: ServiceConfig) -> None:
        self.root = root
        self.config = config
        _, self.packet_dir = ensure_runtime_dirs(root)

    async def _read_available(self, reader: asyncio.StreamReader, first_wait: float = 8.0) -> bytes:
        chunks: list[bytes] = []
        try:
            first = await asyncio.wait_for(reader.read(65536), timeout=first_wait)
        except asyncio.TimeoutError:
            return b""
        if not first:
            return b""
        chunks.append(first)
        while True:
            try:
                more = await asyncio.wait_for(reader.read(65536), timeout=0.4)
            except asyncio.TimeoutError:
                break
            if not more:
                break
            chunks.append(more)
            if sum(len(c) for c in chunks) >= 1024 * 1024:
                break
        return b"".join(chunks)

    def _build_update_info_ok(self, mode: int = 1) -> bytes:
        # null-terminated string + BE uint16 mode (1/3/4 => accept, no file list)
        return b"\x00" + struct.pack(">H", mode)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        update_info_replies = 0
        try:
            for round_idx in range(8):
                data = await self._read_available(reader, first_wait=8.0 if round_idx == 0 else 4.0)
                write_packet_log(self.packet_dir, "updater", "in", data)
                if not data:
                    print(f"[updater] {peer} round={round_idx} empty/timeout")
                    break

                packets = parse_mps_packets(data)
                if not packets:
                    print(f"[updater] {peer} round={round_idx} unframed recv={data.hex()}")
                    break

                for msg_type, payload in packets:
                    print(
                        f"[updater] {peer} round={round_idx} "
                        f"type=0x{msg_type:04x} payload={payload.hex() or '-'}"
                    )
                    responses: list[bytes] = []
                    if msg_type == self.MSG_CLIENT_HELLO:
                        responses = [mps_packet(self.MSG_SERVER_HELLO)]
                    elif msg_type == self.MSG_CLIENT_VERSION:
                        # uint16 count=0 => no patch files; client will send 0x6830
                        responses = [mps_packet(self.MSG_FILE_LIST, struct.pack(">H", 0))]
                    elif msg_type == self.MSG_GET_UPDATE_INFO:
                        update_info_replies += 1
                        if update_info_replies == 1:
                            responses = [
                                mps_packet(
                                    self.MSG_UPDATE_INFO_OK,
                                    self._build_update_info_ok(mode=1),
                                )
                            ]
                        else:
                            # Second get-info after OK => session complete
                            responses = [mps_packet(self.MSG_UPDATE_DONE)]
                    else:
                        print(f"[updater] unknown type 0x{msg_type:04x}, sending done")
                        responses = [mps_packet(self.MSG_UPDATE_DONE)]

                    for resp in responses:
                        write_packet_log(self.packet_dir, "updater", "out", resp)
                        writer.write(resp)
                    await writer.drain()

                    if any(
                        parse_mps_packets(r) and parse_mps_packets(r)[0][0] == self.MSG_UPDATE_DONE
                        for r in responses
                    ):
                        print(f"[updater] {peer} sent UPDATE_DONE")
                        return
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[updater] closed {peer}")

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        print(f"[updater] listening on {self.config.host}:{self.config.port}")
        return server
