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

import os
import struct

import ability
import characters
import club

MSG_CL_CAST_BATTLE_CHAT = 0x5C00
MSG_SV_NOTIFY_NPC_BATTLE_INFO = 0x5C05
MSG_SV_NOTIFY_TRAINING_BATTLE_INFO = 0x5C06
MSG_CL_NOTIFY_BATTLE_READY = 0x5C07
MSG_SV_NOTIFY_BATTLE_READY = 0x5C08
MSG_SV_NOTIFY_BATTLE_TURN_START = 0x5C09
MSG_CL_CAST_BATTLE_COMMAND = 0x5C0A
MSG_SV_ERROR_BATTLE_COMMAND = 0x5C0B
MSG_SV_NOTIFY_BATTLE_COMMAND = 0x5C0C
MSG_SV_NOTIFY_BATTLE_ACTION_ORDER = 0x5C0D
MSG_SV_NOTIFY_BATTLE_ACTION_BEGIN = 0x5C0E
MSG_SV_NOTIFY_BATTLE_ACTION_END = 0x5C0F
MSG_SV_NOTIFY_BATTLE_REACTION = 0x5C10
MSG_SV_NOTIFY_BATTLE_EFFECT = 0x5C11
#: ⚠️ UNREAD, and the one message in this family whose place in the sequence is
#: still a guess. It carries NOTHING (the shape reader says empty), which leaves
#: only its name to read: 「the demo starts」. The pairing that makes it worth
#: trying is that its mirror already exists — 0x5C16 MsgClNotifyClubBattleTurnEnd
#: is also empty, also carries only 「it happened」, and is the client telling
#: the server it has FINISHED playing a turn. A start with no end and an end
#: with no start is the shape of one missing half.
MSG_SV_NOTIFY_BATTLE_DEMO_START = 0x5C12
MSG_CL_NOTIFY_BATTLE_TURN_END = 0x5C16
#: The three 「you got something」 messages, all of them Sv, all of them
#: OPTIONAL: the manual grants them with 〜ことがあります (p07_03 「『奥義の書』
#: や合成アイテムが手に入ることがあります」, p07_04 「合成アイテムが手に入るこ
#: とがあります」). ⚠️ NOT SENT by this server, and that is a decision rather
#: than a gap — what earns a keyword, an item or a 部活奥義 is not restored, so
#: the honest count is none, and 「ことがあります」 says none is a legal round.
MSG_SV_NOTIFY_BATTLE_GET_KEYWORD = 0x5C17
MSG_SV_NOTIFY_BATTLE_GET_ITEM = 0x5C18
MSG_SV_NOTIFY_BATTLE_GET_CLUB_SKILL = 0x5C19
MSG_SV_NOTIFY_BATTLE_RESULT = 0x5C1A
MSG_SV_NOTIFY_BATTLE_PART = 0x5C1B
MSG_SV_NOTIFY_BATTLE_END = 0x5C1C

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

#: tmn::NUM_OF_CHARA_ABILITY, the length of both ability arrays in 0x5C1A.
#: Taken from ability rather than restated: the same six are already on screen
#: through 0x4310, and a second definition here would be the untested one. The
#: reader agrees independently — both loops in 0x8F1BD0 count down from an
#: immediate ``mov ebp, 6``.
NUM_OF_CHARA_ABILITY = len(ability.ABILITIES)

#: charaId u32 + vitality u16 + energy u8 + NUM_OF_CLUB_STATUS x u16. ⚠️ 23,
#: not the 0x18 the client's struct advances by: that stride includes a pad
#: byte after ``energy`` so the u16 array lands aligned. Padding is a fact
#: about their memory, not about the wire, and the reader takes each field
#: through its own width-checked accessor.
TURN_START_ROW_SIZE = 23

