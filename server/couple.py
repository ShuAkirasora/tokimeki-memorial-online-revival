"""The カップル list: 0x4500's exchange, and the screen behind it.

    0x4500 MsgClQueryCoupleList   -> 0x4501 MsgSvResultCoupleList  (i16 nCoupleNum)
                                  -> 0x4502 MsgSvErrorCoupleList   (i8  reason)
                                  -> 0x4503 MsgSvNotifyCoupleList  (the rows)

⭐⭐⭐ THIS FAMILY EXISTS AND NOTHING HERE HAD EVER ANSWERED IT. Until this
module, 0x4500..0x4503 appeared in exactly one place in this tree -- their names
in message_names.py -- and the note on mps_session._couple_console said, of the
カップル rules, that "there is no handshake in the message table to read one
off". That sentence was written before anyone looked at 0x45xx. It is wrong, and
the three things it was blocking are all read rather than invented: the field
names, their widths, and the row limit.

⭐ THE NAMES ARE THE CLIENT'S OWN, printed by the message's dump at 0x9BA810:

    coupleInfo[%d]={{info[2]={{charaId=%d, familyName[..], firstName[..],
                               nickName[..], classId=%d,}}
                     ardent=%d, match=%d, date={year=%d,month=%d,day=%d,}}}

⭐ THE WIDTHS COME OUT OF Input_MsgSvNotifyCoupleList::deserialize (0x9BAB60),
read through the stream vtable's slots (the read-slot table) -- the same way
career.py's card was read, and through the same fixed-string helper 0xA49610:

    u16  nCoupleNum                     vt+0x28 -> +0xB04
    per row, twice (info[2]):
      u32  charaId                      vt+0x24
      char familyName[11]               0xA49610, count 11
      char firstName[11]                0xA49610, count 11
      char nickName[11]                 0xA49610, count 11
      u16  classId                      vt+0x28
    u8   ardent                         vt+0x2C
    u8   match                          vt+0x2C
    u16  year                           vt+0x28
    u8   month                          vt+0x2C
    u8   day                            vt+0x2C

(4+11+11+11+2) * 2 + 1+1+2+1+1 = 84 bytes on the wire. ⚠️ The in-memory stride
is 0x58 = 88, not 84: each info is padded to 0x28 and the row to 0x58. Do not
read the stride off the disassembly's `add ebx,0x58` and put it on the wire.

⭐ THE ROW LIMIT IS READ, NOT GUESSED, the same way career.CAREER_LIST_PAGE was:
the count lands at +0xB04 and the rows start at +0x04 with stride 0x58, so the
array holds exactly (0xB04 - 4) / 0x58 == 32 rows and the count sits behind them
with no bounds check.

⚠️ 0x4501 IS SIGNED AND SO IS 0x4502. The Result's reader is vt+0x18 (int16) and
the Error's is vt+0x1C (int8) -- not the unsigned slots their neighbours use
(career's 0x4319 count is vt+0x28, u16). Nothing is known to send a negative
count; the slot is recorded because it was read, not because it is used.

⭐⭐ THE CLIENT SIDE IS WHOLE AND LIVE. CoupleInfoMessageProcedure::onMessage
(0x98FC90) dispatches all three -- Result, Error and Notify -- each to its own
CSequencerCoupleInfo, and on success stores it as the current sequencer, which
is what makes a screen come up. It is byte-for-byte the same function as
CaptureNpcInfoMessageProcedure::onMessage (0x9AE7A0), whose screen is reachable
today through menu_item 17 ＮＰＣ情報参照. The only structural difference is
that CaptureNpc's family has no Notify, so that dispatch has two arms and this
one has three.

⇒ 0x4503 is a Notify: this end may push it without being asked, exactly as
0x480F is pushed. That is the whole reason this module can be tested at all --
see the ⚠️ below for why it has to be.

⚠️⚠️ WHAT IS NOT HERE, AND WHY IT IS NOT A GAP IN THIS SERVER. The manual
(manual/p05_12) states the カップル rules in full, with numbers:

  * a pair forms by TRADING カップルアイテム -- 「メモリアルリング」 (male) and
    「ときめきリング」 (female), bought at the 購買部, with the item they trade
    for obtained by asking 保科先生 in the 保健室;
  * one of each per character, and the trade item cannot be obtained while
    already holding a ring or already in a couple;
  * dropping the ring dissolves the pair, and locks the dropper out of couples
    for 5 days counting the day of the split;
  * a deleted partner also dissolves it, with no penalty;
  * 恋人 get デートチャット: right-click the partner, 交流メニュー, 「デート申込み」,
    then pick a デートスポット outside the school.

⛔️ NONE OF THAT CAN BE BUILT ON THIS CLIENT, and the reason is a date, not a
missing feature on this end. tmo.exe here is stamped 2006-01-23; カップルシステム
went live 2007-02-14 (the same day as that year's バレンタインイベント), thirteen
months later. The data in this build agrees, in three independent places:

  * `item.bin` has 223 rows and NEITHER RING is among them -- while the
    バレンタイン items from that same event (義理チョコ, 本命チョコ, キープチョコ)
    ARE there, so the table is not simply missing its item category;
  * `menu_item.bin` row 1 デートチャット has 有効 == 0, the gate at 0x6A6E4F
    refuses it, and PROTOCOL 2.104 measured the ring of icons topping out at six;
  * `annual_event.bin` has fifteen rows and every one is a test -- β２期間中テスト
    and デバッグ用テスト01..13 -- i.e. this is a β2-era data set, and the service
    proper did not open until 2006-03-31.

⇒ The pairing rules are not "undocumented", they are POST-DATED. Writing them
would not be restoring this build; it would be porting a later one onto it.
What this module restores is the half that IS in this build: the list, its
layout, and the screen that draws it.

⚠️ INVENTED, and kept to the smallest thing that lets the wire be tested:
`ardent`, `match` and `date`. Nothing in this build sets them -- there is no
カップル here to have any of the three -- so they default to zero and are only
moved by /couple probe, a knob of the same kind as career's.
⚠️ Their NAMES are the client's; what they MEAN is not read anywhere. `ardent`
and `match` are one byte each and nothing has probed either range, so do not
write a guessed gloss next to them -- a field's range is not its meaning.
⭐ WHO is on the list is NOT invented: it is read off loverCharaId, the field
/couple has been setting since round 154, so a pair this server actually holds
is a row this message actually carries.
"""

