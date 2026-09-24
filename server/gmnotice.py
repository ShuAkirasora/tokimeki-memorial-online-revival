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

⭐⭐ BOTH BOXES ARE DRAWN. They are the small notice in the top right corner
that every refusal on this wire uses -- the constructor places it at
(0x1CC, 0x78) itself -- and it goes away on its own after about five seconds.
Measured on a retail client standing in a classroom: 0x680A with an ASCII line
and with a full-width one, and 0x6809 with its empty body, each drawn with
its own title and sentence.

⚠️⚠️ An earlier reading of this file said neither box ever appeared and that
the two handlers took their window from different fields than 0x6800's does
(`this+0x3f0` / `this+0x3ec` against `this+0x400`). ⛔️ Both halves were wrong.
The listener multiply-inherits one base per message and each handler is
entered with `this` at its own base -- 0x6800 at +0x198, 0x6809 at +0x1A8,
0x680A at +0x1AC -- so all three read the one field at +0x598 of the whole
object; and 0x5A02 MsgSvNgClubEnter, whose box is certainly drawn, reads it
at +0x180 + 0x418, the same place again. What that empty run had seen could
not be reproduced; pushed unprompted from the console, each of the three
boxes appears on its own. ⚠️ The control that settles it has to be well
formed: a 0x5A02 cut short to one byte draws nothing either, because the
reader never gets to the handler.

⚠️⚠️ 0x6809 LOGS NOBODY OUT. Its handler builds a window and returns; nothing
in it closes a socket or unwinds a session. But its own sentence is in the past
tense -- the player is told they *have* been logged out -- so a server that
sent it and left the connection up would be saying something untrue. Closing
the connection is therefore this end's own act, and the order is the one
shutdown.py uses for the same reason: say it first, then go. ⭐ And the order
is enough: a player on a map sees the 強制ログアウト notice and the client's
own red 「通信が断たれました」 box on top of each other, the notice fading
after its five seconds. ⚠️ Not in the middle of a ドラマイベント: that screen
goes black the moment the socket closes and only the red box is drawn, so
there the sentence is lost. Waiting before the close would save it, but for
how long is nothing the client says -- that would be a number of this end's
own, and none is set.

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
