"""お助けスキル — the eight things a student may do during a 授業.

「授業中に画面上のマップキャラにマウスカーソルを合わせて左クリックをすると、
「お助けスキル」が表示されます」 (`p06_02`). Five of the eight act on yourself and
three act on a classmate, and the split is visible in the protocol before anyone
reads the manual: the ones that must hand something back are Request/Ok/Ng, and
the ones that only announce what you did are Cast/Notify/Error.

    自分用   助けてコール  Help          0x610F  Cast
             早弁          Lunch         0x6112  Cast
             直感          Feeling       0x6115  Request
             精神集中      Cool          0x611D  Request
             明鏡止水      Meikyoushisui 0x6124  Request
    他人用   そっと応援    Support       0x6121  Cast
             カンニング    Cheating      0x6119  Request
             ティーチング  Teaching      0x6128  Cast

⭐ The naming is not a guess. `MsgSvOkLessonCool` and
`MsgSvNotifyLessonTeachingToTarget` are the only two replies in the family that
carry a *counted array of u8* instead of one u8, and 精神集中 and ティーチング are
the only two skills the manual describes as narrowing the choice list
(「答えを絞り込みます」「選択肢を半分に絞り込んであげる」). The other three that
answer — 直感, 明鏡止水, カンニング — each hand back a single `choiceId`, which is
what 「答えを選びます」 and 「自分の答えを他の生徒の答えと同じにして決定します」
describe. Shape and prose agree skill by skill.

⭐ So does `successFlag`. It is present in exactly the four Notify bodies whose
skills the manual says can fail — 早弁, カンニング, 精神集中, ティーチング — and
absent from 直感, 明鏡止水 and そっと応援, the three it does not. 直感 and 明鏡止水
still miss: 「必ずしも正解を選ぶとは限りません」 is a wrong answer, not a failure,
and the wire draws that distinction too.

Field names are the client's own, from the debug formatters (`the field-name extractor`
in the reverse-engineering tree); no disassembly was needed for any of it.
"""

import random
import struct

import curriculum


# ── the wire ────────────────────────────────────────────────────────────────
MSG_CL_CAST_LESSON_HELP = 0x610F
MSG_SV_NOTIFY_LESSON_HELP = 0x6110
MSG_SV_ERROR_LESSON_HELP = 0x6111
MSG_CL_CAST_LESSON_LUNCH = 0x6112
MSG_SV_NOTIFY_LESSON_LUNCH = 0x6113
MSG_SV_ERROR_LESSON_LUNCH = 0x6114
MSG_CL_REQUEST_LESSON_FEELING = 0x6115
MSG_SV_OK_LESSON_FEELING = 0x6116
MSG_SV_NG_LESSON_FEELING = 0x6117
MSG_SV_NOTIFY_LESSON_FEELING = 0x6118
MSG_CL_REQUEST_LESSON_CHEATING = 0x6119
MSG_SV_OK_LESSON_CHEATING = 0x611A
MSG_SV_NG_LESSON_CHEATING = 0x611B
MSG_SV_NOTIFY_LESSON_CHEATING = 0x611C
MSG_CL_REQUEST_LESSON_COOL = 0x611D
MSG_SV_OK_LESSON_COOL = 0x611E
MSG_SV_NG_LESSON_COOL = 0x611F
MSG_SV_NOTIFY_LESSON_COOL = 0x6120
MSG_CL_CAST_LESSON_SUPPORT = 0x6121
MSG_SV_NOTIFY_LESSON_SUPPORT = 0x6122
MSG_SV_ERROR_LESSON_SUPPORT = 0x6123
MSG_CL_REQUEST_LESSON_MEIKYOUSHISUI = 0x6124
MSG_SV_OK_LESSON_MEIKYOUSHISUI = 0x6125
MSG_SV_NG_LESSON_MEIKYOUSHISUI = 0x6126
MSG_SV_NOTIFY_LESSON_MEIKYOUSHISUI = 0x6127
MSG_CL_CAST_LESSON_TEACHING = 0x6128
MSG_SV_NOTIFY_LESSON_TEACHING = 0x6129
MSG_SV_ERROR_LESSON_TEACHING = 0x612A
MSG_SV_NOTIFY_LESSON_TEACHING_TO_TARGET = 0x612B

