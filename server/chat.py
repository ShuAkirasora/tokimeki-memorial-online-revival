"""The bottom chat bar: reading what was typed, and answering it.

Two messages, both read straight out of the client rather than guessed at:

``MsgClCastNormalChat`` (0x4900), deserializer 0x8E0590::

    u16 length            through the stream's +0x28 slot
    bytes utterance       `length` bytes copied verbatim by 0xA49610

``MsgSvNotifyNormalChat`` (0x4901), deserializer 0x8D6230, fields named by its
dump function 0x905D00::

    u32 senderId
    u16 nameLen,      bytes name
    u16 utteranceLen, bytes utterance

**Neither string is bounds-checked on the way in.** The reader does
``movzx eax, word ptr [ebx]; push eax`` and hands that length to the copier, so
the count on the wire lands in a fixed buffer with nothing between them: the
name goes to obj+0x08 with the length field itself at obj+0x1E, and the
utterance to obj+0x20 with its length at obj+0x7E. That makes the buffers 22
and 94 bytes, and makes clamping the server's job. Hence NAME_MAX/TEXT_MAX
below, and hence `clip`, which cuts by character before encoding so a
double-byte pair is never halved — the same care ``marker_names`` takes, for
the same reason.

Chat is also the only free-text channel a player has, so it doubles as this
server's console. ``/go``, ``/pos`` and ``/maps`` are ours, not the game's;
they exist because the round that read every map's collision file left us
knowing a standable cell on all 78 maps and no way to ask for one. Anything not
starting with ``/`` is only echoed back, which is what a real server would do
anyway — the speaker sees their own line arrive as a broadcast.

The client gets first refusal on the name, though: it keeps a command table of
its own and swallows what it recognises, so ``/where`` and ``/help`` never
reach the wire at all. Unrecognised words come through with the slash intact,
which is why ours are named the way they are. See CLIENT_RESERVED.
"""

from __future__ import annotations

import struct
from datetime import timedelta
from typing import NamedTuple

import ability
import curriculum
import facing
import lesson
import mapgraph
import quiz
import romance
import script

# Capacities of the client's own receive buffers; see the module docstring.
NAME_MAX = 22
TEXT_MAX = 94

# Chat is a broadcast, so the reply names its speaker. The server has no
# character of its own to speak as, and inventing a charaId would have the
# client asking MsgClQueryCharaInfo about somebody who does not exist, so
# server lines come from the player's own id and are told apart by the name.
SERVER_NAME = "サーバ"

PREFIX = "/"

# The direction to arrive facing: towards the camera, which is what stepping out
# of a doorway ought to look like. This used to be 0 — "the value we have watched
# the client accept" — from before the /dirs ruler showed 0 sets no direction bit
# at all. The map files' 2/4/6/8 belong to a different field; see
# mapgraph.landing, and see facing.py for what this one's bits mean.
ARRIVAL_DIRECTION = facing.DEFAULT

# Words the client's own chat bar takes before anything reaches the wire: it
# handles them itself and nothing is forwarded, so a command of ours by any of
# these names is dead code. Not a guess and not a survey — this is the game's
# own list, reference/idlist/command_explain.txt, the 69 lines the client prints
# for `/command`. Two of them were met the expensive way first: `/where` (立ち位置
# 座標の表示) and `/help` (操作説明ウィンドウの開閉) both vanished on the way out.
# Check a new command name against this before naming it.
CLIENT_RESERVED = (
    "menu", "log", "emotion", "status", "club", "drama", "item", "board",
    "address", "group", "navi", "help", "option", "quit",
    "secretchat", "friendchat", "groupchat", "twoshotchat",
    "ignore", "refer",
    "balloon", "name", "mspeed", "study", "test", "record", "history",
    "boldword", "iconformat", "optionformat",
    "bgm", "bgmoff", "env", "envoff", "se", "seoff", "system", "systemoff",
    "soundformat", "messagekey", "messagekeyformat",
    "online", "localtime", "where", "random", "command",
)


def clip(text: str, limit: int) -> bytes:
    """Encode to Shift-JIS, dropping whole characters until it fits.

    Truncating the bytes instead would leave a half-encoded character at the
    end, which the client draws as garbage.
    """
    for end in range(len(text), -1, -1):
        raw = text[:end].encode("cp932", "replace")
        if len(raw) <= limit:
            return raw
    return b""


def parse_cast(params: bytes) -> str:
    """The line the player typed, out of a MsgClCastNormalChat body.

    The count on the wire includes the C terminator — `テスト` arrives as five
    bytes ending in NUL — so the string has to be cut at the first NUL rather
    than trusted whole. Leaving it on cost a round: ``str.strip()`` does not
    treat NUL as whitespace, so ``/go 食堂`` searched the map table for
    ``"食堂\\x00"`` and found nothing.
    """
    if len(params) < 2:
        return ""
    (length,) = struct.unpack_from(">H", params, 0)
    raw = params[2 : 2 + length].split(b"\x00", 1)[0]
    return raw.decode("cp932", "replace")


def notify_params(sender_id: int, name: str, text: str) -> bytes:
    """A MsgSvNotifyNormalChat body, clamped to what the client can hold.

    Both strings carry their terminator, the way the client's own casts do
    (`/xyzzy` goes out as ``utterance[7]``, seven bytes for six characters).
    The copier writes exactly the counted bytes and adds nothing, while the
    chat window draws the buffer as a C string, so a count that stops short of
    the NUL leaves whatever the previous, longer line put there hanging off the
    end — which is what a stray `・」` after a six-character line turned out to
    be. Room for the terminator comes out of the buffer, hence the -1.
    """
    name_raw = clip(name, NAME_MAX - 1) + b"\x00"
    text_raw = clip(text, TEXT_MAX - 1) + b"\x00"
    return (
        struct.pack(">IH", sender_id, len(name_raw))
        + name_raw
        + struct.pack(">H", len(text_raw))
        + text_raw
    )


