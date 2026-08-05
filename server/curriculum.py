"""カリキュラム: 校内時計、時間割、そして通知表.

Two messages, and between them the whole of the 授業 system's bookkeeping:

    0x4309 MsgClQueryCurriculum  -> 0x430A MsgSvResultCurriculum
    0x430C MsgClQueryScoreCard   -> 0x430D MsgSvResultScoreCard

The first is the school clock. Its answer is four bytes — timeTableType,
dayOfTheWeek, hour, minuts — and nothing else, which settles a question the
manual leaves open: the 時間割 grid the client draws is **not** sent by the
server. The client owns `class_schedule.bin` and only needs telling what time
it is. The clock is therefore server-authoritative and the timetable is a pure
function of it.

The second is the 通知表 (メインメニュー →「生徒情報」→「通知表」). Manual
`manual/p06_01` lists its columns one by one, and every column is a field of
MsgSvResultScoreCard — with three exceptions:

    前回得点          -> lastScore
    最高得点/必要得点 -> maxScore / ✗ not on the wire
    成績              -> estimation / ✗ not on the wire
    出席表            -> attendanceCount / ✗ not on the wire
    修了状況          -> completionFlag
    総合評価          -> totalEstimation

The three 必要 halves never cross the network. The client must therefore read
them out of a local table, and there is exactly one place they can be: the
20-byte constant tail every one of `lesson.bin`'s eight records carries, byte
for byte identical across all eight. See REQUIRED_* below.

⭐ Every value below that the 通知表 can display has been read back off the
screen (2026-08-03, the ruler in chat.py's /card). That is the only reason the
thresholds are stated as fact: the client filled the 必要 columns in with
70/80/80, Ｃ/Ｂ/Ｂ and 7/40/100 from its own copy of lesson.bin, which is what
proves the decoding rather than merely fitting it.

⚠️ It also killed a claim made here before that test ran — that there are five
課程 because the completionInfo buffer holds forty rows and the manual's three
is stale. The screen draws **three** stages per subject, 24 rows, exactly as
`p06_01` says. Forty was headroom over 8 × 3, and reading a capacity as a count
was the mistake. `quiz_level.bin` had said so all along: its records' last byte
is 0, 0, 0, 1, 1, setting `senior` and `master` apart from the three levels the
manual admits to.
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta

MSG_CL_QUERY_CURRICULUM = 0x4309
MSG_SV_RESULT_CURRICULUM = 0x430A
MSG_SV_ERROR_CURRICULUM = 0x430B
MSG_CL_QUERY_SCORE_CARD = 0x430C
MSG_SV_RESULT_SCORE_CARD = 0x430D
MSG_SV_ERROR_SCORE_CARD = 0x430E

NAME_LEN = 11  # tmn::MAX_CHARA_FAMILYNAME + 1, same as characters.NAME_LEN

# `subject_type.bin` and `lesson.bin` agree, keys 0–7 in this order. The wire's
# subjectId is one of these.
SUBJECTS = ("国語", "数学", "理科", "社会", "外国語", "体育", "芸術", "家庭科")

# Who teaches each subject: a `lesson_npc.bin` key, from `lesson.bin`'s u16[3].
# Read rather than guessed — 体育's is 2 and `lesson_npc` 8:2 is 体育教師, which
# no other assignment of that column would produce. The rest fall out with it:
#
#     国語 城崎先生   数学/理科 薬研先生   芸術 黒十影先生   家庭科 針縫先生
#     社会 汎用先生（男）        外国語 汎用先生（女）
#
# The two 汎用 are the middleware's generic teachers, which is why two subjects
# share them and why the named ones are the interesting ones.
SUBJECT_TEACHER = (3, 4, 4, 0, 1, 2, 5, 6)

# 組 → その組の教室の map id, from `class.bin`'s u16[1]. All twenty-six agree
# with `map.bin`'s own names (key 10 「Ｋ組」 → map 16 「一般教室校舎２ＦＫ組
# 教室」), so this is a decode and not a correlation.
#
# It matters because it settles where a lesson happens: `p06_02` says 「授業は
# あなたが在籍しているクラスの教室で受けることができます」, so the room is a
# property of the *player's* 組 and not of the subject. A column in lesson.bin
# that looked like a map id (17/17/23/17/17/38/24/22) is therefore not one —
# 17 and 22–24 are ordinary 組 classrooms and 体育 would never be held in one.
CLASSROOM = (
    3, 4, 5, 6, 7, 8, 9, 10, 11, 12,          # Ａ〜Ｊ組  一般教室校舎１Ｆ
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25,   # Ｋ〜Ｔ組  一般教室校舎２Ｆ
    29, 30, 31, 32, 33, 34,                   # Ｕ〜Ｚ組  一般教室校舎３Ｆ
)

# How many 課程 each subject has. Three, counted off the 通知表 itself, which is
# also what `p06_01` says. The client's completionInfo buffer takes forty rows,
# but that is room and not a count — see the ⚠️ above.
COURSES = 3

# Where the wire's `testLv` starts counting. Zero, measured: a row sent as
# testLv 1 was drawn on 段階２ and one sent as testLv 0 would therefore be 段階
# １. The client places each row at `subjectId * COURSES + testLv` in the grid
# it draws, so this is not cosmetic — get it wrong and every row shifts down one
# and the last ones fall off the end of the sheet.
TESTLV_BASE = 0

# ── recovered from lesson.bin ───────────────────────────────────────────────
# Bytes 34–53 of every lesson.bin record, identical in all eight, so these are
# global settings rather than per-subject ones:
#
#     46 50 50 55 5a | 03 04 04 04 05 | 07 00 28 00 64 00 c8 00 5e 01
#     └─ u8 × 5 ────┘ └─ u8 × 5 ─────┘ └─ u16 × 5 (little-endian) ────┘
#
# That they are the 課程修了 thresholds is not a guess. Four things agree:
#
#   1. Count and order. `p06_01`: 「課程を修了するには、試験の点数、授業の成績、
#      出席回数において、条件をクリアする必要があります」— exactly three
#      conditions, and here are exactly three arrays, in that same order.
#   2. Length. Five each, matching the 40-row completionInfo buffer's 5 課程.
#   3. Width. On the wire lastScore/maxScore are u8, estimation is u8 and
#      attendanceCount is u32; here the score and grade arrays are u8 and only
#      the attendance one is u16 — which it has to be, since 350 > 255. Swap
#      any two arrays and the widths stop making sense.
#   4. Monotonicity. All three rise, as thresholds for successive stages must.
#
# …and then the 通知表 printed the first three of each in its 必要 columns, which
# turns all of that from a good fit into a measurement.
#
# Only the first COURSES entries are reachable. The trailing two of each array
# are the same unused headroom as `quiz_level`'s senior/master; they are kept
# because they are what the file says, not because anything reads them.
REQUIRED_SCORE = (70, 80, 80, 85, 90)        # 必要得点
REQUIRED_ESTIMATION = (3, 4, 4, 4, 5)        # 必要成績 (1=Ｅ … 5=Ａ)
REQUIRED_ATTENDANCE = (7, 40, 100, 200, 350)  # 必要な出席回数

# The two letter scales do not share a base, which is the sort of thing only an
# experiment settles. Both measured off the 通知表 in the same pass:
#
#   成績      1…5 → Ｅ…Ａ    estimation 1 drew Ｅ, 5 drew Ａ
#   総合評価  0…9 → Ｊ…Ａ    totalEstimation 3 drew Ｇ, which is 'A' + (9 - 3);
#                            a one-based ten-step scale would have drawn Ｈ
ESTIMATION_MIN, ESTIMATION_MAX = 1, 5
TOTAL_ESTIMATION_MIN, TOTAL_ESTIMATION_MAX = 0, 9

# 何も受けていない試験の「前回得点」.
#
# ⚠️ Open. `p06_01` promises 「前回試験を受けていない場合、点数は表示されません」
# and a sheet full of zeros came back drawn as zeros, so whatever the sentinel
# is, it is not this. Nothing else in the row is a candidate — lastScore is a
# lone u8 — so it is presumably a magic value like 0xFF. Untested; leave the
# blank-cell promise unmet rather than guess at it.
NO_SCORE = 0


def grade_letter(value: int, steps: int = 5, base: int = ESTIMATION_MIN) -> str:
    """`base` → the lowest letter, `base + steps - 1` → 「Ａ」. Logs only.

    Both of the 通知表's scales go through here, which is why the base is a
    parameter and not an assumption: 成績 runs 1…5 over Ｅ…Ａ while 総合評価
    runs 0…9 over Ｊ…Ａ. Both were read off the screen; see above.
    """
    if not base <= value < base + steps:
        return "?"
    return chr(ord("A") + steps - 1 - (value - base))


# ── the school clock ────────────────────────────────────────────────────────
# dayOfTheWeek is a `class_schedule.bin` key: 0=日, 1=月 … 6=土. That is also
# what `(weekday() + 1) % 7` gives, so no table is needed.
#
# timeTableType picks which 時間割 the client draws. `p06_01`: 「試験期間中は、
# 時間割が試験の時間割になります」— two timetables, so 0 is the ordinary one.
# There is no idlist table for the type, so 1 = 試験期間 is an assumption; this
# server never sets it, because there are no exam periods yet.
TIMETABLE_NORMAL = 0
TIMETABLE_EXAM = 1

# 授業は15分ごとに行われます (`p06_01`, `p06_02`). Fifteen is the manual's own
# number, stated twice, so the slot length is recovered and not chosen.
LESSON_MINUTES = 15

# 校内マップにいる場合、授業開始５分前に予鈴があります (`p06_02`).
PRE_BELL_MINUTES = 5

# ── 時間割, recovered from class_schedule.bin ───────────────────────────────
# Seven records, one per weekday, 24 bytes each: key u16, name[4], then nine
# little-endian u16. The first of the nine is zero in all seven rows and the
# remaining eight are the day's subjects, so the row is one unidentified field
# followed by eight slots.
#
#     0 日  (0) 6 7 0 1 2 3 4 5
#     1 月  (0) 0 1 2 3 4 5 6 7
#     2 火  (0) 1 2 3 4 5 6 7 0
#     …
#     6 土  (0) 5 6 7 0 1 2 3 4
#
# It is the eight subjects rotated left by `(day - 1) mod 7`, and an earlier
# pass shipped that formula instead of the table. The table is what the file
# says; the rotation is a remark about it. Ship the table.
#
# ⭐ The 時間割 tab settles the eight. Its rows run 14:15 数学 … 16:15 数学 on
# 月 — the same subject two hours apart, which is eight fifteen-minute slots and
# not nine. So the leading zero is a field of the record and not a period. What
# it is remains unknown; it is simply not this.
TIMETABLE = (
    (6, 7, 0, 1, 2, 3, 4, 5),  # 0 日
    (0, 1, 2, 3, 4, 5, 6, 7),  # 1 月
    (1, 2, 3, 4, 5, 6, 7, 0),  # 2 火
    (2, 3, 4, 5, 6, 7, 0, 1),  # 3 水
    (3, 4, 5, 6, 7, 0, 1, 2),  # 4 木
    (4, 5, 6, 7, 0, 1, 2, 3),  # 5 金
    (5, 6, 7, 0, 1, 2, 3, 4),  # 6 土
)
SLOTS_PER_CYCLE = len(TIMETABLE[0])

# Where slot 0 of the day sits on the wall clock, in minutes past midnight.
#
# ⭐ Measured, not chosen. The 時間割 tab prints every slot's 開始時間 (`p06_02`:
# 「授業科目の順番や開始時間は…「時間割」で確認できます」) and the server sends
# nothing but hour and minuts, so the client lays the grid out from a rule of its
# own that this has to match. It draws 月曜's 国語 at 16:00 — 960 minutes, a
# whole number of two-hour cycles past midnight — and the 15:00 row across all
# seven weekdays reads 外国/体育/芸術/家庭/国語/数学/理科, which is TIMETABLE[d][4]
# for every d. Sixty-three cells, no disagreement.
#
# So the day is twelve passes of the same eight subjects. That is not decoration:
# a single two-hour pass would lock an evening player out of 国語 forever, and
# the weekday rotation exists so that someone who plays at fixed hours still
# meets all eight over a week.
TIMETABLE_SLOT_ZERO = 0


def clock(when: datetime | None = None) -> tuple[int, int, int, int]:
    """``(timeTableType, dayOfTheWeek, hour, minuts)`` — the 0x430A body's fields.

    The host's wall clock, straight through. The original ran on Japan time and
    a single-player server has no reason to; what matters for fidelity is that
    the clock is real time and the server is the one that says so, both of which
    this keeps.
    """
    now = when or datetime.now()
    return (TIMETABLE_NORMAL, (now.weekday() + 1) % 7, now.hour, now.minute)


def day_of_week(when: datetime | None = None) -> int:
    """`class_schedule.bin` key: 0=日, 1=月 … 6=土."""
    return ((when or datetime.now()).weekday() + 1) % 7


def slot_index(when: datetime | None = None) -> int:
    """Which of the day's eight slots is in session, 0…7."""
    now = when or datetime.now()
    minutes = now.hour * 60 + now.minute - TIMETABLE_SLOT_ZERO
    return minutes // LESSON_MINUTES % SLOTS_PER_CYCLE


