#!/usr/bin/env python3
"""Put the confession close-ups back into twenty-two of your copy's script files.

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

Kasuga's close-up does get its figure, and shows it wrong. This client draws
every part a script registers until the script switches it off, and her script
switches on only the parts it wants: so all three of her poses are up at once,
and over them seven frames of her with her eyes shut that the script means
only for the moments it animates them. Her face, with its expressions, is
under those frames; the scene plays with her eyes shut and two heads of hair.
Her staff-roll card has her looking out of the same picture.

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

The title screen's おまけ menu replays each heroine's confession and epilogue
from its own copies of the two scripts, `<name>_o011` and `<name>_o012` --
the same lines with the letter and the choice cut out. The copies carry the
same holes and some of their own: where the heroine's picture should be,
they mostly declare the underwater view, Sakurai's confession declares
nothing else and never puts up a picture or opens the window, and Yayoi's
puts her scene and the place before it under the sea. Kasuga's has her
confession's parts and its fault, and also leaves the count that lets the
client load the parts at 0, and never loads the face overlay it shows.

This build's own data is the defect, not the server and not the renderer, and
nothing on the wire can carry an instruction into a script the client is
already running. The fix has to be in the script files.

The title screen's おまけ gallery has a hole of the same kind, in a table
rather than a script. Each heroine has nine scenes there, and each opens to a
full-size picture looked up in `gallery.bin` by heroine and scene. Only the
first three scenes have a picture in that table; for the other six the entry
is empty, and the viewer draws the empty entry -- a black screen -- where the
scene's thumbnail promised a picture. The pictures are the events' own: the
three that are filled are each event's CG or a copy of it with the face
redrawn, and one of them (Inukai's second) names the event CG itself. So the
six empty entries per heroine get the CG of that event, which the client has.

What this changes
-----------------
Only the five confession scripts `amm_e011`, `ksg_e011`, `yyi_e011`,
`skr_e011` and `ink_e011`, the epilogue `amm_e012`, Amamiya's events
`amm_e005` to `amm_e010`, and the ten replay copies `<name>_o011` and
`<name>_o012`, and in each only by adding:

  * the scene-effect count on the background that needs one (it was 0);
  * a detour at a handful of instructions: the instruction is replaced by a
    jump to new code at the end of the script, which does what it did and then
    the additions -- register the parts, switch them on or off, change the
    heroine's expression before a line -- and jumps back;
  * in `amm_e007` to `amm_e010`, one cast entry: the face overlay for that
    event's picture, which the script's header did not declare.

And `gallery.bin`, inside `idlist.arc`: thirty empty picture entries (five
heroines, scenes 5 to 10) are filled with the event CG of that scene, in the
first six of each entry's twelve places -- one per expression. The first is
the one the viewer opens a scene on; the other five are where its 表情 button
would step to, and an event that has one picture shows that one picture
there too, so the button -- enabled only when the next picture differs from
the first -- stays grey instead of opening onto black. Every other byte of the archive stays as it is,
including every other table in it; the one that says which version of the game
this is (`property_text.bin`) is not touched.

No instruction moves within the code, no label is added and nothing is
removed, so every instruction keeps its number, and every jump and label its
target. The one thing that does shift is where the code starts in the file:
the cast entry is 56 bytes, so in those four scripts the code section sits 56
bytes further on, and the addresses the client reports for it change with it.
The server reads that offset from the export, which is one more reason the
exports below go with the archives. Some edits change an instruction in place
instead, at the same length: Yayoi's scene loads a
background the parts list does not cover, and is pointed at its twin (the same
picture, byte for byte) that it does; Sakurai's first shot is of his back, so
the face overlay that would land on it is replaced by switching on his body.
Amamiya's epilogue declares the stage in place of the underwater view, and
declares the pastel as a second background after it; her six events declare
their own picture in place of it, and so do the replays, each with the
picture its scene shows in the full script. Sakurai's and Yayoi's replays
declare one more background after their last, as her epilogue does.

Which parts go with which background, and which picture and overlay go with
which of Amamiya's events, are read from the client. Which expression goes
with which line, the moment Yayoi's rain clears, and the line Amamiya's
epilogue turns pastel on, are choices made
here -- the original never played these scenes, so there is nothing to recover
them from. The replays make the same choices for the same lines, and where a
replay has lost a cut its full script makes (Amamiya's close-up, every shot
of Sakurai's, Yayoi's shelter from the rain), the cut is put back the way the
full script has it. The choices are the recipes below, and are meant to be
read.

How it reaches players
----------------------
Through the game's own updater. Run this on the server's machine, against a
copy of the game:

    python3 confession_fix.py                   # writes the two halves below
    python3 confession_fix.py --check           # only says what it would do
    python3 confession_fix.py --game-dir PATH   # when the guess is wrong

  1. The twenty-two fixed archives go into `runtime/update/data/script/`. Every
     client that starts through BootFirst asks the server for updates first;
     this server offers whatever is in `runtime/update/`, and the client fetches
     the files that differ from its own and puts them in place.
  2. The twenty-two scripts are exported again, from the fixed archives, into
     `runtime/scripts/`. The server follows each scene alongside the client and
     has to be following the same script, or the scene still plays but the
     server loses track of it -- and with it the ending.
  3. The fixed `idlist.arc` goes into `runtime/update/data/idlist/`. The server
     reads nothing from it, so there is no export to go with it.

Both halves together, always. Nothing here is a general script or table
editor: the twenty-two recipes and the thirty pictures are the whole of what it
does.

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
    _sjis,
    arc_entries,
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
#: And the index tables, the same way.
IDLIST_SUBDIR = Path("data") / "idlist"


# --------------------------------------------------------- the instructions
#
# Fixed-length commands: a little-endian u16 opcode and its operand bytes. The
# lengths agree with reference/ssc_ops.tsv; operands are written the way
# Kasuga's confession, whose figure loads, writes the same commands.


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


def background(name: int, bg: int, effects: int = 0) -> bytes:
    """EVENT_BG_INFO: declare the next background slot.

    `name` is the place-name word as the script has it (the string's position
    in the script's pool); `bg` the picture; `effects` the scene-effect count.
    No weather. Slots are numbered in the order their declarations run.
    """
    return op(0x5000, 0, 0, *struct.pack("<II", name, effects), *struct.pack("<H", bg),
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
    """EVENT_BG_DISP_ON, operands after the slot copied from the script.

    With none given, the slot byte has 0x20 set and the rest is zero: no
    place-name plate, and nothing else read from the script's tables.
    """
    if not rest:
        return op(0x5101, slot | 0x20, *bytes(9))
    return op(0x5101, slot, *rest)


def bg_off() -> bytes:
    """EVENT_BG_DISP_OFF."""
    return op(0x5141)


def black_out(speed: int = 2) -> bytes:
    """SCREEN_BLACK_OUT, waiting until it is done -- the scripts' 0x40."""
    return op(0x3040, speed, 0x40)


def black_in(speed: int = 2) -> bytes:
    return op(0x3000, speed, 0x40)


def white_out(speed: int = 2) -> bytes:
    return op(0x3041, speed, 0x40)


def white_in(speed: int = 2) -> bytes:
    return op(0x3001, speed, 0x40)


def window_open() -> bytes:
    """EVENT_WINDOW_OPEN, as every script writes it."""
    return op(0x2000, 2, 0, 0, 0, 0, 0)


def window_close() -> bytes:
    return op(0x2001, 0, 0)


def event_screen() -> bytes:
    """BG_PAGE_RANGE and SCREEN_CHANGE_WAISTUP: what every scene's first
    subroutine does before it puts anything up."""
    return op(0x1180, 0x10, 0) + op(0x3081)


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
# `after` behind. A hook with a fifth element moves that instead of the
# original: the original with something put in the middle of it. Actor 0x60
# and 0x61 are the script's first and second face overlays.

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


# The おまけ ending replay. It plays its own copies of each confession and
# epilogue, `<name>_o011` and `<name>_o012`: the same lines, cut down -- no
# letter, no choice, no player data -- so the instruction numbers are not the
# ones above, and each recipe is written again against its own script. The
# expressions are the ones chosen for the same lines in the scenes above.
#
# Where a replay puts up a picture of the heroine, its script mostly declares
# the underwater view (1065) in its place -- in some scripts for every slot.
# Those declarations name the right picture instead; the face overlays these
# scripts load and show were drawn for those pictures (the client's event-
# character table says which picture each is for), so they land where they
# should once the picture is there.
UNDERWATER = AMAMIYA_SEA

# Amamiya's confession. Both shots are declared, without scene effects; the
# window shot is shown with its overlay switched on and nothing else, and the
# script never cuts to the close-up: the blackout before her last answer is
# gone, with the close-up's slot left declared and unused. It comes back as in
# her confession, before the same line.
AMAMIYA_REPLAY_WINDOW_LINES = {91: 14, 107: 15, 123: 14, 139: 16, 155: 14, 171: 16, 219: 17}
AMAMIYA_REPLAY_LIGHT_LINES = {283: 20, 299: 23, 331: 22}
AMAMIYA_REPLAY_CUT = 251            # 「……いいえっ！」

# Yayoi's confession. Both slots are the underwater view. The first is the
# notice board where the hero waits (85); the cut to the bicycle shed where he
# shelters from the rain (78) is a blackout with no new picture in it, and
# gets one, in a third slot. The second slot is her scene: 2134, the twin of
# the confession's first picture that has a parts list (see YAYOI_PARTS).
# The board and her scene go up with the place-name plate off, as the
# epilogues below do, for the same reason.
YAYOI_BOARD, YAYOI_SHED, YAYOI_RAIN = 85, 78, 2134
YAYOI_REPLAY_LINES = {221: 77, 253: 74, 285: 78, 301: 74, 333: 77, 365: 75, 397: 74, 413: 82,
                      429: 80, 461: 74, 493: 77, 525: 79, 573: 74, 605: 75, 669: 74, 733: 76,
                      797: 80, 829: 81, 861: 79, 893: 82, 925: 77, 957: 79, 989: 78, 1021: 77}
YAYOI_REPLAY_RAIN_STOPS = 685

# Sakurai's confession has nothing but its lines: one slot, the underwater
# view, never loaded or shown; no window, no fade. The staging is his
# confession's: his back at the blackboard (2192), then a white flash to the
# close-up (2193) for「$m00さん、オレと一緒にいてください」, and a blackout at
# the end.
SAKURAI_REPLAY_LINES = {148: 109, 180: 108, 212: 104, 244: 106, 276: 107, 308: 106, 340: 111,
                        372: 105, 404: 107, 436: 109, 468: 110}
SAKURAI_REPLAY_OPEN, SAKURAI_REPLAY_CUT, SAKURAI_REPLAY_LAST = 20, 116, 484

# Inukai's confession is staged as his is, with the same gap.
INUKAI_REPLAY_LINES = {337: 132, 372: 131, 476: 132, 511: 131, 543: 132}

# The epilogues each declare the underwater view for the heroine's picture.
# Each takes the picture its own epilogue shows (Kasuga 2074, Yayoi 2136,
# Sakurai 2194, Inukai 2254); they end on a sepia of it rather than on the
# pastel, which is these scripts' own way of ending and stays. Amamiya's is
# fixed as her epilogue is.
#
# The declarations keep the place name they had, 「海の中」, and these scripts
# put their pictures up with the place-name plate on: so the plate goes off
# where the picture goes up (0x20 in the slot byte, as Amamiya's scenes have
# it). The full scripts name these slots with an empty string, which none of
# the replays has to hand.
REPLAY_EPILOGUES = {                # script: (ip, place name, picture,
    "ksg_o012": (14, 0x3004, 2074,  #          ip it goes up at, its operands)
                 271, (0x01, 0, 0, 0, 0, 0, 0, 0x00, 0x14, 0)),
    "yyi_o012": (26, 0x7004, 2136,
                 230, (0x02, 0, 0, 0, 0, 0, 0, 0x50, 0x11, 0)),
    "skr_o012": (14, 0x8004, 2194,
                 457, (0x01, 0, 0, 0, 0, 0, 0, 0xF0, 0x27, 0)),
    "ink_o012": (4, 0x0004, 2254,
                 37, (0x00, 0, 0, 0, 0, 0, 0, 0x40, 0x00, 0)),
}
PLATE_OFF = 0x20


def plate_off(ip: int, operands: tuple) -> tuple:
    """A swap: the same EVENT_BG_DISP_ON without its place-name plate."""
    slot, *rest = operands
    return (ip, bg_show(slot, *rest), bg_show(slot | PLATE_OFF, *rest))


# Kasuga's close-up on the sunflowers (2073) has twenty-one parts, and both
# her confession and its replay register them all and switch them line by
# line. (The replay alone leaves the sunflowers' count at 0.) Two things still
# keep her face from showing, in both:
#
#   * This client draws every registered part until it is switched off, and
#     the scripts switch on only what they want. So the whole set stays up at
#     once: the three poses of hair and body, and on top of them the seven
#     frames of her eyes-shut figure, which the scripts mean only for the
#     moments their animations play. The face overlay is under that figure.
#     When the sunflowers go up, everything but the first pose (without its
#     blush, as the scripts first show it) is switched off.
#     In registration order the parts are 0-2 the first pose, 3-5 the second,
#     6-8 the third, 9-10 the ribbon and collar, 11-17 the eyes-shut frames and
#     18-20 a blush for each pose; her confession registers one part for the
#     picture before first, so there each number is one more.
#   * Between two poses the script switches the old one off, changes the
#     expression -- which waits for the overlay -- and only then switches the
#     new one on, so for a moment there is a face and no head. The change goes
#     in after the line before it instead, with the old pose off and the new
#     on straight after; the script's own switches then find it done.
#
# And the replay shows the face overlay without ever loading it; her
# confession loads it right after putting up the sunflowers, and so does this.
KASUGA_PARTS = 21
KASUGA_POSES = ((0, 1, 2, 18), (3, 4, 5, 19), (6, 7, 8, 20))
KASUGA_POSE_CHANGES = (             # emotion, from, to; the first has no blush
    (52, 0, 1), (51, 1, 0), (53, 0, 1), (56, 1, 2), (48, 2, 0),
    (54, 0, 1), (50, 1, 0), (54, 0, 1), (48, 1, 0),
)
#: script: (the sunflowers go up, the line before each change, the first part)
KASUGA_CLOSE_UP = {
    "ksg_e011": (575, (718, 834, 994, 1029, 1064, 1153, 1204, 1255, 1306), 1),
    "ksg_o011": (191, (339, 455, 615, 650, 685, 774, 825, 876, 927), 0),
}


def kasuga_close_up(name: str, load: bytes = b"") -> list:
    """The detours for one of the two scripts; `load` goes in first."""
    up, lines, first = KASUGA_CLOSE_UP[name]
    hidden = [i for i in range(KASUGA_PARTS) if i not in KASUGA_POSES[0][:3]]
    hooks = [(up, BG_SHOW, b"", load + b"".join(hide(first + i) for i in hidden))]
    for k, (ip, (emotion, old, new)) in enumerate(zip(lines, KASUGA_POSE_CHANGES)):
        off, on = KASUGA_POSES[old], KASUGA_POSES[new]
        if k == 0:
            off, on = off[:3], on[:3]
        hooks.append((ip, TALK, b"", expression(0x60, emotion)
                      + b"".join(hide(first + i) for i in off)
                      + b"".join(show(first + i) for i in on)))
    return hooks


# Amamiya's epilogue: the same as hers, at its own instruction numbers. The
# script already shows the overlay; her first expression goes in after it.
AMAMIYA_REPLAY_PLAY_LINES = {66: 25, 130: 24}
AMAMIYA_REPLAY_LAUGH = 167


def replay_epilogue(name: str) -> dict:
    ip, place, picture, up, operands = REPLAY_EPILOGUES[name]
    return dict(effects={}, swap=[(ip, background(place, UNDERWATER),
                                   background(place, picture)),
                                  plate_off(up, operands)], hooks=[])


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
    "ksg_e011": dict(effects={}, hooks=kasuga_close_up("ksg_e011")),
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
    "amm_o011": dict(
        effects={4: 7, 14: 6},
        hooks=[
            # The window shot's slot is loaded here; the close-up's is not
            # loaded anywhere, so it is loaded here too.
            (40, call(4) + bg_load(0), b"",
             b"".join(register(p) for p in AMAMIYA_PARTS) + face_load(0x61) + bg_load(1)),
            (49, bg_show(0x20, 0, 0, 0, 0, 0, 0, 0x20, 0, 0), b"",
             b"".join(show(i) for i in AMAMIYA_WINDOW)),
            # The script shows the overlay itself; her first expression goes
            # between that and the fade-in.
            (55, face_show(0x60) + call(7), b"", b"",
             face_show(0x60) + expression(0x60, 15, first=True) + call(7)),
            (AMAMIYA_REPLAY_CUT, TALK,
             black_out(3) + bg_show(1) + face_hide(0x60)
             + b"".join(show(i) for i in AMAMIYA_LIGHT) + face_show(0x61)
             + expression(0x61, 19, first=True) + black_in(3), b""),
            *[(ip, TALK, expression(0x60, e), b"") for ip, e in AMAMIYA_REPLAY_WINDOW_LINES.items()],
            *[(ip, TALK, expression(0x61, e), b"") for ip, e in AMAMIYA_REPLAY_LIGHT_LINES.items()],
        ],
    ),
    "ksg_o011": dict(effects={14: 21}, hooks=kasuga_close_up("ksg_o011", face_load(0x60))),
    "yyi_o011": dict(
        effects={},
        swap=[(4, background(0x0004, UNDERWATER), background(0x0004, YAYOI_BOARD)),
              (14, background(0x4004, UNDERWATER),
               background(0x4004, YAYOI_RAIN, effects=len(YAYOI_PARTS) + 1)),
              plate_off(38, (0x00, 0, 0, 0, 0, 0, 0, 0x80, 0x00, 0)),
              plate_off(161, (0x01, 0, 0, 0, 0, 0, 0, 0x50, 0x0A, 0))],
        hooks=[
            # The shed, as slot 2.
            (14, background(0x4004, YAYOI_RAIN, effects=len(YAYOI_PARTS) + 1), b"",
             background(0x4004, YAYOI_SHED)),
            (84, black_out() + black_in(), b"", b"",
             black_out() + bg_off() + bg_load(2) + bg_show(2) + black_in()),
            (161, bg_show(0x21, 0, 0, 0, 0, 0, 0, 0x50, 0x0A, 0), b"",
             b"".join(register(p) for p in YAYOI_PARTS)
             + b"".join(show(i) for i in range(len(YAYOI_PARTS)))
             + register(YAYOI_SHADOW) + face_load(0x60) + face_show(0x60)
             + expression(0x60, 74, first=True)),
            *[(ip, TALK, expression(0x60, e), b"") for ip, e in YAYOI_REPLAY_LINES.items()],
            (YAYOI_REPLAY_RAIN_STOPS, TALK, hide(2) + animate(0), b""),
        ],
    ),
    "skr_o011": dict(
        effects={},
        swap=[(4, background(0x0004, UNDERWATER), background(0x0004, 2192, effects=2))],
        hooks=[
            (4, background(0x0004, 2192, effects=2), b"", background(0x0004, 2193, effects=1)),
            (SAKURAI_REPLAY_OPEN, TALK,
             event_screen() + black_out() + bg_load(0) + bg_show(0)
             + b"".join(register(p) for p in SAKURAI_PARTS) + show(0) + show(1)
             + black_in() + window_open(), b""),
            (SAKURAI_REPLAY_CUT, TALK,
             window_close() + white_out() + bg_off() + bg_load(1) + bg_show(1) + show(2)
             + face_load(0x61) + face_show(0x61) + expression(0x61, 104, first=True)
             + white_in() + window_open(), b""),
            *[(ip, TALK, expression(0x61, e), b"") for ip, e in SAKURAI_REPLAY_LINES.items()],
            (SAKURAI_REPLAY_LAST, TALK, b"",
             window_close() + black_out(0) + bg_off() + face_hide(0x61)),
        ],
    ),
    "ink_o011": dict(
        effects={24: 2, 34: 1},
        hooks=[
            (183, face_show(0x60) + call(8),
             b"".join(register(p) for p in INUKAI_PARTS) + show(0) + show(1), b""),
            (264, face_show(0x61) + call(8), show(2), b""),
            *[(ip, TALK, expression(0x61, e, first=(k == 0)), b"")
              for k, (ip, e) in enumerate(INUKAI_REPLAY_LINES.items())],
        ],
    ),
    "amm_o012": dict(
        effects={},
        swap=[(4, background(AMAMIYA_PLAY_NAME, UNDERWATER),
               background(AMAMIYA_PLAY_NAME, AMAMIYA_STAGE))],
        hooks=[
            (4, background(AMAMIYA_PLAY_NAME, AMAMIYA_STAGE), b"",
             background(AMAMIYA_PLAY_NAME, AMAMIYA_PASTEL)),
            (46, face_show(0x60) + call(4), b"", b"",
             face_show(0x60) + expression(0x60, 24, first=True) + call(4)),
            *[(ip, TALK, expression(0x60, e), b"") for ip, e in AMAMIYA_REPLAY_PLAY_LINES.items()],
            (AMAMIYA_REPLAY_LAUGH, TALK, face_hide(0x60) + bg_load(1) + crossfade(1), b""),
        ],
    ),
    **{name: replay_epilogue(name) for name in REPLAY_EPILOGUES},
}

