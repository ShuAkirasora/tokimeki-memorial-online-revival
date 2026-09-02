"""禁止用語: the word filter behind 「…に禁止語が含まれています。」

Two places in this game refuse text for containing a banned word, and the
client ships both sentences. From ``error_message.bin``, in the client's own
words:

    0x7218 MsgSvNgScriptCommandInput   reason 0
        入力された文字列に禁止語が含まれています。
    0xFF07 (the 仲良しグループ list)    reason 29
        入力されたグループ名に禁止語が含まれています。

⚠️ Neither is the 名前チェック rule. That one refuses a whole 氏名 for being
somebody's name (0x030E reason 2) and compares complete strings; this one asks
whether a banned word occurs ANYWHERE INSIDE what was typed. Two different
questions, two different tables, and a digest list can answer the first but not
this one -- see naming.py for the other half.

THE TABLE
---------
``reference/ngwords.json``: 1355 banned words and 85 exemptions, decoded from
the dictionary the game ships (``ldic/ngwordlist.dat``). Every record in that
file carries a class byte; class 7 is the exemption and everything else is a
ban, which is as much as the file itself says. It does not say what the other
ten class values distinguish, so they are not shipped and nothing uses them.

⭐ The game's client never loads this dictionary -- no code path in it names
the file -- so a word filter is the server's to run or not to exist. That is
the same shape the 名前チェック tables have, and it is why both refusals are
sentences the client is holding for somebody else to select.

The two lists are needed together. 「アホウドリ」 (albatross) contains 「アホウ」,
「ウルトラマンコスモス」 contains 「マンコ」, 「キッコーマン」 contains 「コーマン」
and 「クラブホテル」 contains 「ラブホテル」 -- four of the 85, and a filter that
ships only the ban list refuses all four.

HOW THE COMPARISON IS DONE, AND WHY
-----------------------------------
The original server is gone, so the matching rule cannot be read out of any
binary. It can be read out of the TABLE, which contains entries that are dead
weight under any other rule:

⭐ **Kana are folded**, hiragana onto katakana. Nine exemptions are otherwise
inert -- 「ぱちんこ」 guards 「チンコ」, 「すまんこってす」 guards 「マンコ」,
「そうざい」 guards 「ウザイ」, 「おかめ納豆」 guards 「オカメ」, and five more --
and in every one of the nine the guarded word is katakana while the guard is
hiragana. Fold nothing and all nine protect a word that can never be hit, while
「まんこ」 typed in hiragana walks straight through a table that bans 「マンコ」.

⭐ **ASCII is compared without case.** Every one of the 77 banned ASCII words is
upper case. The single lower-case entry in the whole file is the exemption
「google」, and the only banned word inside it is 「GOO」.

⚠️ Half and full width are NOT folded, and that is the table's word too: it
holds no half-width kana at all, and it spells 「ＴＩＴ」 and 「Ｇスポット」 in
full width beside their ASCII neighbours -- so it distinguishes widths itself
rather than expecting the matcher to.

⚠️ Leading and trailing spaces are stripped from table entries. 37 of the 1442
records have a trailing space, 36 of them exemptions, including all four of the
worked exemptions above; an exemption that only matches when the player also
types a trailing space exempts nothing. Read as data entry, not as syntax.

WHAT AN EXEMPTION DOES
----------------------
It protects a span of the input, not a word in the list. A banned word is
ignored when the whole of it falls inside one occurrence of one exemption, so
「アホウドリ」 passes while 「アホウドリのアホウ」 does not: the second 「アホウ」
is outside the albatross.

⚠️ INVENTED: which wins when a string is BOTH banned and exempt. Seven are --
ホモ, レズ, バカマ, バカ苗病, フジバカマ, ペチジン, ペテン師 -- each appearing
twice in the file under two different class bytes. The exemption wins here,
because that is what the same code already does for a banned word inside a
longer exemption and a special case for equal length would be a rule nobody
observed. ⛔️ Note the file's own order does not agree with itself about it:
the exemption comes first for ホモ and second for レズ, so "first record wins"
is not the answer either.

⚠️ INVENTED: this filter is not applied to chat. The client does not filter
what it receives -- it never loads this dictionary at all -- so a chat filter
would be the server's to build, and there is no refusal message for one in the
whole table. The two callers here are the two the client has sentences for.

AN OPERATOR'S OWN LIST
----------------------
``runtime/ngwords.json``, same shape, merged on top. Words an operator adds are
theirs and never leave their machine.
"""

from __future__ import annotations

import json
from pathlib import Path


#: The shipped table and the operator's optional additions carry the same name
#: in two directories, for the reason naming.RESERVED_FILE gives.
NGWORDS_FILE = "ngwords.json"

#: 0x7218 MsgSvNgScriptCommandInput. The list has one row and this is it:
#: 「入力された文字列に禁止語が含まれています。」
SCRIPT_INPUT_REASON = 0

