"""オプション: the four settings on the client's option screen that cross the wire.

Two exchanges, one pair each way:

    0x0700 MsgClQueryOption             -> 0x0701 MsgSvResultOption (four u8)
                                        -> 0x0702 MsgSvErrorOption  (u8 reason)
    0x0703 MsgClRequestGameOptionUpdate -> 0x0704 MsgSvOkGameOptionUpdate (empty)
                                        -> 0x0705 MsgSvNgGameOptionUpdate (u8)

The four u8 are named lesson, test, scorecard and career by the client's dump
at 0x8DA0D0, and the manual page for the option screen spells all four out as
ON/OFF pairs:

    lesson     授業の有無    ON = 出席する      OFF = 出席しない
    test       試験の有無    ON = 出席する      OFF = 出席しない
    scorecard  通知表公開    ON = others may look at this character's 通知表
    career     経歴公開      ON = others may look at this character's 経歴

⚠️ All-zero is not neutral, it is all-OFF: no lessons, no exams, and both
cards private. (1, 1, 0, 0) is the factory setting this server had answered
0x0700 with as a constant ever since the first character walked in, so it is
what a character with nothing saved gets -- turning this from a constant into a
per-character record must not move anybody's settings, and that is why the
default is spelled out rather than zeroed.

⭐⭐ Round 152 read all four off the option screen with the client and they
matched those four bytes one for one, which is what ties the dump's field names
to the manual's ON/OFF rows: 授業の有無 ON, 試験の有無 ON, 通知表公開 OFF,
経歴公開 OFF. The rest of that screen -- 吹き出し表示, マップ上の名前表示,
メッセージ速度, 強調単語, サウンド, メッセージキー -- is not in these four
bytes; opening the window sends nothing at all, and only these four rows
produce an 0x0703, so the others really are client-side.

⭐ The *order* of 0x0703's four bytes was an inference (the shape reader reads
1+1+1+1, and the message is named the push-back half of 0x0701) until round 152
flipped 通知表公開 alone and watched byte three -- and only byte three -- move.
⚠️ Measured for that one field; the other three rode along in the same update.
The handler names each byte in its log so the next toggle says the same thing.
"""

from __future__ import annotations

import struct

MSG_CL_QUERY_OPTION = 0x0700
MSG_SV_RESULT_OPTION = 0x0701
MSG_SV_ERROR_OPTION = 0x0702
MSG_CL_REQUEST_GAME_OPTION_UPDATE = 0x0703
MSG_SV_OK_GAME_OPTION_UPDATE = 0x0704
MSG_SV_NG_GAME_OPTION_UPDATE = 0x0705

#: Wire order, which is also the order the dump prints them in.
FIELDS = ("lesson", "test", "scorecard", "career")

#: What each flag is called on the option screen itself.
LABELS = {
    "lesson": "授業の有無",
    "test": "試験の有無",
    "scorecard": "通知表公開",
    "career": "経歴公開",
}

#: The setting a character with nothing saved has. Attend both, publish neither.
DEFAULTS = (1, 1, 0, 0)

SIZE = len(FIELDS)


class GameOptions:
    """One character's four wire-visible オプション flags.

    Stored on the character record under "options" and rebuilt from that dict
    each time, the same arrangement as Romance, ScoreCard and AbilitySheet.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.flags = {
            name: 1 if int(saved.get(name, default)) else 0
            for name, default in zip(FIELDS, DEFAULTS)
        }

    def to_json(self) -> dict:
        return dict(self.flags)

    def __getitem__(self, name: str) -> int:
        return self.flags[name]

    def set(self, name: str, value: bool) -> None:
        self.flags[name] = 1 if value else 0

    def update(self, values: "tuple[int, int, int, int]") -> None:
        for name, value in zip(FIELDS, values):
            self.set(name, value)

    def result_params(self) -> bytes:
        """The body of MsgSvResultOption: four u8 in wire order."""
        return struct.pack(">4B", *(self.flags[name] for name in FIELDS))

    def summary(self) -> str:
        return " ".join(
            f"{name}={self.flags[name]}" for name in FIELDS
        )

    def lines(self) -> "list[str]":
        return [
            f"{LABELS[name]} {'ON' if self.flags[name] else 'OFF'}"
            for name in FIELDS
        ]


def parse_update(params: bytes) -> "tuple[int, int, int, int] | None":
    """MsgClRequestGameOptionUpdate's four u8, or None if the body is short.

    Anything non-zero is ON: the field is a bool on the far side and this end
    has never seen a value other than 0 or 1, so normalising here keeps a
    surprise out of the store rather than hiding it -- the handler logs the raw
    bytes before this runs.
    """
    if len(params) < SIZE:
        return None
    values = struct.unpack_from(">4B", params, 0)
    return tuple(1 if value else 0 for value in values)  # type: ignore[return-value]
