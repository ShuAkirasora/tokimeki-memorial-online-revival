"""ストレスと体調: the stress bar, 休憩, and ノイローゼ.

`p05_09` states the whole system in prose, and unusually for this project most
of it is restoration rather than invention. Quoted where it decides something:

    ストレスがたまる場合   授業・試験 / クラブ活動 / 奥義合成
    ストレスが０でない場合は、キャラクターの下にストレスバーが表示されます
    マップ上で座って（[Insert]キー）じっとしていると、少しずつストレスが
      減っていきます（体調が「健康」の場合）
    ノイローゼ … ストレスが高い状態で授業や試験を受けると、ノイローゼになる
      ことがあります。学業に参加できなくなります
    怪我 … ストレスが高い状態でクラブ活動を行なうと、怪我をすることがあります
    ドクターストップ … ノイローゼと怪我が重なった状態です
    ストレスを0にすることで、体調が「健康」に戻ります。ただし、体調不良の場合、
      座っているだけではストレスは減りません。癒しスペース（保健室・泉・テラス）
      で座り、回復を待つようにしてください

Four wire messages carry it, and all four were already in the id table:

    0x4806 MsgClCastCharaPose        u8  pose          the client, on [Insert]
    0x4807 MsgSvNotifyCharaPose      u32 charaId, u8 pose
    0x4811 MsgSvNotifyCharacterStress    u8 stress
    0x4812 MsgSvNotifyCharacterCondition u8 condition

⚠️ The two notifies carry no charaId. Everything else in the 0x48xx block that
talks about a character in the scene names one — 0x4807 pose, 0x480A move,
0x4813 info — so the absence is a statement: these two are about the player's
own character. What the bar under *another* player's head is fed by is
therefore not answered by these, and this server has no second player to ask.

⚠️ 0x4806 is a Cast and must be answered, exactly like MsgClCastCharaTurn
(0x4803). Leaving it unanswered wedges the client's input for the rest of the
session — a second [Insert] produces nothing and neither does a click on the
ground. That is the same failure the turn cast cost a session for, so it is now
two for two: a `MsgClCast*` that gets no notify back stops the client dead.
The client also does not sit down on its own — it casts and waits for 0x4807,
so the pose on screen is the server's to grant.

WHAT IS RESTORED AND WHAT IS INVENTED
-------------------------------------
Restored, and each traceable to a sentence above or to a table:

  * which activities add stress, and that only 授業 of them exists here
  * that sitting is what removes it, and only while 体調 is 健康
  * that 体調不良 is escaped by reaching stress 0, not by waiting it out
  * that a 体調不良 character recovers only in a 癒しスペース
  * ノイローゼ blocks 学業 — REASON_NEUROSIS was already sitting in lesson.py
  * the three 癒しスペース, from the data rather than only from the prose:
    `twoshot_place.bin` gives each of its 118 places a flag byte at +0x2D, and
    it is set on exactly three records — 7 テラス, 23 泉, 41 保健室. That is the
    manual's parenthesis, member for member, with nothing else in the file. The
    neighbouring byte at +0x2C is set on exactly the 48 places whose keys are
    ≥256, which are the off-campus backgrounds, so the two are independent
    booleans rather than one u16 that happens to read small.

Invented, because no table carries a number for any of it:

  * STRESS_PER_LESSON, NEUROSIS_AT, and the two recovery rates
  * that crossing NEUROSIS_AT is *certain* rather than a chance. The manual
    says 「なることがあります」, which is a probability, and this server makes it
    a threshold. A coin flip that cannot be reproduced would make the whole
    subsystem untestable — the run that produced a ノイローゼ and the run that
    did not would look identical in the log — and picking the coin's weight
    would be one more invented number on top of the threshold, not instead of
    it. Recorded as a divergence, not as a reading.

⚠️ 泉 and テラス are places on 屋外, not maps of their own: `map.bin` has no
record under either name, and `twoshot_place` gives seasonal background ids
rather than cells. So HEALING_MAPS can only name 保健室 for now, and a
体調不良 character has exactly one room in this server that will heal them.

Scale, from ability.py: `stress` is drawn as 「ストレス：Ｎ／１００」 with
N = min(100, floor(値·100/257)), so 257 is a full bar and the numbers below are
in 値 with their screen reading in the comment. ⚠️ The field is u16 in 0x4310
and u8 in both 0x6102 and 0x4811, so 値 above 255 cannot survive the round trip
through the notify — FULL is 257 on the sheet and the packers clamp.
"""
from __future__ import annotations

import struct

MSG_CL_CAST_CHARA_POSE = 0x4806
MSG_SV_NOTIFY_CHARA_POSE = 0x4807
MSG_SV_ERROR_CHARA_POSE = 0x4808
MSG_SV_NOTIFY_CHARACTER_STRESS = 0x4811
MSG_SV_NOTIFY_CHARACTER_CONDITION = 0x4812

