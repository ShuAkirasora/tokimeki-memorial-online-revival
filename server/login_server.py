from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

from common import ServiceConfig, ensure_runtime_dirs, utc_now, write_packet_log
from state import LocalState


class LoginServer:
    def __init__(
        self, root: Path, config: ServiceConfig, *, advertise_ip: str = "127.0.0.1"
    ) -> None:
        self.root = root
        self.config = config
        self.advertise_ip = advertise_ip
        runtime, self.packet_dir = ensure_runtime_dirs(root)
        self.state = LocalState(runtime / "revival.sqlite3")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        data = await reader.read(4096)
        write_packet_log(self.packet_dir, "login", "in", data)

        username = "local_user"
        try:
            msg = json.loads(data.decode("utf-8"))
            username = str(msg.get("username", username))
        except Exception:
            pass

        token = secrets.token_hex(16)
        self.state.upsert_login(username=username, token=token, login_utc=utc_now())
        char_state = self.state.get_character(username)

        resp_obj = {
            "result": "ok",
            "session_token": token,
            "world_host": self.advertise_ip,
            "world_port": 12020,
            "character": {"name": username, **char_state},
        }
        resp = json.dumps(resp_obj, ensure_ascii=True).encode("utf-8")
        write_packet_log(self.packet_dir, "login", "out", resp)
        writer.write(resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        print(f"[login] served {peer}, user={username}")

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        print(f"[login] listening on {self.config.host}:{self.config.port}")
        return server
