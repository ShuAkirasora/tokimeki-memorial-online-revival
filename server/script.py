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
from collections.abc import Sequence
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

# The script pushed in place of the one the client just asked for, or None for
# the factory behaviour, which is to answer 0x5600 with the id the client read
# out of its own event record. Set from `/sc next`, cleared the moment it is
# used, and None on every start.
#
# ⭐ Why it has to exist at all: a script only ever runs as the *answer* to the
# client asking for one (round 35 measured what an unprompted 0x7200 does --
# it strips the extension, opens `data/sound/se/<name>_sdlist.snl`, and stops:
# no .arc, no Ok, no Ng). The ids the client can ask for come from the four
# `*_npc_event` tables, whose records name scripts in the 0x2000/0x4000/0x6000/
# 0x8000 ranges. The 22 ドラマイベント live in `drama_event.bin` with ids 2..68
# and are reached through the matching screen, and that screen hangs off
# `menu_item` 19 ドラママッチング, which sits only on the three 先生 menus --
# and no 先生 can be put on a map (none of the 44 non-恋愛候補生 placement
# scripts has a MAP_CHARA_DISP_ON). So there is no id the client can be made to
# ask for that names a drama script; swapping the answer is the only way in.
FORCED_NEXT_SCRIPT: str | None = None

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

# ⭐⭐⭐ The third command that stops the client dead, and the only one it stops
# on through the ordinary 0x721b rather than a 0x721c Begin. Round 189 hit it
# twice in one run of the tutorial and read the second one as the proof: the
# page of dialogue was fully drawn, two clicks and three seconds changed not one
# pixel, and the last report was still this ip.
#
# ⭐ What it wants is 0x721E below. The client cannot fill in a `$s00` by
# itself -- its OP_STR and arithmetic slots are logging stubs (round 169) -- so
# a script about to interpolate a register asks this end for it first.
OP_SYNC_VARIABLE = 0x903F

# ⭐⭐⭐ The answer to a SYNC_VARIABLE: the registers it named, with the values
# this end computed. Round 189 found the handler is real (0x784b1f, on the very
# listener this server's conversations already go through) while three of its
# neighbours are the `mov al,1; ret 4` stub; round 190 read the wire format out
# of the deserialiser. Sending it is also what releases the client -- 0x9f0048
# ends by clearing the interpreter's wait flag through 0x9f002c, the same call
# 0x721d makes.
MSG_SV_NOTIFY_SCRIPT_COMMAND_VARIABLE = 0x721E

# One entry's value block, per register category, at the widths the client's own
# write slots use (0x9f1e17): a FLAG is a byte at +0x60, 16BIT a u16 at +0xc4,
# 32BIT a u32 at +0x18c, and the two string categories are a `rep movsd` into
# fixed-width buffers -- 52 bytes at +0x31c for SSTRING, 148 at +0x99c for
# LSTRING. ⭐ Sending exactly that many bytes is what keeps the tail of a short
# string from being whatever the receiving buffer happened to hold: the client
# copies its full width regardless of how few bytes arrived.
VARIABLE_WIDTHS = {0: 1, 1: 2, 2: 4, 3: 52, 4: 148}

# The two of those whose block is text rather than a little-endian number.
VARIABLE_STRING_CATEGORIES = (3, 4)

# ⚠️ The client deserialises into a fixed array of 64 entries -- the count field
# sits at +0x2604, which is 4 + 64*152 -- and neither the read loop (0x8e9da0)
# nor the apply loop (0x9f0048) checks the count against it. Nothing in the 683
# scenarios synchronises more than four registers at once, so this cap has never
# been near; it is here because the consequence of passing it is not an error.
VARIABLE_MAX = 64

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

# The other command that stops the client dead, and the one that makes a
# ドラマイベント playable at all. ⚠️ Its name is PLAYER_WAIT_TIME and not
# PLAYER_SYNC: the two are neighbours (0x9100 is PLAYER_SYNC) and the one the
# client actually stops on is this one. It carries a count -- un111 asks for
# 0x32 twice in its opening -- and there is a PLAYER_WAIT_TIME_LOCAL beside it
# in the same opcode table, which is the reason to read this one as "wait, and
# let the server decide when the wait is over": the local variant is the one
# that does not need anybody.
#
# It arrives as a 0x721c Begin exactly the way INPUT_SELECT does, so what
# releases it is the same closing bracket, 0x721d carrying the Begin's {ip, op}.
OP_PLAYER_WAIT_TIME = 0x9101

