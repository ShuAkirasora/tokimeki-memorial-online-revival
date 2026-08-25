"""能力パラメータ: the キャラメニュー ability sheet.

One exchange:

    0x430F MsgClQueryCharaMenuAbility -> 0x4310 MsgSvResultCharaMenuAbility
                                      -> 0x4311 MsgSvErrorCharaMenuAbility

The client sends this on its own the moment 「生徒情報」's ability tab is
opened, and it had been going unanswered. That makes it the cheapest screen in
the game to put a number on: no lesson has to run, nothing has to be timed, and
the client asks first — so unlike 0x6102's ability fields, which only appear
after ten questions, this one can be read off the screen on demand.

What the answer carries, from `Input_MsgSvResultCharaMenuAbility`'s
deserializer at 0x008CEB80 with the names out of the client's own dump string:

    u8      testLevel                              +0x04
    u8 × 16 clubParamInfo.level[tmn::NUM_OF_CLUB]  +0x05
    u8 × 16 clubParamInfo.gauge[tmn::NUM_OF_CLUB]  +0x15
    u16 × 6 abilityInfo.abilityParam
              [tmn::NUM_OF_CHARA_ABILITY]          +0x26
    u16     virtue                                 +0x32
    u16     stress                                 +0x34
    i8      condition                              +0x36
    u32     elapsedDays                            +0x38

Both array lengths are confirmed away from the wire: `chara_ability_type.bin`
has exactly six records (文系 理系 芸術 雑学 運動 スタミナ) and `club.bin`
exactly sixteen, so the 6 and the 16 are decodes rather than counts fitted to a
buffer — the mistake an earlier lesson is about. The same u16×6 / u8[16] / u8[16] trio
is the head of the 238-byte character list entry in 2.10, which is a second
sighting of the same three arrays in the same order.

What the screen does with each field, all of it read back off screenshots
measured pixel by pixel rather than inferred:

    abilityParam   six rows in `chara_ability_type.bin` key order, one to one.
                   The u16 is an 8.8 fixed-point number — the high byte is the
                   level, the low byte is the progress inside that level, and
                   the screen draws the two halves separately:

                     「レベルＮ」  N    = (値 >> 8) + 1
                     progress bar  fill = (値 & 0xFF) / 256   of the track

                   Thirty points agree, and 値 = 0 needs no special case: the
                   shift draws レベル1 on its own. Two earlier readings —
                   ceil(値/250), then ceil(値/256) — each needed a max(1, …)
                   patch for exactly that value, which is the tell that both
                   were the wrong shape. Neither could be separated from the
                   shift by the samples then in hand: ceil and floor+1 differ
                   only where 値 is an exact multiple of 256, and thirty-odd
                   measurements had never once landed on one. 256, 512 and
                   2560 do, and they draw レベル 2, 3 and 11 with an empty bar
                   where ceil predicts 1, 2 and 10 with a full one.
                   ⚠️ 値 ≥ 32768 — the u16 sign bit, and this field is u16 on
                   the wire — switches to a different rule altogether: 32768,
                   40000, 50000, 65535 draw 12, 15, 19, 25, every one of them
                   exactly round(値 × 25 / 65536). A signed read on the far
                   side is the obvious suspect, but the switch has been
                   bracketed, not found. Keep values below 32768 and the
                   screen means what it says.
    virtue         drawn as 「人　徳」 on the same sheet, same レベル rule,
                   which is why 0 reads as レベル1 there too.
    stress         「ストレス：Ｎ／１００」 with N = min(100, floor(値·100/257)).
                   The 257 is measured from both sides: 257 → 100 caps it
                   from above, 200 → 77 from below. The bar's colour tracks it
                   (38 cyan, 77 yellow, 100 red); where the thresholds sit is
                   not known.
    condition      an index into `chara_condition.bin` — 0 健康, 1 ノイローゼ,
                   2 怪我, 3 ドクターストップ — confirmed on 0 and 2. Out of
                   range draws nothing, which is why -3 once looked like a
                   field the client ignores.
    elapsedDays    no text of its own; it sets the バイオリズム graph's phase.
    clubParamInfo  the 「部　活」 tab, and only eight of the sixteen: keys 1-8,
                   野球部 through 家庭科部. 無所属, 未定部１…６ and 番長 are
                   never drawn whatever they hold. level is 0-based the way
                   testLevel is — level[1] = 50 draws 「レベル５１」 — and
                   gauge reads against a full scale near 255 (99 filled 37.8%
                   of the track; one point only, so the offset the ability bar
                   carries was not separated out).

⚠️ Widths differ between messages for the same quantity, so do not share a
packer: `stress` is u16 here and u8 in 0x6102's 結果発表, and `condition` is i8
in both. Reading one off the other would have gone unnoticed until a value
above 255 appeared.

⚠️ EVERY VALUE HERE IS UNSET, not invented. Nothing in this server raises an
ability, a club level or a 徳: the subsystems that would (授業's 能力増減,
クラブ活動モード, キーワード) are not modelled, so a sheet reads zero until
`/ab` is used to put a number on it by hand. That is deliberate and it is the
same choice `lesson.end_params` already makes by sending ability and
beforeAbility equal — a screen that reports nothing is the honest rendering of
a system that is not there. `/ab ruler` exists to measure the screen, not to
play the game.

`testLevel` is NOT stored here. It is the ScoreCard's 試験レベル, which is
already derived from the 課程 that have been 修了, and a second copy would be a
second answer to the same question.
"""
from __future__ import annotations

