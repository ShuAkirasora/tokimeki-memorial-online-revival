"""The club tables a 練習 needs, read out of a table file rather than kept inline.

`reference/clubbattle.json` ships with this server. Nothing in this module
carries a number of its own; every rule value a club battle is fought by is in
that file, and an operator may override any row or add rows of their own at
`runtime/clubbattle.json` (or point `TMO_CLUB_DATA` somewhere else).

    keyword    261 rows: attack, defence, the 習熟度 full scale, the 能力属性
               a play raises and the クラブの素 a play can yield
    npc        144 rows: the practice opponents' vitality/energy/speed, their
               部活レベル, their club and which deck they bring
    ladder     800 rows: 8 clubs x 100 対戦レベル, the 1-3 opponents at each
    training     9 rows: 自主トレ plus the eight clubs' 練習, each one's club
               and the background its battle screen draws
    clubskill   57 rows: every 部活奥義's effects -- attack power, 消費気力,
               success rate, the three +-% modifiers, two heals, one ailment,
               and the 能力属性 it raises
    skillbook   57 rows: every 奥義の書 -- which 部活奥義 it makes, whose club
               that is, and ⭐ the RECIPE (2-8 合成アイテム with a count each),
               which round 226 added because 奥義合成 now consumes it
    npcdeck    200 rows: which キーワード and 部活奥義 an opponent brings

⚠️ WHY A FILE AND NOT LITERALS IN HERE. Two reasons, and the second is the one
that decides it. These are far too many numbers to read as code -- 1528 rows
against the handful of constants the rest of this tree keeps inline. And they
are the operator's to change: what a keyword hits for and who stands on which
rung are the levers a running server is tuned with, and a lever belongs in a
file that survives a pull rather than in a diff against the source.

⚠️ WHAT IS NOT IN IT. The opponents' names. Nothing in `server/` reads them --
they were only ever printed in one log line -- so they are not carried, and the
log names an opponent by its key. The shipped file is generated; edit
`runtime/clubbattle.json` instead, which is merged over it row by row.

⚠️ THE SERVER RUNS WITHOUT EITHER FILE. Every accessor answers None or an empty
result when there are no rows, and the one caller that cannot proceed without a
number says so in the log instead of substituting one. No tables makes 練習
unavailable; it does not make the server unstartable, and it does not make
自主トレ (which needs only the keyword rows) any worse than it was.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

#: The shipped tables, then the operator's own, the same two directories
#: `reserved_names.json` uses. ⚠️ Off `__file__` rather than the working
#: directory: run_all.py is started from several places and a relative path
#: finds the file from only one of them.
#: ⚠️ Order matters -- the loader lets the later file win row by row.
_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = _ROOT / "reference" / "clubbattle.json"
FEED = Path(os.environ.get("TMO_CLUB_DATA") or (_ROOT / "runtime" / "clubbattle.json"))

#: Category 7 of the charaId space is `training_npc.bin` -- the client reads
#: `id >> 16` to pick which table a map object's appearance and right-click
#: menu come out of, and 7 is this one. So an opponent's charaId is simply
#: `NPC_CATEGORY << 16 | row`, which is what 0x5C05 carries and the only thing
#: about that opponent that goes on the wire.
NPC_CATEGORY = 7

_DATA: "dict | None" = None
_LOADED = False


#: Every table this module knows, and the order `summary()` prints them in.
#: ⚠️ Every table, not a chosen few -- see summary().
TABLES = ("keyword", "npc", "ladder", "training", "clubskill", "skillbook",
          "npcdeck")


def _read(path: Path) -> "dict | None":
    """One file, or None. ⚠️ A file that is simply not there is silent: either
    of the two may be absent legitimately, and only both being absent is worth
    a line -- which _data says once it knows."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        print(f"[clubdata] {path} unreadable: {exc}")
        return None