def subject_at(day: int, slot: int) -> int:
    """The 時間割 cell, straight out of the table."""
    return TIMETABLE[day % len(TIMETABLE)][slot % SLOTS_PER_CYCLE]


def current_subject(when: datetime | None = None) -> int:
    """Which subjectId is in session right now."""
    return subject_at(day_of_week(when), slot_index(when))


def slot_start(when: datetime | None = None) -> datetime:
    """When the slot that is in session began."""
    now = when or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = now.hour * 60 + now.minute - TIMETABLE_SLOT_ZERO
    began = minutes // LESSON_MINUTES * LESSON_MINUTES + TIMETABLE_SLOT_ZERO
    return midnight + timedelta(minutes=began)


def next_slot_start(when: datetime | None = None) -> datetime:
    """When the next lesson begins. This is what the bells are hung on."""
    return slot_start(when) + timedelta(minutes=LESSON_MINUTES)


def next_lesson(when: datetime | None = None) -> tuple[datetime, int]:
    """``(開始時刻, subjectId)`` of the lesson after the one in session.

    Crossing midnight changes the weekday and therefore the row of the table,
    so the subject is looked up at the *start time*, never at now.
    """
    begins = next_slot_start(when)
    return begins, subject_at(day_of_week(begins), slot_index(begins))


