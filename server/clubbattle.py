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
MSG_CL_CAST_BATTLE_COMMAND = 0x5C0A
MSG_SV_ERROR_BATTLE_COMMAND = 0x5C0B
MSG_SV_NOTIFY_BATTLE_COMMAND = 0x5C0C
MSG_CL_NOTIFY_BATTLE_TURN_END = 0x5C16

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

#: How many per-character status counters 0x5C09 carries, and the number of
#: rows in the client's own ``clubstatus`` table.
#:
#: ⭐⭐ Two independent witnesses, which is why this is not a guess:
#:
#: 1. The reader at 0x8F0B90 walks the array with an explicit counted loop —
#:    ``mov ebp, 8`` / ``call [edx+0x28]`` (u16) / ``add edi, 2`` / ``dec ebp``
#:    / ``jne``. The 8 is an immediate in the instruction stream. Its outer
#:    loop then advances one entry with ``add ebx, 0x18``, and 4 + 2 + 1 +
#:    (1 pad) + 8*2 is exactly 0x18, so the stride agrees with the count.
#: 2. ``clubstatus`` in the client's own idlist data is an IdBn table whose
#:    header count is 8 and whose file is 32 + 8*24 bytes: 通常, 眠り, しびれ,
#:    沈黙, 混乱, 練習不能, 奥義無効, 奥義反射.
#:
#: The array is therefore indexed by clubstatus id, and entry 0 is 通常 —
#: the not-afflicted row, which is why an untouched fighter sends all zeroes.
NUM_OF_CLUB_STATUS = 8

#: charaId u32 + vitality u16 + energy u8 + NUM_OF_CLUB_STATUS x u16. ⚠️ 23,
#: not the 0x18 the client's struct advances by: that stride includes a pad
#: byte after ``energy`` so the u16 array lands aligned. Padding is a fact
#: about their memory, not about the wire, and the reader takes each field
#: through its own width-checked accessor.
TURN_START_ROW_SIZE = 23

#: ⚠️ INVENTED. Nothing seen so far says how long a turn is allowed to take;
#: this is a minute because a minute is a plausible minute.
TURN_TIMEOUT_MS = 60_000


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


def turn_start_row(
    chara_id: int,
    vitality: int,
    energy: int,
    states: "list[int] | None" = None,
) -> bytes:
    """One ``turnStartCharaInfo``: who, their two bars, their eight counters.

    ⚠️ No ``speed`` here, and no ``clubId`` — 0x5C06 carries those once, at the
    top of the fight, and this message carries only what a turn can change.
    That asymmetry is the reason this is worth sending: ``vitality`` and
    ``energy`` appear in both messages, so giving them different values here
    is the only reading anyone gets of which value the client treats as the
    maximum and which as the current one.
    """
    counters = list(states or [])[:NUM_OF_CLUB_STATUS]
    counters += [0] * (NUM_OF_CLUB_STATUS - len(counters))
    out = struct.pack(">IHB", chara_id, vitality & 0xFFFF, energy & 0xFF)
    out += struct.pack(f">{NUM_OF_CLUB_STATUS}H", *(c & 0xFFFF for c in counters))
    if len(out) != TURN_START_ROW_SIZE:
        raise AssertionError(f"row is {len(out)}B, reader wants {TURN_START_ROW_SIZE}")
    return out


def turn_start_params(turn: int, timeout_time: int, rows: "list[bytes]") -> bytes:
    """0x5C09: the turn number, its deadline, and everybody's current numbers.

    ``timeout_time`` is a moment on the CLIENT's own clock in milliseconds,
    read through the stream's +0x10 slot as a signed 64-bit — the same slot,
    width and frame as 0x480A's arrivalTime, 0x6100's speechEndTime and
    0x6103's startTime/endTime. All four of those are already on screen and
    correct, so the frame is not being guessed at; what has not been checked
    is only whether this particular field is an absolute moment like those or
    a duration, and a client that draws a countdown answers that on sight.

    ⚠️ Unlike 0x5C06 this body is the same for every recipient: nothing in it
    is written from the reader's point of view.
    """
    out = struct.pack(">Bq", turn & 0xFF, timeout_time)
    out += struct.pack(">H", len(rows)) + b"".join(rows)
    return out


