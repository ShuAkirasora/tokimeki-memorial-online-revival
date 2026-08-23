"""経歴: the 「ゲーム実績」 card, and the 過去の実績 list under it.

Two exchanges, and between them the whole of the 経歴 screen
(メインメニュー →「生徒情報」→「経歴」, and another player's copy of it through
the PC 交流メニュー's 「経歴を見る」):

    0x4315 MsgClQueryCharaCareer      -> 0x4316 MsgSvResultCharaCareer
                                      -> 0x4317 MsgSvErrorCharaCareer   (u8 reason)
    0x4318 MsgClQueryCharaCareerList  -> 0x4319 MsgSvResultCharaCareerList (u16 nNum)
                                      -> 0x431A MsgSvNotifyCharaCareerList (rows)

Both queries carry one u32 charaId, because a player can look at somebody
else's card -- which is what 経歴公開 (options.py's fourth flag) is for. That
flag is this screen's gate exactly as 通知表公開 is 0x430C's, and until this
module existed it had no reader at all: 0x4315 was answered with a flat refusal
out of mps_session's FIXED_REPLIES, so a character who turned 経歴公開 ON was
refused anyway, for lack of data rather than for lack of permission.

⭐ THE CARD'S LAYOUT IS RESTORED, WHAT GOES IN IT IS NOT. The eight fields and
their widths come out of Input_MsgSvResultCharaCareer::deserialize (0x8CF030),
which reads, in this order and through these slots of the stream's vtable:

    u16   inClass          vt+0x28 -> +0x04
    char  familyName[11]   0xA49610, count 11 -> +0x06
    char  firstName[11]    0xA49610, count 11 -> +0x11
    u16   title            vt+0x28 -> +0x1C
    i32   attendCount      vt+0x14 -> +0x20
    i64   attendTime       vt+0x10 -> +0x28
    u32   attendanceCount  vt+0x24 -> +0x30
    u16   learningSkill    vt+0x28 -> +0x34

2+11+11+2+4+8+4+2 = 44 bytes. The names are the client's own, printed by the
message's dump at 0x8CF200. The first three fields are the same header
MsgSvResultScoreCard opens with, which is why 0x430D and 0x4316 look alike.

⭐⭐ WHICH NUMBER DRAWS WHICH LINE was read off the screen, not matched up by
order, and the difference matters. The window has EIGHT rows and the card has
SIX numbers, so lining the two lists up top to bottom is off by one somewhere --
and it is: 「1期生として入学」 is not on this wire at all. The client fills that
from its own `period`, the one 0x0319 and 0x6501 carry.

    称号：           title              0 draws 「無し」 (its table has one row)
    Ａ組  <name>     inClass            zero-based, exactly as 0x430D's is
    1期生として入学   -- NOT ON THIS WIRE --
    登校回数：        attendCount
    累計登校時間：    attendTime         ⭐ the unit is HOURS; see ATTEND_TIME_UNIT
    授業出席数：      attendanceCount
    習得部活奥義：    learningSkill
    過去の実績        the 0x4318 list

⭐ All six at once, from one screenshot, by sending six values that are all
different -- that is what PROBE below is for, and why it takes six numbers
rather than being six separate knobs.

⭐ THAT MAKES FOUR OF THE SIX DERIVABLE RATHER THAN INVENTED. 登校 is not a
metaphor here -- it is MsgClRequestSchoolLogin, the message the client sends
when the player picks a character, and 下校 is MsgClRequestSchoolLogout. So
「登校回数」 is how many times that has happened and 「累計登校時間」 is how
long they added up to, both of which this server is the only thing that can
know. 「授業出席数」 is the 通知表's own attendance column summed over the eight
subjects -- the same numbers 0x430D already sends, so a second copy would be a
second answer. 「習得部活奥義」 is the length of the 部活奥義 list 0x4308 sends.
None of the four is stored twice and none is a constant.

⚠️ INVENTED: 称号 and 過去の実績. `designation.bin` has exactly one row and it
is the empty one, and `career.bin` has three, every one of them awarded by
something this server does not have -- two class elections and an exam ranking.
So the honest default for both is empty, and /career's grant is a knob of the
same kind as /kw and /cs: it opens the door so the wire can be tested, and it
says so.

⭐ attendTime's unit is MEASURED, not read off the label: the card went out
with a 7 in that field and the screen drew 「7時間」. The server stores seconds
and divides by ATTEND_TIME_UNIT on the way out. ⚠️ Only small values have been
sent -- the field is 64 bits wide and nothing has probed what a large one does.
"""

from __future__ import annotations

import struct

