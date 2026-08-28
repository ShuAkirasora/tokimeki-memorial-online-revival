"""多目的室予約 -- the 理事長秘書's fourth ring item and the 0x09xx family.

Where this starts. Round 219 opened all four doors on that ring and finished
two of them; this one it could only describe. What the screen showed was
already a batch of facts: a header reading 「２週間の期間内に１日予約できます」,
seven tabs, and two columns headed 予約日 and 同好会名. The window opens on
0x622A (which group am I in) and then 0x0900 with roomId 0, i.e. tab 1, so the
tabs are rooms 0..6 and the list is per room.

⚠️ It is a passive list: unanswered, the window still draws and still closes,
which is why this family sat unanswered for two hundred rounds without ever
looking broken. What it could not do is show a single booking.

⭐⭐⭐ The row layout is read out of the client's own deserializer at 0x8DB930,
not guessed from the field names, and the two would have disagreed. the shape reader
calls 0x0901 ``counted entry=27B``; the entry is 25 bytes and the 2 it added is
the roomId, which sits *in front of* the count and belongs to no row:

    u16 roomId
    u16 booking count
    per booking:
        u16 year
        u8  month
        u8  day
        char[21] groupName        ← FIXED, not counted

⚠️⚠️ That last field is the one worth stopping on. 0x622D's group name is a
counted string; this one is a fixed 21-byte field, and the reader says so
outright -- 0x8D2100 pulls a u16 off the wire and hands it to the string reader
at 0xA49610 as the length, while 0x8DB930 hands that same reader the constant
0x15. Same family of screens, same word "groupName", opposite encodings.

⭐⭐⭐ And the field dump tells them apart without any disassembly at all, which
is the reusable half of this:

    groupName[%d]={%c}                        ← counted
    groupName[tmn::MAX_GROUP_NAME + 1]={%c}   ← fixed at 21

0x0904 carries one of each and settles it: its groupName is ``[%d]`` and its
familyName/firstName are ``[tmn::MAX_CHARA_FAMILYNAME + 1]``, and 0x8DBD30 reads
exactly that -- a counted string, then two 11-byte fixed ones, then a counted
comment, then a u8. So the bracket is the encoding. 2.177 三 had noticed the two
spellings look alike and warned not to confuse them; they are not merely
distinguishable, the dump is a complete answer.

The rules are the client's, not this end's. 0x0908 and 0x090B carry twenty-odd
reason strings between them and they read as a specification:

    0x0908 (予約 Ng)          0x090B (キャンセル Ng)
      0 room info invalid       0 no such booking (予約情報不正)
      1 character info invalid  1 character info invalid
      2 no character data       2 no character data
      3 未使用 (comms)          3 未使用 (comms)
      4 未使用 (no permission)  4 no permission
      5 already booked, one     5 you have no booking
        at a time
      6 date is wrong           6 未使用 (undefined)

⚠️⚠️ **The asymmetry on reason 4 decides a design question, and round 220
found out why it is there.** 「予約権限がありません。」 is live for cancel and
marked 未使用 for booking -- so the original server refused a *cancel* for lack
of permission and never refused a *booking* for it, while the β manual (p05_05)
says the room is something a group can book 「同好会」になると. Both are true:
**the client enforces that one itself.** With the store empty, every day in the
window draws grey and not one of them can be clicked, by a leader whose group
holds no booking -- so the thing stopping it is not "you already have one", and
the only candidate left is the manual's sentence. A gate the client keeps is a
gate the server never needs a reason code for.

⇒ This end does not invent it either: booking asks for a group, which is the
least the request needs to name a booker at all. ⚠️ It is untested for exactly
that reason -- 0x0906 has never been on the wire, because nothing in reach is a
同好会 yet.

What a booking is, then: one group holds at most one across all seven rooms
(reason 5 says so in one sentence), on one day inside the horizon (reason 6),
and cancelling it is refused for somebody else's group (0x090B reason 4) or
when there is none (reason 5).

⭐⭐⭐ **What the list is, and what it is not.** 0x0901 carries the room's
*bookings*, not its days. The window draws fourteen dated rows on its own --
they arrive on no message, and a payload of three November dates changed not one
pixel of them -- and it decides each row's state by looking for a booking with
that date:

    no booking            → grey, not clickable: the day is free
    booking, another 同好会 → grey, not clickable: not yours to touch
    booking, your own      → white, and clicking opens 予約内容 with ［予約解除］

⚠️⚠️ **An empty groupName matches every viewer**, which is the trap round 220
fell into: one row per day with the free ones left blank drew a full white list
of fourteen days all apparently held by the viewer's group. See BookingBook.rows.

⚠️ Where the window's own fourteen days start is **not identified**. It was
2026-09-06 on every open of a session whose clock said 2026-08-28, across three
different payloads, so it is the client's and not ours; whether it counts from
the client's clock, a weekday, or something else has not been measured.

⚠️ The calendar is the school clock, i.e. wall-clock time, the same one
curriculum.clock runs on. A booking that falls out of the horizon is expired
rather than deleted; nothing here rewrites the store on a date change.
"""
from __future__ import annotations