#: 0x5C0C's ``reason``, RESTORED from ``error_message.bin`` 487-489. The table
#: names three and only three, and the first of them is one of the developers'
#: own 「未使用：：：正常」 rows — a numbered slot with no sentence, which is
#: how that table spells 「this code is the success one, draw nothing」 (0x5C1C
#: reason 0 is the same). So a command that is simply accepted goes out as 0.
#:
#: ⚠️ The other two are the whole refusal policy this subsystem has:
#:
#:     1  選択できるコマンドがありません。
#:     2  コマンド選択がゲームサーバ側の制限時間内に間に合いませんでした。
#:
#: ⭐ Reason 2 is the first thing anywhere to say what ``timeoutTime`` is FOR:
#: the deadline is enforced by the server, and this is the sentence it says
#: when it passes. That is a use for the field, not yet a reading of it — see
#: the note on turn_start_params.
#:
#: ⚠️⚠️ Note what is NOT here: 「選択可能なコマンドがありません」, the sentence
#: actually on screen right now, is not in this table at all. It is row 660 of
#: the client's own ``msg_text`` (id 0x0295), between 「眠っている……」 and
#: 「敵対象を選択してください」. Different wording, different table, different
#: speaker: the client says it to itself, about a command list it built from
#: data it already holds. No reason code will ever produce it and no server
#: message clears it — only giving the client something to list will.
COMMAND_OK = 0
COMMAND_NONE_SELECTABLE = 1
COMMAND_TOO_LATE = 2


def parse_command(params: bytes) -> "tuple[int, int, int] | None":
    """0x5C0A -> ``(itemNum, isAttck, targetId)``, or None if it is malformed.

    ⚠️ ``itemNum`` indexes the player's own 部活デッキ and the wire never says
    which deck that is — 0x5C07 said, once, at the top of the fight. So the
    card a number names is only resolvable against the Fighter that sent it,
    which is why this returns the raw triple and Battle.command does the
    lookup.

    ⚠️ Whether ``itemNum`` is 0- or 1-based is UNREAD. Nothing has been on
    screen yet that would say, and the first real 0x5C0A answers it for free:
    a deck whose entries are distinguishable will name its own indexing.

    ⭐ ``isAttck`` is the client's own word (from the dump at 0x8EE3C0), and
    the two sentences it must be choosing between are next to each other in
    ``msg_text``: 「敵対象を選択してください」 and 「味方対象を選択してくださ
    い」. So a card is aimed at one side or the other and this byte says which
    — which also means ``targetId`` is a charaId in the fight, not a slot.
    """
    if len(params) < 6:
        return None
    item_num, is_attck = params[0], params[1]
    target_id = struct.unpack_from(">I", params, 2)[0]
    return (item_num, is_attck, target_id)


def command_params(chara_id: int, reason: int = COMMAND_OK) -> bytes:
    """0x5C0C: who chose, and how it went.

    ⚠️ It carries a charaId, so it is not a private answer to the chooser —
    the same argument 0x5C08 settled. A message told only to its sender does
    not need to name them. And the pairing says the same thing twice: 0x5C0A
    is a MsgCl**Cast**, and in this protocol Cast means 「repeat this to the
    others」 — MsgClCastNormalChat -> MsgSvNotifyNormalChat is the same shape,
    and so is 0x5C00 -> 0x5C01 inside this very family.

    ⚠️ What the other side DOES with it is unread. It cannot be the card: the
    body has no room for one, and 0x5C0E carries the deckItem later. The
    guess with the least invention behind it is 「that player has chosen」,
    the tick the room window draws next to a member who pressed 準備ＯＫ, but
    that is a guess and nothing here depends on it.
    """
    return struct.pack(">IB", chara_id, reason & 0xFF)


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


#: ⭐ The first turn is 1, and the screen agrees: sending turn=1 draws
#: 「残り　7　ターン」, which is 8 - 1 against the eight-turn limit the club
#: tables give. So this is a 1-based turn ORDINAL and the client subtracts it
#: from the limit itself; it is not a countdown we are supposed to send.
#: ⚠️ One data point. A second one is cheap and has not been taken: open a
#: fight with this set to 3 and the counter should read 5.
FIRST_TURN = 1


