"""KONAMI IDs, and the token that carries one from the auth service to the game.

There are two logins, on two connections, and until now only one of them meant
anything here.

    https://<auth>/login.php     konami_id + personal_key, in the query string
    MPS 0x7000                   sessionId[64] + registrationCode[20]

The first is the account the player has with KONAMI; the second is the code that
came in the box. The original tied them together with a step on KONAMI's website
-- 登録, binding one code to one KONAMI ID -- and the client still carries the
refusals that step produced (codes.py sets out which). This file is the half of
that binding that is about the KONAMI ID: who exists, what their personal key
is, and how the answer to /login.php reaches the connection that needs it.

  The token
  ---------
  /login.php's reply has a session_id field, and the client copies it into the
  buffer it later sends as 0x7000's sessionId -- but only when the value is
  exactly 64 bytes (see auth_http_server.SESSION_ID for the compare that decides
  it). So a token of exactly that length is a channel between the two
  connections, and it is the only one: nothing else the client sends on the game
  port mentions the KONAMI ID at all.

  What travels is a handle and not a claim. The token is random, it means
  nothing away from the desk that minted it, and the desk remembers which KONAMI
  ID it was minted for -- including the case where the personal key did not
  verify, which mints a token belonging to nobody rather than no token at all.
  That distinction is what lets the game connection tell "signed in as somebody
  else" from "never signed in", and those are two different sentences.

⚠️ This is not a security boundary, and accounts.py's warning applies here word
for word. The personal key crosses the wire in a query string, TLS is 1024-bit
RSA/SHA-1 because that is all the client will accept, and anything on the
machine can open a socket to the game port and send 84 bytes of its choosing.
The point of the check is that the original had a 登録 step and a sentence for
failing it, and reproducing the observable behaviour is what this server is for.
Treat a personal key as a label with a lock drawn on it.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import secrets

# The reply field is copied only at this exact length; anything else is skipped
# with the login still reported as a success. 32 random bytes as hex is 64
# characters, and hex keeps the value inside the ASCII the client's parser and
# our own query strings can both carry.
TOKEN_LEN = 64

# What a KONAMI ID may be made of. The ceiling and the character set are ours,
# not measured off the client -- what is measured is that the id arrives in a
# query string with no escaping whatsoever
# (`?request_kind=R&msgno=12&konami_id=...&personal_key=...&content_id=0050`),
# so a value containing & or = would be read as the end of the field. Keeping to
# an identifier alphabet avoids that class of problem rather than papering over
# it, and matches the shape of a real KONAMI ID.
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

# The personal-key box on the client's login screen accepts only a-zA-Z0-9 --
# its kind-1 input alphabet, the 62-byte table at 0xd7d418 (the KONAMI-ID box
# beside it is kind 0, whose table also carries . _ -). A browser has no such
# filter, so without this a player could pick a key holding a hyphen, a space,
# or a symbol, register it here, and then never be able to type it in-game: the
# client would send a different string and the login would fail with 0x7002
# reason 4 for good. Restricting to the client's alphabet is not our taste, it
# is the set of keys that can actually be entered -- and as a side effect it
# keeps the value inside the unescaped query string the client sends it in
# (`&` and `=` would end the field early).
#
# The length ceiling is still ours: getkeylen returns the length of the
# client's crypto key, not a limit on this field, and the input box's own
# maximum has not been read off the binary.
KEY_MIN = 4
KEY_MAX = 64
KEY_PATTERN = re.compile(r"^[A-Za-z0-9]+$")

ITERATIONS = 200_000


class InvalidId(ValueError):
    """A KONAMI ID or personal key this server will not store."""


def normalise_id(text: str) -> str:
    """A KONAMI ID as it is stored: stripped and folded to lower case.

    Folding is a decision, not a transcription. The client sends whatever was
    typed into the login screen and nothing on this side can see that screen, so
    a player who registered as Kei and later typed KEI would otherwise be told
    their user information is incorrect -- which is true and useless. Case is
    the one difference between those two strings that a person does not consider
    a difference.
    """
    return text.strip().lower()


def check_id(konami_id: str) -> str:
    """The stored form of a KONAMI ID, or InvalidId saying what is wrong."""
    key = normalise_id(konami_id)
    if not key:
        raise InvalidId("a KONAMI ID is required")
    if not ID_PATTERN.match(key):
        raise InvalidId(
            "a KONAMI ID may hold up to 64 letters, digits, and . _ - "
            "(the client sends it in a query string with no escaping)"
        )
    return key


def check_personal_key(personal_key: str) -> str:
    """The personal key, or InvalidId saying what is wrong. Not folded."""
    if len(personal_key) < KEY_MIN:
        raise InvalidId(f"a personal key needs at least {KEY_MIN} characters")
    if len(personal_key) > KEY_MAX:
        raise InvalidId(f"a personal key may be at most {KEY_MAX} characters")
    if not KEY_PATTERN.match(personal_key):
        raise InvalidId(
            "a personal key may hold only letters and digits (A-Z a-z 0-9) -- "
            "the client's login screen accepts nothing else, so a key with any "
            "other character could never be typed in"
        )
    return personal_key


def _hash(personal_key: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", personal_key.encode("utf-8"), salt, iterations
    ).hex()


class Directory:
    """Every KONAMI ID on this server, with its personal key stored as a hash.

    On disk at ``runtime/accounts/konami_ids.json``, next to the code table and
    the account index, and reloaded before every read for the same reason they
    are: the file is small, it changes rarely, and a person with a text editor
    is a supported way to remove an entry.

    ⚠️ Hashed rather than kept, even though the warning at the top of this file
    says the lock is drawn on. Storing it in the clear would make this file a
    list of the passwords the people on this machine actually use, which is a
    harm that has nothing to do with whether anybody can log in to a game.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "konami_ids.json"
        self.table: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.table = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[konamiid] ⚠ {self.path} is unreadable ({exc}); nobody is known")
            self.table = {}
            return
        if isinstance(raw, dict):
            self.table = {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.table, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def reload(self) -> None:
        self._load()

    # -- questions --------------------------------------------------------

    def exists(self, konami_id: str) -> bool:
        self.reload()
        return normalise_id(konami_id) in self.table

    def verify(self, konami_id: str, personal_key: str) -> bool:
        """Is this the personal key for this KONAMI ID?

        False for an id that does not exist, and it takes the same work to say
        so: the hash is computed against a throwaway salt before the answer is
        returned, so how long this takes does not report whether the id was
        real. Cheap here and habitual in the right direction.
        """
        self.reload()
        key = normalise_id(konami_id)
        entry = self.table.get(key)
        if entry is None:
            _hash(personal_key, b"absent", ITERATIONS)
            return False
        try:
            salt = bytes.fromhex(entry.get("salt", ""))
            expected = entry.get("key", "")
            iterations = int(entry.get("iterations", ITERATIONS))
        except (TypeError, ValueError):
            print(f"[konamiid] ⚠ {key} has an unreadable entry; refusing it")
            return False
        return secrets.compare_digest(_hash(personal_key, salt, iterations), expected)

    # -- changes ----------------------------------------------------------

    def create(self, konami_id: str, personal_key: str) -> str:
        """Record a new KONAMI ID. Returns its stored form.

        Raises InvalidId when the id is already taken, which is the same
        exception as a malformed one on purpose: both are things the person
        filling in the form has to fix, and the page shows the message.
        """
        key = check_id(konami_id)
        check_personal_key(personal_key)
        self.reload()
        if key in self.table:
            raise InvalidId(f"the KONAMI ID {key} is already taken")
        salt = secrets.token_bytes(16)
        self.table[key] = {
            "salt": salt.hex(),
            "key": _hash(personal_key, salt, ITERATIONS),
            "iterations": ITERATIONS,
            "created": date.today().isoformat(),
        }
        self.save()
        return key

    def set_personal_key(self, konami_id: str, personal_key: str) -> bool:
        """Change an existing personal key. False when there is no such id."""
        check_personal_key(personal_key)
        self.reload()
        key = normalise_id(konami_id)
        if key not in self.table:
            return False
        salt = secrets.token_bytes(16)
        self.table[key].update(
            salt=salt.hex(),
            key=_hash(personal_key, salt, ITERATIONS),
            iterations=ITERATIONS,
        )
        self.save()
        return True


class TokenDesk:
    """The 64-byte session tokens /login.php mints, and who each stands for.

    In memory only, and deliberately: a token is the fact that somebody signed
    in on this run of the server, so surviving a restart would be wrong -- the
    client signs in again on its next login anyway, and it always does so before
    reaching 0x7000.

    Shared by every AuthHttpServer instance and every MPS port, the way the
    account store and the ticket desk are. run_all.py builds one.
    """

    # A login is minted and redeemed seconds later, so the table only ever holds
    # the recent past; the bound is there so that a server left running for a
    # month with a client reconnecting in a loop does not accumulate one entry
    # per attempt forever.
    LIMIT = 256

    def __init__(self) -> None:
        self.issued: dict[str, str | None] = {}

    def mint(self, konami_id: str | None) -> str:
        """A fresh token standing for this KONAMI ID, or for nobody.

        None is the interesting argument: it is what a login whose personal key
        did not verify gets. The client is told nothing about that here -- the
        auth service has no way to say it, and 000 is what it answers either way
        -- so the refusal has to happen later, and it can only happen later if
        the failure is remembered rather than dropped.
        """
        while True:
            token = secrets.token_hex(TOKEN_LEN // 2)
            if token not in self.issued:
                break
        self.issued[token] = konami_id
        while len(self.issued) > self.LIMIT:
            # Insertion order, so this is the oldest token on the books.
            self.issued.pop(next(iter(self.issued)))
        return token

    def knows(self, token: str) -> bool:
        """Was this token minted here? True even when it stands for nobody."""
        return token in self.issued

    def who(self, token: str) -> str | None:
        """The KONAMI ID this token stands for; None if nobody, or unknown."""
        return self.issued.get(token)


def token_from_params(session_id: bytes) -> str:
    """The token out of 0x7000's sessionId field, as a string.

    The field is a fixed 64 bytes and an unauthenticated client leaves it at
    zeroes, so anything that is not 64 characters of ASCII is not a token this
    desk minted -- returning "" says so without the caller having to know what a
    token looks like.
    """
    trimmed = session_id.rstrip(b"\x00")
    if len(trimmed) != TOKEN_LEN:
        return ""
    try:
        return trimmed.decode("ascii")
    except UnicodeDecodeError:
        return ""
