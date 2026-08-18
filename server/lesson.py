"""授業: the bells, and who is let into the room when they ring.

`curriculum.py` owns the school clock — which subject is in session and when the
next one begins. This owns what the server *does* about it. The two are split
because the clock is recovered and this is policy: `class_schedule.bin` says what
is taught at 15:00 on a 火曜, and nothing anywhere says what the server should
send to a player standing in the wrong room when it does.

    0x6005 MsgSvNotifyBeforeLessonStart   u16 type          — 予鈴, five minutes out
    0x6000 MsgSvNotifyLessonReady         (empty)           — 本鈴
    0x6001 MsgClRequestLessonReady        (empty)           — sent by the client itself
    0x6002 MsgSvOkLessonReady             (empty)
    0x6003 MsgSvNgLessonReady             u8 reason
    0x6004 MsgSvNotifyLessonStartImpossible u8 reason
    0x6100 MsgSvNotifyLessonStart         counted, 66B entries — the seat list
    0x6103 MsgSvNotifyLessonQuestionStart the question, as three numbers
    0x6105 MsgClCastLessonAnswer          u8 questionNo, u8 choiceId
    0x6106 MsgSvNotifyLessonAnswer        u32 senderId, u8 correctAnswerflg
    0x6104 MsgSvNotifyLessonQuestionEnd   u16 gradingWordsId
    0x6102 MsgSvNotifyLessonEnd           結果発表

Six of the eight handshake bodies are empty or a single byte, and `0x6001` — the client
saying it wants in — carries **nothing at all**: no subject, no room, no seat.
The client is not asserting anything the server could check. Every condition the
manual lists (`p06_02`: in your own 組's classroom, waiting when the bell goes,
no joining once it has started) is therefore the server's to enforce, and none of
it is negotiated on the wire.

⭐ The entry handshake has been run, and it runs like this::

    -> 0x6000                     (empty)
    <- 0x4003 RequestLobbyDataEnd            the client tears the scene down and
                                             rebuilds it — this is the black
                                             screen, and it happens *before* it
                                             has any idea whether it is welcome
    <- 0x6001                     (empty)
    -> 0x6003 reason=0                       →「授業起動失敗」, back to the map

So `0x6000` alone is enough to put the client into 授業モード; it commits to the
mode first and asks afterwards. Refusing is therefore never free — it costs a
scene reload either way, which is an argument for checking what can be checked
*before* ringing rather than after.

The whole chain has since been run: an Ok is followed by 0x6100 and the client
draws the room, the backdrop, the player at a desk and the panel above it. What
this file adds on top of that is the lesson itself — ``Lesson`` down at the
bottom is the ten-question loop, and it is a clocked state machine rather than a
set of handlers because only one of its five messages is something the client
sends.
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta

import curriculum

MSG_SV_NOTIFY_LESSON_READY = 0x6000
MSG_CL_REQUEST_LESSON_READY = 0x6001
MSG_SV_OK_LESSON_READY = 0x6002
MSG_SV_NG_LESSON_READY = 0x6003
MSG_SV_NOTIFY_LESSON_START_IMPOSSIBLE = 0x6004
MSG_SV_NOTIFY_BEFORE_LESSON_START = 0x6005
MSG_SV_NOTIFY_LESSON_START = 0x6100
MSG_SV_NOTIFY_LESSON_END = 0x6102
MSG_SV_NOTIFY_LESSON_QUESTION_START = 0x6103
MSG_SV_NOTIFY_LESSON_QUESTION_END = 0x6104
MSG_CL_CAST_LESSON_ANSWER = 0x6105
MSG_SV_NOTIFY_LESSON_ANSWER = 0x6106
# The 授業 screen keeps a chat bar of its own. It is a separate pair from the
# map's 通常会話 (0x4900/0x4901) even though the box on screen is the same one:
# during a lesson the client casts 0x6109 and never 0x4900, which is why a
# `/quiz` typed in class in round 51 reached the server, printed "no reply
# implemented for 0x6109 yet", and did nothing at all. Layouts in chat.py.
MSG_CL_CAST_LESSON_CHAT = 0x6109
MSG_SV_NOTIFY_LESSON_CHAT = 0x610A
MSG_SV_ERROR_LESSON_CHAT = 0x610B
MSG_CL_CAST_LESSON_EMOTION = 0x610C
MSG_SV_NOTIFY_LESSON_EMOTION = 0x610D
MSG_SV_ERROR_LESSON_EMOTION = 0x610E

# 一般教室校舎 has an 「自分の教室」 pseudo-map at key 128 that no ordinary warp
# leads to. Not used here — the room a lesson happens in is a real map, the one
# `curriculum.CLASSROOM` gives for the player's 組 — but it is the reason not to
# be surprised by a 128 turning up in a map field later.
MY_CLASSROOM_MAP = 128

# ── 予鈴 ────────────────────────────────────────────────────────────────────
# `p06_02`: 「校内マップにいる場合、授業開始５分前に予鈴があります」. Every map
# in `map.bin` is on school grounds — 屋外 included, and there is no off-campus
# map at all — so 「校内マップにいる場合」 is not a place test. It separates
# walking around from being inside another mode (授業 itself, ドラマ, 対戦,
# 自主トレ, the マッチング screen), which is where the client is not on a map.
#
# ⭐ MsgSvNotifyBeforeLessonStart's one u16 is the **subjectId**, measured. The
# client's own dump calls the field `type`, which sent an earlier version of this
# file looking for a table of bell kinds that does not exist; sending 0, 1 and 2
# by hand drew 「まもなく国語の授業が始まります」, 「…数学…」, 「…理科…」 in an
# 「授業予鈴」 window. That is `curriculum.SUBJECTS` in order, so the name in the
# dump is short for something like subjectType (cf. `subject_type.bin`) and not a
# kind of warning at all.
#
# Which also settles what the 予鈴 *is*: not a generic "class soon" chime but the
# announcement of a specific subject, and therefore something the server has to
# look up rather than a constant it can send.

# ── 断られる理由 ────────────────────────────────────────────────────────────
# ⚠️ INVENTED, all of them -- and now known to be inconsequential: the client
# does not read this byte. Both messages carry one u8 the client's own dump
# calls `reason`, and both draw a fixed pair of strings regardless of its value.
#
# For 0x6004 that is settled twice over. The dialog is built at 0x6B2A6B with
# `push 0x266` / `push 0x265` -- msg_text 614 「上限人数オーバー」 and 613
# 「授業開始エラー確認」, hardcoded immediates in a function that has no reason
# parameter -- and sending 0, 1, 2, 3 and 255 drew five identical screens.
#
# For 0x6003 the static trail ends at a delegate bound at run time, so it was
# settled the other way: 0xFF, which the client reads as -1 and which is the
# furthest out of range a byte can go, drew the same 「授業起動失敗」 and the
# same return to the lobby as 0 does.
#
# So these names describe what the *server* means, and nothing the player will
# ever see. They are kept because the server still has to decide, and a named
# decision is worth more than a bare 0.
REASON_NOT_IN_CLASSROOM = 0  # 自分の組の教室にいない
REASON_ALREADY_STARTED = 1   # 途中から参加することはできません (`p06_02`)
REASON_LESSON_OFF = 2        # オプション →「授業の有無」が OFF
REASON_NEUROSIS = 3          # ノイローゼ (`p06_02`: 参加できなくなります)

# What a refusal looks like from the player's side, measured. MsgSvNgLessonReady
# puts up a dialog reading 「授業起動失敗」 over 「ロビーに戻ります。」 --
# `msg_text.bin` 611 and 612 -- and then does exactly that. The client is
# obeying its own message, not falling over.
#
# ⭐ It waits for the player. The connection drops when 確認 is clicked, not on
# any timer, which is the whole of the "sometimes at once, sometimes a minute
# later" that this was written down as for two rounds. That minute was a person.
#
# 0x6004 NotifyLessonStartImpossible draws its own dialog -- 613 over 614,
# 「上限人数オーバー」 -- and does *not* disconnect, because nothing has been torn
# down when it arrives.
#
# ⚠️ That is not a licence to use it as a general "you cannot attend" notice.
# 614 says the room is full, which is `p06_02`'s ~100-student limit and not
# "you are in the wrong room"; sending it for the wrong reason would put an
# official-looking falsehood on screen, every quarter of an hour, in a modal.
# It is the right message for a capacity limit, if this server ever grows one.


# How long after the bell a 0x6001 is still taken. The manual bans joining a
# lesson in progress and says nothing about how much of a moment the client gets
# to answer in; this is the round trip plus the up-to-30s the timesync-driven
# bell can be late by, which is a fact about this server and not the original.
#
# ⚠️ In practice this is unreachable: the client answers 0x6000 within the same
# few packets, with no prompt in between, so nothing ever arrives late enough
# to be turned away by this.
GRACE_SECONDS = 45


# 授業の背景. `lesson.bin`'s u16[4], and it indexes `bg.bin`, not `map.bin`:
#
#     国語/数学/社会/外国語 17 一般教室（昼）   理科 23 理科室（昼）
#     体育 38 グラウンド（昼）  芸術 24 美術室（昼）  家庭科 22 家庭科室（昼）
#
# ⭐ Confirmed on screen before it was confirmed in the table: the 芸術 lesson
# drew 美術教室 and the 体育 one drew a running track, without the server ever
# naming a background. So the client reads this itself and the server has no
# part in it — which is also why the earlier reading of this column as a map id
# had to fail. A lesson is a backdrop, not a place you can walk in; the room you
# must *stand* in to be let in is your 組's, from CLASSROOM above.
LESSON_BACKGROUND = (17, 17, 23, 17, 17, 38, 24, 22)

# ── probe knobs ─────────────────────────────────────────────────────────────
# Settable from chat with /lopt, because 0x6100 kills the client and every retry
# costs a client restart — a knob that survives on the server is worth more than
# a constant that needs one here too. Nothing in normal play reads these except
# through the defaults.
PROBE = {
    "seats": 1,        # how many seatInfo entries go out
    # How long the 開始台詞 runs, and therefore how long until question one:
    # 0x6100's speechEndTime and Lesson's opening phase both read this, so the
    # knob cannot put them out of step. It was 600_000 while the only question
    # about this field was whether the client cared (it did not visibly), and ten
    # minutes of silence is no longer a sensible lesson.
    "speech_ms": 8_000,
    "words": -1,       # -1 = the subject's own 開始台詞
    "charaid": -1,     # -1 = the session's own; see the id namespace below
    "testlv": -1,      # -1 = the 通知表's own 試験レベル
    # How many 「お弁当」 the player sits down with, and therefore whether 早弁 can
    # be used at all. Zero is the honest default: `item.bin` 8 is a consumable and
    # this server has no inventory to hold one, so 「消費アイテム「お弁当」を所持
    # していないため」 (`error_message.bin` 531) is the true answer. The knob is
    # what makes the skill reachable for a test without inventing a stock.
    "lunch": 0,
}

# ── refusal knobs ───────────────────────────────────────────────────────────
# Settable from chat with /bell, and here for the same reason as PROBE: what
# they test costs a login per attempt.
#
# ✅ They have answered the question they were built for, and it was not "what
# does each reason mean" -- which is unanswerable from this side, since which
# value the original server sent in which situation only ever went
# server-to-client, and this is the server now. It was: is any value survivable?
#
# No. 0xFF, read by the client as -1 and as far out of range as a byte goes,
# drew the same 「授業起動失敗」 over 「ロビーに戻ります。」 as 0 does. What
# costs the connection is being refused after the scene has already come down,
# not the number in the refusal, so Bell.poll's suppression stays.
#
# They are kept because they are the only way to ask this message anything, and
# the next question about it will want them.
#
#   reason   the byte a refusal carries; None means the real one
#   force    let /bell ready ring from outside the classroom, which is otherwise
#            refused precisely because it logs the player out
NG_PROBE: dict[str, int | None] = {"reason": None, "force": 0}


def refusal_reason(real: int) -> int:
    """The byte to actually send, honouring the probe knob."""
    override = NG_PROBE["reason"]
    return real if override is None else override

# ⚠️ charaId and testLv were both 1 in the seat that killed the client, and the
# faulting register held 1. Which of the two the classifier was applied to is not
# something the disassembly settles — hence two knobs, so one run tells them
# apart. Everything else in that seat was 0, 3, 4, 9 or 0xFFFF.

# ── the client's id namespace ───────────────────────────────────────────────
# Two range checks the client applies to ids all over itself, and the reason a
# seatInfo carrying charaId 1 killed it:
#
#     0x00404FDF(id) -> 1  iff  0x10000  <= id <= 0x11FFFF
#     0x00404FBB(id) -> 1  iff  0xF0000  <= id <= 0xFFFFF
#                          or   0x1000000 <= id <= 0xFFFFFFFE
#
# and the predicate built on them, 0x00404FF9, which is called from 38 places:
#
#     if 0x404FDF(id): return id >> 16
#     return 0x11 if not 0x404FBB(id) else 0
#
# In the lesson-start path at 0x0083F48D the caller does `test ax, ax; je` and
# only the zero answer skips the block that follows — a block which dereferences
# a global smart pointer that nothing in the binary ever fills (0xE361A4; its
# only three references are the lazy init, the getter and the atexit destructor).
# So for ids outside 0xF0000-0xFFFFF and below 0x1000000 that block is entered
# and reads through null, which is exactly the page fault on 0x000000A0.
#
# ⚠️ This says the ranges exist and which one avoids the fault. It does not say
# what the classes *mean*, and it does not prove that the original's charaIds
# were large — only that this server's charaId 1 lands in a class the lesson
# scene cannot handle. See the probe knob above.
ID_SAFE_LOW = 0x0100_0000


def classroom_of(in_class: int) -> int:
    """Which map this player's lessons happen in."""
    return curriculum.CLASSROOM[in_class % len(curriculum.CLASSROOM)]


