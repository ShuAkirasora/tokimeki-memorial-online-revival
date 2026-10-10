from __future__ import annotations

import asyncio
import struct
import zlib
from pathlib import Path, PurePosixPath

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


# ---------------------------------------------------------------------------
# What the updater can be told, read out of UpdateClient.exe itself.
#
# The session is the client's: it asks, one 0x6830 at a time, and every answer
# but the last is one 0x6831 record that it appends to a list. The last answer
# decides what happens to the list:
#
#   0x6822  "nothing to do"   -- the list is dropped and tmo.exe is started.
#   0x6832  "here is the set" -- u32, the version written back to update.ini
#                                once the set is applied; then the list is
#                                worked through, see below.
#
# An 0x6831 record is: name (NUL-terminated, relative to the game folder), u16
# operation, and for operation 0 three u32 -- the file's time, size and
# checksum -- then u16 source and a u16-counted blob. Operation 0 brings a file
# up to date; 1 deletes one, 2 and 5 rename one, 3 and 4 make and remove a
# folder. Source 2 means "fetch the blob's path from a download server", and the
# download servers are the (name, URL prefix) pairs 0x6821 carried before any of
# this started. Integers are big-endian, as everywhere on this wire.
#
# The client then makes two passes. The first skips every operation-0 file whose
# size and checksum already match, and fetches the rest over plain HTTP/1.x into
# a temporary folder: GET prefix+blob, "Range: bytes=0-", "Connection: close".
# A fetched file that is a cabinet is unpacked (it must hold exactly one file);
# anything else is used as it came. Size and checksum are then checked against
# the record -- a mismatch fails the update -- and the second pass copies each
# file into place and stamps it with the record's time. A failed fetch moves on
# to the next download server, round the list, before giving up.
#
# The checksum is CRC-32 with the usual table and the usual starting value, but
# WITHOUT the final inversion -- i.e. zlib.crc32(data) ^ 0xFFFFFFFF.
#
# ⭐ So a file only ever travels when the copy on the player's disk differs from
# the one here, and a second session with nothing new is a session of checks.
# ---------------------------------------------------------------------------

OP_UPDATE_FILE = 0
SOURCE_DOWNLOAD = 2

# Where the files to hand out live, laid out exactly as in the game folder
# (runtime/update/data/script/xyz.arc replaces <game>\data\script\xyz.arc).
# Empty or absent -- the shipped state -- and the session is the one this server
# has always answered: nothing to do.
UPDATE_DIRNAME = "update"

# ⚠️ INVENTED — the name of the one download server announced in 0x6821. The
# client keeps it next to the URL prefix and never puts it on the wire again;
# no recorded session survives to say what the real ones were called.
MIRROR_NAME = "main"


def checksum(data: bytes) -> int:
    """The updater's file checksum: CRC-32 without the closing inversion."""
    return zlib.crc32(data) ^ 0xFFFFFFFF


class UpdateFile:
    """One file to bring up to date: where it goes, what it must end up being."""

    def __init__(self, path: Path, rel: PurePosixPath) -> None:
        data = path.read_bytes()
        self.path = path
        self.url_path = rel.as_posix()
        # The client joins this onto BASE_DIR (".\\") with no translation.
        self.name = str(rel).replace("/", "\\")
        self.mtime = int(path.stat().st_mtime)
        self.size = len(data)
        self.crc = checksum(data)

    def record(self) -> bytes:
        blob = self.url_path.encode("ascii") + b"\x00"
        return (
            self.name.encode("ascii") + b"\x00"
            + struct.pack(">HIII", OP_UPDATE_FILE, self.mtime, self.size, self.crc)
            + struct.pack(">HH", SOURCE_DOWNLOAD, len(blob)) + blob
        )


def load_release(update_dir: Path) -> list[UpdateFile]:
    """Every file under the update folder, in a stable order."""
    if not update_dir.is_dir():
        return []
    files = []
    for path in sorted(p for p in update_dir.rglob("*") if p.is_file()):
        rel = PurePosixPath(path.relative_to(update_dir).as_posix())
        if any(part.startswith(".") for part in rel.parts):
            continue
        files.append(UpdateFile(path, rel))
    return files


