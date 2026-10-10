#!/usr/bin/env python3
"""Put the confession close-ups back into four of your copy's script files.

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

This build's own data is the defect, not the server and not the renderer, and
nothing on the wire can carry an instruction into a script the client is
already running. The fix has to be in the script files.

What this changes
-----------------
Only the four scripts `amm_e011`, `yyi_e011`, `skr_e011` and `ink_e011`, and in
each only by adding:

  * the scene-effect count on the background that needs one (it was 0);
  * a detour at a handful of instructions: the instruction is replaced by a
    jump to new code at the end of the script, which does what it did and then
    the additions -- register the parts, switch them on, change the heroine's
    expression before a line -- and jumps back.

No instruction moves, no label is added and nothing is removed, so every
address the server already knows a script by stays the same. Two edits change
an instruction in place instead, at the same length: Yayoi's scene loads a
background the parts list does not cover, and is pointed at its twin (the same
picture, byte for byte) that it does; Sakurai's first shot is of her back, so
the face overlay that would land on it is replaced by switching on her body.

Which parts go with which background is read from the client. Which expression
goes with which line, and the moment Yayoi's rain clears, are choices made
here -- the original never played these scenes, so there is nothing to recover
them from. The choices are the recipes below, and are meant to be read.

How it reaches players
----------------------
Through the game's own updater. Run this on the server's machine, against a
copy of the game:

    python3 confession_fix.py                   # writes the two halves below
    python3 confession_fix.py --check           # only says what it would do
    python3 confession_fix.py --game-dir PATH   # when the guess is wrong

  1. The four fixed archives go into `runtime/update/data/script/`. Every
     client that starts through BootFirst asks the server for updates first;
     this server offers whatever is in `runtime/update/`, and the client fetches
     the files that differ from its own and puts them in place.
  2. The four scripts are exported again, from the fixed archives, into
     `runtime/scripts/`. The server follows each scene alongside the client and
     has to be following the same script, or the scene still plays but the
     server loses track of it -- and with it the ending.

Both halves together, always. Nothing here is a general script editor: the
four recipes are the whole of what it does.

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


def jump(ip: int) -> bytes:
    """OP_JP. The target is in 16-bit words from the start of the code."""
    return struct.pack("<HHI", 0x9080, 0, ip << 12)


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

    The second byte is 0x40 on a scene's first change and 0 after, as in
    Kasuga's script; what it means is not known.
    """
    return op(0x5280, actor, 0x40 if first else 0, emotion & 0xFF, emotion >> 8)


#: A hook whose original is given as an opcode takes the whole instruction from
#: the file, after checking the opcode. Used for the spoken lines.
TALK = 0x5380


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
}

BG_INFO = 0x5000
EFFECT_COUNT_MASK = 0x3F


# ------------------------------------------------------------ the procedure


class NotThisScript(Exception):
    """The file is not the script the recipe was written against."""


def already_fixed(ssc: bytes, recipe: dict) -> bool:
    """True when every background the recipe gives effects to already has them."""
    sec = ssc_sections(ssc)
    code = ssc[sec["code"]:sec["aux"]]
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
        description="Fix the four confession scenes, for handing out through the updater.")
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