class Bell:
    """Per-session bell state.

    Nothing here is saved. A bell is a thing that happened at a moment, and a
    player who was logged out when it rang did not miss anything they can be
    given later.

    ``poll`` is edge-triggered against the wall clock rather than scheduled,
    because the server has no timer of its own: it wakes when a packet arrives,
    and the client's timesync arrives every thirty seconds. That sets the
    resolution — a bell can be up to one timesync late, never early. Fifteen
    minutes between lessons and five minutes of warning leave room for that; if
    the client turns out to care about the exact second, this becomes an
    asyncio task and the drain goes away.
    """

    def __init__(self) -> None:
        # The slot each bell was last rung *for*, so that a bell rings once per
        # lesson however often poll is called. None = nothing rung yet, which is
        # not the same as 0: slot 0 is a real slot.
        self.pre_rung: datetime | None = None
        self.start_rung: datetime | None = None
        # When the 本鈴 actually went out, and for which subject. This and not
        # the slot boundary is what admit() measures against: the invitation is
        # what opens the door, so a bell that left 25 seconds late gives the
        # player 25 seconds later a door, and a bell that never rang leaves no
        # door at all. It also makes a hand-rung bell a real one, which the
        # boundary version did not — /bell ready in the middle of a period was
        # refused as 「already started」 by a rule that had nothing to do with it.
        self.rang_at: datetime | None = None
        self.rang_subject = -1
        # Which lesson the player is currently sitting in, if any.
        self.in_lesson: datetime | None = None
        self.subject = -1

    def poll(
        self, when: datetime | None = None, *, admits: bool = True
    ) -> list[tuple[str, int]]:
        """Which bells are owed, as ``(kind, subjectId)`` in the order to send.

        ``kind`` is "pre" for 予鈴, "start" for 本鈴, and "skip" for a 本鈴 that
        is due but must not go out — see ``admits``.

        ``admits`` is whether this player could actually be let in right now.
        Ringing anyway is not free, and not merely untidy:

          0x6000 makes the client tear its scene down (0x4003) and then ask to
          come in (0x6001) **by itself** — there is no prompt and no button, so
          the player cannot decline. If admit() then refuses, the 0x6003 that
          says so makes the client close the connection. A bell rung at someone
          standing outside their classroom therefore logs them out, every
          fifteen minutes, with nothing they can do about it.

        So the condition is checked *before* the invitation goes out rather than
        after it comes back. The caller passes what it knows; a False only
        suppresses the 本鈴, never the 予鈴, because the 予鈴 is exactly the
        warning that sends a player to the right room in time.

        ⚠️ This is an inference, not something read off the wire: the original
        server cannot have rung 本鈴 at players in corridors either, or every
        one of them would have been disconnected on the quarter hour.

        ✅ The alternative that used to be recorded here — that it did ring, and
        that what the client disliked was our invented reason=0 — has been
        tested and does not hold. See NG_PROBE.
        """
        now = when or datetime.now()
        owed: list[tuple[str, int]] = []

        begins, subject = curriculum.next_lesson(now)
        if now >= begins - timedelta(minutes=curriculum.PRE_BELL_MINUTES):
            if self.pre_rung != begins:
                self.pre_rung = begins
                owed.append(("pre", subject))

        # The 本鈴 is for the lesson that is *in session*, not the next one, and
        # its start is where slot_start already points.
        started = curriculum.slot_start(now)
        if self.start_rung != started:
            # Mark the slot either way, so a suppressed bell is skipped once
            # rather than reconsidered on every packet for fifteen minutes.
            self.start_rung = started
            current = curriculum.current_subject(now)
            if admits:
                # rang() is what opens the door; a bell that never went out must
                # not leave rang_at behind, or admit() would honour a door that
                # was never there.
                owed.append(("start", self.rang(current, now)))
            else:
                owed.append(("skip", current))
        return owed

    def rang(self, subject: int, when: datetime | None = None) -> int:
        """Note that the 本鈴 has just gone out. Returns the subject, for brevity.

        Called by whatever actually sends 0x6000 — the poll above, or a hand-rung
        one. Everything admit() decides hangs off this.
        """
        self.rang_at = when or datetime.now()
        self.rang_subject = subject
        return subject

    def prime(self, when: datetime | None = None) -> None:
        """Swallow the bells for the lesson already under way.

        Logging in at 14:53 must not ring the 14:45 本鈴 — that lesson began
        eight minutes ago and `p06_02` is explicit that there is no joining one
        in progress. Called once when a session reaches the world, so the first
        real bell a player hears is the next one.
        """
        now = when or datetime.now()
        self.start_rung = curriculum.slot_start(now)
        begins, _ = curriculum.next_lesson(now)
        if now >= begins - timedelta(minutes=curriculum.PRE_BELL_MINUTES):
            self.pre_rung = begins

    def admit(
        self,
        map_id: int,
        in_class: int,
        when: datetime | None = None,
        *,
        neurotic: bool = False,
    ) -> int | None:
        """Let this player into the lesson now starting, or say why not.

        Returns None on success — three of `p06_02`'s four conditions:
        「あなたが在籍しているクラスの教室で」, 「授業の途中から参加すること
        はできません」, and ノイローゼ's 「学業に参加できなくなります」. The
        fourth, the 授業の有無 option, lives in the client and never reaches
        here.

        ``neurotic`` rather than a whole AbilitySheet: the only thing this rule
        reads is one boolean, and lesson.py has no other reason to know what a
        体調 is. Whoever calls it must suppress the 本鈴 on the same condition —
        see Bell.poll for why refusing after the bell costs the connection.
        """
        now = when or datetime.now()
        if map_id != classroom_of(in_class):
            return REASON_NOT_IN_CLASSROOM
        if neurotic:
            return REASON_NEUROSIS
        if self.rang_at is None or now - self.rang_at > timedelta(seconds=GRACE_SECONDS):
            return REASON_ALREADY_STARTED
        self.in_lesson = self.rang_at
        self.subject = self.rang_subject
        return None


