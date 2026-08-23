"""役職: the クラス委員 post, the 部活 post, and how their two tables are keyed.

`title`, `classPost` and `clubPost` are three u16 that travel side by side in
both character records -- the 238-byte 0x0319 list entry and the 139-byte 0x6501
info block -- and both messages have carried a hard ``0, 0, 0`` there since the
first round. This module is what makes the last two of them values.

⭐ `title` is not here. It is the 称号, it already has a home in career.py
(`designation.bin` has exactly one row, the empty one), and a character has one
称号 rather than one per message -- so both records now read it out of the 経歴
instead of packing another constant. That changes no byte today and is not
meant to: it is the wiring, not a new value.

⭐⭐ WHERE THE SCREEN READS THEM, as far as the client's own text tables go:

  `msg_text.bin` 220  「所属部：%1%  役職：%2%」    ← the club line, WITH a post
  `msg_text.bin` 859  「所属部：%1%」               ← the same line, WITHOUT one
  `msg_text.bin` 221  「所属グループ：%1%  役職：%2%」
  `msg_text.bin` 860  「所属グループ：%1%」
  `msg_text.bin` 222  「称号：%1%」

Those sit in one run with 218/219 (「第%1%期生 %2%組 氏名：%3%」) and 223
(「キャッチコピー：%1%」), and together they are the five-line name card the
client pops beside the PC 交流メニュー when one player right-clicks another --
measured, by putting a different key in each field and reading both names back
off one screenshot. ⭐ Each of the two 役職 lines has a version WITHOUT that
half (859, 860), and the client picks between them by whether the key it was
given is in the table: so 「the screen is missing half a line」 is the client's
own choice, not a field this end failed to send.

⚠️⚠️ `classPost` DRAWS ON THE 所属グループ LINE, not on a line of its own. The
other half of that line is the group's name, which makes its 役職 look like a
role *within* the group -- リーダー / メンバー, for which there are already two
fields on the wire (leaderAuthority, leaderQualification). It is not. Measured
twice, one variable at a time: a character in group R151 with classPost 1 drew
「所属グループ：R151　役職：クラス委員」, and ⭐ a character in NO GROUP AT ALL
with classPost 6 drew 「所属グループ：無所属　役職：ＱＬ委員」. That second row
is the judgement: the 役職 there has nothing to do with the group.

⚠️ It is drawn nowhere else. The ステータス page has 所属部 and 称号 and no
役職 (`win_text.bin` 18-31 is that window's whole label block), and the only
役職 label in `win_text.bin` is 433, inside a window this server cannot open:
430-455 is 立候補者情報 / 立候補者一覧 / クラス委員に推薦 / 演説日時, the
クラス委員長選挙 screens. `menu_item.bin` 405 and 406 are that menu, and
`sub_menu.bin` 3/4/5 are 委員長選挙 立候補受付／選挙活動中／投票. So the field
is one end of a whole subsystem, and this module is deliberately only its end.

⛔️ The same three fields ride in the 238-byte 0x0319 entry and NOTHING reads
them there: with classPost and clubPost both set, neither the character-select
card nor its 「情報を見る」 page draws a 役職 or a 称号. ⭐ The same message's
`inClub` does change on that screen (無所属 → 陸上部), so the entry is being
parsed -- those three just have no place to land on it.

⭐⭐⭐ THE WIRE KEY FOR clubPost IS THE postId, AND THE CLIENT PAIRS IT WITH ITS
OWN `inClub`. `club_post.bin` is keyed by a PAIR -- u16 clubId then u16 postId,
little-endian, straight out of the file -- and only one u16 crosses the wire, so
something had to supply the other half. Three readings fit the file (postId /
a flat row index / clubId packed into the high byte) and they draw different
rows, so one screen settled it: with `inClub` 1 and this field 5 the card drew
「所属部：野球部　役職：マネージャー」, which is row 1:5. A flat index would have
drawn 1:4 (予備軍) and a packed key would have drawn nothing.

⚠️⚠️ SO 0 IS NOT 「no post」 FOR SOMEBODY IN A CLUB -- it is that club's row 0,
and for 野球部 that is 「１軍レギュラー」. This server sent a hard 0 in every
round up to this one, so every character who had joined a club was being shown
to other players as a first-string regular. Measured, one variable at a time:

    inClub  clubPost  the card's club line
    0       0         所属部：無所属                  (no 役職)
    0       0xFFFF    所属部：無所属                  (no 役職)
    1       0         所属部：野球部　役職：１軍レギュラー
    1       5         所属部：野球部　役職：マネージャー
    2       515       所属部：バレー部                (no 役職 -- 2:515 is not a key)
    2       0xFFFF    所属部：バレー部                (no 役職)

⇒ a key the table does not have degrades to the no-post line rather than to
garbage or a crash, and NO_CLUB_POST below is the one this server sends.
⚠️ Which of two rules the client follows for the 無所属 rows above is NOT
separable from this end: it may skip the 役職 half whenever `inClub` is 0, or
whenever the row it finds is 「無職」. `club_post.bin` has no row that would
tell them apart. Both readings give the same answer for everything this server
sends, which is why it does not matter yet.
"""

from __future__ import annotations

#: `class_post.bin`, 9 rows. ⚠️⚠️ The keys are NOT 0..8: the table has 0-7 and
#: then 9, with nothing at 8. A range check would accept a key the client
#: cannot look up, which is the shape of thing that has crashed it before.
CLASS_POST_KEYS = (0, 1, 2, 3, 4, 5, 6, 7, 9)

