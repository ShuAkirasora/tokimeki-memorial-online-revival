"""What a right-click on a teacher or a member of staff starts: their own script.

⭐⭐⭐ The original server had one script per person for this question, the same
way it had one per 恋愛候補生: ``<stem>_s102``, where the stem is the one their
placement script carries (``kyt`` for 教頭, ``fte`` / ``mte`` for the two 担任,
``tik`` for the PE teacher). Fifteen of them, and each is a few lines long:

    menu item == 402 (リーダー試験を受ける)  ->  its c002, or its c003
    menu item == 401 / 17                   ->  its c001
    anything else                           ->  EVENT_CALL 0xffff

The only interesting line is the c002 / c003 one, and it is the line this end
used to answer with a table of rooms (`script.LEADER_EXAM_SECOND_HALF_MAP`):

    教頭      CTX[0x8101] == 11 -> c002    == 17 -> c003
    体育教師  CTX[0x8101] == 27 -> c002    == 28 -> c003
    担任      CTX[0x8101] == PC[0x301C] (自分のクラス) -> c002, else c003

WHAT CTX[0x8101] IS
-------------------
The row of the roster record that was right-clicked -- the low half of the
npcId. Three readings that share no input agree:

* 11 and 17 are the two records 教頭 has, 2:11 in 進路指導室 and 2:17 in
  職員室; 27 and 28 are the PE teacher's two, 3:27 on the グラウンド and 3:28
  in the 体育館. The four numbers the two scripts test are exactly the rows
  of those four records.
* A 担任's row *is* a classroom: 3:k stands in the k-th classroom for every k
  from 0 to 25, and 自分のクラス counts the same 26 rooms in the same order.
  So 「the row equals my class」 is 「this is my own 担任」 -- which is what the
  c003 says in words: 「そもそもわたしはあなたの担任じゃない」.
* ``sys_s000``, the original's new-game reset, compares the same slot with 0-4
  and clears 恋愛候補生 i's block on each: the row, again, of the person the
  run is about (a candidate's npcId is 1:i).

⭐ So the rooms were never the rule, only where it showed. The table this
replaces answered the two records it was written against and nobody else: the
second 教頭, the second PE teacher and 24 of the 26 担任 own no event row of
their own, `script.event_for_menu_item` found nothing for them, and the answer
fell through to a capture_npc_event key their table does not have. So
kyt_c003 and tik_c003 could not be reached at all on a campus staffed from the
roster, and a player's own 担任 could set the exam only in Ａ組 and Ｂ組.
The script has no such hole: the key it names is looked up under the npcId
that was clicked, and the client reads it out of that npcId's own table.

⚠️ The key has to be unpacked the way that table packs it (`gs3vm.event_key`):
for these scripts ``0x015B`` is 91:1, not the 27:10 the capture packing gives.

What is NOT here: the scripts also set ``CTX[0x8000]`` to 1 on their first
line; nothing in either corpus reads that slot, so it is dropped with the rest
of the run. ``CTX[0x8102]``, read by the two scripts that are not about a person
(``itm_s001`` / ``stf_s001``), has no reading and nothing here runs them.
"""

from __future__ import annotations

from typing import NamedTuple

import gs3vm
import npcspawns
import romance
import script

#: The roster row of the NPC a run is about -- see the module docstring.
CTX_ROSTER_ROW = 0x8101

#: The suffix of the script that answers a right-click.
RIGHT_CLICK_SUFFIX = "_s102"


class Answer(NamedTuple):
    """One run's answer: the key it called in ``table``, or None for 0xffff."""

    script_name: str
    table: str
    event: "tuple[int, int] | None"


def cells(npc_id: int, menu_item: int, in_class: int) -> dict:
    """Everything a staff ``_s102`` reads.

    ⭐ Three cells and each has a single source: the menu item and the npcId are
    the two fields of the 0x6304 that asked, and 自分のクラス is the value this
    end already puts on the wire as ``inClass``.
    """
    return {
        ("CTX", (romance.CTX_MENU_ITEM, 0)): menu_item,
        ("CTX", (CTX_ROSTER_ROW, 0)): npc_id & 0xFFFF,
        ("PC", script.PC_IN_CLASS): in_class,
    }


def answer(npc_id: int, menu_item: int, in_class: int) -> "Answer | str":
    """Run this NPC's ``_s102``. An `Answer`, or a line saying why not.

    Why-not is a string rather than None so the caller can log it: the NPC is
    not staff, their script is not exported on this machine, or it read a cell
    this end did not supply. In every one of those the caller keeps the answer
    it had before this module.
    """
    stem = npcspawns.STEMS.get(npc_id)
    if stem is None:
        return "not staff"
    name = stem + RIGHT_CLICK_SUFFIX
    found = gs3vm.load(name)
    if found is None:
        return f"{name}: not exported"
    try:
        result = gs3vm.Machine(found, cells(npc_id, menu_item, in_class)).run()
    except (gs3vm.UnknownCell, gs3vm.UnsupportedOp, gs3vm.Runaway) as exc:
        return f"{name}: {exc}"
    table = script.event_table_for(npc_id)
    if result.no_event:
        return Answer(name, table, None)
    if not result.fields:
        return f"{name}: ended without an answer"
    return Answer(name, table, gs3vm.event_key(result.fields[0], table))
