"""授業: the bells, and who is let into the room when they ring.

`curriculum.py` owns the school clock — which subject is in session and when the
next one begins. This owns what the server *does* about it. The two are split
because the clock is recovered and this is policy: `class_schedule.bin` says what
is taught at 15:00 on a 火曜, and nothing anywhere says what the server should
send to a player standing in the wrong room when it does.

    0x6005 MsgSvNotifyBeforeLessonStart   u16 type          — 予鈴, five minutes out
    0x6000 MsgSvNotifyLessonReady         (empty)           — 本鈴
    0x6001 MsgClRequestLessonReady        (empty)           — 「出ます」
    0x6002 MsgSvOkLessonReady             (empty)
    0x6003 MsgSvNgLessonReady             u8 reason
    0x6004 MsgSvNotifyLessonStartImpossible u8 reason
    0x6100 MsgSvNotifyLessonStart         counted, 66B entries — the seat list

Six of the eight bodies are empty or a single byte, and `0x6001` — the client
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

⚠️ What happens after an Ok has not been seen. The client presumably then waits
for 0x6100 MsgSvNotifyLessonStart and its seat list, which this file does not
build yet.
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
# ⚠️ INVENTED, all of them. MsgSvNgLessonReady and NotifyLessonStartImpossible
# each carry one u8 the dump calls `reason`. `error_message.bin`'s 965 strings
# were decoded and searched: it has 授業-adjacent entries, but every one of them
# is an お助けスキル gate on 試験レベル (545/549/553/559) and none is a refusal to
# let anyone into a room. So these are not indices into that table, and the
# client is presumably mapping them to strings from somewhere else. Until one is
# seen on screen the numbers mean what this file says and nothing more.
REASON_NOT_IN_CLASSROOM = 0  # 自分の組の教室にいない
REASON_ALREADY_STARTED = 1   # 途中から参加することはできません (`p06_02`)
REASON_LESSON_OFF = 2        # オプション →「授業の有無」が OFF
REASON_NEUROSIS = 3          # ノイローゼ (`p06_02`: 参加できなくなります)

# What a refusal looks like from the player's side, measured: MsgSvNgLessonReady
# with reason=0 put up a システムメッセージ reading 「授業起動失敗」 and dropped
# the client back out of 授業モード. Whether the other reasons draw anything
# different is untested — one string may well cover all of them, since the
# client had already torn the scene down by the time it asked.


# How long after the bell a 「出ます」 is still taken. The manual bans joining a
# lesson in progress and says nothing about how much of a moment the client gets
# to answer in; this is the round trip plus the up-to-30s the timesync-driven
# bell can be late by, which is a fact about this server and not the original.
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
    "speech_ms": 600_000,
    "words": -1,       # -1 = the subject's own 開始台詞
    "charaid": -1,     # -1 = the session's own; see the id namespace below
    "testlv": -1,      # -1 = the 通知表's own 試験レベル
}

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
#                          or   0x1000000 <= id <= 0xFFFFFFFD
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

    def poll(self, when: datetime | None = None) -> list[tuple[str, int]]:
        """Which bells are owed, as ``(kind, subjectId)`` in the order to send.

        ``kind`` is "pre" for 予鈴 and "start" for 本鈴.
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
            self.start_rung = started
            owed.append(("start", self.rang(curriculum.current_subject(now), now)))
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

    def admit(self, map_id: int, in_class: int, when: datetime | None = None) -> int | None:
        """Let this player into the lesson now starting, or say why not.

        Returns None on success — `p06_02`'s two conditions and no more:
        「あなたが在籍しているクラスの教室で」 and 「授業の途中から参加すること
        はできません」. The other two reasons above belong to state this server
        does not keep yet (the 授業の有無 option lives in the client, ストレス is
        not tracked), so nothing returns them.
        """
        now = when or datetime.now()
        if map_id != classroom_of(in_class):
            return REASON_NOT_IN_CLASSROOM
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