# Every client-to-server body in the family starts with the same u8, and the
# three that name a classmate follow it with a u32:
#
#     questionNo                       Help Lunch Feeling Cool Meikyoushisui
#     questionNo, targetId             Cheating Support Teaching
#
# `questionNo` is the same counter 0x6105 MsgClCastLessonAnswer carries, so it is
# checked the same lenient way — see Lesson.take_answer for why one-vs-zero based
# is not settled and why being lenient is the cheap side of that bet.


# ── the level gates ─────────────────────────────────────────────────────────
# ⭐ RESTORED, and from the client's own data rather than from prose:
# `error_message.bin` spells each gate out in a sentence that names both the
# skill and the number.
#
#     545  試験レベルが２未満では「精神集中」を使うことはできません。
#     549  試験レベルが２未満では「そっと応援」は使うことはできません。
#     553  試験レベルが３未満では「明鏡止水」を使うことはできません。
#     559  試験レベルが４未満では「ティーチング」を使うことはできません。
#
# ⚠️ Two of the four disagree with the manual, and the data is followed:
#
#   * そっと応援 — `p06_02` lists it with no gate at all. The data has one.
#   * ティーチング — `p06_02` says 「試験レベルが３になると使用できるように
#     なります」. The data says 4.
#
# The other two (精神集中 2, 明鏡止水 3) agree, so this is not a case of one
# source being wrong about everything. What settles it is the direction the two
# sources drift: the β manual (archived 2006-02-03) states *no* gates for any of
# the four, and the release manual (2006-05-08) added three of them. A page that
# was late to document gates at all, and still omits そっと応援's entirely, is a
# page that lags the build. `error_message.bin` is not documentation — those
# strings exist because a server sent the reason code that selects them.
#
# ⚠️ This is not a rule that the manual loses. It remains the authority on what
# a skill *means*; it lost here only on a number, and only to data that states
# that same number more directly.
#
# 試験レベル runs 1…5 (`quiz_level.bin` has five records), so a gate of 4 is
# reachable. The manual's 「難易度は３レベル存在します」 is about 難易度, which is
# what the level selects, not the level itself.
LEVEL_GATE = {
    MSG_CL_REQUEST_LESSON_COOL: 2,
    MSG_CL_CAST_LESSON_SUPPORT: 2,
    MSG_CL_REQUEST_LESSON_MEIKYOUSHISUI: 3,
    MSG_CL_CAST_LESSON_TEACHING: 4,
}


# ── refusal reasons ─────────────────────────────────────────────────────────
# ⚠️ Every Ng/Error in this family is one u8 the client calls `reason`, and what
# number means what is **not settled**. It cannot be read off `error_message.bin`
# directly: that table's ids run past 900 and the field is a byte.
#
# What the client actually holds is a sorted lookup table at file offset
# 0x009B3648, 12-byte records of (errorMessageId, group, code), 1128 of them. The
# skill strings 529…561 all live in it, so `reason` is the `code` half of a key
# whose `group` half the client supplies from somewhere else. Which group each
# message contributes is the part still open — the groups those rows carry do not
# fall on skill boundaries, and at least one (group, code) pair appears twice,
# so the record is not simply a two-column key and one more pass is owed to it.
#
# Until that pass happens every refusal here sends zero, and REASON_PROBE exists
# to settle it by experiment instead: set it, trigger a refusal, read the dialog
# the client draws. That is the same arrangement lesson.NG_PROBE already uses for
# the bell, and for the same reason — the meaning of a server-to-client byte can
# only be recovered by sending it.
REASON_UNSPECIFIED = 0
REASON_PROBE: "dict[int, int]" = {}


def reason_for(msg_type: int) -> int:
    """The byte a refusal of `msg_type` carries, honouring the probe knob."""
    return int(REASON_PROBE.get(msg_type, REASON_UNSPECIFIED)) & 0xFF


