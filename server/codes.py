"""Which registration codes may log in, and what the client is told when one may not.

accounts.py answers "whose characters are these"; this file answers the question
in front of it, "may this code in at all". They are deliberately two files with
two tables on disk, because the two facts have different lifetimes: an account id
is permanent once handed out -- characters saved under it carry that id in their
own charaIds -- while permission to log in is exactly the thing an operator wants
to be able to withdraw. Suspending somebody must not put their save at risk, and
it cannot if the two are not the same record.

    runtime/accounts/index.json   code -> account id        never shrinks
    runtime/accounts/codes.json   code -> may it log in      edited freely

The original did this too, and its own error text is the evidence. The client
carries a table of refusals for MsgSvNgLoginServerLogin (0x7002), and among the
thirty entries are four that only make sense against a table of codes that exists
before anybody types one:

    21  the code does not exist            入力されたレジストレーションコードは存在しません
    22  the code's period has ended        レジストレーションコードの有効期限が過ぎています
    24  the code is not registered         レジストレーションコードが登録されていません
    25  the account is suspended           アカウント停止期間中です

21 against 24 is the useful pair. It says the original could tell a string it had
never printed from one it had printed but that nobody had claimed yet -- so the
codes were generated into a database up front, and a separate later step marked
one as belonging to somebody. That later step was 登録, done by the player on
KONAMI's website with the code from the box; reason 23 (再登録が必要です) and
reason 27 (buy a play ticket on the website) are the rest of that same shape.

So a code here has two stages, named after theirs:

    issued     generated, not yet claimed by anybody   -> refused with 24
    active     claimed, may log in                     -> allowed
    suspended  withdrawn by the operator               -> refused with 25

and a string that is in no row at all is refused with 21, which is also what a
player who mistypes their code gets. That is the right answer for a typo: the
thing they typed is, in fact, not a code this server ever issued.

⚠️ No check digit, and that is a decision rather than an omission. An earlier
draft of this file derived the last four characters from the first sixteen so a
typo could be rejected without a table lookup -- which reproduces 21 correctly
but for a reason the original cannot have had, since KONAMI had the database and
no need to decide anything offline. The table gives 21 by itself. What KONAMI did
do about mistyping is visible in the alphabet below.

⚠️ The reason numbers are the client's, but what the client draws for each was
measured, not assumed: 21 and 24 were both sent to a real client and both put
their own sentence on the login screen. The other two are from the same table and
have not been put on screen yet.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import secrets

# MsgSvNgLoginServerLogin reasons, as the client indexes its own error table.
# Only the ones this server can arrive at are named; the full thirty are in the
# client's table.
REASON_ACCOUNT_CREATE_FAILED = 3
REASON_UNKNOWN = 21
REASON_EXPIRED = 22
REASON_NOT_REGISTERED = 24
REASON_SUSPENDED = 25

# The twenty-seven characters the client's registration-code boxes accept, in
# the order they sit in the binary. Everything excluded from a full alphanumeric
# set is a confusable -- 0 1 8 and B G I O Q Z -- which is KONAMI's answer to
# somebody copying a code off a printed slip by hand, and is reason enough to
# keep to it here even though nothing is printed: the five boxes on the login
# screen reject anything else, so a code containing one could never be entered.
ALPHABET = "2345679ACDEFHJKLMNPRSTUVWXY"

# Twenty characters, shown as the five four-character groups the login screen
# has. The dashes are display only and never reach the wire.
CODE_LEN = 20
GROUP_LEN = 4

STATE_ISSUED = "issued"
STATE_ACTIVE = "active"
STATE_SUSPENDED = "suspended"


def format_code(key: str) -> str:
    """A code as the login screen shows it: five groups, dash separated.

    Anything that is not a full twenty characters comes back untouched. The
    grouping is the five boxes on that screen, so applying it to a short code --
    the fixed ones the smoke tests use, say -- would draw dashes that are not
    there and cannot be typed, which reads as a code that has been corrupted.
    """
    if not is_wellformed(key):
        return key
    return "-".join(key[i : i + GROUP_LEN] for i in range(0, len(key), GROUP_LEN))


def is_wellformed(key: str) -> bool:
    """Twenty characters, all of them in the client's alphabet."""
    return len(key) == CODE_LEN and all(ch in ALPHABET for ch in key)


