"""ＧＭチャット, the player's half: the 0x68xx family and what it puts on screen.

The name says GM on both halves and the direction is not the same. 0x67xx is
the console a GM drives -- apply, cancel, end -- and no account on this build
can reach it (see gmcall.py for that judgement in full). 0x68xx is the other
end of the same conversation: it is what a server says TO a player, and three
of its members are the player's answers coming back. Those three are owed, not
out of reach, and this is them::

    0x6800 MsgSvRequestGMChatResponse  (u32 charaId, familyName[11], firstName[11])
        -> 0x6801 MsgClOkGMChatResponse   (u8: 1 = はい, 0 = いいえ)
        -> 0x6802 MsgClNgGMChatResponse   (u8 reason, the client's own refusal)
    0x6803 MsgSvNotifyGMChatStart      (empty)        the window opens
    0x6804 MsgClCastGMChat             (u16 count, text)      the player speaks
    0x6805 MsgSvNotifyGMChat           (u32 charaId, familyName[11],
                                        firstName[11], u16 count, text)
    0x6806 MsgSvErrorGMChat            (u8 reason)
    0x6807 MsgSvNotifyGMChatCancel     (u8, not read)  the box closes
    0x680B MsgSvNotifyGMChatEnd        (u8, not read)  the window closes

⭐ ONE 0x6800 IS THE WHOLE DOOR. The retail client's handler for it (0x78098A)
builds a name out of the two fixed fields and hands it to 0x6BAFCC, which is a
yes/no box made of `msg_text` by id: 333 ＧＭチャット for the title, 334
「%1%さんからＧＭチャットを申し込まれました」 for the body with that name
substituted, and two buttons -- 5 はい / 369 チャットします, and 6 いいえ /
19 やめる. Each button carries a one-byte action object, 1 behind はい and 0
behind いいえ, and both end in 0x700277, which sends 0x6801 with that byte.
So the box, the wording and the two answers are all the client's; nothing here
had to be designed, only sent.

⭐ THE SHAPES ARE THE CLIENT'S OWN READERS, every one of them:

  * 0x6800 (0x90ACA0): u32 through the stream's +0x24 slot, then two eleven-byte
    fixed copies through 0xA49610 -- familyName at +8 and firstName at +0x13,
    the create block's NAME_LEN twice. 26 bytes.
  * 0x6801 (0x8D83A0): one byte through +0x2C (uint8_t).
  * 0x6802 (0x8D84A0): one byte through +0x1C (int8_t).
  * 0x6803 (0x8CB9A0): `xor eax,eax; ret 8` -- reads nothing.
  * 0x6804 (0x8E0590): u16 count through +0x28, then that many bytes. This is
    0x4900's body exactly, so chat.parse_cast reads it unchanged. The client's
    own builder (0x744F4A) clips at 0x5D before it writes the count, which is
    TEXT_MAX - 1: the same 94-byte buffer every chat channel has.
  * 0x6805 (0x8D7F90): u32, the two eleven-byte names again, then u16 count and
    the text -- the buffer between the text's destination (+0x1E) and its own
    length field (+0x7C) is 94 bytes, TEXT_MAX once more.
  * 0x6807 and 0x680B (0x8D84A0): one byte each, and see below.

⭐⭐ WHAT THE PLAYER SEES, by handler, all six of these sentences new to this
server:

  * 0x6800 -> the 333/334 box with はい and いいえ.
  * 0x6803 (0x780B2C) -> the chat bar's destination becomes the GM and the
    line the player types next leaves as 0x6804. Which of two things is drawn
    depends on the same classifier again, this time on a value the client holds
    for itself (0x6F891C, `[[x]+0xCC]`): category 15 opens the GM's own chat
    window, anything else puts up the box 335 ＧＭチャット開始 /
    336 ＧＭチャットを開始します. ⚠️ MEASURED on a player's client, where it is
    always the box; the window half belongs to a client whose own id is a GM's
    and has not been seen.
  * 0x6805 (0x780DB8) -> one line in the chat window, credited to the name in
    the message.
  * 0x6807 (0x771B6C) -> 0x700502: title 330 ＧＭチャット申し込み拒否 and then
    331 ＧＭチャットを拒否しました if this client is the one that pressed いいえ,
    332 ＧＭチャットを拒否されました otherwise. ⭐ That flag is set locally by
    the いいえ button, so 331 is only ever reached by a client that declined
    AND was sent this message afterwards -- pressing いいえ on its own closes
    the box and says nothing.
  * 0x680B (0x774820) -> the destination clears and the same branch decides
    between 337 ＧＭチャット終了 with 338 ＧＭチャットを終了しました and 337 with
    339 ＧＭチャットは終了しました. ⚠️ A player's client draws 337 + 339.
  * 0x6806 (0x771B2B) -> one line in the log window, the reason run through the
    shared sentence table.

⚠️⚠️ 0x6807 AND 0x680B CARRY A BYTE THAT NEITHER HANDLER READS. Both readers
take one, and both handlers go straight to the window without touching the
message. Their sentences (rows 11-17 of the table 0x6802's neighbours share)
are about the 申し込み and are drawn by the applicant's end, not by this one.
So the value below is chosen for the log and for whoever reads this next, and
changing it cannot change a pixel.

⚠️ THE CLIENT REFUSES BY ITSELF, TWICE, and 0x6802 is how it says so: reason 5
if the applicant's charaId is not in the GM category (see GM_CHARA_ID), reason
8 if this client is already in a GM chat. Both come straight out of 0x78098A,
and reason 5 is the one an end that has this wrong will keep seeing -- it is
sent before anything is drawn, so the symptom is a box that never appears.
⭐ Reason 5's row opens with the developers' 未使用 marker, which is part of
the string and not a switch -- so the retail client sends a row its own table
calls unused, and that is the original's behaviour, not a mistake to correct.

⚠️ WHILE A GM CHAT IS UP THE CHAT BAR IS RE-ROUTED. 0x744F4A tests the
manager's own flag before anything else: set, and the line the player types
leaves as 0x6804 instead of as 0x4900 or any of the addressed channels. So a
player in a GM chat cannot reach the console commands -- which is why the
operator side of this lives on the other connection, or in runtime/console.txt.

⚠️ NOTHING HERE IS MADE UP (inventions:skip). The widths are the client's
readers', the sentences are the client's text tables, the two answers are the
client's own buttons. What this server adds is a way for an operator to press
the GM's side of it, the same way gmcall.py adds one for the queue: the 0x67xx
console those actions would have come from is unreachable on this build.
"""
from __future__ import annotations

