"""ツーショットチャット: the PC 交流メニュー's first icon and the screen behind it.

Right-click another player, pick 「ツーショット」, and the client sends one u32.
That much was measured in round 151 alongside the other three icons; what came
back until now was a refusal, because a whole subsystem is not a message. This
is the subsystem.

WHAT IT IS -- and the manual says it in one sentence
----------------------------------------------------
`manual/p05_05` section 4 「チャットの種類」:

    「ツーショットチャット」 …ウェストアップ画面で友達のキャラクターを見ながら、
    ２人きりで会話ができます。このチャットで感情表現を行うと、感情アイコン表示
    ではなく、感情に応じた表情変化が行われます。

So it is not a channel on the map: it is the ウェストアップ screen -- the same
one the scripts reach with `SCREEN_CHANGE_WAISTUP` -- with the other player's
character standing in it, and it takes the whole screen for both of them until
one leaves. `manual/p05_03` names the button that leaves: 「ツーショットチャット
終了ボタン」, which appears 「ツーショットチャット時のみ」.

Two things follow, and both are why this family is shaped the way it is:

  * a background has to be chosen, because a waist-up screen has one -- that is
    `MsgSvNotifyTwoshotStart`'s ``placeId``, and see PLACE below;
  * 感情 in here is a face, not an icon over a head, which is why 0x5403 has its
    own message instead of reusing the map's 0x480C.

THE HANDSHAKE, read off the client's own message classes
--------------------------------------------------------
Shapes from the client's own deserialisers, names from each class's dump
function. Nothing here is guessed:

    0x5000 Cl RequestTwoshotRequest  targetId u32       SEEN (round 151)
    0x5001 Sv OkTwoshotRequest       --                 the asker's receipt
    0x5002 Sv NgTwoshotRequest       reason u8
    0x5003 Sv RequestTwoshotResponse senderId u32       the other side is asked
    0x5004 Cl OkTwoshotResponse      reply u8           they accept
    0x5005 Cl NgTwoshotResponse      reason u8          they decline
    0x5006 Sv NotifyTwoshotStart     placeId u16        both screens change
    0x5007 Cl RequestTwoshotCancel   --   -> 0x5008/0x5009, peer gets 0x500A
    0x500A Sv NotifyTwoshotCancel    reason u8          the application ended
    0x5200 Cl RequestTwoshotEnd      --   -> 0x5201/0x5202, peer gets 0x5203
    0x5203 Sv NotifyTwoshotEnd       reason u8          the screen closes
    0x5400 Cl CastTwoshotChat        utterance
    0x5401 Sv NotifyTwoshotChat      senderId u32, name, utterance
    0x5402 Sv ErrorTwoshotChat       reason u8
    0x5403 Cl CastTwoshotEmotion     emotionId u16
    0x5404 Sv NotifyTwoshotEmotion   senderId u32, emotionId u16
    0x5405 Sv ErrorTwoshotEmotion    reason u8

⭐⭐ CANCEL AND END ARE DIFFERENT THINGS HERE, which トレード left ambiguous.
There the two pairs sit in one block (0x5106 中止 and 0x5109 終了) and round 213
could not tell them apart. Here they are in different blocks with different
notifies, and 0x5200's own block is where the manual's 「終了ボタン」 lands: 0x5007
withdraws an application nobody has answered yet, 0x5200 leaves a screen that is
already open. The client's own error table agrees -- see the reason lists below,
where the End notify's slot is literally named 「終了メッセージ」.

⭐⭐ TWO OF THE FOUR PACKERS ARE ALREADY WRITTEN, and not because the shapes
look alike. `Input_MsgSvNotifyTwoshotChat`'s vtable[0] is **0x8D6230**, the very
function `Input_MsgSvNotifyNormalChat` uses, and `Input_MsgSvNotifyTwoshotEmotion`'s
is **0x8F1840**, the one `Input_MsgSvNotifyLessonEmotion` uses. Same reader, same
bytes, same buffer sizes -- so chat.notify_params and chat.lesson_emotion_params
are exact here rather than merely compatible.

⭐⭐⭐ PLACE: ``placeId`` HAS A SOURCE, AND IT IS PER CELL
----------------------------------------------------------
This was the family's one open question. `error_message.bin` 0xFF05 reason 11 --
「指定されたキャラクターがいる場所ではツーショットチャットを行うことはできません」
-- says the id is about where the other player is standing, and it turns out to
be exactly that, literally:

    every cell of every cld_*.bin carries a u32 at +4, and each value that is
    not 0xffffffff is a key of `twoshot_place.bin`.

屋外 is cut into its 27 outdoor places (校門周辺, 並木道, 噴水 … 泉, 水辺,
テニスコート), 食堂 into 食堂 and 購買部, the library into 図書室 / 図書室本棚 /
図書室受付, and all 26 classroom maps into the single place named 教室. Not one
value in all 126555 cells falls outside the table, and the 48 places whose keys
are ≥256 -- 通学路, 駅, 海, 遊園地 -- appear nowhere, exactly as they should,
being off campus. The map exporter documents the four checks; the server
reads it through mapgraph.region, and `the map exporter regions` prints it.

⇒ The place is the target's cell, and a cell with no place is what reason 11
refuses. 33% of all cells are such cells.

⚠️ WHICH of the two players' cells is a reading, not a measurement: reason 11
says 「指定されたキャラクター」, which from the asker's side is the target, so the
target's cell picks the background. The two are nearly always the same cell's
place anyway -- you have to be next to somebody to right-click them.

WHERE THE REFUSALS COME FROM -- ⭐⭐⭐ and this is the round's other finding
--------------------------------------------------------------------------
Round 213 established that a refusal's reason byte is an index into
`error_message.bin`, and that this family's sentences sit under the pseudo id
0xFF05 rather than under the message's own number. What it could not say was
which pseudo id each message uses. **The client has that as a function**:

    FUN_008163e9(u16 msgId) -> u16 pseudoId

a compare chain that redirects 57 message ids and returns the id unchanged for
everything else. Its one caller, at 0x817048, builds the (id, reason) key that
looks the sentence up. So the mapping is not inferred from wording any more --
it is read, and it splits this family across three tables:

    0x5002 NgTwoshotRequest   -> 0xFF05    the 申し込み refusals
    0x5009 NgTwoshotCancel    -> 0xFF05
    0x5202 NgTwoshotEnd       -> 0xFF05
    0x500A NotifyTwoshotCancel-> 0xFF04    ⭐ the *notify* list, shared by all
    0x5203 NotifyTwoshotEnd   -> 0xFF04       six 申し込み subsystems
    0x5402 ErrorTwoshotChat   -> 0xFF00    the chat list, shared by all channels
    0x5405 ErrorTwoshotEmotion-> 0xFF00

⭐ 0xFF04 is the discovery. It holds reasons 11..17 and nothing else -- 「申し込み
を断られました」, 「申し込みがキャンセルされました」, 「相手がログアウトもしくは
キャラクター選択画面に戻ったため、申し込みをキャンセルしました」 -- and every
`Notify*Cancel`/`Notify*End` in the game maps to it: this family's two, トレード's
0x510D/0x510E, 仲良しグループ's 0x6217/0x6222, 友達登録's 0x640D, ＧＭチャット's
0x6807/0x680B. It is the sentence list for "the application you were part of is
over, and here is why", which is a thing no per-subsystem list ever had.

⚠️ It also settles a trade bug by inspection: trade.py sent 0x510E with 24 out
of the 0xFF09 list, and 0xFF04 has no row 24, which is why round 213 watched a
disconnected partner's window close leaving not one character on screen. Fixed
alongside this.

NOTHING HERE IS SAVED
---------------------
A twoshot is two people standing in front of each other, exactly like the 友達
登録, 勧誘 and トレード handshakes: all of it lives on the two sessions and dies
with either connection. Unlike トレード it does not even leave an item move
behind -- when it is over there is nothing to write down.
"""

