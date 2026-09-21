"""システムメッセージ: the server talking to a player as the server.

0xA001 MsgSvNotifySystemMessage is the one message on this wire that belongs to
no subsystem. It carries a line of text and an importance byte, and the client
draws it in a window of its own:

    0xA001 MsgSvNotifySystemMessage   (u16 count, count bytes, u8 importance)

No MsgCl names this topic, so nothing a player does asks for one: the server
volunteers it, and what this file adds is a way for an operator to press it --
the same thing gmchat.py adds for ＧＭチャット, and for the same reason. The
console the original's own staff would have driven is the 0x67xx family, and
no account on this build can reach it.

⭐ THE SHAPE IS THE CLIENT'S OWN READER (0x8EBEB0), not a guess. A u16 through
the stream's +0x28 slot into the message's own length field, then that many
BYTES copied raw by the stream's block read, then one byte through +0x2C. The
text lands at message+4 and the length field sits at +0x196, so the room for it
is 0x192 = 402 bytes with the terminator inside that; the block read clips to
what is left in the stream and to nothing else, so keeping the count inside the
client's buffer is this end's job. The encoding and the terminator are the ones
every other counted string in this protocol uses: cp932, and the count includes
the terminator.

⭐⭐ WHAT THE PLAYER SEES, measured on a retail client rather than reasoned:

  * a window in the top right corner, titled with msg_text 14
    「システムメッセージ」, the line in its body, and one 「確 認」 button.
  * It does not stop the game. The map keeps running underneath it, the
    toolbar still answers, and the player can walk away with it open.
  * They stack, newest on top. Four were pushed without touching the box and
    four 確認 presses took them off again in reverse order, the window going
    away with the last one.
  * ⚠️ NOTHING COMES BACK. 確認 sends not one byte -- which is the same fact
    as "no MsgCl names this topic", seen from the other side. This end cannot
    learn whether a player read one.

⚠️⚠️ THE IMPORTANCE BYTE CHANGED NOTHING WE COULD SEE. 0, 1, 2 and 255 were
each pushed at a retail client and all four drew the same window, in the same
place, with the same single button. The field is real -- the client parses it
and prints it back by its own name, ImportanceLevel -- but what it selects was
not found. So this end sends 0 unless an operator asks for another value,
rather than dressing a guess up as a rule, and the operator can ask for any
byte precisely so that the next person to look has a way to keep measuring.

⚠️ NOTHING HERE IS MADE UP (inventions:skip). The width and the order are the
client's reader's, the window and its button are the client's own, and the text
is whoever typed it -- the same division as a chat line, where this server
carries what somebody said and invents no sentences of its own.
"""
# UNSENT 0xA002 -- EchoGameMessage, the second face of the same handler object
# and the same GameSystemMessageProcedure that draws the box above. Its body
# was read out of the client as well (u16 messageTypeNo, then a counted string
# into a 0x8000 buffer), and its occasion never was: nothing in the client asks
# for one and no sentence anywhere says what an echo is for. ⭐ What settles it
# is not the missing occasion but the client's own dispatch table: the
# sequencer that owns this family declares three messages and carries exactly
# one registration, and the one is 0xA001. A message with no registered
# handler is parsed and dropped -- that was measured on 0x0001, whose log line
# for it reads 受信ハンドラが設定されていません -- so an echo pushed at this
# build would change nothing on any screen. ⚠️ Its sibling 0xA004
# ResultServerVersion is the third of those three and is unsent for its own
# reason, a few files away.
from __future__ import annotations

import struct

MSG_SV_NOTIFY_SYSTEM_MESSAGE = 0xA001

#: Room for the line in the client's own message struct: the text is copied to
#: +4 and its length field is at +0x196. The terminator lives inside this.
TEXT_MAX = 0x196 - 4

#: What goes out when nobody said otherwise. Not a recovered default -- see the
#: paragraph above on why no value can be called the right one yet.
DEFAULT_IMPORTANCE = 0


def notify_params(text: str, importance: int = DEFAULT_IMPORTANCE) -> bytes:
    """0xA001's body: one counted cp932 line and the importance byte.

    The line is clipped to the client's buffer before its terminator is put
    back, so an operator who pastes a paragraph gets a short message rather
    than a client writing past the end of its own message struct: the reader
    bounds the copy against the packet, never against the destination.
    """
    raw = text.encode("cp932", "replace")[: TEXT_MAX - 1] + b"\x00"
    return struct.pack(">H", len(raw)) + raw + struct.pack(">B", importance & 0xFF)