import struct

MSG_SV_REQUEST_GM_CHAT_RESPONSE = 0x6800
MSG_CL_OK_GM_CHAT_RESPONSE = 0x6801
MSG_CL_NG_GM_CHAT_RESPONSE = 0x6802
MSG_SV_NOTIFY_GM_CHAT_START = 0x6803
MSG_CL_CAST_GM_CHAT = 0x6804
MSG_SV_NOTIFY_GM_CHAT = 0x6805
MSG_SV_ERROR_GM_CHAT = 0x6806
MSG_SV_NOTIFY_GM_CHAT_CANCEL = 0x6807
MSG_SV_NOTIFY_GM_CHAT_END = 0x680B

#: What the dispatcher hands to the handler: the player's three.
HANDLED = frozenset({
    MSG_CL_OK_GM_CHAT_RESPONSE,
    MSG_CL_NG_GM_CHAT_RESPONSE,
    MSG_CL_CAST_GM_CHAT,
})

#: ⭐⭐⭐ THE ONE THING THE CLIENT CHECKS ABOUT AN APPLICANT: the charaId's
#: category has to be 15. 0x6800's handler runs the id through the shared
#: classifier at 0x404FF9 -- which answers `id >> 16` for an id inside
#: 0x10000..0x11FFFF and zero for an ordinary character (0x1000000 and up) --
#: and refuses anything that is not 15 by sending 0x6802 back on its own. So a
#: GM is not a character with a flag; it is an id out of a range of its own,
#: and the client's own file for that range holds a roster of fourteen.
#: ⭐ 0x6805 reads the same category and puts the line in a different channel
#: when it is 15, so the GM's lines are drawn as the GM's and not as a
#: player's -- which is why this id is used for those as well.
#: ⚠️ MEASURED: sending an operator's own charaId gets 0x6802 reason 5 and no
#: box at all, every time. The row within the category is not checked; row 0 is
#: the first of the client's own, so that is what goes out.
GM_CATEGORY = 15
GM_CHARA_ID = GM_CATEGORY << 16

#: tmn::MAX_CHARA_FAMILYNAME + 1, the width both fixed name fields are read at.
NAME_LEN = 11
#: The text buffer in 0x6804's reader and 0x6805's alike; one byte of it is the
#: terminator the count includes.
TEXT_MAX = 94

#: 0x6802's two reasons, by the rows the client's own table gives them. These
#: are what a retail client sends unprompted; nothing here ever sends 0x6802.
NG_BAD_CHARA_INFO = 5   # 未使用：：：キャラクターの情報が不正です。 (not on campus)
NG_ALREADY_APPLIED = 8  # 既に申し込んでいます。 (already in a GM chat)

#: 0x6806's rows, from the same table. reason 3 is the one that fits a line
#: arriving with no chat open: 「指定されたキャラクターは、現在申し込みを受けて
#: いません。」
ERROR_NOT_APPLIED = 3

