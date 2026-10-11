"""The 校内新聞's 試験結果 page: six ranking files, handed out through the updater.

The client's school paper has four tabs, and three of them are pictures it
carries. The fourth, 試験結果, is a table -- 個人 and クラス, each with a tab per
試験レベル (初級/中級/上級, and two more drawn greyed out) -- and its rows come
from six files the shipped game does not have:

    data/news/personal0.arc  personal1.arc  personal2.arc     (個人, by level)
    data/news/class0.arc     class1.arc     class2.arc        (クラス, by level)

The client asks for them when it builds the paper, under the names
`data/news/personal0.bin` ... with the extension swapped for `.arc` (the same
swap turns `data/news/paper.news` into the `paper.arc` that does ship), and it
only ever reads them: a file that is missing leaves that table empty, which is
all a player has ever seen there. So they were the operator's to publish after
each 試験期間, the way the updater publishes anything -- and this server has the
papers (examrank.py). This module writes them; updater_server.py hands them out
beside whatever runtime/update/ holds, and a player's paper shows the latest
released period from their next start.

File layout, as the client reads it (little-endian, packed):

    header   16 bytes; byte 2 is the row count, read as a signed char, so at
             most 127 rows. Nothing else in it is read.
    個人 row 34 bytes: 姓 char[12] · 名 char[12] (Shift_JIS, NUL-padded) ·
             8 scores, one byte each, in curriculum.SUBJECTS order (国 数 理
             社 外 体 芸 家) · 合 as two bytes, low then high.
    クラス row 16 bytes: 組 (0 = Ａ組) · one byte not read · the 8 scores · 合
             as two bytes · 4 bytes not read.

The 順位 column is not in the file: the client numbers the rows as it draws
them, so the order of the rows is the ranking.

⚠️ THE CLIENT READS EVERY SCORE AS A SIGNED BYTE. Each one is loaded with a
sign extension and then compared with 0xFF to choose 「　－　」 over a number;
after the extension 0xFF is -1, so that test never succeeds -- the dash is dead
code in this build -- and 合, assembled as ``high << 8 | low`` from two
sign-extended bytes, comes out negative whenever its low byte is 0x80 or more.
A score of 0..100 survives; a total of 0..800 does not, about half the time.
That is fixed in the client, the way the operated game fixed client code --
ranking_fix.py, handed out through the updater -- so the files here are written
as the format means them: 合 is the sum, an untaken subject is 0xFF.

Each file is an ARC0 container holding one entry, stored plain: the header
says how an archive's payloads are stored, and most of the shipped archives
(every map, every model) say "plain", so no key is needed to write one. The entry's first field, which the shipped
archives fill with a value per content, is not checked by the client and is
left at zero.
"""
from __future__ import annotations

import struct
from datetime import datetime

import curriculum
import examrank

#: Where the six files go, as paths in the game folder (updater_server.py).
NEWS_DIR = "data/news"
LEVELS = curriculum.COURSES
HEADER_SIZE = 16
PERSONAL_ROW = 34
CLASS_ROW = 16
NAME_FIELD = 12
MAX_ROWS = 127          # the header's count is a signed char

# ⚠️ INVENTED — how many rows each 個人 table prints.
# ⭐ What the original most likely did: a short list -- the manual calls it
# 「個人の上位ランキング」. Longer than one page, though: the page shows 19 rows and
# carries a scroll bar, which a list that always fitted would not need. 50 is a
# few pages; the file cannot hold more than 127.
# ⭐ What would overturn it: a surviving 試験結果 page, or an operator notice
# saying how many were listed.
PERSONAL_ROWS = 50

#: 合: the eight scores added up (two bytes, which only a total needs).
#: 0xFF: the client's own marker for a subject not taken, drawn as 「　－　」.
ABSENT = 0xFF


def _name_field(text: str) -> bytes:
    """Shift_JIS, cut to fit with its NUL, padded to NAME_FIELD."""
    raw = text.encode("cp932", "replace")[: NAME_FIELD - 1]
    while raw:
        try:
            raw.decode("cp932")
            break
        except UnicodeDecodeError:  # a double-byte character cut in half
            raw = raw[:-1]
    return raw.ljust(NAME_FIELD, b"\x00")


def _byte(value: "int | None") -> int:
    return (ABSENT if value is None else max(0, min(100, int(round(value))))) & 0xFF


def _total(scores: list) -> int:
    return int(round(sum(s for s in scores if s is not None)))


def _header(count: int) -> bytes:
    head = bytearray(HEADER_SIZE)
    head[2] = count
    return bytes(head)


def personal_file(rows: list[dict]) -> bytes:
    """Rows of ``{"family", "first", "scores": [8 x int|None]}``, best first."""
    rows = rows[:MAX_ROWS]
    out = bytearray(_header(len(rows)))
    for row in rows:
        scores = list(row["scores"])
        out += _name_field(row["family"]) + _name_field(row["first"])
        out += bytes(_byte(s) for s in scores)
        out += struct.pack("<H", _total(scores) & 0xFFFF)
    return bytes(out)