#: ⚠️ INVENTED as a number, but no longer a free choice. Three things bound it:
#:
#: 1. The manual states the SEMANTICS (p07_03): 「０になる前に入力を完了できな
#:    かった場合、キャラクターは行動しません」 — running out costs that
#:    character their action, and the round then proceeds to 「全員の行動が実行
#:    されます」 as usual. So on the original, a timeout does NOT end anything;
#:    it drops one participant's move and the turn carries on.
#: 2. The manual gives a figure everywhere it can — 「制限時間は１０分です」
#:    (p06_03), 「制限時間は３分です」 (p08_03) — and pointedly gives none here.
#:    That fits a value the server hands down per turn, which is what this is.
#: 3. The client caps it. At 60_000 it draws a live "あと N 秒" counter and
#:    counts down cleanly (60 → 53 → 10). At 600_000 the counter stops meaning
#:    anything: it sits in the single digits and jumps around (8, 3, 5, 9).
#:    Something far narrower than the i64 holds the remainder client-side, so
#:    ⭐ whatever the original sent, it FIT — and a minute does.
#:    ⚠️ The exact width is NOT established: 600_000 mod 65_536 ≈ 10s lands in
#:    the observed range but does not explain the jumping. Cheap probe: send
#:    65_000, just under a u16 of milliseconds; a clean 65 counting down says
#:    u16 of ms.
#:
#: ⭐ The semantics in (1) ARE implemented as of round 88: a turn whose
#: deadline passes resolves with whoever chose in time, and the ones who did
#: not simply take no action. See MpsServer._drain_battle. ⚠️ The dead end that
#: used to be blamed on this number was never about its width — it was the
#: missing 0x5C0D/0x5C0E/0x5C0F, so do not reach for this constant when a
#: battle stalls. Widening it past what the client can represent (tried:
#: 600_000) puts a value on the wire the original could never have sent.
TURN_TIMEOUT_MS = 60_000

#: How long THIS SERVER waits before resolving a turn nobody finished, in
#: seconds. Normally exactly the 60 above, and the two are the same number for
#: a reason: the wire's timeoutTime and the server's own patience describing
#: different deadlines is a bug, not a feature.
#:
#: ⭐ TMO_TURN_DEADLINE_S overrides ONLY this side. It exists for measuring with
#: a real client, where the constraint is not the protocol but the person: the
#: コマンド window gives 60 seconds, and one look-then-click round trip costs
#: 15 (round 61). Pausing the VM freezes the client's own countdown — it draws
#: the counter itself and closes the window when it hits zero — but the server
#: keeps counting in real time and would resolve the turn out from under a
#: paused client. This is the other half of that: pause the client, and the
#: server waits too.
#:
#: ⚠️⚠️ IT CHANGES NO BYTE ON THE WIRE. turn_start_params still sends
#: TURN_TIMEOUT_MS, because 600_000 was measured to make the client's counter
#: jump around (see above) — a value the original could not have sent. What
#: this moves is only how long this server is willing to wait.
#:
#: ⚠️ Unset is the shipping behaviour, so nothing has to be remembered or put
#: back: a measurement session that forgets to unset it leaves the default
#: intact for the next one.
#:
#: ⚠️ Do not leave it set while testing the TIMEOUT semantics themselves
#: (「制限時間以内に入力を完了できなかった場合、キャラクターは行動しません」),
#: which is the one behaviour it hides.
TURN_DEADLINE_S = float(os.environ.get("TMO_TURN_DEADLINE_S") or TURN_TIMEOUT_MS / 1000)

#: 「1）〜3）を８ターンが終了するまで、もしくはどちらかの体力が全員０になるまで
#: 繰り返します」 (p07_03). RESTORED, and it agrees with what the screen drew
#: when turn=1 went out: 「残り　7　ターン」 is 8 - 1.
#:
#: ⚠️ Nothing here implements what happens when the count runs out. The manual's
#: next line is 「5）勝敗が表示されます」, which is 0x5C1A/0x5C1C, and neither is
#: written. So this is used only to STOP starting turns — a ninth 0x5C09 would
#: draw 「残り　-1　ターン」 and that is a number the original could not send.
TURN_LIMIT = 8


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


def action_order_params(chara_ids: "list[int]") -> bytes:
    """0x5C0D: ``order[u16] = {charaId u32}``, the turn's running order.

    ⭐ The manual names the thing this feeds: 「味方の状態」…キャラクターの
    **行動順**、残り体力、残り気力などが表示されます (p07_03). So the order is
    the server's to state and the client draws it next to each ally.

    ⚠️ THE LIST IS THE ONES WHO ACT, not everybody in the fight. That is a
    choice, and the cheap alternative (everybody, with the non-actors at the
    end) is not excluded by anything read so far. It is made this way because
    the 0x5C0E stream that follows walks exactly this list, and an order naming
    a character no ActionBegin ever mentions would be the server saying two
    different things about the same turn.
    """
    out = struct.pack(">H", len(chara_ids))
    return out + b"".join(struct.pack(">I", c) for c in chara_ids)