from __future__ import annotations

import struct

MSG_CL_REQUEST_TWOSHOT_REQUEST = 0x5000
MSG_SV_OK_TWOSHOT_REQUEST = 0x5001
MSG_SV_NG_TWOSHOT_REQUEST = 0x5002
MSG_SV_REQUEST_TWOSHOT_RESPONSE = 0x5003
MSG_CL_OK_TWOSHOT_RESPONSE = 0x5004
MSG_CL_NG_TWOSHOT_RESPONSE = 0x5005
MSG_SV_NOTIFY_TWOSHOT_START = 0x5006
MSG_CL_REQUEST_TWOSHOT_CANCEL = 0x5007
MSG_SV_OK_TWOSHOT_CANCEL = 0x5008
MSG_SV_NG_TWOSHOT_CANCEL = 0x5009
MSG_SV_NOTIFY_TWOSHOT_CANCEL = 0x500A
MSG_CL_REQUEST_TWOSHOT_END = 0x5200
MSG_SV_OK_TWOSHOT_END = 0x5201
MSG_SV_NG_TWOSHOT_END = 0x5202
MSG_SV_NOTIFY_TWOSHOT_END = 0x5203
MSG_CL_CAST_TWOSHOT_CHAT = 0x5400
MSG_SV_NOTIFY_TWOSHOT_CHAT = 0x5401
MSG_SV_ERROR_TWOSHOT_CHAT = 0x5402
MSG_CL_CAST_TWOSHOT_EMOTION = 0x5403
MSG_SV_NOTIFY_TWOSHOT_EMOTION = 0x5404
MSG_SV_ERROR_TWOSHOT_EMOTION = 0x5405

