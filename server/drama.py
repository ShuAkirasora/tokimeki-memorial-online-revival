"""ドラマイベント parties: the second half of the matching screen (0xE007-0xE026).

The first half — open the screen, list the 22 events — went through in round
217 and lives in ``script.py``. This half is the lobby that hangs off it: a
party is a booking for one drama, made by one player, with one cast role taken
per member and the rest left open for whoever walks in.

    0xE00B MsgClRequestDramaPartyCreate  dramaEventId{categoryId u16, id u16},
                                         actorId u16, name[u16], password[u16]
    0xE00C MsgSvOkDramaPartyCreate       dramaPartyId u64
    0xE00D MsgSvNgDramaPartyCreate       reason u8
    0xE00E MsgClRequestDramaPartyInfo    dramaPartyId u64
    0xE00F MsgSvOkDramaPartyInfo         dramaPartyId u64, actorIdLeader u16,
                                         password[u16], dramaActorInfo[u16]
    0xE010 MsgSvNgDramaPartyInfo         reason u8
    0xE011 MsgClRequestDramaPartyJoin    dramaPartyId u64, password[u16],
                                         actorId u16
    0xE012 MsgSvOkDramaPartyJoin         dramaPartyId u64
    0xE013 MsgSvNgDramaPartyJoin         reason u8
    0xE014 MsgClRequestDramaPartyPart    ()
    0xE015 MsgSvOkDramaPartyPart         ()
    0xE016 MsgSvNgDramaPartyPart         reason u8
    0xE004 MsgSvNotifyDramaPartyList     dramaPartyList[u16]  (the record below)
    0xE007 MsgSvNotifyDramaPartyUpdate   one such record, uncounted
    0xE008 MsgSvNotifyDramaPartyDel      dramaPartyId u64
    0xE009 MsgSvNotifyDramaPartyJoin     dramaPartyId u64, actorIdLeader u16,
                                         dramaActorInfo[u16]
    0xE00A MsgSvNotifyDramaPartyPart     actorId u16, reason u8,
                                         actorIdLeader u16, password[u16]
    0xE017 MsgClCastDramaPartyReady      prepare u8
    0xE018 MsgSvNotifyDramaPartyReady    actorId u16, prepare u8
    0xE019 MsgSvErrorDramaPartyReady     reason u8
    0xE01A MsgClCastDramaPartyStart      ()
    0xE01B MsgSvNotifyDramaPartyStart    ()
    0xE01C MsgSvErrorDramaPartyStart     reason u8

Field names are the client's own (its ``DramaParty`` formatter), shapes
and buffer sizes are read out of its deserialisers, and every limit below is
a number the client would overrun rather than clamp.

⭐⭐⭐ WHAT THE THREE FLAG FIELDS MEAN. The party record ends in three bytes
whose names — ``flgUnreserve``, ``existPassword``, ``state`` — say almost
nothing on their own, and guessing them was going to be a whole client run.
It did not have to be: the client carries its own debug printer for this
record (0x74A5AB, and a second copy at 0x74B491), and it prints each field
with a caption::

    ◆パーティ%I64d：        dramaPartyId
    　パーティ名 %s          name
    　イベントＩＤ %d %d     dramaEventId
    　パスワードなし         [obj+0x39] == 0        <- existPassword
    　パスワードあり         [obj+0x39] == 1
    　参加者募集中           [obj+0x3a] == 0        <- state
    　イベント中             [obj+0x3a] == 1
    　役柄未予約：%x         [obj+0x38] in hex      <- flgUnreserve

⇒ ``state`` is recruiting/running, and ``flgUnreserve`` is a **bit mask of the
cast slots nobody has taken** — printed in hex because that is what a mask is
for. Which cast slots exist is in the game's own ``drama_event.bin``: four
slots per drama, and all 22 in this build use exactly the first two
(read off the drama-event table), so a fresh party with its leader in slot 0
leaves 0b10.

⚠️ The mask's width is one byte and the slot count is four, so bits 4-7 have
no meaning and go out clear.

Refusals
--------
``error_message.bin`` files all 27 of this family's sentences under one pseudo
id (0xFF01), shared by every Ng/Error in the 0xE0xx range, so the reason
numbers below are the same numbers 0xE00D, 0xE010, 0xE013 and 0xE016 select
from. Only the ones this server can actually reach are named.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# The party half of the family. ⚠️ 0xE000-0xE006 — the screen's own open and
# close bracket, and the event list it puts up — stay in `script.py`, where the
# rest of the drama-event reading lives; the split is by subsystem, not by
# number range.
MSG_SV_NOTIFY_UPDATE = 0xE007
MSG_SV_NOTIFY_DEL = 0xE008
MSG_SV_NOTIFY_JOIN = 0xE009
MSG_SV_NOTIFY_PART = 0xE00A
MSG_CL_REQUEST_CREATE = 0xE00B
MSG_SV_OK_CREATE = 0xE00C
MSG_SV_NG_CREATE = 0xE00D
MSG_CL_REQUEST_INFO = 0xE00E
MSG_SV_OK_INFO = 0xE00F
MSG_SV_NG_INFO = 0xE010
MSG_CL_REQUEST_JOIN = 0xE011
MSG_SV_OK_JOIN = 0xE012
MSG_SV_NG_JOIN = 0xE013
MSG_CL_REQUEST_PART = 0xE014
MSG_SV_OK_PART = 0xE015
MSG_SV_NG_PART = 0xE016
# The two buttons the room itself has, once there is somebody standing in it.
# ⚠️ Neither of the Sv halves is an "Ok": a Cast is answered by a Notify that
# goes to the whole room, because 準備ＯＫ and 開始 are things the room learns,
# not things the presser is told. The Error halves are for the presser alone.
MSG_CL_CAST_READY = 0xE017
MSG_SV_NOTIFY_READY = 0xE018
MSG_SV_ERROR_READY = 0xE019
MSG_CL_CAST_START = 0xE01A
MSG_SV_NOTIFY_START = 0xE01B
MSG_SV_ERROR_START = 0xE01C

# Cast slots per drama, from `drama_event.bin`'s four (sex, keyword) pairs.
# All 22 events in this build fill the first two and leave slots 2 and 3 empty,
# which is why `reference/drama_events.json` carries the per-event list rather
# than this end assuming a pair.
CAST_MAX = 4
#: How many parties MsgSvNotifyDramaPartyList's reader has room for: entries of
#: 0x38 at obj+8 with the count parked at obj+0x708, and it loops on the count
#: without checking it, so one entry too many walks over the bound itself.
PARTY_MAX = 32
#: Same shape, same lack of a check, in 0xE00F and 0xE009: four actors at
#: obj+0x20 / obj+0x14, stride 0x28, count at obj+0xc0 / obj+0xb4.
ACTOR_MAX = 4
#: The party name's destination buffer, measured as the gap between it and the
#: length field that follows (0x2a - 0x08 in the list reader, 0x32 - 0x10 in
#: the update reader, 0x2c - 0x0a in the client's own create serialiser).
NAME_MAX = 34
#: Likewise for the password: 0x38 - 0x2e on the way in, 0x1c - 0x12 on the way
#: back out of 0xE00F.
PASSWORD_MAX = 10
#: And for each actor's two names, 12 apiece — the character sheet's NAME_LEN
#: plus a terminator, so a name that fits a character fits here.
ACTOR_NAME_MAX = 12

#: state, as the client's debug printer captions it.
STATE_RECRUITING = 0
STATE_RUNNING = 1

# The refusals this server can reach, out of the 27 the family shares.
NG_BAD_CHARACTER = 0        # キャラクター情報の取得に失敗しました。
NG_BAD_EVENT = 2            # 選択されたドラマイベントの情報が不正です。
NG_BAD_PARTY = 4            # 選択されたパーティの情報が不正です。
NG_BAD_ACTOR = 5            # 選択された登場人物の情報が不正です。
NG_BAD_PASSWORD = 7         # パスワードが正しくありません。
NG_ACTOR_TAKEN = 14         # 選択された登場人物は、他のキャラクターが担当…
NG_NO_ROOM = 15             # この場所では、これ以上パーティを登録できません。
NG_NOT_IN_PARTY = 16        # パーティに参加していません。
NG_ALREADY_IN_PARTY = 17    # 既にパーティに参加しています。
NG_NOT_LEADER = 19          # リーダー権限がありません。
NG_NOT_ALL_READY = 20       # パーティの参加者全員が「準備OK」の状態に…
NG_ALREADY_STARTED = 23     # 既にドラマイベントが開始されています。
NG_DUPLICATE_NAME = 26      # 同名のパーティが存在しています。

# 0xE00A's reason, from the client's own three sentences at 0xBD75D8:
# 自分自身の要求による / リーダーに排除された / 切断による.
PART_SELF = 0
PART_KICKED = 1
PART_DISCONNECTED = 2


def selectable_actors(event: dict, sex: int, owns_keyword) -> int:
    """``flgSelectActor``: a bit per cast slot this character is allowed to play.

    ⭐⭐⭐ THE GATE ON THE 参加 SCREEN. Round 229 spent a client run on 「入れま
    せん」: with this byte zero, EVERY 登場人物 button on パーティ参加 reads
    「入れません」 and the teacher says 「このパーティには参加できないようだ。」
    — for every party, every role, whatever `flgUnreserve` says, and with not
    one byte going back up the wire. Send it and the same buttons become
    「募集中」/「しめきり」 and the screen works. ⚠️ It is NOT the same thing as
    `flgUnreserve`: that one says which roles are free, this one says which
    roles are *yours to take*, and the client needs both.
    ⚠️ 0xE003 carries it per event, not per party, so it is about the character
    and the drama — never about who is already in a booking.

    The rule is restored rather than invented: the client computes the same
    thing locally for the パーティ作成 dialog, where 五郎 (男) gets Ａ太 in white
    and Ｂ美 greyed out, so the two inputs are the ones `drama_event.bin` keeps
    per slot — the role's 性別, and its 必要キーワード where it has one.
    """
    mask = 0
    for slot in event.get("cast", ()):
        index = int(slot["slot"])
        if index >= CAST_MAX or int(slot["sex"]) != sex:
            continue
        keyword = slot.get("keyword")
        if keyword is not None and not owns_keyword(int(keyword)):
            continue
        mask |= 1 << index
    return mask


def counted(text: str, limit: int) -> bytes:
    """``u16 length`` + SJIS bytes, terminator included, whole characters only.

    The count on this wire includes the NUL — every counted string the client
    sends does, and its readers copy exactly the counted bytes into a buffer
    they then draw as a C string, so a count that stops short of the NUL leaves
    whatever was there before hanging off the end. Truncating bytes rather than
    characters would leave half an SJIS character instead, which draws as
    garbage; hence the walk down whole characters.
    """
    for end in range(len(text), -1, -1):
        raw = text[:end].encode("cp932", "replace")
        if len(raw) + 1 <= limit:
            return struct.pack(">H", len(raw) + 1) + raw + b"\x00"
    return struct.pack(">H", 1) + b"\x00"


def read_counted(params: bytes, at: int) -> tuple[str, int]:
    """One counted string out of a client message: the text and where it ended.

    Cut at the first NUL for the same reason `chat.parse_cast` is: the count
    carries the terminator, and `str.strip()` does not treat NUL as whitespace.
    """
    if at + 2 > len(params):
        return "", len(params)
    (length,) = struct.unpack_from(">H", params, at)
    raw = params[at + 2 : at + 2 + length].split(b"\x00", 1)[0]
    return raw.decode("cp932", "replace"), at + 2 + length


@dataclass
class Actor:
    """One member of a party, in the cast slot they took."""

    actor_id: int
    chara_id: int
    family: bytes
    first: bytes
    #: The per-actor ``state`` byte, which is 準備ＯＫ. 0xE017
    #: CastDramaPartyReady carries a ``prepare`` u8 and 0xE018 answers with
    #: (actorId, prepare), and this is the value both of them mean: whatever
    #: the client last said about this actor goes back out in every roster
    #: (`actor_record`), so a member who arrives late sees who is already
    #: waiting. ⚠️ The byte is echoed rather than interpreted — this end reads
    #: only "nonzero is ready" (`Party.everyone_ready`), because the button is
    #: a toggle and nothing says its off value is anything but 0.
    ready: int = 0


@dataclass
class Party:
    """One booking: a drama, a name, an optional password, and its cast."""

    party_id: int
    genre: int
    index: int
    name: str
    password: str
    #: Which cast slot the leader took.
    #:
    #: ⚠️ INVENTED — that leadership passes to the member who has been in the
    #: party longest when the leader leaves (`Board.part`). Round 229 let a
    #: second person in with 0xE011, which is the day the old note here was
    #: waiting for: nothing on the wire says where leadership goes, but
    #: 0xE00A carries `actorIdLeader` *after* the departure, so the protocol
    #: takes for granted that it can have moved. ⛔️ Not a knob: who leads is
    #: a rule, not a number. Seniority rather than the lowest cast slot
    #: because the slot is a role in a play — 0 is not a rank.
    leader_actor_id: int
    #: Which cast slots this drama actually has, from `drama_events.json`.
    #: ⚠️ Empty means "the event is not in the export", not "no roles": the
    #: mask is then left clear rather than inventing a pair.
    cast_slots: tuple[int, ...] = ()
    actors: list[Actor] = field(default_factory=list)
    state: int = STATE_RECRUITING

    @property
    def unreserved(self) -> int:
        """``flgUnreserve``: a bit per cast slot with nobody in it."""
        taken = {actor.actor_id for actor in self.actors}
        mask = 0
        for slot in self.cast_slots:
            if slot < CAST_MAX and slot not in taken:
                mask |= 1 << slot
        return mask

    def has(self, chara_id: int) -> bool:
        return any(actor.chara_id == chara_id for actor in self.actors)

    def actor_of(self, chara_id: int) -> Actor | None:
        return next((a for a in self.actors if a.chara_id == chara_id), None)

    def everyone_ready(self) -> bool:
        """Whether 0xE01A 開始 is allowed to go through.

        Refusal 20 says 「パーティの参加者全員が『準備OK』の状態になっていま
        せん」, and 全員 is the one word in it this end has to read: everybody
        in the room, the leader included.

        ⭐ Not a guess — the client says so three times over (round 230). The
        leader's own cell carries an ［OK!］ button like everyone else's; with
        it unpressed the ［イベントスタート］ button is drawn grey and pressing
        it sends nothing at all; and the byte that greys it is this one, since
        a hand-sent 0xE018 (actorId=0, prepare=1) lights the button up on its
        own. So the client gates 開始 on every actor's prepare bit, and this
        end refusing on the same rule only makes the two agree.
        """
        return all(actor.ready for actor in self.actors)


class Board:
    """Every party currently up on this port.

    Held by the server rather than by a session for the same reason the 看板 is:
    a party outlives whoever is looking at the list. Not persisted — a booking
    is only up while its members are logged in, which is what 0xE00A's
    「切断による」 reason exists to say.
    """

    def __init__(self) -> None:
        self.parties: dict[int, Party] = {}
        # ⚠️ INVENTED — how a dramaPartyId is handed out. Nothing on the wire
        # says anything about the number beyond its width, so: start at 1 and
        # only ever go up, per port, not persisted. Zero is skipped because it
        # is the value an uninitialised u64 has, and ids are never reused
        # because a stale row on someone's list would then quietly match a
        # different party.
        self._next_id = 1

    def create(self, party: Party) -> Party:
        party.party_id = self._next_id
        self._next_id += 1
        self.parties[party.party_id] = party
        return party

    def find(self, party_id: int) -> Party | None:
        return self.parties.get(party_id)

    def party_of(self, chara_id: int) -> Party | None:
        for party in self.parties.values():
            if party.has(chara_id):
                return party
        return None

    def named(self, name: str) -> Party | None:
        for party in self.parties.values():
            if party.name == name:
                return party
        return None

    def part(self, chara_id: int) -> Party | None:
        """Take a character out of whatever party they are in.

        Returns the party they left, already emptied of them.

        ⚠️ INVENTED — that the last member leaving deletes the party. The
        protocol has a message for saying so (0xE008 Del) but nothing that says
        when it fires; this end fires it here because a party with nobody in it
        has no leader to run it and no way back onto anyone's list. ⛔️ Not a
        knob: whether an emptied party survives is a design decision, not a
        number.
        """
        party = self.party_of(chara_id)
        if party is None:
            return None
        left = next(a for a in party.actors if a.chara_id == chara_id)
        party.actors = [a for a in party.actors if a.chara_id != chara_id]
        if not party.actors:
            self.parties.pop(party.party_id, None)
        elif left.actor_id == party.leader_actor_id:
            # See Party.leader_actor_id: the longest-standing member left in
            # the room takes over, and 0xE00A tells everyone in the same
            # breath as the departure.
            party.leader_actor_id = party.actors[0].actor_id
        return party

    def summary(self) -> str:
        if not self.parties:
            return "no parties"
        return ", ".join(
            f"#{p.party_id} {p.name!r} {p.genre}:{p.index} "
            f"({len(p.actors)} in, free={p.unreserved:#x})"
            for p in self.parties.values()
        )


def party_record(party: Party) -> bytes:
    """One MsgSvNotifyDramaPartyList entry, which is 0xE007's whole body too.

    17 bytes plus the name: the two readers take the same seven fields in the
    same order, one into an array slot and one into the object itself.
    """
    return (
        struct.pack(">Q", party.party_id)
        + counted(party.name, NAME_MAX)
        + struct.pack(
            ">HHBBB",
            party.genre,
            party.index,
            party.unreserved,
            1 if party.password else 0,
            party.state,
        )
    )


def party_list_params(parties: list[Party], limit: int = PARTY_MAX) -> bytes:
    """A MsgSvNotifyDramaPartyList body. Clamped here because nothing clamps it
    at the other end."""
    kept = parties[:limit]
    return struct.pack(">H", len(kept)) + b"".join(party_record(p) for p in kept)


def actor_record(actor: Actor) -> bytes:
    """One dramaActorInfo entry, shared by 0xE00F and 0xE009."""
    def name(raw: bytes) -> bytes:
        cut = raw.split(b"\x00", 1)[0].decode("cp932", "replace")
        return counted(cut, ACTOR_NAME_MAX)

    return (
        struct.pack(">HI", actor.actor_id, actor.chara_id)
        + name(actor.family)
        + name(actor.first)
        + struct.pack(">B", actor.ready)
    )


def actor_list_params(party: Party, limit: int = ACTOR_MAX) -> bytes:
    kept = party.actors[:limit]
    return struct.pack(">H", len(kept)) + b"".join(actor_record(a) for a in kept)


def info_params(party: Party, viewer_chara_id: int) -> bytes:
    """A MsgSvOkDramaPartyInfo body, for one named viewer.

    ⭐⭐⭐ THE PASSWORD IS FOR MEMBERS, AND ONLY FOR MEMBERS. 0xE00E is sent by
    people who are *not* in the party — pressing ［パーティ参加］ on somebody
    else's row is what makes the client ask (round 229), and the roster that
    comes back is what the パーティ情報 dialog draws its 「募集中」/「⊛試験 次郎」
    cells from. So refusing a stranger outright would break 参加; what a
    stranger must not get is the one field that is a credential.

    ⭐⭐ Two readings out of the client say the field is a member's, and that
    withholding it changes nothing on screen:

    * The 0xE00F consumer (`FUN_0074a6d7` -> `FUN_006564d4`) hands the password
      to `std::string::assign` **only** after `actorIdLeader == my own actorId`
      — the receiver keeps it if it is the leader and drops it otherwise. Its
      own gate is tighter than membership, so a blank for a non-member lands in
      code that was going to throw the value away.
    * 0xE00A NotifyDramaPartyPart carries the password too, to a whole room at
      once, with the same leader test on the far end (`FUN_006559e8`). A
      departure notice would have no reason to carry a credential unless the
      credential belonged to whoever is still standing there.

    ⭐ And a member learning it is not a disclosure at all: every member either
    made the party (they typed the password) or got past `NG_BAD_PASSWORD` in
    `_drama_party_join` (they typed it too). Membership is the line because
    everyone on the far side of it already knows the answer.
    """
    password = party.password if party.has(viewer_chara_id) else ""
    return (
        struct.pack(">QH", party.party_id, party.leader_actor_id)
        + counted(password, PASSWORD_MAX)
        + actor_list_params(party)
    )


def join_params(party: Party) -> bytes:
    """A MsgSvNotifyDramaPartyJoin body: the party's whole roster, again."""
    return (
        struct.pack(">QH", party.party_id, party.leader_actor_id)
        + actor_list_params(party)
    )