def before_lesson_start_params(subject: int) -> bytes:
    """MsgSvNotifyBeforeLessonStart. One u16, and it names the subject."""
    return subject.to_bytes(2, "big")


# ── 先生の台詞 ──────────────────────────────────────────────────────────────
# `lesson_npc_sentence.bin` holds 161 lines whose keys run 0…202 with gaps: 23
# consecutive keys per teacher, then a jump to the next multiple of thirty. Each
# teacher's twenty-three sit in the same order, so a line is
# ``teacherId * SENTENCE_STRIDE + offset`` and the offsets below are that order,
# read off the records' own names.
#
# `lesson_npc.bin` says the same thing from the other side: every teacher record
# carries its own twenty-three keys, and 8:1 汎用先生（女）'s list starts at 30
# where `lesson_npc_sentence` key 30 is 「先生女開始台詞１」. Seven for seven.
#
# The block is also the clearest statement of the lesson loop that exists
# anywhere, `p06_02` included — it names every beat the server has to drive:
#
#   開始 → (次出題前 → 評価前 → 高/並/低評価) × 10 → 全問正解 or 終了
#
# 評価前 is 「今の問題の正答率は……$00か。」, so `$00` is a substitution the
# client fills — which is why the correct-answer rate is not in the sentence and
# has to reach it some other way.
SENTENCE_STRIDE = 30
WORDS_START = (0, 1)          # 開始台詞１／２
WORDS_BEFORE_RESULT = 2       # 評価前台詞
WORDS_GOOD = (3, 4)           # 高評価台詞
WORDS_FAIR = (5, 6)           # 並評価台詞
WORDS_POOR = (7, 8)           # 低評価台詞
WORDS_NEXT_QUESTION = 9       # 次出題前台詞
WORDS_PERFECT = (10, 11)      # 全問正解時台詞
WORDS_END = (12, 13)          # 終了台詞
WORDS_EXAM_START = (14, 15, 16, 17, 18)   # 試験開始台詞、五つ
WORDS_EXAM_LEAVE = (19, 20)   # 試験途中退出時台詞
WORDS_EXAM_END = (21, 22)     # 試験終了台詞


