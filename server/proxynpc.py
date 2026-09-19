"""The ten stand-in NPCs a drama party can put in an empty cast slot.

『ときめきメモリアルONLINE』 ships five male and five female 代行ＮＰＣ, and a
party that is one player short is meant to fill the empty 役柄 with one of them
rather than wait -- 「ＮＰＣに変更」 on the cell, 「代行ＮＰＣを申請」 in its
tooltip, and 0xE01D MsgClCastDramaPartySurrogate on the wire. This module is
the roster behind that: `reference/proxy_npcs.json`, ten rows of names, sex,
blood type and appearance.

⭐⭐⭐ WHY THE APPEARANCE IS IN HERE AND NOT JUST THE NAMES. The cast cell is
not drawn from the roster message. Measured with the client's own log: the
moment 0xE009 names an actor whose charaId the client does not know, it sends
0x6500 MsgClQueryCharaInfo for that id and *waits*; answer Error and the cell
stays empty with its 「ＮＰＣに変更」 button, whatever the roster said. The
0x6501 answer is what carries looks and accessory, so a surrogate needs a whole
character record, not a name -- see `create_info`.

⭐ A surrogate's charaId is `CATEGORY << 16 | id`, the same rule clubdata uses
for a practice opponent: the client reads `id >> 16` to pick which NPC table a
character comes out of, and 6 is `proxy_npc`. Nothing is invented here; the id
the client sent in 0xE01D is `npcId{categoryId, id}` and this packs the pair.

⚠️ WHAT THE TABLE DOES NOT SAY. Two accessory slots -- uniform and tie -- are
empty (0xFFFF, 「nothing equipped」) in all ten rows, where a player's record
carries 4 and 9. The table is shipped as it reads: 「the file does not say」 is
not 「the file says none」, and picking a uniform for them would be a number
this end made up. If they turn out to need one, that is a measurement, not a
guess.

⚠️ THE SERVER RUNS WITHOUT THE FILE. Every accessor answers None, which makes
0xE01D refuse with 「選択されたＮＰＣの情報が不正です。」 rather than take
the server down.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import characters

#: Category 6 of the charaId space is `proxy_npc.bin`; see the module docstring.
CATEGORY = 6

_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = _ROOT / "reference" / "proxy_npcs.json"

_ROWS: "dict[str, dict] | None" = None
_LOADED = False


def _rows() -> dict[str, dict]:
    global _ROWS, _LOADED
    if not _LOADED:
        _LOADED = True
        try:
            data = json.loads(SHIPPED.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"[proxynpc] no roster at {SHIPPED} -- 代行ＮＰＣ unavailable")
            data = {}
        except (OSError, ValueError) as exc:
            print(f"[proxynpc] {SHIPPED} unreadable: {exc}")
            data = {}
        rows = {row["key"]: row for row in data.get("npcs", [])}
        if rows:
            print(f"[proxynpc] reference/proxy_npcs.json: {len(rows)} 代行ＮＰＣ")
        _ROWS = rows
    return _ROWS or {}


def chara_id(category: int, ident: int) -> int:
    """``(6, 3)`` -> ``0x00060003``, the charaId a surrogate stands behind."""
    return (category << 16) | ident


def is_proxy(value: int) -> bool:
    return (value >> 16) == CATEGORY


def find(category: int, ident: int) -> "dict | None":
    """One row by its `npcId{categoryId, id}` pair, or None."""
    if category != CATEGORY:
        return None
    return _rows().get(f"{category}:{ident}")


def by_chara_id(value: int) -> "dict | None":
    """The row a surrogate charaId stands for, or None if it is not one."""
    if not is_proxy(value):
        return None
    return find(CATEGORY, value & 0xFFFF)


def available() -> bool:
    return bool(_rows())


def _name(text: str) -> bytes:
    """One 11-byte name field, cut down whole characters like `counted` does."""
    for end in range(len(text), -1, -1):
        raw = text[:end].encode("cp932", "replace")
        if len(raw) < characters.NAME_LEN:
            return raw.ljust(characters.NAME_LEN, b"\x00")
    return b"\x00" * characters.NAME_LEN


def create_info(row: dict) -> bytes:
    """One row as the 74-byte character-creation block the rest of this tree
    passes around.

    ⭐ The point of answering in *that* shape rather than a shape of its own:
    `characters.chara_info` turns it into 0x6501 and `script.pc_info_entry`
    turns it into a 0x7200 cast slot, so a surrogate is a character everywhere
    a party member is one, with no second code path to keep in step.

    charaFrameId, birthMonth and birthDay are zero because the table's own
    bytes are: the ten records carry 0 in all three. ⚠️ charaType is 0, which
    is what a drawable character carries (a player's record says 0); the two
    unclaimed constants in the file's tail are not it.
    """
    out = bytearray()
    out += bytes((0,))  # charaFrameId
    out += _name(row["familyName"])
    out += _name(row["firstName"])
    out += _name(row["nickName"])
    out += struct.pack(">HH", int(row["sex"]), int(row["bloodType"]))
    out += struct.pack(">BB", 0, 0)  # birthMonth, birthDay
    values = list(row["looks"]) + list(row["accessory"])
    if len(values) != len(characters.LOOKS) + len(characters.ACCESSORY):
        raise ValueError(f"{row['key']}: {len(values)} looks+accessory values")
    for value in values:
        out += struct.pack(">H", int(value))
    out += struct.pack(">H", 0)  # charaType
    if len(out) != 74:
        raise ValueError(f"{row['key']}: create block is {len(out)}B")
    return bytes(out)


def names(row: dict) -> tuple[bytes, bytes]:
    """Family and given name as the drama roster wants them (NUL-padded)."""
    return _name(row["familyName"]), _name(row["firstName"])


def stand_in(sex: int, taken: "set[tuple[int, int]]") -> "tuple[int, dict] | None":
    """A 代行ＮＰＣ of this 役柄's sex that this party has not cast yet.

    ⭐ THE TWO CONSTRAINTS ARE THE CLIENT'S, not this end's. 0xE01D's own list
    「ＮＰＣの設定」 offers 「the five whose sex matches the 役柄」, and two of
    the 27 refusal sentences guard exactly this pair -- 22 「…性別が違うため」
    and 18 「選択された代行ＮＰＣは、既に役柄が割り当てられています」. A
    stand-in the server picks for a 離脱 is going into the same cast as one the
    leader picks by hand, so it answers to the same two rules.

    ⚠️ INVENTED — *which* of the free ones. Nothing anywhere says, and the
    party has at most four 役柄 against five stand-ins per sex, so there is
    always more than one right answer and no way to be caught taking the wrong
    one. Lowest id first, which is the order the client's own list draws them
    in (`proxy_npc.bin` order) and therefore the one a player has seen.
    ⛔️ Not a knob: it is a choice among equals, not a number to tune.
    """
    rows = ((int(key.split(":")[1]), row) for key, row in _rows().items())
    for ident, row in sorted(rows, key=lambda pair: pair[0]):
        if int(row["sex"]) != int(sex):
            continue
        if (CATEGORY, ident) in taken:
            continue
        return ident, row
    return None