# Whether to send that closing bracket at all. ⚠️ Off is the state the client
# was measured in first: it sits on the Begin and nothing happens, which is
# indistinguishable from "the wait has not elapsed yet" until somebody waits
# longer than the count asks for.
RELEASE_PLAYER_WAIT = False

# ⭐⭐ Where the season of a background comes from. `"clock"` is the factory
# answer here: the school clock's own quarter (`curriculum.season`). `"script"`
# leaves the scripts' own constant standing, which is what a server that only
# evaluates the bytecode does and why the tutorial used to snow in August; an
# int 0..3 forces one arm, which is how all four get looked at without waiting
# a year.
#
# ⚠️ **Booked carefully** (the smallest-invention rule): that the switch moves with the
# calendar is *restored* -- the manual, the beta-2 report and the client's own
# `SeasonName` property all say the original had a live season (`gs3vm.SEASONS`
# has the citations). **The inventions are the mechanism and the boundaries**:
# the original server overrode that register from code nobody has, and where it
# cut the year is in no table on this disk.
#
# ⚠️ It reaches the client through `gs3vm.Follower.season` and therefore only
# where the shadow already decides -- a four-armed switch whose every arm is
# scenery. ⛔️ Nothing else in a script moves because of this.
SEASON_SOURCE: str | int = "clock"

# How far past an OP_BR its fall-through lies. OP_BR is 8 bytes wide, and the
# client counts ip in file bytes, so "condition not taken" is br + 8. Verified
# live: the client sat on the OP_BR at file 1148, was told 1156, and moved on.
OP_BR_WIDTH = 8

# ⭐ The reason string `resolve_branch` gives when its answer is the standing
# "no" and nothing else -- no forced branch, no choice chain in flight. It is a
# constant because a caller that owns a second opinion is allowed to overrule
# exactly this one answer and no other (`mps_session`'s scenery branches), and
# "is this the default?" should not be a string comparison spelled out twice.
STANDING_NO = "fall-through"

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


# ⭐⭐⭐ Which of the four event tables the client reads our eventId out of, and
# it is decided by the *npcId we send back*, not by the eventId itself.
#
# The client's 0x6305 handler (FUN_0077d69c) is a three-way switch on
# `npcId >> 16`, and each arm calls a different keyed table accessor:
#
#     kind = npcId >> 16                       (0x00404ff9 / 0x00404fdf)
#     kind == 2 -> 0x7e7b2a   manager +0x488 = common_npc_event
#     kind == 3 -> 0x7e7b88   manager +0x498 = general_npc_event
#     else      -> 0x7e6e97   manager +0x038 = capture_npc_event
#
# All three then read the same field out of the record they found — `+0x36`, the
# u16 scriptId — and hand it straight to the event starter. So the categoryId /
# id pair is meaningless on its own: `0:0` is 天宮イベントその１ in one table and
# 石打野球部入退部c001 in another, and this number is what says which.
#
# ⭐ The four roster tables key on exactly these numbers, with no gaps and no
# overlap: capture_npc is 1:0-1:9, common_npc 2:0-2:17, general_npc 3:0-3:31,
# extra_npc 4:0. So the "kind" is not a protocol enum invented for this message,
# it is which cast list the NPC belongs to, and the spawn message carries the
# same pair.
#
# ⚠️ extra_npc_event is not one of the arms, and the table manager never loads
# it either — so 4:0 生徒Ａ falls through to capture_npc_event and its one
# script (sta_c001.ssb, scriptId 0x8000) is unreachable on this build.
NPC_KIND_CAPTURE = 1
NPC_KIND_COMMON = 2
NPC_KIND_GENERAL = 3

_EVENT_TABLE_BY_KIND = {
    NPC_KIND_CAPTURE: "capture_npc_event",
    NPC_KIND_COMMON: "common_npc_event",
    NPC_KIND_GENERAL: "general_npc_event",
}


