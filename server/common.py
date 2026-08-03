from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_runtime_dirs(root: Path) -> tuple[Path, Path]:
    runtime = root / "runtime"
    packet_dir = runtime / "packets"
    runtime.mkdir(parents=True, exist_ok=True)
    packet_dir.mkdir(parents=True, exist_ok=True)
    return runtime, packet_dir


def write_packet_log(packet_dir: Path, service: str, direction: str, data: bytes) -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = packet_dir / f"{ts}-{service}-{direction}.json"
    payload = {
        "time_utc": utc_now(),
        "service": service,
        "direction": direction,
        "size": len(data),
        "hex": data.hex(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def parse_ipv4(text: str) -> str:
    """Return ``text`` unchanged if it is a dotted-quad, else raise ValueError."""
    parts = text.split(".")
    if len(parts) != 4:
        raise ValueError(f"{text!r} is not an IPv4 address")
    for part in parts:
        if not part.isdigit() or not 0 <= int(part) <= 255:
            raise ValueError(f"{text!r} is not an IPv4 address")
    return text


def inet_u32(ip: str) -> int:
    """The address the way inet_addr() keeps it, so 127.0.0.1 is 0x0100007F.

    Both relay tickets the client reads (MsgSvOkLoginServerLogin and
    MsgSvOkSchoolSelect) hold the address in that order, and the LLB reply's
    ``inet_order=True`` path builds the same thing a byte at a time.
    """
    octets = [int(part) for part in parse_ipv4(ip).split(".")]
    value = 0
    for octet in reversed(octets):
        value = (value << 8) | octet
    return value


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int