import struct

MSG_CL_QUERY_CHARA_MENU_ABILITY = 0x430F
MSG_SV_RESULT_CHARA_MENU_ABILITY = 0x4310
MSG_SV_ERROR_CHARA_MENU_ABILITY = 0x4311

# tmn::NUM_OF_CHARA_ABILITY, and the six records of `chara_ability_type.bin` in
# key order. The manual names one of these per subject —「国語なら文系、数学な
# ら理系など」(p06_02, said three times over in the お助けスキル list) — which
# is the hook 授業's 能力増減 will hang on once the mapping is settled.
ABILITIES = ("文系", "理系", "芸術", "雑学", "運動", "スタミナ")

# tmn::NUM_OF_CLUB, and the sixteen records of `club.bin`: 無所属 first, then
# the eleven real clubs, six of which are 未定部１…６ placeholders, and 番長
# last. Two parallel arrays, so a club has both a level and a gauge.
CLUBS = 16


class AbilitySheet:
    """One character's ability sheet, as the キャラメニュー draws it.

    Stored on the character record under "ability" and rebuilt from that dict
    each time, the same arrangement as Romance and ScoreCard: the file is small
    and a sheet only means anything next to the character it belongs to.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.params = self._row(saved.get("params"), len(ABILITIES))
        self.club_level = self._row(saved.get("clubLevel"), CLUBS)
        self.club_gauge = self._row(saved.get("clubGauge"), CLUBS)
        self.virtue = int(saved.get("virtue", 0))
        self.stress = int(saved.get("stress", 0))
        self.condition = int(saved.get("condition", 0))
        self.elapsed_days = int(saved.get("elapsedDays", 0))

    @staticmethod
    def _row(values: object, size: int) -> "list[int]":
        row = [int(value) for value in values] if isinstance(values, list) else []
        return (row + [0] * size)[:size]

    def to_json(self) -> dict:
        return {
            "params": list(self.params),
            "clubLevel": list(self.club_level),
            "clubGauge": list(self.club_gauge),
            "virtue": self.virtue,
            "stress": self.stress,
            "condition": self.condition,
            "elapsedDays": self.elapsed_days,
        }

    def levels(self) -> "list[int]":
        """The six 能力 as レベル rather than as stored: ``(値 >> 8) + 1``.

        The shift is the display's own rule, measured off the screen on thirty
        points (see the module docstring). It is a method here because the
        恋愛 ability gate compares against 3, 4, 5 and 10, and those are only
        numbers on this side of it.

        ⚠️ 値 ≥ 32768 draws by a different rule altogether — the one the module
        docstring brackets but does not explain. This returns the shift for
        those too, because the gate is a comparison against a small integer and
        every reading of a value that large clears every gate anyway.
        """
        return [(value >> 8) + 1 for value in self.params[: len(ABILITIES)]]

    def result_params(self, test_level: int = 0) -> bytes:
        """MsgSvResultCharaMenuAbility, field by field in wire order.

        ``test_level`` comes from the caller's ScoreCard rather than from here;
        see the module docstring.
        """
        out = bytearray(struct.pack(">B", test_level & 0xFF))
        for row in (self.club_level, self.club_gauge):
            out += bytes(value & 0xFF for value in row[:CLUBS])
        for value in self.params[: len(ABILITIES)]:
            out += struct.pack(">H", value & 0xFFFF)
        out += struct.pack(">HH", self.virtue & 0xFFFF, self.stress & 0xFFFF)
        out += struct.pack(">b", max(-128, min(127, self.condition)))
        out += struct.pack(">I", self.elapsed_days & 0xFFFFFFFF)
        return bytes(out)

    def summary(self) -> str:
        abilities = " ".join(
            f"{name} {value}" for name, value in zip(ABILITIES, self.params)
        )
        return (
            f"{abilities} | 徳 {self.virtue}, ストレス {self.stress}, "
            f"体調 {self.condition}, 経過日数 {self.elapsed_days}"
        )

    def lines(self) -> "list[str]":
        """Chat-window rendering, one ability per line plus any joined clubs."""
        out = [f"{name}: {value}" for name, value in zip(ABILITIES, self.params)]
        out.append(
            f"徳 {self.virtue} / ストレス {self.stress} / "
            f"体調 {self.condition} / 経過日数 {self.elapsed_days}"
        )
        joined = [
            f"{index}:{level}({gauge})"
            for index, (level, gauge) in enumerate(zip(self.club_level, self.club_gauge))
            if level or gauge
        ]
        if joined:
            out.append("部活 " + " ".join(joined))
        return out

    def ruler(self) -> None:
        """Make every field on the screen identifiable at a glance — an earlier lesson.

        A sheet of zeros cannot tell "the client did not draw this" apart from
        "the client drew a 0", and six fields that all read the same cannot say
        *which* of the six 能力 sits in which row. Powers of two do both at
        once: any subset of the six can be read back from a single screenshot,
        and no value can be mistaken for its neighbour or for a total.

            能力      1 2 4 8 16 32   position is recoverable from the value
            徳        100             three digits, unlike any ability
            ストレス  200             and distinct from 徳, since both are u16
            体調      -3              negative on purpose: the field is i8 and
                                      a signed reader is the claim being tested
            経過日数  1234            wide enough to prove the u32 is a u32
            部活      level = index, gauge = 2 × index

        The club rows double as a check that the two arrays are not swapped:
        gauge is twice level everywhere, so a transposed pair reads as halves.
        """
        self.params = [1 << index for index in range(len(ABILITIES))]
        self.club_level = list(range(CLUBS))
        self.club_gauge = [2 * index for index in range(CLUBS)]
        self.virtue = 100
        self.stress = 200
        self.condition = -3
        self.elapsed_days = 1234

    def clear(self) -> None:
        """Back to an unset sheet — all zeros, which is what a new one is."""
        blank = AbilitySheet()
        self.params = blank.params
        self.club_level = blank.club_level
        self.club_gauge = blank.club_gauge
        self.virtue = blank.virtue
        self.stress = blank.stress
        self.condition = blank.condition
        self.elapsed_days = blank.elapsed_days
