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

Field names are the client's own (``the field-name extractor DramaParty``), shapes
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
(``the drama-event export cast``), so a fresh party with its leader in slot 0
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

# Cast slots per drama, from `drama_event.bin`'s four (sex, keyword) pairs.
# All 22 events in this build fill the first two and leave slots 2 and 3 empty,
# which is why `runtime/drama_events.json` carries the per-event list rather
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
NG_ACTOR_TAKEN = 14         # 選択された登場人物は、他のキャラクターが担当…
NG_NO_ROOM = 15             # この場所では、これ以上パーティを登録できません。
NG_NOT_IN_PARTY = 16        # パーティに参加していません。
NG_ALREADY_IN_PARTY = 17    # 既にパーティに参加しています。
NG_DUPLICATE_NAME = 26      # 同名のパーティが存在しています。

# 0xE00A's reason, from the client's own three sentences at 0xBD75D8:
# 自分自身の要求による / リーダーに排除された / 切断による.
PART_SELF = 0
PART_KICKED = 1
PART_DISCONNECTED = 2


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
    #: The per-actor ``state`` byte. 0xE017 CastDramaPartyReady carries a
    #: ``prepare`` u8 and 0xE018 answers with (actorId, prepare), so this is
    #: read as that flag — ⚠️ nothing has confirmed it on screen, and the
    #: ready half of this subsystem is not implemented at all yet.
    ready: int = 0


@dataclass
class Party:
    """One booking: a drama, a name, an optional password, and its cast."""

    party_id: int
    genre: int
    index: int
    name: str
    password: str
    #: Which cast slot the leader took. ⚠️ Nothing transfers it: a party only
    #: ever has one member on this server, and the last one leaving deletes the
    #: party, so leadership has never had to move. ⛔️ The day 0xE011 lets a
    #: second person in, this needs a rule for what happens when the leader
    #: leaves — 0xE00A carries `actorIdLeader` precisely to announce that.
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
        party.actors = [a for a in party.actors if a.chara_id != chara_id]
        if not party.actors:
            self.parties.pop(party.party_id, None)
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


def info_params(party: Party) -> bytes:
    """A MsgSvOkDramaPartyInfo body.

    ⚠️ The password goes back out as the client asked for it to. That is what
    the field is for — the leader's own screen shows it — but it means anyone
    who can send 0xE00E for a party id gets its password, and this server does
    not check membership before answering. Fine for one player on one machine;
    ⛔️ not fine the day this listens to strangers.
    """
    return (
        struct.pack(">QH", party.party_id, party.leader_actor_id)
        + counted(party.password, PASSWORD_MAX)
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


def part_params(actor_id: int, reason: int, leader_actor_id: int,
                password: str = "") -> bytes:
    """A MsgSvNotifyDramaPartyPart body: who left, why, and who leads now."""
    return (
        struct.pack(">HBH", actor_id, reason, leader_actor_id)
        + counted(password, PASSWORD_MAX)
    )


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
