"""試験: the periodic academic test, and the half of カリキュラム that scores it.

授業 raises 出席回数 and 成績. 試験 supplies the third condition — the score —
and until this module existed no 課程 in this server could ever be 修了, which
also meant 試験レベル was frozen at 1 forever. This closes that loop.

`p06_03` states the system in prose. Quoted where it decides something:

    定期的に行われる学力テストです。
    試験期間中に各科目の試験を１回ずつ受けます（１科目につき１回しか
      受けられません）。
    テストの難易度はそのときのあなたの試験レベルによって変わります。
    「試験問題」 …全２０問が出題されます。
    「マークシート」 …解答はマークシート方式です。
    「制限時間」 …制限時間は１０分です。
    「退出ボタン」 …早く終わった場合は、制限時間が終了していなくても、
      退出できます。
    試験は、授業と同じように開始時間に教室に待機していることで参加できます。
      ただし、試験は他のプレイヤーと一緒に受けることはできません。
    クラスもしくは氏名を記入し忘れると０点になってしまいます。
    自分の結果は、試験期間終了後に通知表で確認することができます。

and `p06_01` settles the difficulty:

    試験では、試験レベルに応じた難易度の問題しか出題されません
    （…試験では、試験レベルが１の場合はレベル１の問題のみ出題されます）

THE WIRE
--------
Thirteen messages, in two blocks, all thirteen already named in the id table
and shaped in the frozen the shape reader dump. The 0x66xx block is the doorway and
mirrors 授業's 0x60xx one exactly; the 0x6Axx block is the paper itself.

    0x6600 MsgSvNotifyBeforeExamStart   u16 subjectId          ≙ 0x6005 予鈴
    0x6601 MsgSvNotifyExamReady         (empty)                ≙ 0x6000 本鈴
    0x6602 MsgClRequestExamReady        (empty)                ≙ 0x6001
    0x6603 MsgSvOkExamReady             u16 schoolId, u16 subjectId, u8 testLv
    0x6604 MsgSvNgExamReady             i8  reason             ≙ 0x6003

    0x6A00 MsgClRequestExamStart        (empty)
    0x6A01 MsgSvOkExamStart             i64 endTime,
                                        u16 count, { u16 quizType, u16 quizId }
    0x6A02 MsgSvNgExamStart             i8  reason
    0x6A03 MsgSvNotifyExamEnd           (empty)      — time is up
    0x6A04 MsgClNotifyExamAnswerState   the mark sheet, unprompted
    0x6A05 MsgClRequestExamPart         the mark sheet, on 退出
    0x6A06 MsgSvOkExamPart              u8 stress, i8 condition
    0x6A07 MsgSvNgExamPart              i8 reason

⚠️ 0x6601 is 0x6000's twin and carries 0x6000's trap with it: the client tears
its scene down and asks to come in *by itself*, with no prompt the player could
decline, so a refusal after the fact costs the connection. Whoever rings it must
check admission first — see lesson.Bell.poll, which this module reuses whole.

⭐ **The mark sheet's two client messages share one deserializer** (0x008F3320,
ICF-folded), so 0x6A04 and 0x6A05 are byte-for-byte the same shape:

    u16 inClass                    the クラス written on the sheet
    char familyName[11]            (fixed reader 0xA49610)
    char firstName[11]
    u16 count; u8 choiceId[count]

⭐⭐ That layout is where `p06_03`'s otherwise odd 【注意事項】 —
「クラスもしくは氏名を記入し忘れると０点になってしまいます」 — stops being a
piece of flavour text and becomes a rule the protocol was built to carry. The
client sends the name and the class *back* on every submission, which is only
worth doing if the server is expected to look at them. See `score` below.

⭐ **Twenty is in the binary, not only in the manual.** The deserializer writes
choiceId into a buffer running +0x1C…+0x30 at one byte each, and 0x6A01's
questionInfo into one running +0x10…+0x60 at four bytes each. Both are exactly
twenty entries, and neither loop is bounds-checked — so 「全２０問」 is also a
hard ceiling on what may be sent.

⭐⭐ **The absence of a field is the evidence.** 授業's 0x6103 names a question
with three numbers — quizType, quizLv, quizId — because a lesson rolls the
difficulty per question. 試験's questionInfo has only two of the three. The
missing quizLv is the one `p06_01` says an exam does not roll, and it is sent
once instead, as 0x6603's `testLv`. The protocol shape and the manual sentence
were recovered independently and agree.

⚠️ questionInfo also has no `choiceId[]`, which 0x6103 does have: in a lesson
the server deals the four options and the client reports back the *value* it
was dealt. Nothing is dealt here.

⭐⭐ **The client deals them itself and reports the undealt value**, so `judge`
works unchanged and the server never needs to know the shuffle. Both halves were
measured on screen:

  * The bank's convention is that the right answer is the first of the four in
    the client's own file, so the server knows a 4択's answer is raw 0. Two live
    papers drew it **fourth** — 「リンゴが84個あります。12人の子供に、1人8個ずつ
    配ったら、何個足りない？」 with 16個/8個/4個/12個, and 「インドネシアに棲む
    世界最大のトカゲは？」 with the コモドオオトカゲ last. File order would have
    put both first, so the client shuffles.
  * Clicking that fourth option put **0** in the next sheet's choiceId[0], not 3.
    So what comes back is the value, and the position it was drawn in never
    leaves the client. The same paper's ○× row, marked ○ on a question the bank
    answers ○, came back **1** — quiz.judge's ○× direction, confirmed here too.

WHAT IS RESTORED AND WHAT IS INVENTED
-------------------------------------
Restored, each traceable to a quoted sentence or to the binary above:

  * all thirteen ids, their field names (the client's own dump strings) and
    every width (the deserializers, not the shape reader — which got this family wrong
    twice; see MISREPORTED below)
  * twenty questions, from three independent places
  * one difficulty for the whole paper, taken from 試験レベル
  * a ten-minute limit, a 退出 button that ends it early, and a mark sheet
  * entry by standing in your own classroom when the slot begins, exactly as
    for 授業 — so lesson.Bell.admit is the same rule and is reused unchanged
  * that a blank class or name scores zero — enforced for the name, which is a
    NUL-padded buffer and therefore self-evidently blank or not; ⚠️ **not** for
    the class, because `inClass` 0 is Ａ組 and there is no sentinel to compare
    against. See CLASS_BLANK.
  * that the result appears on the 通知表 and nowhere else, which is why there
    is no MsgSvResultExam in the block: nothing is shown when the paper ends
  * that exams are solitary, which costs this server nothing — it has one player

Invented, because no table and no sentence carries a number for it:

  * WHEN 試験期間 happens. Nothing in the data describes a school calendar;
    `annual_event.bin`, the only candidate, turned out to be fifteen ドラマ
    scripts (`ev_00NN.gsb`) whose names merely contain the word テスト. So the
    period is switched on by hand here — see `Period` — rather than fabricated
    into a calendar the original would have had and this one would have got
    wrong.
  * POINTS_PER_QUESTION. Twenty questions and a score the 通知表 compares
    against 70/80/80 make five the only round number that reaches 100, but no
    sentence says the paper is marked out of a hundred, so it is a choice.
  * STRESS_PER_EXAM. `p05_09` lists 試験 as a source of ストレス and gives no
    quantity, exactly as for 授業.
  * which quizId inside the category, and the 4択/○× mix — both inherited from
    quiz.py, where they were already invented for 授業.

MISREPORTED
-----------
⚠️ `the shape reader` is wrong about this family in two different ways, and the
standing rule — count the calls in the deserializer before sending anything
that matters — caught both:

  * 0x6A04/0x6A05 are reported `counted entry=25B`. The real entry is one byte;
    25 is the 24-byte prefix (inClass + two names) plus it. A `counted` message
    whose count is not the first thing on the wire confuses the walk.
  * 0x6A01 is reported `scalar reads=8+2+2+2`. It is a counted list with an
    8-byte scalar in front, and 8+2+2+2 is one pass through the loop.

ON SCREEN
---------
Settled by two live exams: the room is built and the paper is drawn, the client
asks for it with 0x6A00 unprompted, the countdown runs off `endTime`, `testLv` 0
is drawn 「レベル１」, the 解答用紙 has twenty rows of 1-2-3-4 and a 組/苗字/名前
header, 0x6A04 is a periodic autosave that starts before anything is filled in,
0xFF is a blank row, 4択 answers come back as the file-order value and ○× as 1
for ○. Also, the hard way, that `schoolId` must be a real one — see
mps_session.EXAM_SCHOOL_ID.

⚠️ Still open, and it needs a person at the keyboard rather than more static
reading: what an unwritten クラス arrives as. Submit with the 組 box **left**
blank and read the inClass the log prints. See CLASS_BLANK.
"""

