"""Driving the client's own scenario scripts.

Two ways in, and they are not the same subsystem. The 0x72xx handshake below
drives a script the client has *already* loaded; ``MsgSvNotifyDramaEventList``
(0xe003), at the bottom of this file, is the other of the only two code paths in
the whole client that open a ``Data/script/*.arc`` at all. Round 34 read both out
of the binary; only the first has ever been on the wire.

The 0x72xx subsystem
--------------------

**The client runs the VM; the server only arbitrates control flow.** Round 37
established this on the wire, overturning the reading rounds 28-32 were built
on. After ``NotifyScriptStart`` the server says nothing: the client plays the
script out of its own copy of the ``.ssb`` and calls home only when it reaches
something it is not allowed to decide::

    Sv 0x7200 RequestScriptReady   scriptId + cast
    Cl 0x7201 OkScriptReady        empty        (Ng is 0x7202, with a reason)
    Sv 0x7203 NotifyScriptStart    empty        <- the server goes quiet here
    Cl 0x721b NotifyScriptCommand  {ip, op}     <- "I am at this instruction"
    Sv 0x721a NotifyScriptCommandBranch  ip     <- only ever for OP_BR
    Cl 0x721c NotifyScriptCommandBegin   {ip, op}  <- "this one needs you"
    Sv 0x7204 NotifyScriptEnd      empty

Two of those the client *waits* on. ``OP_BR`` is answered with an ip; a
0x721c Begin is answered with whatever that command needs, which for
``INPUT_SELECT`` is the select query below. Everything else in 0x721b goes by
as a notification — the client has already moved on and answering only muddles
the two ip units (see ``wire_ip``).

Shapes, from the client's own deserialisers:

* ``0x7200`` (reader 0x8e8120) — u16 scriptId, then a counted ``pcInfo[]`` of
  75-byte entries, then a counted ``npcInfo[]`` of ``{u16 actorId, u16 npcId}``.
* ``0x721f`` (reader 0x8e9e60) — **u32** ip through the stream's +0x24 slot,
  then u16 op and u16 ctrl through +0x28. ⚠️ Server-pushed 0x721f is what
  rounds 30-32 spent themselves on and it does nothing useful; it is kept only
  for the manual ``/sc`` driver.

``ctrl`` is still a guess and so is whether ``npcInfo[]`` may be empty — the
``.ssb`` already declares its own cast. Both stay ``/sc`` arguments rather than
constants, because each wrong guess otherwise costs a whole client run
(handoff lesson 3).

The instruction list comes from ``runtime/scripts/<name>.json``, written by
``tools/sscops.py export``. That indirection is the publishing boundary: the
exporter reads the game's content (the decrypted ``.ssb`` tree and
``reference/idlist/script.txt``), this module reads neither. Missing file means
"no such script" rather than an error, the way mapgraph.py degrades.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "runtime" / "scripts"

MSG_SV_REQUEST_SCRIPT_READY = 0x7200
MSG_CL_OK_SCRIPT_READY = 0x7201
MSG_CL_NG_SCRIPT_READY = 0x7202
MSG_SV_NOTIFY_SCRIPT_START = 0x7203
MSG_SV_NOTIFY_SCRIPT_END = 0x7204
MSG_CL_NOTIFY_SCRIPT_COMMAND = 0x721B
MSG_CL_NOTIFY_SCRIPT_COMMAND_BEGIN = 0x721C
MSG_SV_NOTIFY_SCRIPT_COMMAND = 0x721F
MSG_SV_NOTIFY_SCRIPT_COMMAND_BRANCH = 0x721A

# The choice box. 0x7213 is what a 0x721c Begin{op=INPUT_SELECT} is waiting
# for; 0x7214 brings back which line was clicked, and 0x7223 arrives unasked
# when the highlight moves.
#
# ⚠️ 0x7215 MsgSvNotifyScriptCommandInput has the *identical* wire shape
# (reads=4+8) and is the wrong one — it is the free-text input box, and round
# 37 crashed the client with it (`page fault on read access to 00000018 at
# 0052DF77`). The two are twins that only their names tell apart. Do not
# substitute one for the other on the strength of the shape matching.
MSG_SV_QUERY_SCRIPT_COMMAND_SELECT = 0x7213
MSG_CL_RESULT_SCRIPT_COMMAND_SELECT = 0x7214
MSG_CL_NOTIFY_SCRIPT_COMMAND_SELECT_DEFAULT = 0x7223

# ⭐ What lets the client go again. A 0x721c Begin is a full stop, and answering
# what the command asked for is not enough to end it: after 0x7214 came back the
# client sat on the box doing nothing but heartbeats until this went out with
# the *same* {ip, op} the Begin carried. Same shape as the Begin (reads=4+2),
# which is the tell — it is the closing bracket, not a new instruction.
MSG_SV_NOTIFY_SCRIPT_COMMAND_END = 0x721D

# Where a script stops of its own accord. Anything past it is not ours to send.
OP_END = 0x9084

# The control-flow ops the client reports back while it plays a script. Round 37
# found out what 0x721b is for: the client runs the VM itself and only calls home
# when it reaches one of these. OP_BR is the one it actually *waits* on — it will
# sit there until the server names the next ip with 0x721a. The other three go by
# as notifications; the client keeps going without being told anything.
OP_JP = 0x9080
OP_BR = 0x9081
OP_JS = 0x9085

# The choice box, reported through 0x721c rather than 0x721b because the client
# stops dead on it. `tools/sscops.py export` carries its prompt and its options
# along in the JSON, so this end can name what it is answering.
OP_INPUT_SELECT = 0x7000

# How far past an OP_BR its fall-through lies. OP_BR is 8 bytes wide, and the
# client counts ip in file bytes, so "condition not taken" is br + 8. Verified
# live: the client sat on the OP_BR at file 1148, was told 1156, and moved on.
OP_BR_WIDTH = 8

# Talking to a chibi on the map. Found in round 37 by right-clicking the NPC
# that /npc had just put on the campus: the client opens a small menu, and
# picking the speech balloon sends 0x6304 with the npcId it was drawn from and
# the menu item's own number. None of the doors this project spent rounds 34-36
# on (0x4200, 0x5700, 0xe000) is involved — the conversation entrance lives in
# the same 0x63xx family as the spawn.
MSG_CL_REQUEST_NPC_MAP_OBJECT_EVENT = 0x6304
MSG_SV_OK_NPC_MAP_OBJECT_EVENT = 0x6305
MSG_SV_NG_NPC_MAP_OBJECT_EVENT = 0x6306

# The menu item the client sends for the speech balloon. Only this one has ever
# been seen; the others in that menu have not been clicked yet.
MENU_ITEM_TALK = 400

# What we answer 0x6304 with. The client takes this pair as a capture_npc_event
# key, reads that record's script id out of it, and asks us to start it — so
# this constant chooses which conversation the NPC has. 16:1 is
# 天宮日常会話c011 -> amm_c011.ssb, whose scriptId is 8206.
#
# It is one constant rather than a table because a table would have to be
# invented: what actually picks the event on a real server is progress state
# this end does not model. /nev changes it without a restart.
DEFAULT_NPC_EVENT = (16, 1)


def available() -> list[str]:
    """The scripts `tools/sscops.py export` has laid down, newest listing first."""
    if not SCRIPT_DIR.is_dir():
        return []
    return sorted(p.stem for p in SCRIPT_DIR.glob("*.json"))


def by_script_id(script_id: int) -> Script | None:
    """The exported script whose scriptId matches, or None.

    The client asks for events by number (MsgClRequestNpcEventStart carries the
    id it read out of the id table, not a name), so the lookup has to go the
    other way from `load`. Linear over a directory of a handful of files.
    """
    for name in available():
        found = load(name)
        if found is not None and found.script_id == script_id:
            return found
    return None


def npc_map_object_event_params(event: tuple[int, int], npc_id: int) -> bytes:
    """A MsgSvOkNpcMapObjectEvent body: eventId{categoryId, id} then npcId.

    Widths are the client's own (`reads=2+2+4`), and the npcId goes back as the
    four bytes it arrived in — the request prints it as one number, so this end
    does not need to know where the split inside it is.
    """
    return struct.pack(">HH", event[0], event[1]) + struct.pack(">I", npc_id)


class Script:
    """One exported script: its id, its cast, and its instruction stream."""

    def __init__(self, data: dict):
        self.file: str = data["file"]
        self.script_id: int | None = data.get("scriptId")
        self.actors: list[dict] = data.get("actors", [])
        # Byte offset of the code section inside the .ssb. Differs per file
        # (464 in amm_c011, 364 in amm_s001), so it has to be carried along.
        self.code_base: int = data.get("codeBase", 0)
        # (ip, op, name, operands) — ip is in u16 words from the start of the
        # code section, which is the unit the labels and jumps inside the file
        # agree on. The wire does NOT use this unit; see wire_ip below.
        self.instructions: list[tuple[int, int, str, str]] = [
            (ip, op, name, args) for ip, op, name, args in data["instructions"]
        ]
        self._by_ip = {ip: (ip, op, name, args)
                       for ip, op, name, args in self.instructions}
        # {OP_BR ip: where it goes when the condition holds}. JSON keys are
        # strings; local ip units throughout, same as `instructions`.
        self.branches: dict[int, int] = {
            int(ip): target for ip, target in data.get("branches", {}).items()
        }
        # {INPUT_SELECT ip: {"prompt": str, "options": [str, ...]}}
        self.selects: dict[int, dict] = {
            int(ip): entry for ip, entry in data.get("selects", {}).items()
        }

    def __len__(self) -> int:
        return len(self.instructions)

    # The client counts ip in bytes from the start of the *file*; we count in
    # u16 words from the start of the code section. Round 37 pinned this down by
    # taking the seven ips the client reported and reading the u16 at that file
    # offset: all seven matched the op it had named alongside them.
    def wire_ip(self, ip: int) -> int:
        return self.code_base + ip * 2

    def local_ip(self, wire: int) -> int:
        return (wire - self.code_base) // 2

    def at(self, ip: int) -> tuple[int, int, str, str] | None:
        """The instruction starting at a local ip, or None if ip is interior."""
        return self._by_ip.get(ip)

    def branch_roads(self, wire: int) -> tuple[int, int | None]:
        """Both ways out of the OP_BR at a wire ip: `(fall_through, taken)`.

        Taken is None when the exported script has no branch recorded there,
        which means either the ip is not an OP_BR or the JSON predates
        `branches` — either way the caller has only the fall-through to offer.
        """
        target = self.branches.get(self.local_ip(wire))
        return wire + OP_BR_WIDTH, None if target is None else self.wire_ip(target)


def load(name: str) -> Script | None:
    """A script by name (`amm_s001`, with or without `.ssb`), or None."""
    stem = name[:-4] if name.endswith(".ssb") else name
    path = SCRIPT_DIR / f"{stem}.json"
    try:
        return Script(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def ready_params(script_id: int, npc_infos: list[tuple[int, int]]) -> bytes:
    """A MsgSvRequestScriptReady body.

    ``pcInfo[]`` goes out empty. Its entries carry a whole character-creation
    block each and the player's own character is already in the scene, so there
    is nothing this end could put there that the client does not have; if it
    turns out to want one, that is what the Ng reason is for.
    """
    body = struct.pack(">HH", script_id, 0)
    body += struct.pack(">H", len(npc_infos))
    for actor_id, npc_id in npc_infos:
        body += struct.pack(">HH", actor_id, npc_id)
    return body


def command_params(ip: int, op: int, ctrl: int) -> bytes:
    """A MsgSvNotifyScriptCommand body: u32 ip, u16 op, u16 ctrl."""
    return struct.pack(">IHH", ip, op, ctrl)


def branch_params(wire_ip: int) -> bytes:
    """A MsgSvNotifyScriptCommandBranch body: just the ip to resume at.

    In the client's unit (file bytes), not ours.
    """
    return struct.pack(">I", wire_ip)


def select_params(select: int, timer_count: int) -> bytes:
    """A MsgSvQueryScriptCommandSelect body: u32 select, u64 timerCount.

    ⭐ **``select`` is one bit per option: set means the line is offered.**
    Measured, not deduced — the binary cannot say, because the handler is a
    weak_ptr the screen installs at run time and there is no static consumer to
    read. So it went out as 3 against a three-option box on the grounds that 3
    is right if the field is a count and ``0b011`` if it is a mask, and the
    client drew **two** lines: not a greyed-out third, no third at all.

    ⚠️ **The box is built once, when the Begin is answered.** A second query
    with a wider mask changes nothing on screen — 7 was sent to the same box
    and it stayed at two options. Whatever this field is going to be, it has to
    be right the first time.
    """
    return struct.pack(">IQ", select & 0xFFFFFFFF, timer_count)


def command_end_params(wire_ip: int, op: int) -> bytes:
    """A MsgSvNotifyScriptCommandEnd body: the Begin's own {ip, op}, echoed."""
    return struct.pack(">IH", wire_ip, op)