MSG_CL_QUERY_CHARA_CAREER = 0x4315
MSG_SV_RESULT_CHARA_CAREER = 0x4316
MSG_SV_ERROR_CHARA_CAREER = 0x4317
MSG_CL_QUERY_CHARA_CAREER_LIST = 0x4318
MSG_SV_RESULT_CHARA_CAREER_LIST = 0x4319
MSG_SV_NOTIFY_CHARA_CAREER_LIST = 0x431A

NAME_LEN = 11  # tmn::MAX_CHARA_FAMILYNAME + 1, same as characters.NAME_LEN

#: How many keys `career.bin` has. Three achievements; the client draws their
#: names out of its own copy of that table, so only the count belongs here.
#: All three are awarded by parts of the game this server does not run -- two
#: class elections and an exam ranking -- see the module docstring.
CAREER_COUNT = 3

#: The only key `designation.bin` has, and it is the empty one. A 称号 the
#: client cannot look up is not a 称号, so this is both the default and the
#: ceiling until that table grows, which it will not.
TITLE_NONE = 0
TITLE_COUNT = 1

#: Seconds per unit of the wire's attendTime: the field is in hours, measured
#: by sending a 7 and reading 「7時間」 back off the screen.
ATTEND_TIME_UNIT = 3600

#: How many rows one 0x431A may carry, and read the same way
#: club.CLUB_SKILL_LIST_PAGE was: the deserializer (0x8CF3C0) stores the row
#: count at +0x44 and the rows from +0x04 at two bytes each, so the array holds
#: exactly (0x44 - 4) / 2 == 32 and the count sits immediately behind it with no
#: bounds check. ⚠️ With CAREER_COUNT == 3 this can never be reached; it is here
#: because the shape was read, not because the limit is near.
CAREER_LIST_PAGE = 32


def career_exists(career_id: int) -> bool:
    """Is this a key `career.bin` actually has?"""
    return 0 <= career_id < CAREER_COUNT


#: One-shot ruler, armed by ``/career probe`` and consumed by the next card
#: this server builds: ``(inClass, title, attendCount, attendTime,
#: attendanceCount, learningSkill)``, the six numeric fields in wire order.
#:
#: ⭐ Six distinct numbers in one card is what settles all six screen lines in a
#: single screenshot, which is why this exists at all rather than six knobs.
#: ⚠️ It is consumed on use, so it restores itself; and it is module-wide rather
#: than per-session, which is fine for a ruler and would not be for a setting.
PROBE: "tuple[int, int, int, int, int, int] | None" = None


def take_probe() -> "tuple[int, int, int, int, int, int] | None":
    """The armed ruler, cleared. See PROBE."""
    global PROBE
    armed, PROBE = PROBE, None
    return armed


