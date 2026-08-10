"""charaId -> accountId, kept on disk, because the id does not say.

This server used to answer "who owns this character" by shifting: account n was
handed the charaId slice ``n << 24``, so ``chara_id >> 24`` was the owner. That
was ours, it was never attested, and the client's own message table contradicts
it in four places -- the argument is in accounts.py's docstring and the evidence
is written up in the reverse-engineering notes. The short form: the original's
operator interface takes accountId and charaId as two separate required fields
when creating a character and only a charaId when destroying one. Two ids go in
because neither can be computed from the other.

So the shift is gone and this file is what replaces it. Two facts, kept apart on
purpose, because only one of them was recovered from the client:

  RECOVERED   A charaId does not encode its owner. The server holds an index
              from one to the other and looks it up. Every message in the
              operator family addresses a character by charaId alone, which is
              what having such an index looks like from the outside.

  INVENTED    How ids get handed out. One counter for the whole server, walking
              up from CHARA_ID_BASE, and a number is never handed out twice.
              KONAMI's scheme is not recoverable -- the client is told ids, it
              never derives one -- so this is a choice and is marked as one.

Why the counter never goes backwards, since that is the part with a reason
rather than a preference: a charaId is referenced from outside the record it
names. loverCharaId, friendGroupId and the address book all store one. Reusing
the id of a deleted character silently points every one of those at whoever
comes next. The old ``max(what is left) + 1`` did exactly that -- delete the
newest character and the following create took its number back.

On disk, ``runtime/accounts/charas.json``::

    {
      "next": "0x0b000003",
      "owners": {
        "0x01000000": 1,
        "0x01000001": 1
      }
    }

Hex keys because every id in this codebase and in the notes is written in hex,
and this file is meant to be readable by whoever is holding the save.
"""

from __future__ import annotations

import json
from pathlib import Path

from characters import CHARA_ID_BASE

# The last id the client draws as an ordinary character. Measured, not chosen:
# the range check at 0x00404FF9 accepts 0x01000000 through 0xFFFFFFFE, and the
# one value above it is this game's "nothing here" sentinel. See characters.py's
# CHARA_ID_BASE for the other end of the same check and for the crash that
# established it.
CHARA_ID_MAX = 0xFFFF_FFFE


class CharaIndex:
    """Who owns each charaId, and which id goes out next.

    Every mutation writes the file. It is small, it is written once per
    character created or deleted rather than once per step, and the alternative
    -- holding it in memory and saving at exit -- loses the mapping if the
    process dies, which turns a save file into orphaned characters.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / "charas.json"
        self.owners: dict[int, int] = {}
        self.next_id: int = CHARA_ID_BASE
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[charaids] ignoring unreadable {self.path}: {exc}")
            return
        if not isinstance(raw, dict):
            return
        owners = raw.get("owners", {})
        if isinstance(owners, dict):
            for key, account_id in owners.items():
                try:
                    self.owners[int(str(key), 16)] = int(account_id)
                except ValueError:
                    print(f"[charaids] ignoring unreadable charaId key {key!r}")
        try:
            self.next_id = max(self.next_id, int(str(raw.get("next", "0x0")), 16))
        except ValueError:
            print(f"[charaids] unreadable next id {raw.get('next')!r}, keeping default")

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "next": f"0x{self.next_id:08x}",
                    "owners": {
                        f"0x{chara_id:08x}": account_id
                        for chara_id, account_id in sorted(self.owners.items())
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- migration --------------------------------------------------------

    def backfill(self, saved: "dict[int, list[int]]") -> None:
        """Take in the characters already on disk, once, at startup.

        ``saved`` is ``{accountId: [charaId, ...]}`` read out of the per-account
        files. Every id that predates this index has to land in it or its owner
        stops being findable -- and every id on this machine predates it, since
        they were all minted under the shift.

        Nothing is renumbered. The ids the shift produced are all inside the
        range the client accepts, and only this server ever read meaning into
        them, so the migration is a new file and not a rewrite of the saves.

        The counter is pushed above everything seen, so a migrated id can never
        be handed out a second time.

        ⚠️ This adds and never removes. An account directory deleted by hand
        leaves its ids here, pointing at a store that will come back empty --
        harmless, and preferable to the other failure, where a file this code
        decided was stale took somebody's characters with it.
        """
        changed = not self.path.exists()
        for account_id, chara_ids in saved.items():
            for chara_id in chara_ids:
                if self.owners.get(chara_id) != account_id:
                    self.owners[chara_id] = account_id
                    changed = True
                if chara_id >= self.next_id:
                    self.next_id = chara_id + 1
                    changed = True
        if changed:
            self._save()
            print(
                f"[charaids] {len(self.owners)} character(s) indexed, "
                f"next id 0x{self.next_id:08x}"
            )

    # -- lookup and allocation --------------------------------------------

    def owner(self, chara_id: int) -> int | None:
        """The account holding this charaId, or None if nothing does.

        None is the answer for a probe id, a stand-in, or anything a stranger
        made up -- those were never minted here, so no account claims them.
        """
        return self.owners.get(chara_id)

    def ids_of(self, account_id: int) -> list[int]:
        """Every charaId recorded against one account, in minting order."""
        return sorted(c for c, a in self.owners.items() if a == account_id)

    def mint(self, account_id: int) -> int:
        """The next charaId, recorded as belonging to this account.

        Walks past anything already claimed rather than trusting the counter
        alone: the file is editable, and an id handed out twice is two players
        sharing one character.
        """
        chara_id = self.next_id
        while chara_id in self.owners:
            chara_id += 1
        if chara_id > CHARA_ID_MAX:
            raise RuntimeError(
                f"charaId space exhausted at 0x{CHARA_ID_MAX:08x}"
            )
        self.owners[chara_id] = account_id
        self.next_id = chara_id + 1
        self._save()
        return chara_id

    def release(self, chara_id: int) -> None:
        """Forget who owned a deleted character, without freeing its number.

        The counter is deliberately untouched. See the module docstring: the id
        of a deleted character is still written down in other characters'
        records, and handing it to the next create points those at a stranger.
        """
        if self.owners.pop(chara_id, None) is not None:
            self._save()

    def summary(self) -> str:
        if not self.owners:
            return f"(no characters yet, next 0x{self.next_id:08x})"
        return (
            f"{len(self.owners)} character(s) across "
            f"{len(set(self.owners.values()))} account(s), "
            f"next 0x{self.next_id:08x}"
        )
