"""ＧＭコール -- the システムメニュー row that calls for a 風紀委員, and its queue.

WHAT IT IS, IN THE VENDOR'S WORDS
---------------------------------
The game shipped with a support channel built into the client. From the manual
(manual/p10_01):

    ゲーム中、プレイヤーが快適にプレイ出来るように管理しているのが
    ゲームマスター（以下、GM）である風紀委員です。
    ...
    風紀委員へコールする場合、メインメニュー中の「システムメニュー」にある
    「ＧＭコール」をクリックします。プルダウンメニューが表示されますので、
    その中から発生している問題の種類を選択し、［コール］を押します。

That pull-down is a table in the game's own data, and the operating policy
(support/housin.txt, ■ＧＭコールについて) says what the queue behind it is for.
So none of the rules below are this project's: they are read off the vendor's
documentation, the vendor's tables, and the sentences the client already holds.

THE WINDOW, CONTROL BY CONTROL (win_text 494..499)
--------------------------------------------------
    494  --ご注意--
    495  ・バグ報告は運営ＨＰのフォームよりお願い致します。 ...
    496  報告の種類          <- the pull-down
    497  コール              <- sends 0x6900
    498  やめる
    499  ＧＭコール          <- the window's title

THE PULL-DOWN IS `gm_call_type`, AND IT IS INDEXED BY ID
--------------------------------------------------------
Ten rows. The client walks the whole table once and files each row's label
under its own key in a map, then looks rows up by that key -- so the ids are
the wire values and the gaps in them are real gaps:

     0  (blank)          ⭐ NOT a report type -- see below
     1  ハラスメント        harassment
     2  ストーカー          stalking
     3  中傷・差別          slander and discrimination
     4  詐欺行為            fraud
     5  ゲーム妨害          griefing
     6  不正行為            cheating (外部ツール・バグ利用等)
     7  迷惑行為            nuisance, everything else human
     8  -- no such row --
     9  -- no such row --
    10  データ不整合        lost or inconsistent game data
    11  キャラ移動不可      the character will not move

⭐ Row 0 is 「非選択」, and it is the one row whose pull-down label is empty.
What it carries instead is the pull-down's *initial* text,「選択してください」,
which is where the client reads it from. It is the "nothing chosen yet" state,
not a kind of report, so it is not in REPORT_TYPES and arriving here it is
refused the way any other unknown value is.

⭐⭐ Rows 1..7 are the human troubles and 10..11 the system ones, which is the
same split the manual draws (「人為的なトラブル」 / 「ゲームシステムに関する
トラブル」). The policy page lists three system cases -- 進行不可, 移動不可,
その他 -- and the table ships two of them; whatever stood at 8 and 9 is not in
the shipped data and nothing here guesses at it.

THE MESSAGES
------------
    0x6900 MsgClRequestGMCall        u8  report type
    0x6901 MsgSvOkGMCall             u8  how many calls were already waiting
    0x6902 MsgSvNgGMCall             u8  reason
    0x6903 MsgClRequestGMCallCancel  (empty)
    0x6904 MsgSvOkGMCallCancel       (empty)
    0x6905 MsgSvNgGMCallCancel       u8  reason

Every one of those shapes is the client's own reader, not a guess: the
deserializers behind 0x6900/0x6902/0x6905 pull a single int8 through the input
stream's read-int8 slot, 0x6901 pulls a single uint8, and 0x6903/0x6904
deserialize through the shared zero-parameter stub that reads nothing at all.

⭐⭐⭐ WHAT THE BYTE IN THE Ok IS. The client holds two sentences for a call
that was accepted and picks between them:

    msg_text 366  GMコールを受け付けました。返答には時間がかかる場合がございます。
    msg_text 367  只今、%1%件待ちです。ただし、緊急な用件を優先する場合があります。

and one for the cancel confirmation that reuses the same number:

    msg_text 364  只今、%1%件待ちです。コールを取り消しますか？

%1% is a count of calls already queued, and the Ok carries exactly one byte and
nothing else. So the byte is that count -- taken here BEFORE the new call is
added, because it is what the player is being told they are waiting behind.

THE REFUSALS ARE THE CLIENT'S OWN SENTENCES
--------------------------------------------
`error_message.bin` holds nine rows for 0x6902 and nine for 0x6905, and reason
is the index into each list. The ones marked 「未使用：：：」 are the
developers' own dead rows and are never sent from here.

    0x6902  0  プレイヤー情報が不正です。
            1  報告の種類が不正です。
            2  現在、GMコールは禁止されています。
            3  今の状態では、GMコールを行うことはできません。
            4  未使用：：：
            5  既にGMコールを送っています。同時に複数件のＧＭコールを行うことはできません。
            6  只今、多数のGMコールに対応しきれておりません。時間をおいて再コールをお願いいたします。
            7  ＧＭコール送信者のキャラクターデータが見つかりません。
            8  未使用：：：

    0x6905  0  プレイヤー情報が不正です。
            1  未使用：：：
            2  現在、GMコール機能は使用できません。
            3  今の状態では、GMコールの取り消しを行うことはできません。
            4  GMコールをしていません。
            5  未使用：：：
            6  現在、ＧＭが対応中ですので、ＧＭコールを取り消すことはできません。
            7  未使用：：：
            8  未使用：：：

⭐ Row 5 of the first list is the whole concurrency rule, written out: one open
call per character, and a second one is refused rather than queued. Row 6 of
the second is the state rule: once a GM has picked the call up it can no longer
be taken back. Both are enforced below and neither was chosen here.

WHAT IS NOT IMPLEMENTED, AND WHY THAT IS NOT A GAP IN THIS FILE
----------------------------------------------------------------
The other half of the subsystem is the GM's own console -- ＧＭメニュー and
ＧＭコールリスト (win_text 483..493), the 0x67xx family, every message of which
answers 「ＧＭ権限がありません」 to anyone without the flag. Nothing here grants
that flag and no session on this server has it, so those messages are not
answered at all. What a GM would *do* with a call -- ＧＭチャット, appearing
beside the player, the sanctions table in the operating policy -- is a person's
job, not a protocol's, and inventing a bot to fake it would be inventing.

⚠️ MsgSvResultGMCallList (0x6712) therefore still answers a count of zero from
the fixed-reply table, and this book is not wired into it. That is deliberate:
the count is the GM list's, the entries behind it are 36-byte records this
server has never sent, and answering a non-zero count would promise entries
that never arrive. A queue with calls in it is visible through the console
below, which is the operator's channel and does not go on the wire.

⚠️⚠️ A call OUTLIVES ITS CALLER'S SESSION on purpose. The operating policy is
explicit that logging out after calling may cost you the answer, not the call:
「GMコール申請後、GMからの連絡が入る前にログアウトしてしまいますと、返答でき
ない場合があります」. So logging out does not cancel; only 0x6903 and the
console do.

game_master_pc: NOT USED HERE
------------------------------
The roster of GM characters (ときめき太郎, ときめき花子 and ＧＭ睦月..ＧＭ師走,
the twelve traditional month names) is a table of PC records the client never
loads, keyed by 「ゲームマスターＰＣ」 -- character type 15. Putting those
characters on the server is a separate piece of work and this file does not do
it. It is mentioned because of one consequence that already matters: none of
those fourteen names is in the reserved-name tables naming.py enforces, while
「ＧＭ」 and 「ゲームマスター」 are. See the reverse-engineering notes.

RESTORED and INVENTED
---------------------
RESTORED: the report-type ids and which of them are selectable; the message
shapes; every refusal and its number; one-open-call-per-character; a call that
a GM has taken up cannot be cancelled; the Ok's byte being the queue length.

INVENTED: nothing on the wire. The console commands and the JSON file are this
server's own, the way every other store here is.
"""
from __future__ import annotations