def _data() -> dict:
    """The shipped tables with the operator's merged over them, row by row.

    Row by row rather than table by table so that an operator who wants one
    opponent slower does not have to carry a copy of all 144 -- their file holds
    only what they changed, and a row they did not mention keeps the shipped
    value. A table nobody ships and nobody overrides is simply absent, which is
    what every accessor's `.get(table, {})` already handles.
    """
    global _DATA, _LOADED
    if not _LOADED:
        _LOADED = True
        merged: dict = {}
        for source in (_read(SHIPPED), _read(FEED)):
            for table in TABLES:
                rows = (source or {}).get(table)
                if isinstance(rows, dict):
                    merged.setdefault(table, {}).update(rows)
        if not merged:
            print(f"[clubdata] no tables at {SHIPPED} -- 練習 is unavailable")
        _DATA = merged or None
    return _DATA or {}


def available() -> bool:
    """Are there any tables at all? The one thing callers branch on."""
    return bool(_data())


def summary() -> str:
    data = _data()
    if not data:
        return f"no club tables ({SHIPPED})"
    # ⚠️ Every table, not a chosen few: this line is what a log reader uses to
    # tell 「the tables are stale」 from 「they are missing」, and a table left
    # out of it is one that can go missing without anybody noticing.
    return "club tables: " + " · ".join(
        f"{name} {len(data.get(name, {}))}" for name in TABLES
    )


def keyword(keyword_id: int) -> "dict | None":
    """`{attack, defence, fullScale, ability, sozai}` for one キーワード, or None.

    ⭐ attack/defence are `keyword.bin` +0x2e/+0x30 and they are in the SAME
    CURRENCY as 体力: 260-700 and 300-630 against opponents holding 550-1999.
    So an attack value is not a percentage and not a band index -- it is priced
    in 体力, which is the one thing the tables settle about the damage rule.

    ⭐⭐ ``ability`` is +0x2c, 0-5, and it is the whole of what 「使用したキー
    ワードの能力属性…によって、能力パラメータが増加します」 (p07_03) needs from
    this end: WHICH of the six goes up is the table's, and only HOW MUCH is
    invented. 261 rows agree with the six id blocks with no exceptions, and the
    client looks the same field up in `chara_ability_type.bin` (2.154 一).

    ⭐ ``sozai`` is +0x36's eight slots as ``["32:1", …]`` -- the クラブの素 this
    card can yield, all 94 of them inside `item.bin` categories 32-40 with no
    exceptions (2.156 二). ⚠️ Every one of the 261 rows has at least one slot,
    so an empty list means the table is old, not that this card yields nothing.
    """
    return _data().get("keyword", {}).get(str(keyword_id))


def club_skill(category_id: int, skill_id: int) -> "dict | None":
    """One 部活奥義's effect row, by its `clubskill.bin` key.

    ⭐ The whole row is restored -- 攻撃力 (0-1100, the same 体力 currency the
    keywords are in), 消費気力, 成功率, the three ±% modifiers, the two heals,
    the ステータス異常 it inflicts and the 能力属性 it raises.
    ⭐⭐ ALL OF IT IS ACTED ON as of round 223; up to 222 only ``power`` was, and
    the rest sat here unused. See clubbattle's SKILL EFFECTS block for which
    0x5C11 ``type`` each column narrates through and which two columns are
    applied silently because the client has no line for them.
    """
    return _data().get("clubskill", {}).get(f"{category_id}:{skill_id}")


def skill_book(category_id: int, book_id: int) -> "dict | None":
    """One 奥義の書 by its `item_skillbook.bin` key: `{skill, club, mats}`.

    ⚠️ The key space is `item.bin`'s -- categories 17-24 are the eight clubs'
    books and they sit in the same inventory as everything else, which is why
    `item.ITEM_KEYS` already carries them.

    ⭐ ``mats`` is the RECIPE, and it is what p07_05 says a book is for:
    「『奥義の書』には部活奥義を合成するためのレシピが書いてあり、そのレシピ通りの
    合成アイテムを用意する必要があります」. 2-8 kinds, each with a count, every
    key inside `item.bin`'s 32-40 クラブの素. ⚠️ It arrived in the feed only in
    round 226; a feed written before that has the other two fields and no
    ``mats``, which recipe_of reports as 「no recipe」 rather than as an empty
    one -- see 0x5308 reason 11.
    """
    return _data().get("skillbook", {}).get(f"{category_id}:{book_id}")


