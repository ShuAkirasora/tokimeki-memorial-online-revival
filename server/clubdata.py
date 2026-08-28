"""The club tables a 練習 needs, read out of a local feed rather than kept.

`runtime/clubbattle.json` is written by a tool in the private tree out of the
client's own data files, and -- like `runtime/drama_events.json` and everything
else under `runtime/` -- it is a LOCAL FEED that reaches no repository. Nothing
in here carries a number of its own.

    keyword    261 rows: attack, defence, and the 習熟度 full scale
    npc        144 rows: the practice opponents' vitality/energy/speed, their
               部活レベル, their club and which deck they bring
    ladder     800 rows: 8 clubs x 100 対戦レベル, the 1-3 opponents at each
    training     9 rows: 自主トレ plus the eight clubs' 練習, each one's club
               and the background its battle screen draws
    clubskill   57 rows: every 部活奥義's effects -- attack power, 消費気力,
               success rate, the three +-% modifiers, two heals, one ailment
    npcdeck    200 rows: which キーワード and 部活奥義 an opponent brings

⚠️ WHY THE FEED AND NOT A LITERAL IN HERE. Most of these are large tables of
the game's own numbers rather than the handful of rule values this tree carries
inline, and whether that changes what this repository is has not been decided.
Reading them from a file that is never committed keeps the decision open and
keeps the fight runnable in the meantime.

⚠️ THE SERVER RUNS WITHOUT IT. Every accessor answers None or an empty result
when the file is absent, and the one caller that cannot proceed without a
number says so in the log instead of substituting one. A missing feed makes
練習 unavailable; it does not make the server unstartable, and it does not make
自主トレ (which needs only the keyword rows) any worse than it was.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

#: `runtime/` next to `server/`, the same anchor every other local feed uses.
#: ⚠️ Off `__file__` rather than the working directory: run_all.py is started
#: from several places and a relative path finds the file from only one of them.
FEED = Path(
    os.environ.get("TMO_CLUB_DATA")
    or (Path(__file__).resolve().parent.parent / "runtime" / "clubbattle.json")
)

#: Category 7 of the charaId space is `training_npc.bin` -- the client reads
#: `id >> 16` to pick which table a map object's appearance and right-click
#: menu come out of, and 7 is this one. So an opponent's charaId is simply
#: `NPC_CATEGORY << 16 | row`, which is what 0x5C05 carries and the only thing
#: about that opponent that goes on the wire.
NPC_CATEGORY = 7

_DATA: "dict | None" = None
_LOADED = False


def _data() -> dict:
    global _DATA, _LOADED
    if not _LOADED:
        _LOADED = True
        try:
            _DATA = json.loads(FEED.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"[clubdata] no feed at {FEED} -- 練習 is unavailable")
            _DATA = None
        except (OSError, ValueError) as exc:
            print(f"[clubdata] {FEED} unreadable: {exc}")
            _DATA = None
    return _DATA or {}


def available() -> bool:
    """Is there a feed at all? The one thing callers branch on."""
    return bool(_data())


def summary() -> str:
    data = _data()
    if not data:
        return f"no club feed ({FEED})"
    # ⚠️ Every table, not a chosen few: this line is what a log reader uses to
    # tell 「the feed is stale」 from 「the feed is missing」, and a table left
    # out of it is one that can go missing without anybody noticing.
    return "club feed: " + " · ".join(
        f"{name} {len(data.get(name, {}))}"
        for name in ("keyword", "npc", "ladder", "training", "clubskill", "npcdeck")
    )


def keyword(keyword_id: int) -> "dict | None":
    """`{attack, defence, fullScale}` for one キーワード, or None.

    ⭐ attack/defence are `keyword.bin` +0x2e/+0x30 and they are in the SAME
    CURRENCY as 体力: 260-700 and 300-630 against opponents holding 550-1999.
    So an attack value is not a percentage and not a band index -- it is priced
    in 体力, which is the one thing the tables settle about the damage rule.
    """
    return _data().get("keyword", {}).get(str(keyword_id))


def club_skill(category_id: int, skill_id: int) -> "dict | None":
    """One 部活奥義's effect row, by its `clubskill.bin` key.

    ⭐ The whole row is restored -- 攻撃力 (0-1100, the same 体力 currency the
    keywords are in), 消費気力, 成功率, the three ±% modifiers, the two heals
    and the ステータス異常 it inflicts. ⚠️ Only ``power`` is acted on today;
    everything else is carried here so that the rest of 奥義 is a matter of
    using rows that already exist rather than of reading a table again.
    """
    return _data().get("clubskill", {}).get(f"{category_id}:{skill_id}")


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