from __future__ import annotations

import struct

MSG_CL_QUERY_COUPLE_LIST = 0x4500
MSG_SV_RESULT_COUPLE_LIST = 0x4501
MSG_SV_ERROR_COUPLE_LIST = 0x4502
MSG_SV_NOTIFY_COUPLE_LIST = 0x4503

NAME_LEN = 11  # tmn::MAX_CHARA_FAMILYNAME + 1, same as characters.NAME_LEN

#: Bytes one coupleInfo occupies ON THE WIRE. See the module docstring for why
#: this is 84 and the in-memory stride is 88.
ENTRY_LEN = 84

#: How many rows one 0x4503 may carry: (0xB04 - 4) / 0x58, read off the
#: deserializer at 0x9BAB60. There is no bounds check behind it, so this is a
#: ceiling to respect rather than one the client will enforce.
COUPLE_LIST_PAGE = 32

#: The only reason byte anything here sends. ⚠️ Unlike 0x4201's seven, this
#: family's reasons have not been read out of `error_message.bin` -- nothing has
#: ever made the client show one, because nothing has ever sent 0x4500. Use
#: the error-message table before assigning a second value to this.
NG_NO_LIST = 0


def _name(raw: bytes) -> bytes:
    """One fixed-width name field, padded and clipped like every other one."""
    return raw.ljust(NAME_LEN, b"\x00")[:NAME_LEN]