def action_begin_params(
    chara_id: int, kind: int, payload: bytes, target_id: int
) -> bytes:
    """0x5C0E: who acts, the card they play, and who it is aimed at.

    ⭐⭐ ``deckItem`` is the SAME six bytes the client sent in 0x5B03 and that
    the save file has been holding since round 79 — ``kind u8`` plus a block
    the client bulk-copies rather than parses, so it goes back out verbatim.
    ⚠️ Those six are little-endian (the only such field group in this protocol,
    see club.DECK_ITEM_KEYWORD); re-encoding them here would byte-swap a struct
    that was never meant to be read on this side.

    ⚠️ This is why 0x5C07's deckId had to be stored. The wire never repeats
    which of the three decks a fighter brought, so ``itemNum`` in 0x5C0A is
    only resolvable against the deck named once at the top of the fight.
    """
    if len(payload) != club.DECK_ITEM_BYTES:
        raise AssertionError(
            f"deckItem payload is {len(payload)}B, reader wants "
            f"{club.DECK_ITEM_BYTES}"
        )
    out = struct.pack(">IB", chara_id, kind & 0xFF) + payload
    return out + struct.pack(">I", target_id)


def action_end_params(chara_id: int) -> bytes:
    """0x5C0F: that character is done acting, and nothing else.

    ⚠️ It carries no result. Whatever the action DID — damage, a status, a
    miss — is 0x5C10 Reaction and 0x5C11 Effect. Both can now be BUILT (see
    below) but neither is wired into the turn: what an action does to anybody
    has no restored formula, so this server plays the card and changes nothing.
    The pair is the turn's structure, not its outcome.
    """
    return struct.pack(">I", chara_id)


#: 0x5C10's ``reaction`` and 0x5C11's ``type``, in the client's own words.
#:
#: ⭐⭐ The wording for BOTH lives in one run of ``msg_text.bin``, 717-752 —
#: which is a different table from the two whose subject matches (see the
#: warning below), and the only one whose STRINGS are the ones a screen has
#: actually shown:
#:
#:     717 防御（ガマン）     730 パラメータ増   738 ステータス眠り   745 眠り回復
#:     718 攻撃（使った）     731 パラメータ減   739 ステータス痺れ   746 痺れ回復
#:     719 回避（かわした）   732 体力           740 ステータス沈黙   747 沈黙回復
#:     720 反撃（仕返し）     733 気力           741 ステータス混乱   748 混乱回復
#:     721 反射（はじき返した）734 攻撃力        742 練習不能         749 行動不可
#:     722 効果無効           735 守備力         743 練習不可         750 行動中止
#:     723 ダメージ           736 防御力         744 効果反射         751 防御解除
#:     724 「 %3d %%」        737 素早さ                              752 効果無効効果消去
#:     725-729 蚊に刺されたような / 小さな / それなりの / 大きな / 痛烈な
#:
#: ⭐ 725-729 with 724 say something worth having on its own: ダメージ in this
#: client is NARRATED IN BANDS, not printed as a number. So 「the client draws
#: the number on the character」 — which is what round 89 expected of 0x5C11 —
#: is not how at least part of this works. MEASURED: value=999 drew no digit.
#:
#: ⚠️⚠️ WHAT IS PINNED IS TWO CELLS, EACH BY ONE SAMPLE (round 90, real client):
#: ``0x5C11 type=0`` drew 「…は眠ってしまった！」 and left a lasting zzz bubble;
#: ``0x5C10 reaction=0`` drew 「すばやく身をかわした！」. That fixes what those
#: two bytes DO, not where each list starts counting — whether ``type`` is
#: indexed from 738 and ``reaction`` from 719 (rather than 717) is still one
#: assumption each. ``/cb fxnext 1 1 0 1`` settles both in one shot.
#:
#: ⚠️⚠️ DO NOT go back to ``clubstatus.bin`` / ``keyword_defense_characteristic
#: .bin`` for this. Their subjects match beautifully, the client really does use
#: the latter (every card in the コマンド window prints a 守備特性 column), and
#: 眠り/回避 sit at id 1 in both — so 「wire = table id − 1」 fits BOTH samples
#: on BOTH messages and is still wrong. That near-miss is written up as lesson
#: 31; the strings above are the evidence that outranks it.
REACTION_NAMES = ("回避", "反撃", "反射", "効果無効", "ダメージ")


