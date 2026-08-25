"""恋愛候補生の状態: 登場したか、どれだけ親密か、何話まで進んだか。

The official manual describes the loop in four sentences (`manual/p09_01.html`
§1–3), and they divide cleanly into what the game's own data can tell us and
what it cannot:

    1. 「天宮」と「桜井」は、初登校の学校説明で出会います。
       （天宮は男子キャラクターを作成した場合、桜井は女子キャラクターを作成した場合に登場）
    2. その他のキャラクターは、最初からは登場していません。
       特定のドラマイベントの、ある役柄をプレイすると、その中で登場するようになっています。
    3. 恋愛メインイベントを見るためには、日常会話を繰り返して、
       恋愛候補生と親密になっていく必要があります。
       ※一日に何度も日常会話を繰り返しても、あまり親密さは上がりません。
    4. 校内マップで恋愛候補生が立っている位置は、
       メインイベントを一つ見るごとに変わるようになっています。

All four are **recoverable**, and as of round 171 all four have been recovered.
(1), (2) and (4) were always easy: the debut event is a field in the game's own
`capture_npc` record and the placement rule is stated outright. (3) — 親密さ —
was the hard one, and for a long time this file carried three invented numbers
for it under a banner saying so.

⭐ They are gone. The numbers were never missing; they were in a place nothing
searched. The manual gives no figures, `capture_npc` has no threshold field and
親密さ never crosses the wire — all true, all checked — but the *scripts* have
it twice over, on both sides of the old client/server line:

  * the original server's GS3 scripts gate each メインイベント on
    ``PC[0x3920+i] >= 72 * progress`` (the opcode table gates);
  * the client's own SSC 日常会話 scripts **add to that very same slot**, and
    implement the manual's 「一日に何度も…あまり上がりません」 themselves
    (the script data reader intimacy).

Same slot on both sides, so no unit conversion is needed or wanted. The
numbers are under RESTORED below; how they were read out is written up on the
reverse-engineering side, under 恋愛 in the protocol notes.

⭐ The lesson kept from round 39 was «check the sources before reverse
engineering». Its other half was «when the sources stop, say so in the file
rather than letting a plausible constant pass for a recovered one» — and this
file did say so, in the three places it had to. What round 171 adds is the
third half: **a source that has stopped is not the same as a source that has
been looked at.** The banner should name the places already searched, so the
next reader can see which one is still missing. It did, and the missing one was
the scripts.
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple

SEX_MALE, SEX_FEMALE = 0, 1  # chara_sex.bin: 0 男 / 1 女 / 2 不詳


class Candidate(NamedTuple):
    """One 恋愛候補生, as five numbers rather than as a row of game content.

    ``base``/``spots`` are her block in `cibi_control_script` (4:0–4:178): N
    scattered spots and then 26 classrooms, contiguous. ``sex`` is her own, read
    off `capture_npc` +24. ``debut`` is her 初期登場イベント from `capture_npc`
    +394 — a `capture_npc_event` key for the two who are there from the first
    day, ``None`` for the three a drama event has to introduce. ``events`` is how
    many メインイベント she has (その１…その１２, minus the ones she does not
    start with; the two おまけ are not counted).

    All of it is checked against the game's tables by the candidate cross-check, which
    is the reason it can live here as constants instead of as a file to load.
    """

    base: int
    spots: int
    events: int
    sex: int
    debut: tuple[int, int] | None


# 春日 has nine spots where everyone else has ten, and eleven main events where
# 天宮 and 桜井 have twelve — she and 弥生 and 犬飼 start at その２ because their
# その１ is the drama event that introduces them. Nothing here is a rounding of
# anything; it is what the tables say.
CANDIDATES = {
    "天宮": Candidate(base=0, spots=10, events=12, sex=SEX_FEMALE, debut=(0, 0)),
    "春日": Candidate(base=36, spots=9, events=11, sex=SEX_FEMALE, debut=None),
    "弥生": Candidate(base=71, spots=10, events=11, sex=SEX_FEMALE, debut=None),
    "桜井": Candidate(base=107, spots=10, events=12, sex=SEX_MALE, debut=(3, 0)),
    "犬飼": Candidate(base=143, spots=10, events=11, sex=SEX_MALE, debut=None),
}

CIBI_EVENT_CATEGORY = 4  # every cibi_control_script key is 4:something
CIBI_SCRIPT_COUNT = 223  # 4:0–4:178 these five, 4:179–4:222 teachers and staff

# `capture_npc_event` is keyed by category, and the categories are two parallel
# runs over the same five people in the same order as CANDIDATES: 0–4 are their
# メインイベント (その１…その１２ plus two おまけ) and 16–20 their 日常会話
# (c01x…c10x). Each record also carries the owning capture_npc index at +22,
# which is what lets the candidate cross-check check these two numbers rather than take
# them on faith.
MAIN_EVENT_CATEGORY_BASE = 0
TALK_CATEGORY_BASE = 16


def whose_event(category: int) -> tuple[str, str] | None:
    """``(name, "main"|"talk")`` for a capture_npc_event category, or None.

    None covers every category that is not one of these ten — the general and
    extra NPCs have their own tables, and a conversation with one of them is not
    a step in anybody's 恋愛.
    """
    names = list(CANDIDATES)
    for base, kind in ((MAIN_EVENT_CATEGORY_BASE, "main"), (TALK_CATEGORY_BASE, "talk")):
        if base <= category < base + len(names):
            return names[category - base], kind
    return None

# ── RESTORED (round 171) ────────────────────────────────────────────────────
# 親密さ, end to end. Three slots carry it, and both sides of the old
# client/server line read the same one, so everything below is in one unit:
#
#   PC[0x3920+i]     親密さ for candidate i. The original server's GS3 scripts
#                    gate on it; the client's 日常会話 scripts add to it.
#   PCEV[0x6040+i]   the day her last 日常会話 landed, packed as
#                    (year-2000)*512 + month*32 + day
#   PCEV[0x6060+i]   the largest single grant already made to her *that day*
#
# ⚠️ It is a running total: nothing in either script set ever subtracts from it
# or resets it, and the gates are absolute (`>=`), not per-step.
GAIN_BEST = 15    # the best answer in a 日常会話 that offers a choice
GAIN_PLAIN = 12   # a 日常会話 with no choice at all, and the middle answer
GAIN_WORST = 10   # the worst answer
#
# Those three are every value that occurs: 304 client 日常会話 scripts, one
# parameter register each, 463 immediates between them, all 10 / 12 / 15
# (the script data reader intimacy). 209 of the scripts have no choice and grant a
# flat 12; the rest offer two or three answers.
#
# The daily rule is NOT «less the second time». Each script ends with the same
# routine, and what it does is keep the best single grant of the day:
#
#     if PCEV[day] != today:  PC[intimacy] += X;  PCEV[day] = today
#                             PCEV[best] = X
#     elif PCEV[best] < X:    PC[intimacy] += X - PCEV[best]
#                             PCEV[best] = X
#     else:                   nothing at all
#
# So a second conversation the same day is worth the difference and no more,
# and a third worse one is worth nothing. 「一日に何度も日常会話を繰り返しても、
# あまり親密さは上がりません」, implemented rather than approximated.
INTIMACY_STEP = 72  # the ladder the original server's gates climb


def intimacy_needed(progress: int) -> int:
    """親密さ required before the メインイベント after `progress` will play.

    ``c000[00d9] == progress + 2 AND PC[0x3920+i] >= 72 * (c000[00d9] - 2)``,
    i.e. 0, 72, 144, … — a straight line, not a constant.

    ⭐ The ``+2`` is not assumed. `<name>_s101` — the script that answers «where
    does she stand» — is a table of `(c000[00d9], map id)` pairs, and lining
    those up against the placement keys in `cibi_control_script` matches on all
    48 rows across the five candidates, with `c000[00d9] - 2` as the index into
    her spots. Two tables that share no bytes agree on the offset.
    """
    return INTIMACY_STEP * max(0, progress)


# メインイベント scripts grant 親密さ too, 0 / 12 / 24 by answer — but which
# answer the player picked is not something this end sees yet, so see_main_event
# grants nothing. ⚠️ That is a gap, not a decision: it is the one number in this
# file that is known and still unused.
#
# Also still not modelled: 「プレイヤーの能力が低い間は見られないメインイベント
# もあります」. The gate is real and readable — `amm_s102` bails out unless five
# PC[0x310x] slots clear 3/4/5, and it guards exactly one event, her first —
# but which five stats those slots are has not been pinned down (the shape
# matches the six of chara_ability_type minus one, which is a shape, not a
# judgement). Until it is, the gate stays absent rather than guessed.
# ────────────────────────────────────────────────────────────────────────────


def initial_cast(player_sex: int) -> set[str]:
    """Who is already on campus the day a character of this sex starts.

    Derived, not listed: a candidate is there from the start iff she has a debut
    event at all, and she is *this* player's iff her sex is the other one. That
    reproduces the manual's parenthesis (天宮 for a male character, 桜井 for a
    female one) without stating it a second time in a place that could drift.
    """
    return {
        name
        for name, who in CANDIDATES.items()
        if who.debut is not None and who.sex != player_sex
    }


def cibi_key(name: str, progress: int) -> int:
    """Which spot she stands on, given how many main events have been seen.

    「校内マップで恋愛候補生が立っている位置は、メインイベントを一つ見るごとに
    変わるようになっています」. Spot 0 is where she stands once she has appeared;
    each main event moves her one along; past the end she stays put. Her last two
    main events (その１１ / その１２, the two with おまけ) are the confession and
    after, which is why twelve events fit ten spots.

    One body per character, campus-wide: pushing a second key for the same person
    moves her, it does not add anyone. So this returns one key, not a set.
    """
    who = CANDIDATES[name]
    return who.base + max(0, min(progress, who.spots - 1))


def classroom_key(name: str, class_index: int) -> int:
    """Her seat, in whichever of the 26 classrooms is the one that matters.

    The 26 keys are not 26 places: the coordinate is identical across all of
    them, and the five sit side by side (x=3..7, y=10). One room, chosen from
    outside; not a spot she wanders to, which is why it is not in cibi_key().
    """
    who = CANDIDATES[name]
    return who.base + who.spots + class_index % 26


class Romance:
    """Per-character 恋愛 state, the whole of it: five names, three numbers each.

    Lives in the character's record in runtime/characters.json — same tier as
    ``pos`` and ``map``, which is to say derived state that belongs to a save and
    reaches neither repository. Mutating methods return True when something
    changed, so the caller knows whether to write the file.
    """

    def __init__(self, player_sex: int, saved: dict | None = None) -> None:
        self.player_sex = player_sex
        started = initial_cast(player_sex)
        self.state: dict[str, dict] = {}
        for name in CANDIDATES:
            row = (saved or {}).get(name, {})
            self.state[name] = {
                "debut": bool(row.get("debut", name in started)),
                "intimacy": int(row.get("intimacy", 0)),
                "progress": int(row.get("progress", 0)),
                "lastTalk": str(row.get("lastTalk", "")),
                # The best single grant already made today — PCEV[0x6060+i].
                # Absent from saves written before round 171; 0 is the value a
                # fresh day would have anyway, so no migration is needed.
                "todayBest": int(row.get("todayBest", 0)),
            }

    # ── reading ────────────────────────────────────────────────────────────
    def on_stage(self) -> list[str]:
        """The candidates who are actually standing on a map, in key order.

        Before her debut a candidate is nowhere: 「その他のキャラクターは、最初
        からは登場していません」, and p09_02 says the map characters of everyone
        the player never met are simply not drawn. So this — not the whole cast —
        is what a spawn push is allowed to contain.
        """
        return [name for name in CANDIDATES if self.state[name]["debut"]]

    def keys(self) -> list[tuple[str, int]]:
        """``(name, cibi key)`` for everyone on stage, at her own progress."""
        return [(name, cibi_key(name, self.state[name]["progress"])) for name in self.on_stage()]

    def line(self, name: str) -> str:
        row = self.state[name]
        if not row["debut"]:
            return f"{name}=未登場"
        return (
            f"{name}=進行{row['progress']}/{CANDIDATES[name].events}"
            f" 親密{row['intimacy']}/{intimacy_needed(row['progress'])}"
            f" 位置4:{cibi_key(name, row['progress'])}"
        )

    # ── writing ────────────────────────────────────────────────────────────
    def debut(self, name: str) -> bool:
        """Mark her as having appeared. Manual for now, and deliberately so.

        The real trigger is a drama event with a role this player can take, and
        which drama event introduces whom is not in any table we have — the 22
        drama events name their scripts and their roles, not their guest stars.
        Until that mapping is found this is the honest shape: a switch somebody
        flips, not a rule pretending to know.
        """
        if self.state[name]["debut"]:
            return False
        self.state[name]["debut"] = True
        return True

    def talk(self, name: str, today: str | None = None,
             gain: int = GAIN_PLAIN) -> tuple[bool, bool]:
        """One 日常会話 worth of 親密さ. Returns ``(changed, advanced)``.

        ``gain`` is what the script that just played is worth — GAIN_PLAIN for
        the 209 scripts with no choice, GAIN_BEST / GAIN_PLAIN / GAIN_WORST for
        the answer the player picked in the rest. This end does not yet read the
        branch the client reports, so callers pass nothing and get the flat 12
        that two thirds of the scripts grant anyway; the parameter is here so
        that wiring it later is a call-site change and not a rewrite.

        The day is the server's own calendar day. The game surely had its own
        clock — 校内マップ has seasons — but this end does not model one yet, and
        borrowing the real date keeps 「毎日少しずつ」 meaning something instead
        of nothing. Swap it when a game clock exists.

        ⚠️ The daily rule is the scripts' own: keep the best single grant of the
        day, so a repeat is worth the difference and a worse repeat is worth
        nothing. Returning ``(False, False)`` for that case is not an error —
        it is the manual's sentence happening.
        """
        row = self.state[name]
        if not row["debut"]:
            return False, False
        today = today or date.today().isoformat()
        if row["lastTalk"] != today:
            row["lastTalk"] = today
            row["todayBest"] = 0
        credit = max(0, gain - row["todayBest"])
        if credit == 0:
            return False, False
        row["intimacy"] += credit
        row["todayBest"] = gain
        if row["intimacy"] < intimacy_needed(row["progress"]):
            return True, False
        # No subtraction: 親密さ is a running total and the next rung is higher,
        # not the same one again. What the old model called "carrying the
        # remainder over" was an artefact of the invented constant.
        return True, self.see_main_event(name)

    def see_main_event(self, name: str) -> bool:
        """One メインイベント watched: she moves to the next spot.

        ⚠️ Open question, round 171, deliberately not acted on: her *debut*
        event is itself a メインイベント (その１ = category 0, id 0 — which is
        exactly what `capture_npc` +394 points at), so playing it lands here and
        counts as a step. The placement tables say the spot index counts main
        events **after** the debut, which makes that one step too many. It does
        not bite today, because initial_cast() marks the two starters as debuted
        without anyone playing その１ — so the only way in is /sc by hand. Fixing
        it means deciding what `progress` counts, and that is a change to what
        saves mean; it wants its own round, not a line squeezed in here.
        """
        row = self.state[name]
        if not row["debut"] or row["progress"] >= CANDIDATES[name].events:
            return False
        row["progress"] += 1
        return True

    def set_progress(self, name: str, progress: int) -> bool:
        """Jump straight to a spot. Debut first — a story cannot be part-way
        along for somebody the player has not met, and letting it be would put a
        number in the save that /npca can never act on."""
        row = self.state[name]
        if not row["debut"]:
            return False
        want = max(0, min(progress, CANDIDATES[name].events))
        if row["progress"] == want:
            return False
        row["progress"] = want
        return True

    def set_intimacy(self, name: str, value: int) -> bool:
        """Put 親密さ at a number. The counterpart of set_progress, and needed
        for the same reason plus one more: the restored daily rule caps a day at
        one conversation's worth, so climbing a 72-step ladder by talking would
        take a rung per real day. Debut first, as with set_progress."""
        row = self.state[name]
        if not row["debut"] or row["intimacy"] == max(0, value):
            return False
        row["intimacy"] = max(0, value)
        return True

    def to_json(self) -> dict:
        return self.state