# The two poses the map mode has. 1 is what [Insert] casts, measured; 0 is the
# only other value the field can sensibly hold and is what standing up sends.
POSE_STANDING = 0
POSE_SITTING = 1

# `chara_condition.bin`, all four records in key order. The index is what
# 0x4310 and 0x4812 carry.
CONDITIONS = ("健康", "ノイローゼ", "怪我", "ドクターストップ")
HEALTHY = 0
NEUROSIS = 1
INJURY = 2
DOCTOR_STOP = 3

# A full bar. See the module docstring for where the 257 comes from.
FULL = 257

# The one 癒しスペース this server can locate. See the ⚠️ above for the two it
# cannot.
HEALING_MAPS = (48,)  # 特殊教室校舎１Ｆ保健室

# ── INVENTED ───────────────────────────────────────────────────────────────
# Nothing below is read off anything. `lesson.bin` carries no stress column,
# `chara_condition.bin` is four names and two zero bytes, and `p05_09` gives no
# figure at all — not a rate, not a threshold, not a cap.
#
# The shape they were picked for: a lesson every fifteen minutes, ten lessons to
# fill the bar, ノイローゼ waiting at seven of them, and a full bar sat off in
# about the time two lessons take. That makes the whole loop reachable inside
# one session without a save editor, which is the only property that can be
# argued for from here.
STRESS_PER_LESSON = 26          # ≈ 10 / 100 on screen
NEUROSIS_AT = 180               # ≈ 70 / 100 on screen
SIT_SECONDS_PER_POINT = 3.0     # a full bar in ~13 minutes
HEALING_SECONDS_PER_POINT = 1.0 # three times that, in the 保健室
# ── end INVENTED ───────────────────────────────────────────────────────────


def screen(value: int) -> int:
    """What 「ストレス：Ｎ／１００」 will read for this 値. From ability.py."""
    return min(100, value * 100 // FULL)


def pose_params(chara_id: int, pose: int) -> bytes:
    """MsgSvNotifyCharaPose: u32 charaId then u8 pose."""
    return struct.pack(">IB", chara_id & 0xFFFFFFFF, pose & 0xFF)


def stress_params(value: int) -> bytes:
    """MsgSvNotifyCharacterStress. One byte, so a full bar clamps to 255."""
    return struct.pack(">B", max(0, min(0xFF, value)))


def condition_params(value: int) -> bytes:
    """MsgSvNotifyCharacterCondition. One byte, an index into CONDITIONS."""
    return struct.pack(">B", max(0, min(0xFF, value)))


def name(condition: int) -> str:
    return CONDITIONS[condition] if 0 <= condition < len(CONDITIONS) else f"?{condition}"


def healing(map_id: int) -> bool:
    """Is this map one of the 癒しスペース?"""
    return map_id in HEALING_MAPS


def charge(sheet, amount: int) -> "tuple[int, int]":
    """Charge `amount` of stress, and decide whether it broke the player.

    Returns (stress_added, new_condition). Order matters and follows the
    manual's wording: 「ストレスが高い状態で授業や試験を受けると」 — the state
    that is judged is the one the player *sat down* in, so the reading is taken
    before this activity's own stress is added. Charging first would make the
    lesson that takes you over the line the same one that punishes you for it.

    ⭐ The amount is the caller's because 「授業や試験を」 is one sentence about
    two activities: 授業 and 試験 both charge, by the same rule, and only the
    quantity is theirs to name. Both quantities are invented — see the block
    above and exam.STRESS_PER_EXAM.
    """
    was = sheet.stress
    sheet.stress = min(FULL, was + amount)
    if was >= NEUROSIS_AT and sheet.condition == HEALTHY:
        sheet.condition = NEUROSIS
    return sheet.stress - was, sheet.condition


def after_lesson(sheet) -> "tuple[int, int]":
    """One 授業's worth. See charge."""
    return charge(sheet, STRESS_PER_LESSON)


def recover(sheet, seconds: float, map_id: int) -> int:
    """Sit still for `seconds` on `map_id`. Returns the 値 actually removed.

    「体調が「健康」の場合」 and 「体調不良の場合、座っているだけではストレスは
    減りません。癒しスペース…で座り」 — so a 体調不良 character recovers in the
    保健室 and nowhere else, while a healthy one recovers anywhere and faster
    there. 「ストレスを0にすることで、体調が「健康」に戻ります」 closes the loop.
    """
    if sheet.stress <= 0:
        return 0
    at_healing = healing(map_id)
    if sheet.condition != HEALTHY and not at_healing:
        return 0
    rate = HEALING_SECONDS_PER_POINT if at_healing else SIT_SECONDS_PER_POINT
    removed = min(sheet.stress, int(seconds / rate))
    sheet.stress -= removed
    if sheet.stress == 0:
        sheet.condition = HEALTHY
    return removed