#: 0xFF07 reason 29, which is what a refused 0x6202 MsgSvNgCharaGroupCreate
#: selects: 「入力されたグループ名に禁止語が含まれています。」
GROUP_NAME_REASON = 29

#: Where the kana blocks sit relative to one another. Hiragana ぁ..ゖ maps onto
#: katakana ァ..ヶ by a constant, which is the whole of the fold.
_HIRAGANA_FIRST = "ぁ"
_HIRAGANA_LAST = "ゖ"
_KANA_SHIFT = 0x60


def fold(text: str) -> str:
    """The form both sides of the comparison are put in. See the module head.

    Kana onto katakana and ASCII onto upper case, and nothing else -- in
    particular no width folding and no NFKC, which would erase distinctions the
    table draws for itself.
    """
    out = []
    for ch in text:
        if _HIRAGANA_FIRST <= ch <= _HIRAGANA_LAST:
            out.append(chr(ord(ch) + _KANA_SHIFT))
        else:
            out.append(ch)
    return "".join(out).upper()


class NgWords:
    """The banned words and the exemptions, ready to be asked about a string.

    The file is a JSON object with two lists::

        {"banned": ["愛液", ...], "exempt": ["アホウドリ", ...]}

    ⚠️ The class byte each record carries in the game's own dictionary is not
    in that file and is not wanted here. Nothing beyond "7 is an exemption" is
    known about what its eleven values distinguish, so a loader that acted on
    it would be acting on a guess.
    """

    def __init__(self, *paths: "Path | None") -> None:
        self.paths = [p for p in paths if p is not None]
        self.banned: "set[str]" = set()
        self.exempt: "set[str]" = set()
        for path in self.paths:
            self._load(path)
        # How far back a candidate substring can start. Computed rather than
        # constant: an operator's own list can be longer than the shipped one,
        # and a cap that did not grow with it would silently stop matching
        # their longest words.
        self.longest_banned = max((len(w) for w in self.banned), default=0)
        self.longest_exempt = max((len(w) for w in self.exempt), default=0)
        if not self.banned and self.paths:
            print("[ngwords] no word list; 禁止用語 is not enforced")

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[ngwords] ignoring unreadable {path}: {exc}")
            return
        if not isinstance(raw, dict):
            print(f"[ngwords] ignoring {path}: expected a JSON object")
            return
        counts = {}
        for key, into in (("banned", self.banned), ("exempt", self.exempt)):
            entries = raw.get(key)
            if not isinstance(entries, list):
                continue
            before = len(into)
            for entry in entries:
                if not isinstance(entry, str):
                    continue
                word = fold(entry.strip())
                if word:
                    # Merged, not replaced: an operator's file adds to the
                    # shipped one rather than standing in for it.
                    into.add(word)
            counts[key] = len(into) - before
        if counts:
            print(f"[ngwords] {path.parent.name}/{path.name}: " + ", ".join(
                f"{n} {k}" for k, n in sorted(counts.items())
            ))

    def __len__(self) -> int:
        return len(self.banned)

    def _exempt_spans(self, folded: str) -> "list[tuple[int, int]]":
        """Every occurrence of every exemption in an already-folded string.

        Occurrences, not a per-character mask: a banned word is only spared
        when ONE exemption covers all of it, and a mask cannot tell that from
        two adjacent exemptions covering half each.
        """
        spans = []
        for start in range(len(folded)):
            stop = min(len(folded), start + self.longest_exempt)
            for end in range(stop, start, -1):
                if folded[start:end] in self.exempt:
                    spans.append((start, end))
        return spans

    def hit(self, text: str) -> "str | None":
        """The banned word this string contains, or None if it contains none.

        The word comes back folded, which is the form it was matched in; it is
        for the log, and a caller that wants to show the player anything shows
        them the client's own sentence instead.
        """
        if not self.banned or not text:
            return None
        folded = fold(text)
        spans = self._exempt_spans(folded)
        for start in range(len(folded)):
            stop = min(len(folded), start + self.longest_banned)
            for end in range(stop, start, -1):
                word = folded[start:end]
                if word not in self.banned:
                    continue
                if any(lo <= start and end <= hi for lo, hi in spans):
                    continue      # wholly inside one exemption
                return word
        return None

    def hit_bytes(self, raw: bytes) -> "str | None":
        """Same question about a field that arrived on the wire.

        ⚠️ Cut at the first NUL before decoding: every text field in this
        protocol is a C string inside a fixed-width buffer, and the bytes past
        the terminator are whatever the sender's buffer held.
        """
        try:
            text = raw.split(b"\x00")[0].decode("cp932")
        except UnicodeDecodeError:
            # Undecodable bytes are not a banned word; whoever is deciding
            # whether to accept the field at all is a separate question, and
            # answering 禁止語 to it would put the wrong sentence on screen.
            return None
        return self.hit(text)
