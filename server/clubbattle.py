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

⚠️ The u16/u8/u8 width split used to be inferred here, from the order the
reader calls its accessors in, and this paragraph said the pairing of *name*
to *width* had no second witness — so ``energy`` and ``speed`` were given
DIFFERENT defaults on purpose, to be read off the screen the first time a
battle drew. That experiment was tried twice and failed twice.

⭐⭐ IT NOW HAS ITS SECOND WITNESS, and the client handed it over. The NPC
opponent table the original 練習 mode draws its fighters from carries the same
three values per row, and the client reads them at three fixed offsets with
exactly these widths — ``mov ax, word ptr [esi+0x44]`` for 体力, then
``mov al, byte ptr [esi+0x46]`` and ``mov al, byte ptr [esi+0x47]``. Same
order, same widths, an independent reader. ⭐ The table also separates the two
u8: one of them is the SAME value on every row while the other rises
monotonically with 部活レベル, and a quantity that never varies cannot be the
one that orders 行動順 (p07_03 「キャラクターの行動順」) — so the constant one
is 気力 and the rising one is 素早さ.

⚠️ THE THREE DEFAULTS BELOW ARE STILL THIS SERVER'S INVENTION. What the
finding retires is the width/name question and the probe that was waiting on
it, not the numbers: the real ones live in the client's club data tables, and
whether this server should carry those tables is a separate decision that has
not been taken. Nothing here reads them.
"""
from __future__ import annotations

import os
import struct

import ability
import characters
import club

MSG_CL_CAST_BATTLE_CHAT = 0x5C00
MSG_CL_NOTIFY_BATTLE_LEVEL = 0x5C03
MSG_SV_ERROR_BATTLE_LEVEL = 0x5C04
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
#: ⭐ 0x5C17's share of that gap is down to one number as of round 196: which
#: キーワード 習熟 yields is in `keyword.bin` (+46..+52), which of those a
#: character is eligible for is next to it (+54..+60, one per slot: 0 male,
#: 1 female, 2 either), and where the gauge fills is `club.keyword_full_scale`.
#: ⚠️ What one *use* adds is not, and it is the last thing between here and
#: sending this message. ⚠️ 習熟度 is not only the gate: `p07_02` says it also
#: raises a キーワード's attack and defence, so raising it moves more than this.
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

#: ⭐⭐⭐ THE PLAYER'S 体力／気力／素早さ, off the opponents' own restored curve.
#:
#: ⚠️⚠️ What used to be here was `100 / 80 / 40`, three numbers invented before
#: anything was known about the scale they had to live on. They are gone. The
#: opponents this server now fields carry 550-1999 体力, a flat 99 気力 and
#: 120-255 素早さ, so a 100-体力 player was not merely arbitrary, it was in the
#: wrong currency -- the kind of invention a restored ruler makes decidable
#: rather than a matter of taste.
#:
#: ⭐⭐ RESTORED, all of it except one step: `training_npc.bin` gives 部員Ａ-Ｋ
#: as ELEVEN IDENTICAL RUNGS IN ALL EIGHT CLUBS, indexed by 部活レベル --
#:
#:     部活Lv  0    2    5    8   11   15   19   23   27   31   35
#:     体力   550  610  630  650  680  710  730  750  780  810  830
#:     素早さ 128  136  144  152  160  168  176  184  192  192  192
#:     気力    99 on every one of the 144 rows in the table
#:
#: ⚠️ INVENTED — the player's 体力／気力／素早さ, taken off the opponents' own
#: restored ladder by 部活レベル. The invented step is only that a PLAYER is on
#: that ladder at all. Nothing
#: read so far says a player's numbers come from anywhere; the save file has no
#: field for them and no message carries them inbound. What makes this the
#: smallest available invention rather than a new curve is that it borrows a
#: restored one instead of drawing one, and that it lands the player at level 0
#: exactly where 対戦レベル１'s opponent stands (`7:3 野球部員Ａ`, 550/99/128) --
#: the first fight in the game is same-for-same.
#: ⭐ 気力 is the closest to restored of the three: `training_npc.bin` carries
#: the SAME value on all 144 rows, so there is no curve to invent -- only the
#: step that says a player gets that value too.
#:
#: ⭐⭐⭐ AND IT IS COMPUTED, NEVER STORED. The input is 部活レベル, which is
#: already in the save (`ability.club_level`, one slot per club), so this adds
#: no field to any record. Two reasons that was the right side to err on:
#: computing stays reversible -- a real growth source later is `f(lv) + bonus`,
#: an offset added on top -- while a number written into every character's save
#: during the very rounds the curve is being tuned would leave old characters
#: behind and make the next measurement unreadable.
#: ⚠️ Not to be confused with the 残り体力/残り気力 inside a fight: those live on
#: the Battle's Fighter objects, end with the fight, and never touched a save.
PLAYER_STAT_CURVE = (
    (0, 550, 128), (2, 610, 136), (5, 630, 144), (8, 650, 152),
    (11, 680, 160), (15, 710, 168), (19, 730, 176), (23, 750, 184),
    (27, 780, 192), (31, 810, 192), (35, 830, 192),
)

#: 気力 on every row of `training_npc.bin`, all 144 of them.
PLAYER_ENERGY = 99


def player_stats(club_level: int) -> "tuple[int, int, int]":
    """``(vitality, energy, speed)`` for a player at this 部活レベル.

    The curve is a step function, not an interpolation: it names the rungs the
    opponents actually stand on, and a player between two rungs takes the lower
    one. ⚠️ Reading it as a line through those points would be inventing a
    shape the table does not have -- 部員 exist only at those eleven levels.
    """
    vitality, speed = PLAYER_STAT_CURVE[0][1], PLAYER_STAT_CURVE[0][2]
    for rung, rung_vitality, rung_speed in PLAYER_STAT_CURVE:
        if club_level >= rung:
            vitality, speed = rung_vitality, rung_speed
    return (vitality, PLAYER_ENERGY, speed)


#: The level-0 rung, which is what a fighter starts as before anything says
#: otherwise. ⚠️ Still the names the rest of this module uses, so that a caller
#: with no 部活レベル to hand lands on the bottom of the restored curve rather
#: than on a number of its own.
DEFAULT_VITALITY, DEFAULT_ENERGY, DEFAULT_SPEED = player_stats(0)

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

#: ⚠️ INVENTED — the コマンド選択 time limit in ms: how long a player gets each
#: turn to choose a card. Pacing rather than a rule; the manual says only
#: 「０になる前に入力を完了できなかった場合、キャラクターは行動しません」.
#: Three things bound it without fixing it:
#:
#: 1. The manual states the SEMANTICS (p07_03): 「０になる前に入力を完了できな
#:    かった場合、キャラクターは行動しません」 — running out costs that
#:    character their action, and the round then proceeds to 「全員の行動が実行
#:    されます」 as usual. So on the original, a timeout does NOT end anything;
#:    it drops one participant's move and the turn carries on.
#: 2. The manual gives a figure everywhere it can — 「制限時間は１０分です」
#:    (p06_03), 「制限時間は３分です」 (p08_03) — and pointedly gives none here.
#:    That fits a value the server hands down per turn, which is what this is.
#: 3. ⭐⭐⭐ The client's COUNTER caps it, and the cap is decimal: the
#:    「あと NN 秒」 field is two digit cells wide, so a deadline 100 seconds or
#:    more away cannot be drawn. ⚠️ What is narrow is the DISPLAY, not any
#:    container: round 120 sent 65_000 / 70_000 / 99_000 / 300_000 into one
#:    fight (one per turn) and sampled the counter at 1 Hz. The first three
#:    count down cleanly from 64 / 69 / 98, one per second, to zero. 300_000
#:    draws ONE digit — the ones place of the true remaining, tens cell blank —
#:    and then ⭐ FIXES ITSELF the second the real remaining crosses 100 → 99,
#:    frame 39 reading 0 and frame 40 reading 99. So the client's own arithmetic
#:    is right at 300 seconds; only the widget cannot spell it.
#:    ⇒ ⭐ whatever the original sent, it FIT, and it was under 100 seconds.
#:    ⚠️ That also explains 600_000 (round 84: 「single digits, jumping around
#:    — 8, 3, 5, 9」): the ones digit cycles 9→0 every ten seconds and the
#:    sampling was minutes apart. The 600_000 mod 65_536 ≈ 10s coincidence was
#:    a red herring, and so was 「u16 of milliseconds」 — 70_000 disproves it.
#:
#: ⭐ The semantics in (1) ARE implemented as of round 88: a turn whose
#: deadline passes resolves with whoever chose in time, and the ones who did
#: not simply take no action. See MpsServer._drain_battle. ⚠️ The dead end that
#: used to be blamed on this number was never about its width — it was the
#: missing 0x5C0D/0x5C0E/0x5C0F, so do not reach for this constant when a
#: battle stalls. ⚠️⚠️ SHIPPING VALUES MUST STAY UNDER 100_000: at or above it
#: the player is shown a single meaningless digit for the whole turn.
#:
#: ⭐ TMO_TURN_TIMEOUT_MS is how (3) was measured without editing this line, so
#: a measuring session leaves no trace to put back: unset is the shipping 60
#: seconds. ⚠️ It moves a byte ON THE WIRE — the opposite of TMO_TURN_DEADLINE_S
#: below, which moves only this server's patience. Use it to ask what the
#: client's countdown does with a number, never to ship a different game.
#: ⭐⭐ It sets what turn 1 opens with; ``/cb timeout`` moves the same number
#: mid-fight, which is what turned one fight into four questions rather than
#: one (Battle.turn_timeout_ms).
#: ⚠️⚠️ Leaving it set makes the room smoke test's turn-start assertions RED without
#: anything being wrong: that script computes its expectation from its own
#: process's TURN_TIMEOUT_MS, which is not this process's.
TURN_TIMEOUT_MS_STOCK = 60_000
TURN_TIMEOUT_MS = int(os.environ.get("TMO_TURN_TIMEOUT_MS")
                      or TURN_TIMEOUT_MS_STOCK)

#: How long THIS SERVER waits before resolving a turn nobody finished, in
#: seconds. Normally exactly the 60 above, and the two are the same number for
#: a reason: the wire's timeoutTime and the server's own patience describing
#: different deadlines is a bug, not a feature.
#:
#: ⭐ TMO_TURN_DEADLINE_S overrides ONLY this side. It exists for measuring with
#: a real client, where the constraint is not the protocol but the person: the
#: コマンド window gives 60 seconds, and one look-then-click round trip costs
#: 15 (round 61), so a measurement that needs several of them needs the server
#: to stop counting.
#:
#: ⚠️⚠️ It does NOT buy the client's own countdown any more time, and this
#: comment used to claim it did — 「pausing the machine the client runs on freezes the counter
#: the client draws」 was measured false in round 118. That machine's clock is
#: resynchronised to real time when it resumes, so wall time spent paused is
#: charged in full to a deadline the client computes locally: after a few
#: minutes paused, a window two seconds old already read 「あと 3 秒」. Pause
#: the client and this knob keeps the SERVER from resolving the turn; nothing
#: keeps the CLIENT from closing the window.
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

#: Whether the two above were split ON PURPOSE. Only Battle.deadline_s reads
#: it: a fight whose wire deadline is being moved by ``/cb timeout`` moves this
#: server's patience with it, unless somebody already said what that patience
#: should be.
DEADLINE_PINNED = bool(os.environ.get("TMO_TURN_DEADLINE_S"))

#: 「1）〜3）を８ターンが終了するまで、もしくはどちらかの体力が全員０になるまで
#: 繰り返します」 (p07_03). RESTORED, and it agrees with what the screen drew
#: when turn=1 went out: 「残り　7　ターン」 is 8 - 1.
#:
#: ⚠️ Nothing here implements what happens when the count runs out. The manual's
#: next line is 「5）勝敗が表示されます」, which is 0x5C1A/0x5C1C, and neither is
#: written. So this is used only to STOP starting turns — a ninth 0x5C09 would
#: draw 「残り　-1　ターン」 and that is a number the original could not send.
TURN_LIMIT = 8


# ---------------------------------------------------------------------------
# ⭐⭐⭐ THE DAMAGE RULE. Half restored, half invented, and the halves are named.
#
# RESTORED, and it is more than it looks:
#   * `p07_03`/`p07_02` state three rules outright -- 「攻撃時、このパワーは半分
#     になります」 (a keyword's 守備力 counts HALF while its holder is attacking),
#     「『習熟度』が高いと、キーワードによる攻撃や防御のパワーがアップします」,
#     and 「相手から受けるダメージを、キーワードの守備力に応じて軽減します」;
#   * `keyword.bin` gives every card an 攻撃力 (260-700) and a 守備力 (300-630),
#     and those are in the SAME CURRENCY as 体力 (550-1999) -- so an attack
#     value is a number of hit points, not a percentage and not a band index;
#   * the fight is at most eight turns (`p07_03`, TURN_LIMIT) and the weakest
#     opponent has 550 体力.
#
# ⭐⭐ THE SHAPE FOLLOWS FROM THOSE AS INEQUALITIES, which is why it is a
# subtraction rather than a ratio. Taking the medians (攻 400, 守 450):
#
#     opponent is ATTACKING  -> 450/2 = 225 effective  ->  400-225 = 175/turn
#     opponent is DEFENDING  -> 450    effective  ->  400-450 <= 0, nothing
#                               lands, which is 「守備力に応じて軽減」 exactly
#
# ⚠️⚠️ THOSE ARE UNSCALED NUMBERS and a fight does not use them raw. The first
# real fight showed why -- see DAMAGE_SCALE below, which multiplies the result
# and whose factory value is derived from two restored numbers. Read that
# constant before doing arithmetic with the 175 above.
#
# ⚠️⚠️ Only a subtraction gives 「攻撃時、守備力は半分」 anything to mean: halve
# a number inside a ratio or a band index and the halving does not change the
# outcome in the way the sentence promises. The restored rule picks the shape.
# ⭐ It also explains a third restored number: a キャプテン has 1999 体力, which
# needs 250 a turn to finish in eight, and 250 > 175 -- so ordinary cards cannot
# beat 対戦レベル１００, which is what 奥義 (攻撃力 up to 1100) and the 習熟度
# bonus are for. Three restored boundaries agreeing is the argument.
#
#     damage  = max(D_min, ATK x (1 + mastery bonus) - DEF_eff)
#     DEF_eff = the target's card's 守備力, HALVED if the target is attacking
#
# ⚠️ INVENTED, every knob below, and each one is an environment variable whose
# unset value IS the factory setting -- so a session can retune a fight without
# editing code and without leaving a tuned number behind (the same pattern as
# TMO_TURN_TIMEOUT_MS). Nothing here is written to any save.
# ---------------------------------------------------------------------------

#: ⭐ RESTORED, and ⛔️ NOT A KNOB: 「攻撃時、このパワーは半分になります」 -- a
#: card's 守備力 counts half while its holder spends the turn attacking. The 2
#: is the manual's, so tuning it would turn a restoration back into an invention.
DEFENCE_DIVISOR_WHEN_ATTACKING = 2

#: ⚠️ INVENTED — the damage floor: the least one attack can take off, so that a
#: defended hit is not simply nothing. Without it,
#: to zero or below. 1 rather than 0 because a subtraction with no floor makes
#: the 「defend」 command an absolute wall against any weaker card, and eight
#: turns of two players both defending would end with nothing having happened
#: at all -- a state the win rules have no branch for. ⭐ What would overturn
#: it: any operator-era account of a 練習 where a defended hit did nothing.
#: Knob: TMO_CLUB_DAMAGE_FLOOR.
DAMAGE_FLOOR = int(os.environ.get("TMO_CLUB_DAMAGE_FLOOR") or 1)

#: ⚠️ INVENTED — what a fully mastered card gains: 習熟度 at full scale adds this
#: share to its 攻撃力 and 守備力 (0.5 = +50%, scaling linearly). The manual says
#: 守備力. The manual says 「パワーがアップします」 and never how much.
#: ⭐ 0.5 is picked to sit at the size the restored boundaries leave room for:
#: median 400 attack against a captain needing 250 a turn is short by 75, and
#: half again on a well-practised card closes that without making a fresh card
#: useless. ⚠️ It scales linearly with useCount/fullScale, which is itself an
#: invention -- the manual says 「高いと」 and gives no curve.
#: Knob: TMO_CLUB_MASTERY_BONUS.
MASTERY_BONUS_AT_FULL = float(os.environ.get("TMO_CLUB_MASTERY_BONUS") or 0.5)

#: ⚠️ INVENTED — which 0x5C11 type an ordinary hit uses. All six draw the same
#: sentence and differ only in sound effect. 8-13 all draw the same template
#: row (5, 「$M$Nは$sダメージを受けた」) and all move the 体力 bar; 2.85 measured
#: that 8/9/10 differ from each other only in which sound effect fires.
#: ⚠️ INVENTED, narrowly: WHICH of the six a given hit should use. 8 is the
#: first, and this server sends only it. Knob: none -- a probe (/cb fxnext) can
#: still send any of them.
EFFECT_DAMAGE = 8

#: ⚠️ INVENTED — how the damage wording is banded: even shares of the TARGET's
#: maximum 体力. The count of five is the client's. value2 picks the band,
#: adjectives from 蚊に刺されたような to 痛烈な, measured in order 0-4 (round
#: 135). ⚠️ INVENTED: what fraction of the target's 体力 belongs in each band.
#: ⭐ Even fifths of the TARGET's maximum, so that the adjective means the same
#: thing to a 550-体力 部員 and a 1999-体力 キャプテン -- the alternative,
#: absolute thresholds, would call every hit on a captain 「a mosquito bite」.
DAMAGE_BANDS = 5

#: ⚠️ INVENTED — the 「did I hurt them enough」 threshold: what share of the other
#: side's total 体力 has to be gone to count as 「十分」. `p07_03`'s second branch
#: requires it,
#: ダメージを与えている」 and never says how much is enough. This is that share
#: of the opposing side's total 体力.
#: ⭐ Half rather than any other fraction because the branch it guards is
#: already the 「you were ahead when time ran out」 one -- it exists to stop a
#: fight that barely started from counting as a win, and 「more than half the
#: other side's health gone」 is the least arbitrary reading of 「十分」 that
#: does that. Knob: TMO_CLUB_DAMAGE_ENOUGH.
DAMAGE_ENOUGH_SHARE = float(os.environ.get("TMO_CLUB_DAMAGE_ENOUGH") or 0.5)

#: ⚠️ INVENTED — what share of its turns an NPC opponent spends defending rather
#: than attacking.
#: 0.0 -- always attack -- because that is the version with no second number in
#: it, and because a first fight wants the damage rule visible rather than an
#: opponent's temperament. See _battle_npc_choose for the whole of what an
#: opponent's behaviour is. Knob: TMO_CLUB_NPC_DEFEND.
NPC_DEFEND_SHARE = float(os.environ.get("TMO_CLUB_NPC_DEFEND") or 0.0)


#: ⚠️ INVENTED — the overall damage scale: the formula's result is multiplied by
#: this. ⭐ It is the one knob the very first fight proved necessary.
#: The subtraction above is in the right SHAPE and the wrong SIZE: median
#: against median it lands 175, which empties the weakest opponent's 550 体力
#: in 3.2 turns, and real card pairings reach 550 in a single turn. Eight
#: turns, an elaborate tiebreak rule for when they run out, and 「残り体力の
#: 合計」 as a criterion all describe fights that do NOT end on turn one.
#:
#: ⭐ SO THE FACTORY VALUE IS DERIVED FROM TWO RESTORED NUMBERS RATHER THAN
#: PICKED: the weakest opponent has 550 体力 (`training_npc.bin`) and a fight
#: is at most 8 turns (`p07_03`), so a median exchange should take about
#: 550/8 = 69 a turn. 69/175 = 0.39, and 0.4 is that to one figure.
#: ⚠️ What it deliberately does NOT do is change the shape: every relation the
#: restored rules fix -- 攻撃時は守備力半分, 守備力が大きいほどダメージが減る,
#: a captain being out of reach of ordinary cards -- survives a uniform scale.
#: ⭐ What would overturn it: any operator-era screenshot or video of a 練習
#: with a damage number or a bar readable across turns.
#: Knob: TMO_CLUB_DAMAGE_SCALE.
DAMAGE_SCALE = float(os.environ.get("TMO_CLUB_DAMAGE_SCALE") or 0.4)


def damage(
    attack: int, defence: int, mastery: float = 0.0,
    target_attacking: bool = True,
) -> int:
    """How much 体力 one card takes off, in the shape argued above.

    ``mastery`` is useCount/fullScale for the attacking card, 0.0 to 1.0.
    ``target_attacking`` says whether the target spent this turn attacking,
    which is the half/full question for their own card's 守備力.
    """
    powered = attack * (1.0 + MASTERY_BONUS_AT_FULL * max(0.0, min(1.0, mastery)))
    shield = defence / DEFENCE_DIVISOR_WHEN_ATTACKING if target_attacking else defence
    return max(DAMAGE_FLOOR, int((powered - shield) * DAMAGE_SCALE))


def damage_band(value: int, max_vitality: int) -> int:
    """0x5C11's ``value2``: which of the five adjectives narrates this hit."""
    if max_vitality <= 0:
        return 0
    share = value * DAMAGE_BANDS // max_vitality
    return max(0, min(DAMAGE_BANDS - 1, share))


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

    ⭐ ``itemNum`` is a 0-BASED index into that deck -- not a keyword id, and
    not 1-based. Read twice, on decks that tell the two apart: once with the
    deck shuffled so the index and the id differ (two rows, two hits), and
    once with the deck back in keyword order, where clicking the second row
    produced ``itemNum=1`` and the resolution line named the card on row 2.

    ⭐ ``isAttck`` is the client's own word (from the dump at 0x8EE3C0), and
    the two sentences it must be choosing between are next to each other in
    ``msg_text``: 「敵対象を選択してください」 and 「味方対象を選択してくださ
    い」. So a card is aimed at one side or the other and this byte says which
    — which also means ``targetId`` is a charaId in the fight, not a slot.

    ⭐ In a 1v1 with both sides connected the client fills ``targetId`` in on
    its own -- picking the attack entry put the command on the wire inside a
    single 500 ms frame, with no target prompt in between and no click on any
    character. The two sentences above are what it shows when it cannot pick
    a unique living enemy: the one prompt ever observed came from a fight
    whose opponent had already disconnected.
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


