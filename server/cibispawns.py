"""Where the five 恋愛候補生 stand, decided the way the original server did.

Until now a player saw a candidate on campus only after somebody typed the
developer command that pushes her placement key, and lost her again on the
next warp. The original had no such command: every lobby load, the server ran
each candidate's own ちびキャラ管理 script -- one of the 95 server-side GS3
scripts in the game data -- and that script decided whether to push a
placement key for *this* map. This module runs the same scripts, on the same
occasion, with the same inputs.

WHAT THE SCRIPT DECIDES
-----------------------
``<stem>_s101`` (天宮 amm, 春日 ksg, 弥生 yyi, 桜井 skr, 犬飼 ink) reads five
things and nothing else:

* her 登場 flag -- not on stage, nothing to place;
* the five letter flags -- while *anybody's* letter is waiting in the
  locker, nobody stands on campus;
* which letter event is running -- same, while one is;
* her 進行度, on the script's own ruler (+2);
* which map the client is loading.

Then a chain of (進行度, map) doors, one per spot: the door that matches
calls her placement key, and the client's copy of that key's script carries
the cell. No door matches -> she is not on this map, which is the ordinary
case, since each spot is on exactly one map. The 26 classroom placement
scripts every candidate also has are called by nothing in the corpus -- no
GS3 script and no client script names them -- so they stay unused here.

WHAT IS INVENTED
----------------
One thing, and it is a reading rather than a number. In all five scripts an
``OP_END`` sits after the third door, so the doors for 進行度 3 onwards can
never be reached -- they are the only unreachable code in all 95 server
scripts, and the client's 日常会話 scripts for those same stages choose
backgrounds by the very cells those doors would put her on. This end treats
that ``OP_END`` as the defect it looks like and walks the doors behind it
when the ones in front placed nobody; the knob below turns that off, leaving
the script exactly as written. The keys themselves come from the script
either way.
"""

from __future__ import annotations

import struct
from typing import NamedTuple

import gs3vm
import romance

#: The id the placement message names her by: category 1 is `capture_npc`, the
#: candidates' own roster, and the row is her index in it. The client answers a
#: right-click on her with the same pair (1:2 for 弥生, round 139), so this is
#: what it expects to see, not a value that merely passes.
NPC_CATEGORY_CAPTURE = 1

#: Her ちびキャラ管理 script, by candidate. ⚠️ Checked against the keys the
#: script calls: each must lie in her block of `cibi_control_script`.
SCRIPT_STEMS = {"天宮": "amm", "春日": "ksg", "弥生": "yyi", "桜井": "skr", "犬飼": "ink"}

# ── INVENTED — design: the doors the script cannot reach are walked anyway ───
# Every `_s101` has an OP_END after its third (進行度, map) door, which makes
# the doors for 進行度 3..9 dead code -- the only dead code in the 95 server
# scripts. With this on, a run that placed nobody continues past that OP_END
# with its registers intact, so the remaining doors get their turn. Off means
# the script as written: a candidate leaves campus after her third main event.
HONOUR_DEAD_GATES = True
# ── end INVENTED (inventions:skip) ───────────────────────────────────────────


class Spawn(NamedTuple):
    """One placement the script asked for."""

    name: str
    npc_id: tuple[int, int]     # what the 0x6300 names her by
    event: tuple[int, int]      # the cibi_control_script key it pushes
    dead: bool                  # reached only because HONOUR_DEAD_GATES


def cells(love: romance.Romance, map_id: int) -> dict:
    """Everything a `_s101` reads: her save cells plus the map being loaded.

    The map goes in the same engine-argument slot the menu scripts read a
    menu item from -- the one cell the engine, not the save, supplies.
    """
    return {**love.data_cells(), ("CTX", (romance.CTX_ENGINE_ARG, 0)): map_id}


def dead_start(script: gs3vm.Script) -> int | None:
    """The first instruction nothing can reach, or None if the script has none.

    Reachability follows every jump, both arms of a branch and every label, so
    the answer for a `_s101` is the instruction after its mid-script OP_END.
    """
    reachable = set(gs3vm._reachable(script, 0))
    for label in script.labels:
        index = script.index.get(label)
        if index is not None:
            reachable |= gs3vm._reachable(script, index)
    for index in range(len(script.code)):
        if index not in reachable:
            return index
    return None


def on_map(love: romance.Romance, map_id: int) -> tuple[list[Spawn], list[str]]:
    """Who the scripts put on this map, and what to log about it.

    Only the candidates on stage are asked -- the script would refuse the
    others in its first line anyway, and skipping them saves loading it.
    Every failure is a note, never an exception: a lobby load with a broken
    placement script is a lobby without that candidate, not a black screen.
    """
    spawns: list[Spawn] = []
    notes: list[str] = []
    for name in love.on_stage():
        script_name = f"{SCRIPT_STEMS[name]}_s101"
        script = gs3vm.load(script_name)
        if script is None:
            notes.append(f"{script_name}: not exported on this machine, {name} stays off campus")
            continue
        machine = gs3vm.Machine(script, cells(love, map_id))
        dead = False
        try:
            result = machine.run()
            if not result.events and HONOUR_DEAD_GATES:
                start = dead_start(script)
                if start is not None:
                    machine.run(start)
                    dead = bool(result.events)
        except (gs3vm.UnknownCell, gs3vm.UnsupportedOp, gs3vm.Runaway) as exc:
            notes.append(f"{script_name}: {exc}; {name} stays off campus")
            continue
        who = romance.CANDIDATES[name]
        for category, index in result.events:
            if category != romance.CIBI_EVENT_CATEGORY or not who.base <= index < who.base + who.spots:
                notes.append(f"{script_name}: called {category}:{index}, outside {name}'s block; sent anyway")
            spawns.append(Spawn(name, (NPC_CATEGORY_CAPTURE, romance.candidate_index(name)),
                                (category, index), dead))
    return spawns, notes


def pack(spawn: Spawn) -> bytes:
    """The 0x6300 body: npcId then eventId, two u16 pairs."""
    return struct.pack(">HHHH", *spawn.npc_id, *spawn.event)


def describe(spawn: Spawn) -> str:
    key = f"{spawn.event[0]}:{spawn.event[1]}"
    return f"{spawn.name}={key}" + ("(dead gate)" if spawn.dead else "")
