#!/usr/bin/env python3
"""Put the confession close-ups back into eleven of your copy's script files.

What is wrong
-------------
Four of the five confession scenes (Amamiya, Yayoi, Sakurai, Inukai) show an
empty background where the heroine should stand. The art is all in the client:
every one of those backgrounds has a fixed list of figure parts -- the body,
hands, hair, props -- that the client lays over it, and the staff-roll card each
scene ends on is a drawing of exactly that picture with the heroine in it. What
is missing is in the scripts. A background only gets its figure layer when the
script says how many scene effects it has, registers each part, and switches
them on; Kasuga's script does all three, and these four do none of them. So the
parts are never loaded, and the scene plays out around nobody.

Amamiya's epilogue, the scene the client plays straight after her staff roll,
is the same kind of gap at its widest. The other four epilogues each show the
heroine's own two pictures -- the scene, then a pastel copy of it for the last
line. Hers are in the client too (2012, her on the school stage, and 2013, the
pastel), along with a face overlay drawn for 2012 and two expressions for it.
Her script names neither picture: it declares one background, an underwater
view (1065) that every other epilogue declares as well and none of them shows,
loads the overlay and never switches it on. The rehearsal of the play is
spoken over the sea.

Six of her ordinary events, the fifth to the tenth, have the same hole. Every
other heroine's events show her own picture at the high point of the scene --
each script writes the same pair of player-data values and then puts the
picture up. Amamiya's six scripts write that pair too, and then put up the
same underwater view; her pictures for those events (2004-2009) are in the
client and no script names them. For the seventh to the tenth the client also
has a face overlay drawn for each picture and the expressions for it, as the
other heroines' events use theirs; none of the six scripts even declares the
overlay.

This build's own data is the defect, not the server and not the renderer, and
nothing on the wire can carry an instruction into a script the client is
already running. The fix has to be in the script files.

What this changes
-----------------
Only the four confession scripts `amm_e011`, `yyi_e011`, `skr_e011` and
`ink_e011`, the epilogue `amm_e012`, and Amamiya's events `amm_e005` to
`amm_e010`, and in each only by adding:

  * the scene-effect count on the background that needs one (it was 0);
  * a detour at a handful of instructions: the instruction is replaced by a
    jump to new code at the end of the script, which does what it did and then
    the additions -- register the parts, switch them on, change the heroine's
    expression before a line -- and jumps back;
  * in `amm_e007` to `amm_e010`, one cast entry: the face overlay for that
    event's picture, which the script's header did not declare.

No instruction moves within the code, no label is added and nothing is
removed, so every instruction keeps its number, and every jump and label its
target. The one thing that does shift is where the code starts in the file:
the cast entry is 56 bytes, so in those four scripts the code section sits 56
bytes further on, and the addresses the client reports for it change with it.
The server reads that offset from the export, which is one more reason the
exports below go with the archives. Some edits change an instruction in place
instead, at the same length: Yayoi's scene loads a
background the parts list does not cover, and is pointed at its twin (the same
picture, byte for byte) that it does; Sakurai's first shot is of her back, so
the face overlay that would land on it is replaced by switching on her body.
Amamiya's epilogue declares the stage in place of the underwater view, and
declares the pastel as a second background after it; her six events declare
their own picture in place of it.

Which parts go with which background, and which picture and overlay go with
which of Amamiya's events, are read from the client. Which expression goes
with which line, the moment Yayoi's rain clears, and the line Amamiya's
epilogue turns pastel on, are choices made
here -- the original never played these scenes, so there is nothing to recover
them from. The choices are the recipes below, and are meant to be read.

How it reaches players
----------------------
Through the game's own updater. Run this on the server's machine, against a
copy of the game:

    python3 confession_fix.py                   # writes the two halves below
    python3 confession_fix.py --check           # only says what it would do
    python3 confession_fix.py --game-dir PATH   # when the guess is wrong

  1. The eleven fixed archives go into `runtime/update/data/script/`. Every
     client that starts through BootFirst asks the server for updates first;
     this server offers whatever is in `runtime/update/`, and the client fetches
     the files that differ from its own and puts them in place.
  2. The eleven scripts are exported again, from the fixed archives, into
     `runtime/scripts/`. The server follows each scene alongside the client and
     has to be following the same script, or the scene still plays but the
     server loses track of it -- and with it the ending.

Both halves together, always. Nothing here is a general script editor: the
eleven recipes are the whole of what it does.

The archives are encrypted. Like `export_scripts.py`, this works the key out of
your own `tmo.exe` and writes it nowhere.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from export_scripts import (
    TMOC,
    Blowfish,
    Script,
    archive_scripts,
    container_cipher,
    find_game_folder,
    game_data_dirs,
    load_opcodes,
    say,
    script_ids,
    ssc_sections,
    write_exports,
)

HERE = Path(__file__).resolve().parent
UPDATE_DIR = HERE / "runtime" / "update"
SCRIPT_DIR = HERE / "runtime" / "scripts"
#: Where the client keeps scripts, relative to the game folder -- and so where
#: the fixed archives sit under the update folder.
SCRIPT_SUBDIR = Path("data") / "script"


# --------------------------------------------------------- the instructions
#
# Fixed-length commands: a little-endian u16 opcode and its operand bytes. The
# lengths agree with reference/ssc_ops.tsv; operands are written the way
# Kasuga's confession, the one that works, writes the same commands.


def op(code: int, *operand: int) -> bytes:
    return struct.pack("<H", code) + bytes(operand)


JUMP = 0x9080


def jump(ip: int) -> bytes:
    """OP_JP. The target is in 16-bit words from the start of the code."""
    return struct.pack("<HHI", JUMP, 0, ip << 12)


def call(label: int) -> bytes:
    """OP_JS, a subroutine call by label number."""
    return struct.pack("<HH", 0x9085, label)


def ret() -> bytes:
    """OP_RTN -- used only as filler after a jump, so it is never reached."""
    return op(0x9083, 0x80, 0x03)


def register(part: int) -> bytes:
    """EVENT_BG_EFFECT_INFO: register one figure part by its id."""
    return op(0x5001, 0x1F, 0, 0, 0, 0, 0, part & 0xFF, part >> 8, 0xFF, 0xFF, 0xFF, 0xFF)


def show(index: int) -> bytes:
    """EVENT_BGEFF_DISP_ON: switch on the index-th registered part."""
    return op(0x5104, index, 0)


def hide(index: int) -> bytes:
    """EVENT_BGEFF_DISP_OFF."""
    return op(0x5144, index, 0)


def animate(index: int) -> bytes:
    """EVENT_BGEFF_ANIM_ENABLE: start a registered part's animation, no wait."""
    return op(0x5105, index, 0)