#: 0x5C10's ``reaction``, in the client's own words.
#:
#: ⚠️⚠️ THIS BLOCK USED TO CARRY A READING THAT ROUND 91 OVERTURNED, and the
#: correction runs the opposite way from what it warned about, so both halves
#: are spelled out — the old sentence is still a sayable one.
#:
#: 1. ``reaction`` is ``keyword_defense_characteristic.bin``'s id − 1, NOT a
#:    linear index into ``msg_text.bin`` 717-752. FOUR SAMPLES IN ONE FIGHT
#:    (round 91, real client): 0 →「すばやく身をかわした！」, 1 →「【card】を
#:    はじき返した」, 2 →「…の仕返し！」, 3 →「…には効果がないようだ」. The
#:    msg_text run is 719 回避 / 720 反撃 / 721 反射, so reading it linearly
#:    needs reaction=1 to draw 反撃 — the screen drew 反射, and 反撃 came at 2.
#:    The defence table (無し / 回避 / 反射 / 反撃 / 奥義耐性) fits all four
#:    with nothing swapped. ⚠️ The old text here said in so many words 「DO NOT
#:    go back to keyword_defense_characteristic.bin」. an earlier lesson.
#:
#: 2. msg_text 717-752 is a list of NAMES, not of sentences — which is why it
#:    could fit and still be wrong. What gives it away is its own neighbours:
#:    714/715/716 are ``$w`` ``$s`` ``$d``, the placeholder tokens. ⭐ THE
#:    SENTENCES ARE IN ``clubmsg_template.bin`` (30 rows, key + name + the
#:    template), and every line this project has read off a screen is one of
#:    them verbatim, ``$M$N`` and all. See EFFECT_TEMPLATES below.
#:
#: ⭐ What msg_text 724-729 and 732-737 are, then, is the pool that fills ``$s``:
#: 「 %3d %%」 plus five damage bands (蚊に刺されたような / 小さな / それなりの /
#: 大きな / 痛烈な) for the ダメージ template, and 体力 / 気力 / 攻撃力 / 守備力 /
#: 防御力 / 素早さ for パラメータ増/減. ⭐ So ダメージ really is NARRATED IN
#: BANDS rather than printed — MEASURED separately: value=999 drew no digit.
#:
#: ⚠️ The wire values that mean anything are 0-3. The table's five rows start
#: at 無し, which id − 1 sends off the bottom, so a 4 should draw nothing;
#: untested.
#: ⚠️⚠️ reaction 0 (回避) and 3 (奥義耐性) SWALLOW the 0x5C11 sent with them —
#: both mean 「it did not land」. Probe ``type`` with reaction 1 or 2 only.
REACTION_NAMES = ("回避", "反射", "反撃", "奥義耐性")