#: Every MsgCl in the family, handled in one piece for the reason trade.py and
#: item.py give for theirs: a screen with one live button is not a smaller
#: working screen, it is one that wedges on the first wrong click.
HANDLED = frozenset(
    {
        MSG_CL_REQUEST_TWOSHOT_REQUEST,
        MSG_CL_OK_TWOSHOT_RESPONSE,
        MSG_CL_NG_TWOSHOT_RESPONSE,
        MSG_CL_REQUEST_TWOSHOT_CANCEL,
        MSG_CL_REQUEST_TWOSHOT_END,
        MSG_CL_CAST_TWOSHOT_CHAT,
        MSG_CL_CAST_TWOSHOT_EMOTION,
    }
)

# ---------------------------------------------------------------------------
# 0xFF05 -- 0x5002 / 0x5009 / 0x5202. Verbatim from error_message.bin, with the
# file's numbering: slots the original marked 未使用 are named and left unsent
# rather than dropped, because dropping one would renumber the rest.
# ---------------------------------------------------------------------------
REASON_NONE = 0              # 未使用：：：エラーなし
REASON_TARGET_BUSY = 1       # 指定されたキャラクターは、現在申し込みを受けられる状態ではありません。
REASON_REQUEST_FAILED = 2    # ツーショットチャットの申し込みに失敗しました。
REASON_TARGET_NOT_ASKED = 3  # 指定されたキャラクターは、現在申し込みを受け付けていません。
REASON_SEND_ERROR = 4        # 未使用：：：送信エラーが発生しました。
REASON_BAD_CHARA = 5         # キャラクターの情報が不正です。
REASON_WRONG_MODE = 6        # 未使用：：：モードが異なる。
REASON_SELF = 7              # 自分自身に申し込むことはできません。
REASON_ALREADY_ASKED = 8     # 既に申し込んでいます。
REASON_NO_CHARA_DATA = 9     # キャラクターデータの取得に失敗しました。
REASON_NO_CHARA_INFO = 10    # キャラクター情報の取得に失敗しました。
REASON_BAD_PLACE = 11        # 指定されたキャラクターがいる場所ではツーショットチャットを行うことはできません。

# ---------------------------------------------------------------------------
# 0xFF04 -- 0x500A / 0x5203, and every other 申し込み subsystem's Notify. The
# list starts at 11 because 0..10 are what each subsystem's own list holds; this
# one is only the endings. See the module docstring for how the split was read.
# ---------------------------------------------------------------------------
NOTIFY_FAILED = 11     # 申し込みに失敗しました。
NOTIFY_DECLINED = 12   # 申し込みを断られました。
NOTIFY_CANCELLED = 13  # 申し込みがキャンセルされました。
NOTIFY_PARTNER_GONE = 14  # 相手がログアウトもしくはキャラクター選択画面に戻ったため、申し込みをキャンセルしました。
NOTIFY_END = 15        # 未使用：：：終了メッセージ
NOTIFY_OUT_OF_RANGE = 16  # 指定されたキャラクターが申し込み可能な範囲に存在しません。
NOTIFY_OTHER_ACCEPTED = 17  # １つの申し込みが承諾されましたので、他の申し込みはキャンセルしました。

# ---------------------------------------------------------------------------
# 0xFF00 -- 0x5402 / 0x5405, shared with every other chat channel's Error.
# ⭐ Row 9 names this family out loud, which is the third witness for the
# mapping: 「キャラクターの情報が不正です。ツーショットチャットを継続できません。」
# ---------------------------------------------------------------------------
CHAT_BAD_DATA = 1        # 受信したチャットデータが不正です。
CHAT_FORBIDDEN = 2       # 現在、チャットが禁止されています。
CHAT_NO_PARTNER = 3      # チャット相手が存在していません。
CHAT_REFUSED = 4         # 指定されたキャラクターは、現在受信を拒否しています。
CHAT_SEND_FAILED = 5     # チャットメッセージの送信に失敗しました。
CHAT_BAD_CHARA = 6       # キャラクターの情報が不正です。
CHAT_NO_CHARA_DATA = 7   # キャラクターデータの取得に失敗しました。
CHAT_NO_CHARA_INFO = 8   # キャラクター情報の取得に失敗しました。
CHAT_CANNOT_CONTINUE = 9  # キャラクターの情報が不正です。ツーショットチャットを継続できません。

