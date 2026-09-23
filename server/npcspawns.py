"""The teachers and staff who stand on campus, and where each of them stands.

Every door into a club, a 同好会, a 多目的室 booking, a リーダー試験 and a
ドラマイベント is a right-click on one of these people. Until now the only way
to put one on a map was a developer command, which meant a player who did not
know the command never saw a teacher at all, and one who did lost them again the
moment the scene reloaded.

WHAT THE CLIENT DOES WITH THIS
------------------------------
A MsgSvNotifyCharacterAdd (0x480F) whose charaId is a roster reference -- the
category in the top 16 bits, the row in the bottom -- is not drawn from the
record it rides in. The client splits the id, looks the row up in the roster
that category names (2 = the named staff, 3 = the teachers), and takes both the
chibi it draws *and* the right-click menu it offers from that row. The ``looks``
in the entry are ignored for such an id. So one message, no scripts and no
patches, is the whole mechanism; see characters.add_entry for the entry layout.

WHAT IS RESTORED
----------------
``reference/npc_spawns.json`` holds 44 rows of (charaId, mapId, cell), and both
halves of each row are read out of the game's own data rather than chosen here:

* **which map** each of them belongs to is a field in the roster they come from:
  both rosters carry one, and both agree with the placement scripts row for row;
* **which cell** each of the 44 stands on is the coordinate their own placement
  script sets, one per person -- and the staff roster carries the cell as well,
  so its thirteen placed rows are a full (map, x, y) that matches their scripts
  exactly, with no exception.

That second source is what decides who is standing where. Thirteen scripts share
twelve people: one person has two of them, in two different rooms, because the
staff roster holds two records for him -- the same name twice, differing in the
room they name and in one byte of appearance. Matching on the whole coordinate
rather than on a name is what tells those two records apart, and it is why the
second room now gets the second record instead of a copy of the first.

Those 44 placement scripts are also the only ones in the game that never make
anybody visible -- they set a position and stop. That is why pushing them down
the chibi-spawn path draws nothing: they are the half of the job that was always
the server's.

WHAT IS INVENTED
----------------
Two things, both about presentation rather than about who stands where, and both
marked below: how they are turned to face, and *when* they are there. Nothing in
the tables or the scripts carries a timetable, so this end keeps them on their
cells for as long as the map exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import facing

SPAWNS_PATH = Path(__file__).resolve().parent.parent / "reference" / "npc_spawns.json"

# ── INVENTED — the facing all 44 of them are placed with: DOWN ────────────
# Their placement scripts set a cell and no direction: not one of the 44 carries
# a MAP_CHARA_DIRECTION, so there is no value here to recover and something has
# to be sent. DOWN is the same default a character gets anywhere else it is
# placed without a facing, which is the cheapest choice that is consistent with
# the rest of this end rather than a guess about each room's layout.
SPAWN_FACING = facing.DEFAULT
# ── end INVENTED (inventions:skip) ────────────────────────────────────────


class Spawn(NamedTuple):
    """One person standing somewhere: the id the client resolves, and the cell."""

    chara_id: int
    pos: tuple[int, int]


def _parse(key: str) -> int:
    """``"3:27"`` -> ``0x0003001B``, the way the client splits it back apart."""
    category, row = key.split(":")
    return (int(category) << 16) | int(row)


def _load() -> tuple[dict[int, list[Spawn]], dict[int, str]]:
    try:
        raw = json.loads(SPAWNS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[npc] no spawn table ({exc}); campus stands empty")
        return {}, {}
    out: dict[int, list[Spawn]] = {}
    stems: dict[int, str] = {}
    for row in raw.get("spawns", []):
        chara_id = _parse(row["chara"])
        out.setdefault(int(row["map"]), []).append(
            Spawn(chara_id, (int(row["x"]), int(row["y"])))
        )
        if row.get("stem"):
            stems[chara_id] = str(row["stem"])
    return out, stems


#: mapId -> who stands on it. ⚠️ The 44 rows are 44 distinct charaIds: the
#: one person who stands in two rooms has a roster record for each of them, so
#: each room names its own id rather than the same id twice.
#:
#: charaId -> the stem of that person's own placement script (``fte`` for
#: ``fte_s003``). ⭐ It is also the stem of the original server's scripts for
#: them, which is what `staffscripts` runs: the one person with two records has
#: two placement scripts under one stem (``kyt_s001`` / ``kyt_s002``), and the
#: thirteen classrooms of one 担任 are thirteen scripts under one stem.
BY_MAP, STEMS = _load()


def on_map(map_id: int) -> list[Spawn]:
    """Everybody who belongs on this map. Empty for the maps nobody staffs."""
    return BY_MAP.get(map_id, [])


def summary() -> str:
    return f"{sum(len(v) for v in BY_MAP.values())} spawns on {len(BY_MAP)} maps"
