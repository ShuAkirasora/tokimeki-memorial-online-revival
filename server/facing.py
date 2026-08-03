"""Which way a character is turned: the ``direction`` byte, and how to pick one.

Measured, not guessed. ``/dirs`` puts one stand-in per value 0-15 on the ground
at once — the ruler trick — and reading the sixteen sprites off one screenshot
gave this, with no exceptions and nothing left over:

    0 下   1 上   2 下   3 下      8 右   9 右上  10 右下  11 下
    4 左   5 左上 6 左下 7 下     12 下  13 下   14 下    15 下

That is a four-bit mask of the arrow keys, and it explains all sixteen readings:
each of 上/下/左/右 is one bit, the two diagonals that make sense are the two
sensible bits together, and every self-contradicting combination (上|下, 左|右,
three bits, four bits) falls back to the same pose. The eight legal values are
VALUES below; the client's own MsgClCastCharaTurn has been seen sending 5 and
10, both of them in that set.

Where the readings above say 上/下/左/右 they mean *on screen*, because that is
what a player can see. The wire's cells are the isometric axes underneath, and
the two are turned 45 degrees from each other — one cell of +X moves a sprite
down-and-right on screen, one cell of +Y moves it down-and-left, as measured off
the ruler screenshot at (+136,+87) and (-133,+88) pixels. So screen-right grows
with ``x - y`` and screen-down grows with ``x + y``, which is the whole of
``of_move``.

One thing this module cannot yet vouch for: the sixteen were read from
MsgSvNotifyCharacterAdd, and the value 0 there was read as 下, while 0 in
MsgSvNotifyCharaMove looked like 右 to the player who reported it. Since 0 sets
no bit at all, "whatever the client falls back to" is allowed to differ between
the two, and nothing here emits 0 any more, so the discrepancy stays parked
rather than being explained away.
"""

from __future__ import annotations

UP = 1
DOWN = 2
LEFT = 4
RIGHT = 8

# Every value the client draws as a distinct pose. Anything else is a
# contradiction it collapses onto one fallback, so these are the only numbers
# this server puts on the wire.
VALUES = (UP, DOWN, LEFT, RIGHT, UP | LEFT, DOWN | LEFT, UP | RIGHT, DOWN | RIGHT)

NAMES = {
    UP: "上",
    DOWN: "下",
    LEFT: "左",
    RIGHT: "右",
    UP | LEFT: "左上",
    DOWN | LEFT: "左下",
    UP | RIGHT: "右上",
    DOWN | RIGHT: "右下",
}

# Facing the camera. What a character arrives on a new map as, and what a
# session starts as, in place of the 0 that used to stand for "no idea".
DEFAULT = DOWN


def of_move(start: tuple[int, int], end: tuple[int, int]) -> int | None:
    """The way a walk from `start` to `end` leaves a character turned.

    None when the two cells are the same, which is the caller's cue to leave the
    facing alone rather than to reach for a default: a walk that arrives where
    it began says nothing about which way to look.
    """
    across = (end[0] - start[0]) - (end[1] - start[1])  # screen right when > 0
    down = (end[0] - start[0]) + (end[1] - start[1])  # screen down when > 0
    direction = 0
    if across:
        direction |= RIGHT if across > 0 else LEFT
    if down:
        direction |= DOWN if down > 0 else UP
    return direction or None


def name(direction: int) -> str:
    """A readable facing for a log line; unnamed values show as themselves."""
    return NAMES.get(direction, str(direction))