from __future__ import annotations

import random
import struct
from datetime import datetime, timedelta

import curriculum
import quiz

# ── the wire ────────────────────────────────────────────────────────────────

MSG_SV_NOTIFY_BEFORE_EXAM_START = 0x6600
MSG_SV_NOTIFY_EXAM_READY = 0x6601
MSG_CL_REQUEST_EXAM_READY = 0x6602
MSG_SV_OK_EXAM_READY = 0x6603
MSG_SV_NG_EXAM_READY = 0x6604

MSG_CL_REQUEST_EXAM_START = 0x6A00
MSG_SV_OK_EXAM_START = 0x6A01
MSG_SV_NG_EXAM_START = 0x6A02
MSG_SV_NOTIFY_EXAM_END = 0x6A03
MSG_CL_NOTIFY_EXAM_ANSWER_STATE = 0x6A04
MSG_CL_REQUEST_EXAM_PART = 0x6A05
MSG_SV_OK_EXAM_PART = 0x6A06
MSG_SV_NG_EXAM_PART = 0x6A07

# 「全２０問が出題されます」, and the client's two buffers hold exactly this many.
QUESTIONS_PER_EXAM = 20

# 「制限時間は１０分です」. Comfortably inside a 15-minute slot, which is the
# other half of why the exam can hang off the ordinary lesson bell: the paper
# is over before the next period's 予鈴.
EXAM_MINUTES = 10