def reaction_params(target_id: int, reaction: int) -> bytes:
    """0x5C10: ``targetId u32, reaction u8`` — 「being hit」 as a visible act.

    Reader at 0x9BB390: two calls and then ``ret 8`` — ``[edi+0x04]`` through
    the stream vtable's ``+0x24`` (unsigned 32) and ``[edi+0x08]`` through
    ``+0x2c`` (unsigned 8). the shape reader agrees at ``4+1``, and the dump names the
    two ``targetId`` and ``reaction``.

    ⚠️ It is ``targetId``, NOT ``charaId``. 0x5C0E/0x5C0F next door name theirs
    ``charaId`` and mean the actor; this one and 0x5C11 mean the one acted
    upon. Copying the neighbour's field name is how they would get swapped.
    """
    return struct.pack(">IB", target_id, reaction & 0xFF)


def effect_params(
    target_id: int, effect_type: int, value: int, value2: int
) -> bytes:
    """0x5C11: ``targetId u32, type u8, value s16, value2 s16``.

    Reader at 0x8F1680: four calls then ``ret 8`` — ``[edi+0x04]`` via ``+0x24``
    (unsigned 32), ``[edi+0x08]`` via ``+0x2c`` (unsigned 8), then ``[edi+0x0a]``
    and ``[edi+0x0c]`` BOTH via ``+0x18``. ⚠️ ``+0x09`` is a hole in the struct,
    not a field — the u8 is followed by u16 alignment, the same way 0x5C1A's
    ``+0x05`` is skipped. On the wire the four are adjacent: 4+1+2+2 = 9 bytes.

    ⚠️⚠️ ``value`` AND ``value2`` ARE SIGNED. The stream vtable at 0xC0B8B0 is
    four signed readers (``+0x10 +0x14 +0x18 +0x1C``, 64/32/16/8) followed by
    four unsigned (``+0x20 +0x24 +0x28 +0x2C``), so ``+0x18`` is signed 16 —
    and this is the ONLY place in the 0x5C** family that uses it. 0x5C1A's
    twelve reads are all ``+0x28``/``+0x2c``, both unsigned, including its six
    ability u16s; the difference is deliberate rather than incidental. ⭐ It
    also fits what the manual says this screen shows: 「自分の状態」…残り体力、
    残り気力、攻撃力増減状態、防御力増減状態、ステータス異常状態 (p07_03) —
    増減 needs a sign. So these are packed as ``>h`` and a caller may pass a
    negative number.

    ⭐⭐ ``type`` SELECTS A STATUS EFFECT, and it does more than animate one:
    MEASURED with a real client (round 90), ``type=0`` drew 「…は眠ってしまった！」,
    turned the character white and left a zzz bubble over their head THAT WAS
    STILL THERE ON LATER TURNS. So this message SETS state the client then keeps
    — it is not a one-off flourish. The vocabulary is REACTION_NAMES' table
    above; ⚠️ which row ``type=0`` counts from is still one sample, and
    ``value2`` (duration? second operand? table id?) is untouched.
    ⚠️ ``value`` drew nothing at all for ``type=0`` — see the band-narration
    note above before assuming any ``type`` prints its number.

    ⚠️⚠️ MEASURING WHAT A FIELD MEANS IS NOT INVENTING A DAMAGE RULE. Nothing
    here decides when an effect happens or how big it is; that rule has no
    restored source at all, which is why neither this nor reaction_params is
    called from the turn loop.
    """
    return struct.pack(
        ">IBhh",
        target_id,
        effect_type & 0xFF,
        max(-32768, min(32767, value)),
        max(-32768, min(32767, value2)),
    )