def event_table_for(npc_id: int) -> str:
    """Which table the client will look the eventId up in, given this npcId.

    ⚠️ The fallback is the same table as kind 1 rather than an error, because
    that is what the client does: only 2 and 3 have an arm, and everything else
    — 4, 0, 17, anything — lands in the capture_npc_event one.
    """
    return _EVENT_TABLE_BY_KIND.get(npc_id >> 16, "capture_npc_event")


def npc_map_object_event_params(event: tuple[int, int], npc_id: int) -> bytes:
    """A MsgSvOkNpcMapObjectEvent body: eventId{categoryId, id} then npcId.

    Widths are the client's own (`reads=2+2+4`); the npcId is one u32 here
    because the request prints it as one number, so this end does not need to
    know where the split inside it is.

    ⚠️ The caller normally passes back the four bytes that arrived, but that is
    a choice and not a formality: see `event_table_for` above — the npcId in
    *this* body is what picks the event table. Echoing keeps whatever the NPC
    was spawned as, which is the behaviour to keep by default.
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
    is empty and the log says the box's text is in the script only. ⭐ The
    choice mask degrades the same way and by the same route: no export is also
    no shadow (``gs3vm.follow`` returns None), so ``select_query`` is asked
    nothing and answers ``SELECT_ALL`` — which is what this end sent to every
    box there has ever been until round 211.

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


def pc_info_entry(actor_id: int, info: bytes) -> bytes:
    """One ``pcInfo[]`` entry: an actorId and the character behind it.

    ⭐ It is the character-creation block minus its first byte, and that is not
    a coincidence to be trimmed later -- it is what the reader asks for. From
    0x8e8120, per entry and in order: u16 actorId, three fixed 11-byte names,
    u16 sex, u16 bloodType, u8 birthMonth, u8 birthDay, sixteen u16 (the nine
    ``looks`` then the seven ``accessory``), u16 charaType. That is 75 bytes,
    and ``parse_create_info`` reads the same fields in the same order after
    ``charaFrameId`` -- which is byte 0 and the only one not in this message.

    ⚠️ Both counted arrays in 0x7200 are read into fixed room: pcInfo has four
    entries' worth (0x136 - 6 over a 0x4c stride) and npcInfo four (0x148 -
    0x138 over 4), and the reader tests neither count against them. Four is
    also how many 役柄 the client has names for (``win_baloon_text`` 168-171),
    so the ceiling is the game's, not a buffer that happens to be that size.
    ⛔️ Never send more than four of either.
    """
    if len(info) != 74:
        raise ValueError(f"create info is {len(info)}B, expected 74")
    return struct.pack(">H", actor_id) + info[1:74]


PC_INFO_MAX = 4

# ⭐⭐ Which 役柄 slot the player who started the script goes into, or None to
# send no pcInfo[] at all (which is what every solo script got until round 191).
#
# ⭐ The evidence that it is 0 and not 1 is in the scripts themselves, and it is
# a pair rather than a guess: `TALK_ON_EVENT` names its speaker as `PC#n`, the
# dialogue writes the players' names as `$m0n` (family) and `$n0n` (given), and
# the two indices move together. `un111`, a two-player ドラマイベント, speaks as
# `PC#0`/`PC#1` and writes `$m00`/`$m01`; `amm_e001`, the tutorial, speaks only
# as `PC#0` and writes only `$m00`. ⇒ the slot the local player belongs in is
# `PC#0`, and round 186 filling it as actorId 1 left `$m00` with nothing behind
# it -- which is exactly what the screen showed (2.144, round 190).
#
# ⚠️ A knob rather than a literal because the whole claim is one screen away
# from being checked, and `/pcinfo 0|1|off` asks all three questions of one
# running client. Factory value is the answer this end believes.
CAST_LOCAL_PLAYER: int | None = 0


def ready_params(script_id: int, npc_infos: list[tuple[int, int]],
                 pc_infos: Sequence[tuple[int, bytes]] = ()) -> bytes:
    """A MsgSvRequestScriptReady body.

    ⚠️⚠️ **`pcInfo[]` used to be empty for everything a single player starts on
    his own**, on the reasoning that his character is already in the scene and
    there is nothing this end could put there that the client does not have.
    ⛔️ That reasoning is wrong, and the screen said so: the tutorial draws
    「**くん、あなたのクラスを教えてくれる？**」 with the name missing and the
    LOG window's speaker as 【】, because `$m00`/`$n00` are read out of *this*
    array and out of nothing else. The client knowing who it is playing and the
    script being able to *say* his name are two different tables.

    ⭐ A ドラマイベント is the case that made the array visible in the first
    place -- the cast of one of those is the *players*, which is why all 22 of
    them name no actors in their own headers -- but it is not the only case
    that needs it.
    """
    cast = list(pc_infos)[:PC_INFO_MAX]
    body = struct.pack(">HH", script_id, len(cast))
    for actor_id, info in cast:
        body += pc_info_entry(actor_id, info)
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
    caps to what the ``.ssb`` declares, so a mask this end cannot compute can
    still go out as every bit without knowing how many options there are — and
    when it *can* compute one, the count comes from the instruction rather than
    from here (``select_query``).

    ⭐ **The scripts number their options the same way, and that is a separate
    source.** Every ``INPUT_SELECT`` in the game's 683 client scripts is
    preceded by exactly one ``SELITEM_DISP_FLAG`` write per option, and the
    low five bits of those flag numbers are exactly ``0..n-1`` — 1853 of 1853,
    no exception. Three complementary pairs of conditions (a ``<`` branch and
    a ``>=`` branch on the same stat) land on the option the number names, and
    the six option texts read correctly. So "bit k is option k" holds on the
    wire *and* in the bytecode, established once from each end.

    ⭐ **Knowing that is what makes a computed mask usable at all.** The flags
    are written from expressions over registers the conversation itself keeps,
    and round 211 stopped sending every bit and started sending what the shadow
    VM works out of them (``select_query``). Bit k being option k in both the
    bytecode and the wire is the join between the two halves: without it a
    computed mask would be a number with nowhere to put it.
    """
    return struct.pack(">IQ", select & 0xFFFFFFFF, timer_count)