def words(subject: int, offset: int) -> int:
    """A `lesson_npc_sentence` key for the teacher who takes this subject."""
    return curriculum.SUBJECT_TEACHER[subject] * SENTENCE_STRIDE + offset


# ── 0x6100 MsgSvNotifyLessonStart ───────────────────────────────────────────
# Deserializer 0x008E34F0, read slot by slot. The seat array lives at struct
# +0x0C with a stride of 0x54 and its count at +0x300, which makes room for
# exactly (0x300 - 0x0C) / 0x54 = 9 entries.
#
# Nine is a **view, not a roster**. `p06_02` gives two different numbers and they
# answer two different questions: 「約１００人までの生徒が一度に授業を受けられ
# ますが、画面に表示されるのはあなたを含めた周囲の９人までです」— up to a
# hundred sit the lesson, nine get drawn. So this array is who the client should
# put on screen around the player, and the class can be far larger than it.
#
# Buffer and manual agree on the nine, unlike the 通知表's forty-row one, so nine
# is nine. What has no number anywhere is a *minimum*: nothing in the manual and
# nothing in `error_message.bin`'s 965 strings gates a lesson on how many are
# present, and all 965 were decoded and searched. One student alone is a lesson.
# The only thing that goes hollow is the お助けスキル set — 助けてコール asks the
# students around you, そっと応援 and ティーチング help somebody else — and that
# is an effect landing on nobody, not a door being shut.
MAX_SEATS = 9

