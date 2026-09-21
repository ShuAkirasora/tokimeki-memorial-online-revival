"""The GM's two one-way notices: 強制ログアウト and ＧＭメッセージ.

Two more members of the 0x68xx family, and neither of them is a conversation::

    0x6809 MsgSvNotifyGMLogout   (empty)              「強制ログアウト」
    0x680A MsgSvNotifyGMMessage  (u16 count, text)    「ＧＭメッセージ」

They are the far end of two buttons on a console no account on this build can
open -- 0x670C MsgClRequestGMLogout (u32 charaId) and 0x670F MsgClCastGMMessage
(u16 count, text). gmcall.py carries the judgement on that console in full and
this file does not repeat it; what matters here is that the judgement was about
the *sending* half. It said nothing about whether this end could put these two
on a player's screen, and it turns out that it can: both are registered
handlers in the retail client (0x771B83 and 0x780E85), which is the same thing
that made ＧＭチャット answerable in gmchat.py.

⭐ THE SHAPES ARE THE CLIENT'S OWN READERS.

  * 0x6809 (0x8CB9A0): `xor eax,eax; ret 8` -- it reads nothing. The same
    deserializer 0x6803 MsgSvNotifyGMChatStart uses, and an empty body can only
    be about the connection it arrives on: there is no room in it for anybody
    else's name.
  * 0x680A (0x8E0590): u16 count through the stream's +0x28 slot into the
    message's own length field at +0x62, then that many bytes copied raw to
    +4. The room for the text is therefore 0x62 - 4 = 94 bytes with the
    terminator inside it -- TEXT_MAX again, the same buffer every chat channel
    has. ⭐ It is literally the same function as 0x6804 MsgClCastGMChat and
    0x4900's cast body, so chat.parse_cast reads one unchanged.

⭐⭐ WHAT EACH HANDLER BUILDS, read out of the two of them. Both end in
0x6FA455, the box constructor every refusal on this wire goes through
(0x6FA4D3, the `title + msgId + reason` helper, is a wrapper around it), and
both take their title from a row of `msg_text` written into the handler:

  * 0x6809 (0x771B83) -> title 342 「強制ログアウト」, body 343
    「ＧＭに強制的にログアウトされました」. Both rows are fixed; the message
    carries nothing to put in them.
  * 0x680A (0x780E85) -> title 344 「ＧＭメッセージ」, body = the line this
    end sent, taken from the message at +4.

⚠️⚠️ NEITHER BOX HAS BEEN SEEN ON SCREEN, AND THAT WAS MEASURED, not assumed.
Both were pushed at a retail client standing on a map, and 0x680A also at one
sitting in a live ＧＭチャット; thirty-two seconds of screenshots, four a
second, covering the whole delivery window caught no box in any frame. What the client's own log shows is that
everything up to the drawing happened: it parses the body and names the field
(`MsgSvNotifyGMMessage, utterance[25]={…}`), hands it to its own
GMResponseMessageProcedure, and the handler runs far enough to build the
dialog -- the log prints its `title_`, the flags, and `button`.

⭐ What separates them from a box that does appear is one field. 0x6800, whose
own box went up on that same screen in that same state, reads its window out
of `this+0x400`; these two read `this+0x3f0` and `this+0x3ec`. All three are
members of the one listener object -- so it is not the window machinery in
general, it is which window these two are queued into, and what fills those
two fields has not been found. ⛔️ So nothing here may be read as "the player
sees this"; what is recovered is that the message is delivered, named and
dispatched, and that the widths and the sentences are the client's.

⚠️⚠️ 0x6809 LOGS NOBODY OUT. Its handler builds a window and returns; nothing
in it closes a socket or unwinds a session. But its own sentence is in the past
tense -- the player is told they *have* been logged out -- so a server that
sent it and left the connection up would be saying something untrue. Closing
the connection is therefore this end's own act, and the order is the one
shutdown.py uses for the same reason: say it first, then go. ⭐ On the measured
run the player was thrown out of the game with the client's own red
「通信が断たれました」 box, which is what a closed socket always draws here.

⭐ THE ONE RULE HERE WAS RECOVERED, not chosen. 0x670E, the refusal to the GM's
own 強制ログアウト request, has a reason 3 reading 「指定したキャラクターが校内
マップ上にいません」 -- so the original refused to force out a character who was
not at school, rather than reaching for one that was not there. This end asks
the same question the only way it can: the target has to be a live connection
that has 登校'd.

⚠️ NOTHING HERE IS MADE UP (inventions:skip). The widths are the client's
readers', the box and its two fixed sentences are the client's own text tables,
and the line in a ＧＭメッセージ is whoever typed it -- the same division as a
chat line. What this end adds is a way for an operator to press the GM's side
of both, exactly as gmchat.py and gmcall.py do, and the closing of the socket
that the first one's sentence commits it to.
"""
from __future__ import annotations

import struct

import chat

MSG_SV_NOTIFY_GM_LOGOUT = 0x6809
MSG_SV_NOTIFY_GM_MESSAGE = 0x680A

#: Room for the line in the client's own message struct: the text is copied to
#: +4 and its length field is at +0x62. The terminator lives inside this, and
#: it is the same 94 bytes chat.TEXT_MAX names -- the reader is the same one.
TEXT_MAX = 0x62 - 4


def logout_params() -> bytes:
    """0x6809's body, which is nothing at all.

    Here so that a caller names the message rather than writing ``b""`` beside
    it, and so that the one place that knows the shape is this file.
    """
    return b""


def message_params(text: str) -> bytes:
    """0x680A's body: one counted cp932 line.

    Whole characters are dropped until the line fits (chat.clip), because the
    client's copier bounds itself against the packet and never against the
    destination: a count that overran would be written past the end of the
    client's own message struct, and a count that cut a character in half
    would be drawn as garbage. The terminator is inside the count, the way
    every counted string on this wire carries one.
    """
    raw = chat.clip(text, TEXT_MAX - 1) + b"\x00"
    return struct.pack(">H", len(raw)) + raw