def normalise(text: str) -> str:
    """A code as it is stored, from however a person wrote it down.

    Dashes and spaces come out and letters go up, so the thing typed at a shell
    matches the thing on the wire -- which carries the twenty characters with no
    separators at all.
    """
    return "".join(ch for ch in text.upper() if ch not in "- \t")


def generate(taken: set[str]) -> str:
    """A code that is not already in use.

    secrets rather than random because it costs nothing here and the alternative
    is a generator whose output can be predicted from earlier codes. Nobody is
    paying to play on this server, so guessing one is not worth much -- but the
    space is 27**20, and drawing from it badly is the only way to make guessing
    cheap.
    """
    while True:
        key = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if key not in taken:
            return key


class CodeTable:
    """Every registration code this server has issued, and its state.

    Reloaded before every read and written whole. The file is small, changes
    rarely, and is meant to be edited by hand -- issue_code.py is a convenience,
    not the only supported way in -- so holding a copy in memory across a change
    made outside would quietly undo it. accounts.py learned that the hard way
    with the index next to it.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "codes.json"
        self.table: dict[str, dict] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            self.table = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Louder than the index's equivalent: an unreadable index costs an
            # account its name, an unreadable code table would refuse everybody.
            print(f"[codes] ⚠ {self.path} is unreadable ({exc}); refusing every code")
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

    # -- the question the login asks --------------------------------------

    def check(self, key: str, today: date | None = None) -> int | None:
        """The reason this code may not log in, or None if it may.

        Order matters where two answers could both be true. A suspended code
        that has also run out of time reports the suspension, because that is
        the one somebody decided on purpose and is the one they will look for
        when the player asks why.
        """
        self.reload()
        entry = self.table.get(key)
        if entry is None:
            return REASON_UNKNOWN
        if entry.get("state") == STATE_SUSPENDED:
            return REASON_SUSPENDED
        expires = entry.get("expires")
        if expires and (today or date.today()) > date.fromisoformat(expires):
            return REASON_EXPIRED
        if entry.get("state") != STATE_ACTIVE:
            return REASON_NOT_REGISTERED
        return None

    # -- changing it ------------------------------------------------------

    def issue(
        self,
        *,
        state: str = STATE_ACTIVE,
        note: str = "",
        expires: str | None = None,
        today: date | None = None,
    ) -> str:
        """Generate one code and record it. Returns the code."""
        self.reload()
        key = generate(set(self.table))
        self.table[key] = {
            "state": state,
            "issued": (today or date.today()).isoformat(),
            "expires": expires,
            "note": note,
        }
        self.save()
        return key

    def set_state(self, key: str, state: str) -> bool:
        """Move an existing code to a state. False when there is no such code."""
        self.reload()
        entry = self.table.get(key)
        if entry is None:
            return False
        entry["state"] = state
        self.save()
        return True

    def adopt(self, key: str, note: str) -> bool:
        """Record a code that is already in use as active, if it is not known.

        For the codes that were logging in before this table existed. Without
        this the first restart after it appeared would refuse every account on
        the machine, including the operator's own -- a table that starts empty
        and is consulted for permission is a lockout unless something seeds it.

        Never overwrites: a code that was deliberately suspended stays suspended
        even though it still names an account in the index.
        """
        self.reload()
        if key in self.table:
            return False
        self.table[key] = {
            "state": STATE_ACTIVE,
            "issued": date.today().isoformat(),
            "expires": None,
            "note": note,
        }
        self.save()
        return True