#: 0x5004's ``reply``. Read as a byte rather than trusted as a message id, the
#: rule 勧誘 paid for in round 146 and trade.py restates: both buttons of a
#: confirmation box can send the Ok message and put the answer in the byte.
ANSWER_YES = 1

# ⭐⭐⭐ WHICH 感情 A WAIST-UP SCREEN CAN SHOW. The two tables answer it between
# them, and round 214 then MEASURED both ends of the answer on a real client.
#
# The 感情アイコンウィンドウ has 17 icons (`manual/p05_04` lists them;
# `cibi_emotion.bin` keys 1..17 are those same seventeen names in reverse order),
# and the manual says a twoshot turns the icon into 「感情に応じた表情変化」. The
# faces live in `wu_emotion.bin` -- whose keys run **0..10** and then jump
# straight to 24. That gap is exactly the seven icons with no face: 11 疑問,
# 12 ひらめき, 13 かがやき, 14 沈黙, 15 グー, 16 チョキ, 17 パー. Nine of the ten
# that remain carry the identical name in both tables (笑う, 恥ずかしい, ときめき,
# 怒る, 悲しい, 泣く, 驚く, 呆れる, 困る) and the tenth is a synonym (cibi 楽しい /
# wu 微笑む). Fn on the keyboard casts emotionId n -- F4 measured, 「ときめき」,
# and the portrait blushed.
#
# ⚠️⚠️ 0 IS IN THE RANGE AND THAT IS THE PART THAT WAS MEASURED THE HARD WAY.
# The first draft wrote range(1, 11) -- reasoning about the icon window, where
# there is no 0 -- and 25 smoke assertions were green. The real client then sent
# **0x5403 with emotionId 0 every ten seconds, all by itself**: it is how the
# face goes back to 通常 after an expression, not a button anybody presses. Every
# one of those got a refusal, and the client put 「受信したチャットデータが不正
# です」 on screen in a box titled 「ツーショットチャットエラー」. `wu_emotion` had
# said so all along -- its key 0 is 表情デフォルト / 表情普通.
#
# ⭐⭐⭐ AND THE OTHER END IS WHY THE CHECK EXISTS AT ALL: 0x5404 carrying a
# faceless emotion **crashes the client**. Round 214 pushed `/raw 5404
# 08000000000f` (グー) by hand and tmo.exe died on the spot -- 0xc0000005 at RVA
# 0x003944dc, which is `mov eax,[eax+4]` one instruction after `mov eax,[esi+8]`,
# i.e. a null from a table fetch dereferenced immediately. Same shape as the
# three crashes item.py records for keys `item.bin` does not have.
#
# ⭐ So the refusal for 11..17 is protective rather than pedantic -- and in
# ordinary play it is unreachable anyway: pressing F11 (疑問) inside a twoshot
# sends nothing at all, so the client gates those seven itself.
EMOTION_WITH_FACE = range(0, 11)


def reason(code: int) -> bytes:
    """One refusal byte. The client's reader is read-int8, i.e. signed, and
    every code used here is far below 128, so none of them wraps."""
    return struct.pack(">B", code & 0xFF)


def parse_target(params: bytes) -> int:
    """0x5000's one u32. 0 for a body too short to hold one."""
    if len(params) < 4:
        return 0
    return struct.unpack_from(">I", params, 0)[0]


def parse_answer(params: bytes) -> int:
    """0x5004/0x5005's one u8."""
    return params[0] if params else 0


def parse_emotion(params: bytes) -> int:
    """0x5403's one u16. 0 for a body too short, which is 通常 and not an icon."""
    if len(params) < 2:
        return 0
    return struct.unpack_from(">H", params, 0)[0]


def response_params(chara_id: int) -> bytes:
    """0x5003's u32: whom this application is from.

    ⚠️ The field is ``senderId`` in the original's own dump, which is the same
    wire position トレード's 0x5103 calls ``targetId``. Same message, opposite
    name; the position is the judge and this end sends the asker either way.
    """
    return struct.pack(">I", chara_id)


def start_params(place_id: int) -> bytes:
    """0x5006's u16 ``placeId``.

    One u16 and nothing else: deserializer 0x8DB8E0 makes a single call through
    the stream's ``vt+0x28`` slot, which the read-slot table
    names uint16, and stores it at the object's +4.
    """
    return struct.pack(">H", place_id & 0xFFFF)
