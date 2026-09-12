"""The two refusal lists the client shares between families, read out of its own
message-id -> table function.

A refusal byte on this protocol is an index, not a code: the client looks the
sentence up in error_message.bin under a (id, reason) key, and the id it uses is
not always the message's own. FUN_008163e9 takes a message id and returns a
pseudo id, returning its input unchanged when there is no redirect; its only
caller (0x817048) builds the key from the answer. Round 214 read that function
out of the image -- 57 redirects -- and two of the eight pseudo ids it names are
shared by more than one subsystem:

    0xFF04   every 申し込み subsystem's Notify*Cancel / Notify*End
             (0x500A 0x510D 0x510E 0x5203 0x6217 0x6222 0x640D 0x6807 0x680B)
    0xFF07   仲良しグループ / 同好会's whole family (0x62xx, eleven messages)
             **and 友達登録's two refusals** (0x6405 0x640C)

Both are here rather than in one family's module because neither belongs to one.
The per-family lists stay where their family is: 0xFF09 in trade.py, 0xFF05 in
twoshot.py, 0x0311's and 0x6410's own rows beside the code that sends them.

⭐⭐⭐ THAT THE CLIENT REALLY READS THIS BACK IS MEASURED, not argued. Round 213
sent 0x5116 with reason 21 by accident and the client put 0xFF09's row 21 on
screen word for word. Round 214 then read the redirect function, which is what
turned 「which list」 from a guess into a reading. Round 323 added the second
on-screen witness, this time out of 0xFF07: a 0x621D with reason 8 puts
「既に申し込んでいます。」 on screen, row 8 word for word.

⚠️⚠️ AND THAT SAME ROUND FOUND THE OTHER HALF DOES NOT WORK THAT WAY. The
Notify*Cancel side -- the 0xFF04 list below -- is NOT looked up in
error_message.bin by the families that were watched doing it: a 0x6222 with
reason 12 draws a box the client owns, worded 「仲良しグループへの登録を拒否され
ました」, a sentence that appears nowhere in error_message.bin. The byte is still
read, and it still decides what happens -- same box, same state, only the byte
changed: 12 draws that box, 13 closes the waiting box silently -- so it is a
BRANCH NUMBER there rather than a row index. The names and numbering below are
the ones to send either way (they are what the original's own list calls these
endings), but do not promise that a particular sentence reaches the screen
without watching it arrive.

⚠️ Slots the original marked 未使用 are named and kept rather than dropped:
dropping one would renumber the rest. They are the developers' own 「nothing to
say here」 -- 0xFF04's row 15 is 「未使用：：：終了メッセージ」 and goes out on
every clean ツーショット ending, which is a normal end with no sentence to put on
screen rather than a hole in the list.

⚠️ The client's reader for these is read-int8, i.e. **signed**. Every code below
is far under 128, so none of them arrives negative.
"""

from __future__ import annotations

import struct

# ---------------------------------------------------------------------------
# 0xFF04 -- 「the application you were part of is over, and here is why」. Seven
# rows, 11..17, and no row 0: a Notify sent with a placeholder zero puts nothing
# at all on screen, which is exactly what round 213 watched a disconnected
# トレード partner's window do.
# ---------------------------------------------------------------------------
NOTIFY_FAILED = 11          # 申し込みに失敗しました。
NOTIFY_DECLINED = 12        # 申し込みを断られました。
NOTIFY_CANCELLED = 13       # 申し込みがキャンセルされました。
NOTIFY_PARTNER_GONE = 14    # 相手がログアウトもしくはキャラクター選択画面に戻ったため、申し込みをキャンセルしました。
NOTIFY_END = 15             # 未使用：：：終了メッセージ
NOTIFY_OUT_OF_RANGE = 16    # 指定されたキャラクターが申し込み可能な範囲に存在しません。
NOTIFY_OTHER_ACCEPTED = 17  # １つの申し込みが承諾されましたので、他の申し込みはキャンセルしました。