def command_end_params(wire_ip: int, op: int) -> bytes:
    """A MsgSvNotifyScriptCommandEnd body: the Begin's own {ip, op}, echoed."""
    return struct.pack(">IH", wire_ip, op)


def variable_entry(category: int, number: int, value) -> bytes:
    """One `{category, number, byteLen, value}` of a 0x721E body.

    `value` is an int for a numeric category, a str for a string one, or None
    for "this end could not say" -- which goes out as the category's zero (0,
    or the empty string) rather than being dropped, because the client is
    waiting on the entry count and a short list leaves a register holding
    whatever was in it.

    ⚠️⚠️ **Two byte orders in one record, and they are not a mistake.** The
    length goes through the stream's own u16 reader and is big-endian like every
    other field on this wire; the value block is `memcpy`d out of the stream
    (0xa49610) and then read back with plain x86 loads -- `mov cx, [esi]` for a
    16BIT, `mov ecx, [esi]` for a 32BIT -- so numbers inside it are
    **little-endian**. Both halves are packed here, in one function, so that the
    mixture is impossible to read past.
    """
    width = VARIABLE_WIDTHS.get(category)
    if width is None:
        raise ValueError(f"category {category} has no value block on the wire")
    if category in VARIABLE_STRING_CATEGORIES:
        raw = ("" if value is None else str(value)).encode("cp932", "replace")
        # NUL-terminated and no longer than the buffer it is copied into: the
        # client reads it back as a C string out of a fixed-width field.
        block = raw[: width - 1].ljust(width, b"\x00")
    else:
        block = int(value or 0).to_bytes(width, "little", signed=False)
    return struct.pack(">BBH", category & 0xFF, number & 0xFF, width) + block


def command_variable_params(entries: Sequence[tuple[int, int, object]]) -> bytes:
    """A MsgSvNotifyScriptCommandVariable body: `[(category, number, value)]`.

    Shape, read straight out of the client's own deserialiser (0x8e9da0, the
    vtable[0] of `Input_MsgSvNotifyScriptCommandVariable`) in round 190::

        u16 count
        count x { u8 category, u8 number, u16 byteLen, byteLen bytes }

    ⭐ The category numbers are the *same seven* the bytecode's operand encoding
    uses (round 169: 0 FLAG, 1 16BIT, 2 32BIT, 3 SSTRING, 4 LSTRING, 5
    SELITEM_DISP_FLAG, 6 SELECT). That is not an assumption carried over -- the
    handler's own dispatch at 0x9f0048 splits on the first byte into exactly
    those seven cases, with 0 and 5 reading a bool, 1 and 6 a u16, 2 a u32, and
    3 and 4 taking the block as a buffer. Two independent readings, one table.

    ⚠️ Only categories 1 and 3 have ever been on this wire, because those are
    the only two the 683 scenarios ever synchronise (473 and 604 of 1077
    entries, and not one of any other kind).
    """
    kept = list(entries)[:VARIABLE_MAX]
    return struct.pack(">H", len(kept)) + b"".join(
        variable_entry(category, number, value) for category, number, value in kept
    )