def background(name: int, bg: int) -> bytes:
    """EVENT_BG_INFO: declare the next background slot.

    `name` is the place-name word as the script has it (the string's position
    in the script's pool); `bg` the picture. No weather, no scene effects.
    Slots are numbered in the order their declarations run.
    """
    return op(0x5000, 0, 0, *struct.pack("<II", name, 0), *struct.pack("<H", bg),
              0xFF, 0xFF, 0xFF, 0xFF, 0, 0)


def crossfade(slot: int) -> bytes:
    """SCREEN_CROSSFADE to a loaded background slot, no wait.

    The slot is bits 3-7 of the first operand byte: the other epilogues write
    0x10 and 0x18 to fade to their pastel in slot 2 and slot 3.
    """
    return op(0x3002, slot << 3, 0, 0, 0, 0, 0)


def bg_load(slot: int) -> bytes:
    return op(0x5100, slot, 0)


def bg_show(slot: int, *rest: int) -> bytes:
    """EVENT_BG_DISP_ON, operands after the slot copied from the script."""
    return op(0x5101, slot, *rest)


def face_load(actor: int) -> bytes:
    return op(0x5180, actor, 0)


def face_show(actor: int) -> bytes:
    return op(0x5181, actor, 0x07)


def face_hide(actor: int) -> bytes:
    return op(0x51C1, actor, 0x07)


def expression(actor: int, emotion: int, first: bool = False) -> bytes:
    """WAISTUP_EXPRESSION_CHANGE. `emotion` keys the client's emotion table.

    The second byte, 0x40, makes the script wait until the change has finished
    (the client's own debug text calls the flag "end detection"). Kasuga's
    script sets it on a scene's first change only, and so do these.
    """
    return op(0x5280, actor, 0x40 if first else 0, emotion & 0xFF, emotion >> 8)


#: A hook whose original is given as an opcode takes the whole instruction from
#: the file, after checking the opcode. Used for the spoken lines, and for the
#: background switches of Amamiya's events.
TALK = 0x5380
BG_SHOW = 0x5101


