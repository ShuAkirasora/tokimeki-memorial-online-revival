"""A charaId that names a roster row, and what the client does with one.

Most charaIds name a character this server is holding. A charaId in
``0x00010000..0x0011FFFF`` names something else: a row in one of the game's own
rosters, with the roster's number in the top 16 bits and the row in the bottom.
Send one of those in a MsgSvNotifyCharacterAdd and the client does not draw the
record the id rides in -- it splits the id and goes looking.

THE SPACE, READ OFF THE CLIENT'S OWN THREE FUNCTIONS
----------------------------------------------------
Three routines, called from 38 places between them, define the whole of it:

  0x00404FDF(id)   1 iff 0x10000 <= id <= 0x11FFFF -- the roster space itself
  0x00404FF9(id)   the category: id >> 16 inside that range; 0 for an ordinary
                   character (0x01000000..0xFFFFFFFE); 0x11 for anything else
  0x00405022(id)   the row: id & 0xFFFF inside the range, 0xFFFF outside it

So the categories are 1..17 and no others, and ROW_NONE below is the client's
own "no row" answer rather than a convention chosen here.

⚠️ 0x11 is returned by the classifier in two different situations -- category
17, and an id that is neither a roster reference nor a character -- so it does
not distinguish them. Nothing here depends on telling those apart; the space is
described by the range check, which does.

WHICH ROSTER EACH CATEGORY IS
-----------------------------
Every one of the game's id tables carries its category in its own keys, so the
mapping is read out of the tables rather than guessed:

    1  capture_npc 10          2  common_npc 18       3  general_npc 31
    4  cibi_control_script 223 5  event_npc 63        6  proxy_npc 10
    7  training_npc 144        8  lesson_npc 7        9  matching_npc 3
   12  scenario_npc 140       13  generation_npc 104  15  game_master_pc 14
   16  map_object 2

10, 11, 14 and 17 have no table at all. This end already knew seven of those
categories one constant at a time -- 1 in cibispawns, 4 in romance, 6 in
proxynpc, 7 in clubdata, 15 in gmchat, 2 and 3 in npcspawns -- and the point of
writing the space down in one place is the four questions those constants
cannot answer between them: which categories exist, which of them the client
draws, which of them it offers a menu for, and what it does with the rest.

⚠️ Category 0 is not a roster. It is what the classifier answers for an
ordinary character, so both dispatches below reach it for every real player,
and their category-0 branches are the player's own case rather than a
fourteenth table. Nothing in this module builds an id with it.

WHAT THE CLIENT DRAWS (0x0070F100)
-----------------------------------
The chibi it puts on the map is chosen by category, and only four rosters
choose anything:

    0        a player -- the default appearance triple (1, 0, 0)
    1        capture_npc, by row
    2        the entry the scene is already holding for (2, row)
    3        general_npc, by row
    7        training_npc, through its clubId
    anything else, and any of 2/3/7 whose row is not found
             -> the same default chibi a player gets

⭐ So a roster id the client cannot resolve is not a crash and not an empty
space: it is a nobody in the default body. That matters for reading a probe --
"a chibi appeared" says nothing until you know whether it was *that* chibi.

WHAT THE CLIENT OFFERS A MENU FOR (0x006A6388)
-----------------------------------------------
A second, independent dispatch picks the right-click menu, and it covers a
different set of categories than the drawing does:

    0        yes (a player: the PC 交流メニュー)
    1        yes                     3  yes                 15  yes
    2        rows 0-7, 8-11 and 17 -- thirteen rows, and no others
    16       rows 0 and 1 only (map_object has exactly two)
    everything else -- including 4, 5, 6, 7, 8, 9, 12, 13 -- no menu at all

The dispatch returns nothing for those, and its caller (0x006A6582) handles the
empty answer rather than faulting on it, so this too is a quiet outcome.

⭐ The thirteen rows of category 2 are a check on this reading rather than a
detail of it. npcspawns staffs the campus from the game's placement scripts,
with no knowledge of this dispatch, and the category-2 people it puts out are
rows 0 through 11 -- twelve rows, every one of them inside the thirteen, no
exceptions either way.

⭐⭐ The one row left over says something. It is ``2:17 教頭先生立ち``, and its
two name fields are byte for byte the ones in ``2:11 教頭先生``: the same man in
a second record, and the reason the dispatch reaches for row 17 out of order
right after rows 8-11. So the client holds a menu for somebody this end has
never put anywhere -- and the 教頭 is already the one person npcspawns places
twice, once in each of the two rooms he is found in, both times as 2:11.
⚠️ That is a lead and not a conclusion: nothing read so far says which of the
two rooms, if either, wanted the standing record.

WHAT THIS IS FOR
----------------
``/cid`` is the one command that dictates a charaId instead of minting one, and
since the teachers and staff became permanent its only remaining use is asking
about an id no table answers for. It can now say what the client will do with
each id before it is sent: which body, and whether right-clicking will offer
anything. Two categories it reports on are ones nothing else in this server
reaches -- scenario_npc and generation_npc, 244 people between them -- and the
answer for both is "a default chibi and no menu", which is what closes them
rather than leaving them on a list of tables nobody has tried.

⚠️ Nothing here validates. An id outside the space, or a category with no
table, is still sent exactly as asked: the probe is the point, and a server
that refuses the unanswered ids cannot ask about them.
"""

