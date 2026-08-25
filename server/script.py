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

⭐ **``npcInfo[]`` may be empty.** Measured, and it used to be the open half of
this paragraph: the same NPC conversation was played twice, once with the cast
announced from an export and once with nothing announced at all, and the client
answered ``OkScriptReady`` and ran to ``OP_END`` both times. The ``.ssb``
declares its own actors and that is enough for it. ``ctrl`` is still a guess,
and stays a ``/sc`` argument rather than a constant, because a wrong guess
costs a whole client run (an earlier lesson).

Two sources, and the difference between them is the whole shape of this module
--------------------------------------------------------------------------

⭐ **One field of a script cannot be watched off the wire: ``branches``.** The
run above pinned the rest down as dispensable — the id arrives from the client,
the cast can be empty, the instruction list is only ever printed, and a select
needs no option count (see ``select_params``). Without branch targets a scene
still plays through to its own ``OP_END`` and a choice box is still drawn and
answered; what is lost is the answer *mattering*, because every ``OP_BR`` then
falls through. A branch target lives in the instruction's operands, and
operands never go on the wire, so it is the one thing no amount of watching
recovers.

So it ships, in ``reference/branches.json``:

* Keyed by scriptId, because that is all the client ever names — a conversation
  arrives as ``MsgClRequestNpcEventStart`` carrying an id it read out of its own
  tables, with no filename anywhere.
* Two integers per branch, plus each script's ``codeBase`` so that ips can be
  converted at all (see ``wire_ip``), and nothing else. No text, no options, no
  cast, no instruction stream.
* Only the branches this end can actually answer: the run of ``OP_BR`` that
  follows a choice box, one per option (see ``Runner.resolve_branch``). Every
  other branch in the game tests a script variable, which this end always
  answers "no" to, and a "no" needs no target — it is the reported ip plus
  ``OP_BR_WIDTH``. 5125 entries survive that cut out of 15586 branches.
⚠️ Round 167 shipped a second class here, ``gates``, and round 167 took it
back out; the episode is worth the paragraph. One ``OP_BR`` per
``<キャラ>_e011`` tests a player-data field that the choice box's own branch
wrote a few dozen ips earlier, so "the condition holds" and "the player picked
option 0" looked like one statement — and answering it "yes" does play the
confession scene the letter is inviting you to, measured on a real client.

⚠️⚠️ **But that is a guess about what the original server answered, not a
reading of it.** The client does not evaluate the condition; it *asks*. So the
arithmetic in the script is what the author meant the condition to say, and
never what the server said back. And the game ships that same confession twice
— once here as a ``BGNPC`` cutscene, once as ``<キャラ>:20`` / ``*_o011`` with
the same 92 lines and 桜井 as a real ``NPC`` standing in the room — which is
what an invitation followed by a trip to the 生徒会室 looks like. Answering
"yes" collapses the two into one and fires a route's climax for a character the
player has never met. So the standing "no" is back, and the confession waits
for its own entrance to be found.

``runtime/scripts/<name>.json``, written by ``the script exporter``, is the
other source and is *not* shipped: it carries the instruction stream, the cast
and a choice box's own prompt and option text, all of it read straight out of
the game's content. That file is for driving a script by name from ``/sc``
while working on this end. Both sources are optional in the same way
mapgraph.py's graph is — missing means "nothing known", never an error.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "runtime" / "scripts"
BRANCH_PATH = Path(__file__).resolve().parent.parent / "reference" / "branches.json"


def _load_branches() -> dict[int, dict]:
    """``{scriptId: {"codeBase": int, "branches": {ip: target}}}``, ips local.

    Silent when the file is simply absent, unlike mapgraph.py's loader: a server
    with no branch table answers every branch with its fall-through, which is
    exactly what this server did before the table existed. Nothing is unchecked
    and nothing is refused — choices just stop having consequences, and the
    branch log says ``fall-through`` on every line, which is the same diagnostic
    printed in longer form.
    """
    try:
        raw = json.loads(BRANCH_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        int(script_id): {
            "codeBase": entry["codeBase"],
            "branches": {int(ip): target
                         for ip, target in entry["branches"].items()},
        }
        for script_id, entry in raw.items()
    }


BRANCHES = _load_branches()

