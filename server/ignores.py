"""受信拒否: the list of people whose addressed messages never arrive.

The feature is the game's, and the game documents it itself. `/command` prints a
section of its own for it, two entries out of the client's own help text::

    ■ 受信拒否コマンド
    ［ /ignore [on/off] [苗字 名前] ］ … 指定したユーザーからの
        『名前指定でのメッセージ』や各種申込みを拒否する（on）／拒否を解除する（off）
    ［ /refer ］ … 受信拒否しているユーザーを、会話ログウィンドウに表示する

So the entry is typed rather than clicked: the two commands are in the client's
first block of player commands, and each reaches the wire through one message.
Nothing else in the client sends these three -- each command handler is
referenced once by the command table, and each request object is built in one
place, its own handler.

    0x5E00 MsgClRequestIgnoreReceive      familyName[11], firstName[11]   /ignore on
    0x5E01 MsgSvOkIgnoreReceive           -
    0x5E02 MsgSvNgIgnoreReceive           reason
    0x5E03 MsgClRequestListenReceive      familyName[11], firstName[11]   /ignore off
    0x5E04 MsgSvOkListenReceive           -
    0x5E05 MsgSvNgListenReceive           reason
    0x5E06 MsgClQueryIgnoreReceiveList    -                               /refer
    0x5E07 MsgSvResultIgnoreReceiveList   u16 count, entries of 22 bytes

⭐ The 22 bytes of an entry are the same two 11-byte names the request carries,
which is why this family addresses people by 氏名 and not by charaId: it is the
one place in the protocol where a player names somebody who need not be on
screen, in the address book, or even logged in.

WHAT THE PLAYER SEES IS THE CLIENT'S OWN TEXT
---------------------------------------------
Nothing here sends a sentence on the happy path. The client holds all of it --
「受信拒否を設定しました。」, 「受信拒否を解除しました。」, the 受信拒否 heading
and the 受信拒否%1% line /refer draws per entry -- and picks one by which of the
six answers arrives. So Ok with an empty body is the whole of a success.

⚠️⚠️ THE POINT OF THE FEATURE IS SOMEWHERE ELSE ENTIRELY
--------------------------------------------------------
A list nobody consults is a list that does nothing, and the row that consults it
is in the chat family: 0xFF00 reason 4, 「指定されたキャラクターは、現在受信を
拒否しています。」 -- the one sentence in the whole error table that mentions
受信拒否. It is reachable from every Error that redirects to 0xFF00, and the two
this server can honestly earn it with are the addressed channels, 0x4602
友達チャット and 0x4A02 内緒話. That is exactly what the help text scopes it to,
『名前指定でのメッセージ』. See chat.ERROR_CHAT_IGNORED.

⚠️ 各種申込み -- the other half of that sentence -- is NOT enforced. Not an
oversight and not a shortcut: 友達登録, トレード, グループ勧誘 and
ツーショット申込み each refuse out of a list of their own, and not one of those
lists holds a row that says 受信拒否. Refusing an application here would mean
picking somebody else's sentence to say something it does not say. What the
original did with an application to somebody who had ignored the applicant is
unmeasured, and stays that way until a row or a screen settles it.

THE REFUSALS
------------
0x5E02 and 0x5E05 read a byte out of four rows each, identical between them::

    0  キャラクター情報が不正です。
    1  指定されたキャラクターは存在しません。
    2  未使用：：：サーバーとの通信に失敗しました。
    3  未使用：：：未定義のエラーが発生しました。

Two are usable, and the developers' own 「未使用」 marks the other two as never
sent -- the same reading naming.py makes of the character-create list.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from characters import NAME_LEN, parse_create_info

MSG_CL_REQUEST_IGNORE_RECEIVE = 0x5E00
MSG_SV_OK_IGNORE_RECEIVE = 0x5E01
MSG_SV_NG_IGNORE_RECEIVE = 0x5E02
MSG_CL_REQUEST_LISTEN_RECEIVE = 0x5E03
MSG_SV_OK_LISTEN_RECEIVE = 0x5E04
MSG_SV_NG_LISTEN_RECEIVE = 0x5E05
MSG_CL_QUERY_IGNORE_RECEIVE_LIST = 0x5E06
MSG_SV_RESULT_IGNORE_RECEIVE_LIST = 0x5E07

#: Everything this module answers. The query is in here with the two commands
#: for the reason friends.HANDLED gives for keeping its own list query: a list
#: that can be read but not written is not the feature.
HANDLED = frozenset(
    {
        MSG_CL_REQUEST_IGNORE_RECEIVE,
        MSG_CL_REQUEST_LISTEN_RECEIVE,
        MSG_CL_QUERY_IGNORE_RECEIVE_LIST,
    }
)

#: One row of the /refer list: the two 11-byte names and nothing else. The
#: client's reader takes 22 bytes an entry.
ENTRY_SIZE = NAME_LEN + NAME_LEN

#: 「キャラクター情報が不正です。」 -- for a body too short to hold two names.
#: Exact: a request that does not parse has no 氏名 in it, which is what the
#: row says.
NG_BAD_INFO = 0
#: 「指定されたキャラクターは存在しません。」 -- nobody on this server answers to
#: that 氏名. Exact, and the reason the name is resolved at all.
NG_NO_SUCH_CHARA = 1

#: ⚠️⚠️ THERE IS NO THIRD REFUSAL, AND THAT IS THE EVIDENCE, NOT A GAP.
#: Two rows are usable and the other two carry the developers' 「未使用」 marker,
#: so the list of what the original refused is two items long -- the same
#: reading naming.py makes of the character-create list. Three cases that would
#: obviously want a sentence therefore do not get one here:
#:
#:   /ignore on somebody already on the list   no row says 「already」
#:   /ignore off somebody who is not on it     no row says 「not on it」
#:   /ignore on oneself                        no row says 「自分自身」, and
#:                                             友達登録 has one (friends.NG_SELF)
#:                                             precisely because it needs it
#:
#: All three are answered Ok. The first two leave the list saying what the
#: player asked it to say, and the third leaves a row that costs its owner one
#: thing only: a 内緒話 addressed at themselves comes back refused.


def parse_name(params: bytes) -> "tuple[bytes, bytes] | None":
    """``(familyName, firstName)`` out of a 0x5E00 / 0x5E03 body, or None.

    One reader for both because the client has one writer for both: the same
    22-byte copy stands behind each of the two request objects.
    """
    if len(params) < ENTRY_SIZE:
        return None
    return params[:NAME_LEN], params[NAME_LEN:ENTRY_SIZE]


def entry(info: bytes) -> bytes:
    """One 22-byte row, built from the character's own create block.

    The same source friends.entry uses, and for the same reason: /refer must not
    list somebody under a name that disagrees with the one over their head. It
    also means the list answers with the canonical split of a 氏名 rather than
    with wherever the player who typed the command happened to put the space --
    see naming.full_name for why those two need not be the same.
    """
    fields = parse_create_info(info)
    out = b""
    for key in ("familyName", "firstName"):
        raw = fields[key]
        assert isinstance(raw, bytes)
        out += raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    if len(out) != ENTRY_SIZE:
        raise AssertionError(f"entry is {len(out)}B, reader wants {ENTRY_SIZE}")
    return out


def list_params(rows: "list[bytes]") -> bytes:
    """``u16 count`` then the rows. An empty list is two zero bytes."""
    return struct.pack(">H", len(rows)) + b"".join(rows)


class IgnoreBook:
    """Who refuses to hear from whom, for the whole server.

    Directed, one key per owner, exactly like friends.FriendBook -- and here the
    direction is the whole point rather than a detail of 消去: 受信拒否 is one
    player's decision about their own inbox and says nothing about the other
    side's. The far side is never told, either; the family has no Notify.

    ⚠️ Stored by charaId although the wire addresses by 氏名. The name is
    resolved once, when the command is accepted, and what is kept is whom it
    resolved to. A stored name would go stale the moment a row was rebuilt from
    a record, and would compare wrongly against a 氏名 split in a different
    place (naming.full_name).

    ⚠️ INVENTED, one decision and the only one in this file: THAT THE LIST
    SURVIVES A LOGOUT. Nothing says how long 受信拒否 lasts -- 「現在受信を拒否
    しています」 is the only word on it anywhere, and nothing at login hands the
    client a copy, the four wire options carrying no 受信拒否 flag
    (options.py), so this end is the only thing that could remember. Kept
    because /refer exists to review a list the player need not have built in
    this sitting, and because a list that emptied itself every evening would
    make 解除 a button nobody would ever need to press.

    Every mutation writes the file, for the reason charaids.CharaIndex gives.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "ignores.json"
        self.edges: dict[int, set[int]] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[ignores] ignoring unreadable {self.path}: {exc}")
            return
        if not isinstance(raw, dict):
            return
        for key, listed in raw.items():
            try:
                chara_id = int(str(key), 16)
            except ValueError:
                print(f"[ignores] ignoring unreadable charaId key {key!r}")
                continue
            if not isinstance(listed, list):
                continue
            for other in listed:
                try:
                    self.edges.setdefault(chara_id, set()).add(int(str(other), 16))
                except ValueError:
                    print(f"[ignores] ignoring unreadable entry {other!r}")

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

    # -- the list ---------------------------------------------------------

    def of(self, chara_id: int) -> list[int]:
        """Whom this character is refusing, in charaId order."""
        return sorted(self.edges.get(chara_id, ()))

    def holds(self, owner: int, other: int) -> bool:
        """Is ``other`` on ``owner``'s list -- i.e. does ``owner`` refuse them?"""
        return other in self.edges.get(owner, ())

    def add(self, owner: int, other: int) -> bool:
        """/ignore on. False if the row was already there.

        ⚠️ Nothing is refused here -- not a repeat, and not oneself. See the
        refusal rows above for why the absence of a sentence is read as the
        absence of a rule.
        """
        if other in self.edges.setdefault(owner, set()):
            return False
        self.edges[owner].add(other)
        self._save()
        return True

    def remove(self, owner: int, other: int) -> bool:
        """/ignore off. False if the row was not there -- which is not refused."""
        if not self.holds(owner, other):
            return False
        self.edges.get(owner, set()).discard(other)
        self._save()
        return True

    def forget(self, chara_id: int) -> None:
        """Take a deleted character off both ends of every list.

        Their own list goes because they are gone; the rows naming them go for
        the reason friends.FriendBook.forget gives -- a charaId is never handed
        out twice, so the row could never name anybody again, and /refer builds
        its rows out of records and would draw nothing at all for it.
        """
        changed = self.edges.pop(chara_id, set()) != set()
        for listed in self.edges.values():
            if chara_id in listed:
                listed.discard(chara_id)
                changed = True
        if changed:
            self._save()

    def summary(self) -> str:
        rows = sum(len(listed) for listed in self.edges.values())
        return f"{rows} 受信拒否 row(s)" if rows else "(nobody is ignoring anybody)"