# ------------------------------------------------------------ the cast entry
#
# A script's header starts at 0x80 with a short stream of the same commands:
# the scenario, then one entry per player role and per cast member, then the
# variable declarations. A face overlay is a cast entry of its own (opcode
# 0x83, 56 bytes) naming the client's event-character record; the script's
# first one is actor 0x60. The lengths of the header's parts are kept at 0x68
# (all of them) and 0x6c (the command stream), in 4-byte words.
CAST_START = 0x80
CAST_LENGTHS = {0x0000: 12, 0x0080: 64, 0x0081: 52, 0x0082: 68, 0x0083: 56}
OVERLAY_CAST = 0x0083
OVERLAY_KIND = 0x15                 # the low four bits: an event character
HEROINE_KIND = 1
NAME_FIELD = slice(6, 0x2A)         # family name, given name, nickname


def overlay_entry(header: bytes, character: int) -> bytes:
    """A cast entry for event character `character`, named after the script's
    own entry for the heroine (the cast member whose kind is a heroine)."""
    entry = bytearray(CAST_LENGTHS[OVERLAY_CAST])
    struct.pack_into("<HH", entry, 0, OVERLAY_CAST, 0)
    entry[4] = character << 1
    at = CAST_START
    while not (struct.unpack_from("<H", header, at)[0] == 0x0081
               and struct.unpack_from("<I", header, at + 0x2C)[0] & 0xF == HEROINE_KIND):
        code = struct.unpack_from("<H", header, at)[0]
        if code not in CAST_LENGTHS:
            raise NotThisScript("no heroine in the cast")
        at += CAST_LENGTHS[code]
    entry[NAME_FIELD] = header[at + NAME_FIELD.start:at + NAME_FIELD.stop]
    struct.pack_into("<I", entry, 0x2C, OVERLAY_KIND)
    return bytes(entry)


def add_cast(ssc: bytes, entry: bytes) -> bytes:
    """`ssc` with `entry` after its last cast entry."""
    at = CAST_START
    while True:
        code = struct.unpack_from("<H", ssc, at)[0]
        if code not in CAST_LENGTHS:
            break
        if code == OVERLAY_CAST:
            raise NotThisScript("the script already declares a face overlay")
        at += CAST_LENGTHS[code]
    out = bytearray(ssc[:at] + entry + ssc[at:])
    words = len(entry) // 4
    for field in (0x68, 0x6C):
        struct.pack_into("<I", out, field, struct.unpack_from("<I", out, field)[0] + words)
    return bytes(out)


# -------------------------------------------------------------- the recipes
#
# Each recipe: `effects` -- instruction pointer of an EVENT_BG_INFO and the
# scene-effect count to give it; `swap` -- (ip, original, replacement) of the
# same length; `hooks` -- (ip, original, before, after): the original
# instructions at ip are moved to the end, with `before` ahead of them and
# `after` behind. Actor 0x60 and 0x61 are the script's first and second
# face overlays.

# Amamiya. Two shots: by the window in full (background 2010; parts 4-6 in
# front, 7-10 behind) and the close-up in white light (2011; 0xb-0xc in front,
# 0xd and 0x33-0x35 behind). The first set goes on as the window shot comes up,
# the second in the blackout before her last answer.
AMAMIYA_PARTS = [4, 5, 6, 7, 8, 9, 0xA, 0xB, 0xC, 0xD, 0x33, 0x34, 0x35]
AMAMIYA_WINDOW = range(0, 7)
AMAMIYA_LIGHT = range(7, 13)
# Expressions. Window: 14 neutral, 15 eyes closed, 16 smile, 17 lonely.
# Close-up: 18 neutral, 19 troubled, 20 lonely, 21 glad, 22 smile, 23 shy.
AMAMIYA_WINDOW_LINES = {391: 14, 407: 15, 423: 14, 439: 16, 455: 14, 471: 16, 519: 17}
AMAMIYA_LIGHT_LINES = {593: 20, 609: 23, 641: 22}

