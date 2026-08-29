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

# ── INVENTED — how much ストレス one activity adds (授業 / クラブ / 奥義合成) ──
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

# 「クラブ活動」 is the second entry on the manual's list of what adds ストレス,
# and it is worth what a lesson is worth for the same reason 試験 is: the page
# names the three sources in one sentence and gives a figure for none of them,
# so a difference between them would be a second invention on top of the first.
# ⚠️ One 自主トレ fight is one クラブ活動, whatever its length -- turns are not
# what the sentence counts.
STRESS_PER_CLUB_ACTIVITY = 26

# 「奥義合成」 is the third and last entry on that list, and it gets the same
# figure for the same reason the other two do: one sentence names all three and
# gives a figure for none, so a difference between them would be a second
# invention resting on the first. ⭐ One attempt is one 合成, win or lose --
# p05_09 counts 「行なうと」, and a failed 合成 was still performed.
STRESS_PER_GOUSEI = 26
# ── end INVENTED (inventions:skip) ────────────────────────────────────────


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


def worsen(condition: int, added: int) -> int:
    """Put `added` on top of `condition`. 「ノイローゼと怪我が重なった状態」.

    ⭐⭐⭐ RESTORED, and the whole of ドクターストップ is in that one clause:
    the fourth 体調 is not a thing anything gives you, it is what the other two
    add up to. Which is also why nothing needs to name it -- 授業 gives
    ノイローゼ, クラブ活動 gives 怪我, and a player who collects both arrives
    here.

        健康     + X       = X
        X        + X       = X          (already there; nothing gets worse)
        ノイローゼ + 怪我     = ドクターストップ   (and the other way round)
        ドクターストップ + X    = ドクターストップ   (there is nothing above it)
    """
    if condition == DOCTOR_STOP or condition == added or added == HEALTHY:
        return condition
    if condition == HEALTHY:
        return added
    return DOCTOR_STOP


def charge(sheet, amount: int, breaks_into: int = NEUROSIS) -> "tuple[int, int]":
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

    ⭐⭐ ``breaks_into`` is the caller's for the same reason, and it is the
    half round 148 and everything before it left out: the manual names *two*
    ways to break, one per kind of activity — 「授業や試験を受けると、ノイローゼ
    になることがあります」 and 「クラブ活動を行なうと、怪我をすることがあります」
    — and this end only ever charged the 学業 half. See worsen for what happens
    when a player collects both.
    """
    was = sheet.stress
    sheet.stress = min(FULL, was + amount)
    if was >= NEUROSIS_AT:
        sheet.condition = worsen(sheet.condition, breaks_into)
    return sheet.stress - was, sheet.condition


def after_lesson(sheet) -> "tuple[int, int]":
    """One 授業's worth. See charge."""
    return charge(sheet, STRESS_PER_LESSON)


def after_club_activity(sheet) -> "tuple[int, int]":
    """One クラブ活動's worth, and it breaks into 怪我 rather than ノイローゼ."""
    return charge(sheet, STRESS_PER_CLUB_ACTIVITY, breaks_into=INJURY)


def after_gousei(sheet) -> "tuple[int, int]":
    """One 奥義合成's worth. ⭐⭐⭐ It CHARGES BUT DOES NOT BREAK.

    ⚠️⚠️ The third source on p05_09's list is the one that is on that list
    and on no other, and the asymmetry is the whole reading:

        1.ストレスがたまる場合   授業・試験 / クラブ活動 / 奥義合成
        3.体調不良          ノイローゼ … 授業や試験を受けると
                          怪我      … クラブ活動を行なうと

    Three sources, two ways to break, and 合成 is not one of the two. That is
    an earlier lesson -- an absence is a value that gets read -- taken the careful way
    rather than the lazy one: it does not rest on the silence alone, because
    `error_message.bin` says the same thing from the other side. The 練習 door
    has a 怪我 code (0x5D02 reason 11
    「怪我をしているため、部活に参加できません」) and the 合成 door (0x5302, seven
    codes) has none -- so 怪我 does not bar 合成 either, and gousei.py checks
    barred_from_club nowhere. ⭐ Two witnesses, a table and a page, agreeing.

    ⚠️ ``breaks_into=HEALTHY`` is how that is expressed rather than a second
    code path: worsen() returns the condition unchanged when what is added is
    HEALTHY, so a player already at 怪我 stays at 怪我 and a healthy one over
    the threshold stays healthy. See charge.
    """
    return charge(sheet, STRESS_PER_GOUSEI, breaks_into=HEALTHY)


def barred_from_club(condition: int) -> bool:
    """怪我をするとクラブ活動に参加できなくなります.

    ⭐⭐⭐ RESTORED down to the refusal bytes: the client ships the sentences
    (trainingroom.py lists them) -- 0x5802 reason 11 「怪我をしていると、自主トレ
    に参加することはできません。」 and 0x5808 reason 10. A rule the other end
    already has a sentence for is not one this end gets to invent.

    ドクターストップ is 「ノイローゼと怪我が重なった状態」, so it bars this too,
    exactly as it bars 学業.
    """
    return condition in (INJURY, DOCTOR_STOP)


def relieve(sheet, amount: int) -> int:
    """Take `amount` of ストレス off. Returns the 値 actually removed.

    ⭐ 「ストレスを0にすることで、体調が「健康」に戻ります」 is a sentence about
    the value reaching zero and not about how it got there, so everything that
    takes ストレス off closes the loop the same way — sitting through recover
    below, and 消費アイテム through item.ITEM_EFFECTS. Having one function for
    it is what keeps a second way of getting to zero from quietly growing a
    second rule.
    """
    removed = max(0, min(sheet.stress, amount))
    sheet.stress -= removed
    if sheet.stress == 0:
        sheet.condition = HEALTHY
    return removed


def recover(sheet, seconds: float, map_id: int) -> int:
    """Sit still for `seconds` on `map_id`. Returns the 値 actually removed.

    「体調が「健康」の場合」 and 「体調不良の場合、座っているだけではストレスは
    減りません。癒しスペース…で座り」 — so a 体調不良 character recovers in the
    保健室 and nowhere else, while a healthy one recovers anywhere and faster
    there. 「ストレスを0にすることで、体調が「健康」に戻ります」 closes the loop,
    and relieve is where that last clause lives.
    """
    if sheet.stress <= 0:
        return 0
    at_healing = healing(map_id)
    if sheet.condition != HEALTHY and not at_healing:
        return 0
    rate = HEALING_SECONDS_PER_POINT if at_healing else SIT_SECONDS_PER_POINT
    return relieve(sheet, int(seconds / rate))