# `timerCount` is a duration in units unknown, and stayed unknown: the box does
# not close on its own within the minute anybody has watched it. 60000 is "a
# minute if these are milliseconds". 0 is avoided because "0 = no limit" and
# "0 = expire now" are equally plausible readings and one of them loses.
DEFAULT_SELECT_TIMER = 60000

# Every bit set, for a select whose option count this end does not know.
SELECT_ALL = 0xFFFFFFFF


# The widest mask this end will build out of a computed one. The instruction
# carries its option count in six bits, so 63 is what it can say; the field on
# the wire is 32 bits wide. A count in between is not a box this end knows how
# to answer, and it says so rather than sending a silently truncated mask.
SELECT_BITS = 32


def select_query(computed: tuple[int, int, int] | None = None
                 ) -> tuple[int, int, str]:
    """`(select, timerCount, why)` for the INPUT_SELECT the client stopped on.

    `computed` is `gs3vm.Follower.select()` for *this* box — `(mask, unknown,
    options)`, one bit per option in each of the first two — or None when there
    is no shadow to ask, which is the ordinary case for a stub and for every
    copy of this server that has exported nothing.

    ⭐⭐ **The mask is the script's own, and this end can finally read it.**
    Which lines a player may take is decided by the run of `OP_STR 0x1e80+k`
    the script puts in front of the command, and until round 211 nothing here
    evaluated script arithmetic, so every bit went out set and the client drew
    every line the `.ssb` declares. The shadow evaluates that run, walking the
    same scenario the client is playing, so "which lines, right now" is a
    question this end can answer. It is a restoration, not a new rule: the
    original server is the only place those flags could ever have been read.

    ⚠️⚠️ **Asked at the box, never stored.** Those flags are mostly `F<n> == 0`
    over registers the conversation itself writes — "has this answer been used
    yet" — so a script that loops back and redraws the same box gets a
    different mask the second time (`amm_e002` does exactly that). There is no
    such quantity as *the* mask of a select, which is why this takes a value
    computed at the stop instead of looking one up.

    ⭐ **A bit this end could not work out goes out set.** `unknown` is the
    shadow's ⊤ — a cell nobody supplied, an operation it does not implement.
    The two ways to be wrong are not symmetric: offering a line the script
    meant to hide lets a player take one answer twice, while hiding a line it
    meant to offer can leave a box with no way out of it and a conversation
    with no way to end. So ⊤ degrades into the behaviour this end had when it
    could compute nothing at all.

    ⚠️ **Never an empty box.** A mask of 0 with nothing unknown is a reading
    this end will not act on. The client draws exactly the lines the mask names
    and no others (`select_params`), so 0 is a box with no lines — the same
    dead end the old exported-option-list mask fell into on a stub, where it
    computed `(1 << 0) - 1`. Whatever produced the 0 is a bug on this end long
    before it is a script that offers nothing, so it falls back and says so.
    """
    if computed is None:
        return SELECT_ALL, DEFAULT_SELECT_TIMER, "no shadow"
    mask, unknown, options = computed
    if not 0 < options <= SELECT_BITS:
        return SELECT_ALL, DEFAULT_SELECT_TIMER, f"{options} options declared"
    offered = (mask | unknown) & ((1 << options) - 1)
    if offered == 0:
        return SELECT_ALL, DEFAULT_SELECT_TIMER, "⚠️ the shadow offers nothing"
    if offered == (1 << options) - 1:
        return offered, DEFAULT_SELECT_TIMER, "the shadow, every line on"
    return offered, DEFAULT_SELECT_TIMER, (
        f"the shadow, {bin(offered).count('1')} of {options} lines")


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
        # ⭐ A `gs3vm.Follower` walking the same script alongside the client,
        # or None when this machine has no export of it.
        #
        # ⚠️ **It arrived deciding nothing**, and for a round it changed no byte
        # that went out: it only said in the log what a register file on this
        # end would have answered, so that it could be read off a log and
        # compared against a screen before any of it was allowed to matter. The
        # reason for that order was not caution — the first two things checked
        # against the outside world (an arithmetic table, a walk over recorded
        # ip traces) both leave "does it keep up with a real conversation"
        # untested, and this was the cheapest way to test it.
        #
        # ⭐⭐ **Two answers are its now**, both after that wait: the branches
        # whose road decides nothing visible (`mps_session`, over exactly the
        # `STANDING_NO` of `resolve_branch`), and the choice-box mask
        # (`select_query`). ⚠️ Everything else here still answers what it
        # answered before this existed.
        self.shadow = None

    def chose(self, result: int) -> None:
        """Remember a MsgClResultScriptCommandSelect and start counting.

        ⚠️ What is remembered here lasts until the OP_BR chain consumes it, and
        no longer. 親密さ is settled at NotifyScriptEnd, by which time this
        Runner is gone, so the copy that survives the script is
        `_Session.talking_choice` — do not move it back here.
        """
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

        ⭐ One family of branches is now answered rather than defaulted, and
        the caller does it, not this method: `mps_session` overrules exactly
        the `STANDING_NO` answer, and only when the shadow VM has a definite
        condition *and* everything the branch decides is invisible to the save
        and to the story (`gs3vm.Follower.decided_road`). A forced branch and a
        choice chain both outrank it, which is why the override keys off this
        one reason string and not off the target.

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
            return fall_through, STANDING_NO
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
# ⭐⭐⭐ タイトルイベント: the door 初登校 comes through, and it is the client
# that knocks. Measured in round 192, on the first 登校 this server ever
# answered with `tutorialFlag = 1` in the character list (characters.py): the
# client stopped mid-登校 on 「登校処理を行っています」 and sent 0x6C00 carrying
# `npcEventId = 0x2000`, which is `amm_e001` -- the tutorial. ⚠️ Single variable:
# 0x6C00 appears in exactly one of this server's logs, the one where the flag
# was 1, and in none of the ~200 rounds before it.
#
# ⇒ 2.143 六's hypothesis, confirmed: the client has its own table of which
# event 初登校 plays and needs to be told nothing but 「this is a first day」.
# What it does NOT do is come through the map-object door -- this is a channel
# of its own, with its own procedure class (TitleEventMessageProcedure.cpp) and
# its own Ok/Ng pair. Nothing in the 0x56xx range is involved.
#
#   0x6C00 RequestTitleEventStart  npcEventId u16   -> 0x6C01 Ok (empty)
#                                                   -> 0x6C02 Ng (u8 reason)
#   0x6C03 RequestTitleEventEnd    (empty)          -> 0x6C04 Ok (empty)
#                                                   -> 0x6C05 Ng (u8 reason)
#
# Field names from the client's own dumps (`the field-name extractor TitleEvent`),
# shapes from `the shape reader`. ⭐ `npcEventId` is the same u16 0x5600
# carries and it means the same thing there: a scriptId, resolved through
# `by_script_id`.
MSG_CL_REQUEST_TITLE_EVENT_START = 0x6C00
MSG_SV_OK_TITLE_EVENT_START = 0x6C01
MSG_SV_NG_TITLE_EVENT_START = 0x6C02
MSG_CL_REQUEST_TITLE_EVENT_END = 0x6C03
MSG_SV_OK_TITLE_EVENT_END = 0x6C04
MSG_SV_NG_TITLE_EVENT_END = 0x6C05

#: 自分のクラス, 0 = Ａ組 .. 25 = Ｚ組. Pinned by value range in 2.143 四 (26
#: constants in the tutorial's dispatch tree, 26 classrooms in `map.bin`) and
#: read by both `<キャラ>_e011` and the tutorial. ⭐ The tutorial dispatches on it
#: to pick which classroom door to walk the player to; characters.DEBUT_CELLS is
#: that walk's 26 endpoints, and this end feeds the same value to the shadow VM
#: that it puts on the wire as `inClass`.
PC_IN_CLASS = 0x301C

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