HELP = (
    "/go <地図名|番号> [x y] 移動",
    "/pos 現在地",
    "/maps <名前> 検索",
    "/dirs 方向の目盛りを置く",
    "/npc <cat>:<id> <cat>:<id> NPC制御 (2つめが台本キー)",
    "/npca 登場済みの恋愛候補生を配置 / <始> <終> [分類] で生キー",
    "/rom [名前] [debut|talk|ev|p <n>] 恋愛の状態を見る・動かす",
    "/card [ruler|clear|<科目> <出席> <成績> <課程> <点>] 通知表",
    "/ab [ruler|clear|p <値×6>|club <番号> <lv> <gauge>|<能力>|徳|ストレス|体調|日数 <値>] 能力パラメータ",
    "/jikan [日|月|…|0-6] 時間割 (サーバ側の並べ方)",
    "/lopt [seats|speech|words] <数> 0x6100 の実験用つまみ",
    "/bell [<科目番号>|ready] 予鈴/本鈴を手で鳴らす",
    "/quiz [sec <秒>|wait <秒>] 出題の状態と正解 (採点の検証用)",
    "/npcx 補充をやめる (画面上の分は地図を跨ぐまで残る)",
    "/nev [<cat>:<id>] 会話イベントキー (既定 16:1)",
    "/sc <名前|scriptId> [ctrl] [actor:npcId] 台本開始",
    "/scn 次の命令へ  /sce 台本終了  /scl 一覧",
    "/sel [<select> [timer]] 選択肢を問い直す (無引数で既定に戻す)",
    "/de [<genre>:<番号>|un007 …] ドラマ一覧通知",
    "/dms マッチング画面を開かせる (0xe002+0xe003+0xe004)",
)

# MsgSvNotifyNpcControl — the message that puts a chibi NPC on the map.
# Deserialiser 0x908980 reads four u16 into obj+4/+6/+8/+0xa and stops; the dump
# at 0x908810 calls them npcId{categoryId, id} and eventId{categoryId, id}. There
# is no coordinate anywhere in it because there does not need to be: the client's
# handler (0x7722F8) drops eventId — the u32 at obj+8 — into the ちびキャラ
# spawner's queue, and the spawner looks it up in cibi_control_script, whose
# record names a placement script (MAP_CHARA_POSITION / _DIRECTION / _DISP_ON).
# The position is in the script, not in the message.
#
# ⚠️ What that same comment used to say — "npcId is not read at all" — is wrong,
# and it cost a round to find out. Measured 2026-08-02, one key (4:112 桜井),
# two pushes, the player standing 18 cells off for both so visibility was not the
# variable: npcId 0:0 put nobody on the map, npcId 1:0 put 桜井 on his script's
# square. eventId still picks *who* — the body that appeared was 4:112's and not
# {1,0}'s — so the enqueue does take eventId; npcId is read by something earlier
# that a zero does not get past. Which check that is has not been traced, so
# treat 1:0 as the value known to work rather than as an understood one.
MSG_SV_NOTIFY_NPC_CONTROL = 0x6300

# The whole ちびキャラ cast, as a range rather than a table. `cibi_control_script`
# is keyed {4, 0..222} with no gaps, and — this is the part that keeps the
# content catalogue out of server/ — the *placement* is not ours to know: each
# key names a script of the client's own that does MAP_CHARA_POSITION /
# _DIRECTION / _DISP_ON. So "put everybody out" is 223 sends of four u16 and not
# one byte of reference/. The map id lives in that script too, which is why this
# does not and cannot filter by where the player is standing: spawns are
# remembered per session and re-pushed on every lobby load, so one /npca
# populates every map the player later walks into, not just the current one.
# The cast, the placement rule and the state behind them all live in
# romance.py — the whole of 恋愛 in one file, so that what is reconstruction and
# what is invented can be told apart in one reading. Keys 4:0–4:178 are those
# five and nobody else; 4:179–4:222 are teachers and staff, and not one of those
# 44 scripts has a MAP_CHARA_DISP_ON, so NpcControl can only ever put these five
# on a map.
#
# ⭐ No coordinate and no map id belongs anywhere in server/, because neither is
# ours to hold: the key names a script *of the client's*, and that script carries
# the position and the map. 0x6300 is four u16 and the server only ever picks a
# number.
CIBI_EVENT_CATEGORY = romance.CIBI_EVENT_CATEGORY
CIBI_SCRIPT_COUNT = romance.CIBI_SCRIPT_COUNT

# The npcId every batched push carries: not zero (see above), and the same one
# for all 223 because two chibis sharing it were already seen standing on the
# map together in round 37 — 4:0 and 4:112 at once — so it is not a slot that
# they would evict each other from.
CIBI_NPC_ID = (1, 0)


def parse_id_pair(word: str) -> tuple[int, int] | None:
    """``"1:0"`` -> ``(1, 0)``. Both halves must be there; ids are per-category."""
    category, sep, ident = word.partition(":")
    if not sep or not category.isdigit() or not ident.isdigit():
        return None
    values = (int(category), int(ident))
    return values if all(0 <= v <= 0xFFFF for v in values) else None

# One stand-in per direction value, laid out as a grid so a single screenshot
# answers what the whole field means. The alternative — send one value, look,
# send the next — is a login apiece, and that is how three rounds were spent on
# the coordinate scale before somebody put all the candidates on screen at once.
DIRECTION_PROBE_COUNT = 16
DIRECTION_PROBE_COLS = 4
DIRECTION_PROBE_STEP = 3  # cells between neighbours; adjacent ones overlap


