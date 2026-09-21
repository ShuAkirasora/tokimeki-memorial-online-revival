"""Saying so before the lights go out.

Until now this end stopped the way a process stops: the socket closed in the
middle of a sentence, and the client put up its red 「通信が断たれました」 box.
That box is what the client says about *any* connection that dies under it, so
a planned restart and a pulled cable look exactly the same to the player, who
is told neither why it happened nor whether to wait.

The client can be told. 0xA001 MsgSvNotifySystemMessage is this server's own
voice -- see sysmsg.py for the wire shape and for what the window does once it
is up -- and a line of text in a window that does not stop the game is what a
「まもなくサーバを停止します」 would always have gone out on. What this file
adds is the small amount of order that turns that message into a shutdown:
say it, wait exactly as long as was promised, then go.

⚠️⚠️ WHAT IS RECOVERED HERE, AND WHAT IS NOT. The window, its button and the
fact that this end has a voice at all are the client's, and they were measured
on a retail one. *When* a server stops is not the client's and could never be
read out of it: it is this end's own event, an operator with a reason. So
nothing here runs on a schedule of its own and nothing here writes a sentence.
The delay and the words both come from whoever types the command, exactly the
way a chat line's words do, and the one rule this file contributes is that the
promise is kept -- the sockets stay up for as long as the players were told
they would, and not a second longer.

⚠️ ONE COUNTDOWN PER PROCESS, not one per port. A player is on several of
these ports at once (the login hop, the game connection, the school one) and
they all end when the process does, so a second countdown could only ever be a
second opinion about the same moment. Arming again replaces what was armed,
which is also how an operator moves the time: say the new one, arm it, and the
old timer is gone.

⚠️ NOTHING HERE IS MADE UP (inventions:skip). There is no default delay and no
default text -- a command that leaves either out is refused rather than filled
in, because a number this end picked would look exactly like a number it
recovered.
"""
# UNSENT 0x0001 -- MpsGameServerLogout, the server's own 「log out of the game
# server now」. It is the one message this file would otherwise send: a planned
# stop is exactly the occasion the original would have used it for. This build
# does not listen for it. CSequencerMpsGameServerLogout declares it and nothing
# in the client's image registers a handler behind that declaration, and the
# client says so itself -- pushed at a retail client standing on a map, its own
# log answers in three lines: it parses the body (which is empty), names the
# procedure the message belongs to, and then prints
# 受信ハンドラが設定されていません. Nothing was drawn, nothing changed, and not
# one byte came back -- in particular not the 0x0100 NotifyGameServerLogout the
# client sends of its own accord when a player quits to the title screen.
#
# ⚠️ That is a statement about this build, not about the message. The client
# carries the whole apparatus for it -- a parser, a procedure, a sequencer --
# so the original had something to do with it; what the missing registration
# says is that on the client as shipped there is no screen for it to change.
# Sending it anyway would be writing bytes that were measured doing nothing,
# which is worse than not sending them: the next person would read the send
# path as evidence that it works.
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class Countdown:
    """What the players were promised: the words, and the moment it happens."""

    line: str
    seconds: float
    #: time.monotonic(), so that it survives a wall clock being put right.
    deadline: float

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


#: Set when the countdown reaches zero (or an operator asks for zero). The
#: process's own main loop waits on it; see run_all.py.
_stopping = asyncio.Event()

_armed: "Countdown | None" = None
_timer: "asyncio.TimerHandle | None" = None


def armed() -> "Countdown | None":
    """The countdown now running, if there is one."""
    return _armed


def arm(seconds: float, line: str) -> Countdown:
    """Promise to stop in *seconds*, and hold this end to it.

    Replaces any countdown already armed: see the module docstring for why
    there can only be one. The caller announces -- this only keeps time.
    """
    global _armed, _timer
    cancel()
    loop = asyncio.get_running_loop()
    _armed = Countdown(line=line, seconds=seconds,
                       deadline=time.monotonic() + seconds)
    _timer = loop.call_later(seconds, stop_now)
    return _armed


def cancel() -> "Countdown | None":
    """Call off the countdown. Returns what was called off, or None."""
    global _armed, _timer
    was = _armed
    if _timer is not None:
        _timer.cancel()
    _armed = None
    _timer = None
    return was


def stop_now() -> None:
    """Stop serving. The timer's own destination, and the way to skip ahead."""
    global _armed, _timer
    if _timer is not None:
        _timer.cancel()
    _timer = None
    _armed = None
    _stopping.set()


def stopping() -> bool:
    """Whether the process is on its way down already."""
    return _stopping.is_set()


async def wait() -> None:
    """Block until something asks this process to stop."""
    await _stopping.wait()