# ── what the rules are ──────────────────────────────────────────────────────
# ⭐ RESTORED. `error_message.bin` 529…561 is a complete statement of when each
# skill is refused, because a refusal the original server never sent would have
# no string. Read as rules rather than as sentences:
#
#   all five self-skills   refused once you have answered this question
#                          (529 助けてコール, 534 直感, 543 精神集中,
#                           551 明鏡止水; カンニング 539)
#   早弁                   refused with no 「お弁当」 in hand (531);
#                          no effect at zero ストレス (532)
#   直感 / 明鏡止水        no effect when one choice is left (536, 554)
#   精神集中 / ティーチング no effect when the list is already narrowed (546, 558)
#   カンニング             needs a target who has already answered (541);
#                          target must resolve (540)
#   ティーチング           refused when the target has already answered (561);
#                          target must resolve (560)
#   そっと応援             target must resolve (550)
#   all                    refused after the question's timer has run out
#
# The last one is why `questionNo` is on every request: 「選択がゲームサーバ側の
# 制限時間内に間に合いませんでした」 is exactly the check Lesson already makes on
# 0x6105, applied to skills.
BENTO_ITEM_ID = 8  # `item.bin` 8 お弁当「ストレスがちょっと回復します」


# ── what had to be invented ─────────────────────────────────────────────────
# ⚠️ INVENTED, all of it, and unavoidably: there is no お助けスキル table. The
# only skill tables in the data are `clubskill.bin`/`item_skillbook.bin`, both 57
# records, and both belong to クラブ活動. These eight are hard-coded in the
# original server, so nothing about their strength survives on this side.
#
# What the manual does pin down is the *shape*: 直感, 精神集中 and 明鏡止水 all
# scale with 「授業の科目に応じた能力」, and 明鏡止水 is 「さらにすごい」 than
# 直感. So the numbers below are a floor plus an ability-driven span, with
# 明鏡止水 strictly above 直感 at every ability. Nothing verifies the values.
#
# Ability is 8.8 fixed point (レベル = (値 >> 8) + 1), and ABILITY_FULL is the
# レベル at which a skill is as good as it gets — 25 because lesson.ABILITY_STEP's
# own note puts a third 課程 near there, so "as far as this save can go" and "as
# good as the skill gets" line up.
ABILITY_FULL = 25

# (floor, ceiling) probability, at レベル 1 and at ABILITY_FULL.
FEELING_ACCURACY = (0.30, 0.70)        # 直感: picks *an* answer, maybe wrong
MEIKYOU_ACCURACY = (0.50, 0.95)        # 明鏡止水: 「さらにすごい直感」
COOL_SUCCESS = (0.40, 0.90)            # 精神集中: 「成功する確率が高くなります」
CHEATING_SUCCESS = 0.70                # カンニング: no ability clause in the manual
LUNCH_SUCCESS = 0.80                   # 早弁: 「失敗することもあります」
TEACHING_SUCCESS = 0.80                # ティーチング: 「失敗することもあります」