# {scriptId: {local ip: local target}} — branches answered "yes" no matter what,
# set from `/scb` and empty on every start, so the factory answer is the one the
# shipped table gives and a forced answer never outlives the session that typed
# it. It exists because the standing "no" of `Runner.resolve_branch` is not only
# a shrug: for a gate the script itself decides (round 167 found one, the
# `*_e011` letter gating its own confession scene) the standing answer is the
# wrong answer, and the cheapest way to find out what the right one plays is to
# force it once and watch.
FORCED_BRANCHES: dict[int, dict[int, int]] = {}

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
# stops dead on it. `the script exporter` carries its prompt and its options
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

# The other half of that pair. 0x6301 and 0x6304 are one action landing two
# ways, chosen by the `menu_item.bin` record's type: 0 starts an event (0x6304,
# above), 1 opens a sub-menu (this one). Both bodies are npcId u32 then
# menuItemId u16; only the answers differ.
#
# ⭐ For a long time nothing here could send it, because the only type 1 item in
# the whole table is `403 ロッカー開く` and it hangs off a *map object* menu
# rather than an NPC one -- and no map object had ever been found standing on
# any map. One is: hovering the run of grey cabinets along the window wall at
# the back of Ａ組教室 (map 3) draws the tooltip 「ロッカー」, one highlight per
# segment. The manual said where to look -- 「自分の教室のロッカー」 -- and the
# corridor and changing-room locker artwork that had been tried before is
# background painting with no tooltip at all.
MSG_CL_REQUEST_NPC_MAP_OBJECT_MENU = 0x6301
MSG_SV_OK_NPC_MAP_OBJECT_MENU = 0x6302
MSG_SV_NG_NPC_MAP_OBJECT_MENU = 0x6303

# What we answer 0x6301 with: one `sub_menu.bin` key, and the server is the one
# that picks it. The request carries no hint of which sub-menu is wanted -- it
# names the object and the item that was clicked and nothing else -- so this end
# chooses, exactly the way DEFAULT_NPC_EVENT above chooses a conversation.
#
# 2 is ロッカー・手紙メニュー, the parent of 0 ロッカー起動 and 1 手紙イベント起動,
# which is what a locker's 「ロッカー開く」 should reasonably lead to. Measured,
# one key at a time, against a live client: 0 opens the locker window outright,
# 2 asks 「手紙を読みますか？」 first and opens it on 読まない, and 1 starts a
# script.
#
# ⛔️ The rest of the table is 3/4/5 -- クラス委員長選挙 立候補受付 / 選挙活動中 /
# 投票 -- and answering any of them does NOTHING: no screen, and not one byte
# back from the client. That is the judgement, and it is not "the client had no
# data to draw with": those screens have to ask for the candidate list first
# (0x5509 / 0x550D) and the client never asked. Their own menu items, 405 and
# 406, are switched off in the data too, so there is no other way in either.
# ⛔️ Do not implement 0x5500-0x5518 -- nothing on this build can reach it.
#
# /smenu moves this without a restart.
DEFAULT_SUB_MENU = 2

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
#
# ⚠️ 16:1 is one of the 22 conversations that grant no 親密さ at all
# (romance.TALK_GAINS), so the conversation this server starts by default is
# worth nothing and the log says so when it ends. That is the conversation
# being what it is, not the credit path being broken; /nev 16 12 for one that
# pays. It stays the default because it is the one measured to play.
DEFAULT_NPC_EVENT = (16, 1)


def available() -> list[str]:
    """The scripts `the script exporter` has laid down, newest listing first."""
    if not SCRIPT_DIR.is_dir():
        return []
    return sorted(p.stem for p in SCRIPT_DIR.glob("*.json"))