# What the paper actually runs for. Ten minutes, and it is a separate name from
# the number above so that shortening it for a test cannot be mistaken for
# revising what the manual says. ⚠️ Module-level and server-wide, like
# lesson.ANSWER_SECONDS: `/exam sec` rebinds it and it stays rebound until the
# server restarts. It exists because the 0x6A03 path is otherwise a ten-minute
# wait to exercise once.
LIMIT_SECONDS = EXAM_MINUTES * 60

NAME_LEN = 11  # tmn::MAX_CHARA_FAMILYNAME + 1, as everywhere else

# What an unfilled row of the マークシート arrives as.
#
# ⭐ Measured, off a real exam: the first 0x6A04 of a paper nobody has touched
# carries twenty 0xFF, and they stay 0xFF until a row is filled in. So a blank
# row is 255 and not 0 — which matters, because 0 is a perfectly good answer.
# ⚠️ Reading a blank as an answer is not a rounding error either: `judge` marks
# a ○× right when `reported == 1` equals the bank, so an untouched ○× row read
# literally would score correct every time the bank says ×. Half the blanks on
# an abandoned paper would have come out right.
UNANSWERED = 0xFF

# Refusal reasons for 0x6604 / 0x6A02 / 0x6A07. ⚠️ These are this server's
# numbering, not a recovered table — the same position lesson.py's are in, and
# for the same reason: no table in the client's files lists them, and the one
# experiment that has been run on 0x6003's twin showed the client draws the same
# 「起動失敗 → ロビーに戻ります」 whatever byte it is handed. They exist to make
# the log say why, not to make the client say why.
REASON_NOT_IN_CLASSROOM = 0
REASON_ALREADY_STARTED = 1
REASON_NEUROSIS = 2
REASON_ALREADY_SAT = 3       # 「１科目につき１回しか受けられません」
REASON_NO_QUESTIONS = 4      # the bank has nothing for this subject at this 難易度

# ── INVENTED — how a 試験 is scored: points per question, how many, pass mark ──
# Twenty questions and a 通知表 that wants 70, 80 and 80 out of the score.
POINTS_PER_QUESTION = 5

# `p05_09` lists 試験 among the things that add ストレス and says how much for
# none of them. An exam is one activity where 授業 is one activity, so it costs
# what a lesson costs; the difference is that an exam happens far less often.
STRESS_PER_EXAM = 26
# ── end INVENTED (inventions:skip) ────────────────────────────────────────