# Each name is copied by the unchecked fixed reader 0xA49610 into a 12-byte slot
# (+0x08 and +0x16 inside the seat). The count on the wire is what it copies, so
# it has to include the terminator and stay inside twelve.
SEAT_NAME_LEN = 12


def seat_params(
    seat_id: int,
    chara_id: int,
    family_name: bytes,
    first_name: bytes,
    sex: int,
    test_lv: int,
    stress: int,
    question_count: int,
    correct_count: int,
    looks: "list[int]",
    accessory: "list[int]",
) -> bytes:
    """One seatInfo. Also the whole body of 0x6101 MsgSvNotifyLessonJoin.

    ``questionCount`` / ``correctAnswerCount`` are the subject's running totals
    and not this period's — `p06_02` is explicit: 「その授業時間内の正解率では
    なく、科目の通算正解率となります」.
    """
    out = bytearray()
    out += struct.pack(">BI", seat_id & 0xFF, chara_id)
    for raw in (family_name, first_name):
        text = raw.split(b"\x00", 1)[0][: SEAT_NAME_LEN - 1] + b"\x00"
        out += struct.pack(">H", len(text)) + text
    out += struct.pack(">HHB", sex, test_lv, stress & 0xFF)
    out += struct.pack(">II", question_count, correct_count)
    for value in list(looks)[:9] + [0] * max(0, 9 - len(looks)):
        out += struct.pack(">H", value)
    for value in list(accessory)[:7] + [0] * max(0, 7 - len(accessory)):
        out += struct.pack(">H", value)
    return bytes(out)


def start_params(
    subject: int,
    seats: "list[bytes]",
    speech_end_time: int,
    start_words: int | None = None,
    lunch_count: int = 0,
) -> bytes:
    """MsgSvNotifyLessonStart.

        u16 startWordsId
        i8  subjectId          (vt+0x1C — signed, and the only signed field here)
        u8  lunchCount
        u16 count; seatInfo × count
        i64 speechEndTime      (vt+0x10)

    ⚠️ INVENTED: `lunchCount` and `speechEndTime`.

    `lunchCount` is a u8 with no table behind it; 早弁 spends an 「お弁当」 item,
    so a count of them is the obvious reading and zero is the honest value while
    no inventory exists.

    `speechEndTime` is signed 64-bit, which in this protocol means one thing:
    the timesync's clock, milliseconds in the client's own frame since it
    started. The server can only name a moment in that frame by way of the
    mapping the timesync already maintains — see _Session.client_now — so that
    is what it is given. If the client instead wants a duration, this is off by
    the whole elapsed time and the teacher's opening line will end the moment it
    begins.
    """
    if start_words is None:
        start_words = words(subject, WORDS_START[0])
    kept = seats[:MAX_SEATS]
    out = bytearray()
    out += struct.pack(">HbB", start_words, subject, lunch_count & 0xFF)
    out += struct.pack(">H", len(kept))
    for seat in kept:
        out += seat
    out += struct.pack(">q", speech_end_time)
    return bytes(out)


def ng_params(reason: int) -> bytes:
    """MsgSvNgLessonReady / MsgSvNotifyLessonStartImpossible. One u8."""
    return reason.to_bytes(1, "big")


# ── 出題と採点 ──────────────────────────────────────────────────────────────
# `p06_02` lays the loop out step by step, and it matches the five messages the
# protocol has exactly one for one:
#
#   1）先生から問題が出題されます。…キャラクターがひらめいて選択肢が絞り込まれる
#      ことがあります                     → 0x6103, flashId[]/flashChoiceId[]
#   2）答えを選択し左クリックで解答します。一度解答すると変更できません
#                                          → 0x6105 (client)
#   3）残り時間が０になると正解が発表され、○・×が生徒ごとに表示されます
#                                          → 0x6106, one per student
#   4）先生が今回の問題についての正解率と感想を述べます
#                                          → 0x6104 gradingWordsId
#   5）1）〜4）を繰り返して１０問終了すると、結果発表になります
#                                          → 0x6102 resultInfo
#
# ⭐ Step 3 answers something the 評価前台詞 had left open. That line is
# 「今の問題の正答率は……$00か。」, `$00` is a client-side substitution, and 0x6104
# carries nothing but a sentence id — so the rate had to reach the client some
# other way. It already has: the client has seen one 0x6106 per student and can
# count them. There is no rate field because there does not need to be one.
#
# Step 3 also says *when*: at zero, not on the answer. With one student in the
# room those differ only in that the reveal waits, and the reveal is what the
# manual describes, so that is what happens here — see Lesson.pump.

# 「１回の授業につき１０問出題されます」 (`p06_02`).
QUESTIONS_PER_LESSON = 10