#: 0x5C1A's ``winTeam``, and the one field in this message whose ENCODING is
#: invented while its VALUE is restored. Two separate questions, kept apart:
#:
#: 1. WHICH OUTCOME this server has to announce is settled by the manual, and
#:    settled unusually cleanly. p07_04's 勝敗の判定方法 has three branches, and
#:    the third one is a footnote that reads like it was written for exactly
#:    this situation: 「※双方ともが相手に十分なダメージを与えていない場合は、
#:    士気が低いとみなされ、両方が負けになります」. Nothing in this server
#:    subtracts 体力 from anybody — 0x5C10/0x5C11 are unimplemented and no
#:    damage rule is restored — so BOTH sides deal zero damage, and the first
#:    two branches (相手を全員リタイヤ / 残り体力の合計が多く**かつ相手に十分な
#:    ダメージ**) both require damage that was never dealt. ⭐⭐ So 「nobody
#:    wins」 is the OUTCOME THE ORIGINAL RULE PRODUCES here, not a stand-in
#:    picked because the winner is unknown. ⚠️ It stops being right the moment
#:    damage exists; this constant is where that shows up.
#:    ⚠️ p07_03 (ＮＰＣ戦) has no such third branch — its 「それ以外の場合は、
#:    プレイヤーの負け」 makes a damage-less fight a plain player loss. Same
#:    fight, two rule sheets: do not carry this constant over to 練習.
#:
#: 2. WHAT BYTE spells it is UNREAD. Teams are 0-based (0x5817, 0x5C06) and
#:    there are two of them, so 0 and 1 are spoken for and 「neither」 needs a
#:    third value; 2 is the next one and the field is read unsigned (+0x2c), so
#:    255 would arrive as 255 rather than -1. ⭐ Cheap to measure and cheap to
#:    correct: ``/cb result <n>`` sends one of these into a fight already on
#:    screen. Until a screen has been read, this is a guess wearing a name.
WIN_TEAM_NEITHER = 2

#: 0x5C1C's ``reason``, RESTORED from ``error_message.bin`` 496-497 — the whole
#: table for this message, two rows:
#:
#:     0  未使用：：：正常
#:     1  サーバーとクライアントとの同期が取れません。
#:
#: ⭐ Same shape as 0x5C0C: row 0 is a developers' unfilled slot, which is this
#: table's way of writing 「this code is the success one, say nothing」. So a
#: fight that simply finished ends with 0, and 1 is a sentence this server has
#: no way to mean — it would be claiming the client and the server disagree
#: about the fight, which is not something the code can currently detect.
END_NORMAL = 0
END_OUT_OF_SYNC = 1

#: 0x5C1B's ``reason``, from ``error_message.bin`` 494-495. ⚠️ NOT IMPLEMENTED,
#: kept here because reading it settled what 0x5C1C is not: 0x5C1B is the
#: one-person message (「通信が切断されたため、クラブ活動を強制終了しました」,
#: charaId + reason), 0x5C1C the whole-fight one. A disconnect mid-battle
#: currently drops the Battle server-side without telling the survivors, which
#: is what this message is for.
PART_DISCONNECTED = 0
PART_OUT_OF_SYNC = 1


