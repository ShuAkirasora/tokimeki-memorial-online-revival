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

The graph is **directed** -- see FriendBook.unlink for the sentence in the
manual that settles it -- and lives in one file for the whole server rather than
one per account, because 友達登録 writes two books at once and a per account
file would have to be written twice and could disagree with itself.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import refusals
from characters import NAME_LEN, parse_create_info

MSG_CL_QUERY_FRIEND_LIST = 0x6400
MSG_SV_RESULT_FRIEND_LIST = 0x6401
MSG_SV_ERROR_FRIEND_LIST = 0x6402
# ⭐⭐⭐ 0x6402 IS NOT SENT (round 417). It was explicitly kept OUT of
# mps_session's twelve, on the grounds that one of its four sentences reads like
# a rule rather than a backend fault:
#
#   reason 0  キャラクターの情報が不正です。
#   reason 1  アドレス帳に登録されたキャラクター一覧の取得に失敗しました。
#   reason 2  未使用：：：…   reason 3  未使用：：：…
#
# ⚠⚠ That reading asked the wrong question. 「…が不正です」 is only a rule
# when there is something in the request for it to be about, and
# `Output_MsgClQueryFriendList`'s dump (0x8D35B0) prints the message name and
# **no fields**: 0x6400 carries no body. The module docstring says the same
# thing from the other side -- opening アドレス帳 sends nothing, the client
# asks this once at login and never again -- so the only キャラクター this
# refusal could be about is the asker's own record, which this end has in
# memory before the request arrives.
#
# ⇒ Both live arms are the original's store answering badly: reason 1 says so
# outright, and reason 0 is the same fault one step earlier. This is the shape
# round 414 used on 0x5603/0x6C03 -- an empty request makes a bad-parameter arm
# about a parameter that does not exist -- and it is what settles this id.
# UNSENT 0x6402 -- FriendList: an empty request, so both live sentences are the original's store failing.
MSG_CL_REQUEST_FRIEND_ADD_REQUEST = 0x6403
MSG_SV_OK_FRIEND_ADD_REQUEST = 0x6404
MSG_SV_NG_FRIEND_ADD_REQUEST = 0x6405
MSG_SV_REQUEST_FRIEND_ADD_RESPONSE = 0x6406
#: ⚠️ 1 = yes, measured in round 146: a client that already held the asker in
#: its address book answered 0x6407 with answer=1 without showing its dialog at
#: all. The same byte is the yes in both 仲良しグループ handshakes, where it is
#: also what carries the *no* -- see groups.ANSWER_YES for why that matters.
ANSWER_YES = 1

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
#: 4 + 11 + 11 + 2, and the shape reader reads 28 off the client's own loop.
ENTRY_SIZE = 4 + NAME_LEN + NAME_LEN + 2

# ---------------------------------------------------------------------------
# The refusals. ⚠️⚠️ NOTHING BELOW IS MADE UP ANY MORE (round 323) -- every byte
# is a row of error_message.bin, and which list a row comes out of was read off
# the client's own redirect function (refusals.py). This family spends its bytes
# on three different lists:
#
#   0x6405 / 0x640C  -> 0xFF07, the group family's list. ⚠️ Not a mistake in
#                       this end: the image ships 0xFF08 with 友達登録 wording
#                       and produces it nowhere, so the original showed these
#                       refusals out of the group list too.
#   0x640D           -> 0xFF04, shared by every 申し込み subsystem's Notify.
#   0x6410           -> its own id, no redirect, five rows of its own.
#
# ⚠️ Where a row says exactly what happened it is used; where none does, the
# comment says so. A judgement call named as one can be replaced later; a
# placeholder zero looked like a decision and said nothing on screen.
# ---------------------------------------------------------------------------