import json
import struct
from datetime import date, timedelta
from pathlib import Path

from characters import GROUP_NAME_LEN, NAME_LEN

MSG_CL_QUERY_MULTIPURPOSE_ROOM_BOOKING = 0x0900
MSG_SV_RESULT_MULTIPURPOSE_ROOM_BOOKING = 0x0901
MSG_SV_ERROR_MULTIPURPOSE_ROOM_BOOKING = 0x0902
MSG_CL_QUERY_MULTIPURPOSE_ROOM_RESERVE = 0x0903
MSG_SV_RESULT_MULTIPURPOSE_ROOM_RESERVE = 0x0904
MSG_SV_ERROR_MULTIPURPOSE_ROOM_RESERVE = 0x0905
MSG_CL_REQUEST_MULTIPURPOSE_ROOM_RESERVE = 0x0906
MSG_SV_OK_MULTIPURPOSE_ROOM_RESERVE = 0x0907
MSG_SV_NG_MULTIPURPOSE_ROOM_RESERVE = 0x0908
MSG_CL_REQUEST_MULTIPURPOSE_ROOM_CANCEL = 0x0909
MSG_SV_OK_MULTIPURPOSE_ROOM_CANCEL = 0x090A
MSG_SV_NG_MULTIPURPOSE_ROOM_CANCEL = 0x090B

#: The four the client can send. Everything else in 0x09xx is an answer.
HANDLED = frozenset({
    MSG_CL_QUERY_MULTIPURPOSE_ROOM_BOOKING,
    MSG_CL_QUERY_MULTIPURPOSE_ROOM_RESERVE,
    MSG_CL_REQUEST_MULTIPURPOSE_ROOM_RESERVE,
    MSG_CL_REQUEST_MULTIPURPOSE_ROOM_CANCEL,
})

#: Seven tabs on the window, numbered 1..7, and the client asks for tab 1 as
#: roomId 0 -- measured on the first open (2.177 四). Nothing names the rooms;
#: the tabs are drawn with numbers.
ROOM_COUNT = 7

#: 「２週間の期間内に１日予約できます」, read off the window's own header, and
#: the number of rows the window draws -- fourteen, counted on screen.
#:
#: ⚠️ Nothing computes with it: which fourteen days those are is the client's
#: (see HORIZON_DAYS), and a list of bookings has no length of its own. It is
#: here because the number is measured and the next person to look at this
#: family will want it.
WINDOW_DAYS = 14

#: How far ahead this end will accept a booking date.
#:
#: ⚠️⚠️ Deliberately wider than WINDOW_DAYS, and the reason is an admission: the
#: fourteen days the client draws did **not** start on its own today. Three
#: different payloads on a client whose clock said 2026-08-28 all produced the
#: same 2026-09-06 … 2026-09-19, so the start is the client's and computed from
#: something this end has not identified. Refusing on a fortnight measured from
#: *this* end's today would therefore refuse days the client is offering, which
#: is a rule invented by accident. A horizon that covers the drawn window and
#: nothing beyond a month is the smallest honest thing to check instead.
HORIZON_DAYS = 30

#: The longest comment 0x0906 is allowed to bring back out. The field is counted
#: on the wire so nothing forces a width, but the store is a JSON file and an
#: unbounded string in it is a way to make the server unreadable from a client.
MAX_COMMENT = 64

