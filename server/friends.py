"""友達登録 and the アドレス帳 window behind the toolbar's sixth icon.

What the window is, measured rather than guessed (round 141, one real client and
one scripted second player standing next to each other):

  * Opening アドレス帳 sends **nothing**. The list it draws is the one the
    client was handed at login, in MsgSvResultFriendList, and the two columns on
    screen -- 氏名 and 性別 -- are exactly the fields of a 28-byte entry. So the
    only lever this end has over that window is the answer to a query the client
    makes once, before the player can see anything.
  * The 所属グループ box at the top of the same window reads 未所属 out of the
    character's own record, not out of this list.
  * A friend is made through the PC 交流メニュー -- right-click somebody, pick
    「友達登録申込み」 -- and that is a client-drawn menu, so nothing on this end
    can open it. What it puts on the wire is MsgClRequestFriendAddRequest with
    one u32: whom.

The handshake the message names lay out. SEEN means a real client put it on the
wire or took it and did the right thing on screen:

  0x6403 targetId          SEEN  the menu item sends it
  0x6404 targetId          SEEN  the requester's receipt
  0x6405 targetId, reason        refused before the other side ever hears
  0x6406 targetId          SEEN  the other side is asked; targetId is the *asker*
  0x6407 targetId, answer  SEEN  they accept
  0x6408 targetId, reason        they decline
  0x6409 targetId          SEEN  it happened -- one id, no name, no sex
  0x640A/B/C/D                   the asker withdraws before they answer
  0x640E/F/10              SEEN  the 消去 button at the bottom of the window
  0x6411/12 charaId,state        is this friend online

⚠️ 0x6409 carrying nothing but an id is the interesting one: the row the window
needs has a name and a sex in it, and this message has neither. Measured: the
client does **not** re-query. No second MsgClQueryFriendList follows, and the
row appears in the window all the same -- it already holds the record of
whoever it just agreed with, because it right-clicked them. So this notify is a
bell and not a payload.

⭐ That is also why "the row showed up" does not prove the store works. It took
a second login -- with the other player not even connected -- to see the window
filled from MsgSvResultFriendList. The two have to be checked separately.

The graph is symmetric and lives in one file for the whole server rather than
one per account, because an edge belongs to two accounts at once and a per
account file would have to be written twice and could disagree with itself.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from characters import NAME_LEN, parse_create_info

MSG_CL_QUERY_FRIEND_LIST = 0x6400
MSG_SV_RESULT_FRIEND_LIST = 0x6401
MSG_SV_ERROR_FRIEND_LIST = 0x6402
MSG_CL_REQUEST_FRIEND_ADD_REQUEST = 0x6403
MSG_SV_OK_FRIEND_ADD_REQUEST = 0x6404
MSG_SV_NG_FRIEND_ADD_REQUEST = 0x6405
MSG_SV_REQUEST_FRIEND_ADD_RESPONSE = 0x6406
MSG_CL_OK_FRIEND_RESPONSE = 0x6407
MSG_CL_NG_FRIEND_RESPONSE = 0x6408
MSG_SV_NOTIFY_FRIEND_ADD = 0x6409
MSG_CL_REQUEST_FRIEND_ADD_CANCEL = 0x640A
MSG_SV_OK_FRIEND_ADD_CANCEL = 0x640B
MSG_SV_NG_FRIEND_ADD_CANCEL = 0x640C
MSG_SV_NOTIFY_FRIEND_ADD_CANCEL = 0x640D
MSG_CL_REQUEST_FRIEND_DEL = 0x640E
MSG_SV_OK_FRIEND_DEL = 0x640F
MSG_SV_NG_FRIEND_DEL = 0x6410
MSG_CL_QUERY_FRIEND_STATE = 0x6411
MSG_SV_RESULT_FRIEND_STATE = 0x6412

#: Everything this module answers. The list query is deliberately in here too,
#: even though it used to be a two-zero-byte stub: an answer built from the
#: store and an answer that is always empty are the same message, and leaving
#: the stub in place beside a store that can now hold rows is how a locker gets
#: swallowed (that is exactly what 0x0406 did before it was answered for real).
HANDLED = frozenset(
    {
        MSG_CL_QUERY_FRIEND_LIST,
        MSG_CL_REQUEST_FRIEND_ADD_REQUEST,
        MSG_CL_OK_FRIEND_RESPONSE,
        MSG_CL_NG_FRIEND_RESPONSE,
        MSG_CL_REQUEST_FRIEND_ADD_CANCEL,
        MSG_CL_REQUEST_FRIEND_DEL,
        MSG_CL_QUERY_FRIEND_STATE,
    }
)

#: One row of the アドレス帳: u32 charaId, the two 11-byte names, u16 sex.
#: 4 + 11 + 11 + 2, and listshape.py reads 28 off the client's own loop.
ENTRY_SIZE = 4 + NAME_LEN + NAME_LEN + 2

#: ⚠️ INVENTED, like every other reason byte this server sends. The refusals in
#: this family each spend one byte on a reason and nothing in the image visibly
#: reads it back, so zero goes out because the reader consumes a byte either
#: way. See mps_session.NG_REASON for the same argument at length.
REASON = 0

#: MsgSvResultFriendState's ``state``. Two values are needed and the client's
#: own vocabulary elsewhere -- the roster's onlineFlag -- is a flag, so this is
#: read as one. ⚠️ Which way round it is has not been measured; nothing on
#: screen has shown a friend's state yet because the client has never sent
#: 0x6411 here.
STATE_OFFLINE = 0
STATE_ONLINE = 1


def entry(chara_id: int, info: bytes) -> bytes:
    """One 28-byte row, built from the character's own create block.

    The same source the roster and 生徒情報 are built from, so a friend cannot
    be listed under a name that disagrees with the one over their head.
    """
    fields = parse_create_info(info)
    out = struct.pack(">I", chara_id)
    for key in ("familyName", "firstName"):
        raw = fields[key]
        assert isinstance(raw, bytes)
        out += raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    out += struct.pack(">H", fields["sex"])
    if len(out) != ENTRY_SIZE:
        raise AssertionError(f"entry is {len(out)}B, reader wants {ENTRY_SIZE}")
    return out


def list_params(rows: "list[bytes]") -> bytes:
    """``u16 count`` then the rows. An empty book is two zero bytes."""
    return struct.pack(">H", len(rows)) + b"".join(rows)


class FriendBook:
    """Who is in whose アドレス帳, for the whole server.

    Edges are symmetric: 友達登録 needs both sides to agree, and the manual says
    so in as many words -- 「相手が承諾すると、相手の情報がアドレス帳に登録され」.
    Storing one edge as two entries costs a few bytes and makes every lookup a
    dict hit instead of a scan.

    Every mutation writes the file, for the reason charaids.CharaIndex gives:
    holding it in memory until exit turns a crash into a save file that has
    forgotten who agreed to what.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "friends.json"
        self.edges: dict[int, set[int]] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[friends] ignoring unreadable {self.path}: {exc}")
            return
        if not isinstance(raw, dict):
            return
        for key, listed in raw.items():
            try:
                chara_id = int(str(key), 16)
            except ValueError:
                print(f"[friends] ignoring unreadable charaId key {key!r}")
                continue
            if not isinstance(listed, list):
                continue
            for other in listed:
                try:
                    self.edges.setdefault(chara_id, set()).add(int(str(other), 16))
                except ValueError:
                    print(f"[friends] ignoring unreadable entry {other!r}")

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    f"0x{chara_id:08x}": [f"0x{other:08x}" for other in sorted(listed)]
                    for chara_id, listed in sorted(self.edges.items())
                    if listed
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- the graph --------------------------------------------------------

    def of(self, chara_id: int) -> list[int]:
        """This character's address book, in minting order."""
        return sorted(self.edges.get(chara_id, ()))

    def linked(self, one: int, other: int) -> bool:
        return other in self.edges.get(one, ())

    def link(self, one: int, other: int) -> bool:
        """Register the two with each other. False if they already were."""
        if one == other or self.linked(one, other):
            return False
        self.edges.setdefault(one, set()).add(other)
        self.edges.setdefault(other, set()).add(one)
        self._save()
        return True

    def unlink(self, one: int, other: int) -> bool:
        """⚠️ Both directions, and that is a decision rather than a reading.

        The family has no MsgSvNotifyFriendDel: nothing tells the other side
        their book just lost a row. Keeping the edge one-way would leave a book
        listing somebody who no longer lists them, which the 消去 button cannot
        express and no message can repair. Symmetric it is -- and if a capture
        ever shows the original keeping the far side, this is the one line to
        change.
        """
        if not self.linked(one, other):
            return False
        self.edges.get(one, set()).discard(other)
        self.edges.get(other, set()).discard(one)
        self._save()
        return True

    def forget(self, chara_id: int) -> None:
        """Take a deleted character out of everybody's book.

        A charaId is never handed out twice (charaids.CharaIndex says why), so a
        stale edge would not point at a stranger -- it would point at nobody, and
        the row would quietly vanish from the list because there is no record to
        build it from. Dropping it here keeps the file honest instead.
        """
        listed = self.edges.pop(chara_id, set())
        for other in listed:
            self.edges.get(other, set()).discard(chara_id)
        if listed:
            self._save()

    def summary(self) -> str:
        pairs = sum(len(listed) for listed in self.edges.values()) // 2
        return f"{pairs} friendship(s)" if pairs else "(nobody is friends yet)"