# ⭐⭐ THE CLIENT NARRATES THIS FIGHT FROM ``clubmsg_template.bin``, a 30-row
# IdBn table of TEMPLATES — 「<name> は <band> ダメージを受けた」, 「<name> の
# <parameter> が <amount> 上がった！」 and so on, placeholders and all.
#
# ⚠️ THE TABLE ITSELF IS NOT REPRODUCED HERE. It is thirty lines of the game's
# own writing, this server needs none of it to run, and 「game content stays
# out of the public tree」 is the same rule that keeps the quiz bank and the
# word lists out. What this file needs is the NUMBERS, and those are below.
#
# ⚠️⚠️ msg_text.bin 717-752 IS NOT THAT TABLE, which is what this comment used
# to say it was. It is a list of NAMES for those rows, and its own neighbours
# give it away: 714/715/716 are the placeholder tokens themselves. The runs at
# 724-729 and 732-737 are likewise not effects but the POOL that fills a
# template's 「which one」 slot — five damage bands for the damage line, and the
# six parameter names (体力 / 気力 / 攻撃力 / 守備力 / 防御力 / 素早さ) for the
# parameter lines. They matched beautifully and they were the wrong file.
#
# ⭐⭐ EIGHT LINES ALREADY READ OFF A SCREEN ARE IN HERE VERBATIM: rows 0, 2, 3,
# 8, 10, 13, 19 and 20. That is what identifies the table; nothing here is a
# guess about which file the client narrates from. ⭐ Row 20 came from a turn
# with NO probe in it at all, which is the cleanest witness of the eight.
#
# ⚠️⚠️ ``type`` IS NOT AN INDEX INTO THIS TABLE. It is not this table's row
# number, not its key, and — round 97 — not clubstatus's id either, which is
# what 2.47 concluded and what every experiment for five rounds was designed
# around. It is an enumeration of the client's own; the client picks the
# template from it. MEASURED, real client, two fights:
#
#     type          what the screen drew                         round
#     0 / 1 / 2     眠り / しびれ / 沈黙 set on the target        90 / 91
#     3             ⭐ 混乱 「…は混乱した！」, and the FOURTH
#                   status lamp lights (grey 213 → 255,225,107).
#                   So 0-3 are the four clubstatus afflictions in
#                   clubstatus order, and nothing else is         98
#     4             ⭐⭐ 「…はリタイヤした…」 (練習不能): the
#                   sprite greys out and the panel's 「練 習 中」
#                   badge changes. ⚠️ It also REPLACES that
#                   turn's 「…はボーっとしている」 line            98
#     5 / 6 / 7     nothing at all. ⭐ 7 was sent at a target
#                   ALREADY 混乱 — so these are not 「recovery
#                   lines suppressed because there is nothing to
#                   recover」, they simply draw nothing      91 / 92 / 98
#     8 - 13        ⭐ ダメージ 「…は<band>ダメージを受けた」,
#                   AND THE 体力 BAR GOES DOWN — see below for
#                   how much and which band                  97 / 98
#     14            「…の攻撃力が ８６％ 下がった！」(sent 14)     97
#     15            「…の防御力が ８５％ 下がった！」(sent 15)     97
#     16            「…の素早さが ８４％ 下がった！」(sent 16)     97
#     17 / 20 / 21  ⭐ nothing, and this is now a real negative:
#                   17 alone in a turn of its own, 20 alone, and
#                   21 in one stream with a type 3 CONTROL that
#                   did draw. ⚠️ So 17 is NOT 守備力, which is
#                   what the sweep's silence was read as          98
#     18            「…の体力が １８ 上がった！」(sent 18)         97
#     19            「…の気力が ７７ 上がった！」(sent 77)         97
#     22 - 29       nothing, and no bar moved (all eight in one
#                   stream; the settled log held the three lines
#                   an undoctored turn has)                       97
#
# ⭐⭐⭐ ``value`` REACHES THE SCREEN, in two different currencies:
#   * 体力 / 気力 (18/19) print it raw — send 77, read 77.
#   * 攻撃力 / 防御力 / 素早さ (14/15/16) print ``100 - value`` with a ％ sign.
#     ⭐ The reading that fits is 「value is what percent of base it becomes」
#     (14 → 14% left → 「dropped 86%」), ⚠️ but that is ONE sample per type.
# ⚠️⚠️ 上がった vs 下がった IS NOT ARITHMETIC ON THE NUMBER — round 98 sent
# ``type=18 value=-30`` and the screen drew 「…の体力が−３０上がった！」. The
# minus sign is PRINTED, the verb does not flip, and 「the client decides the
# verb from the sign」 (what round 97 wrote here) is dead. The verb comes with
# the type; 14/15/16 say 下がった because that is their template.
#
# ⭐⭐⭐ THE SIGN STILL HAS A JOB, and it is the value itself: that same −30
# took the 体力 bar from 66 px to 45 px — 100 → 70 out of a 66 px full bar is
# 46 px, and the sentence and the bar disagree about the WORDS while agreeing
# exactly about the NUMBER. Two accounts, one message.
#
# ⭐⭐⭐ AND THE DAMAGE TYPES SUBTRACT EXACTLY WHAT THEY CARRY. Round 97 read
# three mismatched samples off animating frames and warned not to derive a
# formula from them; with the frames left to settle (six-plus captures, then
# the last one used), two hits landed on the number:
#     100 −30 (type 18) → 45 px      (predicted 46)
#      70 −30 (type 8)  → 26 px      (predicted 26)
#      40 −10 (type 13) → 20 px      (predicted 20)
# So 「how much comes off」 needs no formula: it is ``value``.
#
# ⭐⭐ ``value2`` PICKS THE DAMAGE BAND — the 「which one」 slot of the damage
# template, 0-4 in the order msg_text.bin 725-729 lists them. Measured with
# ``value`` held at 5: value2=0 drew the weakest band, 2 the middle one, 4 the
# strongest. ⚠️ THAT ANSWERS 「what chooses the band」, which round 97 could not
# answer by varying ``value`` (8/10/50/300 all drew the weakest) — it is not a
# function of the amount at all.
#
# ⚠️⚠️ WHAT THE CLIENT KEEPS, IT KEEPS: the bar stayed at 45 px for three
# consecutive turns and the 混乱 lamp stayed lit across a turn boundary, while
# every 0x5C09 in between carried the MAXIMUM vitality and an all-zero status
# array. So the client holds its own battle state and neither repaints from
# 0x5C09 nor resets at turn start. ⚠️ That retires round 97's 「the next
# TurnStart paints over it」 — see Battle.turn_start_hp for the probe, and
# below for what that frame was really showing.
#
# ⚠️⚠️ BELOW ZERO IS NOT ZERO. 95 damage against a bar that had about 85 left
# did not empty it — the bar came back FULL. ⭐ Which is very probably what
# round 97 photographed when it saw a short bar go full 「as the next turn
# began」: its last probe was ``type=8 value=300`` into a bar that had 13 px
# left, and it recorded that the same shot took nothing off. Nothing is known
# about what the client does with the underflowed number, only that the bar
# reads full afterwards. ⚠️ A server that wants somebody knocked out cannot
# get there by sending a big enough number.


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
    above. ⭐ Round 98 finished that row-counting question the cheap way: types
    0-3 are 眠り/しびれ/沈黙/混乱, in clubstatus order, and type 3 lights the
    fourth status lamp — so the four afflictions are 0-3 and nothing else is.
    ⭐⭐ ``value2`` IS THE DAMAGE BAND for types 8-13 (0-4, weakest first) and
    was measured at three points; it is untouched for every other type.
    ⚠️ ``value`` drew nothing at all for ``type=0`` — see the band-narration
    note above before assuming any ``type`` prints its number.

    ⭐⭐⭐ THE CLIENT KEEPS ITS OWN 体力 AND DECIDES ON ITS OWN WHO IS DOWN.
    MEASURED round 99, three fights, pixels only:

    * ``type=8`` with ``value`` EXACTLY equal to what the target has left
      empties the bar (0 px) and the client prints a line NOBODY SENT IT —
      「…はリタイヤした…」 — and greys the sprite. One past that (``value``
      one over) is not a knockdown at all: the number wraps and the bar comes
      back FULL. So a big number does not knock anybody out; the exact number
      does.
    * ``type=4`` sets that same 体力 to 0 WITHOUT REPAINTING the bar, which
      makes it look inert until something else touches 体力. Effects still
      land on a downed fighter (a ``type=18`` heal refills the bar) but the
      sprite stays grey for the rest of the fight.
    * ⚠️⚠️ NONE OF THIS COMES BACK. The turn the client went down it sent
      exactly one 0x5C16 and nothing else, byte for byte like any other turn.
      There is no upstream message that can carry 「I am out」, so
      「相手を全員リタイヤ」 (see WIN_TEAM_NEITHER below) is decidable ONLY by
      a server that subtracts 体力 itself. That is a constraint the wire
      imposes, not a design preference.

    ⚠️⚠️ MEASURING WHAT A FIELD MEANS IS NOT INVENTING A DAMAGE RULE. Nothing
    here decides when an effect happens or how big it is; that rule has no
    restored source at all, which is why neither this nor reaction_params is
    called from the turn loop. ⭐ Round 99 sharpens what is missing rather
    than filling it: 「how much comes off」 is still unrestored, but 「what a
    knockdown looks like on screen」 no longer is.
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
#:    ⭐ Round 99 measured who would have to notice: a client retires itself
#:    the moment its own 体力 hits zero and never says so upstream (see
#:    effect_params), so the 全員リタイヤ branch is evaluable only here.
#:    ⚠️ p07_03 (ＮＰＣ戦) has no such third branch — its 「それ以外の場合は、
#:    プレイヤーの負け」 makes a damage-less fight a plain player loss. Same
#:    fight, two rule sheets: do not carry this constant over to 練習.
#:
#: 2. WHAT BYTE spells it is still UNREAD. Teams are 0-based (0x5817, 0x5C06)
#:    and there are two of them, so 0 and 1 are spoken for and 「neither」 needs
#:    a third value; 2 is the next one and the field is read unsigned (+0x2c),
#:    so 255 would arrive as 255 rather than -1.
#:
#:    ⭐⭐⭐ WHAT IT DOES ON SCREEN IS NO LONGER A GUESS. Measured round 100,
#:    four fights, one 0x5C1A each: the client plays TWO cutscenes back to
#:    back — the fixed 「終 了」 caption, and then, four seconds later, a
#:    verdict: 「かち」 if winTeam equals the reader's own team, 「まけ」 for
#:    anything else. Knockdowns do not enter into it (a fight where nobody was
#:    hit drew the same verdict as one where the reader had been emptied to 0
#:    体力). ⭐ So THIS value makes every player read 「まけ」 — which is
#:    exactly what p07_04's third branch prescribes when neither side dealt
#:    damage: 「両方が負けになります」. The invented encoding lands on the
#:    restored meaning.
#:    ⚠️ It still does not prove 2 is the ORIGINAL byte: every value that is
#:    not the reader's own team draws the same 「まけ」, so 2, 3 and 255 are
#:    indistinguishable on that screen. What changed is that the CONSEQUENCE
#:    is now measured rather than assumed.
#:    ⭐⭐⭐ Round 101 put a second real client on team B and read both screens
#:    at once, three fights: winTeam=0 drew かち on team 0 and まけ on team 1,
#:    winTeam=1 drew exactly the reverse, winTeam=2 drew まけ on both. So the
#:    field is an ABSOLUTE team index — one value, sent to everyone, and each
#:    client compares it with its own team. 「equals 0」 is ruled out, and
#:    「両方が負け」 is now measured on both sides rather than inferred from the
#:    one screen a script opponent does not have.
#:    ⚠️⚠️ A round-93 measurement said this field 「drives no pixel at all」.
#:    It was a sampling artifact: that round burst 4 frames (~2 s) after
#:    0x5C1A and the verdict starts at T+4 s. Do not shorten the capture.
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