def course_of(card: "curriculum.ScoreCard") -> int:
    """Which 課程 this character's exams are for, 0-based.

    試験レベル counts from 1 and reaches curriculum.COURSES + 1 once every
    course of every subject is 修了; 難易度 has only three levels
    (「難易度は３レベル存在します」) and 課程 only three stages. So the top
    試験レベル has no course of its own left to sit and is clamped onto the last
    one — a character who has finished everything can still take exams, they
    simply cannot improve a 修了 they already hold.

    ⭐ One number does three jobs, and that is not a coincidence in this game's
    design: it is the 課程 the score is filed under, the quizLv the questions
    come from, and the testLv 0x6603 carries. `p06_01` ties the first two
    together outright and the 通知表's own testLv field is 0-based the same way
    (curriculum.TESTLV_BASE).
    """
    return min(card.test_level() - 1, curriculum.COURSES - 1)


def before_start_params(subject: int) -> bytes:
    """MsgSvNotifyBeforeExamStart. One u16, the subject, as 0x6005's is."""
    return struct.pack(">H", subject & 0xFFFF)


def ready_params(school_id: int, subject: int, test_lv: int) -> bytes:
    """MsgSvOkExamReady. Deserializer 0x00900B00: u16, u16, u8 (unsigned).

    `test_lv` is 0-based — it is the quizLv the paper is drawn from, and
    quiz.LEVELS starts at zero. See course_of.
    """
    return struct.pack(">HHB", school_id & 0xFFFF, subject & 0xFFFF, test_lv & 0xFF)


def ng_params(reason: int) -> bytes:
    """MsgSvNgExamReady / NgExamStart / NgExamPart. One byte, read signed.

    All three go through the reader's +0x1C slot — the int8_t one — so 255 is
    read back as −1, which is worth knowing before choosing a probe value.
    0x6A02's deserializer is literally the same function as 0x6003's.
    """
    return struct.pack(">B", reason & 0xFF)


def start_params(end_time_ms: int, questions: "list[quiz.Question]") -> bytes:
    """MsgSvOkExamStart. Deserializer 0x008F3120.

        i64 endTime                    (reader slot +0x10, signed 64)
        u16 count
        { u16 quizType, u16 quizId } × count

    ``endTime`` is in the client's own clock, exactly as 0x6100's speechEndTime
    is: the client is told the moment the paper is due, not how long it has, so
    a packet delayed in flight shortens the exam rather than moving its end.

    ⚠️ The count is capped rather than trusted. The client's questionInfo buffer
    holds twenty and the loop does not check, so a twenty-first entry would be
    written past it.
    """
    body = struct.pack(">qH", end_time_ms, min(len(questions), QUESTIONS_PER_EXAM))
    for question in questions[:QUESTIONS_PER_EXAM]:
        body += struct.pack(">HH", question.quiz_type & 0xFFFF, question.quiz_id & 0xFFFF)
    return body


def part_params(stress_value: int, condition: int) -> bytes:
    """MsgSvOkExamPart. Deserializer 0x00909C10: u8 stress, i8 condition.

    ⚠️ The two fields do not share a width policy with each other or with the
    rest of the game: stress comes off the unsigned byte slot (+0x2C) and
    condition off the signed one (+0x1C). Elsewhere stress is a u16 (0x4310) and
    a u8 (0x6102, 0x4811). Never share a packer between them.
    """
    return struct.pack(">Bb", max(0, min(0xFF, stress_value)), max(-128, min(127, condition)))


def parse_sheet(params: bytes) -> "dict | None":
    """The mark sheet, out of 0x6A04 or 0x6A05. None if it does not parse.

        u16 inClass | char familyName[11] | char firstName[11]
        u16 count   | u8 choiceId[count]

    Returns ``{"inClass", "familyName", "firstName", "choiceId"}`` with the two
    names as the raw NUL-padded bytes the client sent, because whether they are
    *blank* is the question asked of them and decoding would only get in the way.
    """
    head = 2 + NAME_LEN * 2 + 2
    if len(params) < head:
        return None
    in_class = struct.unpack_from(">H", params, 0)[0]
    family = params[2:2 + NAME_LEN]
    first = params[2 + NAME_LEN:2 + NAME_LEN * 2]
    count = struct.unpack_from(">H", params, 2 + NAME_LEN * 2)[0]
    count = min(count, QUESTIONS_PER_EXAM)
    answers = params[head:head + count]
    if len(answers) < count:
        return None
    return {
        "inClass": in_class,
        "familyName": bytes(family),
        "firstName": bytes(first),
        "choiceId": list(answers),
    }


