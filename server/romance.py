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

(1), (2) and (4) are **recoverable**: the debut event is a field in the game's
own `capture_npc` record and the placement rule is stated outright, so `debut`
and `progress` below are reconstruction. (3) is **not**: the manual gives the
mechanism but no numbers, and there are none to find — see INVENTED below.

⭐ The distinction matters more than it looks. Round 39 spent itself on a
question the manual had already answered, and the lesson taken was to check the
sources before reverse-engineering. The other half of that lesson is this one:
when the sources genuinely stop, say so in the file rather than letting a
plausible constant pass for a recovered one.
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

    All of it is checked against the game's tables by tools/cibiplan.py, which
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
# which is what lets tools/cibiplan.py check these two numbers rather than take
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

# ── INVENTED ────────────────────────────────────────────────────────────────
# Everything above is reconstruction. These three are not: the manual says
# 親密さ rises with 日常会話 and rises less when the same day's are repeated, and
# it never says by how much. The numbers were checked for in all three places
# they could have been and are in none of them:
#
#   capture_npc_event  394 records, 24-byte tails fully accounted for
#                      (filename, scriptId LE at +18, constant 1 at +20,
#                      owning capture_npc index at +22) — no threshold field
#   capture_npc        12 u16 pairs fully accounted for (debut event, the two
#                      confession events and their おまけ, four gallery
#                      entries, a text id that splits by sex) — no threshold
#   the wire           MsgSvResultCaptureNpcList (0x4401) is a counted list of
#                      `captureNpcId[%d]={%d,}` and nothing else: four bytes
#                      per candidate, so 親密さ never crossed the network and
#                      cannot be in the client either
#
# So this curve is a guess that satisfies the manual's shape and no more. Change
# it freely; nothing is being contradicted. What must NOT happen is someone
# later reading these as recovered values.
TALK_FIRST_OF_DAY = 3   # 「毎日少しずつでも話しかけることが大切」
TALK_AGAIN_TODAY = 1    # 「一日に何度も繰り返しても、あまり上がりません」
INTIMACY_PER_EVENT = 10  # 親密さ needed before the next メインイベント opens
#
# Not modelled at all: 「プレイヤーの能力が低い間は見られないメインイベントも
# あります」. The six abilities exist (chara_ability_type: 文系 理系 芸術 雑学
# 運動 スタミナ) but this server has no ability values to gate on yet, so the
# gate is absent rather than guessed. When abilities land, it goes here.
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
            f" 親密{row['intimacy']}/{INTIMACY_PER_EVENT}"
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

    def talk(self, name: str, today: str | None = None) -> tuple[bool, bool]:
        """One 日常会話 worth of 親密さ. Returns ``(changed, advanced)``.

        The day is the server's own calendar day. The game surely had its own
        clock — 校内マップ has seasons — but this end does not model one yet, and
        borrowing the real date keeps 「毎日少しずつ」 meaning something instead
        of nothing. Swap it when a game clock exists.
        """
        row = self.state[name]
        if not row["debut"]:
            return False, False
        today = today or date.today().isoformat()
        gain = TALK_FIRST_OF_DAY if row["lastTalk"] != today else TALK_AGAIN_TODAY
        row["lastTalk"] = today
        row["intimacy"] += gain
        if row["intimacy"] < INTIMACY_PER_EVENT:
            return True, False
        # Carrying the remainder over rather than zeroing it: a conversation that
        # overshoots should not be worth less than one that lands exactly.
        row["intimacy"] -= INTIMACY_PER_EVENT
        return True, self.see_main_event(name)

    def see_main_event(self, name: str) -> bool:
        """One メインイベント watched: she moves to the next spot."""
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

    def to_json(self) -> dict:
        return self.state