class Career:
    """One character's 経歴: what this server counts, and what it was given.

    Stored on the character record under "career" and rebuilt from that dict
    each time, the same arrangement as Romance, ScoreCard, AbilitySheet and
    GameOptions.

    ⚠️ Only the fields nothing else already knows live here. 授業出席数 and
    習得部活奥義 are read off the 通知表 and the 部活奥義 list when the card is
    built -- see ``params`` -- because a copy of a number is a number that can
    disagree with the original.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        # 登校回数: one per MsgClRequestSchoolLogin answered for this character.
        self.visits = max(0, int(saved.get("visits", 0)))
        # 累計登校時間, in seconds. Accumulated between 登校 and 下校, which
        # includes the disconnect path -- a player who pulls the plug has still
        # been at school for the time they were there.
        self.seconds = max(0, int(saved.get("seconds", 0)))
        # 称号. Nothing awards one; see TITLE_NONE.
        title = int(saved.get("title", TITLE_NONE))
        self.title = title if 0 <= title < TITLE_COUNT else TITLE_NONE
        # 過去の実績: `career.bin` keys, in the order 0x431A will send them. A
        # key the client's own table does not have is dropped rather than sent
        # on, the same treatment club.Membership gives キーワード ids.
        self.achievements: "list[int]" = []
        for value in saved.get("achievements") or ():
            try:
                career_id = int(value)
            except (TypeError, ValueError):
                continue
            if not career_exists(career_id):
                print(f"[career] {career_id} is not in career.bin, dropping")
                continue
            if career_id not in self.achievements:
                self.achievements.append(career_id)

    def to_json(self) -> dict:
        return {
            "visits": self.visits,
            "seconds": self.seconds,
            "title": self.title,
            "achievements": list(self.achievements),
        }

    # ── what the server counts ──────────────────────────────────────────────

    def arrive(self) -> int:
        """One 登校. Returns the new 登校回数."""
        self.visits += 1
        return self.visits

    def depart(self, seconds: float) -> int:
        """One 下校, however it happened. Returns the new total in seconds.

        Negative and absurd spans are dropped rather than clamped to something
        plausible: the only way to get one is a clock that moved, and a total
        that quietly absorbed it would be wrong in a way nothing could see.
        """
        span = int(seconds)
        if 0 < span < 366 * 24 * 3600:
            self.seconds += span
        return self.seconds

    def grant(self, career_id: int) -> bool:
        """Award one 実績. False for a key `career.bin` does not have.

        INVENTED that this happens at all, exactly as for club.grant_keyword and
        for the same reason: the three real ones come from class elections and
        an exam ranking, and this server holds neither.
        """
        if not career_exists(career_id):
            return False
        if career_id not in self.achievements:
            self.achievements.append(career_id)
        return True

    def revoke(self, career_id: int) -> bool:
        before = len(self.achievements)
        self.achievements = [k for k in self.achievements if k != career_id]
        return len(self.achievements) != before

    # ── the wire ────────────────────────────────────────────────────────────

    def params(
        self,
        family_name: bytes,
        first_name: bytes,
        in_class: int = 0,
        attendance_count: int = 0,
        learning_skill: int = 0,
    ) -> bytes:
        """A MsgSvResultCharaCareer body, 44 bytes. Deserializer 0x8CF030.

        ``attendance_count`` and ``learning_skill`` are passed in rather than
        stored: they belong to the 通知表 and the 部活奥義 list. See the class
        docstring.
        """
        armed = take_probe()
        if armed is not None:
            in_class, title, visits, attend_time, attendance_count, learning_skill = armed
        else:
            title = self.title
            visits = self.visits
            attend_time = self.seconds // ATTEND_TIME_UNIT
        out = struct.pack(">H", in_class & 0xFFFF)
        out += family_name.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        out += first_name.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        out += struct.pack(">H", title & 0xFFFF)
        out += struct.pack(">i", max(-0x80000000, min(0x7FFFFFFF, visits)))
        out += struct.pack(">q", attend_time)
        out += struct.pack(">I", attendance_count & 0xFFFFFFFF)
        out += struct.pack(">H", learning_skill & 0xFFFF)
        return out

    def rows(self, keys: "list[int] | None" = None) -> bytes:
        """0x431A's body: count u16 then one u16 per 実績."""
        keys = self.achievements if keys is None else keys
        return struct.pack(">H", len(keys)) + b"".join(
            struct.pack(">H", key) for key in keys
        )

    def row_pages(self) -> "list[bytes]":
        """The same body, split into messages the client's reader can hold.

        One page always, today: see CAREER_LIST_PAGE.
        """
        pages = []
        for start in range(0, max(len(self.achievements), 1), CAREER_LIST_PAGE):
            pages.append(self.rows(self.achievements[start:start + CAREER_LIST_PAGE]))
        return pages

    # ── for the log and the chat bar ────────────────────────────────────────

    def summary(self) -> str:
        return (f"登校{self.visits}回 {self.seconds // ATTEND_TIME_UNIT}時間 "
                f"称号{self.title} 実績{len(self.achievements)}")

    def lines(self, attendance_count: int = 0, learning_skill: int = 0) -> "list[str]":
        return [
            f"称号：{self.title}",
            f"登校回数 {self.visits}",
            f"累計登校時間：{self.seconds // ATTEND_TIME_UNIT}時間"
            f" ({self.seconds}秒)",
            f"授業出席数 {attendance_count}",
            f"習得部活奥義：{learning_skill}種類",
            "過去の実績 " + (
                " ".join(str(key) for key in self.achievements) or "なし"),
        ]


def describe(body: bytes) -> str:
    """A 0x4316 body read back out, for the log.

    ⚠️ Reading the wire rather than the record is the point: with PROBE armed
    the two disagree, and the log is what the screen gets compared against.
    """
    if len(body) != 2 + NAME_LEN * 2 + 2 + 4 + 8 + 4 + 2:
        return f"{len(body)} バイト?"
    in_class = struct.unpack_from(">H", body, 0)[0]
    title, visits, hours, attended, skills = struct.unpack_from(
        ">HiqIH", body, 2 + NAME_LEN * 2)
    return (f"組{in_class} 称号{title} 登校{visits}回 {hours}時間 "
            f"出席{attended} 奥義{skills}")


def list_replies(state: "Career | None") -> "list[tuple[int, bytes]]":
    """The two messages 0x4318 is answered with.

    ⚠️ The Result's count is a u16 here, not the u32 the キーワード and 部活奥義
    lists use for the same job -- Input_MsgSvResultCharaCareerList reads it
    through the stream's uint16 slot (vt+0x28). Two families, two widths, and
    the difference is the client's, not a slip.
    """
    pages = state.row_pages() if state is not None else [struct.pack(">H", 0)]
    total = sum(struct.unpack_from(">H", page, 0)[0] for page in pages)
    return ([(MSG_SV_RESULT_CHARA_CAREER_LIST, struct.pack(">H", total))]
            + [(MSG_SV_NOTIFY_CHARA_CAREER_LIST, page) for page in pages])