def result_params(
    win_team: int,
    before_gauge: int,
    after_gauge: int,
    before_lv: int,
    after_lv: int,
    before_ability: "list[int]",
    after_ability: "list[int]",
    book_category: int = 0,
    book_id: int = 0,
    hurt: int = 0,
    before_gousei_entry_max: int = 0,
    after_gousei_entry_max: int = 0,
) -> bytes:
    """0x5C1A: 「5）勝敗が表示されます」, the screen a fight ends on.

    Twelve arguments for twelve fields, in the client's own words. Reader at
    0x8F1BD0, names from the dump at 0x8F1EE0, and the two agree read for read
    — the deserializer makes exactly twelve calls and then ``ret 8``:

        winTeam                       u8   [edi+0x04]  (+0x2c, unsigned)
        endResult.beforeGauge         u8   [edi+0x06]
        endResult.afterGauge          u8   [edi+0x07]
        endResult.beforeLv            u8   [edi+0x08]
        endResult.afterLv             u8   [edi+0x09]
        endResult.beforeAblity        u16 x NUM_OF_CHARA_ABILITY  [edi+0x0a]
        endResult.afterAblity         u16 x NUM_OF_CHARA_ABILITY  [edi+0x16]
        endResult.book.categoryId     u16  [edi+0x22]
        endResult.book.id             u16  [edi+0x24]
        endResult.hurt                u8   [edi+0x26]
        endResult.beforeGouseiEntryMax u8  [edi+0x27]
        endResult.afterGouseiEntryMax  u8  [edi+0x28]

    ⭐ The two ability loops are ``mov ebp, 6`` immediates in the instruction
    stream, which is the same count ``chara_ability_type.bin`` has records and
    the same six 0x4310 already draws (ability.ABILITIES). Two witnesses, so
    the 6 is a decode rather than a length fitted to a buffer (an earlier lesson).

    ⚠️⚠️ THIS MESSAGE IS PER-RECIPIENT. ``beforeAblity``/``afterAblity`` are one
    character's six numbers and the fight holds several characters, so it
    cannot be broadcast from one shared buffer — the same rule 0x5C06 is under
    for its ``team`` byte. ``winTeam`` by contrast is an absolute team index:
    0x5C06 already tells each client which side it is on, so the winner does
    not need restating in the recipient's own coordinates.

    ⚠️ EVERY before/after PAIR GOES OUT EQUAL from this server, and that is the
    finding, not a placeholder. 「使用したキーワードの能力属性や、使用した部活
    奥義のクラブ属性によって、能力パラメータが増加します」 (p07_03) names a
    rule — which keyword raises which ability, by how much — that is not
    restored anywhere. An 「after」 larger than its 「before」 would be this
    server inventing a reward curve and then writing it into a save file.
    ⭐ Sending them as a matched pair is also what makes them a RULER: the
    caller can set them apart deliberately (``/cb result``) and read off which
    half of each pair the screen actually draws.

    ⚠️ ``book`` is 「奥義の書」 and 自主トレ never grants one — p07_04 drops it
    from the reward sentence that p07_03 has it in. {0, 0} is 「no book」 on the
    same argument as the unsent 0x5C17/0x5C18/0x5C19: a category and an id are
    a key the client looks up, so any other value would be a made-up lookup.

    ⚠️ ``hurt`` is 【怪我】, and it has a restored TRIGGER with no restored
    THRESHOLD: 「ストレスが高い状態でクラブ活動に参加すると怪我をする場合があ
    ります」 (both pages). 「高い」 is not a number and 「場合があります」 is not
    a certainty, so 0 goes out until something says where the line is.
    """
    if len(before_ability) != NUM_OF_CHARA_ABILITY:
        raise AssertionError(
            f"beforeAblity is {len(before_ability)} long, reader wants "
            f"{NUM_OF_CHARA_ABILITY}"
        )
    if len(after_ability) != NUM_OF_CHARA_ABILITY:
        raise AssertionError(
            f"afterAblity is {len(after_ability)} long, reader wants "
            f"{NUM_OF_CHARA_ABILITY}"
        )
    out = bytearray(
        struct.pack(
            ">BBBBB",
            win_team & 0xFF,
            before_gauge & 0xFF,
            after_gauge & 0xFF,
            before_lv & 0xFF,
            after_lv & 0xFF,
        )
    )
    for row in (before_ability, after_ability):
        for value in row:
            out += struct.pack(">H", value & 0xFFFF)
    out += struct.pack(">HH", book_category & 0xFFFF, book_id & 0xFFFF)
    out += struct.pack(
        ">BBB",
        hurt & 0xFF,
        before_gousei_entry_max & 0xFF,
        after_gousei_entry_max & 0xFF,
    )
    return bytes(out)


def end_params(reason: int = END_NORMAL) -> bytes:
    """0x5C1C: the fight is over, one byte saying how.

    Reader at 0x8D84A0 — a single call through ``[eax+0x1c]``, which is the
    SIGNED 8-bit slot of the stream vtable rather than the unsigned one every
    other reason byte in this family uses. ⚠️ Noted, not exploited: both
    restored values are 0 and 1, where the two readings agree.
    """
    return struct.pack(">b", max(-128, min(127, reason)))