# ---------------------------------------------------------------------------
# 0xFF07 -- the group family's list, 32 rows, and 友達登録's two refusals are
# looked up in it as well. ⚠️ THAT IS NOT A TYPO IN THE IMAGE: error_message.bin
# also ships 0xFF08, whose rows say 友達登録 out loud (「友達登録の申し込みに失敗
# しました」), and nothing in the whole image produces that id. Every 友達登録
# refusal the original ever showed came out of the list below, group wording and
# all, so this end's job is to pick the row that is *true* rather than the row
# whose wording fits best -- seven of the thirty-two say nothing about groups.
#
# ⚠️ Row 0 is 「未使用：：：エラーなし」. Unlike 0xFF04 the row exists, so a
# placeholder zero here is not silence -- it is the original's own dead-slot text
# where a sentence belongs.
# ---------------------------------------------------------------------------
NG_NONE = 0                  # 未使用：：：エラーなし
NG_TARGET_BUSY = 1           # 指定されたキャラクターは、現在申し込みを受けられる状態ではありません。
NG_REQUEST_FAILED = 2        # 仲良しグループもしくは同好会のメンバー登録の申し込みに失敗しました。
NG_TARGET_NOT_ACCEPTING = 3  # 指定されたキャラクターは、現在申し込みを受け付けていません。
NG_SEND_ERROR = 4            # 未使用：：：送信エラーが発生しました。
NG_BAD_CHARA = 5             # キャラクターの情報が不正です。
NG_WRONG_MODE = 6            # 未使用：：：モードが異なる。
NG_SELF = 7                  # 自分自身に申し込むことはできません。
NG_ALREADY_ASKED = 8         # 既に申し込んでいます。
NG_NO_CHARA_DATA = 9         # キャラクターデータの取得に失敗しました。
NG_NO_CHARA_INFO = 10        # キャラクター情報の取得に失敗しました。
NG_BAD_GROUP = 11            # 仲良しグループもしくは同好会の情報が不正です。
NG_NOT_LEADER_RANK = 12      # 仲良しグループのリーダーになる資格をまだ持っていません。
NG_NOT_LEADER = 13           # 仲良しグループもしくは同好会のリーダー権限を持っていません。
NG_CREATION_FORBIDDEN = 14   # 現在、仲良しグル－プの作成が禁止されています。
NG_NO_GROUP = 15             # 仲良しグループもしくは同好会に所属していません。
NG_IN_ANOTHER_GROUP = 16     # 既に別の仲良しグループもしくは別の同好会に所属しています。
NG_ALREADY_IN_A_GROUP = 17   # 既に仲良しグループもしくは同好会に所属しています。
NG_GROUP_FULL = 18           # これ以上メンバーを増やすことはできません。
NG_NAME_MISSING = 19         # グループ名が指定されていません。
NG_NAME_TOO_LONG = 20        # グループ名の入力は最大２０バイト（全角１０文字分）までです。
NG_NAME_TAKEN = 21           # 入力されたグループ名は既に使用されています。
NG_NO_GROUP_INFO = 22        # 仲良しグループもしくは同好会の情報を取得できませんでした。
NG_CHARA_UPDATE_FAILED = 23  # キャラクター情報の変更に失敗しました。
NG_NO_MEMBER_LIST = 24       # 仲良しグループもしくは同好会のメンバー一覧を取得できませんでした。
NG_NO_LEADER_INFO = 25       # 仲良しグループもしくは同好会のリーダー情報を取得できませんでした。
NG_MEMBERS_REMAIN = 26       # 未使用：：：リーダー以外のメンバーが存在する
NG_CLUBLIKE_PUBLIC_REQUIRED = 27  # 同好会を非公開にはできません。（公開必須です）
NG_NO_LOBBY = 28             # 未使用：：：ロビー情報を受け取れない or イベント中
NG_NAME_FORBIDDEN = 29       # 入力されたグループ名に禁止語が含まれています。
NG_KICK_SELF = 30            # 自分自身を除名することはできません。
NG_INTERNAL = 31             # 通常ではありえないエラー：：：ＳＴＬ内部のエラー等


def byte(code: int) -> bytes:
    """One refusal byte, the only shape any of these ever goes out in."""
    return struct.pack(">B", code & 0xFF)
