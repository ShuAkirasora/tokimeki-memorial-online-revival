"""The question bank, from the side that has to mark the answers.

授業 is a quiz. `0x6103 MsgSvNotifyLessonQuestionStart` names a question with
three numbers and no text at all —

    u16 quizType, u16 quizLv, u16 quizId

— so the questions themselves live in the client, and what reaches it is a
key. That split is not this server's invention; it is the whole reason the
protocol looks like this. The client renders, the server arbitrates: it is the
server that decides which question is asked and the server that answers
`0x6106 MsgSvNotifyLessonAnswer`'s `correctAnswerflg`.

⭐ **quizId counts within a category, not across the bank.** The client resolves
a question at 0x007A3456: it walks `quiz_category.bin`'s 32-byte records
comparing three u16s at record +0x18, +0x1a and +0x1c against (subject,
quizType, quizLv), copies the matching record, and then

    0x007A34D6   mov  eax, [ebp+0x14]     ; quizId
    0x007A34D9   push 0x7d                ; 125
    0x007A34DD   idiv ecx                 ; eax = shard, edx = index in shard

builds a filename from the record's own name plus `"_%02d"` % shard and asks
for record `quizId % 125` inside it. So a quizId is meaningless without the
category, the largest one in the bank is 319, and a flat 0…9185 numbering —
which is what a naive extraction produces — would be wrong in every category
but the first. Verified for all 9186 questions at export time.

The subject is not in 0x6103 because it is already fixed for the period, by
0x6100's `subjectId`.

── what ships, and what does not ───────────────────────────────────────────

``reference/quizkeys.json``, about 6 KiB, holding two things per category:

    "{subject}_{quizType}_{quizLv}": {"count": N, "answers": "0110…"}

``count`` is the range of valid quizIds; without it the server cannot ask a
question the client can look up. ``answers`` is one character per question and
appears only for ○× categories.

The 4択 half of the bank — 6320 of the 9186 — needs **no data at all**, because
in the client's own files the right answer is always the first of the four
choices. The server is the one that shuffles them, in `choiceId[]` below, so it
already knows where the right one went. Nothing has to be shipped to recover a
fact the server itself chose. (Checked, not assumed: the exporter re-verifies
all 6320 on every run and refuses to write if one ever differs.)

That leaves 2866 bits of genuine data, the ○× answers, which split 1439/1427 —
no rule hides in them, they are simply the answers. Also therefore worth being
precise about: the question text, the four choice strings and the subject names
are **not here and are not shipped**. This file cannot show anyone a question.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

KEYS_PATH = Path(__file__).resolve().parent.parent / "reference" / "quizkeys.json"

# `quiz_type.bin`, both records.
TYPE_TRUEFALSE = 0   # ○×
TYPE_CHOICE = 1      # ４択

CHOICES = 4          # the 4択 choice count, and choiceId[]'s buffer capacity

# 「難易度は３レベル存在します」 (`p06_01`). `quiz_level.bin` has five records
# and the bank has questions for all five, but the manual is explicit that three
# exist and 通知表 drew three rows a round earlier for the same reason; the last
# two are the same unused headroom in both tables. Lessons draw from these.
LEVELS = (0, 1, 2)

# ⭐ Which level a question comes from is **recovered, not policy**. `p06_01`:
# 「授業では、出題の度にランダムで難易度が決定しますが、試験では、試験レベルに
# 応じた難易度の問題しか出題されません」— so a lesson rolls the difficulty per
# question and an exam does not. That sentence also fixes the range:
# 「授業ではレベル１〜３の問題が出題されます」.
#
# Which of the two *types* a question is has no such sentence behind it. `p06_02`
# says only 「種類は「４択」か「○×」の２種類になります」, one line before the
# 難易度 sentence that does specify. So the type roll below is INVENTED, and it
# is a coin flip because that is the least assuming shape, not because anything
# says even odds.
TYPE_ODDS_TRUEFALSE = 0.5


def _load() -> dict[tuple[int, int, int], dict]:
    try:
        raw = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[quiz] no question keys ({exc}); lessons will ask nothing")
        return {}
    out: dict[tuple[int, int, int], dict] = {}
    for key, entry in raw.items():
        subject, quiz_type, level = (int(part) for part in key.split("_"))
        out[(subject, quiz_type, level)] = entry
    return out


BANK = _load()


def count(subject: int, quiz_type: int, level: int) -> int:
    """How many quizIds this category has. 0 if it has none, or if no bank loaded."""
    entry = BANK.get((subject, quiz_type, level))
    return int(entry["count"]) if entry else 0


def available(subject: int) -> list[tuple[int, int]]:
    """The ``(quizType, quizLv)`` pairs this subject actually has questions in.

    Not every cell of the table is filled — 外国語's level-5 ○× category is
    empty in the client's own table, count 0 — and asking out of an empty one
    would send a quizId the client cannot resolve.
    """
    return [
        (quiz_type, level)
        for quiz_type in (TYPE_TRUEFALSE, TYPE_CHOICE)
        for level in LEVELS
        if count(subject, quiz_type, level) > 0
    ]


class Question:
    """One question, as asked: which one, and in what order the choices went out.

    ``choice_ids`` is what `0x6103` carries as `choiceId[]`. For 4択 it is a
    permutation of 0…3, and it is the whole reason no answer key is needed for
    those: position 0 of the client's file is the right answer, so whichever
    slot holds the value 0 is the right slot, and the server dealt the deck.

    ⚠️ Which end of `0x6105 MsgClCastLessonAnswer`'s `choiceId` the client
    reports — the slot it drew in, or the value this list put there — is not
    settled. `judge` accepts either reading, because for a permutation both are
    answerable and the two agree exactly when the answer is right, which is the
    only bit `0x6106` carries. See there.
    """

    def __init__(self, subject: int, quiz_type: int, level: int, quiz_id: int,
                 choice_ids: "list[int]", answer: bool | None) -> None:
        self.subject = subject
        self.quiz_type = quiz_type
        self.level = level
        self.quiz_id = quiz_id
        self.choice_ids = choice_ids
        # ○× only: what the bank says. None for 4択, where the key is positional.
        self.answer = answer

    def judge(self, reported: int) -> bool:
        """Was that right?

        4択: the right choice is the one the file put first, so it is right if
        the player's report points at raw choice 0 — either directly, or as the
        slot whose ``choice_ids`` entry is 0. Both readings are checked because
        they cannot be told apart from the disassembly, and they disagree only
        on wrong answers, never on right ones: exactly one slot holds 0 and
        exactly one raw value is 0.

        ⚠️ That tolerance is deliberate but it is not free. If the client turns
        out to report slots, a player who picks the slot *numbered* 0 while the
        right answer sits elsewhere would be marked right. The knob that removes
        this is one measurement — ask a 4択 with a known deal and see which
        number comes back — and until then this errs towards the player.

        ○×: the report selects one of the two options this server sent in
        ``choice_ids``, and 0 is ○. ⭐ **Measured on screen**, which it had to be
        — `quiz_type.bin` only names the type 「○×」 in that order, which is
        suggestive and not evidence. A 芸術 level-3 ○× question came up asking
        whether 東大寺南大門's style is called 「宋様」; the bank says false, the
        player clicked × and the client sent choiceId 1, and this server's answer
        of "correct" was the ○ the client then drew over the desk. Three things
        agreeing — the bank, the click, and the mark — is what settles it; the
        mark alone never could, since the client draws whatever this end says.
        """
        if self.quiz_type == TYPE_CHOICE:
            if reported == 0:
                return True
            return 0 <= reported < len(self.choice_ids) and self.choice_ids[reported] == 0
        return (reported == 0) == bool(self.answer)


def pick(subject: int, rng: random.Random | None = None) -> Question | None:
    """Roll one question for this subject, or None if the bank has nothing.

    Difficulty is rolled per question (`p06_01`, quoted above). Which quizId
    within the category is INVENTED — nothing states it, and uniform is the
    least assuming choice. There is deliberately no memory of what has already
    been asked: 通算正解率 is what the game records, a repeat costs the player
    nothing, and an anti-repeat rule would be furniture.
    """
    rng = rng or random
    pairs = available(subject)
    if not pairs:
        return None
    wanted = TYPE_TRUEFALSE if rng.random() < TYPE_ODDS_TRUEFALSE else TYPE_CHOICE
    candidates = [pair for pair in pairs if pair[0] == wanted] or pairs
    quiz_type, level = rng.choice(candidates)
    quiz_id = rng.randrange(count(subject, quiz_type, level))

    if quiz_type == TYPE_CHOICE:
        choice_ids = list(range(CHOICES))
        rng.shuffle(choice_ids)
        return Question(subject, quiz_type, level, quiz_id, choice_ids, None)

    entry = BANK[(subject, quiz_type, level)]
    answers = entry.get("answers") or ""
    if quiz_id >= len(answers):
        # The count and the answer string are written together and asserted
        # equal by the exporter, so this is a corrupt file rather than a case.
        print(f"[quiz] {subject}_{quiz_type}_{level}: no answer for quizId {quiz_id}")
        return None
    # ○× goes out as the two options in their natural order; there is nothing to
    # shuffle, since ○ and × are drawn by the client and mean themselves.
    return Question(subject, quiz_type, level, quiz_id, [0, 1], answers[quiz_id] == "1")


def loaded() -> bool:
    """Whether there is a bank at all. Lessons check before they ring."""
    return bool(BANK)