# 0x0902 / 0x0905, the two 「取得に失敗」 answers.
#
# ⚠️ Only ROOM is ever sent: the list and the details box are readable by
# anyone, so the two 「情報が取得できません」 codes have no case here. They are
# named anyway because a reason table with holes in it reads like a table
# nobody finished reading -- the error-message table has all five, and these are the two this
# end deliberately does not use.
BOOKING_NG_ROOM = 0
BOOKING_NG_CHARACTER = 1
BOOKING_NG_NO_DATA = 2

# 0x0908, 予約.
RESERVE_NG_ROOM = 0
RESERVE_NG_CHARACTER = 1
RESERVE_NG_NO_DATA = 2
RESERVE_NG_ALREADY = 5
RESERVE_NG_DATE = 6

# 0x090B, キャンセル.
CANCEL_NG_NO_BOOKING = 0
CANCEL_NG_CHARACTER = 1
CANCEL_NG_NO_DATA = 2
CANCEL_NG_NOT_YOURS = 4
CANCEL_NG_NONE_HELD = 5


def window(today: "date | None" = None) -> list[date]:
    """The days a booking may name: today and the HORIZON_DAYS-1 after it."""
    first = today or date.today()
    return [first + timedelta(days=offset) for offset in range(HORIZON_DAYS)]


class Booking:
    """One reservation: which room, which day, whose, and what they wrote."""

    def __init__(self, room: int, day: date, group_id: int, chara_id: int,
                 comment: bytes = b"", public: int = 1) -> None:
        self.room = room
        self.day = day
        self.group_id = group_id
        self.chara_id = chara_id
        self.comment = comment.split(b"\x00")[0][:MAX_COMMENT]
        self.public = public & 0xFF

    def to_json(self) -> dict:
        return {
            "room": self.room,
            "date": self.day.isoformat(),
            "group": f"0x{self.group_id:08x}",
            "chara": f"0x{self.chara_id:08x}",
            "comment": self.comment.decode("cp932", "replace"),
            "public": self.public,
        }

    def label(self) -> str:
        return (f"room {self.room} {self.day.isoformat()} "
                f"group 0x{self.group_id:08x} by 0x{self.chara_id:08x}")


