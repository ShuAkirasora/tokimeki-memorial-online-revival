"""Which characters belong to whom, and how a connection says which it is.

The client names its account on the wire once per login, and it does it in
MsgClRequestLoginServerLogin (0x7000). That message is
``sessionId[SESSION_ID_LEN] + registrationCode[REGISTRATION_CODE_LEN]``, the
field names coming from the client's own trace, and the second field is the one
worth reading: twenty bytes holding the five four-character groups the player
typed into the レジストレーションコード boxes on the login screen, concatenated
with no separators and NUL-padded when a group is short.

That shape was measured rather than reasoned. A login with the boxes reading
AAAA-AAAA-AAAA-AAAA-AAAA put twenty 0x41 bytes on the wire; deleting two
characters from the first box and logging in again put eighteen 0x41 bytes and
two NULs there. So the field is the typed text, left-packed, and nothing
reformats it on the way out.

The sibling field is not usable and that was measured too: sessionId is 64 zero
bytes on every login regardless of what /login.php answers with, so the KONAMI ID
the player types never arrives here. It does reach this machine -- every request
to the auth service carries ``konami_id=`` in its query string -- but on a
different connection and under TLS, so using it would mean correlating two
connections by source address. The registration code arrives on the connection
that needs it, already tied to the login it belongs to.

⚠️ This is addressing, not authentication. Neither value is a secret, nothing
signs them, and the client will send whatever is in the boxes. Two players keep
their characters apart the way two save files do -- by being named differently --
and that is all this is for. The server it belongs to runs on one machine for the
people sitting at it; see the README on why it is not meant to face a network.

Accounts own a slice of the charaId space rather than a counter, because the
client has an opinion about which ids are ordinary characters (see
characters.CHARA_ID_BASE: 0x01000000 and up, or the small 0x000Fxxxx window).
Account n takes ``n << 24``, so the account that owns a character can be read
straight off its id -- which is what lets one connection answer a question about
another connection's character without searching every account first.
"""

from __future__ import annotations

import json
from pathlib import Path
import secrets

from characters import CharacterStore

# The two fixed-length fields of MsgClRequestLoginServerLogin, in the order the
# client serializes them.
#
# ⚠️ SESSION_ID_LEN is measured, not read off a header: the client's whole
# message is 84 bytes and the code is the last 20 of them, so the field ahead of
# it is 64. It was 128 here for one round, which cost a login -- the server read
# past the end of an 84-byte message, found nothing, and filed the real client
# under a brand new account with no characters in it.
SESSION_ID_LEN = 64
REGISTRATION_CODE_LEN = 20

# Account ids start at 1 and stop at 255, both ends set by the charaId space:
# account 0 would put characters at 0x00000000, which the client resolves through
# the NPC subsystem instead of drawing as a player, and 256 would run off the top
# of the byte. Nothing is expected to come near the ceiling -- this is a server
# for the room it is running in -- but a wrong answer here is a client crash in a
# lesson rather than an error, so it is a check and not a comment.
FIRST_ACCOUNT_ID = 1
MAX_ACCOUNT_ID = 0xFF

ACCOUNT_SHIFT = 24


def account_of(chara_id: int) -> int:
    """Which account owns this charaId, by the slice it falls in."""
    return chara_id >> ACCOUNT_SHIFT


def registration_code(params: bytes) -> bytes:
    """The registration code out of MsgClRequestLoginServerLogin's parameters.

    Taken from the END of the message rather than at SESSION_ID_LEN, and that is
    the whole point: the code is the last field the client serializes, so the
    only thing this has to be right about is its own length. Reading it at a
    fixed offset means being right about the field in front of it too, and being
    wrong there does not fail loudly -- it hands back twenty bytes of something
    else, or nothing, and the login proceeds under the wrong account.

    Trailing NULs come off: the client pads a short code out to the full twenty
    bytes, and a player who typed three groups instead of five means the same
    account every time they do it.

    Returns b"" when the message is too short to hold one, which is not treated
    as an error here -- the caller decides what an unnamed connection gets.
    """
    if len(params) < SESSION_ID_LEN + REGISTRATION_CODE_LEN:
        return b""
    return params[-REGISTRATION_CODE_LEN:].rstrip(b"\x00")