def by_script_id(script_id: int) -> Script | None:
    """What is known about a scriptId — an export, or the branch table, or None.

    The client asks for events by number (MsgClRequestNpcEventStart carries the
    id it read out of the id table, not a name), so the lookup has to go the
    other way from `load`. Exports are searched first and are linear over a
    directory of a handful of files; they are the richer of the two sources and
    exist only on a machine that made them.

    ⭐ **The second half is the one a shipped copy takes.** With no exports at
    all, an id in `reference/branches.json` still comes back as a Script that
    can answer a choice — which is the entire reason the table is shipped. None
    now means what it says: nothing on this machine knows anything about this
    id, not merely that nobody exported it.
    """
    for name in available():
        found = load(name)
        if found is not None and found.script_id == script_id:
            return found
    return stub(script_id) if script_id in BRANCHES else None


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
        # What the shipped table knows about this id, if anything. It is the
        # only source a stub has, and the fallback for an export that predates
        # `branches` — an export that has them is a superset, since the table is
        # deliberately cut down to the branches this end can answer.
        known = BRANCHES.get(self.script_id) or {}
        # Byte offset of the code section inside the .ssb. Differs per file
        # (464 in amm_c011, 364 in amm_s001), so it has to be carried along.
        # Never legitimately zero — it is past the header of every .ssb there
        # is — so `or` picks the table without having to test for absence.
        self.code_base: int = data.get("codeBase") or known.get("codeBase", 0)
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
        } or dict(known.get("branches", {}))
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

        Taken is None when neither source has a branch recorded there: the ip is
        not an OP_BR, or it is one of the two thirds the table leaves out
        because this end could never answer it anyway. Either way the caller has
        only the fall-through to offer, which for those two thirds is the right
        answer rather than a degraded one.
        """
        target = self.branches.get(self.local_ip(wire))
        return wire + OP_BR_WIDTH, None if target is None else self.wire_ip(target)


def load(name: str) -> Script | None:
    """A script by name (`amm_s001`, with or without `.ssb`), or None.

    The name is matched without regard to case if the exact one is not there,
    which on macOS and Windows is what happens anyway -- their filesystems do
    not distinguish, and a name typed into the chat bar has always been allowed
    to arrive in any case. On Linux the same typing would miss the file and
    report the export as absent, which is a worse answer than the file.
    """
    stem = name[:-4] if name.lower().endswith(".ssb") else name
    path = SCRIPT_DIR / f"{stem}.json"
    if not path.exists():
        wanted = f"{stem}.json".lower()
        try:
            path = next(p for p in SCRIPT_DIR.iterdir() if p.name.lower() == wanted)
        except (StopIteration, OSError):
            return None
    try:
        return Script(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def stub(script_id: int) -> Script:
    """A Script with an id and nothing else, for playing without an export.

    ⭐ **A stub plays.** Round 37 established that the client runs the VM; what
    a stub tested is the assumption round 37 left standing, that the cast this
    end announces in ``MsgSvRequestScriptReady`` is needed at all. It is not.
    The same NPC conversation was played twice, once from an export and once
    from a stub built out of nothing but the id the client had just asked for,
    and both were accepted and both ran to the script's own ``OP_END``.

    Every field a stub lacks degrades into a path that already exists: ``at()``
    returns None and the log says ``<not an instruction start>``, ``selects``
    is empty and the query goes out as ``SELECT_ALL`` regardless.

    ⭐ **Two of those fields a stub no longer lacks.** ``branches`` and
    ``codeBase`` come from ``reference/branches.json`` when the id is in it
    (see ``Script.__init__``), which is what makes a choice stick on a machine
    that has never exported anything — the case every copy but this one is in.
    They were the only two that cost anything: a scene plays either way, but
    with no branch table a choice cannot take its branch, and with ``codeBase``
    0 the *printed* local ip is half the wire ip, wrong as a label though
    harmless as an answer, since every ip that goes back on the wire is in wire
    units. The name says which of the two happened, because "the choice did
    nothing" and "the table has never heard of this script" look identical from
    the outside and are not the same bug.
    """
    known = script_id in BRANCHES
    return Script({"file": f"<{'branch table' if known else 'stub'} {script_id}>",
                   "scriptId": script_id,
                   "codeBase": 0, "actors": [], "instructions": []})


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
    and it stayed at two options. So the field has to be right the first time,
    which is what the next paragraph is about.

    ⭐ **All bits set draws every option the script has, and no more.** The
    reading is settled by two measurements that only make sense together: 3
    against a three-option box drew *two* lines, which is what makes this a
    mask rather than a count, and 0xFFFFFFFF against the same box on a first
    query drew *three* — the script's own number, not thirty-two. The client
    caps to what the ``.ssb`` declares, so this end never has to know how many
    options there are, and ``select_query`` does not try to.
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

# Every bit set, for a select whose option count this end does not know.
SELECT_ALL = 0xFFFFFFFF


def select_query() -> tuple[int, int]:
    """`(select, timerCount)` for any INPUT_SELECT.

    Every option on, and no arithmetic to get there: the client caps the mask
    to the number of lines the script declares (`select_params`), and the
    script itself decides which of them a player may take, through the
    `OP_STR 0x1e80+k = 1` run it puts in front of the command. This end has no
    state with which to second-guess either, and now no need to count.

    ⚠️ This used to derive the mask from the exported option list, which made a
    choice box the one thing a stub could not answer — with nothing exported it
    computed `(1 << 0) - 1`, a box offering no lines at all.
    """
    return SELECT_ALL, DEFAULT_SELECT_TIMER


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

        ⚠️ The standing "no" is still not a neutral default -- it is a
        decision, and for the `<キャラ>_e011` gate it is the decision that
        keeps the confession scene off the screen (see the module docstring).
        It stays because "no" is the conservative half of a question this end
        cannot yet answer, not because it is known to be right.

        ⚠️ `FORCED_BRANCHES` outranks it and looks at nothing at all. That is
        what it is for -- finding out what an unanswered branch plays, before
        there is any reading of it to encode.
        """
        fall_through, taken = self.script.branch_roads(wire)
        local = self.script.local_ip(wire)
        forced = FORCED_BRANCHES.get(self.script.script_id or -1, {})
        target = forced.get(local)
        if target is not None:
            return self.script.wire_ip(target), f"強制 -> ip={target}"
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
# The closing half of the same bracket. Round 160 read the client's own list of
# what this subsystem can be told: the debug strings that sit beside
# `.\client\procedure\NpcEventMessageProcedure.cpp` name exactly five server
# messages -- Ok/Ng Start, Ok/Ng End, and NotifyNpcEventClearCharacterInfo --
# so whatever the client is waiting for after an event that came off a map
# object is one of these three and nothing else in the 0x56xx range.
MSG_CL_REQUEST_NPC_EVENT_END = 0x5603
MSG_SV_OK_NPC_EVENT_END = 0x5604
MSG_SV_NG_NPC_EVENT_END = 0x5605
# `info = { npcId: u16, eventFlag[MAX_GALLERY_ROUTE_FLAG_COUNT]: u32 x 2 }` --
# ten bytes, read field by field out of the client's own deserialiser. Not the
# counted list `the shape reader` classifies it as: the 2 it sees is a
# `mov ebx,2` constant loop bound, not a count on the wire.
MSG_SV_NOTIFY_NPC_EVENT_CLEAR_CHARACTER_INFO = 0x5606
# ⭐ This message is the only server-driven way out of an NPC event that was
# started from a map object, and `npcId` is what picks which way out.
#
# The handler (0x784cd1) is two branches and both of them end in the client's
# one and only "put a screen back on" call, 0x412547:
#
#   npcId == 0xffff -> 0x412547(5)     the field: map, toolbar, the player
#   otherwise       -> clear that npc's cached info, then 0x412547(0x0e), which
#                      is the ending: a four-minute staff roll, and then a
#                      black screen with nothing left listening.
#
# So the sentinel is not "clear every character", it is "the event is over,
# give the player the map back". Sending a real npcId here plays the credits.
NPC_EVENT_CLEAR_TO_FIELD = 0xFFFF
# tmn::MAX_GALLERY_ROUTE_FLAG_COUNT. The bits are unread; zero is what an event
# that grants no gallery route should say, and it is what the field branch
# ignores anyway.
GALLERY_ROUTE_FLAG_COUNT = 2


def npc_event_clear_params(npc_id: int, flags: tuple[int, ...] = ()) -> bytes:
    """A MsgSvNotifyNpcEventClearCharacterInfo body: npcId u16 + two u32 flags."""
    kept = list(flags[:GALLERY_ROUTE_FLAG_COUNT])
    kept += [0] * (GALLERY_ROUTE_FLAG_COUNT - len(kept))
    return struct.pack(">H", npc_id) + b"".join(struct.pack(">I", f) for f in kept)


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
    """The `(genre, index)` keys `the drama-event export export` laid down.

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