class BookingBook:
    """Every reservation on the server, in one file beside groups.json.

    Same reasoning GroupBook gives for not filing itself under an account: a
    booking belongs to a group, a group spans accounts, and the seven rooms are
    the school's rather than anybody's. Every mutation writes the file.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "multipurpose.json"
        self.bookings: list[Booking] = []
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[multipurpose] ignoring unreadable {self.path}: {exc}")
            return
        for body in (raw.get("bookings") if isinstance(raw, dict) else None) or []:
            if not isinstance(body, dict):
                continue
            try:
                self.bookings.append(Booking(
                    int(body.get("room", 0)),
                    date.fromisoformat(str(body.get("date"))),
                    int(str(body.get("group", "0x0")), 16),
                    int(str(body.get("chara", "0x0")), 16),
                    str(body.get("comment", "")).encode("cp932", "replace"),
                    int(body.get("public", 1)),
                ))
            except ValueError as exc:
                print(f"[multipurpose] ignoring unreadable booking {body!r}: {exc}")

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"bookings": [b.to_json() for b in self.bookings]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )

    # -- queries ----------------------------------------------------------

    def at(self, room: int, day: date) -> "Booking | None":
        for booking in self.bookings:
            if booking.room == room and booking.day == day:
                return booking
        return None

    def of_group(self, group_id: int) -> "Booking | None":
        """The one booking a group holds, if it holds one.

        ⚠️ Only inside the current window. A booking whose day has gone by is
        not deleted -- nothing sweeps this file -- and counting it would leave a
        group unable to book again forever, which reason 5 plainly does not mean.
        """
        live = set(window())
        for booking in self.bookings:
            if booking.group_id == group_id and booking.day in live:
                return booking
        return None

    def rows(self, room: int, names: "dict[int, bytes]") -> list[tuple[date, bytes]]:
        """(day, holder's groupName) for the bookings this room actually holds.

        ⭐⭐⭐ **One row per booking, not one per day** -- and round 220 got that
        backwards first, which is worth writing down because the wrong version
        looked like it worked. Sending one row per day with an empty name for
        the free ones drew a full white list: fourteen days, every one of them
        apparently booked by the viewer's own group, each opening a 予約内容 box
        whose button said ［予約解除］. Nothing was booked.

        ⭐ What the client does with a row: it compares the row's groupName with
        the viewer's own, and **an empty name matches everything**, so every free
        day arrived claiming to be theirs. Measured with a marked payload --
        thirty rows, two of them named ZZZZ and YYYY: exactly those two greyed
        out (another group's day, not yours to touch) and the twenty-eight empty
        ones stayed white. That is the whole rule, from one experiment.

        ⇒ A day this room has no row for is **free**. Only bookings go on the
        wire, which is also why ``booking[%d]`` is a counted list rather than the
        fourteen fixed slots the window draws.

        ``names`` maps group id to the 21-byte name. ⚠️⚠️ A booking whose group
        no longer resolves is **left off the wire entirely** rather than sent
        with a blank name: blank is not "unknown" to the client, it is 「yours」,
        so an unattributable booking would show up as every viewer's own. That
        is normally unreachable -- forget_group drops a disbanded group's
        bookings where the group goes -- and this is the belt to that braces.
        """
        out = []
        for booking in self.bookings:
            if booking.room != room:
                continue
            name = names.get(booking.group_id)
            if not name or not name.split(b"\x00")[0]:
                print(f"[multipurpose] {booking.label()} has no group left, "
                      f"leaving it off the list")
                continue
            out.append((booking.day, name))
        return sorted(out)

    # -- mutations --------------------------------------------------------

    def add(self, booking: Booking) -> None:
        self.bookings.append(booking)
        self._save()

    def remove(self, booking: Booking) -> None:
        if booking in self.bookings:
            self.bookings.remove(booking)
            self._save()

    def forget_group(self, group_id: int) -> None:
        """Drop a disbanded group's bookings. Called where the group goes."""
        kept = [b for b in self.bookings if b.group_id != group_id]
        if len(kept) != len(self.bookings):
            self.bookings = kept
            self._save()

    def summary(self) -> str:
        return f"{len(self.bookings)} booking(s)" if self.bookings else "(no bookings)"


def booking_params(room_id: int, rows: "list[tuple[date, bytes]]") -> bytes:
    """MsgSvResultMultipurposeRoomBooking (0x0901).

    roomId, then a u16 count, then the rows -- year u16, month u8, day u8 and
    the group name as a *fixed* 21-byte field. See the module docstring for why
    that last one is not the counted string its neighbour in 0x622D is.
    """
    out = struct.pack(">HH", room_id, len(rows))
    for day, name in rows:
        out += struct.pack(">HBB", day.year, day.month, day.day)
        out += name.ljust(GROUP_NAME_LEN, b"\x00")[:GROUP_NAME_LEN]
    return out


def reserve_params(group_name: bytes, family: bytes, first: bytes,
                   comment: bytes, public: int) -> bytes:
    """MsgSvResultMultipurposeRoomReserve (0x0904): one booking's details.

    Read off 0x8DBD30: a counted group name, two 11-byte fixed name fields, a
    counted comment, then publicFlag. ⚠️ The counts include the trailing NUL,
    the convention groups.read_counted documents for the whole neighbourhood.
    """
    name = group_name.split(b"\x00")[0] + b"\x00"
    text = comment.split(b"\x00")[0] + b"\x00"
    out = struct.pack(">H", len(name)) + name
    out += family.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += first.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += struct.pack(">H", len(text)) + text
    out += struct.pack(">B", public & 0xFF)
    return out


def read_date(params: bytes, at: int) -> "date | None":
    """year u16, month u8, day u8 -- the shape 0x0903/0x0906/0x0909 all share.

    None for anything the calendar refuses, rather than raising: a malformed
    date is a reason code (0x0908 reason 6), not a dropped connection.
    """
    if len(params) < at + 4:
        return None
    year, month, day = struct.unpack_from(">HBB", params, at)
    try:
        return date(year, month, day)
    except ValueError:
        return None
