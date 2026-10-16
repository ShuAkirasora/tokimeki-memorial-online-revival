#!/usr/bin/env python3
"""Fix the client's own bugs, for handing out through the updater.

Seven fixes, one file -- the client is a single tmo.exe, so whatever is fixed
in it goes out together:

  * the 試験結果 page of the school paper (twenty bytes, below);
  * the title screen's おまけ button, which this build never draws (four
    bytes, after that);
  * the おまけ gallery's 表情 photos, which this build can never show past
    the first (five bytes, after that);
  * the おまけ gallery's Epilogue, which opens onto a black screen for anyone
    but an account whose only ending is Amamiya's (three bytes, after that);
  * 「イベント中断」 in a one-player event, which this build draws grey and
    wires to nothing (nine bytes, after that);
  * the staff roll of an おまけ ending, which nothing in this build can stop
    (five bytes and a 140-byte routine, after that);
  * the あとがき blackboard after an おまけ confession is left with
    イベント中断 (eleven bytes and two short routines, last).

The paper's 試験結果 tab draws the exam rankings from six files this server
publishes (server/newspaper.py). The client that shipped reads every score in
them as a SIGNED byte: each of the twenty loads that feed the table is a
``movsx``. A score of 0..100 survives that, but

  * 合, the eight scores added up, is put together as ``high << 8 | low`` from
    two sign-extended bytes, so any total whose low byte is 0x80 or more -- 200,
    450, 480, roughly half of them -- is drawn as a negative number;
  * a subject the sitter did not take is marked 0xFF, and the client compares
    the loaded value with 0xFF to draw 「　－　」 instead of a number -- after the
    sign extension it is -1, so the dash is never drawn and "-1" is.

Twenty one-byte changes fix both: ``0F BE`` (movsx) becomes ``0F B6`` (movzx)
at each load, and nothing else moves. 合 then reads 0..800 as written, and the
dash appears where the format says it should. (A total of exactly 255 also
reads as the marker and draws a dash; that is the format's own choice of
marker, and the fix keeps it rather than invent another.)

  The おまけ button
  ----------------
  The manual describes おまけ as part of this game (p02_06, p02_07, p09_02:
  a gallery of the scenes a character has seen and the endings received), and
  two of the operator's notices fixed bugs in it (2006-04-19 and 04-26). The
  client that shipped builds the title menu with the button and then, four
  bytes later, takes it away again: at 0x6895DD ``mov byte [ebp+0x13], 0``
  clears the "draw おまけ" flag whenever the nVersion property reads 1..5,
  and this build's own data sets it to 5. Those four bytes become NOPs. The
  other half of the condition is left as it is: the button still appears only
  once some character of the account has received a confession (the 0x0316
  list is not empty), as the client always meant it to.

  ⚠️ Why not raise nVersion instead: the same property also opens 転校 (moving
  to another school), which the manual never mentions and this build shipped
  closed. Changing the client's test changes only the button.

  The 表情 photos
  ---------------
  A scene of the gallery can hold up to six photos of the heroine, one per
  expression, and the client's own gallery table carries them: a row is
  ``photo[route][expression]``, and the photos are filed in the background
  table as 「<name>表情<scene><route + 1><expression + 1>」 -- route 0 for all
  of them. The server says which ones the player has seen, and the viewer's
  表情 button steps through those. But the function that turns (route,
  expression) into a photo (0x68BBE6) picks the route-0 photo when
  ``route == expression`` instead of when ``route == 0``: six
  ``cmp byte [ebp+0x10], k`` for k = 0..5, where every k should have been 0.
  So route 0 reaches its first photo and nothing else, every further
  expression lands in the route-1 group, which is empty, and the button
  either stays grey or opens onto a black screen. The immediates of the five
  compares with k = 1..5 become 0; nothing else moves.

  The Epilogue
  ------------
  The tenth picture of a heroine's gallery page is her Epilogue, the group
  photo her row of the client's own candidate table names (+0x1C0). Whether
  it opens is one byte of the gallery record, "this candidate is in the
  ending list" -- and the client works that byte out twice, once for the
  page (0x688367) and once for the viewer (0x688553), in two copies of the
  same function. The page's copy is right: it looks the candidate's npcId up
  in the ending list (0x68566A, comparing each entry with it) and keeps
  "found" (setne). The viewer's copy pushes an empty comparand, calls a
  lookup that compares with no one (0x685691: the first entry whose id is
  not 0) and keeps "not found" (sete). So the viewer reads "nobody but
  Amamiya has an ending", whoever's page it was opened from: on an account
  with any other ending every Epilogue opens black and 次へ steps over it,
  and on one with Amamiya's alone every candidate's viewer reaches the
  photo, ending or not. Three bytes make the viewer's copy the page's: push
  the npcId the function has just stored (disp 0x10 -> 0x12), call 0x68566A
  instead (the low byte of the rel32), and keep "found" (sete -> setne).

  イベント中断 in a one-player event
  ---------------------------------
  Right-clicking an event puts up three items: ポーズ, 鑑賞モード and
  イベント中断 (interrupt). The event screen comes in two builds, one for a
  ドラマイベント played by a party and one for everything a player watches
  alone -- a campus event, the tutorial, an おまけ ending -- and the client
  finished the item in the first only. The party build fills the menu's three
  "can be picked" bytes with (pause allowed, 1, 1) and opens the
  「イベントを中断しますか？」 box when the third is picked; the one-player
  build fills them with (0, 1, 0) at 0x73CEBB, its slot for that pick is a
  ``return 1`` and its dialog factory's slot for the box returns nothing. So
  one byte lights the item (0x73CF09, the immediate of
  ``mov byte [esi+0xe], 0``), and two vtable entries of the one-player build
  are pointed at the party build's own code: the pick (0x73E45C, which asks
  the build's dialog factory for the box) and the box itself (0x73F781). From
  there the client's own path takes over: はい sends the same 0x7205 a party
  member's does, and the server decides what the interrupt means.
  ⚠️ ポーズ stays grey: a pause tells the others in the party to wait, and
  the client's own sentence for it says a one-player event has no one to tell.

  Esc on an おまけ staff roll
  ---------------------------
  Replaying an ending from おまけ plays the confession, then the full staff
  roll -- about five minutes, theme song and all -- then the epilogue. The
  confession and the epilogue can be left with イベント中断 (above); the roll
  cannot. It is a screen of its own with no menu, and the client gives it no
  key at all: its update (0x82172B) is a seven-step sequence -- fade in,
  start the song, wait for it, scroll, wait for the song to end, fade out,
  move on -- that only time advances. So a player who replays an ending for
  the scene sits through the whole roll every time.

  The fix gives the roll Esc, a key several of the client's own screens
  already bind (0x69061E, 0x80062D, 0x80EC04, 0x82ADB1, 0x85C09B). Five
  bytes at the top of the update (0x821734) jump to a routine in the unused
  tail of the code section (0xB58F00, zero-filled and mapped as code), and
  the routine asks three things each frame: is the roll past its first
  step and not yet fading out (steps 2..5); was Esc pressed this frame, by
  the client's own keyboard state (0xA55319: down now, up the frame
  before); and is this the roll of an おまけ replay. The last is the field
  the roll itself reads at its end (0x81F84D) to decide what follows: 6
  there asks for the epilogue as a title event (0x6C00), the way おまけ
  plays it, and 5 as a campus event (0x5600), the way a confession does.
  If all three hold it does what step 5 does when the song ends, with the
  song stopped first and the shorter of the roll's two fades: music off,
  fade to black, step 6. From there nothing differs: the roll's own last
  step asks for the epilogue, exactly as when it runs out. Then it puts back
  the five bytes it took and jumps back.
  ⚠️ Only in おまけ: the roll that follows a confession on campus is the
  first time the player sees it, and it plays as it always did.

  No あとがき after leaving an おまけ confession
  ----------------------------------------------
  The あとがき is the blackboard that closes a story: a teacher explains
  再入学 to a player who has just been given an ending. The client puts it up
  on the way back to the menus after one -- the Ok of leaving the school
  (0x030A) as it arrives in an event (0x7838F3) sets the menu's entry step to
  4, and the menu (0x69F235) reads 4 as "blackboard first, then on its ＯＫ
  the ゲームメニュー" (its own steps 9..12, then 7). An おまけ confession left
  with イベント中断 comes back the same way -- it is the only answer that
  brings this client out of the replay onto a menu at all -- so the player
  who skipped the scene is shown the story's closing lecture.

  The entry steps the menu knows are 0..4, and none of the others leads to
  the ゲームメニュー without the board: 0 replays the start-up logos, 1 is the
  login box, 2 the キャラクター選択, 3 the board again. So the fix adds one,
  in two places. In the Ok's handler, seven bytes at 0x783910 (``push 4;
  call 0x640F80``, the store of the 4) call a routine after the roll's
  (0xB58F90) that stores 5 instead when the event is an おまけ replay -- the
  field the roll reads (kind 6) -- and 4 otherwise. In the menu, the jump
  taken for anything past 4 (0x69F2BC, to the end of the step) is pointed at
  a second routine (0xB58FB0): 5 there goes straight to step 7, as the
  board's ＯＫ would, and every other value takes the jump it always took.
  Nothing in the shipped client stores 5, so nothing else changes.
  ⚠️ Only in おまけ: after a confession on campus the Ok is the client's own
  way out of the story, and the あとがき there is the ending's last page.

  How it reaches players, and why that way
  ----------------------------------------
  The way the operated game shipped client fixes. Its updater runs before the
  client on every start, and replaces whole files -- nothing in it edits part
  of one -- so a change to the client's code was a new tmo.exe, in place from
  the next start. Its own notices say as much: a fix to a crash on leaving a
  card game, 2007-03-03, "本修正は、一度ゲームを終了した後、再度起動することで
  適用（アップデート）されます". This tool makes that file and puts it where
  server/updater_server.py hands files out from (runtime/update/), and every
  client fetches it on its next start.

  ⚠️ The file is the client, so it is made from your own copy and never kept
  anywhere but your server's runtime/update/: this tree carries the twenty
  bytes, not the program. Your copy has to be the build this was written
  against, give or take the four bytes set_auth_address.py writes; anything
  else -- another build, a copy carrying other changes -- is refused rather
  than handed to every player who connects.

  ⚠️ The four authentication bytes. The copy that is handed out is the one the
  client then runs, so it has to carry the address your players' clients are
  pointed at -- the same one they gave Play.cmd / set_auth_address.py. Give it
  as --address; it is written exactly as set_auth_address.py writes it, so a
  client set up for this server sees nothing to change and fetches the file
  once. A client pointed elsewhere gets this server's address with the file.

Usage::

    python3 ranking_fix.py --game-dir <folder with tmo.exe> --address <server address>
    python3 ranking_fix.py --game-dir ... --address ... --check   # say what it would write
    python3 ranking_fix.py --remove                               # stop handing it out

The server needs no restart: the updater reads runtime/update/ at every check.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import set_auth_address as auth

HERE = Path(__file__).resolve().parent
UPDATE_DIR = HERE / "runtime" / "update"
TARGET = "tmo.exe"

#: SHA-256 of the build this was written against, as it shipped (2006012300).
RETAIL_SHA256 = "df6652613021f554f09bebda6de890d2cee3fc8133e9f096817255e31bc6608b"

IMAGE_BASE = 0x400000
MOVSX, MOVZX = 0xBE, 0xB6

#: The おまけ button's gate: the instruction that clears its flag, as shipped.
OMAKE_GATE = 0x6895DD
OMAKE_GATE_SHIPPED = "c6451300"
NOP = 0x90

#: The 表情 photo lookup (0x68BBE6): the immediate byte of each
#: ``cmp byte [ebp+0x10], k`` for k = 1..5, which becomes 0 (k = 0 is right).
PHOTO_ROUTE_TESTS = {0x68BCE3: 5, 0x68BCF5: 4, 0x68BD07: 3, 0x68BD19: 2, 0x68BD2B: 1}
PHOTO_ROUTE_TEST = "807d10"

#: The gallery viewer's ending test (0x688553), made the album page's
#: (0x688367): address -> (byte as shipped, byte fixed).
EPILOGUE_FIX = {
    0x6885E2: (0x10, 0x12),   # push dword [ebp+0x10] -> [ebp+0x12]: the npcId as comparand
    0x6885EC: (0xA1, 0x7A),   # call 0x685691 -> call 0x68566A: the lookup that compares it
    0x6885FC: (0x94, 0x95),   # sete -> setne: keep "found"
}

#: イベント中断 in the one-player event screen: address -> (as shipped, fixed).
#: One immediate byte, then two vtable entries (little-endian dwords).
RETIRE_ITEM = 0x73CF09                     # mov byte [esi+0xe], 0 -> 1
RETIRE_ITEM_INSTRUCTION = "c6460e"
RETIRE_SLOTS = {
    0xBD5EE8: (0x464585, 0x73E45C),        # the pick: return 1 -> open the box
    0xBD60D4: (0x5F88DC, 0x73F781),        # the box: nothing -> 「イベントを中断しますか？」
}

#: Esc on an おまけ staff roll: the five bytes the hook takes at the top of the
#: roll's update, and the routine it jumps to (position-dependent: every rel32
#: below is worked out for ROLL_ESC_CODE).
ROLL_ESC_HOOK = 0x821734
ROLL_ESC_HOOK_SHIPPED = "8b46604857"       # mov eax,[esi+0x60]; dec eax; push edi
ROLL_ESC_CODE = 0xB58F00
ROLL_ESC_ROUTINE = bytes.fromhex(
    "8b4660"            # mov eax,[esi+0x60]          the roll's step
    "83e802"            # sub eax,2
    "83f803"            # cmp eax,3
    "7777"              # ja done                     only steps 2..5
    "e88facefff"        # call 0xA53B9F               the keyboard
    "8bc8"              # mov ecx,eax
    "6a1b"              # push 0x1B                   Esc
    "e800c4efff"        # call 0xA55319               pressed this frame?
    "84c0"              # test al,al
    "7465"              # jz done
    "6a006a0054"        # push 0; push 0; push esp
    "e8c6aa8aff"        # call 0x4039ED               the event being played (a shared pointer)
    "59"                # pop ecx
    "8b0424"            # mov eax,[esp]
    "85c0740a"          # test eax,eax; jz release
    "8b4044"            # mov eax,[eax+0x44]
    "85c07403"          # test eax,eax; jz release
    "8b4028"            # mov eax,[eax+0x28]          its kind
    "50"                # release: push eax
    "8b4c2408"          # mov ecx,[esp+8]
    "85c97405"          # test ecx,ecx; jz kept
    "e868828aff"        # call 0x4011AF               let the pointer go
    "58"                # kept: pop eax
    "83c408"            # add esp,8
    "83f806"            # cmp eax,6                   an おまけ replay (5 is campus)
    "7532"              # jne done
    "6a00"              # push 0                      no song
    "8bc4"              # mov eax,esp
    "6a0050"            # push 0; push eax
    "8d4e58"            # lea ecx,[esi+0x58]
    "e823eab0ff"        # call 0x667982               the song: fade it out, play nothing
    "c7042403000000"    # mov dword [esp],3           fade to black ...
    "8bc4"              # mov eax,esp
    "ff35602fbe00"      # push dword [0xBE2F60]       ... over the roll's 2.0 s
    "50"                # push eax
    "8d8ef0000000"      # lea ecx,[esi+0xf0]
    "e81160c3ff"        # call 0x78EF8B
    "58"                # pop eax
    "c7466006000000"    # mov dword [esi+0x60],6      step 6: wait for the fade
    "8b46604857"        # done: the five bytes the hook took
    "e9ad87ccff"        # jmp 0x821739
)

#: No あとがき after an おまけ confession left with イベント中断. First the seven
#: bytes the hook takes in the Ok of leaving the school (0x7838F3, with the
#: context 0x4039ED hands out in ecx) and the routine it calls; then the jump
#: in the menu's first step (0x69F235) that takes every entry step past 4 to
#: the end of the step, and the routine it is pointed at instead. Both
#: routines are position-dependent, like the roll's.
OMAKE_LOGOUT_HOOK = 0x783910
OMAKE_LOGOUT_HOOK_SHIPPED = "6a04e869d6ebff"   # push 4; call 0x640F80
OMAKE_LOGOUT_CODE = 0xB58F90
OMAKE_LOGOUT_ROUTINE = bytes.fromhex(
    "6a04"              # push 4                      blackboard first ...
    "8b4144"            # mov eax,[ecx+0x44]          the event being played
    "85c0740d"          # test eax,eax; jz store
    "83782806"          # cmp dword [eax+0x28],6      an おまけ replay?
    "7507"              # jne store
    "c7042405000000"    # mov dword [esp],5           ... or straight to the ゲームメニュー
    "e8d57faeff"        # store: call 0x640F80
    "c3"                # ret
)
MENU_ENTRY_JUMP = 0x69F2BC
MENU_ENTRY_JUMP_SHIPPED = "0f85c6040000"       # jne 0x69F788 (entry step past 4)
MENU_ENTRY_CODE = 0xB58FB0
MENU_ENTRY_ROUTINE = bytes.fromhex(
    "48"                # dec eax                     the entry step, less 4, less 1
    "0f85d167b4ff"      # jne 0x69F788                not 5: as it always was
    "8b45f0"            # mov eax,[ebp-0x10]          the menu
    "885844"            # mov [eax+0x44],bl           (bl is 0) the ゲームメニュー, as after 4
    "c7404007000000"    # mov dword [eax+0x40],7      step 7: the step the board's ＯＫ leads to
    "e9bf67b4ff"        # jmp 0x69F788
)

#: The twenty loads, by address, with the instruction as shipped. The paper's
#: ranking drawer (0x60CA11) reads a クラス row's eight averages and 合 first,
#: then a 個人 row's eight scores and 合.
SITES = {
    0x60CF89: "0fbe4002", 0x60D008: "0fbe4003", 0x60D08D: "0fbe4004", 0x60D112: "0fbe4005",
    0x60D197: "0fbe4006", 0x60D21C: "0fbe4007", 0x60D2A1: "0fbe4008", 0x60D326: "0fbe4009",
    0x60D3AE: "0fbe410b", 0x60D3B2: "0fbe4a0a",
    0x60D525: "0fbe4018", 0x60D5AA: "0fbe4019", 0x60D635: "0fbe401a", 0x60D6C0: "0fbe401b",
    0x60D74B: "0fbe401c", 0x60D7D6: "0fbe401d", 0x60D861: "0fbe401e", 0x60D8EC: "0fbe401f",
    0x60D97B: "0fbe4121", 0x60D97F: "0fbe4a20",
}


def offset(va: int) -> int:
    """File offset of a .text address (raw and virtual coincide there)."""
    return va - IMAGE_BASE


def as_shipped(data: bytes) -> bytes:
    """The file with the authentication address and every fix put back.

    So a copy already fixed -- by an earlier run of this tool, with or without
    the おまけ button, the 表情 photos or the Epilogue -- is recognised as the
    build it was made from.
    """
    out = bytearray(data)
    site = auth.find_site(bytes(out))
    for k, octet in enumerate(auth.parse_ipv4(auth.ORIGINAL_ADDRESS)):
        out[site + 4 + 5 * k] = octet
    for va in SITES:
        out[offset(va) + 1] = MOVSX
    at = offset(OMAKE_GATE)
    if out[at:at + 4] == bytes([NOP] * 4):
        out[at:at + 4] = bytes.fromhex(OMAKE_GATE_SHIPPED)
    for va, k in PHOTO_ROUTE_TESTS.items():
        at = offset(va)
        if out[at - 3:at] == bytes.fromhex(PHOTO_ROUTE_TEST) and out[at] == 0:
            out[at] = k
    for va, (shipped, fix) in EPILOGUE_FIX.items():
        if out[offset(va)] == fix:
            out[offset(va)] = shipped
    at = offset(RETIRE_ITEM)
    if out[at - 3:at] == bytes.fromhex(RETIRE_ITEM_INSTRUCTION) and out[at] == 1:
        out[at] = 0
    for va, (shipped, fix) in RETIRE_SLOTS.items():
        if out[offset(va):offset(va) + 4] == fix.to_bytes(4, "little"):
            out[offset(va):offset(va) + 4] = shipped.to_bytes(4, "little")
    at = offset(ROLL_ESC_HOOK)
    if out[at:at + 5] == roll_esc_jump():
        out[at:at + 5] = bytes.fromhex(ROLL_ESC_HOOK_SHIPPED)
    at = offset(ROLL_ESC_CODE)
    if out[at:at + len(ROLL_ESC_ROUTINE)] == ROLL_ESC_ROUTINE:
        out[at:at + len(ROLL_ESC_ROUTINE)] = bytes(len(ROLL_ESC_ROUTINE))
    at = offset(OMAKE_LOGOUT_HOOK)
    if out[at:at + 7] == omake_logout_call():
        out[at:at + 7] = bytes.fromhex(OMAKE_LOGOUT_HOOK_SHIPPED)
    at = offset(OMAKE_LOGOUT_CODE)
    if out[at:at + len(OMAKE_LOGOUT_ROUTINE)] == OMAKE_LOGOUT_ROUTINE:
        out[at:at + len(OMAKE_LOGOUT_ROUTINE)] = bytes(len(OMAKE_LOGOUT_ROUTINE))
    at = offset(MENU_ENTRY_JUMP)
    if out[at:at + 6] == menu_entry_jump():
        out[at:at + 6] = bytes.fromhex(MENU_ENTRY_JUMP_SHIPPED)
    at = offset(MENU_ENTRY_CODE)
    if out[at:at + len(MENU_ENTRY_ROUTINE)] == MENU_ENTRY_ROUTINE:
        out[at:at + len(MENU_ENTRY_ROUTINE)] = bytes(len(MENU_ENTRY_ROUTINE))
    return bytes(out)


def roll_esc_jump() -> bytes:
    """``jmp ROLL_ESC_CODE``, as written at ROLL_ESC_HOOK."""
    return b"\xe9" + (ROLL_ESC_CODE - (ROLL_ESC_HOOK + 5)).to_bytes(4, "little", signed=True)


def omake_logout_call() -> bytes:
    """``call OMAKE_LOGOUT_CODE; nop; nop``, as written at OMAKE_LOGOUT_HOOK."""
    rel = OMAKE_LOGOUT_CODE - (OMAKE_LOGOUT_HOOK + 5)
    return b"\xe8" + rel.to_bytes(4, "little", signed=True) + bytes([NOP] * 2)


def menu_entry_jump() -> bytes:
    """``jne MENU_ENTRY_CODE``, as written at MENU_ENTRY_JUMP."""
    rel = MENU_ENTRY_CODE - (MENU_ENTRY_JUMP + 6)
    return b"\x0f\x85" + rel.to_bytes(4, "little", signed=True)


def fixed(data: bytes, address: bytes) -> bytes:
    """The build as shipped, pointed at ``address``, with every fix made."""
    if hashlib.sha256(as_shipped(data)).hexdigest() != RETAIL_SHA256:
        raise ValueError(
            "this tmo.exe is not the build this fix was written for, or carries "
            "changes besides the authentication address -- refusing to hand it out")
    out = bytearray(as_shipped(data))
    for va, shipped in SITES.items():
        at = offset(va)
        if out[at:at + 4] != bytes.fromhex(shipped):  # pragma: no cover - hash covers it
            raise ValueError(f"unexpected instruction at {va:#x}")
        out[at + 1] = MOVZX
    at = offset(OMAKE_GATE)
    if out[at:at + 4] != bytes.fromhex(OMAKE_GATE_SHIPPED):  # pragma: no cover - hash covers it
        raise ValueError(f"unexpected instruction at {OMAKE_GATE:#x}")
    out[at:at + 4] = bytes([NOP] * 4)
    for va, k in PHOTO_ROUTE_TESTS.items():
        at = offset(va)
        if out[at - 3:at + 1] != bytes.fromhex(PHOTO_ROUTE_TEST) + bytes([k]):  # pragma: no cover - hash covers it
            raise ValueError(f"unexpected instruction at {va - 3:#x}")
        out[at] = 0
    for va, (shipped, fix) in EPILOGUE_FIX.items():
        if out[offset(va)] != shipped:  # pragma: no cover - hash covers it
            raise ValueError(f"unexpected byte at {va:#x}")
        out[offset(va)] = fix
    at = offset(RETIRE_ITEM)
    if out[at - 3:at + 1] != bytes.fromhex(RETIRE_ITEM_INSTRUCTION) + b"\x00":  # pragma: no cover - hash covers it
        raise ValueError(f"unexpected instruction at {RETIRE_ITEM - 3:#x}")
    out[at] = 1
    for va, (shipped, fix) in RETIRE_SLOTS.items():
        if out[offset(va):offset(va) + 4] != shipped.to_bytes(4, "little"):  # pragma: no cover - hash covers it
            raise ValueError(f"unexpected entry at {va:#x}")
        out[offset(va):offset(va) + 4] = fix.to_bytes(4, "little")
    at = offset(ROLL_ESC_HOOK)
    if out[at:at + 5] != bytes.fromhex(ROLL_ESC_HOOK_SHIPPED):  # pragma: no cover - hash covers it
        raise ValueError(f"unexpected instruction at {ROLL_ESC_HOOK:#x}")
    out[at:at + 5] = roll_esc_jump()
    at = offset(ROLL_ESC_CODE)
    if any(out[at:at + len(ROLL_ESC_ROUTINE)]):  # pragma: no cover - hash covers it
        raise ValueError(f"the code section's tail at {ROLL_ESC_CODE:#x} is not empty")
    out[at:at + len(ROLL_ESC_ROUTINE)] = ROLL_ESC_ROUTINE
    at = offset(OMAKE_LOGOUT_HOOK)
    if out[at:at + 7] != bytes.fromhex(OMAKE_LOGOUT_HOOK_SHIPPED):  # pragma: no cover - hash covers it
        raise ValueError(f"unexpected instruction at {OMAKE_LOGOUT_HOOK:#x}")
    out[at:at + 7] = omake_logout_call()
    at = offset(OMAKE_LOGOUT_CODE)
    if any(out[at:at + len(OMAKE_LOGOUT_ROUTINE)]):  # pragma: no cover - hash covers it
        raise ValueError(f"the code section's tail at {OMAKE_LOGOUT_CODE:#x} is not empty")
    out[at:at + len(OMAKE_LOGOUT_ROUTINE)] = OMAKE_LOGOUT_ROUTINE
    at = offset(MENU_ENTRY_JUMP)
    if out[at:at + 6] != bytes.fromhex(MENU_ENTRY_JUMP_SHIPPED):  # pragma: no cover - hash covers it
        raise ValueError(f"unexpected instruction at {MENU_ENTRY_JUMP:#x}")
    out[at:at + 6] = menu_entry_jump()
    at = offset(MENU_ENTRY_CODE)
    if any(out[at:at + len(MENU_ENTRY_ROUTINE)]):  # pragma: no cover - hash covers it
        raise ValueError(f"the code section's tail at {MENU_ENTRY_CODE:#x} is not empty")
    out[at:at + len(MENU_ENTRY_ROUTINE)] = MENU_ENTRY_ROUTINE
    site = auth.find_site(bytes(out))
    for k, octet in enumerate(address):
        out[site + 4 + 5 * k] = octet
    return bytes(out)


def find_exe(game_dir: str) -> Path:
    path = Path(game_dir).expanduser()
    if path.is_dir():
        path = path / TARGET
    if not path.is_file():
        raise SystemExit(f"no {TARGET} at {path}")
    return path


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix the client's own bugs (試験結果 page, おまけ button, 表情 photos, Epilogue, イベント中断, おまけ staff roll, あとがき after an おまけ confession), for handing out through the updater.")
    parser.add_argument("--game-dir", help="the folder that holds tmo.exe (or tmo.exe itself)")
    parser.add_argument("--address", help="the server address players' clients are pointed at")
    parser.add_argument("--update-dir", default=str(UPDATE_DIR),
                        help=f"where the updater's files live (default {UPDATE_DIR})")
    parser.add_argument("--check", action="store_true", help="say what would be written, write nothing")
    parser.add_argument("--remove", action="store_true", help="stop handing the fixed client out")
    args = parser.parse_args(argv)

    dest = Path(args.update_dir) / TARGET
    if args.remove:
        if dest.exists():
            dest.unlink()
            print(f"removed {dest}; clients that already fetched it keep it")
        else:
            print(f"nothing at {dest}")
        return 0
    if not args.game_dir or not args.address:
        parser.error("--game-dir and --address are both needed")

    source = find_exe(args.game_dir)
    shown, _resolved = auth.resolve_server(args.address)
    address = auth.parse_ipv4(shown)
    try:
        out = fixed(source.read_bytes(), address)
    except (ValueError, LookupError) as exc:
        print(f"{source}: {exc}", file=sys.stderr)
        return 1
    print(f"{source}: the shipped build; authentication address {shown}, "
          f"{len(SITES)} score loads, the おまけ button, the 表情 photos, the Epilogue, "
          f"イベント中断, the おまけ staff roll and the あとがき after leaving an おまけ "
          f"confession fixed")
    if args.check:
        print(f"would write {dest} ({len(out)} bytes, sha256 {hashlib.sha256(out).hexdigest()[:16]}…)")
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)
    print(f"wrote {dest}; every client fetches it on its next start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