# `timerCount` is a duration in units unknown, and stayed unknown: the box does
# not close on its own within the minute anybody has watched it. 60000 is "a
# minute if these are milliseconds". 0 is avoided because "0 = no limit" and
# "0 = expire now" are equally plausible readings and one of them loses.
DEFAULT_SELECT_TIMER = 60000


def select_query(entry: dict | None) -> tuple[int, int]:
    """`(select, timerCount)` for one INPUT_SELECT, from its exported entry.

    Every option on: the script itself decides which lines a player may take,
    through the `OP_STR 0x1e80+k = 1` run it puts in front of the command, and
    this end has no state with which to second-guess it.
    """
    options = (entry or {}).get("options", [])
    return (1 << len(options)) - 1, DEFAULT_SELECT_TIMER


class Runner:
    """Which script one session is playing.

    It no longer walks anything: round 37 established that the client runs the
    VM and only asks the server which way to go at an OP_BR. What is left here
    is the loaded script, the cast we announced, and a count of how much the
    client has reported. `index`/`advance` survive for the manual `/sc` driver.
    """

    def __init__(self, script: Script, ctrl: int, npc_infos: list[tuple[int, int]]):
        self.script = script
        self.ctrl = ctrl
        self.npc_infos = npc_infos
        self.index = -1        # -1 = 0x7200 sent, still waiting for Ok
        self.started = False
        self.acks = 0          # how many 0x721b came back
        # Which line the player clicked, and how many OP_BR have gone by since.
        # See `resolve_branch` for what the pair is for.
        self.choice: int | None = None
        self.since_choice = 0
        # The 0x721c Begin the client is stopped on, as `(wire ip, op)`. Kept
        # because the release has to echo it back verbatim, and the client is
        # the only one who knows which instruction it stopped on.
        self.begun: tuple[int, int] | None = None

    def chose(self, result: int) -> None:
        """Remember a MsgClResultScriptCommandSelect and start counting."""
        self.choice = result
        self.since_choice = 0

    def resolve_branch(self, wire: int) -> tuple[int, str]:
        """Which ip to answer an OP_BR at `wire` with, and why, for the log.

        Every OP_BR in the game asks the server the same thing — "does the
        condition hold?" — and the server cannot generally answer it, because
        the condition is a script variable and the variables live in a VM this
        end does not run. So the standing answer is "no": fall through, walk the
        chain, and let the script find its own way. That is enough to see a
        conversation play.

        The one case this end *can* answer is the one right after a choice box.
        Scripts spell a selection out as one `OP_STR const; OP_EQ; OP_BR` per
        option, in option order — amm_c011 is the three at ip 207/218/229, all
        testing the same 0x029f — so once the client has told us the player
        clicked line k, the k-th OP_BR to come by is the one that holds.

        ⚠️ That last step is a *heuristic about how the scripts are written*,
        not a reading of the condition. It is right for the chain idiom and
        says nothing about an OP_BR that is not part of one, which is why the
        counter is armed only by `chose` and disarmed the moment it fires.
        """
        fall_through, taken = self.script.branch_roads(wire)
        if self.choice is None or taken is None:
            return fall_through, "fall-through"
        seen, self.since_choice = self.since_choice, self.since_choice + 1
        if seen != self.choice:
            return fall_through, f"fall-through (選択肢 {seen} ≠ {self.choice})"
        self.choice = None
        return taken, f"選択肢 {seen} の枝"

    @property
    def current(self) -> tuple[int, int, str, str] | None:
        if 0 <= self.index < len(self.script.instructions):
            return self.script.instructions[self.index]
        return None

    def advance(self) -> tuple[int, int, str, str] | None:
        """Step to the next instruction; None once the script is over."""
        self.index += 1
        return self.current

    def describe(self) -> str:
        here = self.current
        if here is None:
            return f"{self.script.file} (終了)"
        ip, op, name, args = here
        return f"{self.script.file} [{self.index + 1}/{len(self.script)}] ip={ip} {name} {args}"