# Yayoi. One shot. The script loads slot 4 (background 2133), which has no
# parts list; slot 5 (2134) is the identical picture and has one, so both
# instructions are pointed there. 0x19 is the shafts of light, 0x1b her bust,
# 0x18 a dark silhouette over the bust that the data switches on by itself --
# it stays registered, and is taken off when she says the rain is stopping,
# where the light starts to move.
YAYOI_PARTS = [0x19, 0x1B]
YAYOI_SHADOW = 0x18
# 74 neutral, 75 lonely, 76 shy, 77 smile, 78 cheerful, 79 glad, 80 surprised,
# 81 surprised (2), 82 bashful.
YAYOI_LINES = {616: 77, 648: 74, 680: 78, 696: 74, 728: 77, 760: 75, 792: 74, 808: 82,
               824: 80, 856: 74, 888: 77, 920: 79, 968: 74, 1000: 75, 1064: 74, 1128: 76,
               1192: 80, 1224: 81, 1256: 79, 1288: 82, 1320: 77, 1352: 79, 1384: 78,
               1416: 77}
YAYOI_RAIN_STOPS = 1080

# Sakurai. Two shots: at the blackboard from behind (2192: the lectern edge 0x1d
# in front, her body 0x1f behind) and the close-up (2193: her fringe 0x20 in
# front; the body is painted into the background).
SAKURAI_PARTS = [0x1D, 0x1F, 0x20]
# 104 neutral, 105 looking away, 106 surprised, 107 smile, 108 holding back,
# 109 bashful, 110 glad, 111 troubled.
SAKURAI_LINES = {565: 109, 597: 108, 629: 104, 661: 106, 693: 107, 725: 106, 757: 111,
                 789: 105, 821: 107, 853: 109, 885: 110}

# Inukai. Of four shots, two have him in them: by the easel (2251: the covered
# easel 0x22 and his hand on the cloth 0x23) and the close-up (2252: his fringe
# 0x24). Both bodies are painted into the backgrounds.
INUKAI_PARTS = [0x22, 0x23, 0x24]
# 131 neutral, 132 smile.
INUKAI_LINES = {699: 132, 734: 131, 838: 132, 873: 131, 905: 132}

# Amamiya's epilogue: she and the hero rehearse the school play. The stage (2012)
# comes up where the underwater view did, with its overlay (the script's own
# 0x60, which it loads and never shows) on her face; for her laugh at the end
# the scene crossfades to the pastel (2013), where she laughs with her eyes
# closed. The overlay is drawn for 2012 alone, so it goes off first.
AMAMIYA_PLAY_NAME = 4               # the place-name word slot 0 already has
AMAMIYA_SEA, AMAMIYA_STAGE, AMAMIYA_PASTEL = 1065, 2012, 2013
# 24 sad, 25 smile -- the overlay's only two.
AMAMIYA_PLAY_LINES = {72: 25, 136: 24}
AMAMIYA_LAUGH = 173

# Amamiya's events 5 to 10. Each script's underwater view is declared under its
# own place name; the event's picture takes its place. Events 7 to 10 also get
# the picture's face overlay (event character 5 to 8): on where the picture
# goes up, off where the scene leaves it.
AMAMIYA_EVENT_SEA = {               # script: (ip, place name, picture)
    "amm_e005": (56, 0x14004, 2004),
    "amm_e006": (88, 0x26004, 2005),
    "amm_e007": (68, 0x17004, 2006),
    "amm_e008": (26, 0x06004, 2007),
    "amm_e009": (88, 0x21004, 2008),
    "amm_e010": (78, 0x21004, 2009),
}
# script: (event character, ip the picture goes up at, ip it is left at,
#          first expression or None, {line ip: expression}).
# 7: one expression only, the picture's own -- the overlay just blinks.
# 8: 6 neutral, 7 exasperated, 8 exasperated (2), 9 smile.
# 9: 10 shy (the picture's own face), 11 startled. Called twice; the overlay
#    goes up and down with the picture each time.
# 10: 12 neutral, 13 smile.
AMAMIYA_EVENT_FACES = {
    "amm_e007": (5, 430, 474, None, {}),
    "amm_e008": (6, 1900, 1974, 6, {1908: 7, 1924: 6, 1956: 9}),
    "amm_e009": (7, 4982, 4996, 10, {4870: 10, 4902: 10, 4934: 11, 5094: 10, 5126: 11}),
    "amm_e010": (8, 4967, 5012, 12, {4978: 13, 4994: 12}),
}