def recipe_of(category_id: int, book_id: int) -> "list[tuple[int, int, int]] | None":
    """This book's recipe as ``[(category, itemId, count), ...]``, or None.

    None means 「this book has no usable recipe」 and is what 0x5308 reason 11
    「奥義の書の内容が正常でない」 is for. An empty list is not a thing the table
    produces -- every one of the 57 rows uses between two and eight slots.

    ⚠️ ONE ROW IS KNOWN TO BE MALFORMED IN THE ORIGINAL DATA and it is not
    repaired here: `22:6 眼力解明書` names two materials but leaves a 1 in the
    third count slot. The tool that writes the feed pairs counts with slots by
    index and drops the stray, which is the reading 2.158 三 settled: the
    original table had a slot removed without its count being removed with it.
    Anything that tried to be cleverer here would be inventing a third material
    for a book that has two.
    """
    row = skill_book(category_id, book_id)
    if not row:
        return None
    out = []
    for entry in row.get("mats") or ():
        key = str(entry.get("key") or "")
        category, _, item_id = key.partition(":")
        try:
            out.append((int(category), int(item_id), int(entry.get("count") or 0)))
        except ValueError:
            return None
    return out or None


def books_of_club(club_id: int) -> "list[str]":
    """Every 奥義の書 whose 部活奥義 belongs to this club, as ``"17:0"`` keys.

    ⭐ The partition is restored and exact: a book's category is its club + 16,
    and that equals the 奥義's own category and the 奥義's クラブ属性 column,
    57 rows out of 57 with no exceptions. ⚠️ So this is not 「books that look
    like they belong to this club」 -- it is the table's own grouping.
    """
    return sorted(
        key for key, row in _data().get("skillbook", {}).items()
        if row.get("club") == club_id
    )


def npc(key: str) -> "dict | None":
    """One practice opponent by its `training_npc.bin` key, e.g. ``"7:3"``."""
    return _data().get("npc", {}).get(key)


def npc_deck(key: str) -> "dict | None":
    """One `npc_clubdeck.bin` row: the キーワード and 奥義 an opponent holds.

    ⭐ Which deck belongs to which opponent is restored -- `training_npc.bin`
    +0x48/+0x4a is this table's key, and all 144 rows point at a real one whose
    first field is the NPC's own club.
    """
    return _data().get("npcdeck", {}).get(key)


def npc_chara_id(key: str) -> int:
    """``"7:3"`` -> ``0x00070003``, the charaId 0x5C05 puts on the wire."""
    category, _, row = key.partition(":")
    return (int(category) << 16) | int(row)


def npc_key(chara_id: int) -> str:
    """The inverse, for looking an opponent back up out of a fight."""
    return f"{chara_id >> 16}:{chara_id & 0xFFFF}"


def is_npc(chara_id: int) -> bool:
    return (chara_id >> 16) == NPC_CATEGORY


def ladder(club_id: int, level: int) -> "list[str]":
    """Who stands at 対戦レベル ``level`` of club ``club_id`` -- 1 to 3 keys.

    ⚠️ Levels are 1-based on screen and in this table's own row names
    (「野球部レベル１」 is the first), so this takes the number the client sent
    in 0x5C03 without shifting it.
    """
    return list(_data().get("ladder", {}).get(f"{club_id}:{level}", []))


def ladder_top(club_id: int) -> int:
    """The highest 対戦レベル this club's ladder actually has rows for."""
    levels = [
        int(key.split(":")[1])
        for key in _data().get("ladder", {})
        if key.startswith(f"{club_id}:")
    ]
    return max(levels) if levels else 0


def training_for_club(club_id: int) -> "tuple[int, int] | None":
    """`(trainingId, background)` for one club's 練習, or None.

    ⭐⭐ The background is the ONE field the client reads out of `training.bin`
    (offset +0x1a, one reader, and its consumer's first instruction is a
    compare against 0xFFFF -- which is exactly what 自主トレ's row carries).
    This server does not send it anywhere: the client picks it up from its own
    table once it knows which 練習 is being fought. It is here so the log can
    name the place, and because the row is also what says which club a given
    trainingId belongs to.
    """
    for key, row in _data().get("training", {}).items():
        if row.get("club") == club_id:
            return (int(key), row.get("bg", 0xFFFF))
    return None