class UpdaterServer:
    """The update check UpdateClient.exe makes before it starts tmo.exe.

    With nothing to hand out:
      C:0x6810 -> S:0x6811
      C:0x6820(version u32) -> S:0x6821(no download servers)
      C:0x6830 -> S:0x6831(an empty record the client never acts on)
      C:0x6830 -> S:0x6822 (nothing to do; client state=8)

    With files under runtime/update/:
      C:0x6820 -> S:0x6821(one download server: this port, over HTTP)
      C:0x6830 -> S:0x6831(one record per file) ... repeated
      C:0x6830 -> S:0x6832(the client's own version, so update.ini keeps it)
      then GETs on this same port for whatever the client found out of date.

    ⭐ The downloads come back to the port the check went to, told apart by
    their first bytes: an MPS frame never starts with "GET ". One port means a
    deployment that already lets the update check through needs nothing more.
    """

    MSG_CLIENT_HELLO = 0x6810
    MSG_CLIENT_VERSION = 0x6820
    MSG_GET_UPDATE_INFO = 0x6830

    MSG_SERVER_HELLO = 0x6811
    MSG_FILE_LIST = 0x6821
    MSG_UPDATE_DONE = 0x6822
    MSG_UPDATE_INFO_OK = 0x6831
    MSG_UPDATE_SET = 0x6832

    def __init__(self, root: Path, config: ServiceConfig, advertise_ip: str = "127.0.0.1") -> None:
        self.root = root
        self.config = config
        self.advertise_ip = advertise_ip
        runtime, self.packet_dir = ensure_runtime_dirs(root)
        self.update_dir = runtime / UPDATE_DIRNAME

    def mirror_url(self) -> str:
        return f"http://{self.advertise_ip}:{self.config.port}/"

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
        # empty name + u16 operation 1 ("delete"), which the client only ever
        # acts on after an 0x6832 -- this session answers 0x6822 instead.
        return b"\x00" + struct.pack(">H", mode)

    def _build_mirrors(self, release: list[UpdateFile]) -> bytes:
        if not release:
            return struct.pack(">H", 0)
        return (
            struct.pack(">H", 1)
            + MIRROR_NAME.encode("ascii") + b"\x00"
            + self.mirror_url().encode("ascii") + b"\x00"
        )

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            data = await self._read_available(reader, first_wait=8.0)
            if data.startswith((b"GET ", b"HEAD ")):
                await self._serve_http(peer, data, reader, writer)
                return
            await self._serve_check(peer, data, reader, writer)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[updater] closed {peer}")

    async def _serve_check(self, peer, data: bytes, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> None:
        # Read once per session, so a file dropped in mid-session cannot make
        # the list the client was promised disagree with the one it walks.
        release = load_release(self.update_dir)
        records = [f.record() for f in release]
        sent = 0
        version = 0
        # Two greetings, one 0x6830 per record and one to close: anything past
        # that is not this client.
        for round_idx in range(8 + len(records)):
            if round_idx:
                data = await self._read_available(reader, first_wait=4.0)
            write_packet_log(self.packet_dir, "updater", "in", data)
            if not data:
                print(f"[updater] {peer} round={round_idx} empty/timeout")
                return

            packets = parse_mps_packets(data)
            if not packets:
                print(f"[updater] {peer} round={round_idx} unframed recv={data.hex()}")
                return

            for msg_type, payload in packets:
                print(
                    f"[updater] {peer} round={round_idx} "
                    f"type=0x{msg_type:04x} payload={payload.hex() or '-'}"
                )
                final = False
                if msg_type == self.MSG_CLIENT_HELLO:
                    response = mps_packet(self.MSG_SERVER_HELLO)
                elif msg_type == self.MSG_CLIENT_VERSION:
                    if len(payload) >= 4:
                        (version,) = struct.unpack_from(">I", payload)
                    response = mps_packet(self.MSG_FILE_LIST, self._build_mirrors(release))
                    if release:
                        print(f"[updater] {peer} offering {len(release)} file(s) "
                              f"from {self.mirror_url()}")
                elif msg_type == self.MSG_GET_UPDATE_INFO and records:
                    if sent < len(records):
                        response = mps_packet(self.MSG_UPDATE_INFO_OK, records[sent])
                        sent += 1
                    else:
                        # The client's own version back: the set changes files,
                        # not what update.ini says the installation is.
                        response = mps_packet(self.MSG_UPDATE_SET, struct.pack(">I", version))
                        final = True
                elif msg_type == self.MSG_GET_UPDATE_INFO:
                    if sent == 0:
                        response = mps_packet(self.MSG_UPDATE_INFO_OK, self._build_update_info_ok())
                        sent = 1
                    else:
                        response = mps_packet(self.MSG_UPDATE_DONE)
                        final = True
                else:
                    print(f"[updater] unknown type 0x{msg_type:04x}, sending done")
                    response = mps_packet(self.MSG_UPDATE_DONE)
                    final = True

                write_packet_log(self.packet_dir, "updater", "out", response)
                writer.write(response)
                await writer.drain()
                if final:
                    what = "UPDATE_SET" if records and msg_type == self.MSG_GET_UPDATE_INFO else "UPDATE_DONE"
                    print(f"[updater] {peer} sent {what}")
                    return

    async def _serve_http(self, peer, data: bytes, reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter) -> None:
        """One GET for one file of the current release, then close.

        Only paths the release lists are served -- the folder is not browsable,
        and nothing outside it is reachable whatever the path says.
        """
        head, _, _ = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        method = parts[0]
        target = parts[1] if len(parts) > 1 else ""
        offset = 0
        for line in lines[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "range":
                spec = value.strip()
                if spec.startswith("bytes=") and spec.endswith("-") and spec[6:-1].isdigit():
                    offset = int(spec[6:-1])

        wanted = target.split("?", 1)[0].lstrip("/")
        found = next((f for f in load_release(self.update_dir) if f.url_path == wanted), None)
        if found is None:
            print(f"[updater] {peer} http {method} {target} -> 404")
            writer.write(b"HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return

        body = found.path.read_bytes()
        if 0 < offset < len(body):
            status = "206 Partial Content"
            extra = f"Content-Range: bytes {offset}-{len(body) - 1}/{len(body)}\r\n"
            body = body[offset:]
        else:
            status = "200 OK"
            extra = ""
        header = (
            f"HTTP/1.0 {status}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Content-Length: {len(body)}\r\n{extra}"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        print(f"[updater] {peer} http {method} /{wanted} -> {status.split()[0]} {len(body)} bytes")
        writer.write(header if method == "HEAD" else header + body)
        await writer.drain()

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        print(f"[updater] listening on {self.config.host}:{self.config.port}")
        return server