# --------------------------------------------------------------------------
# The drama-event matching screen (0xe0xx) — the other way a .ssb gets opened
# --------------------------------------------------------------------------
#
# Round 35 sent MsgSvNotifyDramaEventList out of the blue and the client parsed
# every field of it correctly and then said, in its own words::
#
#     ▼Recv MsgSvNotifyDramaEventList, dramaEventList[1]={{dramaEventId=
#           {categoryId=0,id=7,}nPartyNum=0,flgSelectActor=0,orderOpen=0,
#           orderLast=0,maxPoint=0,flgAcquiredKeyword=0,}}
#           受信ハンドラが設定されていません          <- "no receive handler set"
#
# So the message is not a way *in*: it is one page of a screen that has to be
# open. Each message procedure holds one weak_ptr to a handler (the lookup is
# 0x935B14, the complaint is at 0x93593B); whoever opens the screen installs it,
# and until then the procedure drops the message on the floor. The whole 0xE0xx
# family is that screen — a party-matching lobby — and it opens like this::
#
#     Cl 0xe000 RequestDramaEventMatchingStart   npcId={categoryId, id}
#     Sv 0xe002 OkDramaEventMatchingStart        nDramaNum, nPartyNum
#     Sv 0xe003 NotifyDramaEventList             the events   (this file)
#     Sv 0xe004 NotifyDramaPartyList             the parties already forming
#     Cl 0xe00b RequestDramaPartyCreate → 0xe017 Ready → 0xe01a Start → …
#
# The same list has a second, cheaper door: MsgClQueryCharaMenuDramaEventList
# (0x4300) takes no arguments at all, and its answer carries records of exactly
# the same eight fields. `/drama` — which the client swallows rather than
# forwarding, see chat.CLIENT_RESERVED — is 「ドラマイベントリストの開閉」 in the
# game's own command table, so that is the likeliest thing behind it.
#
# ⚠️ **Six of the eight fields still only have names, not meanings.** They go
# out as zero, which is a guess: "zero works" is not yet known, and neither is
# "zero is ignored".
MSG_CL_REQUEST_DRAMA_EVENT_MATCHING_START = 0xE000
MSG_SV_NG_DRAMA_EVENT_MATCHING_START = 0xE001
MSG_SV_OK_DRAMA_EVENT_MATCHING_START = 0xE002
MSG_SV_NOTIFY_DRAMA_EVENT_LIST = 0xE003
MSG_SV_NOTIFY_DRAMA_PARTY_LIST = 0xE004