#: 「自分自身に申し込むことはできません。」 -- exact.
NG_SELF = refusals.NG_SELF
#: 「キャラクターの情報が不正です。」 for a target id that is 0 or nobody, and
#: for one who is offline. ⚠️ The second is a judgement: no row in 0xFF07 says
#: 「offline」, and トレード picked the same row for the same case (trade.py's
#: REASON_BAD_CHARA), so the two families at least say the same thing.
NG_BAD_CHARA = refusals.NG_BAD_CHARA
#: 「指定されたキャラクターは、現在申し込みを受けられる状態ではありません。」
#: ⚠️ A judgement, for 「they are already in your アドレス帳」: 0xFF07 has no row
#: for that, and a real client greys the menu entry out (measured round 214), so
#: this branch is a guard rather than something a player can reach.
NG_TARGET_BUSY = refusals.NG_TARGET_BUSY
#: 「指定されたキャラクターは、現在申し込みを受け付けていません。」 for 取り下げ
#: with nothing open. ⚠️ A judgement, and the same slot number トレード uses for
#: the same case out of its own list (0xFF09's row 3, worded 受けていません).
NG_NOTHING_OPEN = refusals.NG_TARGET_NOT_ACCEPTING

#: 0x640D's two, out of 0xFF04. Both exact: the family has no 「they said no」
#: message of its own, so the sentence is what carries the difference between
#: 「断られました」 and 「キャンセルされました」.
NOTIFY_DECLINED = refusals.NOTIFY_DECLINED
NOTIFY_CANCELLED = refusals.NOTIFY_CANCELLED

# 0x6410 消去's own five rows. It is in no redirect, so these are read under the
# message's own id.
DEL_BAD_CHARA = 0      # キャラクターの情報が不正です。
DEL_BAD_SELECTION = 1  # 選択されたキャラクターの情報が不正です。
DEL_NO_LIST = 2        # アドレス帳に登録されたキャラクター一覧の取得に失敗しました。
DEL_NOT_IN_BOOK = 3    # 選択されたキャラクターはアドレス帳に登録されていません。
DEL_UNDEFINED = 4      # 未使用：：：未定義のエラーが発生しました。

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

    ⚠️ Edges are directed, and the file has always stored them that way: one
    key per owner, one list of whoever is in that owner's book. 友達登録 writes
    both directions at once -- 「相手が承諾すると、相手の情報がアドレス帳に登録され」
    -- but 消去 writes only one, which is what makes the direction matter. See
    link and unlink; every lookup stays a dict hit instead of a scan.

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
        """友達登録: write both books. False if neither of them changed.

        ⚠️⚠️ Both directions are written even when one of them is already
        there, and that matters now that 消去 is one-way: after ``one`` drops
        ``other``, ``other``'s book still lists ``one``, so a re-registration
        arrives with half the pair already in place. Returning early on the
        half that exists would leave the other half missing and put the two of
        them back in exactly the state the request was meant to end.
        """
        if one == other:
            return False
        changed = other not in self.edges.setdefault(one, set())
        changed |= one not in self.edges.setdefault(other, set())
        if not changed:
            return False
        self.edges[one].add(other)
        self.edges[other].add(one)
        self._save()
        return True

    def unlink(self, one: int, other: int) -> bool:
        """消去: one direction only -- ``one``'s book drops ``other``.

        ⭐⭐⭐ The manual settles this in one sentence (p05_05 §2):
        「アドレス帳から名前を消去することができますが、**自分のアドレス帳から
        消去しても、相手のアドレス帳からは消去されません**」. So a book listing
        somebody who no longer lists them is not a hole -- it is the design.

        ⚠️⚠️ This end used to drop both, on the reasoning that the family has no
        MsgSvNotifyFriendDel and nothing could ever repair the one-sided state.
        Read the other way round, the missing notify is the *evidence*: there is
        no message telling the far side because the far side does not change.
        Round 149 turned that invention back into a reading.

        ⭐ What the asymmetry costs the players is exactly what the wire allows:
        ``one`` can ask again (the 0x6403 gate reads linked(me, target), which is
        directed too), while ``other`` cannot -- their book still has the row, so
        they are told 「already friends」. Only the side that deleted can undo it.
        """
        if not self.linked(one, other):
            return False
        self.edges.get(one, set()).discard(other)
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
