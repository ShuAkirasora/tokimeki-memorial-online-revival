"""What a character keeps from a ドラマイベント it has played to the end.

The play itself is `mps_session`'s ドラマパーティ and `gs3vm`'s shadow; this is
the one thing that outlives it. A ドラマイベント leaves nothing else behind --
the party is a board in memory, the script goes with the connection -- so
without this a scenario played to `OP_END` is indistinguishable from one never
opened.

⭐⭐⭐ WHERE THE TWO FIELDS COME FROM, and why they are these two and not some
record invented here. Both ends of it are the client's own words:

  * the record the client keeps per event is eight fields wide, and it names
    them itself in the dump of `MsgSvNotifyCharaMenuDramaEventList` (0x8CCEC0)::

        dramaEventId={categoryId,id}, nPartyNum, flgSelectActor,
        orderOpen, orderLast, **maxPoint**, **flgAcquiredKeyword**

  * and the instruction that ends every ドラマイベント, 0x9200
    RESULT_MULTI_PLAYER_EVENT, carries a 評価ポイント (a named score, e.g.
    「シンクロ度」 in un007, 「タイムトラベラー度」 in un081) and a count of
    入手キーワード -- see `gs3vm.OP_RESULT_MULTI_PLAYER_EVENT` for how those
    four fields were read out of the client's decoder slot.

⇒ `maxPoint` is where that score lands and `flgAcquiredKeyword` is where that
count lands. ⚠️ That pairing is a reading, not a measurement: nothing has yet
been seen on screen with a non-zero value in either field. What is measured is
the layout of both halves.

⚠️⚠️ **入手キーワード数 is zero at all 296 sites in all 683 scenarios**, so in
this build nothing ever sets `flgAcquiredKeyword`. The path is written anyway,
because the alternative -- leaving the count unread -- is how a field stays
"unknown" forever. ⛔️ Do not read the constant zero as "keywords are granted
somewhere else and this is a hole": drama scenarios grant keywords through
`PC_KEYWORD_UPDATE` while they play, which is a different instruction.

⚠️ The other four fields stay zero. `nPartyNum` is measured to be ignored
(2.183), and `orderOpen`/`orderLast` have names and nothing else.
"""
from __future__ import annotations

#: The width of `maxPoint` on the wire: one byte, out of the client's own
#: deserializer for the list entry (widths 2,2,2,1,2,8,1,2 after the count).
#: A 評価ポイント is a 16-bit register on this end, so it can in principle hold
#: more than this; the clamp is at the packing and is logged when it bites.
MAX_POINT_CEILING = 0xFF


class DramaRecords:
    """One character's ドラマイベント records, keyed by ``(genre, index)``.

    Stored on the character record under "dramaEvents" and rebuilt from that
    dict each time, the same arrangement as Career, Posts and ScoreCard. A
    record with no such key produces no rows at all, which puts exactly the
    zeroes on the wire that every character has sent since round 35.

    ⚠️ Keys are strings in JSON (``"4:1"``) and tuples in here, because the two
    halves are a genre and an index everywhere else in this server and joining
    them into one number would make every caller unpack it again.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        self.rows: dict[tuple[int, int], dict[str, int]] = {}
        if not isinstance(saved, dict):
            return
        for key, row in saved.items():
            try:
                genre, index = (int(half) for half in str(key).split(":", 1))
            except (TypeError, ValueError):
                print(f"[dramarecord] {key!r} is not a genre:index key, dropping")
                continue
            if not isinstance(row, dict):
                continue
            self.rows[(genre, index)] = {
                "maxPoint": _int(row.get("maxPoint")),
                "keyword": 1 if _int(row.get("keyword")) else 0,
                "plays": _int(row.get("plays")),
            }

    def to_json(self) -> dict:
        return {f"{genre}:{index}": dict(row)
                for (genre, index), row in sorted(self.rows.items())}

    # -- what a finished play leaves ---------------------------------------
    def finished(self, genre: int, index: int, point: "int | None",
                 keywords: int = 0) -> dict:
        """Book one ending. Returns the row as it now stands.

        ``point`` is the 評価ポイント this ending reported, or None when this
        end could not produce it -- an ending whose operand names a temporary
        nobody wrote a constant into, or a shadow that lost its place
        (`gs3vm.Follower.event_result`). ⭐ A play with no score is
        still a play: `plays` counts it, and only `maxPoint` is left alone.
        ⚠️ It is a *max*, which is the field's own name: a worse second run
        does not overwrite a better first one.
        """
        row = self.rows.setdefault((genre, index),
                                   {"maxPoint": 0, "keyword": 0, "plays": 0})
        row["plays"] += 1
        if point is not None and point > row["maxPoint"]:
            row["maxPoint"] = point
        if keywords:
            row["keyword"] = 1
        return row

    # -- what goes on the wire ---------------------------------------------
    def wire(self, genre: int, index: int) -> tuple[int, int]:
        """``(maxPoint, flgAcquiredKeyword)`` for one event, both clamped."""
        row = self.rows.get((genre, index))
        if row is None:
            return 0, 0
        point = row["maxPoint"]
        if point > MAX_POINT_CEILING:
            print(f"[dramarecord] {genre}:{index} maxPoint {point} does not fit "
                  f"in a byte, sending {MAX_POINT_CEILING}")
            point = MAX_POINT_CEILING
        return max(0, point), row["keyword"]

    def summary(self) -> str:
        if not self.rows:
            return "ドラマイベント：まだ一つも演っていない"
        return "ドラマイベント：" + " ".join(
            f"{genre}:{index}={row['maxPoint']}"
            + ("K" if row["keyword"] else "")
            + f"×{row['plays']}"
            for (genre, index), row in sorted(self.rows.items())
        )


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