def blank(name: bytes) -> bool:
    """Did the player leave this name field empty on the sheet?

    Unambiguous for the two names, which are NUL-padded fixed buffers: nothing
    written means nothing sent. ⚠️ There is no such test for `inClass` — see
    CLASS_BLANK.
    """
    return not name.split(b"\x00")[0].strip()


# What an unwritten クラス arrives as. ⚠️ Still unknown, and now known to be
# genuinely unknowable by guessing: a paper submitted with the 組 box **filled
# in** came back `inClass=0`. Zero is Ａ組, it is what this server's characters
# are in, and it is what a real filled-in sheet sends — so the obvious test,
# treat zero as empty, would score every Ａ組 paper zero. A u16 has 65535 other
# candidates and the manual names none of them.
#
# So half of `p06_03`'s zero rule is enforced below and half is not, which is
# the honest split until a sheet is submitted with the box **left** blank and
# the log says what came in. `_exam_sheet` prints inClass on every submission
# for exactly that purpose.
#
# ⚠️ The value in a paper's *first* 0x6A04 is not the answer either: that one
# goes out before anything has been filled in and carries uninitialised memory —
# 17279 on one run, 26 on the next, with two copies of the float 255.0 sitting
# in the name buffers behind it.
CLASS_BLANK: "int | None" = None


# ── the paper ───────────────────────────────────────────────────────────────


def has_questions(subject: int, level: int) -> bool:
    """Is there anything to examine this subject on at this 難易度?

    Asked at the door rather than after the scene is built: an empty category
    would mean twenty quizIds the client cannot look up, and 0x6604 is a much
    cheaper way to say no than a room full of blank paper.
    """
    return any(
        quiz.count(subject, quiz_type, level) > 0
        for quiz_type in (quiz.TYPE_TRUEFALSE, quiz.TYPE_CHOICE)
    )


def draw(subject: int, level: int, rng: "random.Random | None" = None
         ) -> "list[quiz.Question]":
    """Twenty questions for one subject at one 難易度, or fewer if the bank is short.

    ⚠️ Every question comes from ``level`` and only ``level``: 「試験レベルに
    応じた難易度の問題しか出題されません」. That is the one thing this differs
    from quiz.pick in, and it is why it cannot simply call it — pick rolls the
    difficulty, which is the lesson's rule.

    The type still rolls, on quiz.TYPE_ODDS_TRUEFALSE's invented coin, and only
    among the types this subject actually has at this level: 外国語's level-5 ○×
    category is empty in the client's own table, and a category with no
    questions cannot be asked out of.
    """
    rng = rng or random
    types = [
        quiz_type
        for quiz_type in (quiz.TYPE_TRUEFALSE, quiz.TYPE_CHOICE)
        if quiz.count(subject, quiz_type, level) > 0
    ]
    if not types:
        return []
    out: "list[quiz.Question]" = []
    for _ in range(QUESTIONS_PER_EXAM):
        wanted = quiz.TYPE_TRUEFALSE if rng.random() < quiz.TYPE_ODDS_TRUEFALSE \
            else quiz.TYPE_CHOICE
        quiz_type = wanted if wanted in types else types[0]
        quiz_id = rng.randrange(quiz.count(subject, quiz_type, level))
        if quiz_type == quiz.TYPE_CHOICE:
            # No choiceId[] goes out for an exam, so there is no deal to record.
            # The natural order is what the client is left to render.
            out.append(quiz.Question(subject, quiz_type, level, quiz_id,
                                     list(range(quiz.CHOICES)), None))
            continue
        entry = quiz.BANK[(subject, quiz_type, level)]
        answers = entry.get("answers") or ""
        if quiz_id >= len(answers):
            print(f"[exam] {subject}_{quiz_type}_{level}: no answer for quizId {quiz_id}")
            continue
        out.append(quiz.Question(subject, quiz_type, level, quiz_id, [0, 1],
                                 answers[quiz_id] == "1"))
    return out