def direction_probes(
    map_id: int, pos: tuple[int, int]
) -> list[tuple[str, int, int, int]]:
    """``(label, x, y, direction)`` for the grid, kept inside the map."""
    rows = -(-DIRECTION_PROBE_COUNT // DIRECTION_PROBE_COLS)
    span_x = DIRECTION_PROBE_COLS * DIRECTION_PROBE_STEP
    span_y = rows * DIRECTION_PROBE_STEP
    width, height = mapgraph.size(map_id) or (span_x, span_y)
    # Shifted whole rather than clamped per cell: clamping would stack the
    # outermost stand-ins on one another, and two labels on one square is
    # exactly the ambiguity the grid exists to avoid.
    left = min(max(pos[0] - span_x // 2, 0), max(width - span_x, 0))
    # The extra row keeps the grid off the player's own cell: centred exactly, a
    # stand-in would share a square with the player, and two sprites with two
    # labels on one square is the reading the ruler can least afford to get wrong.
    top = min(max(pos[1] - span_y // 2 + 1, 0), max(height - span_y, 0))
    probes = []
    for value in range(DIRECTION_PROBE_COUNT):
        column, row = value % DIRECTION_PROBE_COLS, value // DIRECTION_PROBE_COLS
        probes.append(
            (
                str(value),
                min(left + column * DIRECTION_PROBE_STEP, width - 1),
                min(top + row * DIRECTION_PROBE_STEP, height - 1),
                value,
            )
        )
    return probes


class ScriptAction(NamedTuple):
    """A request to the session's script runner; see script.py for the protocol.

    ``ctrl`` and ``npc_infos`` are arguments rather than constants because
    neither is understood yet and each wrong guess otherwise costs a full client
    run — this way one login can try several. Defaults are the cheapest
    hypothesis: ctrl 0, and no cast override at all on the grounds that the
    ``.ssb`` already declares its own.
    """

    kind: str                                    # "start" | "next" | "end"
    name: str = ""
    ctrl: int = 0
    npc_infos: list[tuple[int, int]] = []


class Reply(NamedTuple):
    """What one chat line asks the server to do.

    Everything is described rather than sent, so that every wire write stays in
    the one place that owns the session.
    """

    lines: list[str] = []
    warp: tuple[int, int, int, int] | None = None  # MsgSvNotifyGMWarp's shape
    probes: list[tuple[str, int, int, int]] = []
    script: ScriptAction | None = None
    # A new capture_npc_event key for this session; see /nev.
    npc_event: tuple[int, int] | None = None
    # Forget the remembered ちびキャラ pushes, so the lobby stops re-sending
    # them; see /npcx.
    npc_clear: bool = False
    # `(select, timerCount)` for MsgSvQueryScriptCommandSelect, or (-1, -1) to
    # go back to letting the script's own option count decide; see /sel.
    select: tuple[int, int] | None = None
    # Ready-made (msg_type, params) pairs for pushes with no session state
    # behind them. A warp has to be described rather than sent because the
    # session's map and position must be written first; these need nothing, so
    # they travel already packed.
    sends: list[tuple[int, bytes]] = []
    # The 恋愛 state was changed in place and should be written back; see /rom.
    romance_save: bool = False
    # Same, for the 通知表; see /card.
    scorecard_save: bool = False
    # Same, for the 能力パラメータ sheet; see /ab.
    ability_save: bool = False


def respond(
    text: str,
    map_id: int,
    pos: tuple[int, int],
    love: "romance.Romance | None" = None,
    card: "curriculum.ScoreCard | None" = None,
    period: "lesson.Lesson | None" = None,
    sheet: "ability.AbilitySheet | None" = None,
) -> Reply:
    """Answer one chat line.

    ``love`` is the speaking character's 恋愛 state, mutated in place when a
    command changes it — the session owns the file, so writing is asked for
    through ``Reply.romance_save`` the same way every other side effect is.
    ``card`` is the same arrangement for the 通知表 and ``sheet`` for the 能力
    パラメータ. ``period`` is the lesson in progress, read-only and only by
    /quiz.
    """
    # NULs are dropped here as well as in parse_cast: str.strip() does not count
    # one as whitespace, so a terminator that slips through turns an argument
    # into a word that matches nothing, silently and with no error to read.
    text = text.replace("\x00", "").strip()
    if not text.startswith(PREFIX):
        return Reply()
    word, _, rest = text[len(PREFIX) :].partition(" ")
    word, rest = word.lower(), rest.strip()

    if word in ("cmds", "help", "?", ""):
        return Reply(list(HELP))

    if word in ("pos", "where"):
        door = mapgraph.door_at(map_id, pos)
        where = f"{mapgraph.name(map_id)}({map_id}) {pos[0]},{pos[1]}"
        # The floor is reported for the cell the player is standing on, which is
        # the one cell where the answer is known in advance: they are on it. It
        # is here as a spot check on the collision file, not as information.
        floor = mapgraph.walkable(map_id, pos)
        if floor is False:
            where += " 床なし?!"
        return Reply([where + (f" 出入口{door}" if door else "")])

    if word == "maps":
        hits = mapgraph.search(rest)
        if not hits:
            return Reply([f"「{rest}」に一致する地図なし"])
        # One line per hit would be one packet per hit; a handful of ids on a
        # line reads better in a chat log that only keeps a few rows on screen.
        lines = [f"{map_id}:{name}" for map_id, name in hits[:12]]
        more = f" 他{len(hits) - 12}件" if len(hits) > 12 else ""
        return Reply([" ".join(lines) + more])

    if word == "dirs":
        probes = direction_probes(map_id, pos)
        return Reply([f"方向 0-{DIRECTION_PROBE_COUNT - 1} を並べた"], probes=probes)

    if word == "npc":
        # This is the command that puts a chibi NPC on the map, and the working
        # value is the *second* pair: the client's handler for this message
        # ignores npcId entirely and feeds eventId to the ちびキャラ spawner,
        # which reads it as a cibi_control_script key and runs the placement
        # script that record names. `/npc 1:0 4:0` is 天宮小百合 at (133,110) on
        # 屋外 by way of amm_s001.ssb; the 1:0 is along for the ride.
        #
        # Nothing here is validated against the id tables on purpose. server/
        # deliberately does not read reference/idlist/ (that dependency was cut
        # in round 22.5 so the public tree can ship without the game's content
        # catalogue). The categories live in the handoff; this end only checks
        # that two numbers arrived.
        words = rest.split()
        npc = parse_id_pair(words[0]) if words else None
        if npc is None:
            return Reply(["/npc <cat>:<id> <eventCat>:<eventId>  例: /npc 1:0 4:0"])
        event = parse_id_pair(words[1]) if len(words) > 1 else (0, 0)
        if event is None:
            return Reply([f"イベントidが読めない: {words[1]}"])
        return Reply(
            [f"NpcControl npc={npc[0]}:{npc[1]} event={event[0]}:{event[1]}"],
            sends=[
                (
                    MSG_SV_NOTIFY_NPC_CONTROL,
                    struct.pack(">HHHH", npc[0], npc[1], event[0], event[1]),
                )
            ],
        )

    if word == "npca":
        # Sent in one reply, in key order, because that is what makes a partial
        # result readable: the client's ちびキャラ spawner takes these into a
        # queue whose depth is not known from the disassembly, and if it holds
        # fewer than we send, the ones that come out are a prefix. Missing tail
        # = queue depth; missing scattered = something else. Batching or pacing
        # would blur exactly that reading, so it is deliberately absent — and
        # unlike MsgSvNotifyCharacterAdd there is no oversized-parameter hazard
        # to batch around, since each push is its own 8-byte message.
        words = rest.split()
        category = CIBI_EVENT_CATEGORY
        if len(words) < 2:
            # The useful form: whoever has appeared, each on the spot her own
            # story has reached. Not per-map — the map lives in the client's
            # script, so one push seats the whole campus and the player meets
            # whoever is on the map they walk into. Anything beyond one key per
            # person is not more people, it is the same people moved.
            #
            # ⭐ It is the *debuted* ones and not all five. 「その他のキャラクター
            # は、最初からは登場していません」, and p09_02 says the map characters
            # of candidates the player never met are not drawn at all. A fresh
            # male character therefore has exactly 天宮 on campus, and a female
            # one exactly 桜井 — which is also why those two share a square at
            # several spots: they are the same slot, not two people in it.
            if love is None:
                return Reply(["恋愛状態が読めない (キャラ未選択?)"])
            pairs = love.keys()
            if not pairs:
                return Reply(["登場している恋愛候補生がいない (/rom で確認)"])
            keys = [key for _, key in pairs]
            note = f"{len(keys)}人 " + " ".join(f"{who}={key}" for who, key in pairs)
        else:
            # The probe form, kept for keys the cast rule does not reach: 4:179
            # upwards, or some other category entirely. Nothing here consults
            # romance.CANDIDATES, so a range can still be swept blind.
            try:
                start = int(words[0], 0)
                end = int(words[1], 0)
                category = int(words[2], 0) if len(words) > 2 else CIBI_EVENT_CATEGORY
            except ValueError:
                return Reply(["/npca  または  /npca <始> <終> [分類]"])
            if not 0 <= start <= end <= 0xFFFF or not 0 <= category <= 0xFFFF:
                return Reply([f"範囲が読めない: {start}-{end} 分類{category}"])
            keys = list(range(start, end + 1))
            note = f"{category}:{start}-{end} ({len(keys)}体)"
        return Reply(
            [f"ちびキャラ {note}"],
            sends=[
                (
                    MSG_SV_NOTIFY_NPC_CONTROL,
                    struct.pack(">HHHH", *CIBI_NPC_ID, category, key),
                )
                for key in keys
            ],
        )

    if word == "rom":
        # The 恋愛 state, readable and pokeable. Every mutator here is a stand-in
        # for something the game did on its own — a drama event, a conversation,
        # a main event — and they exist because those triggers are not all wired
        # yet. `debut` in particular has no rule behind it at all: which drama
        # event introduces whom is in none of the tables we have.
        if love is None:
            return Reply(["恋愛状態が読めない (キャラ未選択?)"])
        words = rest.split()
        if not words:
            return Reply([love.line(name) for name in romance.CANDIDATES])
        name = words[0]
        if name not in romance.CANDIDATES:
            return Reply([f"「{name}」は恋愛候補生にない: "
                          + " ".join(romance.CANDIDATES)])
        if len(words) == 1:
            return Reply([love.line(name)])
        verb, args = words[1].lower(), words[2:]
        if verb == "debut":
            changed = love.debut(name)
        elif verb == "talk":
            changed, advanced = love.talk(name)
            if advanced:
                # Worth saying out loud: this is the moment she moves, and the
                # whole point of the intimacy counter is that it eventually does
                # something visible. /npca to see it.
                return Reply(
                    [f"日常会話 -> メインイベント! {love.line(name)} (/npca で反映)"],
                    romance_save=True,
                )
        elif verb == "ev":
            changed = love.see_main_event(name)
        elif verb == "p":
            try:
                changed = love.set_progress(name, int(args[0], 0)) if args else False
            except ValueError:
                return Reply(["/rom <名前> p <数>"])
        else:
            return Reply(["/rom [名前] [debut|talk|ev|p <n>]"])
        return Reply([love.line(name)], romance_save=changed)

    if word == "card":
        # The 通知表, readable and pokeable — the same arrangement as /rom and
        # for the same reason: nothing yet raises these numbers on its own, so
        # until 授業 and 試験 exist this is what puts values on the screen.
        #
        # ``ruler`` is the one that matters. A blank 通知表 is all zeros, and a
        # screen of zeros cannot tell "the client did not fill this in" apart
        # from "the client filled it in with 0" — lesson 8. The pattern below
        # makes every cell identifiable at a glance:
        #
        #   出席回数  11, 22, 33 … 88   unique per subject, and unlike any of
        #                              the 必要出席回数 (7/40/100/200/350)
        #   成績      1,2,3,4,5,1,2,3   walks the whole Ａ〜Ｅ scale, so the
        #                              screen says outright whether 5 is Ａ
        #   前回得点  1 … 24            one number per cell, in sheet order, so
        #                              a misplaced row is not merely visible but
        #                              says by how much. This is what caught the
        #                              off-by-one in testLv.
        #   最高得点  0 everywhere but 家庭科 段階１, which gets 91 and thereby
        #                              clears all three of that stage's
        #                              conditions (91≥70, Ｃ≥Ｃ, 88≥7) — the one
        #                              row that must come up 「済」, so the
        #                              修了状況 column can be read as well
        if card is None:
            return Reply(["通知表が読めない (キャラ未選択?)"])
        words = rest.split()
        if not words:
            return Reply(card.lines())
        verb = words[0].lower()
        if verb == "ruler":
            for index in range(len(curriculum.SUBJECTS)):
                card.attendance[index] = 11 * (index + 1)
                card.estimation[index] = index % curriculum.ESTIMATION_MAX + 1
                for course in range(curriculum.COURSES):
                    card.scores[index][course] = (
                        index * curriculum.COURSES + course + 1,
                        0,
                    )
            last, _ = card.scores[len(curriculum.SUBJECTS) - 1][0]
            card.scores[len(curriculum.SUBJECTS) - 1][0] = (last, 91)
            return Reply(["目盛りを入れた"] + card.lines(), scorecard_save=True)
        if verb == "clear":
            blank = curriculum.ScoreCard()
            card.attendance[:] = blank.attendance
            card.estimation[:] = blank.estimation
            card.scores[:] = blank.scores
            card.asked[:] = blank.asked
            card.right[:] = blank.right
            return Reply(["通知表を白紙に戻した"], scorecard_save=True)
        subject = None
        if verb in [name.lower() for name in curriculum.SUBJECTS]:
            subject = [name.lower() for name in curriculum.SUBJECTS].index(verb)
        elif verb.isdigit() and int(verb) < len(curriculum.SUBJECTS):
            subject = int(verb)
        if subject is None:
            return Reply([
                "/card [ruler|clear|<科目> <出席> <成績> [課程 点]]",
                "科目: " + " ".join(curriculum.SUBJECTS),
            ])
        try:
            numbers = [int(value, 0) for value in words[1:]]
        except ValueError:
            return Reply(["/card <科目> <出席> <成績> [課程 点]"])
        if len(numbers) >= 1:
            card.attendance[subject] = max(0, numbers[0])
        if len(numbers) >= 2 and not card.set_estimation(subject, numbers[1]):
            return Reply([f"成績は {curriculum.ESTIMATION_MIN}〜"
                          f"{curriculum.ESTIMATION_MAX} (Ｅ〜Ａ)"])
        if len(numbers) >= 4:
            course = numbers[2] - 1  # 課程 is 1-based on screen and on the wire
            if not 0 <= course < curriculum.COURSES:
                return Reply([f"課程は 1〜{curriculum.COURSES}"])
            card.record_exam(subject, course, numbers[3])
        return Reply(card.lines(), scorecard_save=True)

    if word == "ab":
        # 能力パラメータ, readable and pokeable — the same arrangement as /card
        # and for the same reason. Nothing in this server raises an ability, so
        # until 授業's 能力増減 is settled this is the only thing that puts a
        # number on that screen.
        #
        # ``ruler`` is the one that matters: powers of two across the six, so a
        # single screenshot says which 能力 the client draws in which row.
        # AbilitySheet.ruler documents the whole pattern and why each value was
        # chosen.
        #
        # ⚠️ Values above 10000 do not draw what they mean — see ability.py for
        # where the display leaves the ceil(値/250) rule and what it does
        # instead. Nothing here clamps them, because the way that was found was
        # by sending them.
        if sheet is None:
            return Reply(["能力が読めない (キャラ未選択?)"])
        words = rest.split()
        if not words:
            return Reply(sheet.lines())
        verb = words[0].lower()
        if verb == "ruler":
            sheet.ruler()
            return Reply(["目盛りを入れた"] + sheet.lines(), ability_save=True)
        if verb == "clear":
            sheet.clear()
            return Reply(["能力を白紙に戻した"], ability_save=True)
        # Batch forms, because every one of these is typed by hand into the
        # game's own chat line: `p` takes the six 能力 positionally and `club`
        # takes one club's pair. Reading the screen means putting a whole row
        # of values up at once, and one message beats six chances to mistype.
        if verb in ("p", "params"):
            try:
                values = [int(word, 0) for word in words[1:]]
            except ValueError:
                return Reply(["/ab p <文系> <理系> … 最大 6 個"])
            for index, value in enumerate(values[: len(ability.ABILITIES)]):
                sheet.params[index] = max(0, value)
            return Reply(sheet.lines(), ability_save=True)
        if verb in ("club", "部活"):
            try:
                index, level, gauge = (int(word, 0) for word in words[1:4])
            except ValueError:
                return Reply(["/ab club <番号 0-15> <level> <gauge>"])
            if not 0 <= index < ability.CLUBS:
                return Reply([f"部活番号は 0-{ability.CLUBS - 1}"])
            sheet.club_level[index] = max(0, level)
            sheet.club_gauge[index] = max(0, gauge)
            return Reply(sheet.lines(), ability_save=True)
        # 徳/ストレス/体調/経過日数 are keyed by name because they are one of a
        # kind; the six 能力 are keyed by name *or* index, like /card's 科目.
        scalars = {
            "徳": "virtue",
            "virtue": "virtue",
            "ストレス": "stress",
            "stress": "stress",
            "体調": "condition",
            "condition": "condition",
            "日数": "elapsed_days",
            "days": "elapsed_days",
        }
        if len(words) < 2:
            return Reply([
                "/ab [ruler|clear|p <値×6>|club <番号> <lv> <gauge>|<能力>|徳|ストレス|体調|日数 <値>]",
                "能力: " + " ".join(ability.ABILITIES),
            ])
        try:
            value = int(words[1], 0)
        except ValueError:
            return Reply(["/ab <能力|徳|ストレス|体調|日数> <値>"])
        if verb in scalars:
            setattr(sheet, scalars[verb], value)
            return Reply(sheet.lines(), ability_save=True)
        index = None
        if words[0] in ability.ABILITIES:
            index = ability.ABILITIES.index(words[0])
        elif verb.isdigit() and int(verb) < len(ability.ABILITIES):
            index = int(verb)
        if index is None:
            return Reply([
                "/ab [ruler|clear|p <値×6>|club <番号> <lv> <gauge>|<能力>|徳|ストレス|体調|日数 <値>]",
                "能力: " + " ".join(ability.ABILITIES),
            ])
        sheet.params[index] = max(0, value)
        return Reply(sheet.lines(), ability_save=True)

    if word == "jikan":
        # The server's own reading of the 時間割, printed so it can be held up
        # against the client's 「生徒情報」→「時間割」 tab in the same session.
        #
        # Which cells are drawn is settled — `class_schedule.bin` gives all
        # fifty-six and TIMETABLE is a byte-for-byte copy. What is *not* settled
        # is where the grid is pinned to the clock: the server sends only hour
        # and minuts, so the client lays the slots out from a rule of its own,
        # and curriculum.TIMETABLE_SLOT_ZERO is this end's guess at that rule.
        # If the times below and the times on the tab disagree, the tab wins.
        days = "日月火水木金土"
        argument = rest.strip()
        if not argument:
            day = curriculum.day_of_week()
        elif argument in days:
            day = days.index(argument)
        elif argument.isdigit() and int(argument) < len(days):
            day = int(argument)
        else:
            return Reply(["/jikan [日|月|火|水|木|金|土|0-6]"])
        _, _, hour, minute = curriculum.clock()
        begins, subject = curriculum.next_lesson()
        bell = begins - timedelta(minutes=curriculum.PRE_BELL_MINUTES)
        lines = [
            f"{days[curriculum.day_of_week()]}曜 {hour:02d}:{minute:02d}／"
            f"{curriculum.SUBJECTS[curriculum.current_subject()]}"
            f"（{curriculum.slot_index() + 1}時限目）",
            f"次は {begins:%H:%M} {curriculum.SUBJECTS[subject]}、予鈴 {bell:%H:%M}",
            f"― {days[day]}曜の時間割 ―",
        ]
        cells = curriculum.timetable_lines(day)
        half = len(cells) // 2
        lines.append("  ".join(cells[:half]))
        lines.append("  ".join(cells[half:]))
        return Reply(lines)

    if word == "bell":
        # Ring a bell out of turn, because waiting fifteen minutes to find out
        # whether the client reacts at all is not an experiment, it is a wait.
        #
        # It has already earned its keep twice. `/bell 0`, `/bell 1`, `/bell 2`
        # drew 「まもなく国語の授業が始まります」/「…数学…」/「…理科…」, which is
        # how 0x6005's field turned out to be the subjectId and not the kind of
        # bell its name suggests. `/bell ready` drew 「授業起動失敗」 — the client
        # entering 授業モード, asking with 0x6001, and being told no.
        #
        # Values outside 0…7 stay reachable on purpose: what the client does with
        # a subjectId it has no name for is a question about the client, and this
        # is the only thing that can ask it.
        argument = rest.strip().lower()
        if argument in ("ready", "hon", "本"):
            return Reply(
                ["本鈴 (0x6000 NotifyLessonReady) を鳴らした"],
                sends=[(lesson.MSG_SV_NOTIFY_LESSON_READY, b"")],
            )
        try:
            subject = int(argument, 0) if argument else curriculum.current_subject()
        except ValueError:
            return Reply(["/bell [<科目番号>|ready]"])
        if not 0 <= subject <= 0xFFFF:
            return Reply(["科目番号は 0〜65535 (u16)"])
        name = (
            curriculum.SUBJECTS[subject]
            if subject < len(curriculum.SUBJECTS)
            else "?"
        )
        return Reply(
            [f"予鈴 (0x6005 BeforeLessonStart) subjectId={subject} {name} を鳴らした"],
            sends=[(
                lesson.MSG_SV_NOTIFY_BEFORE_LESSON_START,
                lesson.before_lesson_start_params(subject),
            )],
        )

    if word == "quiz":
        # ⭐ Why this exists: the questions are in the client and the answer key
        # is on the server, so neither side alone can tell whether marking works.
        # A tester reads the question off the screen, asks here which choice the
        # server will accept, clicks that one, and sees whether the client draws
        # ○. Without it, an inverted ○×-to-choiceId mapping or a wrong reading of
        # 0x6105's choiceId looks exactly like a lesson working — the ○ and × on
        # screen are drawn from what the server said, so they always agree with it.
        #
        # That it also hands out answers is not a problem worth solving. This is
        # a single-player server on the player's own machine and /go teleports
        # anywhere; a chat command is not where cheating gets interesting.
        words_in = rest.split()
        if words_in and words_in[0].lower() == "sec":
            try:
                lesson.ANSWER_SECONDS = max(1, int(words_in[1], 0))
            except (IndexError, ValueError):
                return Reply(["/quiz sec <秒>"])
            return Reply([f"残り時間 {lesson.ANSWER_SECONDS} 秒"])
        if words_in and words_in[0].lower() == "wait":
            try:
                lesson.GRADING_SECONDS = max(0, int(words_in[1], 0))
            except (IndexError, ValueError):
                return Reply(["/quiz wait <秒>"])
            return Reply([f"評価 {lesson.GRADING_SECONDS} 秒"])
        out = []
        if not quiz.loaded():
            out.append("問題データが読めていない (reference/quizkeys.json)")
        if period is None:
            subject = curriculum.current_subject()
            pairs = quiz.available(subject)
            out.append(f"授業中ではない。{curriculum.SUBJECTS[subject]}: "
                       + ", ".join(f"{'○×' if t == 0 else '４択'}L{v}"
                                   f"×{quiz.count(subject, t, v)}" for t, v in pairs))
        else:
            question = period.question
            out.append(f"{curriculum.SUBJECTS[period.subject]} "
                       f"{period.question_no}/{lesson.QUESTIONS_PER_LESSON}問目, "
                       f"{period.phase}, ここまで {period.summary()}")
            if question is not None:
                # What a correct answer *reports*, which is the number judge()
                # is handed and therefore the only one worth printing under
                # that name. For 4択 that is raw 0 — the client reports the
                # value out of choiceId[], not the slot it was drawn in — and
                # for ○× it is 1 for ○, 0 for ×.
                #
                # ⚠️ Both halves of this were wrong until 2026-08-05 and in the
                # same way: they were the readings judge() was corrected away
                # from in round 51, left behind here because a debug command
                # mirrors the rule instead of calling it. The smoke suite
                # answers with this number, so the two disagreeing showed up as
                # 「全部正解のはずが 2/10」 and not as anything about /quiz.
                # Where a mirror is unavoidable, print both sides — hence 番目.
                right = (
                    0
                    if question.quiz_type == quiz.TYPE_CHOICE
                    else int(bool(question.answer))
                )
                where = (
                    f"{question.choice_ids.index(0)} 番目をクリック"
                    if question.quiz_type == quiz.TYPE_CHOICE
                    else ("○ をクリック" if question.answer else "× をクリック")
                )
                out.append(
                    f"{'○×' if question.quiz_type == 0 else '４択'} "
                    f"難易度{question.level + 1} quizId={question.quiz_id}, "
                    f"choiceId={question.choice_ids}, 正解は choiceId {right}"
                    f"（{where}）"
                )
        out.append(f"/quiz [sec <秒>|wait <秒>] — 今 {lesson.ANSWER_SECONDS}"
                   f"/{lesson.GRADING_SECONDS} 秒")
        return Reply(out)

    if word == "lopt":
        # Knobs for the 0x6100 probe. They live on the server because the packet
        # under test kills the client: a constant in the source would need a
        # server restart for every value, and the client needs restarting anyway,
        # so the setting is the thing that ought to survive.
        #
        #   seats     how many seatInfo entries. 0 isolates the header.
        #   speech    speechEndTime's offset in ms. Ten minutes proved the crash
        #             is not the speech running out — it happened just the same.
        #   words     startWordsId, or -1 for the subject's own 開始台詞.
        words_in = rest.split()
        if len(words_in) >= 2:
            key = words_in[0].lower()
            key = {"speech": "speech_ms", "seat": "seats"}.get(key, key)
            if key not in lesson.PROBE:
                return Reply(["/lopt " + " ".join(sorted(lesson.PROBE))])
            try:
                lesson.PROBE[key] = int(words_in[1], 0)
            except ValueError:
                return Reply([f"/lopt {key} <数>"])
        return Reply([
            "0x6100: " + ", ".join(f"{k}={v}" for k, v in sorted(lesson.PROBE.items()))
        ])

    if word == "npcx":
        # Only stops the re-pushes. Nothing takes a chibi off a map that is
        # already drawn — the spawner has no "remove" push we know of — so the
        # ones on screen stay until the next map load rebuilds the scene without
        # them. Worth having anyway: after a /npca the lobby branch would
        # otherwise replay 223 sends on every single warp, forever.
        return Reply(["ちびキャラの補充を止めた (画面上の分は地図を跨ぐまで残る)"],
                     npc_clear=True)

    if word == "nev":
        # Which conversation the speech balloon starts. The client turns this
        # pair into a capture_npc_event record and asks for the script id in
        # it, so changing it here changes what the NPC says — no restart, and
        # no need to walk back to her.
        if not rest.strip():
            return Reply(["/nev <cat>:<id>  例: /nev 16:1 (天宮日常会話c011)"])
        event = parse_id_pair(rest.split()[0])
        if event is None:
            return Reply([f"イベントidが読めない: {rest}"])
        return Reply([f"会話イベント = {event[0]}:{event[1]}"], npc_event=event)

    if word == "raw":
        # Push any message at all, by number. Exists because every question in
        # the 0x72xx family costs a client run to answer otherwise, and the
        # first one already cost one: the client took MsgSvRequestScriptReady,
        # locked its own input and said nothing, and finding out what it was
        # waiting for meant being able to send the next candidate by hand.
        # Only reachable from runtime/console.txt in practice — see
        # MpsServer._drain_console.
        words = rest.split()
        try:
            msg_type = int(words[0], 16)
            body = bytes.fromhex("".join(words[1:]))
        except (IndexError, ValueError):
            return Reply(["/raw <msgid16> [hex]  例: /raw 7203"])
        return Reply([f"raw 0x{msg_type:04x} {len(body)}B"], sends=[(msg_type, body)])

    if word == "scl":
        names = script.available()
        if not names:
            return Reply(["台本なし: runtime/scripts/ が空"])
        return Reply([" ".join(names[:10])])

    if word == "sc":
        # `/sc amm_s001 1 1:0` -> script, ctrl=1, npcInfo=[(actorId 1, npcId 0)].
        # Nothing is validated beyond "these are numbers": the point of the
        # command is to find out what the client accepts, and a server-side
        # check would only be able to enforce this end's guesses.
        words = rest.split()
        if not words:
            return Reply([f"/sc <名前|scriptId> [ctrl] [actor:npcId]  例: /sc amm_s001"])
        if words[0].isdigit():
            # ⭐ A bare id starts a stub: no cast and no instruction list, but
            # the branches of the shipped table if the id is in it (see
            # script.stub). Everything downstream is the same code as a loaded
            # script, so a difference between `/sc amm_s001` and `/sc 57344` is
            # a difference the export made, and nothing else.
            found = script.stub(int(words[0]))
        else:
            found = script.load(words[0])
            if found is None:
                return Reply([f"台本が見つからない: {words[0]}"])
        if found.script_id is None:
            return Reply([f"{found.file} に scriptId がない"])
        ctrl = int(words[1]) if len(words) > 1 and words[1].isdigit() else 0
        infos = []
        for pair in words[2:]:
            parsed = parse_id_pair(pair)
            if parsed is None:
                return Reply([f"actor:npcId が読めない: {pair}"])
            infos.append(parsed)
        cast = "、".join(f"{a['category']}#{a['actorId']} {a['name']}"
                         for a in found.actors) or "なし"
        return Reply(
            [f"{found.file} id={found.script_id} 命令{len(found)} ctrl={ctrl}",
             f"配役: {cast}"],
            script=ScriptAction("start", words[0], ctrl, infos),
        )

    if word == "scn":
        # A manual step, so that "the client never acknowledged" and "the
        # commands do nothing" stay separable. If 0x721b comes back on its own
        # this is never needed; if it does not, this is the only way to find out
        # whether anything is reaching the screen.
        return Reply(script=ScriptAction("next"))

    if word == "sce":
        return Reply(script=ScriptAction("end"))

    if word == "sel":
        # Re-ask a choice box that is already on screen. The query carries no
        # ip, so re-sending it needs nothing from the session — which is the
        # point: `select` has two live readings ("how many options" vs "a bit
        # per option"), and this turns telling them apart into typing a line
        # rather than walking back to the NPC and starting the script again.
        words = rest.split()
        if not words:
            return Reply(["選択肢の既定に戻した (台本の選択肢数)"], select=(-1, -1))
        try:
            select = int(words[0], 0)
            timer = int(words[1], 0) if len(words) > 1 else script.DEFAULT_SELECT_TIMER
        except ValueError:
            return Reply(["/sel <select> [timer]  例: /sel 7 60000"])
        return Reply(
            [f"QuerySelect select={select} timer={timer}"],
            select=(select, timer),
            sends=[(script.MSG_SV_QUERY_SCRIPT_COMMAND_SELECT,
                    script.select_params(select, timer))],
        )

    if word == "dms":
        # The whole opening bracket of the matching screen, unprompted. The
        # client normally asks for it with 0xe000 and the server answers, but
        # 0xe000 carries an npcId, so the screen may only be reachable by
        # talking to somebody — and if that is so, this is the only way to find
        # out whether the Ok alone is what installs the receive handler.
        known = script.drama_events()
        keys = [(e["genre"], e["index"]) for e in known][: script.DRAMA_EVENT_MAX]
        return Reply(
            [f"MatchingStart nDrama={len(keys)} nParty=0"],
            sends=[
                (script.MSG_SV_OK_DRAMA_EVENT_MATCHING_START,
                 script.matching_start_params(len(keys), 0)),
                (script.MSG_SV_NOTIFY_DRAMA_EVENT_LIST,
                 script.drama_event_list_params(keys)),
                (script.MSG_SV_NOTIFY_DRAMA_PARTY_LIST, struct.pack(">H", 0)),
            ],
        )

    if word == "de":
        # MsgSvNotifyDramaEventList. This is the client's *other* way of opening
        # a .ssb — the one that goes through drama_event.bin rather than through
        # a scriptId — and it has never been sent. Arguments are keys, either
        # `<genre>:<番号>` like /npc or the .ssb stem the key resolves to; with
        # none, the command only lists what the exported table knows, because
        # sending an empty list is a different experiment and worth its own line
        # (`/de 0:` would be a typo, `/raw e003 0000` is deliberate).
        known = script.drama_events()
        words = rest.split()
        if not words:
            if not known:
                return Reply(["ドラマ表なし: runtime/drama_events.json が無い"])
            names = " ".join(f"{e['genre']}:{e['index']}={e['ssb'][:-4]}" for e in known)
            return Reply([f"{len(known)}件"] + [names[i:i + 90]
                                                for i in range(0, len(names), 90)][:3])
        by_stem = {e["ssb"][:-4]: (e["genre"], e["index"]) for e in known}
        keys, titles = [], []
        for token in words:
            key = parse_id_pair(token) or by_stem.get(token.removesuffix(".ssb"))
            if key is None:
                return Reply([f"ドラマの鍵が読めない: {token}"])
            keys.append(key)
            hit = next((e for e in known if (e["genre"], e["index"]) == key), None)
            titles.append(hit["ssb"][:-4] if hit else f"{key[0]}:{key[1]}?")
        if len(keys) > script.DRAMA_EVENT_MAX:
            return Reply([f"多すぎ: {script.DRAMA_EVENT_MAX}件まで"])
        return Reply(
            [f"DramaEventList {len(keys)}件: {' '.join(titles)}"],
            sends=[(script.MSG_SV_NOTIFY_DRAMA_EVENT_LIST,
                    script.drama_event_list_params(keys))],
        )

    if word == "go":
        # An optional landing square, because `mapgraph.landing` gives one spot
        # per map and the ちびキャラ are scattered: checking a placement 40 cells
        # from the door otherwise means walking there, and 223 of them are spread
        # over 78 maps. Read off the end so map names — which never contain a
        # space — stay a single word either way.
        # `119 65` and `119:65` both, because the other command that takes a pair
        # of numbers — /npc — writes them with a colon, and mixing the two up is
        # what the separator being different invites. A map name never contains
        # either, so neither form is ambiguous.
        words, spot = rest.split(), None
        if words and (pair := parse_id_pair(words[-1])) is not None:
            spot, words = pair, words[:-1]
        elif len(words) >= 3 and words[-1].isdigit() and words[-2].isdigit():
            spot, words = (int(words[-2]), int(words[-1])), words[:-2]
        rest = " ".join(words)
        hits = mapgraph.search(rest)
        if not hits:
            return Reply([f"「{rest}」に一致する地図なし"])
        if len(hits) > 1 and not rest.isdigit():
            names = " ".join(f"{map_id}:{name}" for map_id, name in hits[:8])
            return Reply([f"候補{len(hits)}件: {names}"])
        target, target_name = hits[0]
        if spot is None:
            spot = mapgraph.landing(target)
        if spot is None:
            return Reply([f"{target_name}({target}) には降り立つ場所が分からない"])
        pos_x, pos_y = spot
        size = mapgraph.size(target)
        if size is not None and not (0 <= pos_x < size[0] and 0 <= pos_y < size[1]):
            return Reply([f"{target_name}({target}) は {size[0]}x{size[1]}、外です"])
        # Stated, not refused: a placement script is free to stand a chibi on a
        # square the collision file calls solid, and walking over to look at one
        # is exactly what this form is for.
        note = "" if mapgraph.walkable(target, spot) is not False else " 床なし?!"
        return Reply(
            [f"→ {target_name}({target}) {pos_x},{pos_y}{note}"],
            warp=(target, pos_x, pos_y, ARRIVAL_DIRECTION),
        )

    return Reply([f"不明なコマンド: {word}"])