def amamiya_event(name: str) -> dict:
    ip, place, picture = AMAMIYA_EVENT_SEA[name]
    recipe = dict(effects={}, swap=[(ip, background(place, AMAMIYA_SEA),
                                     background(place, picture))], hooks=[])
    if name in AMAMIYA_EVENT_FACES:
        character, up, down, first, lines = AMAMIYA_EVENT_FACES[name]
        on = face_load(0x60) + face_show(0x60)
        if first is not None:
            on += expression(0x60, first, first=True)
        recipe["overlay"] = character
        recipe["hooks"] = [
            (up, BG_SHOW, b"", on),
            *[(line, TALK, expression(0x60, e), b"") for line, e in lines.items()],
            (down, BG_SHOW, face_hide(0x60), b""),
        ]
    return recipe


RECIPES = {
    "amm_e011": dict(
        effects={24: 7, 34: 6},
        hooks=[
            # Leaving the letter scene and loading the window background: the
            # moved instructions first, in case the call clears registrations.
            (340, call(8) + bg_load(2), b"",
             b"".join(register(p) for p in AMAMIYA_PARTS) + face_load(0x61)),
            (351, bg_show(0x22, 0, 0, 0, 0, 0, 0, 0xB0, 0x05, 0), b"",
             b"".join(show(i) for i in AMAMIYA_WINDOW) + face_show(0x60)
             + expression(0x60, 15, first=True)),
            (553, bg_show(0x23, 0, 0, 0, 0, 0, 0, 0x90, 0x24, 0), b"",
             face_hide(0x60) + b"".join(show(i) for i in AMAMIYA_LIGHT) + face_show(0x61)
             + expression(0x61, 19, first=True)),
            *[(ip, TALK, expression(0x60, e), b"") for ip, e in AMAMIYA_WINDOW_LINES.items()],
            *[(ip, TALK, expression(0x61, e), b"") for ip, e in AMAMIYA_LIGHT_LINES.items()],
        ],
    ),
    "yyi_e011": dict(
        effects={54: 3},
        swap=[(550, bg_load(4), bg_load(5)),
              (552, bg_show(0x04, 0, 0, 0, 0, 0, 0, 0xF0, 0x12, 0),
               bg_show(0x05, 0, 0, 0, 0, 0, 0, 0xF0, 0x12, 0))],
        hooks=[
            (558, face_load(0x60) + face_show(0x60),
             b"".join(register(p) for p in YAYOI_PARTS)
             + b"".join(show(i) for i in range(len(YAYOI_PARTS)))
             + register(YAYOI_SHADOW),
             expression(0x60, 74, first=True)),
            *[(ip, TALK, expression(0x60, e), b"") for ip, e in YAYOI_LINES.items()],
            (YAYOI_RAIN_STOPS, TALK, hide(2) + animate(0), b""),
        ],
    ),
    "skr_e011": dict(
        effects={24: 2, 34: 1},
        swap=[(406, face_show(0x60), show(1))],
        hooks=[
            (404, face_load(0x60) + show(1),
             b"".join(register(p) for p in SAKURAI_PARTS) + show(0), b""),
            (523, face_load(0x61) + face_show(0x61), show(2), expression(0x61, 104, first=True)),
            *[(ip, TALK, expression(0x61, e), b"") for ip, e in SAKURAI_LINES.items()],
        ],
    ),
    "ink_e011": dict(
        effects={44: 2, 54: 1},
        hooks=[
            (545, face_show(0x60) + call(5),
             b"".join(register(p) for p in INUKAI_PARTS) + show(0) + show(1), b""),
            (626, face_show(0x61) + call(5), show(2), b""),
            *[(ip, TALK, expression(0x61, e, first=(k == 0)), b"")
              for k, (ip, e) in enumerate(INUKAI_LINES.items())],
        ],
    ),
    "amm_e012": dict(
        effects={},
        swap=[(4, background(AMAMIYA_PLAY_NAME, AMAMIYA_SEA),
               background(AMAMIYA_PLAY_NAME, AMAMIYA_STAGE))],
        hooks=[
            # Right after slot 0 is declared, so the pastel is slot 1.
            (4, background(AMAMIYA_PLAY_NAME, AMAMIYA_STAGE), b"",
             background(AMAMIYA_PLAY_NAME, AMAMIYA_PASTEL)),
            (48, bg_show(0x20, 0, 0, 0, 0, 0, 0, 0x40, 0, 0), b"",
             face_show(0x60) + expression(0x60, 24, first=True)),
            *[(ip, TALK, expression(0x60, e), b"") for ip, e in AMAMIYA_PLAY_LINES.items()],
            (AMAMIYA_LAUGH, TALK, face_hide(0x60) + bg_load(1) + crossfade(1), b""),
        ],
    ),
    **{name: amamiya_event(name) for name in AMAMIYA_EVENT_SEA},
}