#: 「無職」, and the key every character has carried since round 1.
CLASS_POST_NONE = 0

#: `club_post.bin`, 40 rows, in file order: how many postIds each clubId has.
#: Index is the clubId, which is the same key space as `club.bin` -- 0 is
#: 無所属 with its single 「無職」 row, and 1-8 are the eight playable clubs.
#: ⭐ That the counts line up with the playable eight at all is the first hint
#: that `inClub` is the missing half; it is a hint and not a measurement.
CLUB_POST_COUNTS = (1, 6, 6, 4, 4, 3, 3, 10, 3)

#: 「no 部活役職」 on the wire. ⚠️⚠️ NOT 0: see the module docstring -- 0 is a
#: real row for anybody in a club. The client draws no 役職 at all for a key
#: `club_post.bin` does not have, and 0xFFFF is measured to be one, in a club
#: and out of it.
#:
#: ⭐ INVENTED, and the smallest invention available (the smallest-invention rule). The
#: table has no 「無職」 row for clubs 1-8 -- every club's row 0 is a real rank
#: -- so the original game most likely gave every member a post on 入部 and
#: never had this state at all. This server has members with no post because it
#: has no post system, and something has to go on the wire for them. 0xFFFF is
#: the idiom the rest of this protocol already uses for 「none」 (unequipped
#: accessories, and friendGroupId's 0xFFFFFFFF).
NO_CLUB_POST = 0xFFFF

#: `club_post.bin`'s row 0:0, 「無職」. ⚠️ Only reachable for 無所属, and even
#: there the card draws no 役職 -- it is here to name the row, not as a default.
CLUB_POST_NONE = 0

#: The three readings of the single u16, in the order they are worth trying.
PROBE_READINGS = ("postId", "flat", "packed")


def class_post_exists(key: int) -> bool:
    """Is this a key `class_post.bin` actually has? See CLASS_POST_KEYS."""
    return key in CLASS_POST_KEYS


def club_post_exists(club_id: int, post_id: int) -> bool:
    """Is (clubId, postId) a key `club_post.bin` actually has?"""
    return 0 <= club_id < len(CLUB_POST_COUNTS) and 0 <= post_id < CLUB_POST_COUNTS[club_id]


def club_post_flat(index: int) -> "tuple[int, int] | None":
    """The (clubId, postId) at ``index`` rows into the file, or None past the end."""
    for club_id, count in enumerate(CLUB_POST_COUNTS):
        if index < count:
            return (club_id, index)
        index -= count
    return None


def club_post_readings(value: int, in_club: int) -> "list[str]":
    """What each reading of ``value`` would look up, for the log and the reply.

    ⭐ Printing all three next to the value is what makes one screenshot enough:
    the three predictions are different rows of `club_post.bin`, so whichever
    name the card draws names the reading. A reading that lands on no key at all
    prints 「なし」, and a card that draws no 役職 at all is that answer.
    """
    def show(pair: "tuple[int, int] | None") -> str:
        if pair is None or not club_post_exists(*pair):
            return "なし"
        return f"{pair[0]}:{pair[1]}"

    return [
        f"postId={show((in_club, value))}",
        f"flat={show(club_post_flat(value))}",
        f"packed={show(((value >> 8) & 0xFF, value & 0xFF))}",
    ]


class Posts:
    """One character's two 役職 keys.

    Stored on the character record under "posts" and rebuilt from that dict each
    time, the same arrangement as Career, GameOptions and ScoreCard. Both
    default to 0, which is what every character has been sent since round 1, so
    a record with no "posts" key is byte-identical to how it always was.

    ⚠️⚠️ INVENTED that anything sets these at all (the smallest-invention rule). A
    クラス委員 is elected -- the client has the whole 立候補／推薦／演説／投票
    UI for it and this server has none of it -- and a 部活 post is awarded by
    the club. `/post` is a knob of the same kind as `/career title`: it opens
    the door so the wire can be read off the screen, and it says so.
    """

    def __init__(self, saved: "dict | None" = None) -> None:
        saved = saved if isinstance(saved, dict) else {}
        try:
            class_post = int(saved.get("classPost", CLASS_POST_NONE))
        except (TypeError, ValueError):
            class_post = CLASS_POST_NONE
        if not class_post_exists(class_post):
            if class_post != CLASS_POST_NONE:
                print(f"[posts] {class_post} is not in class_post.bin, dropping")
            class_post = CLASS_POST_NONE
        self.class_post = class_post
        # ⚠️ NOT validated against club_post.bin, and that is deliberate: what
        # the u16 keys is the open question (see the module docstring), so a
        # check here would be a check against a guess. It is clamped to the
        # width of the field and no further.
        try:
            self.club_post = int(saved.get("clubPost", NO_CLUB_POST)) & 0xFFFF
        except (TypeError, ValueError):
            self.club_post = NO_CLUB_POST

    def to_json(self) -> dict:
        return {"classPost": self.class_post, "clubPost": self.club_post}

    def summary(self) -> str:
        return f"classPost={self.class_post} clubPost={self.club_post}"

    def lines(self, in_club: int = 0) -> "list[str]":
        post = ("なし" if self.club_post == NO_CLUB_POST else str(self.club_post))
        return [
            f"クラス役職：{self.class_post}"
            + ("" if class_post_exists(self.class_post) else " (表にない)"),
            f"部活役職：{post} (inClub={in_club}) "
            + " ".join(club_post_readings(self.club_post, in_club)),
        ]