def del_params(party_id: int) -> bytes:
    return struct.pack(">Q", party_id)


def ready_params(actor_id: int, prepare: int) -> bytes:
    """A MsgSvNotifyDramaPartyReady body: which cell, and what it now says."""
    return struct.pack(">HB", actor_id, prepare)


def part_params(actor_id: int, reason: int, leader_actor_id: int,
                password: str = "") -> bytes:
    """A MsgSvNotifyDramaPartyPart body: who left, why, and who leads now.

    ⭐⭐ WHY A DEPARTURE CARRIES A PASSWORD. One body goes to the whole room and
    the client sorts out whose business it is: `FUN_006559e8` compares
    `actorIdLeader` with the receiver's own actorId, records the answer as its
    「am I the leader」 flag, and assigns the password into its own slot only
    when that matched. So this field is how a room whose leader just walked out
    hands the password to whoever leads it now — `drama.Board.part` moves
    leadership, and this message is where the new leader hears about both.

    ⚠️ Which is why the default is a bad default for members: assign is not
    conditional on the string being non-empty, so a Notify that leaves this
    blank *wipes* the leader's copy. The empty default is for the one recipient
    who must not have it — the person who just left the party.

    ⚠️ `leader_actor_id == 0xFF` is the client's 「no leader in this message」
    sentinel (`FUN_006559e8` takes the not-leader branch on it without so much
    as a comparison). This end never sends it: `Board.part` always leaves
    somebody in charge of a party that still exists, and a party that does not
    is announced with 0xE008 instead.
    """
    return (
        struct.pack(">HBH", actor_id, reason, leader_actor_id)
        + counted(password, PASSWORD_MAX)
    )


