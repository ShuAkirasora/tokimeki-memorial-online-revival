from __future__ import annotations

import asyncio
import json
from pathlib import Path

from common import ServiceConfig, ensure_runtime_dirs, write_packet_log
from state import LocalState


class WorldServer:
    def __init__(self, root: Path, config: ServiceConfig) -> None:
        self.root = root
        self.config = config
        runtime, self.packet_dir = ensure_runtime_dirs(root)
        self.state = LocalState(runtime / "revival.sqlite3")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        data = await reader.read(4096)
        write_packet_log(self.packet_dir, "world", "in", data)

        username = "local_user"
        x, y, z = 0.0, 0.0, 0.0
        try:
            msg = json.loads(data.decode("utf-8"))
            username = str(msg.get("username", username))
            if "move" in msg:
                move = msg["move"]
                x = float(move.get("x", x))
                y = float(move.get("y", y))
                z = float(move.get("z", z))
                self.state.update_position(username, x, y, z)
        except Exception:
            pass

        char_state = self.state.get_character(username)
        resp_obj = {
            "result": "ok",
            "scene": {"id": char_state["scene_id"], "name": "School Gate"},
            "spawn": {"x": char_state["x"], "y": char_state["y"], "z": char_state["z"]},
            "heartbeat_sec": 5,
            "stubs": {"npc_interaction": True, "quest": True, "economy": True},
        }
        resp = json.dumps(resp_obj, ensure_ascii=True).encode("utf-8")
        write_packet_log(self.packet_dir, "world", "out", resp)
        writer.write(resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        print(f"[world] served {peer}, user={username}")

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        print(f"[world] listening on {self.config.host}:{self.config.port}")
        return server