def half(chara_id: int, family: bytes, first: bytes, nick: bytes,
         class_id: int = 0) -> bytes:
    """One side of a couple: 39 bytes, the `info[i]` of the dump's name."""
    out = struct.pack(">I", chara_id & 0xFFFFFFFF)
    out += _name(family) + _name(first) + _name(nick)
    out += struct.pack(">H", class_id & 0xFFFF)
    return out


def entry(left: bytes, right: bytes, ardent: int = 0, match: int = 0,
          date: "tuple[int, int, int] | None" = None) -> bytes:
    """One coupleInfo row: two halves and the six trailing bytes.

    ⚠️ `ardent`, `match` and `date` are INVENTED -- see the module docstring.
    The default is zero rather than a plausible-looking number precisely so that
    a screenshot of this screen cannot be mistaken for a measurement.
    """
    year, month, day = date or (0, 0, 0)
    out = left + right
    out += struct.pack(">BB", ardent & 0xFF, match & 0xFF)
    out += struct.pack(">H", year & 0xFFFF)
    out += struct.pack(">BB", month & 0xFF, day & 0xFF)
    return out


def rows(entries: "list[bytes]") -> bytes:
    """0x4503's body: u16 count then the rows themselves."""
    return struct.pack(">H", len(entries)) + b"".join(entries)


def result_params(count: int) -> bytes:
    """0x4501's body: i16 nCoupleNum. Signed; the module docstring says why."""
    return struct.pack(">h", max(-0x8000, min(0x7FFF, count)))


def error_params(reason: int = NG_NO_LIST) -> bytes:
    """0x4502's body: i8 reason."""
    return struct.pack(">b", max(-0x80, min(0x7F, reason)))


def list_replies(entries: "list[bytes]") -> "list[tuple[int, bytes]]":
    """The whole answer to one 0x4500, in the order it goes out.

    Count first, then the rows, which is the order career.list_replies uses and
    the order the client's own two sequencers imply: Result arms the screen with
    a length, Notify fills it.

    ⚠️ Pages at COUPLE_LIST_PAGE. The count in 0x4501 is the TOTAL, not the size
    of the first page -- that is the reading career.py settled on for 0x4319 and
    nothing here contradicts it, but ⚠️ with fewer than 32 rows on any account
    this server can build, it has never been on the wire either way.
    """
    replies: "list[tuple[int, bytes]]" = [
        (MSG_SV_RESULT_COUPLE_LIST, result_params(len(entries)))
    ]
    for start in range(0, max(len(entries), 1), COUPLE_LIST_PAGE):
        replies.append(
            (MSG_SV_NOTIFY_COUPLE_LIST, rows(entries[start:start + COUPLE_LIST_PAGE]))
        )
    return replies


def describe(body: bytes) -> str:
    """Decode a 0x4503 body back for the log.

    Decoded out of the bytes rather than printed off the records, for career.py's
    reason: with a probe armed the two disagree, and a log that does not say what
    actually went out cannot be used to read the screen.
    """
    if len(body) < 2:
        return "(short)"
    count = struct.unpack_from(">H", body, 0)[0]
    parts = []
    for i in range(count):
        off = 2 + i * ENTRY_LEN
        if off + ENTRY_LEN > len(body):
            parts.append("(truncated)")
            break
        ids = struct.unpack_from(">I", body, off)[0], \
            struct.unpack_from(">I", body, off + 39)[0]
        tail = off + 78
        ardent, match = body[tail], body[tail + 1]
        year = struct.unpack_from(">H", body, tail + 2)[0]
        month, day = body[tail + 4], body[tail + 5]
        parts.append(f"{ids[0]:#x}+{ids[1]:#x} ardent={ardent} match={match} "
                     f"{year:04d}-{month:02d}-{day:02d}")
    return f"{count} 組: " + "; ".join(parts) if parts else f"{count} 組"