# How far 精神集中 and ティーチング narrow the list. 「選択肢を半分に絞り込んで
# あげる」 is the manual's own word for ティーチング and is applied to both, since
# 精神集中 is described only as 「絞り込みます」 with no number. Rounded up, so a
# 4択 becomes 2 and a ○× cannot become 1 — a skill that hands you the answer
# outright would make 明鏡止水's gate pointless.
def narrowed_size(count: int) -> int:
    return max(2, (count + 1) // 2)


# ⚠️ INVENTED. ストレス moves on nearly every one of these — every Notify in the
# family carries a `stress` or `userStress` — but no quantity survives. These are
# scaled off stress.STRESS_PER_LESSON (26, ≈10 on the 100-point screen) so that a
# skill costs a fraction of a lesson rather than a lesson's worth.
#
# 助けてコール is the one that costs nothing: its Notify carries `userId` and
# nothing else, so the wire says the server had no stress figure to report.
STRESS_FEELING = 3
STRESS_MEIKYOUSHISUI = 5
STRESS_COOL = 5
STRESS_CHEATING_FAILED = 13     # 「失敗すると…ストレスが上がります」, half a lesson
STRESS_CHEATING_OK = 3
STRESS_TEACHING = 3             # spent by the teacher, not the taught
STRESS_SUPPORT_GIVER = 0        # 「あなたが応援することで」 — the cost is theirs
STRESS_SUPPORT_TARGET = -8      # 「相手のストレスを少し減らす」
STRESS_LUNCH = -13              # 「ストレスがちょっとふっと回復します」 (`item.bin` 8)


def _ability_fraction(params: "list[int]", subject: int) -> float:
    """0.0…1.0 over the two abilities `lesson.bin` puts on this subject.

    「国語なら文系、数学なら理系など」 is curriculum.SUBJECT_ABILITY, which is
    that column of `lesson.bin` and not a reading of the sentence.
    """
    slots = curriculum.SUBJECT_ABILITY[subject % len(curriculum.SUBJECT_ABILITY)]
    levels = [((params[slot] if slot < len(params) else 0) >> 8) + 1
              for slot in slots]
    level = sum(levels) / len(levels)
    return max(0.0, min(1.0, (level - 1) / max(1, ABILITY_FULL - 1)))


def chance(band: "tuple[float, float]", params: "list[int]", subject: int) -> float:
    """Where in `band` this character's ability for `subject` puts them."""
    low, high = band
    return low + (high - low) * _ability_fraction(params, subject)


# ── bodies ──────────────────────────────────────────────────────────────────
def error_params(reason: int) -> bytes:
    """MsgSvError… / MsgSvNg… — `reason=%d`, one u8, for all eight skills."""
    return struct.pack(">B", reason & 0xFF)


def notify_help_params(user_id: int) -> bytes:
    """0x6110 — `userId`. The only Notify in the family with nothing else."""
    return struct.pack(">I", user_id)


def notify_lunch_params(user_id: int, stress: int, success: bool) -> bytes:
    """0x6113 — `userId`, `stress`, `successFlag`."""
    return struct.pack(">IBB", user_id, stress & 0xFF, 1 if success else 0)


def notify_stress_params(user_id: int, stress: int) -> bytes:
    """0x6118 直感 and 0x6127 明鏡止水 — `userId`, `stress`. No successFlag."""
    return struct.pack(">IB", user_id, stress & 0xFF)


def notify_self_params(user_id: int, stress: int, success: bool) -> bytes:
    """0x6120 精神集中 — `userId`, `stress`, `successFlag`."""
    return struct.pack(">IBB", user_id, stress & 0xFF, 1 if success else 0)


def notify_target_params(user_id: int, user_stress: int,
                         target_id: int, last: int) -> bytes:
    """0x611C カンニング, 0x6122 そっと応援, 0x6129 ティーチング.

    `userId`, `userStress`, `targetId`, then one more u8 which is
    `targetStress` for そっと応援 and `successFlag` for the other two — the same
    four slots either way, which is why they share a builder.
    """
    return struct.pack(">IBIB", user_id, user_stress & 0xFF,
                       target_id, last & 0xFF)


def ok_choice_params(choice_id: int) -> bytes:
    """0x6116 直感, 0x611A カンニング, 0x6125 明鏡止水 — one `choiceId`."""
    return struct.pack(">B", choice_id & 0xFF)


def ok_choice_list_params(choice_ids: "list[int]") -> bytes:
    """0x611E 精神集中 and 0x612B ティーチング — `choiceId[count]`, u8 each."""
    out = bytearray(struct.pack(">H", len(choice_ids)))
    for choice_id in choice_ids:
        out += struct.pack(">B", choice_id & 0xFF)
    return bytes(out)


# ── the rules, as one entry point ───────────────────────────────────────────
# The three that name a classmate, and therefore the three whose request body is
# `questionNo, targetId` rather than `questionNo` alone.
TARGETED = (
    MSG_CL_REQUEST_LESSON_CHEATING,
    MSG_CL_CAST_LESSON_SUPPORT,
    MSG_CL_CAST_LESSON_TEACHING,
)

# Every client message this module answers, and for each one the reply to refuse
# with. Cast skills refuse with an Error, Request skills with an Ng — the client
# named them differently and they are kept apart.
REFUSAL = {
    MSG_CL_CAST_LESSON_HELP: MSG_SV_ERROR_LESSON_HELP,
    MSG_CL_CAST_LESSON_LUNCH: MSG_SV_ERROR_LESSON_LUNCH,
    MSG_CL_REQUEST_LESSON_FEELING: MSG_SV_NG_LESSON_FEELING,
    MSG_CL_REQUEST_LESSON_CHEATING: MSG_SV_NG_LESSON_CHEATING,
    MSG_CL_REQUEST_LESSON_COOL: MSG_SV_NG_LESSON_COOL,
    MSG_CL_CAST_LESSON_SUPPORT: MSG_SV_ERROR_LESSON_SUPPORT,
    MSG_CL_REQUEST_LESSON_MEIKYOUSHISUI: MSG_SV_NG_LESSON_MEIKYOUSHISUI,
    MSG_CL_CAST_LESSON_TEACHING: MSG_SV_ERROR_LESSON_TEACHING,
}
HANDLED = frozenset(REFUSAL)

NAMES = {
    MSG_CL_CAST_LESSON_HELP: "助けてコール",
    MSG_CL_CAST_LESSON_LUNCH: "早弁",
    MSG_CL_REQUEST_LESSON_FEELING: "直感",
    MSG_CL_REQUEST_LESSON_CHEATING: "カンニング",
    MSG_CL_REQUEST_LESSON_COOL: "精神集中",
    MSG_CL_CAST_LESSON_SUPPORT: "そっと応援",
    MSG_CL_REQUEST_LESSON_MEIKYOUSHISUI: "明鏡止水",
    MSG_CL_CAST_LESSON_TEACHING: "ティーチング",
}


def parse_request(msg_type: int, params: bytes) -> "tuple[int, int]":
    """(questionNo, targetId). targetId is 0 for the five self-skills.

    Short bodies read as zeros rather than raising: a truncated request is a
    request for question zero, which check_common refuses anyway.
    """
    question_no = params[0] if params else 0
    target_id = 0
    if msg_type in TARGETED and len(params) >= 5:
        target_id = struct.unpack_from(">I", params, 1)[0]
    return question_no, target_id


class Refused(Exception):
    """A skill the rules do not allow. Carries the reason byte to send."""

    def __init__(self, msg_type: int, why: str) -> None:
        super().__init__(why)
        self.msg_type = msg_type
        self.why = why
        self.reason = reason_for(msg_type)


def check_common(period, msg_type: int, question_no: int, test_level: int) -> None:
    """The checks every skill shares, in the order the strings imply.

    `period` is a lesson.Lesson. Raises Refused; returns None when allowed.
    """
    gate = LEVEL_GATE.get(msg_type)
    if gate is not None and test_level < gate:
        raise Refused(msg_type, f"試験レベル {test_level} < {gate}")
    if period is None or period.phase != period.ASKING or period.question is None:
        raise Refused(msg_type, "制限時間外")
    # Lenient exactly as Lesson.take_answer is, and for the same unsettled
    # reason: whether the client counts questions from one or from zero.
    if question_no not in (period.question_no, period.question_no - 1):
        raise Refused(msg_type, f"questionNo {question_no} は今の問題ではない")
    if period.reported is not None:
        raise Refused(msg_type, "解答済み")


def live_choices(period) -> "list[int]":
    """The choices still on the table — narrowed if a skill has narrowed them."""
    if period.narrowed is not None:
        return list(period.narrowed)
    return list(period.question.choice_ids)


def pick_answer(period, accuracy: float, rng=None) -> int:
    """A choiceId for 直感 / 明鏡止水: the right one with probability `accuracy`.

    「必ずしも正解を選ぶとは限りません」 — so a miss returns a wrong choice
    rather than nothing, and the player cannot tell which they got until the
    question is marked.
    """
    rng = rng or random
    choices = live_choices(period)
    right = [c for c in choices if period.question.judge(c)]
    wrong = [c for c in choices if not period.question.judge(c)]
    if right and (not wrong or rng.random() < accuracy):
        return rng.choice(right)
    return rng.choice(wrong or right or choices)


def narrow(period, rng=None) -> "list[int]":
    """Halve the live choices, always keeping the right one.

    A narrowing that could drop the answer would make 精神集中 a way to lose,
    which is not what 「答えを絞り込みます」 describes.
    """
    rng = rng or random
    choices = live_choices(period)
    keep = narrowed_size(len(choices))
    right = [c for c in choices if period.question.judge(c)]
    wrong = [c for c in choices if not period.question.judge(c)]
    rng.shuffle(wrong)
    kept = (right[:1] or choices[:1]) + wrong[: max(0, keep - 1)]
    return sorted(kept, key=choices.index)
