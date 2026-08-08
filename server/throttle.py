"""Answering slowly, which is nearly all the defence this server has.

There was none of this until now, and what it defends against is not what the
phrase "rate limit" usually names. Nothing here is worth guessing at:
konami_id.py says what a personal key is on this server -- a label with a lock
drawn on it, weak because the client's login screen imposes the shape -- and the
worst that comes of getting past one is that somebody else's character gets
played. What this is for is the two ways a server running in somebody's room
falls over by accident: a form that will make an account for anything that asks,
and a login endpoint that answers as fast as a script can ask.

  Slower, not refused
  -------------------
  ⭐ Every limit here answers late rather than refusing, and the reason is that
  an address is not a person. One address can be a building: a mobile network
  hands the same one to a city, and a household hands it to everybody in the
  house. A cap turns that into "you cannot get in" for people who did nothing.
  A delay turns it into "that took a moment", which is a cost a person absorbs
  without noticing much and a script cannot absorb at all -- eight seconds a
  request is nothing to somebody filling in a form once in their life, and the
  end of any throughput worth having.

  So the numbers below are not ceilings. They are where answers start arriving
  slowly, and nothing except the fuse ever stops.

  What a slowed answer says
  -------------------------
  Nothing. It is the answer it would have been, late. There is no sentence about
  limits, because that sentence is only useful to somebody trying to find where
  the limit is; a player who trips one of these should come away thinking the
  server is on a slow day.

  That is what they do come away thinking, which was checked rather than
  assumed: through a held login the client shows the same modal it shows
  through an ordinary one -- 「接続処理を行っています」 -- with no seconds, no
  progress, and nothing that moves. Two frames three seconds apart differ by
  nothing inside the dialog. A slow answer looks like a slow network, which is
  the point; a slow answer that ran to thirty seconds would look like a hung
  client in front of a player with no way to tell the difference, and that is
  the other reason DELAYS stops at eight.

  ⚠️ The fuse is the exception, and says so in plain words. Somebody who meets
  it cannot get a code today whatever they do, and staying silent about that
  leaves the one person here who is certainly innocent looking at a page that
  appears broken.

  Not a boundary
  --------------
  ⚠️ Worth being exact about, because the file's name suggests otherwise.
  Another address costs nothing, so anybody who wants past any of this gets
  past it. It is aimed at accidents and at the lowest grade of nuisance -- a
  stuck client in a retry loop, somebody's first script, a scan that found the
  port -- and it happens to be the only thing here that would notice any of
  them. Read it as housekeeping, and do not let it be the reason this server is
  put somewhere it should not be. The README says where that is.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import time

# How long a slowed answer waits, first one to last, in seconds.
#
# ⚠️ The ceiling is measured, not chosen. The client waits exactly 30.0 seconds
# for a reply to login.php and then drops the connection -- RST, not a close --
# and shows 「データの受信に失敗しました。errorcode ff0c:028」. That is per
# request rather than per connection: the whole KONAMI-ID sequence runs down one
# socket and each of its four requests gets its own 30 seconds, which was
# checked by holding one for 25 and watching the login go through. Eight is what
# is left when the measurement is given room to be wrong about the machine it
# was taken on.
DELAYS = (2.0, 4.0, 8.0)

# What the fuse says, and the only thing in this file that is said out loud. It
# names no limit and no address: what the reader needs is that today is over and
# that a person can still get them in.
FUSE_MESSAGE = (
    "This server has given out as many registration codes as it will today. "
    "Try again tomorrow, or ask whoever runs it to issue one by hand."
)


def delay_for(step: int) -> float:
    """How long the ``step``-th over-limit answer waits; step counts from 1.

    Zero and below is under the limit, which is most of them.
    """
    if step < 1:
        return 0.0
    return DELAYS[min(step, len(DELAYS)) - 1]


class Throttle:
    """Both places worth slowing down, and the one place worth stopping.

    Held once and shared: run_all.py builds a single instance and hands it to
    the registration site and to every AuthHttpServer, for the same reason the
    token desk is shared. A failure streak belongs to an account, not to the
    port the client happened to pick out of the six that answer.

    Everything except the fuse lives in memory and goes on restart, which is the
    right lifetime for it -- a restart is not a thing an outsider can arrange,
    and what would be bought by keeping it is not worth a file to keep in step.
    """

    #: Codes one address can be given in a day before answers slow down.
    SIGNUPS_A_DAY = 3
    #: Forms one address can send in an hour before answers slow down. Looser
    #: than the day's codes on purpose: a real person mistypes, and finds out
    #: the id they wanted is taken.
    ATTEMPTS_AN_HOUR = 10
    #: Codes given out everywhere in a day. ⚠️ This one refuses.
    FUSE = 50
    #: Failed logins in a row to one account before answers slow down.
    FREE_FAILURES = 5
    #: How long a failure streak lives without being added to. Somebody who got
    #: it wrong five times last week is not in the middle of anything.
    STREAK_TTL = 3600.0
    #: How many addresses, and how many accounts, to remember at once.
    REMEMBERED = 4096

    DAY = 86400.0
    HOUR = 3600.0

    def __init__(
        self,
        counts_path: Path | None = None,
        *,
        clock=time.monotonic,
        today=None,
    ) -> None:
        # Both injectable so that a day and an hour can be crossed in a test
        # without one taking an hour. The clock is monotonic because these are
        # durations rather than dates -- the fuse is the only thing here that
        # cares what day it is, and it asks separately.
        self._clock = clock
        self._today = today or (lambda: date.today().isoformat())
        self.counts_path = counts_path
        self._attempts: dict[str, list[float]] = {}
        self._signups: dict[str, list[float]] = {}
        self._failures: dict[str, tuple[int, float]] = {}

    # -- who is asking ------------------------------------------------------

    @staticmethod
    def address(peer) -> str:
        """The host out of whatever ``get_extra_info("peername")`` returned."""
        host = str(peer[0]) if isinstance(peer, tuple) and peer else str(peer or "")
        # An IPv4 address arriving down an IPv6 socket. The same machine, just
        # wearing the other family's hat, and it must not get a second budget.
        if host.startswith("::ffff:"):
            host = host[len("::ffff:") :]
        return host

    @classmethod
    def is_local(cls, peer) -> bool:
        """Is this the machine the server is on?

        Exempt, and not as a convenience. Loopback is where this server is meant
        to be used from and where every one of its own tests runs, so counting
        it would mean the smoke suite slows itself down and the person running
        the thing meets a limit aimed at somebody else.
        """
        host = cls.address(peer)
        return host.startswith("127.") or host in ("::1", "localhost")

    # -- the registration form ---------------------------------------------

    def registration_attempt(self, peer) -> float:
        """Note one form arriving from this address; how long to hold the reply.

        Both windows are read before this attempt is added to either, so what
        decides is the count the address had already run up. Whichever window is
        further over wins; they are not added together, because the point is one
        slow answer rather than an arithmetic that reaches a minute.
        """
        if self.is_local(peer):
            return 0.0
        who = self.address(peer)
        now = self._clock()
        tries = len(self._recent(self._attempts, who, self.HOUR, now))
        given = len(self._recent(self._signups, who, self.DAY, now))
        self._attempts.setdefault(who, []).append(now)
        self._forget_oldest(self._attempts)
        return max(
            delay_for(tries - self.ATTEMPTS_AN_HOUR + 1),
            delay_for(given - self.SIGNUPS_A_DAY + 1),
        )

    def registration_succeeded(self, peer) -> None:
        """Note one code actually given out. Called next to the day's count.

        Only fresh codes: showing somebody the code they already have hands out
        nothing, costs nothing, and is the answer this page gives to a reload.
        """
        if self.is_local(peer):
            return
        now = self._clock()
        self._signups.setdefault(self.address(peer), []).append(now)
        self._forget_oldest(self._signups)

    def signups_today(self) -> int:
        """Today's number out of runtime/accounts/registrations.json."""
        if self.counts_path is None:
            return 0
        try:
            counts = json.loads(self.counts_path.read_text(encoding="utf-8"))
            return int(counts.get(self._today(), 0))
        except (OSError, ValueError, TypeError, AttributeError):
            # An unreadable count is not a reason to close the form: this is a
            # fuse against a runaway, and a missing file is the ordinary state
            # of a server nobody has registered on yet.
            return 0

    def fuse_blown(self) -> bool:
        """Has self-serve used up the day, everywhere?

        Read off the file registration_site already writes one number a day
        into. Nothing else records this and nothing else needs to: the number
        only rises when a code is really given out, and nothing can push it past
        FUSE, so a day sitting at FUSE in that file *is* the record that the
        fuse blew that day. A second file saying so would be a second file to
        keep in step with the first.

        ⚠️ The one limit here that refuses, and it cannot do otherwise. What it
        guards is a table filling up with accounts, and a slow answer still ends
        in one. It does not touch /register: a code an operator issued by hand
        was not made by this, and the person holding it is not who this is
        about.
        """
        return self.signups_today() >= self.FUSE

    # -- login.php ----------------------------------------------------------

    def login_failed(self, konami_id: str) -> float:
        """One more failure in a row for this account; how long to wait.

        ⚠️ Only for an account that exists. An unknown KONAMI ID is the ordinary
        state of this server -- every code that predates the 登録 form signs in
        without one, and auth_http_server._login prints that as a fact rather
        than an error -- so counting those would put a growing delay on the path
        most of this server's history uses, for doing nothing wrong.

        The delay lands on the answer to the attempt that failed, which is why
        nothing can lock anybody out: the right personal key is never held back,
        however long the streak in front of it was.
        """
        now = self._clock()
        streak, last = self._failures.get(konami_id, (0, now))
        if now - last > self.STREAK_TTL:
            streak = 0
        streak += 1
        self._failures[konami_id] = (streak, now)
        self._forget_oldest_failure()
        return delay_for(streak - self.FREE_FAILURES)

    def login_ok(self, konami_id: str) -> None:
        """The streak is over. Nothing after this is held back."""
        self._failures.pop(konami_id, None)

    # -- keeping the tables small ------------------------------------------

    def _recent(
        self, table: dict[str, list[float]], who: str, window: float, now: float
    ) -> list[float]:
        """This address's timestamps inside the window, pruning as it reads."""
        kept = [t for t in table.get(who, ()) if now - t < window]
        if kept:
            table[who] = kept
        else:
            table.pop(who, None)
        return kept

    def _forget_oldest(self, table: dict[str, list[float]]) -> None:
        """Bound the table by dropping whoever has been quiet longest.

        Pruning happens when an address is touched, so an address that never
        comes back sits there until this evicts it. Forgetting one is not a
        failure -- it starts again from zero, which is where somebody who has
        not been seen in the window would have been anyway.
        """
        excess = len(table) - self.REMEMBERED
        if excess <= 0:
            return
        for who in sorted(table, key=lambda k: table[k][-1])[:excess]:
            del table[who]

    def _forget_oldest_failure(self) -> None:
        excess = len(self._failures) - self.REMEMBERED
        if excess <= 0:
            return
        for who in sorted(self._failures, key=lambda k: self._failures[k][1])[:excess]:
            del self._failures[who]