def label(code: bytes) -> str:
    """A registration code as it goes into the log: printable, or hex if not."""
    if not code:
        return "(none)"
    try:
        text = code.decode("ascii")
    except UnicodeDecodeError:
        return code.hex()
    return text if text.isprintable() else code.hex()


class AccountStore:
    """Every account this server has seen, each with its own characters.

    On disk::

        runtime/accounts/index.json     registration code -> account id
        runtime/accounts/1/characters.json
        runtime/accounts/2/characters.json

    The index is the only shared file, and it only ever grows: an account id,
    once handed out, keeps its directory and its charaId slice for good, because
    characters saved under it name that slice in their own ids.
    """

    def __init__(self, root: Path, adopt_code: str | None = None) -> None:
        self.dir = root / "runtime" / "accounts"
        self.index_path = self.dir / "index.json"
        self.index: dict[str, int] = {}
        self._stores: dict[int, CharacterStore] = {}
        self._load()
        self._adopt_single_account_file(root / "runtime" / "characters.json")
        if adopt_code is not None:
            self.adopt(adopt_code.encode("ascii", "replace"))

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[accounts] ignoring unreadable {self.index_path}: {exc}")
            return
        if isinstance(raw, dict):
            self.index = {str(k): int(v) for k, v in raw.items()}

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(self.index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _reload(self) -> None:
        """Re-read the index before changing it, so an outside edit survives.

        The file is small, written rarely, and not only written here: a test
        harness that made itself an account cleans it up again, and an operator
        with a text editor is a supported way to rename or drop one. Holding the
        whole thing in memory and writing it back wholesale would undo any of
        that -- which it did once, resurrecting two deleted accounts on the next
        allocation.
        """
        self._load()

    def _adopt_single_account_file(self, legacy: Path) -> None:
        """Move the pre-account characters.json into account 1, once.

        Every character that existed before this file did was made by the only
        account there was, and their ids already start at 0x01000000 -- which is
        account 1's slice, since CHARA_ID_BASE and ``1 << 24`` are the same
        number. So the move is a rename and not a rewrite, and it leaves the ids
        the client has already seen alone.

        ⚠️ It does not decide who owns them. This server never saw a registration
        code before now, so there is nothing on disk that says which one the
        characters belong to, and the obvious shortcut -- let the first code to
        log in claim them -- is a trap: run a test client before the real one and
        the test silently inherits somebody's save. So the account is left
        unclaimed and the operator names it once with --adopt-code.
        """
        target = self._path(FIRST_ACCOUNT_ID)
        if target.exists() or not legacy.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(target)
        print(
            f"[accounts] moved {legacy.name} into account {FIRST_ACCOUNT_ID}; "
            "no registration code owns it yet -- restart with --adopt-code <CODE> "
            "using the レジストレーションコード on the client's login screen"
        )

    def _path(self, account_id: int) -> Path:
        return self.dir / str(account_id) / "characters.json"

    def _reserved(self) -> set[int]:
        """Account ids that exist on disk, claimed or not.

        A directory with no entry in the index is an account waiting to be
        adopted, and handing its id to the next new code would give that code
        somebody else's characters. So it counts as taken for allocation and
        can only be reached by name.
        """
        taken = set(self.index.values())
        if self.dir.exists():
            for child in self.dir.iterdir():
                if child.is_dir() and child.name.isdigit():
                    taken.add(int(child.name))
        return taken

    # -- lookup -----------------------------------------------------------

    def adopt(self, code: bytes) -> bool:
        """Attach a registration code to an account that has none.

        For one job only: the characters that were here before accounts were.
        Refuses when the code already names an account, and when account 1 has
        an owner already -- neither is a state where taking somebody's
        characters is what the operator meant.
        """
        self._reload()
        key = label(code)
        if key in self.index:
            print(f"[accounts] --adopt-code {key} already is account {self.index[key]}")
            return False
        if FIRST_ACCOUNT_ID in self.index.values():
            owner = next(k for k, v in self.index.items() if v == FIRST_ACCOUNT_ID)
            print(
                f"[accounts] ⚠ --adopt-code {key} ignored: account "
                f"{FIRST_ACCOUNT_ID} already belongs to {owner}"
            )
            return False
        self.index[key] = FIRST_ACCOUNT_ID
        self._save()
        store = self.characters(FIRST_ACCOUNT_ID)
        print(
            f"[accounts] {key} adopted account {FIRST_ACCOUNT_ID}: {store.summary()}"
        )
        return True

    def account_id(self, code: bytes) -> int:
        """The account this registration code names, allocating one if new."""
        self._reload()
        key = label(code)
        existing = self.index.get(key)
        if existing is not None:
            return existing
        taken = self._reserved()
        for candidate in range(FIRST_ACCOUNT_ID, MAX_ACCOUNT_ID + 1):
            if candidate not in taken:
                break
        else:
            raise RuntimeError(f"no account id left below {MAX_ACCOUNT_ID}")
        self.index[key] = candidate
        self._save()
        print(f"[accounts] registration code {key} is account {candidate}")
        return candidate

    def characters(self, account_id: int) -> CharacterStore:
        """This account's characters, loaded once and kept.

        One store per account rather than one per connection: two connections on
        the same account have to see each other's writes, and the store is the
        only thing that knows what is on disk.
        """
        store = self._stores.get(account_id)
        if store is None:
            store = CharacterStore(
                self._path(account_id),
                chara_id_base=account_id << ACCOUNT_SHIFT,
            )
            self._stores[account_id] = store
        return store

    def for_code(self, code: bytes) -> tuple[int, CharacterStore]:
        """``(accountId, store)`` for a registration code off the wire."""
        account_id = self.account_id(code)
        return account_id, self.characters(account_id)

    def owner_of(self, chara_id: int) -> CharacterStore | None:
        """The store holding this charaId, read off the id's own account slice.

        None when the slice has never been handed out, which is what a charaId
        from a probe or a stand-in looks like: those live outside every account.
        """
        account_id = account_of(chara_id)
        if account_id not in self.index.values():
            return None
        return self.characters(account_id)

    def summary(self) -> str:
        if not self.index:
            return "(no accounts yet)"
        return ", ".join(
            f"{code}=#{account_id}" for code, account_id in sorted(
                self.index.items(), key=lambda kv: kv[1]
            )
        )


class TicketDesk:
    """Carries an account across the hops between one connection and the next.

    Only the login connection is told a registration code. The client then opens
    a second connection to the game port and a third to the school port, and
    neither of those repeats it -- MsgClQueryCharacterListFromAccount goes out
    with no parameters at all, so a connection that has not been told which
    account it is cannot work it out from anything the client says later.

    What the client does carry across is the relay ticket. MsgSvOkLoginServerLogin
    hands it an address, a port and a u32 authCode, and the first thing it sends
    on the connection it opens there is MsgClNotifyAuthCode with that same
    authCode echoed back. MsgSvOkSchoolSelect does the same for the school hop.
    So the authCode is the handle: mint one per hop, remember which account it
    was minted for, and recognise it when it comes home.

    ⚠️ Not a credential. Anything on the machine can send any u32, and the point
    here is telling two logins apart, not keeping a third one out.
    """

    def __init__(self) -> None:
        self.issued: dict[int, int] = {}

    def issue(self, account_id: int) -> int:
        """A fresh authCode standing for this account."""
        while True:
            code = secrets.randbits(32)
            # 0 is what the client's own trace shows in an uninitialised ticket,
            # so it is kept out of circulation to stay distinguishable from one.
            if code and code not in self.issued:
                break
        self.issued[code] = account_id
        return code

    def redeem(self, code: int) -> int | None:
        """The account an authCode was minted for, or None if we never issued it.

        The ticket stays on the books after it is redeemed: a client that
        reconnects to the same hop without going through the login server again
        sends the same code, and refusing it the second time would drop a
        connection for being what it says it is.
        """
        return self.issued.get(code)