BG_INFO = 0x5000
EFFECT_COUNT_MASK = 0x3F


# ------------------------------------------------------ the おまけ gallery
#
# `gallery.bin` is one of the index tables in `idlist.arc`: `IdBn`, a count at
# +4, the record length at +0x10, records from +0x20. A record is
#
#     u16 key; u16 npcId; u16 slot; u16 photo[2][6]; u16 staffRoll[2]
#
# with npcId the heroine's index (天宮 0 .. 犬飼 4), slot 2..10 the picture's
# place on the page -- slot n is her event n, which the page labels
# Scene:0(n-1) -- and each photo a key of `bg.bin`, 0xffff where there is
# none. The viewer looks a picture up by (npcId, slot) and opens a scene on
# photo[0][0]; 表情 steps on to the next expression the server lights, and is
# enabled only when that photo differs from the first (see
# server/mps_session.py, GALLERY_EMOTION). These scenes have one picture, so
# all six route-0 places get it: whatever expressions the server lights, the
# next photo is the same one and the button stays grey.

IDLIST_ARCHIVE = "idlist.arc"
GALLERY_TABLE = "gallery.bin"
BG_TABLE = "bg.bin"
NO_PHOTO = 0xFFFF
PHOTO_AT = 6
#: photo[0][0..5]: the route-0 group, one place per expression.
PHOTO_PLACES = 6