import json
import struct
from datetime import datetime
from pathlib import Path

MSG_CL_REQUEST_GM_CALL = 0x6900
MSG_SV_OK_GM_CALL = 0x6901
MSG_SV_NG_GM_CALL = 0x6902
MSG_CL_REQUEST_GM_CALL_CANCEL = 0x6903
MSG_SV_OK_GM_CALL_CANCEL = 0x6904
MSG_SV_NG_GM_CALL_CANCEL = 0x6905

#: What the dispatcher hands to the handler. The 0x67xx GM-side family is not
#: in here on purpose -- see the docstring.
HANDLED = frozenset({MSG_CL_REQUEST_GM_CALL, MSG_CL_REQUEST_GM_CALL_CANCEL})

#: 0x6902 MsgSvNgGMCall, by the client's own row numbers.
NG_BAD_PLAYER = 0        # プレイヤー情報が不正です。
NG_BAD_TYPE = 1          # 報告の種類が不正です。
NG_ALREADY_CALLING = 5   # 既にGMコールを送っています。
NG_NO_CHARACTER = 7      # ＧＭコール送信者のキャラクターデータが見つかりません。

#: 0x6905 MsgSvNgGMCallCancel, likewise.
NG_CANCEL_BAD_PLAYER = 0  # プレイヤー情報が不正です。
NG_CANCEL_NOT_CALLING = 4  # GMコールをしていません。
NG_CANCEL_IN_HAND = 6      # 現在、ＧＭが対応中ですので、…取り消すことはできません。