def parse_join(params: bytes) -> tuple[int, str, int] | None:
    """A MsgClRequestDramaPartyJoin body → (dramaPartyId, password, actorId).

    None when the fixed head or the trailing actorId is missing. ⚠️ The
    actorId is *behind* the counted password here, the mirror image of
    0xE00B where it comes first — so it can only be read after walking the
    string, and a body that stops inside it is a message we did not
    understand rather than a refusal with a number.
    """
    if len(params) < 8:
        return None
    (party_id,) = struct.unpack_from(">Q", params, 0)
    password, at = read_counted(params, 8)
    if at + 2 > len(params):
        return None
    (actor_id,) = struct.unpack_from(">H", params, at)
    return party_id, password, actor_id


def parse_create(params: bytes) -> tuple[int, int, int, str, str] | None:
    """A MsgClRequestDramaPartyCreate body → (genre, index, actorId, name, pw).

    None when the three fixed u16 are not all there. A short *string* is not
    an error here — `read_counted` gives back what is on the wire and stops —
    because the two are told apart at the caller: an empty name is a refusal
    with a number, a truncated head is a message we did not understand.
    """
    if len(params) < 6:
        return None
    genre, index, actor_id = struct.unpack_from(">HHH", params, 0)
    name, at = read_counted(params, 6)
    password, _ = read_counted(params, at)
    return genre, index, actor_id, name, password
