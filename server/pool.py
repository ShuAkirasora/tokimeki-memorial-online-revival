"""The message pool: 0xA100's exchange, and the one refusal in it that is real.

    0xA100 MsgClQueryPoolMessage   (u32 charaId)
        -> 0xA101 MsgSvResultPoolMessage   (u16 nNum)
        -> 0xA102 MsgSvErrorPoolMessage    (i8  reason)
        -> 0xA103 MsgSvNotifyPoolMessage   (the bodies)

⭐ THE REQUEST IS THE WHOLE POINT OF THIS MODULE. Every other 一覧 query on this
protocol -- 0x4500 カップル, 0x6400 アドレス帳, 0x622A グループ -- serialises
**empty**, which is why each of their Error siblings ends in a `# UNSENT` line
beside its own family: with nothing in the request, 「…が不正です」 can only be
about a record this end already holds, i.e. the original's store answering
badly. ⭐⭐ 0xA100 is the one that does not. Its dump (0x915A00) prints

    MsgClQueryPoolMessage(0xA100), charaId=%d,

and the wire agrees: `params=00000001`, four bytes, in all 13 of the requests in
this project's logs. ⇒ There **is** something in the request to judge, so the
refusal that judges it is one this end can send.

⚠️⚠️ WHAT WE CANNOT SAY is what that charaId means, and the logs are why: every
one of those 13 was 1, and so was the character that sent them. One value in a
column is the wall round 149 named -- 「whose pool」 and 「always 1」 fit the
measurements equally well. ⭐ The judgement below does not need the answer: an
id no account here claims is invalid either way, and an id that IS the asker's
own is always claimed, so the two readings cannot disagree about this server's
behaviour.

⭐ THE SENTENCES, out of `error_message.bin` (they are 0xA102's own rows, not a
redirect -- FUN_008163e9 leaves this id alone):

    reason 0  キャラクターの情報が不正です。
    reason 1  未使用：：：メッセージを取得できない状態です。
    reason 2  未使用：：：既にメッセージの取得を開始しています。
    reason 3  キャラクターデータの取得もしくは変更に失敗しました。
    reason 4  未使用：：：未定義のエラーが発生しました。

Two live, and they split cleanly: reason 3 is the back end this server does not
have (the same category as mps_session's twelve), and reason 0 is the one about
the parameter that actually arrived. ⚠️ Note what rounds 1 and 2 say in
passing -- 「取得を開始」, a pool you *start* reading -- so the original had a
session-shaped read this end does not model. That is a note, not a plan: no
client message names it.

⛔️ 0xA103 IS NOT SENT, and it is not a discount on a count. What settles it is
the **writer**, measured the only way it can be: the client's whole MsgCl table
holds no request that posts into this pool -- the 0xA1xx family is these four
ids and nothing else -- so a player cannot fill it, and neither can a script.
⚠️ What the rows look like says who could: a counted string plus an
ImportanceLevel and a category is an operator's announcement, not player mail,
and the one operator surface this protocol has is the ＧＭ console, whose whole
0x67xx family is declared unsent (gmcall.py) because no player on this build can
open it. ⇒ The pool is empty here because this server has no writer for it,
not because a count was rounded down.
# UNSENT 0xA103 -- PoolMessage bodies: the only writer is the ＧＭ console, and that whole family is unsent.
"""

from __future__ import annotations

import struct

MSG_CL_QUERY_POOL_MESSAGE = 0xA100
MSG_SV_RESULT_POOL_MESSAGE = 0xA101
MSG_SV_ERROR_POOL_MESSAGE = 0xA102
MSG_SV_NOTIFY_POOL_MESSAGE = 0xA103

#: 「キャラクターの情報が不正です。」 -- the charaId in the request names nobody.
NG_BAD_CHARA = 0

#: 「キャラクターデータの取得もしくは変更に失敗しました。」 ⚠️ Named because it
#: is live in the table, never sent: it is the original's store failing.
NG_STORE = 3


def request_chara_id(params: bytes) -> int | None:
    """The charaId out of one 0xA100, or None when the body is short.

    ⚠️ A short body is not a refusal. 0xA102 answers a charaId that named
    nobody; a request with no charaId in it never got that far, so the caller
    logs and drops it, the way every other short body on this protocol is
    handled.
    """
    if len(params) < 4:
        return None
    return struct.unpack_from(">I", params, 0)[0]


def result_params(count: int) -> bytes:
    """0xA101's body: u16 nNum, how many pooled messages are waiting."""
    return struct.pack(">H", max(0, min(0xFFFF, count)))


def error_params(reason: int = NG_BAD_CHARA) -> bytes:
    """0xA102's body: i8 reason.

    ⚠️ Signed, read off the deserializer: this id takes its one byte through
    the stream's vt+0x1C slot (int8_t), not the vt+0x2C the neighbours use.
    """
    return struct.pack(">b", max(-0x80, min(0x7F, reason)))
