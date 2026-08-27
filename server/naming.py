"""名前チェック: whether a new character may be given the name it asks for.

`MsgClRequestCharacterCreate` (0x030C) carries three names -- 苗字, 名前 and
あだな -- and this server used to accept every one of them. The original did
not, and the client still carries the sentences it refused with. From
`error_message.bin`, all six rows the client holds for 0x030E
MsgSvNgCharacterCreate, in the client's own words and in its own order (`reason`
is the index into that list, so these numbers are read off the table rather than
chosen here):

    0  未使用：：：エラーなし
    1  手帳情報もしくはキャラクターの登録情報が不正です。
    2  不正もしくは使用不可能なキャラクター情報（氏名等）が入力されました。
    3  その生徒手帳には、既にキャラクターが登録されています。
    4  同じ氏名のキャラクターが既に存在しています。
    5  未使用：：：未定義のエラーが発生しました。

Two of them are the name rule (2 and 4), one is the notebook rule (3), and one
covers a request that did not parse (1). Rows 0 and 5 carry the developers' own
「未使用」 marker, which is the original saying it never sent them -- so a
refusal from here is never one of those two, and the byte this server used to
send for every refusal was row 0.

THE RULE IS THE VENDOR'S, WORD FOR WORD
---------------------------------------
⭐⭐⭐ The manual states it and works four examples (manual/p03_02):

    氏名が同じかどうかは、「苗字」＋「名前」が一致するかどうかで決まります。

      苗字＝コナミ太 ／ 名前＝郎     ×   (苗字＋名前 が同じ)
      苗字＝コナ     ／ 名前＝ミ太郎  ×   (同上)
      苗字＝コナミ   ／ 名前＝次郎    ○   (苗字 が同じでも 苗字＋名前 が違う)
      苗字＝ときめき ／ 名前＝太郎    ○   (名前 が同じでも 苗字＋名前 が違う)

So a 氏名 is ONE STRING -- the two fields concatenated with nothing between them
-- and where the player put the split does not matter. That is what full_name()
below builds, and it is the only thing either half of the rule compares.

⚠️ あだな is NOT part of a 氏名: the manual names 「苗字」・「名前」・「あだな」 as
three separate fields and defines 氏名 out of the first two only. Nothing here
looks at the third.

THE TWO TABLES
--------------
The names that are refused outright (reason 2) come from two tables in the
game's own data, 219 rows between them. Both hold the same shape -- a 苗字 and a
名前 whose concatenation is the row.

⭐ The client never loads either table. Neither has an accessor on the table
manager that installs the other 82, which is the same thing the shop's goods
table does, and it is why this rule is the server's to enforce: the client
cannot check what it was never given, and the sentence it shows arrives from
here. See the reverse-engineering notes for the table shapes.

WHAT SHIPS IS DIGESTS, AND THE NAMES ARE NOT IN THIS REPOSITORY
---------------------------------------------------------------
⭐⭐⭐ `reference/reserved_names.json` holds 219 SHA-256 hashes and no text.
That is the whole of what a server needs to enforce this rule: the rule is an
equality test on a complete 氏名, and a hash answers an equality test exactly and
answers nothing else. The names themselves are the game's, and a list of real
people's names is not this repository's to publish; a set of opaque values is.

⚠️ This does not generalise into a trick for shipping other lists. It works here
because the rule compares WHOLE STRINGS -- hash the input, look it up, done. A
rule that has to ask whether some substring occurs, which is what a chat word
filter is, cannot be built out of hashes at all. So nothing follows from this
file about any other table.

An operator may put a second file at `runtime/reserved_names.json` to reserve
names of their own. It is read the same way and merged on top, and it may be
written in plain text: it is theirs and it never leaves their machine.

WITHOUT EITHER FILE
-------------------
The duplicate rule (reason 4) still runs -- it compares against the characters
this server itself is holding and needs no table at all. The reserved-name rule
simply has nothing to match, and the loader says so at startup rather than
failing.

RESTORED and INVENTED
---------------------
Restored: the concatenation rule and its four worked examples, the four reason
codes and the sentences they select, the fact that あだな is outside 氏名, and
that the tables are the server's to hold.

⚠️ INVENTED: the ORDER the four checks run in. Nothing observed says which
refusal the original sent when a request broke two rules at once. The order is
the request alone first (1, then 2), then the whole server (4), then the one
account (3), so that the answer to "may I be called this" does not depend on who
is asking. Nothing else follows from it, and any order refuses the same set of
requests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import characters


# Reasons for 0x030E. Named after the sentence each one selects; see the module
# docstring for the table they are indices into.
REASON_BAD_REQUEST = 1     # 手帳情報もしくはキャラクターの登録情報が不正です。
REASON_BAD_NAME = 2        # 不正もしくは使用不可能なキャラクター情報（氏名等）が入力されました。
REASON_NOTEBOOK_TAKEN = 3  # その生徒手帳には、既にキャラクターが登録されています。
REASON_DUPLICATE = 4       # 同じ氏名のキャラクターが既に存在しています。

#: The shipped list and the operator's optional additions carry the same name in
#: two directories. Two files rather than one so that an operator's own
#: reservations survive a pull: the shipped one is generated and must not be
#: hand-edited, and merging is what makes editing it unnecessary.
RESERVED_FILE = "reserved_names.json"


def full_name(family: bytes, given: bytes) -> bytes:
    """The 氏名 as the rule compares it: 苗字 ＋ 名前, and nothing else.

    Both arrives NAME_LEN bytes wide and NUL-padded, which is how the create
    block carries them and how the tables store them, so each is cut at its
    first NUL before the two are joined. Raw bytes throughout: the client's
    encoding never has to be guessed at, and two names are the same name exactly
    when they are the same bytes.
    """
    return family.split(b"\x00")[0] + given.split(b"\x00")[0]


def name_in(info: bytes) -> "bytes | None":
    """The 氏名 carried by a create block, or None if that is not one.

    The layout belongs to characters.parse_create_info and is not repeated here;
    what this adds is that a block which does not parse has no 氏名 rather than
    an empty one, which is the difference between reason 1 and reason 2.
    """
    try:
        fields = characters.parse_create_info(info)
    except (ValueError, IndexError, KeyError):
        return None
    family, given = fields["familyName"], fields["firstName"]
    if not isinstance(family, bytes) or not isinstance(given, bytes):
        return None
    return full_name(family, given)


class ReservedNames:
    """The 219 names a character may not be called, if the operator has them.

    The file is a JSON object with one list per table, each entry either the
    name itself or the hex SHA-256 of its bytes::

        {"form": "sha256", "ng_name": ["a1b2..."], "reserve_pc": ["c3d4..."]}

    Both forms are accepted and both end up as digests in memory, so a list can
    be handed over without handing over the names in it, and an operator who
    wants to read or extend their own copy can keep it in plain text. Nothing
    else in this server hashes anything; here it is a way to compare without
    holding, not a security measure, and a digest of a short name is not a
    secret.
    """

    def __init__(self, *paths: "Path | None") -> None:
        self.paths = [p for p in paths if p is not None]
        self.tables: "dict[str, set[str]]" = {}
        for path in self.paths:
            self._load(path)
        if not self.tables and self.paths:
            print("[naming] nothing reserved; 氏名 are checked for duplicates only")

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[naming] ignoring unreadable {path}: {exc}")
            return
        if not isinstance(raw, dict):
            print(f"[naming] ignoring {path}: expected a JSON object")
            return
        loaded: "dict[str, int]" = {}
        for table, entries in raw.items():
            if not isinstance(entries, list):
                continue
            digests = set()
            for entry in entries:
                if not isinstance(entry, str):
                    continue
                text = entry.strip()
                if len(text) == 64 and all(c in "0123456789abcdef" for c in text.lower()):
                    digests.add(text.lower())
                else:
                    digests.add(self.digest(text.encode("shift_jis", "replace")))
            if digests:
                # Merged, not replaced: the operator's file adds to the shipped
                # one, and a table name they reuse extends it.
                self.tables.setdefault(table, set()).update(digests)
                loaded[table] = len(digests)
        if loaded:
            print(f"[naming] {path.parent.name}/{path.name}: " + ", ".join(
                f"{n} {k}" for k, n in sorted(loaded.items())
            ))

    @staticmethod
    def digest(full: bytes) -> str:
        return hashlib.sha256(full).hexdigest()

    def __len__(self) -> int:
        return sum(len(v) for v in self.tables.values())

    def holds(self, full: bytes) -> "str | None":
        """Which table reserves this 氏名, or None if none does."""
        if not full:
            return None
        wanted = self.digest(full)
        for table, digests in sorted(self.tables.items()):
            if wanted in digests:
                return table
        return None


def refusal(
    info: bytes,
    reserved: "ReservedNames | None",
    taken: "set[bytes]",
) -> "tuple[int, str] | None":
    """The reason 0x030E should carry for this create request, or None to allow.

    ``taken`` is every 氏名 this server is already holding, as full_name()
    builds them. The caller supplies it because who counts as "already exists"
    is the account layer's question, not this module's.

    The second half of the pair is a line for the log: a refusal that says only
    「reason=2」 leaves whoever is holding the server guessing which of the
    rules it was.

    ⚠️ The notebook rule (reason 3) is NOT here. It is the only one of the four
    that is about where the character goes rather than about who it is, and the
    store is what knows which notebooks are occupied -- see the caller.
    """
    full = name_in(info)
    if full is None:
        return REASON_BAD_REQUEST, f"{len(info)}B is not a create block"
    if not full:
        return REASON_BAD_NAME, "empty 氏名"
    table = reserved.holds(full) if reserved is not None else None
    if table is not None:
        return REASON_BAD_NAME, f"reserved by {table}"
    if full in taken:
        return REASON_DUPLICATE, "a character already has this 氏名"
    return None
