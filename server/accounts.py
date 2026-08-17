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

The sibling field is empty here, but not for the reason this docstring gave for
several rounds. It said sessionId was 64 zero bytes on every login no matter what
/login.php answered, and concluded the client simply never forwards it. The
observation was real; the explanation was wrong, and it was wrong in a way that
made the KONAMI ID look unusable when it is not.

The client copies session_id into the buffer that becomes this field only when
the field is exactly 64 bytes long (auth_http_server's login parser, at the
compare against 0x40). A session_id of any other length is skipped -- silently,
and the login still succeeds -- leaving the buffer at its factory zeroes. This
stub answers with a sixteen-byte SESSION_ID, so the buffer was never written.
Answering with a full 64 bytes puts those 64 bytes verbatim at the head of 0x7000,
which means an authenticated /login.php could mint a token here and have it
arrive on the connection that needs it.

That is what now happens. /login.php checks the KONAMI ID against the directory
in konami_id.py and answers with a 64-byte token; the token arrives here at the
head of 0x7000; and check_login below asks whether the KONAMI ID it names is the
one the registration code was 登録'd to. Which account a connection *is* still
comes from the registration code alone -- the code is the name, as it always was
-- and the KONAMI ID is a second question asked about the same login.

⚠️ Addressing, with a check drawn on it. Nothing here is a secret that survives
being on the same machine: the personal key crosses a query string, the token is
handed out by a service that will hand one to anybody, and the client sends
whatever is in the boxes. Two players keep their characters apart the way two
save files do -- by being named differently -- and the KONAMI ID check exists
because the original had a 登録 step and a sentence for failing it, not because
it keeps anyone out. See the README on why this is not meant to face a network.

A charaId does not name its owner, so the owner is looked up. The index lives in
charaids.py and the file it keeps is runtime/accounts/charas.json.

⚠️ This used to work the other way: account n owned the charaId slice ``n << 24``
and ``chara_id >> 24`` was the answer. What the client is known to do is check a
*range*: 0x000F0000 through 0x000FFFFF, and 0x01000000 through 0xFFFFFFFE, are the
ids it draws as ordinary characters, and anything else goes to another subsystem
or crashes the screen that asks (see characters.CHARA_ID_BASE). That check sorts
ids by kind. It carries no mask for reading an owner out of one, and the client
never asks who owns a charaId -- it is told.

The slicing on top of that was ours, and the client's own message table
contradicts it in four places:

* Its operator interface hands out accountId and charaId as two free variables.
  MsgClSupervisorRequestCharacterCreate takes accountId, charaFrameId and charaId
  together (4+1+4 bytes), while MsgClSupervisorRequestCharacterDestroy takes only
  a charaId. Destroying needs one id, creating needs two -- which is what a
  charaId that does not name its owner looks like. The other 29 messages in that
  family address a character by charaId alone, so the server side has an index
  from one to the other and does not compute it.
* accountId is 4 bytes on the wire (MsgClRequestGameServerLogin), and the school
  list counts accounts in a u16 per school -- the client's own name for the field
  is accountCount. One school holds 65535 accounts; the slicing here caps the
  whole server at 255.
* A school is a property of the account, not of a character. schoolId arrives in
  MsgSvOkGameServerLogin, before any charaId exists, and no character record has
  one -- not the list entries, not the operator interface's full character dump.
* Characters transfer between schools (five request/reply pairs for it), and the
  whole flow addresses a character by charaFrameId, the 0-2 slot number. An id
  with a school in its top bits would have to change under a transfer and take
  every stored loverCharaId with it.

So the shift was not merely unattested, it contradicted the protocol it is
speaking, and it is gone. What replaced it splits along the line that matters:
*not encoding the owner* is a constraint recovered from the client, while *one
counter walking up from CHARA_ID_BASE, never handing a number out twice* is a
choice of ours -- the original's allocation scheme is not recoverable, because
the client is told ids and never derives one. charaids.py keeps the two apart in
writing as well.