def timetable_lines(day: int | None = None) -> list[str]:
    """One day's 時間割 as text, for the log and for /card-style commands."""
    day = day_of_week() if day is None else day
    out = []
    for slot in range(SLOTS_PER_CYCLE):
        minute = TIMETABLE_SLOT_ZERO + slot * LESSON_MINUTES
        out.append(
            f"{minute // 60:02d}:{minute % 60:02d} {SUBJECTS[subject_at(day, slot)]}"
        )
    return out


def result_curriculum(when: datetime | None = None) -> bytes:
    """MsgSvResultCurriculum. Four bytes; see the deserializer at 0x008CE3C0."""
    return struct.pack(">bbBB", *clock(when))


class ScoreCard:
    """One character's 通知表, in the two shapes the wire wants it.

    Per subject: how many lessons attended and the 成績 they earned. Per subject
    *and* 課程: the last and best exam scores. 修了状況 and 試験レベル are not
    stored — both are decided by the thresholds above, and a stored copy is a
    copy that can disagree with them.

    Lives in the character's record in runtime/characters.json, next to
    ``romance``, and for the same reason: it is save data, not world data.
    """

    def __init__(self, saved: dict | None = None) -> None:
        saved = saved or {}
        attendance = saved.get("attendance") or []
        estimation = saved.get("estimation") or []
        scores = saved.get("scores") or []
        self.attendance = [int(v) for v in attendance[: len(SUBJECTS)]]
        self.attendance += [0] * (len(SUBJECTS) - len(self.attendance))
        self.estimation = [int(v) for v in estimation[: len(SUBJECTS)]]
        self.estimation += [ESTIMATION_MIN] * (len(SUBJECTS) - len(self.estimation))
        # 通算, per subject: every lesson question ever asked and every one got
        # right. `p06_02` is explicit that these are lifetime and not per-period
        # 「その授業時間内の正解率ではなく、科目の通算正解率となります」, which is
        # also why they belong in the save file rather than in the Lesson object.
        # They feed 0x6100's seatInfo, where the 正解率 on the panel over the desk
        # comes from, and 成績 below is derived from them.
        asked = saved.get("asked") or []
        right = saved.get("right") or []
        self.asked = [int(v) for v in asked[: len(SUBJECTS)]]
        self.asked += [0] * (len(SUBJECTS) - len(self.asked))
        self.right = [int(v) for v in right[: len(SUBJECTS)]]
        self.right += [0] * (len(SUBJECTS) - len(self.right))
        # scores[subject][course] = (lastScore, maxScore)
        self.scores: list[list[tuple[int, int]]] = []
        for index in range(len(SUBJECTS)):
            row = scores[index] if index < len(scores) else []
            pairs = [
                (int(pair[0]), int(pair[1])) if isinstance(pair, (list, tuple)) else (NO_SCORE, 0)
                for pair in row[:COURSES]
            ]
            pairs += [(NO_SCORE, 0)] * (COURSES - len(pairs))
            self.scores.append(pairs)

    # ── derived, never stored ───────────────────────────────────────────────

    def completed(self, subject: int, course: int) -> bool:
        """Has this 課程 been 修了? All three conditions, as `p06_01` states them."""
        _, best = self.scores[subject][course]
        return (
            best >= REQUIRED_SCORE[course]
            and self.estimation[subject] >= REQUIRED_ESTIMATION[course]
            and self.attendance[subject] >= REQUIRED_ATTENDANCE[course]
        )

    def test_level(self) -> int:
        """試験レベル, 1…COURSES+1.

        `p06_01` gives the rule outright: 「試験レベルは、全科目の同じ段階の課程
        を全て修了することによりアップします（１科目でも修了していないと試験
        レベルは上がりません）」. So it is one plus however many stages are
        complete across every subject, counting from the first and stopping at
        the first gap.

        The ceiling is COURSES + 1 and not COURSES — an earlier version capped it
        at three and was wrong. `error_message.bin` gates the お助けスキル on it
        and its own wording runs past three:
        「試験レベルが２未満では「精神集中」を…」 (545), 「…３未満では「明鏡止
        水」…」 (553), 「…４未満では「ティーチング」を使うことはできません。」
        (559). Four is reachable, which is exactly what 1 + three finished stages
        gives, and it makes the best skill in the set the reward for graduating
        every 課程 of every 科目.
        """
        level = 1
        for course in range(COURSES):
            if not all(self.completed(subject, course) for subject in range(len(SUBJECTS))):
                break
            level += 1
        return min(level, COURSES + 1)

    def total_estimation(self) -> int:
        """総合評価, 1-based (1=Ｊ … 10=Ａ).

        ⚠️ INVENTED, and unrecoverable for the same reason 成績 is — see
        ESTIMATION_BANDS. `p06_01` gives the inputs and never the arithmetic
        (「現在の成績と全課程の修了状況により決定される」), and 総合評価 reaches
        the client the same way 成績 does: as one byte this server writes, on a
        message that carries neither of the two inputs.

        So this is a shape that satisfies the sentence and no more: the mean
        成績 over the eight subjects supplies half the range and the fraction of
        課程 修了 the other half. Change it freely. What must not happen is
        someone later reading it as recovered.
        """
        subjects = len(SUBJECTS)
        mean = sum(self.estimation) / subjects  # 1…5
        done = sum(
            self.completed(subject, course)
            for subject in range(subjects)
            for course in range(COURSES)
        ) / (subjects * COURSES)  # 0…1
        span = TOTAL_ESTIMATION_MAX - TOTAL_ESTIMATION_MIN  # 9
        raw = TOTAL_ESTIMATION_MIN + span * (
            0.5 * (mean - ESTIMATION_MIN) / (ESTIMATION_MAX - ESTIMATION_MIN) + 0.5 * done
        )
        return max(TOTAL_ESTIMATION_MIN, min(TOTAL_ESTIMATION_MAX, int(round(raw))))

    def total_letter(self) -> str:
        """総合評価 as the 通知表 prints it, Ｊ…Ａ."""
        steps = TOTAL_ESTIMATION_MAX - TOTAL_ESTIMATION_MIN + 1
        return grade_letter(self.total_estimation(), steps, TOTAL_ESTIMATION_MIN)

    # ── mutation ────────────────────────────────────────────────────────────

    def rate(self, subject: int) -> float:
        """通算正解率 for one subject, 0.0…1.0. No questions yet reads as 0.

        This is the number the 授業 panel prints as 「正解率」 and it is a lifetime
        figure, not this period's — `p06_02` says so in as many words. Which is
        the whole reason ``asked``/``right`` are saved rather than kept in the
        Lesson: a period ends, the tally does not.
        """
        return self.right[subject] / self.asked[subject] if self.asked[subject] else 0.0

    def answered(self, subject: int, asked: int, right: int) -> None:
        """File a period's questions into the subject's 通算 tallies."""
        self.asked[subject] += max(0, asked)
        self.right[subject] += max(0, right)

    def attend(self, subject: int) -> int:
        """One lesson sat through. Returns the new 出席回数."""
        self.attendance[subject] += 1
        return self.attendance[subject]

    # 授業の成績 (Ａ〜Ｅ) as a function of 通算正解率.
    #
    # ⚠️ INVENTED, and the invented part is the curve rather than the inputs.
    # Read the split before changing anything here.
    #
    # The inputs are an argument, and a decent one. `p06_01` lists 「授業の成績」
    # beside 「試験の点数」 and 「出席回数」 as the three 課程 conditions, so it has
    # to be something lessons produce; the only per-subject lifetime quantity a
    # lesson produces is the 通算正解率 (attendance being already spoken for),
    # and the game cares enough about that rate to ship questionCount and
    # correctAnswerCount to the client so the panel over the desk can print it.
    #
    # ⚠️ A rival reading survives and always will: 成績 could be a stock that
    # moves a notch per period rather than a function of the lifetime rate.
    # `p06_02` hangs ご褒美 on 「**その授業での**成績」, which is a per-period
    # sense of the word, and the per-question 高／並／低評価 machinery shows the
    # game grading period by period. H1 (a function of the rate) is what runs
    # here because it is stateless and recomputable — edit the tallies and the
    # grade follows — not because H2 was ruled out.
    #
    # The curve is not merely unrecovered, it is **unrecoverable from what we
    # have**, so do not go looking and do not let a later session think a screen
    # can settle it:
    #
    #   * 成績 appears on the wire exactly once, server → client, as the u8 in
    #     0x430D. That message carries no rate; 0x6100 carries the rate but no
    #     成績; 0x6102 carries neither.
    #   * /card ruler sent 1,2,3,4,5 against arbitrary attendance and the 通知表
    #     drew Ｅ Ｄ Ｃ Ｂ Ａ, so the client echoes this byte the way it echoes
    #     completionFlag. Reading a grade off the screen reads back this file.
    #   * Which is also why the curve is in no client-side table, and why that
    #     absence is not evidence of a bad search: a server constant only shows
    #     up in client data when the client has to draw it (the 通知表 prints the
    #     required 成績, so lesson.bin carries those). No screen ever shows a
    #     rate-to-grade mapping, so the client was never given one. Searched
    #     anyway, 2026-08-05: all 105 idlist tables for 成績|評価|正解 (only
    #     lesson_npc_sentence, teacher dialogue), lesson.bin field by field, the
    #     quiz_*/subject_*/class tables, error_message.bin's 965 strings, and the
    #     official site including the beta manual. Nothing states the arithmetic.
    #
    # So these five bands are a shape that satisfies the sentence and no more.
    # They are stated as the lower bound of each grade, Ｅ first, and the top one
    # is deliberately reachable — REQUIRED_ESTIMATION asks for Ａ to finish the
    # last 課程, so a curve that cannot award Ａ would wall off 試験レベル 4.
    ESTIMATION_BANDS = (0.0, 0.40, 0.60, 0.75, 0.90)

    def grade_from_rate(self, subject: int) -> int:
        """成績 for one subject, from its 通算正解率. See ESTIMATION_BANDS."""
        rate = self.rate(subject)
        grade = ESTIMATION_MIN
        for step, floor in enumerate(self.ESTIMATION_BANDS):
            if rate >= floor:
                grade = ESTIMATION_MIN + step
        return min(grade, ESTIMATION_MAX)

    def regrade(self, subject: int) -> int:
        """Bring 成績 into line with the tallies. Returns the new grade.

        Called when a period ends, so that in ordinary play there is exactly one
        writer of ``estimation`` and it cannot drift from ``asked``/``right``.
        ``set_estimation`` stays for /card, which is a probe and is allowed to
        lie — a hand-set grade survives until the next lesson in that subject.
        """
        self.estimation[subject] = self.grade_from_rate(subject)
        return self.estimation[subject]

    def set_estimation(self, subject: int, estimation: int) -> bool:
        """Set 授業の成績 for one subject. False if out of the Ａ〜Ｅ range."""
        if not ESTIMATION_MIN <= estimation <= ESTIMATION_MAX:
            return False
        self.estimation[subject] = estimation
        return True

    def record_exam(self, subject: int, course: int, score: int) -> tuple[int, int]:
        """File one exam result. Returns ``(lastScore, maxScore)`` after filing."""
        score = max(0, min(100, score))
        _, best = self.scores[subject][course]
        self.scores[subject][course] = (score, max(best, score))
        return self.scores[subject][course]

    # ── the wire ────────────────────────────────────────────────────────────

    def params(self, family_name: bytes, first_name: bytes, in_class: int = 0) -> bytes:
        """A MsgSvResultScoreCard body. Deserializer: 0x008CE4E0.

            u16 inClass
            char familyName[11], firstName[11]      (fixed reader 0xA49610)
            u8  totalEstimation
            u16 count1; { u16 subjectId, u32 attendanceCount, u8 estimation } × count1
            u16 count2; { u16 subjectId, u16 testLv, u8 lastScore,
                          u8 maxScore, u8 completionFlag } × count2

        Both loops write into fixed buffers with no bounds check — eight entries
        and forty — so the counts are capped rather than trusted. Sending a
        ninth subject would corrupt the client's heap.

        ``testLv`` here is not the global 試験レベル: it is which 課程 the row is
        for, and the client uses it as an index — the row lands at
        ``subjectId * COURSES + testLv`` on the sheet. Zero-based; the first
        pass sent it one-based and every row came out one line low, with 家庭科's
        stage-1 result printed on its 段階２ line.
        """
        subjects = min(len(SUBJECTS), 8)
        out = struct.pack(">H", in_class)
        out += family_name.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        out += first_name.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        out += struct.pack(">B", self.total_estimation())

        out += struct.pack(">H", subjects)
        for subject in range(subjects):
            out += struct.pack(
                ">HIB", subject, self.attendance[subject], self.estimation[subject]
            )

        rows = [
            (subject, course)
            for subject in range(subjects)
            for course in range(COURSES)
        ][:40]
        out += struct.pack(">H", len(rows))
        for subject, course in rows:
            last, best = self.scores[subject][course]
            out += struct.pack(
                ">HHBBB",
                subject,
                course + TESTLV_BASE,
                last,
                best,
                1 if self.completed(subject, course) else 0,
            )
        return out

    def to_json(self) -> dict:
        return {
            "attendance": list(self.attendance),
            "estimation": list(self.estimation),
            "scores": [[list(pair) for pair in row] for row in self.scores],
            "asked": list(self.asked),
            "right": list(self.right),
        }

    def lines(self) -> list[str]:
        """The card as chat lines.

        Several rather than one because the chat bar clips: the first attempt at
        this was a single line and the client cut it off after the third subject,
        which is fine for a log and useless for reading state back in game.
        """
        out = [
            f"総合評価 {self.total_letter()}, 試験レベル {self.test_level()}",
        ]
        half = len(SUBJECTS) // 2
        parts = [
            f"{name} {grade_letter(self.estimation[index])}"
            f"/{self.attendance[index]}回/{sum(self.completed(index, course) for course in range(COURSES))}修了"
            for index, name in enumerate(SUBJECTS)
        ]
        out.append(", ".join(parts[:half]))
        out.append(", ".join(parts[half:]))
        # 通算正解率, but only for subjects that have sat a lesson. Printing all
        # eight would clip the way the single-line version of this method did,
        # and 「0%(0/0)」 eight times over says nothing.
        rates = [
            f"{name} {self.rate(index):.0%}({self.right[index]}/{self.asked[index]})"
            for index, name in enumerate(SUBJECTS)
            if self.asked[index]
        ]
        if rates:
            out.append("正解率 " + ", ".join(rates))
        return out

    def summary(self) -> str:
        """One line for the server log, where nothing clips."""
        return " | ".join(self.lines())