#: The pull-down's ids minus 「非選択」. Read off `gm_call_type`; the private
#: tree's the GM-call check re-derives this from the table and says so if the two
#: ever part company.
REPORT_TYPES = frozenset({1, 2, 3, 4, 5, 6, 7, 10, 11})

#: The Ok carries the queue length in one unsigned byte, so that is the ceiling
#: on what can honestly be reported. A longer queue reports the ceiling rather
#: than wrapping to a small number, which would read as "almost no wait".
MAX_REPORTABLE_WAIT = 0xFF

FILE = "gmcalls.json"


class Call:
    """One open ＧＭコール: who, what kind, when, and whether a GM has it.

    `taken` is the 対応中 state the cancel refusal turns on. It is a flag rather
    than the client's own state byte because the state byte only exists in the
    36-byte list entry, which this server has never sent and whose value range
    has never been observed -- so there is nothing to be faithful to yet.
    """

    def __init__(self, chara_id: int, report_type: int, raised: str,
                 taken: bool = False) -> None:
        self.chara_id = chara_id
        self.report_type = report_type
        self.raised = raised          # ISO 8601, local time
        self.taken = taken

    def label(self) -> str:
        state = "in hand" if self.taken else "waiting"
        return (f"charaId=0x{self.chara_id:x} type={self.report_type} "
                f"{self.raised} ({state})")

    def as_json(self) -> dict:
        return {"type": self.report_type, "raised": self.raised, "taken": self.taken}


class CallBook:
    """Every open call on the server, in one file beside the other shared books.

    One file rather than one per account, for the reason friends.FriendBook
    gives: a queue is the server's, not an account's, and the count that rides
    in the Ok is a count across everybody.

    Every mutation writes the file. A support queue that a crash empties is
    worse than none, and the file is a few hundred bytes.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / FILE
        self.calls: dict[int, Call] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[gmcall] ignoring unreadable {self.path}: {exc}")
            return
        if not isinstance(raw, dict):
            return
        for key, body in (raw.get("calls") or {}).items():
            try:
                chara_id = int(str(key), 16)
            except ValueError:
                print(f"[gmcall] ignoring unreadable charaId {key!r}")
                continue
            if not isinstance(body, dict):
                continue
            report_type = body.get("type")
            if report_type not in REPORT_TYPES:
                # The table is the authority even over this server's own file:
                # a saved call whose type is no longer a type cannot be shown.
                print(f"[gmcall] dropping saved call with type {report_type!r}")
                continue
            self.calls[chara_id] = Call(
                chara_id, report_type, str(body.get("raised", "")),
                bool(body.get("taken")),
            )
        if self.calls:
            print(f"[gmcall] {self.summary()}")

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        body = {"calls": {f"{c.chara_id:x}": c.as_json() for c in self.calls.values()}}
        self.path.write_text(
            json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    # -- the queue --------------------------------------------------------

    def of(self, chara_id: int) -> "Call | None":
        return self.calls.get(chara_id)

    def waiting(self) -> int:
        """How many calls are open. This is the number the Ok carries."""
        return min(len(self.calls), MAX_REPORTABLE_WAIT)

    def open(self, chara_id: int, report_type: int, when: datetime | None = None) -> Call:
        call = Call(
            chara_id, report_type,
            (when or datetime.now()).replace(microsecond=0).isoformat(),
        )
        self.calls[chara_id] = call
        self._save()
        return call

    def close(self, chara_id: int) -> "Call | None":
        call = self.calls.pop(chara_id, None)
        if call is not None:
            self._save()
        return call

    def take(self, chara_id: int, taken: bool = True) -> "Call | None":
        call = self.calls.get(chara_id)
        if call is None:
            return None
        call.taken = taken
        self._save()
        return call

    def summary(self) -> str:
        held = sum(1 for c in self.calls.values() if c.taken)
        return f"{len(self.calls)} open call(s), {held} in hand"


# -- what goes on the wire ---------------------------------------------------


def ok_params(waiting: int) -> bytes:
    """0x6901: the one byte, the count of calls already queued."""
    return struct.pack(">B", min(waiting, MAX_REPORTABLE_WAIT))


def ng_params(reason: int) -> bytes:
    """0x6902 and 0x6905 both: one byte, the row number in the client's list."""
    return struct.pack(">B", reason)


def parse_request(params: bytes) -> "int | None":
    """0x6900's body: one byte, the report type. None if it did not arrive."""
    if len(params) < 1:
        return None
    return params[0]
