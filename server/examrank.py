"""試験ランキング: who came top in a 試験期間, by subject and by 組.

Every paper marked in a period is filed here as well as on the sitter's own
通知表, and once the period is over the book ranks them. Two rankings, in the
words of the β test's notice of 2006-02-15 -- this client's own month -- which
set the rules out before the first exam was held:

    ◆ランキングの順位の付き方
    1) 得点が高い方の順位が上になります
    2) 得点が同じ場合は、対象科目授業の出席数が多い方が上の順位になります
    3) 上記2項の内容でも順位を決定できない場合、対象科目授業の正解率等により
       順位を決定します
    ◆個人ランキングにエントリーするための条件
    ・１科目以上受験する（全科目受験していなくても有効）
    ◆クラスランキングにエントリーするための条件
    ・クラス内に全科目受験した生徒が５名以上存在している

and the manual of the same build (`p06_03`) says what was published:
「個人の上位ランキングと、クラス平均点のランキング」.

⭐ THE PERSONAL RANKING IS PER SUBJECT. Rule 2 breaks a tie on 「対象科目」's
attendance, which only means something when the ranking has one subject; and
the entry condition's 「全科目受験していなくても有効」 is then the plain
reassurance it reads as -- a player who sat one subject is on that subject's
table. So each subject has a table, ordered by the three rules: score, then
that subject's 出席回数, then its 通算正解率 (the lesson figure `p06_02`
defines, the one the 授業 panel prints). 「等」 promises a further tie-break
and does not name it; two papers equal on all three share the rank.

⭐ THE CLASS RANKING needs five full sitters, so it is the full sitters it
averages: each one's eight scores summed, then the mean across them. What the
average is taken over is the part the notice does not say -- see
CLASS_AVERAGE.

⭐ The 組 is the one written down on the day. The operated game's exam pages
said 「回答用紙には、試験当日に所属しているクラスを記入してください」, so a
paper is filed under the 組 its sitter was in when they sat it.

⭐ THE 経歴. `career.bin` key 2 is 「試験ランキング１位」, and the operated
game's 2007 exam pages say 「試験成績（個人）が上位の生徒の経歴に、その旨を
記載いたします」. So 1位 on any subject's personal table writes key 2 into the
sitter's 経歴 -- at the next 登校 after the period is over, since a character
not playing has nobody to tell. Key 2 is one 実績: two firsts are one entry.

⚠️ WHERE IT IS READ is the invented part (round 574, user's call). The
original printed both tables in the 校内新聞 (`p05_07`
「試験のランキングなどが掲載されます」) -- but every page of that paper is the
client's own `Data/news`, and the four messages that open and close it carry
not one byte, so there is nothing this end can put on it. The original also
published results on its website; this server has a website, the registration
page, so the tables are a read-only page on it (registration_site.py,
/ranking). No client change and no new message.

⚠️ A period run from the console (``exam.Period.MANUAL``, `/exam on`) is filed
too, under its own key, because it is over at once and that makes it the way
to see this page work on a development server. No player meets it: the console
is off on a deployed one.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import curriculum
import exam
import gameclock

FILE = "exam_results.json"

#: `career.bin` key 2, 「試験ランキング１位」.
CAREER_FIRST = 2

#: The β notice of 2006-02-15: a class enters the class ranking with
#: 「全科目受験した生徒が５名以上」.
CLASS_MIN_SITTERS = 5

# ⚠️ INVENTED — how many places each subject's personal ranking shows.
# ⭐ What the original most likely did: a short list. `p06_03` calls it 「個人の
# 上位ランキング」 and the 2007 pages 「成績優秀者」 -- the top of each table, not
# every sitter -- and gives no length. Ten is a page's worth that still says
# something on a small server. Every sitter is ranked whatever this says; it
# only decides how many rows are printed.
# ⭐ What would overturn it: a surviving 校内新聞 page of a 試験結果.
TOP = 10

# ⚠️ INVENTED — what the クラス平均点 is the mean of: "full" (each full sitter's
# eight scores summed, averaged over the full sitters) or "papers" (every paper
# anyone in the 組 sat, full sitter or not, averaged per paper).
# ⭐ What the original most likely did: "full". The entry condition counts full
# sitters and nobody else, which is the condition an average over full sitters
# needs -- it is what keeps one strong paper from standing for a whole 組 -- and
# would be an odd gate on an average that also took everybody else in.
# ⭐ What would overturn it: a published class average that is not a mean of
# eight-subject totals.
# Knob: CLASS_AVERAGE (full / papers).
CLASS_AVERAGE = "full"

# ⚠️ INVENTED — hours after a period closes before its rankings are shown (and
# its 1位 written into the 経歴).
# ⭐ What the original most likely did: wait for the next regular maintenance.
# The β test closed 02-20 12:00 and showed 02-21 15:00; the 2007 pages close
# on a Monday at 11:59 and publish after the maintenance of the Wednesday
# (01-17) or Thursday (03-22). That is an operator's working week, not a rule
# of the game:
# the 通知表 has the scores the moment the period closes (`p06_03`), and this
# server has no maintenance to wait for. So 0 -- the rankings come with the
# 通知表. 27 is the β's own gap, for anyone who wants the wait back.
RELEASE_HOURS = 0


def _name(family: bytes, first: bytes) -> str:
    """氏名 as text, from the two NUL-padded Shift_JIS fields."""
    parts = [raw.split(b"\x00", 1)[0].decode("cp932", "replace")
             for raw in (family, first)]
    return " ".join(part for part in parts if part)


def class_name(in_class: int) -> str:
    """0 -> 「Ａ組」, the full-width letter the client prints."""
    if 0 <= in_class < 26:
        return chr(0xFF21 + in_class) + "組"
    return f"{in_class}組"


def _order(paper: dict) -> tuple:
    return (-int(paper["score"]), -int(paper["attendance"]), -float(paper["rate"]))


def _ranked(rows: list, key) -> list:
    """``[(rank, row)]``, best first; rows equal under ``key`` share a rank."""
    rows = sorted(rows, key=key)
    out, last, rank = [], None, 0
    for index, row in enumerate(rows):
        mark = key(row)
        if mark != last:
            rank, last = index + 1, mark
        out.append((rank, row))
    return out


class ResultBook:
    """Every paper marked, by period, in one file beside the other shared books.

    One file for the server rather than one per account, for the reason
    friends.FriendBook gives: a ranking is across everybody. Each entry is a
    copy of what the ranking needs taken on the day -- the score, the subject's
    出席回数 and 正解率, the 組 and the 氏名 -- so the tables do not move when a
    sitter changes 組, attends another lesson or 再入学s afterwards.
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.path = directory / FILE
        # period key -> {"name": str, "papers": [...]}
        self.periods: dict[str, dict] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[examrank] ignoring unreadable {self.path}: {exc}")
            return
        for key, body in (raw.get("periods") or {}).items() if isinstance(raw, dict) else ():
            if not isinstance(body, dict):
                continue
            papers = [p for p in body.get("papers") or [] if isinstance(p, dict)
                      and {"chara", "subject", "score"} <= p.keys()]
            self.periods[str(key)] = {"name": str(body.get("name", "")),
                                      "papers": papers}
        if self.periods:
            print(f"[examrank] {self.summary()}")

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"periods": self.periods}, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # -- filing -----------------------------------------------------------

    def file(self, period: str, chara_id: int, subject: int, score: int,
             right: int, attendance: int, rate: float, in_class: int,
             family: bytes, first: bytes, when: "datetime | None" = None) -> None:
        """One marked paper. A second paper in the same subject replaces it.

        In a calendar period that cannot happen (one sitting per subject); in a
        console period, which starts afresh with every `/exam on`, it is the
        latest sitting that stands.
        """
        if period == exam.Period.MANUAL:
            name = "手動（コンソール）"
        else:
            found = exam.scheduled(when)
            name = found[1] if found and found[0] == period else ""
        book = self.periods.setdefault(period, {"name": name, "papers": []})
        if name and not book.get("name"):
            book["name"] = name
        book["papers"] = [p for p in book["papers"]
                          if not (int(p["chara"]) == chara_id
                                  and int(p["subject"]) == subject)]
        book["papers"].append({
            "chara": chara_id, "subject": subject,
            "score": max(0, min(100, score)), "right": right,
            "attendance": attendance, "rate": round(rate, 6),
            "class": in_class, "name": _name(family, first),
            "sat": (when or datetime.now()).isoformat(timespec="seconds"),
        })
        self._save()

    # -- reading ----------------------------------------------------------

    def released(self, key: str, now: "datetime | None" = None) -> bool:
        """May this period's rankings be shown yet?"""
        if not exam.period_over(key, now):
            return False
        if key == exam.Period.MANUAL or not RELEASE_HOURS:
            return True
        try:
            friday = datetime.fromisoformat(key)
        except ValueError:
            return True
        return (gameclock.school_now(now)
                >= friday + exam.CLOSES + timedelta(hours=RELEASE_HOURS))

    def shown(self, now: "datetime | None" = None) -> list[str]:
        """Released period keys, newest first, the console's last."""
        keys = [k for k in self.periods if self.released(k, now)]
        calendar = sorted((k for k in keys if k != exam.Period.MANUAL), reverse=True)
        return calendar + [k for k in keys if k == exam.Period.MANUAL]

    def name(self, key: str) -> str:
        return self.periods.get(key, {}).get("name") or key

    def subject_ranking(self, key: str, subject: int) -> list[tuple[int, dict]]:
        papers = [p for p in self.periods.get(key, {}).get("papers", [])
                  if int(p["subject"]) == subject]
        return _ranked(papers, _order)

    def class_ranking(self, key: str) -> list[tuple[int, dict]]:
        """``[(rank, {"class", "average", "sitters"})]``, classes that qualify."""
        papers = self.periods.get(key, {}).get("papers", [])
        by_chara: dict[int, dict[int, dict]] = {}
        for paper in papers:
            by_chara.setdefault(int(paper["chara"]), {})[int(paper["subject"])] = paper
        everyone = len(curriculum.SUBJECTS)
        rows = []
        for in_class in sorted({int(p["class"]) for p in papers}):
            # A sitter's 組 is the one on their latest paper of the period.
            members = {chara: sat for chara, sat in by_chara.items()
                       if int(max(sat.values(), key=lambda p: p["sat"])["class"]) == in_class}
            full = {chara: sat for chara, sat in members.items() if len(sat) >= everyone}
            if len(full) < CLASS_MIN_SITTERS:
                continue
            if CLASS_AVERAGE == "papers":
                marks = [int(p["score"]) for sat in members.values() for p in sat.values()]
                average = sum(marks) / len(marks)
            else:
                if CLASS_AVERAGE != "full":
                    print(f"[examrank] CLASS_AVERAGE={CLASS_AVERAGE!r} is not one of "
                          f"full/papers; using full")
                totals = [sum(int(p["score"]) for p in sat.values()) for sat in full.values()]
                average = sum(totals) / len(totals)
            rows.append({"class": in_class, "average": average, "sitters": len(full)})
        return _ranked(rows, lambda row: -row["average"])

    def firsts(self, chara_id: int, now: "datetime | None" = None) -> list[tuple[str, int]]:
        """``[(period, subject)]`` where this character is 1位, shown periods only."""
        out = []
        for key in self.shown(now):
            for subject in range(len(curriculum.SUBJECTS)):
                for rank, paper in self.subject_ranking(key, subject):
                    if rank > 1:
                        break
                    if int(paper["chara"]) == chara_id:
                        out.append((key, subject))
        return out

    def summary(self) -> str:
        return ", ".join(f"{self.name(k)} {len(b['papers'])} papers"
                         for k, b in sorted(self.periods.items()))