class Fighter:
    """One character in a battle, with the numbers the two messages carry.

    ``max_vitality``/``max_energy`` are what 0x5C06 announced; ``vitality``/
    ``energy`` are what 0x5C09 reports each turn. Both are kept because the
    two messages carry the value at different rates, and a single field could
    not express whichever one turns out to be the ceiling.

    ⚠️⚠️ Which one that is remains UNREAD, and the round-84 experiment says it
    is not readable from here. 0x5C09 was given vitality=5/energy=5 against
    0x5C06's 100/80 while a fight was on screen: the Status panel bars and the
    bar under the character's feet BOTH stayed full, on both clients. So the
    bars are drawn from 0x5C06 and 0x5C09's copies of the numbers do not touch
    them. That kills the plan in 2.41 — with only these two messages every bar
    is 「current == maximum」 and no fill is distinguishable from any other, so
    the 気力/素早さ pairing cannot be named here no matter what values go out.
    ⭐ The next place it can be read is the 0x5C0A/0x5C0E コマンド exchange,
    where spending 気力 should make a current value fall below its maximum for
    the first time.
    """

    def __init__(self, chara_id: int, team: int, club_id: int, info: bytes) -> None:
        self.chara_id = chara_id
        self.team = team
        self.club_id = club_id
        self.info = info
        self.max_vitality = DEFAULT_VITALITY
        self.max_energy = DEFAULT_ENERGY
        self.speed = DEFAULT_SPEED
        # A fight opens at full. ⚠️ These were deliberately seeded LOW for one
        # round to try to read the bars; see the class docstring for why that
        # experiment is over and why leaving them low would be worse than
        # useless — a permanently wounded fighter nobody wounded.
        self.vitality = self.max_vitality
        self.energy = self.max_energy
        #: One counter per clubstatus row; all zero is 通常, nothing afflicting.
        self.states = [0] * NUM_OF_CLUB_STATUS
        #: Set by 0x5C07 — 「my battle scene is up」, not 「I am ready to play」.
        self.ready = False
        self.deck_id = 0
        #: This turn's 0x5C0A as ``(itemNum, isAttck, targetId)``, or None
        #: while the player is still choosing. Cleared by every turn start,
        #: because a choice is a statement about one turn and letting last
        #: turn's stand would act for a player who did nothing.
        self.command: "tuple[int, int, int] | None" = None
        #: Whether this player has said 「done choosing」 (0x5C16) this turn.
        self.turn_done = False

    def begin_turn(self) -> None:
        """Forget last turn's choice. Called for everyone by every 0x5C09."""
        self.command = None
        self.turn_done = False

    def info_row(self) -> bytes:
        """This fighter's 83 bytes for 0x5C06."""
        return member_row(
            self.chara_id, self.info, self.club_id,
            self.max_vitality, self.max_energy, self.speed,
        )

    def turn_row(self) -> bytes:
        """This fighter's 23 bytes for 0x5C09."""
        return turn_start_row(
            self.chara_id, self.vitality, self.energy, self.states
        )


class Battle:
    """One fight in progress, from 0x5C06 until whatever ends it.

    ⚠️ Deliberately not the room it came out of. 自主トレ is the only door this
    server can open onto the 0x5C** family today, but 練習 and フリー対戦 reach
    the same messages, and a fight that held a trainingroom.Room would have to
    be rewritten the day one of those opens.
    """

    def __init__(self, fighters: "list[Fighter]") -> None:
        self.fighters = fighters
        #: One short of the first turn: every 0x5C09 advances it first, so the
        #: opening one goes out as FIRST_TURN and nothing has to special-case
        #: 「is this the first」.
        self.turn = FIRST_TURN - 1

    def find(self, chara_id: int) -> "Fighter | None":
        for fighter in self.fighters:
            if fighter.chara_id == chara_id:
                return fighter
        return None

    def side(self, team: int) -> "list[Fighter]":
        return [f for f in self.fighters if f.team == team]

    def all_ready(self) -> bool:
        """Has every fighter reported its battle scene up?

        ⚠️ Every fighter, including the leader — this is not the room's
        ready flag, where the leader is excused because pressing 「開 始」 is
        their version of it. 0x5C07 is a statement about a scene being drawn
        and the leader's scene has to be drawn too.
        """
        return bool(self.fighters) and all(f.ready for f in self.fighters)

    def begin_turn(self) -> int:
        """Advance to the next turn and clear everybody's choice. Returns it."""
        self.turn += 1
        for fighter in self.fighters:
            fighter.begin_turn()
        return self.turn

    def turn_rows(self) -> "list[bytes]":
        return [f.turn_row() for f in self.fighters]

    def summary(self) -> str:
        sides = "/".join(str(len(self.side(t))) for t in (0, 1))
        ready = sum(1 for f in self.fighters if f.ready)
        return f"turn {self.turn}, {sides}, {ready}/{len(self.fighters)} ready"


class Board:
    """Every battle currently up, found by any of its participants.

    Held by the server rather than a session for the same reason the room
    board is: a fight outlives any one message about it, and 0x5C09 has to
    reach people on other connections.
    """

    def __init__(self) -> None:
        self.battles: "list[Battle]" = []

    def open(self, fighters: "list[Fighter]") -> Battle:
        for fighter in fighters:
            self.close(fighter.chara_id)
        battle = Battle(fighters)
        self.battles.append(battle)
        return battle

    def battle_of(self, chara_id: int) -> "Battle | None":
        for battle in self.battles:
            if battle.find(chara_id) is not None:
                return battle
        return None

    def close(self, chara_id: int) -> "Battle | None":
        """Drop whatever battle this character is in, and return it.

        ⚠️ The whole battle goes, not just the one fighter. A two-player
        自主トレ with one side gone is not a fight that can continue, and
        leaving it on the board would let the next 0x5C07 from the survivor
        find a battle nobody is going to answer.
        """
        battle = self.battle_of(chara_id)
        if battle is not None:
            self.battles.remove(battle)
        return battle

    def summary(self) -> str:
        return f"{len(self.battles)} battle(s)"