BG_INFO = 0x5000
EFFECT_COUNT_MASK = 0x3F


# ------------------------------------------------------------ the procedure


class NotThisScript(Exception):
    """The file is not the script the recipe was written against."""


def already_fixed(ssc: bytes, recipe: dict) -> bool:
    """True when every background the recipe gives effects to already has them,
    or, for a recipe that gives none, when its first detour -- or, with no
    detours, its first in-place edit -- is already there."""
    sec = ssc_sections(ssc)
    code = ssc[sec["code"]:sec["aux"]]
    if not recipe["effects"] and not recipe["hooks"]:
        ip, _original, replacement = recipe["swap"][0]
        return code[2 * ip:2 * ip + len(replacement)] == replacement
    if not recipe["effects"]:
        return struct.unpack_from("<H", code, 2 * recipe["hooks"][0][0])[0] == JUMP
    counts = [struct.unpack_from("<I", code, 2 * ip + 8)[0] & EFFECT_COUNT_MASK
              for ip in recipe["effects"]]
    return all(counts)


def apply_recipe(ssc: bytes, recipe: dict, lengths: dict[int, int]) -> bytes:
    """The script with the recipe applied, or NotThisScript."""
    sec = ssc_sections(ssc)
    if sec is None:
        raise NotThisScript("not a scenario script")
    code = bytearray(ssc[sec["code"]:sec["aux"]])

    def expect(ip: int, original: bytes) -> None:
        here = bytes(code[2 * ip:2 * ip + len(original)])
        if here != original:
            raise NotThisScript(f"ip {ip} holds {here.hex()}, expected {original.hex()}")

    for ip, count in recipe["effects"].items():
        if struct.unpack_from("<H", code, 2 * ip)[0] != BG_INFO:
            raise NotThisScript(f"ip {ip} is not a background declaration")
        value = struct.unpack_from("<I", code, 2 * ip + 8)[0]
        if value & EFFECT_COUNT_MASK:
            raise NotThisScript(f"ip {ip} already declares scene effects")
        struct.pack_into("<I", code, 2 * ip + 8, (value & ~EFFECT_COUNT_MASK) | count)

    for ip, original, replacement in recipe.get("swap", ()):
        expect(ip, original)
        code[2 * ip:2 * ip + len(original)] = replacement

    for ip, original, before, after in recipe["hooks"]:
        if isinstance(original, int):
            if struct.unpack_from("<H", code, 2 * ip)[0] != original:
                raise NotThisScript(f"ip {ip} is not opcode {original:#06x}")
            original = bytes(code[2 * ip:2 * ip + lengths[original]])
        expect(ip, original)
        n = len(original)
        # A jump is eight bytes; whatever is left over is filled with returns,
        # which nothing reaches because the jump comes first.
        if n < 8 or (n - 8) % 4:
            raise NotThisScript(f"ip {ip}: {n} bytes cannot hold the jump")
        code += bytes(-len(code) % 4)
        start = len(code) // 2
        code += before + original + after + jump(ip + n // 2)
        code[2 * ip:2 * ip + n] = jump(start) + ret() * ((n - 8) // 4)
    code += bytes(-len(code) % 4)

    header = bytearray(ssc[sec["hdr"]:sec["code"]])
    words = len(code) // 4
    struct.pack_into("<II", header, 0, 4 + words + sec["aux_dw"] + sec["pool_dw"], words)
    fixed = ssc[:sec["hdr"]] + bytes(header) + bytes(code) + ssc[sec["aux"]:]
    if ssc_sections(fixed)["code"] != sec["code"]:
        raise NotThisScript("the code would move")              # pragma: no cover
    if "overlay" in recipe:
        entry = overlay_entry(ssc, recipe["overlay"])
        fixed = add_cast(fixed, entry)
        if ssc_sections(fixed)["code"] != sec["code"] + len(entry):
            raise NotThisScript("the cast entry did not land")  # pragma: no cover
    return fixed


def open_archive(blob: bytes, cipher: Blowfish, iv: bytes):
    """`(entry record offset, data offset, script, padding)` of a one-script archive.

    The padding is what followed the script inside its last cipher block; it
    is kept so that an archive put back unchanged comes out byte for byte.
    """
    table, size = struct.unpack_from("<II", blob, 4)
    if blob[:4] != b"ARC0" or size != 32:
        raise NotThisScript("not a one-script archive")
    data_at, stored = struct.unpack_from("<II", blob, table + 0x10)
    payload = blob[data_at:data_at + stored]
    if payload[:4] != TMOC:
        raise NotThisScript("not enciphered")
    plain_len, cipher_len = struct.unpack_from("<II", payload, 4)
    plain = cipher.cbc(payload[12:12 + cipher_len], iv)
    return table, data_at, plain[:plain_len], plain[plain_len:]


def seal_archive(blob: bytes, table: int, data_at: int, ssc: bytes, padding: bytes,
                 cipher: Blowfish, iv: bytes) -> bytes:
    """The archive with `ssc` in place of its script, enciphered again."""
    pad = -len(ssc) % 8
    body = cipher.cbc_encrypt(ssc + (padding + bytes(8))[:pad], iv)
    payload = TMOC + struct.pack("<II", len(ssc), len(body)) + body
    region = payload + bytes(-len(payload) % 0x800)     # the data region is 2 KiB aligned
    out = bytearray(blob[:data_at]) + region
    struct.pack_into("<II", out, table + 0x14, len(payload), len(ssc))
    struct.pack_into("<I", out, 0x20, len(region))
    return bytes(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix the confession scenes, for handing out through the updater.")
    parser.add_argument("--game-dir", help="the folder that holds tmo.exe")
    parser.add_argument("--check", action="store_true",
                        help="say what would be written, write nothing")
    parser.add_argument("--update-dir", default=str(UPDATE_DIR),
                        help=f"where the fixed archives go, as the game folder (default {UPDATE_DIR})")
    parser.add_argument("--scripts-dir", default=str(SCRIPT_DIR),
                        help=f"where the server's exports go (default {SCRIPT_DIR})")
    parser.add_argument("--key", help="16-byte container key, hex")
    parser.add_argument("--iv", help="8-byte container IV, hex")
    args = parser.parse_args(argv)

    folder = find_game_folder(args.game_dir)
    script_dir, idlist_dir = game_data_dirs(folder)
    archives = archive_scripts(script_dir)
    key, iv = container_cipher(folder, archives, args.key, args.iv)
    cipher = Blowfish(key)
    ids = script_ids(idlist_dir, cipher, iv)
    ops = load_opcodes()
    lengths = {code: size for code, (size, _name) in ops.items()}

    archive_out = Path(args.update_dir) / SCRIPT_SUBDIR
    scripts_out = Path(args.scripts_dir)
    failed = 0
    for name, recipe in RECIPES.items():
        path = archives.get(name)
        if path is None:
            say(f"  ? {name}: your copy has no such script")
            failed += 1
            continue
        blob = path.read_bytes()
        try:
            table, data_at, ssc, padding = open_archive(blob, cipher, iv)
            if already_fixed(ssc, recipe):
                # A copy this server has already updated: hand it out as it is.
                fixed_ssc, fixed_blob, how = ssc, blob, "already fixed in your copy"
            else:
                fixed_ssc = apply_recipe(ssc, recipe, lengths)
                fixed_blob = seal_archive(blob, table, data_at, fixed_ssc, padding, cipher, iv)
                how = f"{len(ssc)} -> {len(fixed_ssc)} bytes of script"
            script = Script(name, fixed_ssc, ops)
        except (NotThisScript, ValueError, KeyError, struct.error, IndexError) as exc:
            say(f"  ! {name}: {exc}")
            failed += 1
            continue
        say(f"  {name}: {how}, archive {len(fixed_blob)} bytes")
        if args.check:
            continue
        archive_out.mkdir(parents=True, exist_ok=True)
        (archive_out / path.name).write_bytes(fixed_blob)
        scripts_out.mkdir(parents=True, exist_ok=True)
        write_exports(scripts_out, script, ids.get(f"{name}.ssb"))

    if not args.check and not failed:
        say(f"  archives in {archive_out}")
        say(f"  exports in {scripts_out}")
        say("  the server reads the exports as each scene starts; clients pick "
            "the archives up the next time they start")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