MSG_CL_QUERY_CHARA_MENU_DRAMA_EVENT_LIST = 0x4300
MSG_SV_RESULT_CHARA_MENU_DRAMA_EVENT_LIST = 0x4301
MSG_SV_NOTIFY_CHARA_MENU_DRAMA_EVENT_LIST = 0x4302

# Three more client-initiated doors, none of which has ever been knocked on.
# They are answered on sight because an unanswered one costs a whole client run
# to notice, and because each answer is two bytes:
#
#   0x4200 QueryDramaeventMatchingPossible  npcId{categoryId,id}
#       -> 0x4201 result, reason            both u8. The gate in front of the
#          matching screen — the client asks an NPC whether matching is on.
#   0x5700 RequestDramaEventStart           scriptId, actorId (both u16)
#       -> 0x5701 dramaEventId              u64. ⭐ The only message in the game
#          that names a scriptId *and* which role the player takes, so this is
#          the likeliest actual ignition for a drama.
#   0x5600 RequestNpcEventStart             npcEventId (u16)
#       -> 0x5601 (empty) / 0x5602 reason
#
# ⚠️ Every reply below is a first guess at what "yes" looks like. `result=1`
# and a made-up session id are the cheapest hypotheses, not measurements.
MSG_CL_QUERY_DRAMAEVENT_MATCHING_POSSIBLE = 0x4200
MSG_SV_RESULT_DRAMAEVENT_MATCHING_POSSIBLE = 0x4201
MSG_CL_REQUEST_NPC_EVENT_START = 0x5600
MSG_SV_OK_NPC_EVENT_START = 0x5601
MSG_CL_REQUEST_DRAMA_EVENT_START = 0x5700
MSG_SV_OK_DRAMA_EVENT_START = 0x5701
MSG_SV_NG_DRAMA_EVENT_START = 0x5702

