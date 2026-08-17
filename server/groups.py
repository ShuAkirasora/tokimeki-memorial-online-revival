"""仲良しグループ -- the toolbar's seventh icon and the 0x62xx family.

Where this starts. The sixth icon (アドレス帳) was answered in round 141; the
seventh one, right beside it, opens a menu whose only row is a greyed
「グループ未所属」, and **not one byte goes out** -- same shape as the right-click
menu in 2.90: the client decided on its own that there is nothing to open. (The
icon's own tooltip is always 「仲良しグループ」; round 142 wrote the greyed row's
text down as the tooltip's, corrected in round 144.) The 「グループ登録申込み」
icon in the PC 交流メニュー is greyed out for the same reason, also without asking
this end anything.

So the gate is in the character record the client already holds, and this server
used to send all four of the fields that could hold it as zero:

    friendGroupName          21 bytes, all zero   (0x6501 and the 238B list entry)
    friendGroupId            u32 0                (0x6501 and the 74B tiny entry)
    leaderAuthorityFlag      u8 0                 (0x6501)
    leaderQualificationFlag  u8 0                 (0x6501)

⭐⭐⭐ Round 143 finished that sentence: zero is not a neutral value on the
second one. The client's predicate behind 「グループ登録申込み」 (VA 0x6FC2B2)
reads the *target's* friendGroupId and refuses on anything but -1, so 0 was
saying 「already in group 0」 about every character on the map. See
characters.NO_GROUP; the three fields around it really are zero when empty.

⭐ The manual says what the last one means and it reads like a latch: 「リーダー
試験」に合格し、リーダー資格を得ることにより、「仲良しグループ」を作成できる
ようになります (p05_05 §3). Membership, creation and the invite are three
different permissions in that text, which is why the fields are set one at a
time here rather than all at once -- one login per field says which one the
client is actually reading.

What the manual lays out, for when the wire work starts:

  * リーダー資格 (試験レベル 2 and a pass at 理事長秘書) lets you *create* one.
  * A group holds 15; at 試験レベル 3 with 15 members it can register as a
    同好会 and then holds 30.
  * Members leave freely; only the leader kicks; leadership can be handed over;
    disbanding and handing over both lock the ex-leader out of creating another
    for 30 days.
  * 公開設定 decides whether it shows up in the 理事長秘書's group list.

None of the cooldowns are modelled here. They are calendar rules with no message
of their own, and the school clock this server runs (curriculum.clock) is not
the one those 30 days would be counted against.

⭐⭐ Round 144 closed the window: ［更 新］ (0x620A) and ［除 名］ (0x6226) are
answered, so every control the 仲良しグループ情報 window draws now does
something. 解散 and 引継 are still open, and the reason to have left them is the
one 2.93 states -- answering half a handshake is harder to debug than answering
none of it -- but the two *inside* the window were a different case: an
unanswered request from a window that is already open hangs the client on
「通信中」 and costs a restart.

The store is one file for the whole server, for the reason friends.FriendBook
gives: a group spans accounts, so a per-account file would have to be written
twice and could disagree with itself.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from characters import GROUP_NAME_LEN, NAME_LEN, NO_GROUP

MSG_CL_REQUEST_CHARA_GROUP_CREATE = 0x6200
MSG_SV_OK_CHARA_GROUP_CREATE = 0x6201
MSG_SV_NG_CHARA_GROUP_CREATE = 0x6202
MSG_CL_REQUEST_CHARA_GROUP_DESTROY = 0x6203
MSG_SV_OK_CHARA_GROUP_DESTROY = 0x6204
MSG_SV_NG_CHARA_GROUP_DESTROY = 0x6205
MSG_SV_NOTIFY_CHARA_GROUP_DESTROY = 0x6206
MSG_CL_QUERY_CHARA_GROUP_INFO = 0x6207
MSG_SV_RESULT_CHARA_GROUP_INFO = 0x6208
MSG_SV_ERROR_CHARA_GROUP_INFO = 0x6209
MSG_CL_REQUEST_CHARA_GROUP_UPDATE = 0x620A
MSG_SV_OK_CHARA_GROUP_UPDATE = 0x620B
MSG_SV_NG_CHARA_GROUP_UPDATE = 0x620C
MSG_CL_REQUEST_CHARA_GROUP_INVITE_REQUEST = 0x6218
MSG_SV_OK_CHARA_GROUP_INVITE_REQUEST = 0x6219
MSG_SV_NG_CHARA_GROUP_INVITE_REQUEST = 0x621A
MSG_SV_REQUEST_CHARA_GROUP_INVITE_RESPONSE = 0x621B
MSG_CL_OK_CHARA_GROUP_INVITE_RESPONSE = 0x621C
MSG_CL_NG_CHARA_GROUP_INVITE_RESPONSE = 0x621D
MSG_SV_NOTIFY_CHARA_GROUP_JOIN = 0x621E
MSG_CL_REQUEST_CHARA_GROUP_INVITE_CANCEL = 0x621F
MSG_SV_OK_CHARA_GROUP_INVITE_CANCEL = 0x6220
MSG_SV_NG_CHARA_GROUP_INVITE_CANCEL = 0x6221
MSG_SV_NOTIFY_CHARA_GROUP_INVITE_CANCEL = 0x6222
MSG_CL_REQUEST_CHARA_GROUP_KICK = 0x6226
MSG_SV_OK_CHARA_GROUP_KICK = 0x6227
MSG_SV_NG_CHARA_GROUP_KICK = 0x6228
MSG_SV_NOTIFY_CHARA_GROUP_KICK = 0x6229

#: The two buttons inside the 仲良しグループ情報 window, measured the same way:
#:
#:   0x620A publicFlag u8 + counted catchcopy   ← ［更 新］
#:   0x620B (empty) / 0x620C reason u8
#:   0x6226 targetCharaId u32                   ← ［除 名］
#:   0x6227 (empty) / 0x6228 reason u8 / 0x6229 (empty)
#:
#: ⚠️ Until round 144 those two were the only controls in a window this server
#: could otherwise draw completely, and an unanswered request is worse than a
#: window that never opens: the client hangs on 「通信中」 and has to be
#: restarted. Answering half a window is the thing 2.93 warned about.
#:
#: ⚠️⚠️ The catchcopy here is the counted string 0x6208 sends back, NOT the
#: 21-byte fixed field the character record spends on its own catchCopy. See
#: MAX_CATCHCOPY for why nothing pads it.

#: The 勧誘 handshake, measured with the shape reader and the field-name extractor:
#:
#:   0x6218 targetId u32   the 「グループ登録申込み」 icon in the PC 交流メニュー
#:   0x6219 (empty)        the inviter's receipt
#:   0x621A reason u8      refused before the other side ever hears
#:   0x621B senderId u32   the other side is asked; senderId is the *inviter*
#:   0x621C answer u8      they accept  -- ⚠️ no id in it, see below
#:   0x621D reason u8      they decline -- ⚠️ no id in it either
#:   0x621E (empty)        it happened; a bell, the roster comes from 0x6207
#:   0x621F (empty)        the inviter withdraws -- ⚠️ no id in it either
#:
#: ⚠️⚠️ Three of those carry no charaId at all, which is a statement about the
#: shape of the feature and not an omission: a character can be one end of at
#: most one application at a time, so the ids live in the session and the wire
#: does not repeat them. friends' 0x6407 does carry one; this family does not.
HANDLED = frozenset({
    MSG_CL_QUERY_CHARA_GROUP_INFO,
    MSG_CL_REQUEST_CHARA_GROUP_UPDATE,
    MSG_CL_REQUEST_CHARA_GROUP_INVITE_REQUEST,
    MSG_CL_OK_CHARA_GROUP_INVITE_RESPONSE,
    MSG_CL_NG_CHARA_GROUP_INVITE_RESPONSE,
    MSG_CL_REQUEST_CHARA_GROUP_INVITE_CANCEL,
    MSG_CL_REQUEST_CHARA_GROUP_KICK,
})

#: 「仲良しグループ」は１５人まで登録できます (p05_05 §3). The client checks
#: nothing about the size before it sends 0x6218 -- the icon is live whatever
#: the roster holds -- so this end is the only place the manual's number can be
#: enforced.
MAX_MEMBERS = 15

#: ⚠️ INVENTED, like every other reason byte here. See mps_session.NG_REASON.
REASON = 0

#: 15 for a 仲良しグループ, 30 once it is a 同好会 (p05_05 §3). Enforced only as
#: a refusal on join; nothing on the wire has been seen to carry it.
MEMBER_LIMIT = 15
CLUBLIKE_MEMBER_LIMIT = 30


#: How much キャッチコピー this end will keep. ⚠️ INVENTED, and deliberately
#: larger than anything the client has been seen to send rather than fitted to
#: it: the wire field is counted, so unlike friendGroupName nothing in the
#: protocol caps it, and a cap that is too small does not fail loudly -- it
#: silently shortens what the player typed and makes the 「type it, press
#: ［更 新］, reopen the window」 round trip look like it half-worked.
#:
#: ⭐ The one length that *is* measured is what arrives: _group_update logs it,
#: so the client's own edit-box limit falls out of the first update anyone does
#: instead of having to be read out of a dialog resource.
MAX_CATCHCOPY = 64


def name_bytes(text: str) -> bytes:
    """A group name as the record wants it: cp932, NUL-padded to 21 bytes.

    Same codec and same padding as every other name this server writes; see
    characters.marker_names for the one place the width matters more than the
    text does.
    """
    raw = text.encode("cp932", "replace")
    return raw.ljust(GROUP_NAME_LEN, b"\x00")[:GROUP_NAME_LEN]


def catchcopy_bytes(text: str) -> bytes:
    """A キャッチコピー as this server keeps it: cp932, no padding.

    ⚠️ Not name_bytes: the group name is a 21-byte field in the character
    record and has to be padded to that width, but the catchcopy only ever
    travels as a counted string (0x620A in, 0x6208 out) and padding it would be
    inventing a width the protocol does not have.
    """
    return text.encode("cp932", "replace").split(b"\x00")[0][:MAX_CATCHCOPY]


class Group:
    """One 仲良しグループ: a name, a leader, and who is in it."""

    def __init__(
        self,
        group_id: int,
        name: bytes,
        leader: int,
        members: "list[int] | None" = None,
        public: int = 1,
        clublike: int = 0,
        catchcopy: bytes = b"",
    ) -> None:
        self.id = group_id
        self.name = name.ljust(GROUP_NAME_LEN, b"\x00")[:GROUP_NAME_LEN]
        self.leader = leader
        self.members: list[int] = list(members if members is not None else [leader])
        self.public = public & 0xFF
        self.clublike = clublike
        self.catchcopy = catchcopy.split(b"\x00")[0][:MAX_CATCHCOPY]

    @property
    def limit(self) -> int:
        return CLUBLIKE_MEMBER_LIMIT if self.clublike else MEMBER_LIMIT

    def to_json(self) -> dict:
        return {
            "name": self.name.split(b"\x00")[0].decode("cp932", "replace"),
            "leader": f"0x{self.leader:08x}",
            "members": [f"0x{member:08x}" for member in self.members],
            "public": self.public,
            "clublike": self.clublike,
            "catchcopy": self.catchcopy.decode("cp932", "replace"),
        }

    def label(self) -> str:
        shown = self.name.split(b"\x00")[0].decode("cp932", "replace") or "(unnamed)"
        return f"#{self.id} {shown} ({len(self.members)}/{self.limit})"


class GroupBook:
    """Every group on the server, plus who has passed the リーダー試験.

    ⚠️ The qualification set lives here rather than beside the exam scores it
    belongs to, because right now nothing awards it: the リーダー試験 is an NPC
    event this server does not run, so the only way in is the console. When the
    event exists, this set is what it should write to.

    Every mutation writes the file, for the reason charaids.CharaIndex gives.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "groups.json"
        self.groups: dict[int, Group] = {}
        self.qualified: set[int] = set()
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[groups] ignoring unreadable {self.path}: {exc}")
            return
        if not isinstance(raw, dict):
            return
        for key in raw.get("qualified", []):
            try:
                self.qualified.add(int(str(key), 16))
            except ValueError:
                print(f"[groups] ignoring unreadable qualified id {key!r}")
        for key, body in (raw.get("groups") or {}).items():
            try:
                group_id = int(str(key), 16)
            except ValueError:
                print(f"[groups] ignoring unreadable group id {key!r}")
                continue
            if not isinstance(body, dict):
                continue
            members = []
            for member in body.get("members", []):
                try:
                    members.append(int(str(member), 16))
                except ValueError:
                    print(f"[groups] ignoring unreadable member {member!r}")
            try:
                leader = int(str(body.get("leader", "0x0")), 16)
            except ValueError:
                leader = members[0] if members else 0
            self.groups[group_id] = Group(
                group_id,
                name_bytes(str(body.get("name", ""))),
                leader,
                members,
                int(body.get("public", 1)),
                int(body.get("clublike", 0)),
                catchcopy_bytes(str(body.get("catchcopy", ""))),
            )

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "qualified": [f"0x{one:08x}" for one in sorted(self.qualified)],
                    "groups": {
                        f"0x{group_id:08x}": group.to_json()
                        for group_id, group in sorted(self.groups.items())
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- the four fields --------------------------------------------------

    def of(self, chara_id: int) -> "Group | None":
        """The group this character is in, or None -- 「グループ未所属」."""
        for group in self.groups.values():
            if chara_id in group.members:
                return group
        return None

    def fields(self, chara_id: int) -> "tuple[bytes, int, int, int]":
        """``friendGroupName, friendGroupId, leaderAuthority, leaderQualification``.

        ⭐ The whole point of routing every record through one call: a character
        in no group answers exactly the bytes this server sent before groups
        existed, apart from the one correction round 143 measured -- see
        characters.NO_GROUP.
        """
        group = self.of(chara_id)
        return (
            group.name if group is not None else b"\x00" * GROUP_NAME_LEN,
            group.id if group is not None else NO_GROUP,
            1 if group is not None and group.leader == chara_id else 0,
            1 if chara_id in self.qualified else 0,
        )

    # -- mutations --------------------------------------------------------

    def qualify(self, chara_id: int, on: bool = True) -> bool:
        """Pass or revoke the リーダー試験. False if it was already that way."""
        if on == (chara_id in self.qualified):
            return False
        if on:
            self.qualified.add(chara_id)
        else:
            self.qualified.discard(chara_id)
        self._save()
        return True

    def _mint(self) -> int:
        """A fresh group id. Never zero: zero is what 無所属 is written as."""
        return max(self.groups, default=0) + 1

    def create(self, leader: int, name: bytes, public: int = 1) -> "Group | None":
        """Found a group. None if this character is already in one."""
        if self.of(leader) is not None:
            return None
        group = Group(self._mint(), name, leader, public=public)
        self.groups[group.id] = group
        self._save()
        return group

    def join(self, group_id: int, chara_id: int) -> bool:
        group = self.groups.get(group_id)
        if group is None or self.of(chara_id) is not None:
            return False
        if len(group.members) >= group.limit:
            return False
        group.members.append(chara_id)
        self._save()
        return True

    def update(self, group_id: int, public: int, catchcopy: bytes) -> bool:
        """［更 新］: the 公開 dropdown and the キャッチコピー box, 0x620A.

        ⚠️ ``public`` is kept as the byte that arrived rather than clamped to
        0/1. The dropdown has two entries and 1 is 公開 (round 142 read that off
        the window), but a value this end invents cannot be told apart from a
        value the client chose, and round-tripping the byte is what would make a
        third state visible if there is one.
        """
        group = self.groups.get(group_id)
        if group is None:
            return False
        group.public = public & 0xFF
        group.catchcopy = catchcopy.split(b"\x00")[0][:MAX_CATCHCOPY]
        self._save()
        return True

    def kick(self, group_id: int, chara_id: int) -> bool:
        """除名, 0x6226. False if there is nobody there to remove.

        ⚠️ The leader is not removable this way even though the roster lists
        them and the button does not grey itself out on their row: 解散 (0x6203)
        and 引継 (0x620D) are the two messages that exist for a leader leaving,
        and letting 除名 do it as well would leave a group with no one who can
        kick or disband -- the same hole GroupBook.leave avoids.
        """
        group = self.groups.get(group_id)
        if group is None or chara_id == group.leader:
            return False
        if chara_id not in group.members:
            return False
        group.members.remove(chara_id)
        self._save()
        return True

    def leave(self, chara_id: int) -> bool:
        """脱退. The leader leaving takes the group with them for now.

        ⚠️ A decision, not a reading: the manual hands leadership over through
        引継 (0x620D..0x6217), a handshake this server does not answer yet, and a
        group whose leader is gone would have no one who can kick or disband it.
        """
        group = self.of(chara_id)
        if group is None:
            return False
        if group.leader == chara_id:
            return self.disband(group.id)
        group.members.remove(chara_id)
        self._save()
        return True

    def disband(self, group_id: int) -> bool:
        if group_id not in self.groups:
            return False
        del self.groups[group_id]
        self._save()
        return True

    def forget(self, chara_id: int) -> None:
        """Take a deleted character out of the group and the qualified set."""
        touched = chara_id in self.qualified
        self.qualified.discard(chara_id)
        group = self.of(chara_id)
        if group is not None:
            if group.leader == chara_id:
                del self.groups[group.id]
            else:
                group.members.remove(chara_id)
            touched = True
        if touched:
            self._save()

    def summary(self) -> str:
        if not self.groups and not self.qualified:
            return "(no groups)"
        return (
            f"{len(self.groups)} group(s), "
            f"{len(self.qualified)} qualified leader(s)"
        )


def result_params(group: Group, roster: "list[tuple[int, bytes, bytes, int, int]]") -> bytes:
    """MsgSvResultCharaGroupInfo (0x6208).

    ⭐ The reader's slot widths, off the shape reader, are what settles the shape --
    and they disagree with the field list alone in one place:

        1 + 1 + 2 + 0 + 2 + 4 + 11 + 11 + 2 + 1 + 4

    ``catchcopy`` is 2 + 0, i.e. a u16 count and then that many bytes, the same
    counted-string convention chat.notify_params writes -- NOT the fixed 21-byte
    field the character record spends on it. The 2 after it is the charaInfo
    count, and the six that follow are one member each.

    ⚠️ And note what is *not* in here: the group's name. The window gets that
    from the character's own record (friendGroupName in 0x6501), which is why
    the name has to be sent there whether or not this message is ever asked for.

    ``roster`` is (charaId, familyName, firstName, sex, onlineFlag) per member.
    """
    catchcopy = group.catchcopy + b"\x00"
    out = struct.pack(">BB", group.clublike, group.public)
    out += struct.pack(">H", len(catchcopy)) + catchcopy
    out += struct.pack(">H", len(roster))
    for chara_id, family, first, sex, online in roster:
        out += struct.pack(">I", chara_id)
        out += family.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        out += first.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        out += struct.pack(">HB", sex, online)
    out += struct.pack(">I", group.leader)
    return out
