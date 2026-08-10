"""クラブ対戦: the battle all three doors lead into, and who has to open it.

Twenty-nine messages, 0x5C00-0x5C1C. They run the fight itself, which is the
same fight whichever door reached it — 「自主トレの流れは、ＮＰＣとの練習と
同じです」 — so 練習, フリー対戦 and 自主トレ all end up here.

⭐⭐ WHY THIS MODULE EXISTS AT ALL, which is the finding it was written for.
For five rounds this project looked for the missing precondition on the
*client* side: 0x5818 「開 始」 went up, 0x5819 went back to everybody in the
room, and then the screen sat still and the client sent nothing further. Three
generations of guess about what it was still waiting for (an NPC on the map,
a second player, a キーワード) were each wrong, and the reason is legible in
the message names alone:

    0x5C05 MsgSvNotifyNpcClubBattleInfo        Sv
    0x5C06 MsgSvNotifyTrainingClubBattleInfo   Sv  ★ the 自主トレ one
    0x5C09 MsgSvNotifyClubBattleTurnStart      Sv

Every opening message in the family is a MsgSv. 0x5819 only announces 「the
leader pressed start」; **drawing the battle is the server's job**, and the
client after 0x5819 is not blocked on a condition, it is waiting for us. The
message never came because nothing here ever sent one.

⚠️ So the rule this cost five rounds to learn: when one MsgSv does not show up
on screen, count the MsgCl/MsgSv split of its family before looking for a
precondition. 「the client still needs something」 is always a sayable
sentence, and it was wrong three times in a row here.

The shape of 0x5C06
-------------------
Reader at 0x8EF380, field names from the dump at 0x8F0090.

    team               u8       which side the RECIPIENT is on (0-based, as 0x5817)
    team1MembersInfo   u16 count, then count x 83B
    team2MembersInfo   u16 count, then count x 83B

⚠️ ``team`` is per-recipient, so this message has a different body for every
person it goes to. It cannot be broadcast with one shared buffer.

One 83-byte member record:

    charaId        u32
    base           71B   the same block a character list entry opens with
    vitality       u16
    energy         u8
    speed          u8
    clubId         u16
    charaBodyType  u16

⭐ ``base`` is not re-derived here. It is the opening 71 bytes of the 0x6501
record that characters.chara_info already builds and that has been on screen
for many rounds — same fields, same order, one definition.

⚠️⚠️ **THERE IS NO DECK IN THIS MESSAGE.** It carries 体力／気力／素早さ／
所属クラブ／体型 and not one card. Each player's 部活デッキ is something the
client already knows; the cards first reach the wire in the 0x5C0A/0x5C0C
コマンド exchange further in. This is also why putting a deck into the save
file had no effect on 「開 始」 — nothing was ever going to read it here.

INVENTED, and flagged as such
-----------------------------
⚠️ 体力／気力／素早さ have no home in the save file: nothing in the ability
sheet corresponds to them and no message seen so far carries them. The three
values below are therefore this server's invention, not a restoration. They
are placeholders that let the battle be drawn; the game they would belong to
(what raises them, what spends them) is not implemented.

⚠️ The u16/u8/u8 width split is itself only inferred, from the order the
reader calls its accessors in — the pairing of *name* to *width* has no second
witness. So ``energy`` and ``speed`` deliberately get DIFFERENT default values
here: whichever number 気力 shows on screen names which of the two u8 it is,
and that reading is free the first time a battle draws.
"""
from __future__ import annotations

import struct

import characters

MSG_CL_CAST_BATTLE_CHAT = 0x5C00
MSG_SV_NOTIFY_NPC_BATTLE_INFO = 0x5C05
MSG_SV_NOTIFY_TRAINING_BATTLE_INFO = 0x5C06
MSG_CL_NOTIFY_BATTLE_READY = 0x5C07
MSG_SV_NOTIFY_BATTLE_READY = 0x5C08
MSG_SV_NOTIFY_BATTLE_TURN_START = 0x5C09

#: The block a character record opens with, shared with the list entry (2.10)
#: and the 0x6501 info record (2.35): names, sex, blood, birthday, looks,
#: accessories. Taken as chara_info's prefix rather than rebuilt.
BASE_SIZE = 71

#: charaId u32 + base + vitality u16 + energy u8 + speed u8 + clubId u16 +
#: charaBodyType u16.
MEMBER_SIZE = 83

#: ⚠️ INVENTED (see the module docstring). Distinct on purpose so that the
#: first battle to reach the screen says which u8 is which.
DEFAULT_VITALITY = 100
DEFAULT_ENERGY = 80
DEFAULT_SPEED = 40


def base_block(info: bytes) -> bytes:
    """The 71-byte ``base`` for one character, out of their create block.

    ⭐ Built by taking what characters.chara_info already assembles and
    keeping its opening 71 bytes. That function's first fields are exactly
    this block in exactly this order — familyName, firstName, nickName, sex,
    bloodType, birthMonth, birthDay, the nine looks and the seven accessories
    — and it is the version that has been drawn correctly on screen since
    round 67. Rebuilding the same field order a second time here would be two
    definitions of one structure, and the second one would be the untested one.
    """
    block = characters.chara_info(info)[:BASE_SIZE]
    if len(block) != BASE_SIZE:
        raise AssertionError(f"base is {len(block)}B, reader wants {BASE_SIZE}")
    return block


def member_row(
    chara_id: int,
    info: bytes,
    club_id: int = 0,
    vitality: int = DEFAULT_VITALITY,
    energy: int = DEFAULT_ENERGY,
    speed: int = DEFAULT_SPEED,
) -> bytes:
    """One 83-byte entry in either side's roster.

    ``charaBodyType`` comes off the end of the create block, where the create
    message calls the same value ``charaType`` — the client picked it at
    character creation and this hands it straight back.
    """
    fields = characters.parse_create_info(info)
    body_type = fields["charaType"]
    assert isinstance(body_type, int)
    out = struct.pack(">I", chara_id)
    out += base_block(info)
    out += struct.pack(">HBB", vitality & 0xFFFF, energy & 0xFF, speed & 0xFF)
    out += struct.pack(">HH", club_id & 0xFFFF, body_type & 0xFFFF)
    if len(out) != MEMBER_SIZE:
        raise AssertionError(f"member is {len(out)}B, reader wants {MEMBER_SIZE}")
    return out


def parse_ready(params: bytes) -> int:
    """0x5C07 -> the deckId the player brought. An absent body reads as 0.

    ⚠️ This is a MsgCl**Notify**: the client is not asking for anything, it is
    saying its battle scene is up and which of its three 部活デッキ it is
    fighting with. Both real clients send it unprompted the moment 0x5C06
    draws, which is how this message named itself as the next one to answer.
    """
    return params[0] if params else 0


def battle_ready_params(chara_id: int) -> bytes:
    """0x5C08: one charaId, and nothing else.

    ⚠️ It does NOT echo the deckId back. Whose deck is whose stays on the
    client until the cards themselves go by in 0x5C0A/0x5C0C — the same
    division 0x5C06 already draws (see the module docstring).
    """
    return struct.pack(">I", chara_id)


def training_battle_info_params(
    team: int, team1_rows: "list[bytes]", team2_rows: "list[bytes]"
) -> bytes:
    """0x5C06's body for ONE recipient — ``team`` is the side they are on.

    ⚠️ Do not reuse the result for a second recipient on the other side. The
    two rosters are the same for everybody; the leading byte is not.
    """
    out = struct.pack(">B", team)
    for rows in (team1_rows, team2_rows):
        out += struct.pack(">H", len(rows)) + b"".join(rows)
    return out