# ⚠️ INVENTED, all three, and they are pacing rather than rules.
#
# `p06_02` puts a 「残り時間」 on the panel and says to answer before it reaches
# zero, without ever saying what it starts at; nothing in `lesson.bin`,
# `quiz_level.bin` or `error_message.bin` holds a duration either. Twenty seconds
# is a guess that leaves time to read four choices.
#
# GRADING_SECONDS is a gap this server has to fill because it drives beats the
# client used to be driven through: how long the 評価 takes before the next
# question goes out. The original's was however long its own animation ran.
#
# The opening pause is not here — it is PROBE["speech_ms"], because 0x6100 has to
# tell the client the same number and one knob for both cannot drift.
ANSWER_SECONDS = 20
GRADING_SECONDS = 6

# Where 高評価 / 並評価 / 低評価 divide, on **this question's** class-wide rate —
# 「先生が今回の問題についての正解率と感想を述べます」, so it is the one question
# and not the 通算 figure. INVENTED, and with a single student in the room only
# the two ends are reachable at all: one student's rate is 0% or 100%.
GRADING_GOOD = 0.75
GRADING_FAIR = 0.40

# tmn::NUM_OF_CHARA_ABILITY, and `chara_ability_type.bin` has the same six:
# 文系 理系 芸術 雑学 運動 スタミナ.
ABILITIES = 6
# (0xE6 - 0x26) / 6 — the client's item buffer in 0x6102. A capacity, not a count.
MAX_ITEMS = 32

# A ruler for the 結果発表, set by `/quiz ab` and nothing else. None means send
# the two ability arrays equal, which is what a server with no 能力 subsystem
# honestly reports; a list overrides one side of that so the screen has to draw
# something. These are INVENTED measuring values, and unlike `/ab`'s sheet they
# are never written to a save — the point is to find out *whether* 0x6102's
# twelve u16 reach the screen at all, which nothing recorded so far answers.
#
# ⚠️ Module-level like ANSWER_SECONDS, so it is server-wide and survives until
# cleared. Clear it once the screen has been read: a later round finding these
# values still set would read them as a lesson that raised an ability.
END_ABILITY_AFTER: "list[int] | None" = None
END_ABILITY_BEFORE: "list[int] | None" = None

# The default ruler, chosen so one screenshot is readable under any of the
# three ways the screen could draw these (lesson 3). ceil(値/250) maps them to
# 1 2 4 8 16 32, so the row a value landed in is recoverable if the screen
# prints the レベル; the values themselves are equally distinct if it prints the
# number; and against a `before` of zeros the difference is the value again.
# All six stay ≤ 10000, the range where 2.30's レベル rule was shown to hold.
END_ABILITY_RULER = (250, 500, 1000, 2000, 4000, 8000)


# ── 能力増減 ────────────────────────────────────────────────────────────────
# 「授業に参加することにより、科目に応じて能力パラメータが増減します」(`p06_02`).
# *Which* abilities is read off `lesson.bin` — curriculum.SUBJECT_ABILITY. *How
# much* is nowhere: no table holds a step, and the client cannot hold one either,
# because it never computes an ability, it only draws the two arrays 0x6102 sends
# it. So the number below is INVENTED, and it is invented in the one unit the
# screen has already settled.
#
# abilityParam is 8.8 fixed point — レベル = (値 >> 8) + 1, and the bar under the
# number is (値 & 0xFF) / 256. So the honest way to state a step is in 256ths of
# a level, and a step is legible on screen exactly when it moves the bar.
#
# ABILITY_STEP = 64 is a quarter of a level **per slot**, so a perfect lesson
# raises each of a subject's two abilities by a quarter — or one ability by a
# half, for the four subjects that name the same one twice. Against 課程修了's
# 「必要な出席回数 7 / 40 / 100」 that puts a first 課程 around レベル 2 and a
# third somewhere near レベル 25. Nothing verifies that shape; 64 is chosen so a
# single lesson visibly moves the bar — a step too small to see is a step nobody
# can check — while a whole level still costs several lessons.
#
# 増減, not 増: the manual says the value can go either way, so the step is
# signed by how the lesson went. `2 * rate - 1` is the cheapest reading of that
# — all ten right is +ABILITY_STEP, all ten wrong is -ABILITY_STEP, and five is
# nothing. It is this lesson's own rate and not the 通算 one, matching the same
# 「その授業での成績」 the manual uses for ご褒美.
#
# ⚠️ Not modelled and deliberately so: the biorhythm the third slot names, ご褒美
# items, and any dependence on 試験レベル or on how far the ability already is.
ABILITY_STEP = 64


def ability_delta(subject: int, right: int, asked: int) -> "list[int]":
    """One lesson's 能力増減, six values in `chara_ability_type` key order.

    INVENTED; see ABILITY_STEP for what part of it is and is not recovered. A
    lesson that asked nothing moves nothing, which is what walking out mid-period
    already does everywhere else in this server.
    """
    delta = [0] * ABILITIES
    if asked <= 0:
        return delta
    step = round(ABILITY_STEP * (2 * right / asked - 1))
    for index in curriculum.SUBJECT_ABILITY[subject % len(curriculum.SUBJECT_ABILITY)]:
        delta[index] += step
    return delta


