"""キャッチコピー: 0x4312's exchange, and the 21-byte field it finally fills.

    0x4312 MsgClRequestCharaMenuCatchcopy  -> 0x4313 MsgSvOkCharaMenuCatchcopy
                                           -> 0x4314 MsgSvNgCharaMenuCatchcopy (u8 reason)

⭐ WHERE THE DOOR IS. `win_text` 30 キャッチコピー and 31 更新 sit in one run
with 25 誕生日, 26 星座, 27 血液型, 28 所属部, 29 称号 and 32 試験レベル -- the
labels of the character's own 個人情報 page. The 更新 button under that box is
the only way to send this message, and its action comes out of the same factory
(0x461983, a `(type==2, index)` switch) that builds four messages this server
has answered for a long time: case 2 カリキュラム 0x4309, case 3 通知表 0x430C,
case 4 能力 0x430F, case 5 経歴 0x4315. Case 7 is this one. Same window, same
factory, same kind of click -- which is what makes it reachable rather than a
message only the code remembers.

⚠️ Not to be confused with the 仲良しグループ キャッチコピー. That one is a
counted string inside 0x620A and it has been answered since round 219; this one
is a character's own line and it travels in a fixed field of the character
record. Two different strings with one name.

⭐ THE LAYOUT IS READ OFF THE CLIENT'S OWN CODE, both directions:

  * Input_MsgClRequestCharaMenuCatchcopy::deserialize (0x8CEF90) is four
    instructions long: `push 2; push 0; push 0x15; lea eax,[eax+4]; push eax;
    call 0xA49610` -- the verbatim-copy helper, 0x15 == 21 bytes into the
    message at +4. No count, no terminator handling, no bounds test.
  * the client's own builder (0x4621AD) pushes the same 0x15 into its copy, out
    of a string the edit box handed it (0x461FFD reads the box, news a 0x20
    message and hands it over), and delivers it through the ordinary door.

⇒ the body is exactly 21 bytes, which is `tmn::MAX_CHARA_CATCHCOPY + 1`: twenty
bytes of cp932 and room for the NUL. The character record has had a field of
precisely that width since the first round -- `catchCopy`, right behind
`inClass`/`inClub` in the 238-byte 0x0319 entry and in the 139-byte 0x6501
info block -- and until now this end packed twenty-one zeros into both.

⭐⭐ WHERE IT SHOWS once it is no longer zeros: 「キャッチコピー：%1%」 is
`msg_text` 223, one of the five lines of the name card the client pops when one
player right-clicks another (see posts.py for the other four and for how that
card was measured). That card is built from 0x6501, so the string a player types
into their own page is read back by somebody else's screen.

⚠️ NO VALIDATION HERE, and that is a decision with a source rather than an
omission. The only name rule this project has an origin for is the one the
manual states for 氏名; the 運営方針 text that covers everything else is a list
of things ＧＭ staff act on by hand, not a table a server can check. So what
arrives is stored, and the one thing this module enforces is the width the
client itself enforces.

⚠️⚠️ THE Ng SIDE IS NOT A CHANNEL. `0x4314`'s reason table has exactly one row,
reason 0, and its text begins with the developers' 未使用 marker. That marker is
a comment inside the string and not a switch -- a reason so marked is drawn
anyway, four extra characters and all -- so sending one would put
「未使用：：：システムエラーが発生しました。」 on the player's screen. It is sent
only when there is no character to store the line on, which is a state a playing
client cannot reach, and never as a way of saying "no".

⚠️ NOTHING HERE IS MADE UP (inventions:skip -- this line says there is no entry
for this module in that ledger, rather than declaring one). The width is the
client's, the field is the record's, the door is the client's own button.
"""
from __future__ import annotations

import struct

MSG_CL_REQUEST_CHARA_MENU_CATCHCOPY = 0x4312
MSG_SV_OK_CHARA_MENU_CATCHCOPY = 0x4313
MSG_SV_NG_CHARA_MENU_CATCHCOPY = 0x4314

#: `tmn::MAX_CHARA_CATCHCOPY + 1` -- the width the deserializer copies and the
#: width the field occupies in both character records. Twenty usable bytes.
CATCHCOPY_LEN = 21

#: 0x4314's only row, and the docstring says why nothing else may send it.
NG_NO_CHARACTER = 0


def parse(params: bytes) -> bytes:
    """The line out of a 0x4312 body: the bytes up to the first NUL.

    ⚠️ A short body is padded rather than refused. The client always sends 21,
    so a shorter one means something in front of this misread the stream, and
    truncating what did arrive keeps that visible on the screen instead of
    turning it into a refusal that says nothing.
    """
    raw = bytes(params)[:CATCHCOPY_LEN]
    return raw.split(b"\x00")[0]


def field(line: bytes) -> bytes:
    """One `catchCopy` field: the line, NUL-padded to CATCHCOPY_LEN."""
    return line.split(b"\x00")[0][: CATCHCOPY_LEN - 1].ljust(CATCHCOPY_LEN, b"\x00")


def ng_params(reason: int = NG_NO_CHARACTER) -> bytes:
    """0x4314's body: one reason byte."""
    return struct.pack(">B", reason & 0xFF)


def describe(line: bytes) -> str:
    """What went into the record, for the log."""
    text = line.decode("cp932", "replace")
    return f"{text!r} ({len(line)}B)" if line else "(cleared)"