#: 0x6807's byte. Neither of the two rows is read by the handler (see the
#: docstring); they name the event for the log.
CANCEL_REFUSED = 12    # 申し込みを断られました。
CANCEL_CANCELLED = 13  # 申し込みがキャンセルされました。
#: 相手がログアウトもしくはキャラクター選択画面に戻ったため、申し込みをキャン
#: セルしました。 -- the row that names a partner leaving, which is the one
#: event here that the table describes exactly.
CANCEL_PARTNER_GONE = 14

#: 0x680B's byte. Every row of that table is about the 申し込み and the only
#: one about an ending is marked 未使用, so an ordinary end sends a zero rather
#: than a row picked to look meaningful. The handler reads neither.
END_NORMAL = 0


def request_params(family: bytes, first: bytes,
                   chara_id: int = GM_CHARA_ID) -> bytes:
    """0x6800's body: the applicant's charaId and their two fixed names.

    ⚠️⚠️ The id defaults to GM_CHARA_ID and callers should leave it there: an
    id outside category 15 is refused by the client before anything is drawn.
    The NAME is free -- the client reads it off this message rather than out of
    its own roster -- so it is the operator's to choose.

    ``family`` and ``first`` are the create block's fields, already NUL-padded
    to NAME_LEN, which is the shape the client's fixed reader wants -- so they
    go out as they are, padded or cut only if a caller hands over something
    that is not that.
    """
    return (
        struct.pack(">I", chara_id & 0xFFFFFFFF)
        + family.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        + first.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
    )


def parse_answer(params: bytes) -> "int | None":
    """0x6801's byte: 1 for はい, 0 for いいえ. None if the body is too short.

    ⚠️ Read as "not zero is yes" by the caller rather than "== 1": the two
    action objects behind the buttons carry 1 and 0, so anything else did not
    come from either of them and refusing it silently would hide that.
    """
    return params[0] if params else None


def parse_reason(params: bytes) -> "int | None":
    """0x6802's reason byte, the client refusing on its own."""
    return params[0] if params else None


def notify_params(chara_id: int, family: bytes, first: bytes, text: str) -> bytes:
    """0x6805's body: who spoke, their two fixed names, and one counted line.

    ⭐ The GM's own lines pass GM_CHARA_ID here, the player's pass theirs: the
    handler reads the category out of this field and draws the two in different
    channels.

    The names are fixed-width here, unlike the counted pair the ordinary chat
    channels carry, so they are padded rather than cut at their terminator. The
    text is clipped to the client's own buffer and given its terminator back --
    the count on this wire includes it.
    """
    raw = text.encode("cp932", "replace")[: TEXT_MAX - 1] + b"\x00"
    return (
        struct.pack(">I", chara_id & 0xFFFFFFFF)
        + family.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        + first.ljust(NAME_LEN, b"\x00")[:NAME_LEN]
        + struct.pack(">H", len(raw))
        + raw
    )


def one_byte(value: int) -> bytes:
    """0x6806 / 0x6807 / 0x680B: a single byte, however it is read."""
    return struct.pack(">B", value & 0xFF)


class Desk:
    """Who has been asked and who is talking, by charaId.

    Two maps rather than one state per character because the two states answer
    different questions and a stray message has to be able to tell them apart:
    an 0x6801 is only meaningful against an invitation, and an 0x6804 only
    against a chat that started. Nothing is persisted -- a GM chat is a
    conversation between two connections, and neither end survives a restart.
    """

    def __init__(self) -> None:
        self.invited: "dict[int, int]" = {}   # player charaId -> GM charaId
        self.talking: "dict[int, int]" = {}   # player charaId -> GM charaId

    def invite(self, player: int, gm: int) -> None:
        self.invited[player] = gm

    def start(self, player: int) -> "int | None":
        """Move an invitation to a conversation; the GM's id, or None."""
        gm = self.invited.pop(player, None)
        if gm is not None:
            self.talking[player] = gm
        return gm

    def gm_of(self, player: int) -> "int | None":
        """The GM this player is talking to, if the chat is up."""
        return self.talking.get(player)

    def waiting_for(self, player: int) -> "int | None":
        """The GM whose box is on this player's screen, if one is."""
        return self.invited.get(player)

    def player_of(self, gm: int) -> "int | None":
        """The one player this GM has a box or a chat with, if any.

        A conversation wins over an invitation: an operator who invites a
        second player without ending the first is describing an order that only
        the GM's own console could give, and this end answers the one that is
        already on screen.
        """
        for player, who in self.talking.items():
            if who == gm:
                return player
        for player, who in self.invited.items():
            if who == gm:
                return player
        return None

    def forget(self, player: int) -> None:
        self.invited.pop(player, None)
        self.talking.pop(player, None)

    def summary(self) -> str:
        parts = [f"0x{p:x}<-0x{g:x} 申込中" for p, g in self.invited.items()]
        parts += [f"0x{p:x}<->0x{g:x} 会話中" for p, g in self.talking.items()]
        return ", ".join(parts) or "(none)"