from __future__ import annotations

from typing import NamedTuple

#: The roster space, both ends inclusive -- 0x00404FDF's range check.
ROSTER_ID_MIN = 0x0001_0000
ROSTER_ID_MAX = 0x0011_FFFF

#: What 0x00405022 answers for an id that is not a roster reference.
ROW_NONE = 0xFFFF

#: The categories that exist at all, by the same range check: 0x10000 >> 16
#: through 0x11FFFF >> 16.
CATEGORY_MIN = ROSTER_ID_MIN >> 16
CATEGORY_MAX = ROSTER_ID_MAX >> 16

#: category -> the table whose keys carry it. Categories 10, 11, 14 and 17 are
#: absent because no table claims them, not because none was looked for.
ROSTERS = {
    1: "capture_npc",
    2: "common_npc",
    3: "general_npc",
    4: "cibi_control_script",
    5: "event_npc",
    6: "proxy_npc",
    7: "training_npc",
    8: "lesson_npc",
    9: "matching_npc",
    12: "scenario_npc",
    13: "generation_npc",
    15: "game_master_pc",
    16: "map_object",
}

#: The rosters 0x0070F100 draws something particular from. Every other category
#: falls through to the default chibi, as does a row these cannot resolve.
#: Category 0 is not here because it is not a roster; it is a player, and a
#: player is drawn from the record rather than looked up.
DRAWN_CATEGORIES = frozenset({1, 2, 3, 7})

#: The right-click dispatch at 0x006A6388, branch for branch. A category maps to
#: the rows it answers for: None means every row, a tuple means those rows and
#: no others. Categories that are absent get no menu at any row. Category 0 --
#: the player's own menu -- is left out for the same reason: this table is asked
#: about roster ids, and 0 is not one.
MENU_ROWS: dict[int, tuple[int, ...] | None] = {
    1: None,
    2: tuple(range(0, 12)) + (17,),
    3: None,
    15: None,
    16: (0, 1),
}


class RosterRef(NamedTuple):
    """A charaId split the way the client splits it."""

    category: int
    row: int

    @property
    def key(self) -> str:
        """``3:27`` -- how every id table and every command writes one."""
        return f"{self.category}:{self.row}"


def is_roster_ref(chara_id: int) -> bool:
    """Whether the client will read this id as a roster row (0x00404FDF)."""
    return ROSTER_ID_MIN <= chara_id <= ROSTER_ID_MAX


def split(chara_id: int) -> RosterRef | None:
    """``0x0003001B`` -> ``RosterRef(3, 27)``; None for an ordinary character.

    The split itself is 0x00404FF9 and 0x00405022 together, and they agree only
    inside the range -- outside it the first answers 0 or 0x11 and the second
    answers ROW_NONE, neither of which is a row in anything. So an id outside
    the space has no split rather than a meaningless one.
    """
    if not is_roster_ref(chara_id):
        return None
    return RosterRef(chara_id >> 16, chara_id & 0xFFFF)


def make(category: int, row: int) -> int:
    """``(3, 27)`` -> ``0x0003001B``."""
    return ((category & 0xFFFF) << 16) | (row & 0xFFFF)


def has_menu(chara_id: int) -> bool:
    """Whether right-clicking this id offers anything (0x006A6388).

    False is the ordinary answer for most of the space, and it is not an error:
    the dispatch returns nothing and its caller carries on.
    """
    ref = split(chara_id)
    if ref is None:
        return False
    if ref.category not in MENU_ROWS:
        return False
    rows = MENU_ROWS[ref.category]
    return rows is None or ref.row in rows


def describe(chara_id: int) -> str:
    """One line saying what the client will do with this id, for /cid to echo.

    Japanese because it is read in the client's chat window beside the game's
    own text, like every other line that command prints.
    """
    ref = split(chara_id)
    if ref is None:
        return "名簿外"
    roster = ROSTERS.get(ref.category)
    body = roster if ref.category in DRAWN_CATEGORIES else "既定ちび"
    menu = "メニューあり" if has_menu(chara_id) else "メニューなし"
    table = f"・{roster}" if roster is not None and body != roster else ""
    if roster is None:
        table = "・表なし"
    return f"{body}{table}・{menu}"
