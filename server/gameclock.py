"""The school calendar's one clock: which day it is, for everything that asks.

The original ran its calendar on the real one. Every rule that says 「a day」
reads the same date: the 日常会話 daily reset the client's own scripts run
over `SYSTEM[0..2]` (`romance.date_cells`), the 親密さ credit per day
(`Romance.credit`), the once-a-day gate in front of each メインイベント
(`<name>_s102` compares the stamp it kept against today), クラブ's ten-day
wait after 退部 (`club.REJOIN_DAYS`), 仲良しグループ's thirty days after
引継／解散 (`groups`), and the 多目的室 booking window (`multipurpose`).
⛔️ One clock, not two: all of those come through `today()` below, so the
calendar cannot disagree with itself.

⚠️ Not everything with a date is on this clock. Registration codes, KONAMI ID
records, the registration site and the throttle stamp the *real* date: those
are administrative facts about accounts, not days in the school year, and they
stay on `datetime.date.today()`. The test is 「does the game's own rule count
this in 日?」 — if yes it belongs here.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

# ⚠️ INVENTED — how many real hours one school day lasts.
# The original had no such number: its day was the real day, and its rules were
# written for a school full of players who came back every real day for
# months. On a server with one player that pacing is the wall — the first
# メインイベント after 初登校 cannot fire until the *next real day*
# (`amm_s102`'s date gate), each rung wants ~72 親密さ at ~10–15 per granting
# 会話 with a per-day cap, so one candidate's ending is weeks of real days.
# This knob compresses the calendar: at 6, a school day is six real hours and
# 「明日」 comes four times a real day. 24 is the factory value and reproduces
# the original exactly (`today()` then IS the real date). The value is pacing,
# not a rule, which is why it is a knob and not a constant.
#
# ⚠️ Change it before an instance has lived a day, or accept one jump: the
# compressed date is computed from EPOCH, so turning the knob moves 「today」
# forward or back in one step. Forward is harmless (everything is 「a new
# day」); backward makes a few 「days since」 counts negative for a while.
# ⚠️ The client packs the year into a u16 with 2000 as its base
# (`romance.TALK_DAY_YEAR_BASE`), so the compressed calendar must stay under
# year 2127: at DAY_HOURS=1 that is about four real years from EPOCH.
DAY_HOURS = float(os.environ.get("TMO_DAY_HOURS", "24"))

#: Where the compressed calendar starts counting. A midnight, so that at
#: DAY_HOURS == 24 the compressed date and the real date are the same day.
EPOCH = datetime(2026, 1, 1)


def today(now: "datetime | None" = None) -> date:
    """The school calendar's date. ⭐ The only way to ask what day it is."""
    now = now or datetime.now()
    hours = DAY_HOURS
    if hours == 24:
        return now.date()
    elapsed = (now - EPOCH).total_seconds() / 3600.0
    return EPOCH.date() + timedelta(days=int(elapsed // hours))


def school_now(now: "datetime | None" = None) -> datetime:
    """The school calendar's date *and* time of day, on the same clock as today().

    For the few rules that fall on an hour of a school day rather than on the day
    — 試験期間 opens on a Friday at 14:00 (`exam.scheduled`). At DAY_HOURS == 24
    it is the wall clock itself; compressed, the school day's 24 hours are spread
    over DAY_HOURS real ones, so its date always agrees with today().

    ⚠️ The 時間割 is NOT on this clock: lessons are fifteen real minutes
    (`p06_01`) whatever the calendar does, and curriculum reads the wall clock.
    """
    now = now or datetime.now()
    hours = DAY_HOURS
    if hours == 24:
        return now
    elapsed = (now - EPOCH).total_seconds() / 3600.0
    days = int(elapsed // hours)
    into = (elapsed - days * hours) / hours * 24.0
    return datetime.combine(EPOCH.date() + timedelta(days=days),
                            datetime.min.time()) + timedelta(hours=into)


def describe() -> str:
    """One line for the startup log."""
    if DAY_HOURS == 24:
        return "school calendar = the real calendar (TMO_DAY_HOURS=24)"
    return (f"school calendar compressed: one day = {DAY_HOURS:g} real hours, "
            f"today is {today().isoformat()} (TMO_DAY_HOURS)")