def score(questions: "list[quiz.Question]", sheet: dict) -> "tuple[int, int]":
    """Mark the paper. Returns ``(score, right)``.

    ⭐ The zero rule is `p06_03`'s, word for word: 「クラスもしくは氏名を記入し
    忘れると０点になってしまいます」 — either one missing, not both. The number
    of questions answered correctly is still reported, because the log should be
    able to say *that* the paper was thrown away rather than that it was bad.

    ⚠️ Only the 氏名 half of that rule is enforced. See CLASS_BLANK: zero is a
    real class, so there is nothing to test `inClass` against yet.

    An unanswered question is one the sheet has no entry for, or one whose entry
    is UNANSWERED. The client always sends twenty rows and marks the empty ones
    itself; a short list would be a paper handed in early, which the 退出ボタン
    makes an ordinary thing to do, so both are treated the same way.
    """
    right = 0
    for index, question in enumerate(questions[:QUESTIONS_PER_EXAM]):
        if index >= len(sheet["choiceId"]):
            break
        if sheet["choiceId"][index] == UNANSWERED:
            continue
        if question.judge(sheet["choiceId"][index]):
            right += 1
    unnamed = blank(sheet["familyName"]) or blank(sheet["firstName"])
    unclassed = CLASS_BLANK is not None and sheet["inClass"] == CLASS_BLANK
    if unnamed or unclassed:
        return 0, right
    return min(100, right * POINTS_PER_QUESTION), right


# ── 試験期間 ────────────────────────────────────────────────────────────────


class Period:
    """Whether an exam period is running, and what has already been sat in it.

    ⚠️ INVENTED, all of it. There is no school calendar anywhere in the client's
    data, so rather than invent dates this is a switch — `/exam on` — and the
    ordinary 時間割 supplies the subjects while it is held down. One pass of the
    eight slots is one exam per subject, which is `p06_03`'s
    「各科目の試験を１回ずつ」 landing on the timetable that already exists.

    Not saved, and deliberately: an exam period is a thing the operator turns on
    to watch it work. A period that survived a restart would need an end date,
    and an end date is the calendar this avoids inventing.
    """

    def __init__(self) -> None:
        self.on = False
        self.sat: set[int] = set()      # subjectIds already examined this period
        # The paper in progress, if any.
        self.paper: "Paper | None" = None

    def open(self) -> None:
        self.on = True
        self.sat.clear()

    def close(self) -> None:
        self.on = False
        self.sat.clear()
        self.paper = None

    def taken(self, subject: int) -> bool:
        return subject in self.sat

    def summary(self) -> str:
        if not self.on:
            return "試験期間ではない"
        done = "、".join(curriculum.SUBJECTS[s] for s in sorted(self.sat)) or "まだ"
        return f"試験期間中（受験済み: {done}）"


class Paper:
    """One exam in progress: the questions, the deadline, and the sheet so far.

    The last of those is why 0x6A04 is worth handling at all. It carries the
    same bytes as the 退出 message and asks for no reply, so the plain reading is
    an autosave — the client telling the server what is on the sheet in case the
    connection does not survive to the end. Storing it means a paper interrupted
    by the ten-minute bell still has answers on it.

    ⚠️ Whether the client actually sends 0x6A04, and when, has not been seen.
    Handling it costs nothing and assuming it does not exist would lose a paper.
    """

    def __init__(self, subject: int, course: int,
                 questions: "list[quiz.Question]", began: datetime) -> None:
        self.subject = subject
        self.course = course
        self.questions = questions
        self.began = began
        self.due = began + timedelta(seconds=LIMIT_SECONDS)
        self.sheet: "dict | None" = None
        # Set once 0x6A03 has gone out, so the bell rings once and not on every
        # packet for the rest of the period.
        self.called = False

    def expired(self, now: "datetime | None" = None) -> bool:
        return (now or datetime.now()) >= self.due

    def summary(self) -> str:
        answered = len(self.sheet["choiceId"]) if self.sheet else 0
        return (f"{curriculum.SUBJECTS[self.subject]} 段階{self.course + 1} "
                f"{len(self.questions)}問中 {answered}問 記入")