def question_params(
    quiz_type: int,
    quiz_lv: int,
    quiz_id: int,
    choice_ids: "list[int]",
    start_time: int,
    end_time: int,
    flash_ids: "list[int]" | None = None,
    flash_choice_ids: "list[int]" | None = None,
) -> bytes:
    """MsgSvNotifyLessonQuestionStart. Deserializer 0x008E4AD0, slot by slot.

        u16 quizType
        u16 quizLv
        u16 quizId
        u16 n; u8  × n   choiceId
        u16 m; u32 × m   flashId
        u16 k; u8  × k   flashChoiceId
        i64 startTime                (vt+0x10, same signed 64-bit as speechEndTime)
        i64 endTime

    The three counts come *before* their arrays on the wire but the arrays live
    *before* the counts in the struct, which is what makes the capacities
    readable: choiceId is bytes +0x0E…+0x11 with its count at +0x12, so **four**;
    flashId is +0x14 stride 4 with its count at +0x38, so **nine**;
    flashChoiceId is +0x3A…+0x3D with its count at +0x3E, so four again.

    ⚠️ Nine is the same nine as the seat list, so flashId is a list of charaIds
    and not of choices — 「キャラクターがひらめいて選択肢が絞り込まれる」, the
    characters who had the flash. Both flash arrays go out empty here: ひらめき
    belongs to the お助けスキル set and none of it is modelled.
    """
    out = bytearray(struct.pack(">HHH", quiz_type, quiz_lv, quiz_id))
    kept = list(choice_ids)[:4]
    out += struct.pack(">H", len(kept)) + bytes(value & 0xFF for value in kept)
    flashes = list(flash_ids or [])[:MAX_SEATS]
    out += struct.pack(">H", len(flashes))
    for chara_id in flashes:
        out += struct.pack(">I", chara_id)
    narrowed = list(flash_choice_ids or [])[:4]
    out += struct.pack(">H", len(narrowed)) + bytes(v & 0xFF for v in narrowed)
    out += struct.pack(">qq", start_time, end_time)
    return bytes(out)


def answer_params(sender_id: int, correct: bool) -> bytes:
    """MsgSvNotifyLessonAnswer: u32 senderId, u8 correctAnswerflg. 0x009BB390.

    One per student, and it is both the ○/× over each desk and — counted — the
    class rate the 評価前台詞 substitutes into `$00`.
    """
    return struct.pack(">IB", sender_id, 1 if correct else 0)


def question_end_params(grading_words: int) -> bytes:
    """MsgSvNotifyLessonQuestionEnd: one u16 gradingWordsId. 0x008DB8E0."""
    return struct.pack(">H", grading_words)


def end_params(
    end_words: int,
    attendance_count: int,
    stress: int = 0,
    condition: int = 0,
    ability: "list[int]" | None = None,
    before_ability: "list[int]" | None = None,
    items: "list[tuple[int, int, int]]" | None = None,
) -> bytes:
    """MsgSvNotifyLessonEnd, the 結果発表. Deserializer 0x008E4520.

        u16 endWordsId
        u32 attendanceCount
        u8  stress
        i8  condition                (vt+0x1C — signed, like 0x6100's subjectId)
        u16 × 6  ability.abilityParam         (tmn::NUM_OF_CHARA_ABILITY)
        u16 × 6  beforeAblity.abilityParam
        u16 count; { u16 itemId.categoryId, u16 itemId.id, u8 param.count } × count

    The item array sits at +0x26 with a stride of 6 and its count at +0xE6, so
    the client can hold 32 — a capacity, not a number, and this sends none.

    ⚠️ INVENTED / not modelled, in descending order of how visible each is:

    * ``ability`` and ``before_ability``. 「授業に参加することにより、科目に応じて
      能力パラメータが増減します」 (`p06_02`) and this message is where that
      lands. *Which* abilities move is read off `lesson.bin`
      (curriculum.SUBJECT_ABILITY); *how much* is invented, in the 256ths the
      screen turned out to count in — see ABILITY_STEP and ability_delta.

      ⚠️ The two arrays are not two pieces of data. ``before_ability`` is where
      the bar starts and ``ability`` is where it ends, and the client **animates
      between them**, so a screenshot taken mid-climb reads the wrong number.
      Send them equal when the point is to read a value off the screen; that is
      what `/quiz ab still` is for.
    * ``stress`` and ``condition``. ストレス／ノイローゼ is a whole subsystem
      (`p06_02`) with an entry condition and a set of places that reduce it, and
      none of it exists; zero is the value of a thing that is never raised.
    * ``items``. ご褒美 「その授業での成績によっては、ご褒美のアイテムが手に入る
      こともあります」 — there is no inventory to put one in.

    ``attendance_count`` and ``end_words`` are the two that are real.
    """
    out = bytearray(struct.pack(">HIBb", end_words, attendance_count,
                                stress & 0xFF, max(-128, min(127, condition))))
    for values in (ability, before_ability):
        row = list(values or [])[:ABILITIES]
        row += [0] * (ABILITIES - len(row))
        for value in row:
            out += struct.pack(">H", value)
    rewards = list(items or [])[:MAX_ITEMS]
    out += struct.pack(">H", len(rewards))
    for category_id, item_id, quantity in rewards:
        out += struct.pack(">HHB", category_id, item_id, quantity & 0xFF)
    return bytes(out)