def part_params(chara_id: int, reason: int = PART_DISCONNECTED) -> bytes:
    """0x5C1B: this one character has dropped out of the fight.

    ⚠️ Built but not yet wired to anything — see PART_DISCONNECTED.
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
        #: Whether this turn's actions have already gone out. Set by the
        #: 0x5C0D/0x5C0E/0x5C0F run, cleared by the next turn start.
        #:
        #: ⚠️ It exists because a turn resolves from two places — the last
        #: 0x5C0A, and the deadline passing — and both can happen: a command
        #: that arrives while the timeout drain is running would otherwise
        #: play the round a second time.
        self.resolved = False
        #: ⚠️⚠️ A PROBE, not gameplay: ``(type, value, value2, reaction)`` to
        #: splice into the NEXT turn's action stream as 0x5C11/0x5C10, or None.
        #: Set by ``/cb fxnext``, cleared as soon as it fires.
        #:
        #: It exists because of a measured dead end (round 90). ``/cb fx``
        #: replayed a whole stream with the effects inside it, into a turn that
        #: had ALREADY resolved and played — and the client drew nothing at all:
        #: not the effects, not even the actions it had just animated. So a
        #: second stream inside one turn is simply ignored, and 「the screen drew
        #: nothing」 said something about the replay rather than about 0x5C11.
        #: The only way to ask what these two messages draw is to have them in
        #: the turn the client is going to play anyway, which is what this is.
        #:
        #: ⚠️ It changes WHAT IS SENT during a normal resolve, which no other
        #: probe here does — hence one-shot, and hence the log line in
        #: _battle_resolve saying the turn was doctored.
        self.fx_probe: "tuple[int, int, int, int] | None" = None
        #: When this turn's choices close, on the SERVER's monotonic clock.
        #: ⚠️ Not the ``timeoutTime`` on the wire: that one is a moment on each
        #: recipient's own clock (0x5C09 states it per session, the way 0x480A
        #: does), and comparing our own elapsed time against a client's timebase
        #: is the mistake 2.15 already cost a round.
        self.deadline = 0.0

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
        self.resolved = False
        for fighter in self.fighters:
            fighter.begin_turn()
        return self.turn

    def finished(self) -> bool:
        """Has the eight-turn limit been reached?

        ⚠️ The manual's other ending — 「どちらかの体力が全員０になるまで」 — is
        not testable here: nothing takes 体力 off anybody, because no damage
        formula has been restored. So this asks the only half that can be
        answered, and the fight that reaches it simply stops (see TURN_LIMIT).
        """
        return self.turn >= TURN_LIMIT

    def all_chosen(self) -> bool:
        """Has every fighter sent their 0x5C0A this turn?

        ⚠️ 「全員のコマンド入力終了後、全員の行動が実行されます」 (p07_03) is
        this condition exactly — and the manual's preceding line says the OTHER
        way a turn can reach that point is the clock running out on somebody.
        Both callers are in MpsServer; neither is in here, because a Battle has
        no way to tell the time on a client's behalf.
        """
        return bool(self.fighters) and all(f.command is not None for f in self.fighters)

    def all_turn_done(self) -> bool:
        """Has every fighter reported 0x5C16 「my turn animation is over」?

        ⭐ The same shape as all_ready: the next 0x5C09 waits for the LAST one,
        because each client plays the action stream at its own pace and a turn
        started on the first report would begin for somebody still watching the
        previous one.
        """
        return bool(self.fighters) and all(f.turn_done for f in self.fighters)

    def actors(self) -> "list[Fighter]":
        """Who acts this turn, in the order they act.

        ⚠️⚠️ THE ORDER IS INVENTED. What is restored is only that an order
        exists and that the client draws it (p07_03 lists 行動順 among the
        things 「味方の状態」 shows). Nothing read so far says what decides it.

        ⭐ 素早さ is used because it is the only field in this family whose name
        could mean 「acts sooner」 — 0x5C06 carries vitality/energy/speed per
        fighter and this is the one that has no other job. Ties keep roster
        order, so a fight where everybody has the same speed (which is every
        fight today: DEFAULT_SPEED is a placeholder) is at least stable rather
        than arbitrary.

        ⚠️ Fighters who did not choose are left out — 「０になる前に入力を完了
        できなかった場合、キャラクターは行動しません」.
        """
        chose = [f for f in self.fighters if f.command is not None]
        order = sorted(
            enumerate(chose), key=lambda pair: (-pair[1].speed, pair[0])
        )
        return [fighter for _index, fighter in order]

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