def class_file(rows: list[dict]) -> bytes:
    """Rows of ``{"class", "scores": [8 x float|None]}``, best first."""
    rows = rows[:MAX_ROWS]
    out = bytearray(_header(len(rows)))
    for row in rows:
        scores = list(row["scores"])
        out += bytes([row["class"] & 0xFF, 0]) + bytes(_byte(s) for s in scores)
        out += struct.pack("<H", _total(scores) & 0xFFFF) + bytes(4)
    return bytes(out)


def archive(name: str, payload: bytes, when: datetime) -> bytes:
    """An ARC0 container with ``payload`` stored plain as its one entry ``name``.

    Laid out the way the shipped one-file archives are: header, a table of
    32-byte entries at 0x80, the names at 0x100, the data at 0x180 padded to
    2 KiB. The entry's time is a Windows FILETIME, high half then low.
    """
    raw = name.encode("ascii") + b"\x00"
    filetime = int((when.timestamp() + 11644473600) * 10_000_000)
    data_off, names_off, table_off = 0x180, 0x100, 0x80
    region = payload + bytes(-len(payload) % 0x800)
    head = bytearray(table_off)
    head[0:4] = b"ARC0"
    struct.pack_into("<II", head, 4, table_off, 32)
    # 0x14 holds 0x100 in every shipped archive and is not read.
    struct.pack_into("<IIIIII", head, 0x0C, names_off, 0, 0x100, len(raw), data_off, len(region))
    # ⭐ The two the loader does read (0x9BC87D mounts, 0x9BC410 opens): 0x28 is
    # the entry count -- an entry at or past it does not open -- and 0x30 how
    # the payloads are stored, 0 plain as in the map and model archives, 2
    # enciphered as in the shipped paper.arc.
    struct.pack_into("<I", head, 0x28, 1)
    struct.pack_into("<I", head, 0x30, 0)
    entry = struct.pack("<8I", 0, filetime >> 32, names_off, len(raw), data_off,
                        len(payload), len(payload), 0)
    table = entry.ljust(names_off - table_off, b"\x00")
    names = raw.ljust(data_off - names_off, b"\x00")
    return bytes(head) + table + names + region


# -- from the book ----------------------------------------------------------

def _personal_rows(papers: list[dict], level: int) -> list[dict]:
    """Everyone who sat at least one paper at ``level``, best total first.

    Ties go the way the β notice orders a ranking: the higher total first,
    then more 出席 in the subjects sat, then the better 正解率.
    """
    by_chara: dict[int, dict[int, dict]] = {}
    for paper in papers:
        if examrank.course_of_paper(paper) == level:
            by_chara.setdefault(int(paper["chara"]), {})[int(paper["subject"])] = paper
    rows = []
    for sat in by_chara.values():
        latest = max(sat.values(), key=lambda p: p["sat"])
        family, first = examrank.name_parts(latest)
        scores = [int(sat[s]["score"]) if s in sat else None
                  for s in range(len(curriculum.SUBJECTS))]
        total = sum(s for s in scores if s is not None)
        attendance = sum(int(p.get("attendance", 0)) for p in sat.values())
        rate = sum(float(p.get("rate", 0)) for p in sat.values()) / len(sat)
        rows.append(((-total, -attendance, -rate),
                     {"family": family, "first": first, "scores": scores}))
    rows.sort(key=lambda pair: pair[0])
    return [row for _, row in rows[: max(0, min(PERSONAL_ROWS, MAX_ROWS))]]


def _class_rows(book: "examrank.ResultBook", key: str, level: int) -> list[dict]:
    """The 組 that qualify at ``level``, by examrank's クラス平均点, best first."""
    out = []
    for _rank, row in book.class_ranking(key, level):
        out.append({"class": row["class"], "scores": row["subjects"]})
    return out[:MAX_ROWS]


def files(book: "examrank.ResultBook | None",
          now: "datetime | None" = None) -> list[tuple[str, bytes, datetime]]:
    """``[(game-folder path, archive bytes, its time)]`` for the newest released
    period, or nothing while no period has been released."""
    if book is None:
        return []
    shown = book.shown(now)
    if not shown:
        return []
    key = shown[0]
    papers = book.periods.get(key, {}).get("papers", [])
    when = book.release_time(key)
    out = []
    for level in range(LEVELS):
        for stem, payload in (
            (f"personal{level}", personal_file(_personal_rows(papers, level))),
            (f"class{level}", class_file(_class_rows(book, key, level))),
        ):
            out.append((f"{NEWS_DIR}/{stem}.arc",
                        archive(f"{stem}.bin", payload, when), when))
    return out