class Lesson:
    """One period in progress, for one session: the ten questions and the tally.

    The bells in ``Bell`` decide *whether* a lesson happens; this is what
    happens during it. It is a small clocked state machine rather than a
    request/response handler because four of its five messages are pushes the
    client never asks for — 0x6105 is the only thing it sends, and only if the
    player answers at all.

    ``pump`` is therefore the whole thing: it is called with the current time,
    returns whatever is now due, and the caller sends it. Nothing here is saved;
    a period that a disconnect interrupts is a period that did not happen, which
    is also what walking out of the room does in the original.
    """

    # Phases, in order. Each ends at ``self.due``.
    OPENING = "opening"    # the teacher's 開始台詞 is running
    ASKING = "asking"      # a question is out and 残り時間 is counting down
    GRADING = "grading"    # 正解 revealed, 評価 being said
    OVER = "over"

    def __init__(self, subject: int, chara_id: int,
                 now: datetime | None = None) -> None:
        self.subject = subject
        self.chara_id = chara_id
        self.phase = self.OPENING
        self.due = (now or datetime.now()) + timedelta(
            seconds=max(0, int(PROBE["speech_ms"])) / 1000
        )
        # 1-based, and it is what 0x6105's questionNo is checked against: a stale
        # answer to the previous question must not count for this one.
        self.question_no = 0
        self.question = None      # quiz.Question, while one is out
        self.reported: int | None = None
        self.asked = 0
        self.right = 0
        # What 精神集中 or ティーチング has left on the table, or None for "all of
        # them". Per question: 「既に選択肢が絞られていますので…効果がありません」
        # (`error_message.bin` 546, 558) is a rule about *this* question, and the
        # next one starts with a full list. See lesson_skill.
        self.narrowed: "list[int] | None" = None
        # 「お弁当」 in hand for 早弁, and spent as they are used. It is the same
        # number 0x6100 went out with, so the buttons the client drew match what
        # this will allow. Nothing outlives the period — there is no inventory.
        self.lunch = max(0, int(PROBE["lunch"]))

    # ── the client's one contribution ───────────────────────────────────────

    def take_answer(self, question_no: int, choice_id: int) -> bool:
        """MsgClCastLessonAnswer. True if it was taken.

        Refused when it names the wrong question, when nothing is out, or when
        one has already been given — 「一度解答すると変更できませんので慎重に
        答えを選びましょう」 makes the last of those a rule and not just
        defensiveness. There is a MsgSvErrorLessonAnswer (0x6107, one u8) for
        saying so, but what it draws is unknown and a silent refusal costs the
        player nothing, so the caller only logs.
        """
        if self.phase != self.ASKING or self.question is None:
            return False
        if self.reported is not None:
            return False
        # ⚠️ Whether the client counts questions from one or from zero is not
        # settled — nothing on the wire has said, and the deserializer only says
        # it is a u8. Both are accepted, because the cost of guessing wrong is a
        # lesson in which every answer is silently refused and every question
        # marked wrong, which looks like broken marking rather than a mismatched
        # convention. The cost of being lenient is much smaller: the only thing
        # it lets through is an answer to the previous question arriving during
        # this one, and a player can only click once per question anyway.
        #
        # Which one it is will be obvious the first time this runs against a
        # client, because the log line below prints what arrived.
        if question_no not in (self.question_no, self.question_no - 1):
            return False
        self.reported = choice_id
        return True

    def would_be_right(self) -> bool:
        """How the answer on the table will be marked when the timer ends.

        For the log only. The mark itself is computed in ``pump`` at the moment
        it goes out, so that this can never be the thing that decided it.
        """
        return (
            self.question is not None
            and self.reported is not None
            and self.question.judge(self.reported)
        )

    # ── the clock ───────────────────────────────────────────────────────────

    def pump(self, now: datetime, client_now_ms: int,
             rng=None) -> "list[tuple[int, bytes]]":
        """Whatever is due, as ``(msgType, params)`` in the order to send.

        ``client_now_ms`` is the client's own clock — 0x6103's startTime and
        endTime live in the same frame as 0x6100's speechEndTime, so they can
        only be named through the timesync mapping. See _Session.client_now.

        Returns [] when nothing is due yet, which is the common case: this gets
        called on every wake.
        """
        import quiz  # local: only lessons need the bank, and only while one runs

        if self.phase == self.OVER or now < self.due:
            return []

        if self.phase == self.GRADING or self.phase == self.OPENING:
            if self.question_no >= QUESTIONS_PER_LESSON:
                self.phase = self.OVER
                return []
            question = quiz.pick(self.subject, rng)
            if question is None:
                # No bank, or an empty category. Ending the period is better
                # than asking a quizId the client cannot resolve.
                self.phase = self.OVER
                return []
            self.question = question
            self.question_no += 1
            self.reported = None
            self.narrowed = None
            self.phase = self.ASKING
            self.due = now + timedelta(seconds=ANSWER_SECONDS)
            start_ms = client_now_ms
            return [(
                MSG_SV_NOTIFY_LESSON_QUESTION_START,
                question_params(
                    question.quiz_type,
                    question.level,
                    question.quiz_id,
                    question.choice_ids,
                    start_ms,
                    start_ms + ANSWER_SECONDS * 1000,
                ),
            )]

        # ASKING, and 残り時間 has reached zero: reveal, then grade.
        question = self.question
        correct = question is not None and self.reported is not None \
            and question.judge(self.reported)
        self.asked += 1
        self.right += 1 if correct else 0
        self.phase = self.GRADING
        self.due = now + timedelta(seconds=GRADING_SECONDS)
        return [
            (MSG_SV_NOTIFY_LESSON_ANSWER, answer_params(self.chara_id, correct)),
            (MSG_SV_NOTIFY_LESSON_QUESTION_END,
             question_end_params(self.grading_words(correct, rng))),
        ]

    def grading_words(self, correct: bool, rng=None) -> int:
        """Which 評価台詞 the teacher uses for the question just marked.

        On this question's class-wide rate, which with one student is 0% or 100%.
        Each band has two lines in `lesson_npc_sentence` and the choice between
        them is arbitrary, so it is random.
        """
        import random

        rng = rng or random
        rate = 1.0 if correct else 0.0
        if rate >= GRADING_GOOD:
            band = WORDS_GOOD
        elif rate >= GRADING_FAIR:
            band = WORDS_FAIR
        else:
            band = WORDS_POOR
        return words(self.subject, rng.choice(band))

    def end_words(self, rng=None) -> int:
        """終了台詞, or 全問正解時台詞 if the player got every one.

        `lesson_npc_sentence` keeps those as separate pairs, which is the only
        statement anywhere that a perfect round is remarked on at all.
        """
        import random

        rng = rng or random
        band = WORDS_PERFECT if self.right == QUESTIONS_PER_LESSON else WORDS_END
        return words(self.subject, rng.choice(band))

    def finished(self) -> bool:
        return self.phase == self.OVER

    def summary(self) -> str:
        return f"{self.right}/{self.asked}"