Nothing on disk was renumbered by the change. Every id minted under the shift is
inside the range the client accepts, and only this server ever read meaning into
them, so the migration is a new index file built by reading the saves.
"""

from __future__ import annotations

import json
from pathlib import Path
import secrets

import charaids
import codes
import item
import konami_id
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

# Account ids start at 1 and stop at 65535, and the two ends are not the same
# kind of fact.
#
# The floor is the client's. Account 0 used to put characters at 0x00000000,
# which it resolves through the NPC subsystem instead of drawing as a player, and
# the first screen to ask (授業) died reading through that resolution rather than
# reporting anything. Ids no longer come from the account number, so that
# particular crash is out of reach -- the floor stays anyway, because 0 is what
# an unnamed connection's account_id reads as (see mps_session._chars) and a real
# account must never collide with it.
#
# The ceiling was 0xFF while an account number had to fit in the top byte of a
# charaId. That is gone, so it is set to what the protocol will carry instead:
# MsgSvResultSchoolList reports each school's population in a u16 the client
# calls accountCount, so 65535 is the largest number a school can honestly
# report. accountId itself is a u32 on the wire (MsgClRequestGameServerLogin).
# Nothing here is expected to come near either -- this is a server for the room
# it is running in.
FIRST_ACCOUNT_ID = 1
MAX_ACCOUNT_ID = 0xFFFF


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


def session_id(params: bytes) -> bytes:
    """The sessionId field out of the same message: the 64 bytes before the code.

    Anchored at the end for the same reason the code is -- the two fields are
    measured backwards from a message whose total length is the thing actually
    known. All zeroes for a client that has not been through /login.php, and
    konami_id.token_from_params is what turns this into a token or into "".
    """
    if len(params) < SESSION_ID_LEN + REGISTRATION_CODE_LEN:
        return b""
    return params[-(SESSION_ID_LEN + REGISTRATION_CODE_LEN) : -REGISTRATION_CODE_LEN]


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
        runtime/accounts/charas.json    charaId -> account id
        runtime/accounts/1/characters.json
        runtime/accounts/2/characters.json

    Both shared files only ever grow an account: an id, once handed out, keeps
    its directory for good, because charas.json points characters at it by
    number.

    Whether a code is allowed to log in at all is a separate table and a separate
    file; see codes.py for why the two are not one record.
    """

    def __init__(self, root: Path, adopt_code: str | None = None) -> None:
        self.dir = root / "runtime" / "accounts"
        self.index_path = self.dir / "index.json"
        self.index: dict[str, int] = {}
        self._stores: dict[int, CharacterStore] = {}
        self._lockers: dict[int, "item.Locker"] = {}
        self._load()
        self._adopt_single_account_file(root / "runtime" / "characters.json")
        # ⚠️ After the adopt, not before: that call moves the pre-account save
        # into account 1's directory, and the backfill reads directories.
        self.charas = charaids.CharaIndex(self.dir)
        self.charas.backfill(self._saved_chara_ids())
        self.codes = codes.CodeTable(self.dir)
        # The three tables in runtime/accounts are built here so that everything
        # holding one holds the same one; run_all.py reaches the other two
        # through this object rather than making its own.
        self.konami_ids = konami_id.Directory(self.dir)
        self._seed_codes()
        if adopt_code is not None:
            self.adopt(adopt_code.encode("ascii", "replace"))

    def _seed_codes(self) -> None:
        """Let every code that already names an account keep logging in.

        The code table decides permission, and it did not exist until now, so on
        the restart that introduces it every account on the machine would be
        refused with reason 24 -- including the operator's own, and including the
        fixed codes the smoke tests log in with. Seeding from the index turns
        that into a no-op upgrade.

        Runs every start rather than once, because the index is also editable by
        hand and an account added there should not need a second step here.
        """
        added = [
            key for key in self.index if self.codes.adopt(key, "adopted from index.json")
        ]
        if added:
            print(
                f"[codes] {len(added)} code(s) already in use are now active: "
                + ", ".join(sorted(added))
            )

    def check(self, code: bytes) -> int | None:
        """The MsgSvNgLoginServerLogin reason for refusing this code, or None."""
        return self.codes.check(label(code))

    def check_login(self, code: bytes, signed_in_as: str | None) -> int | None:
        """The reason this signed-in player may not use this code, or None.

        The second half of the login, and the half the 登録 form exists for:
        check() asks whether the code is usable at all, this asks whether it is
        this player's. ``signed_in_as`` is the KONAMI ID the session token names
        -- None when nothing signed in on this connection, which is also what an
        unverified personal key comes back as.

        Two of the client's sentences are reachable from here:

          4   ユーザ情報が正しくありません   this code belongs to somebody else
          23  再登録が必要です               it belongs to an id that is gone

        23 is worth having rather than folding into 4. Removing an entry from
        konami_ids.json is the supported way to retire a KONAMI ID, and the
        codes registered to it are then bound to nothing -- which is not the
        player getting their password wrong, and 再登録が必要です tells them the
        one thing that will actually fix it.

        A code with no owner is allowed through whatever arrives. That is every
        code from before this field existed, and refusing them would have made
        the upgrade a lockout; codes.py has the longer form of the argument.
        """
        key = label(code)
        owner = self.codes.owner(key)
        if owner is None:
            return None
        if not self.konami_ids.exists(owner):
            return codes.REASON_REREGISTER
        return self.codes.check_owner(key, signed_in_as)

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
        account there was, so the move is a rename and not a rewrite, and it
        leaves the ids the client has already seen alone. Ownership is not in
        those ids and never has to be: charas.json is built from the directory
        this puts them in, which is why the backfill runs after this call and not
        before.

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

    def _locker_path(self, account_id: int) -> Path:
        return self.dir / str(account_id) / "locker.json"

    def locker(self, account_id: int) -> "item.Locker | None":
        """This account's ロッカー, or None for a connection with no account.

        ⭐⭐ ONE PER ACCOUNT, ALONGSIDE characters.json RATHER THAN INSIDE IT,
        because the client's own refusal sentences put it at this level: the two
        locker-side refusals say 「アカウントデータの取得に失敗しました。」 where
        every carried-side refusal says 「キャラクター情報」. See item.Locker.
        A separate file rather than a key in characters.json for the same reason
        the store is separate: it belongs to the account, not to any record in
        that list, and putting it in the list would give it a character to
        belong to.

        Held in the cache the same way CharacterStore is, so two connections on
        one account see each other's writes -- which is the whole point of a
        locker and the one thing a per-connection copy would get wrong.
        """
        if account_id <= 0:
            return None
        cached = self._lockers.get(account_id)
        if cached is not None:
            return cached
        path = self._locker_path(account_id)
        saved: "dict | None" = None
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                saved = loaded if isinstance(loaded, dict) else None
            except (OSError, ValueError) as exc:
                print(f"[accounts] ignoring unreadable {path}: {exc}")
        locker = item.Locker(saved)
        self._lockers[account_id] = locker
        return locker

    def save_locker(self, account_id: int) -> bool:
        """Write this account's ロッカー back. False if it has none loaded."""
        locker = self._lockers.get(account_id)
        if account_id <= 0 or locker is None:
            return False
        path = self._locker_path(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(locker.to_json(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True

    def _saved_chara_ids(self) -> dict[int, list[int]]:
        """``{accountId: [charaId, ...]}`` straight off the save files.

        Read for charas.json's backfill and for nothing else, so it goes to disk
        rather than through characters(): building a CharacterStore per account
        at startup would cache every account this machine has ever seen, and the
        stores are meant to appear when somebody logs in.
        """
        found: dict[int, list[int]] = {}
        if not self.dir.exists():
            return found
        for child in sorted(self.dir.iterdir()):
            if not (child.is_dir() and child.name.isdigit()):
                continue
            path = child / "characters.json"
            if not path.exists():
                continue
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"[accounts] ignoring unreadable {path}: {exc}")
                continue
            if isinstance(records, list):
                found[int(child.name)] = [
                    int(r["charaId"]) for r in records if isinstance(r, dict) and "charaId" in r
                ]
        return found

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
        # An adopted code has to be allowed in as well, or the account it was
        # just pointed at refuses it on the next login.
        self.codes.adopt(key, "adopted with --adopt-code")
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
                ids=self.charas,
                account_id=account_id,
            )
            self._stores[account_id] = store
        return store

    def for_code(self, code: bytes) -> tuple[int, CharacterStore]:
        """``(accountId, store)`` for a registration code off the wire."""
        account_id = self.account_id(code)
        return account_id, self.characters(account_id)

    def owner_of(self, chara_id: int) -> CharacterStore | None:
        """The store holding this charaId, looked up rather than computed.

        None when no account claims the id, which is what a charaId from a probe,
        a stand-in, or an unnamed connection's detached store looks like: none of
        those were ever minted here.

        ⚠️ This used to read the account out of the id's top byte. It cannot any
        more, and that is the point of the change -- see the module docstring.
        Every caller was already asking "whose is this", not "what is its slice",
        so the callers did not move.
        """
        account_id = self.charas.owner(chara_id)
        if account_id is None:
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