#: 0x5C1B's ``reason``, RESTORED from ``error_message.bin`` 494-495. Reading it
#: also settled what 0x5C1C is not: 0x5C1B is the one-person message
#: (「通信が切断されたため、クラブ活動を強制終了しました」, charaId + reason),
#: 0x5C1C the whole-fight one.
#:
#: ⭐ Reason 0 goes out whenever a fighter's connection or 登校 ends mid-fight.
#: ⚠️ PART_OUT_OF_SYNC is not sent, on the same argument END_OUT_OF_SYNC is
#: not: claiming client and server disagree is a diagnosis this code has no way
#: to make.
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

    ⚠️ It names WHO left and WHY, and says nothing about what becomes of the
    fight — no winner, no scores, no 「it is over」 bit. That silence is the
    message's own shape, not a gap in this encoder: 0x5C1A and 0x5C1C are the
    two that speak for the whole fight, and this one is beside them rather than
    instead of them. What the client does on its own after reading it is the
    open question the server cannot answer by sending more fields.
    """
    return struct.pack(">IB", chara_id, reason & 0xFF)


# ---------------------------------------------------------------------------
# ⭐⭐⭐ 練習（ＮＰＣ対戦）'s own door, 0x5D00-0x5D03. It has been called
# unreachable in this tree since round 72, and that was true when it was
# written: 顧問 and キャプテン could not be put on a map, so the right-click
# menu the manual names could not be opened. Round 217 removed that -- a map
# object's whole identity is the charaId 0x480F carries, so `2:0 石打` stands
# up with one message -- and `menu.bin` row 0:3 顧問・キャプテンメニュー holds
# exactly four items: 20 入部, 21 クラブ活動, 11 部活奥義合成, 402 リーダー試験.
#
# ⭐⭐ 「クラブ活動」 IS THE DOOR, in the manual's own words: 「顧問または
# キャプテンの交流メニューから『クラブ活動』を選択すると、ウエストアップ画面に
# 切り替わり、対戦レベルの選択に進みます」 (p07_03). So there was never a
# missing menu item -- 練習 is not on the menu under its own name.
#
#     0x5D00 MsgClCastNpcClubBattleStart      npcId u16   <- 「クラブ活動」
#     0x5D01 MsgSvNotifyNpcClubBattleStart    level i8    (0-based ceiling)
#     0x5D02 MsgSvErrorNpcClubBattleStart     reason u8
#     0x5D03 MsgClNotifyNpcClubBattleStart    (empty)     <- 「my screen is up」
#     0x5C03 MsgClNotifyClubBattleLevel       level i8    (0-based, chosen row)
#     0x5C04 MsgSvErrorClubBattleLevel        reason u8
#     0x5C05 MsgSvNotifyNpcClubBattleInfo     the roster; the fight begins
#
# ⚠️⚠️ THREE OF THOSE WIDTHS ARE NOT WHAT THE DUMP STRINGS SUGGEST, and each was
# corrected by the client rather than by a second reading: `npcId` prints as
# `npcId=%d` like every u32 charaId in this protocol and is a u16; both `level`
# fields go through the stream vtable's SIGNED 8-bit slot; and both are indexed
# from zero, which a real client settled by drawing two rows for a 1 and then
# answering 00 for the first of them. See each parser for the disassembly.
#
# ⚠️ Shapes from the client's own deserializers; the two refusal tables are
# `error_message.bin` 498-510 and 760-775, whole and unedited. The ORDER is
# MEASURED as far as 0x5D03 -- it really does arrive after 0x5D01, the way
# 0x5C07 arrives after 0x5C06 -- and this end answers it with nothing.
# ---------------------------------------------------------------------------
MSG_CL_CAST_NPC_BATTLE_START = 0x5D00
MSG_SV_NOTIFY_NPC_BATTLE_START = 0x5D01
MSG_SV_ERROR_NPC_BATTLE_START = 0x5D02
MSG_CL_NOTIFY_NPC_BATTLE_START = 0x5D03

#: 0x5D02's ``reason``, RESTORED from `error_message.bin` 498-510. ⭐ Rows 0, 1,
#: 4 and 12 are marked 未使用 in the table itself, which is this data's way of
#: saying which codes the original never sent.
NPC_START_NO_CLUB = 2      # クラブに入部していないなどが原因で部活を開始できません。
NPC_START_BAD_STATE = 3    # 今の状態では、部活に参加することはできません。
NPC_START_OTHER_CLUB = 8   # 所属クラブ以外の部活…を行うことはできません。
NPC_START_BAD_LEVEL = 9    # 部活レベルが不正です。
NPC_START_NO_DECK = 10     # 部活デッキが作成されていない、もしくは「部活用」…
NPC_START_INJURED = 11     # 怪我をしているため、部活に参加できません。

#: 0x5C04's ``reason``, RESTORED from `error_message.bin` 760-775. Only the two
#: this server can honestly mean are named.
LEVEL_BAD = 7              # 選択された対戦レベルが不正です。
LEVEL_BAD_CLUB = 8         # 所属クラブの情報が不正です。


def parse_npc_battle_start(params: bytes) -> "int | None":
    """0x5D00's npcId -- which 顧問/キャプテン the player right-clicked.

    ⚠️⚠️ TWO BYTES, not four, and this is the one field in the flow the dump
    string got read wrong from. `the field-name extractor` prints ``npcId=%d`` and every
    other npcId in this protocol is a u32 charaId, so four was the obvious
    reading; the deserializer at 0x8DB8E0 makes ONE call through the stream
    vtable's ``+0x28``, which is uint16. MEASURED the same round: a real client
    right-clicking `2:0 石打` and choosing 「クラブ活動」 sent a two-byte body.
    ⭐ Lesson shape: a field NAME shared with another message is not a width.

    ⭐ So this cannot be a charaId -- 16 bits has no room for the category the
    charaId space puts in the high half. What arrives for `common_npc 2:0` is
    0, i.e. the row alone. ⚠️ Which is enough for the original, because
    `error_message.bin` 506 says the only 練習 you may have is your own club's
    (「所属クラブ以外の部活…を行うことはできません」) -- the club is the
    PLAYER's, and this names which of that club's two openers was clicked.
    """
    if len(params) < 2:
        return None
    return struct.unpack_from(">H", params, 0)[0]


def npc_battle_start_params(level: int) -> bytes:
    """0x5D01: the 対戦レベル the level-select screen should open on.

    ⚠️ WHAT THIS NUMBER MEANS is read from the manual, not from the client:
    「対戦レベルは、選択したレベルの対戦で勝利すると、次のレベルを選択できるよう
    になります」 -- so there is a ceiling per club that a win raises, and one
    byte at the start of the flow is the only place it could be stated.
    ⚠️ That the byte is the CEILING rather than, say, the club's own 部活レベル
    is a reading, and the screen is what settles it.

    ⚠️ SIGNED. The reader (0x8D84A0, shared with 0x5C03) goes through the
    stream vtable's ``+0x1c``, which is int8 -- the same signed slot 0x5C1C's
    reason uses and the opposite of every reason byte in the 0x5C family. The
    ladder tops out at 100 so the two readings agree over the whole range, but
    packing it as signed is what the client actually asks for.
    """
    return struct.pack(">b", max(-128, min(127, level)))


def parse_battle_level(params: bytes) -> "int | None":
    """0x5C03's level -- which 対戦レベル the player picked off the screen.

    ⚠️ One byte, and SIGNED: the reader is the very same function 0x5D01 uses
    (0x8D84A0, ``+0x1c``). Read back the same way, so that a level this end
    could never have meant shows up as a negative number rather than as 200.
    """
    if len(params) < 1:
        return None
    return struct.unpack_from(">b", params, 0)[0]


def level_error_params(reason: int) -> bytes:
    return struct.pack(">B", reason & 0xFF)


#: (0x2c - 0x04) / 4 -- how many npcCharaId the client's own array has room for.
NPC_BATTLE_MAX = 10


def npc_battle_info_params(npc_chara_ids: "list[int]", pc_row: bytes) -> bytes:
    """0x5C05's body: the opponents as bare charaIds, then the player's row.

    Reader at 0x8EECE0, read for read: a u16 count through the stream vtable's
    +0x28, that many u32 through +0x24, and then the same 83-byte member record
    0x5C06 carries (u32 charaId, the 71-byte base block, vitality u16, energy
    u8, speed u8, clubId u16, charaBodyType u16 -- every field at the offset
    the deserializer writes it to).

    ⭐⭐⭐ THE OPPONENTS ARE FOUR BYTES EACH AND NOTHING ELSE, which is the
    finding this message carries. No names, no 体力, no deck: the client looks
    an opponent up in its own `training_npc.bin` by charaId, exactly the way
    round 217 found it looks a map object's appearance up. So this server has
    to get one number per opponent right and has nothing else it could get
    wrong -- and it explains why the client reads 体力/気力/素早さ out of that
    table at three fixed offsets (2.157) while the SERVER needs them only for
    its own arithmetic.

    ⚠️ THE ARRAY THE CLIENT READS INTO HOLDS TEN. The count lands at +0x2c and
    the entries start at +0x04, so ten u32 fit exactly, and the loop has no
    bounds check of its own. The ladder never fields more than three, so this
    is a ceiling nothing approaches -- but it is a real one.

    ⚠️ Unlike 0x5C06 there is no per-recipient ``team`` byte, because there is
    only ever one recipient: the other side is not listening.
    """
    if len(npc_chara_ids) > NPC_BATTLE_MAX:
        raise AssertionError(
            f"{len(npc_chara_ids)} opponents, the reader's array holds "
            f"{NPC_BATTLE_MAX}"
        )
    if len(pc_row) != MEMBER_SIZE:
        raise AssertionError(f"pcInfo is {len(pc_row)}B, reader wants {MEMBER_SIZE}")
    out = struct.pack(">H", len(npc_chara_ids))
    for chara_id in npc_chara_ids:
        out += struct.pack(">I", chara_id)
    return out + pc_row


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
    ⚠️⚠️ Round 96 corrects the pointer that used to sit here (「the next place
    it can be read is the 0x5C0A/0x5C0E コマンド exchange」): 0x5C0E HAS NO ROOM
    FOR IT. Its shape is charaId + the six deckItem bytes + targetId, and
    0x5C0F carries nothing at all — see action_begin_params/action_end_params.

    ✅✅ ROUND 97 ANSWERED IT, and the answer is 0x5C11 Effect alone: types
    8-13 draw ダメージ and the 体力 bar really goes down (66 px of Status panel
    to 49, then 20, then 13, and it turns orange on the way). 0x5C10 was the
    other candidate and it did NOT pan out — it only narrates the reaction.
    See the EFFECT template table above for the whole measured map.

    ✅✅ ROUND 98 SETTLED THE ROUND-84 PARAGRAPH, and it survives: ``/cb vit``
    put vitality=20/energy=30 into every 0x5C09 of a live fight against
    0x5C06's 100/80 — the wire was checked, both rows carried 0014/1e — and
    BOTH Status bars stayed 66 px, the full width. So 0x5C09's numbers really
    do not touch the bars, now with a second and deliberate sample.
    ⭐ And the mirror image of it: with the bars knocked down by 0x5C11 they
    STAYED down for three turns while every 0x5C09 carried the maximum. The
    client owns this state; this message is not how it is told about it.
    ⚠️ Which leaves 0x5C09's vitality/energy with no reader found anywhere yet.
    They are still sent because the original's message carries them.

    ⚠️ All of that is MEASUREMENT (which message moves a current value). The
    INVENTION next to it — how much a hit takes off, and whether this server
    should remember it between turns — is a separate account with no restored
    source, and round 97 deliberately left it untouched. the invention rule.
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
        #:
        #: ⚠️⚠️ NO GAMEPLAY WRITES THIS, and none ever has: 0x5C11 is what puts
        #: a status on a character and the client keeps it by itself (see the
        #: class docstring), so every 0x5C09 this server has sent since the
        #: message existed carried eight zeros. That makes the whole field
        #: UNMEASURED rather than known-inert — zero is its neutral value, and
        #: 「the client ignores these」 fits the evidence exactly as well as
        #: 「they drive the lamps」 does (an earlier lesson). ``/cb states`` is the one
        #: writer, and it is a probe.
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
        #: For an NPC opponent only: the ``(kind, six bytes)`` it is playing
        #: this turn, composed on its behalf because it has no save file and
        #: sends no 0x5C0A. None for anyone with a deck of their own.
        #: ⚠️ It is what 0x5C0E puts on the wire for that opponent, so the
        #: keyword id in it has to be one the client can look up.
        self.npc_card: "tuple[int, bytes] | None" = None
        #: Set when this fighter's connection went away mid-fight. They stay in
        #: the roster — every message this family sends carries the same rows it
        #: carried before, so nothing on the wire changes shape — but the fight
        #: stops WAITING for them (Battle.active).
        #:
        #: ⚠️⚠️ RESTORED and INVENTED, kept apart. Restored: 0x5C1B says
        #: somebody left, and 「０になる前に入力を完了できなかった場合、キャラ
        #: クターは行動しません」 (p07_03) already covers a fighter who does not
        #: act — a gone fighter is that case forever, which is why nothing here
        #: needs a new rule for what happens on their turn. INVENTED: that the
        #: fight carries on at all. Nothing read so far says whether the
        #: original played on, voided the fight, or awarded it.
        #:
        #: ⭐ What picked this over the alternatives is which endings it can
        #: reach: carrying on ends the fight through the ONE ending this server
        #: has restored (turn 8 → 0x5C1A → 結果画面 → the player presses
        #: ［終 了］). Closing the fight, which is what round 94 did, reaches no
        #: ending at all and strands the client on the battle screen; sending
        #: 0x5C1A right there would have to make up a winTeam at a moment
        #: nothing says a fight ends.
        self.gone = False

    def begin_turn(self) -> None:
        """Forget last turn's choice. Called for everyone by every 0x5C09."""
        self.command = None
        self.turn_done = False

    @property
    def retired(self) -> bool:
        """体力 gone. 「リタイヤ」 in the manual's word, and template row 18's.

        ⭐ RESTORED that this state exists and what it is called; restored too
        that the client reaches it by itself, because it retires its OWN
        character the moment that character's 体力 hits zero and never says so
        upstream (round 99). So this side has to keep the same count in
        parallel rather than wait to be told.
        """
        return self.vitality <= 0

    @property
    def defending(self) -> bool:
        """Did this fighter spend the turn defending rather than attacking?

        ⚠️ Read off the 0x5C0A that is still in hand: its ``isAttck`` byte is
        the 攻撃か防御か choice `p07_03` step 2) describes. A fighter with no
        command this turn is not defending -- they simply did not act, which
        the manual covers separately (「キャラクターは行動しません」).
        """
        return self.command is not None and not self.command[1]

    def hurt(self, amount: int) -> int:
        """Take ``amount`` off 体力 and return what was actually taken.

        ⚠️ Clamped at zero on this side even though the CLIENT's bar is not:
        round 97 measured that a 体力 bar driven below zero comes back FULL, so
        a server that let its own count go negative would be tracking a fight
        the screen is not showing. See the EFFECT_TEMPLATE notes.
        """
        taken = min(max(0, amount), self.vitality)
        self.vitality -= taken
        return taken

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
        #: ⭐⭐ Which door this fight came in through, because THE TWO DOORS
        #: HAVE DIFFERENT RULE SHEETS. 練習 is `p07_03`, whose 「それ以外」 is a
        #: plain loss for the player; 自主トレ is `p07_04`, whose 「それ以外」 is
        #: 「両方が負けになります」. Nothing else about the fight differs --
        #: 「自主トレの流れは、ＮＰＣとの練習と同じです」 -- so this flag is the
        #: whole of the difference and it is read only when the verdict is
        #: worked out. Set by the 0x5C05 path; 0x5C06's leaves it False.
        self.npc_fight = False
        #: In an 練習, which side the human is on. Meaningless when npc_fight
        #: is False, where both sides are people.
        self.player_team = 0
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
        #: The turn number whose 習熟度 has already been credited, or None.
        #:
        #: ⚠️⚠️ It exists because ``resolved`` could not be the guard. /cb replay
        #: CLEARS ``resolved`` on purpose — that is how it runs a finished turn's
        #: stream a second time — so a probe walks straight through it, and from
        #: round 198 a resolve RAISES 習熟度 in the save. One replay would then
        #: be a free point per card played, and the smoke suite alone replays a
        #: dozen times. A probe may re-send a turn; it may not re-earn one.
        #:
        #: ⭐ Keyed on ``turn`` rather than being a bool for the same reason:
        #: the next real turn carries a number of its own and credits itself,
        #: while every replay of this one carries this one's number.
        self.mastery_turn: "int | None" = None
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
        #: ⭐ The first member is a TUPLE of types, one 0x5C11 each, so a whole
        #: sweep fits in the single turn this probe gets, and a ``value`` of
        #: None means 「each type sends its own number」 — the label that lets a
        #: sweep be read off the log window.
        self.fx_probe: "tuple[tuple[int, ...], int | None, int, int] | None" = None
        #: ⚠️⚠️ A PROBE, not gameplay: ``(kind, six bytes)`` to put into the
        #: NEXT turn's 0x5C0E ActionBegin in place of the card actually played,
        #: or None. Set by ``/cb card``, cleared with fx_probe as soon as the
        #: turn it doctors goes out.
        #:
        #: It exists because ``kind`` had only ever carried 0 — キーワード. The
        #: other half of that field, ``club.DECK_ITEM_CLUB_SKILL``, was a guess
        #: this server could not test: 部活奥義 are earned in クラブ活動,
        #: nothing here grants one, and so no 0x5B03 has ever carried one for a
        #: deck to hold. Doctoring one ActionBegin is the only way to put a kind
        #: the client must resolve against ``clubskill.bin`` in front of it —
        #: and it settled that guess, see club.DECK_ITEM_CLUB_SKILL.
        #:
        #: ⭐ The probe answers itself, so no positive control has to be
        #: arranged: every clubskill row carries its OWN sentence
        #: (「野球部奥義【重いコンダラ】を使用した！」), so a payload the client
        #: resolves names the skill on screen, while one it cannot resolve
        #: leaves either nothing or the generic 攻撃 row.
        #:
        #: ⚠️ Like fx_probe it changes WHAT IS SENT during a normal resolve, so
        #: it is one-shot and _battle_resolve says in the log that the turn was
        #: doctored. ⚠️⚠️ The six bytes go out verbatim: they are the block the
        #: client bulk-copies rather than parses (action_begin_params), which is
        #: exactly why a wrong guess can only draw nothing, never a wrong field.
        self.card_probe: "tuple[int, bytes] | None" = None
        #: ⚠️⚠️ A PROBE, not gameplay: when set, the next finish sends its
        #: 0x5C1A and then STOPS — no 0x5C1C, and this Battle stays on the
        #: board. One-shot, cleared when it fires. Set by ``/cb hold``.
        #:
        #: It exists because three open questions about the ending all need the
        #: same instant, and that instant is otherwise unreachable (round 89,
        #: 2.44). The 結果画面 is drawn only when the client is idle: sending
        #: 0x5C1A while the コマンド window is up draws nothing, the client
        #: banks the message and cashes it at the next state boundary. The one
        #: idle moment is right after the last turn's animation — and the normal
        #: path closes the fight there, so a ``/cb result`` typed a second later
        #: has nothing to aim at. Holding the fight open across that instant is
        #: what makes winTeam re-sendable while the window is on screen.
        #:
        #: ⚠️ It withholds a message the normal path sends, so like fx_probe it
        #: is one-shot and says so in the log when it fires.
        self.hold_on_finish = False
        #: ⚠️⚠️ A PROBE: winTeam for the next finish to send INSTEAD of the
        #: computed one, or None. Set by ``/cb hold <n>``, cleared with it.
        #:
        #: It exists because winTeam turned out to be drawn BEFORE the 結果画面,
        #: in the 「終 了」 flourish (round 93) — and the window ignores every
        #: 0x5C1A after the first, so the value cannot be swapped while the
        #: result is up. Asking what another winTeam draws means having the
        #: FIRST result of a fight carry it, which is what this does.
        self.hold_win_team: "int | None" = None
        #: ⚠️⚠️ A PROBE, not gameplay: ``(vitality, energy)`` for EVERY row of
        #: EVERY 0x5C09 from now on, instead of each fighter's own numbers, or
        #: None for the shipping behaviour. Set by ``/cb vit``.
        #:
        #: It exists to tell two readings of round 97's frames apart, and they
        #: are the two paragraphs of Fighter's docstring. The bar was short at
        #: the end of a doctored turn and full again as the next turn's stream
        #: began, and this server sends the MAXIMUM in every 0x5C09 — so either
        #: 0x5C09 repaints the bar, or the client resets its own at turn start.
        #: One turn opening on a vitality BELOW the maximum separates them: a
        #: short bar at turn start means 0x5C09 drives it, a full one means the
        #: client does, and round 84's 「0x5C09's numbers do not touch the bars」
        #: stands or falls on that single frame.
        #:
        #: ⚠️ Deliberately NOT one-shot and deliberately NOT an environment
        #: knob. Not one-shot because the question is about the value a turn
        #: OPENS with, so it has to still be there when the next turn starts;
        #: not an environment knob because it must be switchable mid-fight —
        #: the control and the probe belong in one fight, the way round 97's
        #: undoctored turn had to sit next to its doctored one (an earlier lesson).
        #: Living on the Battle is what makes it restore itself: no fight
        #: outlives its board, so nothing has to remember to put it back.
        self.turn_start_hp: "tuple[int, int] | None" = None
        #: ⚠️ A PROBE, not gameplay: the ``timeoutTime`` offset every further
        #: 0x5C09 of THIS fight carries, in ms, or None for TURN_TIMEOUT_MS.
        #: Set by ``/cb timeout``.
        #:
        #: It exists because one value per server restart is one value per
        #: fight — five minutes of clicking to ask one number — while a fight
        #: has eight turns and each one carries a fresh deadline. That is what
        #: settled the cap in TURN_TIMEOUT_MS (3): four values, one fight.
        #: ⚠️ Lives on the Battle for the reason turn_start_hp does: no fight
        #: outlives its board, so nothing has to remember to put it back.
        self.turn_timeout_ms: "int | None" = None
        #: ⚠️⚠️ A PROBE, not gameplay: ``(chara_id, roster)`` for one extra
        #: 0x5C0D to send from INSIDE the handler round that receives that
        #: character's next 0x5C16, or None. Set by ``/cb ordernext``, cleared
        #: as it fires.
        #:
        #: It exists because 2.62 measured one edge of the demo window and not
        #: the other. 0x5C12 OPENS a window: a 0x5C0D that arrives while it is
        #: open is painted on the spot, one that arrives while it is shut is
        #: only stored. The far edge is one round trip wide, which is exactly
        #: the interval no console line can aim at: /cb is drained on a
        #: timesync, up to 30 seconds late. Arming the moment instead of typing
        #: into it is the only way to put a message there.
        #:
        #: ⭐ What it measured (2.63, two fights, three firings): the circle
        #: does NOT move. Nor does it move for a lone 0x5C12 sent seconds later,
        #: nor for a 0x5C0D+0x5C12 pair in one batch — the shape that repaints
        #: on the spot earlier in the turn. So once a client has reported
        #: 0x5C16 for a turn, this family cannot change that widget at all;
        #: only the next turn's own stream can.
        #: ⚠️ It did NOT decide 「shuts on 0x5C16」 vs 「shuts when the animation
        #: ends, 0x5C16 being its echo」, and no probe from this side can:
        #: 0x5C16 IS the animation-end report, so every server-sent message
        #: lands after both. That split needs the binary, not the wire.
        #:
        #: ⚠️ It fires ONLY on a 0x5C16 that does not also finish the turn. A
        #: 0x5C16 from the last fighter carries the next 0x5C09 (or the result)
        #: out in the same batch, and a turn start is itself a candidate for
        #: repainting the widget — so that batch cannot answer this question
        #: either way (an earlier lesson). Firing is therefore something the fight has
        #: to be arranged for: somebody else must still owe a 0x5C16 when the
        #: armed client sends its own.
        self.order_probe: "tuple[int, list[int]] | None" = None
        #: ⚠️⚠️ A PROBE, not gameplay: ``(roster, demo, demo_first)`` for one
        #: extra 0x5C0D to append to the NEXT turn's action stream, behind the
        #: 0x5C12 that closes it, or None. ``demo`` adds a second 0x5C12 behind
        #: that again; ``demo_first`` puts one in FRONT of the appended 0x5C0D
        #: instead. Set by ``/cb ordertail``, cleared as it fires.
        #:
        #: ⭐⭐ ``demo_first`` is the one knob that separates the two readings
        #: 2.64 left facing each other. Appended behind a turn that is playing,
        #: the second 0x5C0D numbers ITS names 3, 4 — it continues the count the
        #: turn's own roster started. Sent as 0x5C12 then 0x5C0D onto a turn
        #: already finished (2.62 step 5), the same widget renumbers from 1.
        #: Two things differ between those, and neither has ever been moved on
        #: its own: whether the turn is still playing, and whether a 0x5C12 sits
        #: immediately in front of the 0x5C0D. This moves the second one alone
        #: — same turn, same append, same roster, one extra 0x5C12 ahead of it.
        #: 1, 2 means the demo in front is what resets the count; 3, 4 means it
        #: is the turn being in flight, and the demo has nothing to do with it.
        #:
        #: It is order_probe's other half, and the pair exists because 2.63 has
        #: only a negative: after a client reports 0x5C16 this family cannot
        #: repaint the circle under a fighter's feet. A negative alone does not
        #: say whether the MOMENT is what refuses it or whether an appended
        #: 0x5C0D never repaints anything, and no reading separates those two
        #: without a positive sample from some other moment. This aims at the
        #: earliest moment there is: the instant the turn's own stream ends,
        #: while the window 0x5C12 opens (2.62) has just been opened by the
        #: stream itself and the client has not yet played a frame.
        #:
        #: ⚠️ It rides out in the SAME batch as the turn, one packet behind the
        #: closing 0x5C12, so what it measures is a position in a stream and
        #: not a wall-clock instant — order_probe with ``by=`` is what reaches
        #: a moment of its own, one round trip later, from inside the handler
        #: round of ANOTHER fighter's 0x5C16 while this client animates.
        #:
        #: ⚠️ Like fx_probe it alters a real resolve, so it is one-shot and
        #: says so in the log when it fires. The roster is a permutation of
        #: this fight's own fighters; no byte of any message is invented.
        self.tail_probe: "tuple[list[int], bool, bool] | None" = None
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

    def active(self) -> "list[Fighter]":
        """Everyone still connected — who the fight is allowed to wait for.

        ⚠️ Not the same list as ``fighters``, and the difference is deliberate:
        the roster that goes out on the wire never shrinks (see Fighter.gone),
        so the client keeps drawing the same battle it was drawing. Only the
        three 「has everybody…」 questions below use this one.
        """
        return [f for f in self.fighters if not f.gone]

    def abandoned(self) -> bool:
        """Has everybody gone? Then there is nobody left to send anything to."""
        return not self.active()

    def side(self, team: int) -> "list[Fighter]":
        return [f for f in self.fighters if f.team == team]

    def all_ready(self) -> bool:
        """Has every fighter reported its battle scene up?

        ⚠️ Every fighter, including the leader — this is not the room's
        ready flag, where the leader is excused because pressing 「開 始」 is
        their version of it. 0x5C07 is a statement about a scene being drawn
        and the leader's scene has to be drawn too.

        ⚠️ Every fighter who is still there. A gone one can never report, and
        waiting for a report that cannot come is the hang this is written
        against; see Fighter.gone.
        """
        active = self.active()
        return bool(active) and all(f.ready for f in active)

    def begin_turn(self) -> int:
        """Advance to the next turn and clear everybody's choice. Returns it."""
        self.turn += 1
        self.resolved = False
        for fighter in self.fighters:
            fighter.begin_turn()
        return self.turn

    def finished(self) -> bool:
        """「８ターンが終了するまで、もしくはどちらかの体力が全員０になるまで」.

        ⭐⭐ BOTH HALVES NOW, which is new. For every round up to this one the
        second half was untestable — nothing took 体力 off anybody — and this
        function asked only about the turn count. Damage exists now, so a fight
        can end the way the manual's own sentence says it usually does.
        """
        return self.turn >= TURN_LIMIT or self.wiped_out() is not None

    def wiped_out(self) -> "int | None":
        """The team whose fighters are ALL retired, or None. 「どちらかの体力が
        全員０」.

        ⚠️ Over the whole roster rather than active(): a fighter who dropped
        their connection is not knocked out, and treating them as one would
        hand the other side a win nobody landed.
        """
        for team in sorted({f.team for f in self.fighters}):
            side = self.side(team)
            if side and all(f.retired for f in side):
                return team
        return None

    def npc_win_team(self, player_team: int) -> int:
        """The 練習 verdict, `p07_03`'s two branches and its 「それ以外」.

        ⭐⭐⭐ RESTORED, word for word, and it is a DIFFERENT RULE SHEET from
        自主トレ's — do not merge the two:

            1. ＮＰＣが全員リタイヤした場合
            2. ＮＰＣが残り一人で、その残り体力がプレイヤーの残り体力より
               少なく、かつＮＰＣ側に十分なダメージを与えている場合
            それ以外の場合は、プレイヤーの負けとなります

        So an 練習 that ends with nobody hurt is a plain LOSS for the player.
        ⚠️ That is why WIN_TEAM_NEITHER must not be carried over here: it is
        p07_04's third branch and p07_03 has no third branch.

        ⚠️ INVENTED, one clause: 「十分なダメージ」 is not a number anywhere.
        DAMAGE_ENOUGH_SHARE below is that number, and it is the only made-up
        thing in this verdict.
        """
        foes = [f for f in self.fighters if f.team != player_team]
        us = [f for f in self.fighters if f.team == player_team]
        if foes and all(f.retired for f in foes):
            return player_team
        standing = [f for f in foes if not f.retired]
        if len(standing) == 1 and us:
            foe = standing[0]
            ours = sum(f.vitality for f in us)
            dealt = sum(f.max_vitality - f.vitality for f in foes)
            enough = sum(f.max_vitality for f in foes) * DAMAGE_ENOUGH_SHARE
            if foe.vitality < ours and dealt >= enough:
                return player_team
        return 1 - player_team if player_team in (0, 1) else WIN_TEAM_NEITHER

    def pvp_win_team(self) -> int:
        """The 自主トレ verdict, `p07_04`.

        ⭐ Its two winning branches are the same shape as p07_03's, but its
        「それ以外」 is 「両方が負けになります」 — which is what WIN_TEAM_NEITHER
        has been sending on its own for every round since round 100, back when
        a damage-less fight made that the only branch reachable.

        ⚠️ 「残り体力」 is summed over a side here, because 自主トレ takes several
        people per side while the sentence the branch comes from was written
        about one. That is a reading, and it is the only one available: the
        manual gives no rule for comparing two groups.

        ⚠️ Branch 1 is checked for BOTH sides before branch 2 for either, so a
        knockout always outranks a points win. Within branch 2 both sides can
        qualify at once (each down to one hurt fighter); the earlier team wins,
        which is arbitrary, and nothing read so far says what the original did.
        """
        teams = sorted({f.team for f in self.fighters})
        if len(teams) != 2:
            return WIN_TEAM_NEITHER

        def opponents(team: int) -> "list[Fighter]":
            return self.side(teams[1 - teams.index(team)])

        for team in teams:
            foes = opponents(team)
            if foes and all(f.retired for f in foes):
                return team
        for team in teams:
            foes = opponents(team)
            standing = [f for f in foes if not f.retired]
            ours = sum(f.vitality for f in self.side(team))
            dealt = sum(f.max_vitality - f.vitality for f in foes)
            enough = sum(f.max_vitality for f in foes) * DAMAGE_ENOUGH_SHARE
            if len(standing) == 1 and standing[0].vitality < ours and dealt >= enough:
                return team
        return WIN_TEAM_NEITHER

    def all_chosen(self) -> bool:
        """Has every fighter sent their 0x5C0A this turn?

        ⚠️ 「全員のコマンド入力終了後、全員の行動が実行されます」 (p07_03) is
        this condition exactly — and the manual's preceding line says the OTHER
        way a turn can reach that point is the clock running out on somebody.
        Both callers are in MpsServer; neither is in here, because a Battle has
        no way to tell the time on a client's behalf.

        ⚠️ Over the active roster: a gone fighter is exactly the 「did not
        finish in time」 case the same paragraph describes, permanently.
        """
        active = self.active()
        return bool(active) and all(f.command is not None for f in active)

    def all_turn_done(self) -> bool:
        """Has every fighter reported 0x5C16 「my turn animation is over」?

        ⭐ The same shape as all_ready: the next 0x5C09 waits for the LAST one,
        because each client plays the action stream at its own pace and a turn
        started on the first report would begin for somebody still watching the
        previous one.

        ⚠️⚠️ This is the one the deadline does NOT cover: a turn whose choices
        timed out still resolves, but a turn nobody reports finished simply
        stops. So this is where a gone fighter used to freeze the fight for
        good, and why active() and not fighters.
        """
        active = self.active()
        return bool(active) and all(f.turn_done for f in active)

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

    def timeout_ms(self) -> int:
        """How far ahead of the reader's own clock this fight's 0x5C09 points."""
        if self.turn_timeout_ms is None:
            return TURN_TIMEOUT_MS
        return self.turn_timeout_ms

    def deadline_s(self) -> float:
        """How long this server waits for a turn of this fight, in seconds.

        ⭐ The probe moves BOTH sides together: the wire's timeoutTime and the
        server's own patience naming different deadlines is a bug, not a
        feature (see TURN_DEADLINE_S). An operator who deliberately split them
        with TMO_TURN_DEADLINE_S keeps that split — it is pinned, and the probe
        does not silently undo it.
        """
        if self.turn_timeout_ms is None or DEADLINE_PINNED:
            return TURN_DEADLINE_S
        return self.turn_timeout_ms / 1000

    def turn_rows(self) -> "list[bytes]":
        # ⚠️ The probe substitutes the two numbers and NOTHING else: same rows,
        # same order, same status counters, so the only thing that can differ
        # on screen is what those two numbers draw. See turn_start_hp.
        if self.turn_start_hp is not None:
            vitality, energy = self.turn_start_hp
            return [
                turn_start_row(f.chara_id, vitality, energy, f.states)
                for f in self.fighters
            ]
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

        ⚠️ The whole battle goes, not just the one fighter. Used where the
        fight is genuinely over — the result has been sent, or nobody is left
        to send anything to. A connection going away is NOT one of those; that
        is what leave() is for.
        """
        battle = self.battle_of(chara_id)
        if battle is not None:
            self.battles.remove(battle)
        return battle

    def leave(self, chara_id: int) -> "Battle | None":
        """One fighter's connection went away. Return the fight, still open.

        ⭐ The fight stays on the board with the leaver marked gone, because a
        fight that is taken off the board can no longer reach any ending — and
        the ending is the whole point (Fighter.gone). ``None`` comes back when
        this character was not fighting, exactly as it does from close().

        ⚠️ The battle IS removed when the last one goes: with nobody active
        there is no connection to carry it forward and no screen waiting on it.
        """
        battle = self.battle_of(chara_id)
        if battle is None:
            return None
        fighter = battle.find(chara_id)
        if fighter is not None:
            fighter.gone = True
        if battle.abandoned():
            self.battles.remove(battle)
        return battle

    def summary(self) -> str:
        return f"{len(self.battles)} battle(s)"