# Both readers loop `count` times over a fixed array with the count field parked
# immediately after it, and neither clamps: one entry too many overwrites the
# loop bound itself. 0xe003's array is 32 entries of 0x20 at obj+8 with the
# count at obj+0x408; 0x4302's is 16, count at obj+0x208. Hence two limits, and
# hence they are enforced at this end.
DRAMA_EVENT_MAX = 32
CHARA_MENU_DRAMA_MAX = 16

DRAMA_EVENTS = Path(__file__).resolve().parent.parent / "runtime" / "drama_events.json"


def drama_events() -> list[dict]:
    """The `(genre, index)` keys `tools/dramaevents.py export` laid down.

    Same indirection as `available()` above and for the same reason: the keys
    live in the game's `drama_event.bin`, and `server/` does not read the game's
    content. Missing file means "none known", not an error — the keys are only
    needed to *name* an event, and `/de 0:7` works without them.
    """
    try:
        return json.loads(DRAMA_EVENTS.read_text(encoding="utf-8"))["events"]
    except (OSError, ValueError, KeyError):
        return []


def drama_event_record(genre: int, index: int) -> bytes:
    """One 20-byte entry: the key, then six named-but-unmeasured fields.

    ``nPartyNum, flgSelectActor, orderOpen, orderLast, maxPoint,
    flgAcquiredKeyword`` — the names are the client's own (dump 0x90C3A0), the
    zeros are ours.
    """
    return struct.pack(">HHHBHQBH", genre, index, 0, 0, 0, 0, 0, 0)


def drama_event_list_params(keys: list[tuple[int, int]], limit: int = DRAMA_EVENT_MAX) -> bytes:
    """A MsgSvNotifyDramaEventList / …CharaMenu… body from `(genre, index)` pairs."""
    kept = keys[:limit]
    return struct.pack(">H", len(kept)) + b"".join(
        drama_event_record(genre, index) for genre, index in kept
    )


def matching_start_params(n_drama: int, n_party: int) -> bytes:
    """MsgSvOkDramaEventMatchingStart: `nDramaNum`, `nPartyNum` (dump 0x90C230).

    Read as "how many of each are about to arrive", because the two lists that
    follow are exactly those two counts. That reading is untested — if the
    client instead treats them as capacities, or ignores them, the logs will
    say so before anything else does.
    """
    return struct.pack(">HH", n_drama, n_party)