#: npcId: (family name, {slot: the event CG, a `bg.bin` key}). Each key is
#: checked against the name `bg.bin` gives it, 「<family name>イベント<slot>」,
#: before anything is written. Two keys are stepped over because the client
#: has a picture in the way: 2129 is Yayoi's eighth from behind
#: (弥生イベント８振り向き), and 2190 is a withdrawn one (欠番・桜井イベント９).
GALLERY_PHOTOS = {
    0: ("天宮", {5: 2004, 6: 2005, 7: 2006, 8: 2007, 9: 2008, 10: 2009}),
    1: ("春日", {5: 2066, 6: 2067, 7: 2068, 8: 2069, 9: 2070, 10: 2071}),
    2: ("弥生", {5: 2125, 6: 2126, 7: 2127, 8: 2128, 9: 2130, 10: 2131}),
    3: ("桜井", {5: 2185, 6: 2186, 7: 2187, 8: 2188, 9: 2189, 10: 2191}),
    4: ("犬飼", {5: 2244, 6: 2245, 7: 2246, 8: 2247, 9: 2248, 10: 2249}),
}
_FULL_WIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


# ------------------------------------------------------------ the procedure


class NotThisScript(Exception):
    """The file is not the script the recipe was written against."""


def already_fixed(ssc: bytes, recipe: dict) -> bool:
    """True when every background the recipe gives effects to already has them
    and its first detour is already there; with no detours, when its first
    in-place edit is."""
    sec = ssc_sections(ssc)
    code = ssc[sec["code"]:sec["aux"]]
    if not recipe["effects"] and not recipe["hooks"]:
        ip, _original, replacement = recipe["swap"][0]
        return code[2 * ip:2 * ip + len(replacement)] == replacement
    counts = [struct.unpack_from("<I", code, 2 * ip + 8)[0] & EFFECT_COUNT_MASK
              for ip in recipe["effects"]]
    detoured = (not recipe["hooks"]
                or struct.unpack_from("<H", code, 2 * recipe["hooks"][0][0])[0] == JUMP)
    return all(counts) and detoured


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
        if value & EFFECT_COUNT_MASK == count:
            continue            # a copy an earlier version of this tool fixed
        if value & EFFECT_COUNT_MASK:
            raise NotThisScript(f"ip {ip} already declares scene effects")
        struct.pack_into("<I", code, 2 * ip + 8, (value & ~EFFECT_COUNT_MASK) | count)

    for ip, original, replacement in recipe.get("swap", ()):
        expect(ip, original)
        code[2 * ip:2 * ip + len(original)] = replacement

    for ip, original, before, after, *moved in recipe["hooks"]:
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
        code += before + (moved[0] if moved else original) + after + jump(ip + n // 2)
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


def _entry_at(blob: bytes, wanted: str) -> tuple[int, int]:
    """`(data offset, stored size)` of the archive entry whose file name is `wanted`."""
    table, size = struct.unpack_from("<II", blob, 4)
    for i in range(size // 32):
        _, _, name_at, name_len, data_at, stored, _, _ = struct.unpack_from(
            "<8I", blob, table + i * 32)
        name = blob[name_at:name_at + name_len].split(b"\0")[0].decode("ascii", "replace")
        if Path(name).name == wanted:
            return data_at, stored
    raise NotThisScript(f"no {wanted} in it")


def _open_table(payload: bytes, cipher: Blowfish, iv: bytes) -> bytes:
    if payload[:4] != TMOC:
        raise NotThisScript("not enciphered")
    plain_len, cipher_len = struct.unpack_from("<II", payload, 4)
    plain = cipher.cbc(payload[12:12 + cipher_len], iv)[:plain_len]
    if plain[:4] != b"IdBn":
        raise NotThisScript("not an index table")
    return plain


def _rows(table: bytes):
    """`(offset, record)` for every record of an `IdBn` table."""
    count = struct.unpack_from("<I", table, 4)[0]
    length = struct.unpack_from("<H", table, 0x10)[0]
    for i in range(count):
        at = 0x20 + i * length
        yield at, table[at:at + length]


def bg_names(blob: bytes, cipher: Blowfish, iv: bytes) -> dict[int, str]:
    """`{key: name}` from `bg.bin`, to check the recipe against."""
    for name, payload in arc_entries(blob):
        if Path(name).name == BG_TABLE:
            table = _open_table(payload, cipher, iv)
            name_at, name_len = struct.unpack_from("<HH", table, 0x0C)
            return {int.from_bytes(r[:name_at], "little"): _sjis(r[name_at:name_at + name_len])
                    for _, r in _rows(table)}
    raise NotThisScript(f"no {BG_TABLE} in it")


def fix_gallery(blob: bytes, cipher: Blowfish, iv: bytes) -> tuple[bytes, int]:
    """`idlist.arc` with the thirty pictures in place, and how many places
    were written (six per picture).

    0 written means the copy already has them. Anything in one of those
    places other than an empty entry or the recipe's own picture is refused:
    that is not the table this was written against. A copy an earlier version
    of this tool fixed has the first place only, and gets the other five.
    """
    names = bg_names(blob, cipher, iv)
    for npc, (family, photos) in GALLERY_PHOTOS.items():
        for slot, key in photos.items():
            want = f"{family}イベント{str(slot).translate(_FULL_WIDTH)}"
            if names.get(key) != want:
                raise NotThisScript(f"bg {key} is {names.get(key)!r}, not {want!r}")
    data_at, stored = _entry_at(blob, GALLERY_TABLE)
    table = bytearray(_open_table(blob[data_at:data_at + stored], cipher, iv))
    todo = {(npc, slot): key for npc, (_, photos) in GALLERY_PHOTOS.items()
            for slot, key in photos.items()}
    written = 0
    for at, row in _rows(bytes(table)):
        _, npc, slot = struct.unpack_from("<3H", row)
        key = todo.pop((npc, slot), None)
        if key is None:
            continue
        for place in range(PHOTO_PLACES):
            photo = struct.unpack_from("<H", row, PHOTO_AT + 2 * place)[0]
            if photo == NO_PHOTO:
                struct.pack_into("<H", table, at + PHOTO_AT + 2 * place, key)
                written += 1
            elif photo != key:
                raise NotThisScript(f"slot {slot} of npc {npc} already has picture {photo}")
    if todo:
        raise NotThisScript(f"no row for {sorted(todo)[0]}")
    if not written:
        return blob, 0
    if len(table) % 8:                               # pragma: no cover - 3432 bytes as shipped
        raise NotThisScript("the table does not fill its last cipher block")
    payload = TMOC + struct.pack("<II", len(table), len(table)) + cipher.cbc_encrypt(bytes(table), iv)
    if len(payload) != stored:                       # pragma: no cover - same length in, same out
        raise NotThisScript("the table changed size")
    return blob[:data_at] + payload + blob[data_at + stored:], written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix the confession scenes and the おまけ gallery, for handing out through the updater.")
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

    gallery_out = Path(args.update_dir) / IDLIST_SUBDIR / IDLIST_ARCHIVE
    source = idlist_dir / IDLIST_ARCHIVE if idlist_dir is not None else None
    if source is None or not source.is_file():
        say(f"  ? {IDLIST_ARCHIVE}: your copy has no such archive")
        failed += 1
    else:
        try:
            fixed_idlist, written = fix_gallery(source.read_bytes(), cipher, iv)
        except (NotThisScript, ValueError, struct.error) as exc:
            say(f"  ! {IDLIST_ARCHIVE}: {exc}")
            failed += 1
        else:
            say(f"  {IDLIST_ARCHIVE}: " + (f"{written} gallery picture places filled in"
                                           if written else "gallery already fixed in your copy"))
            if not args.check:
                gallery_out.parent.mkdir(parents=True, exist_ok=True)
                gallery_out.write_bytes(fixed_idlist)

    if not args.check and not failed:
        say(f"  archives in {archive_out}")
        say(f"  the gallery in {gallery_out}")
        say(f"  exports in {scripts_out}")
        say("  the server reads the exports as each scene starts; clients pick "
            "the archives up the next time they start")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
