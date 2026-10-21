#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
农历节气 + 节日判定。

节气不是查表，而是**按太阳视黄经算**：太阳每走 15° 就是一个节气。
这样 2000–2099 年都准，不用维护一张越来越长的日期表。

用法：
    from calendar_cn import describe
    describe(date(2026, 12, 21))
    -> {"kind": "节气", "name": "冬至", "songs": ["葡萄成熟時/陳奕迅"], ...}
"""

import math
from datetime import date, timedelta

# 24 节气：太阳视黄经 → 名称
TERMS = {
    315: "立春", 330: "雨水", 345: "驚蟄", 0: "春分",
    15: "清明", 30: "穀雨", 45: "立夏", 60: "小滿",
    75: "芒種", 90: "夏至", 105: "小暑", 120: "大暑",
    135: "立秋", 150: "處暑", 165: "白露", 180: "秋分",
    195: "寒露", 210: "霜降", 225: "立冬", 240: "小雪",
    255: "大雪", 270: "冬至", 285: "小寒", 300: "大寒",
}


def _jd(d: date) -> float:
    """公历日期 → 儒略日（0h UT）。"""
    y, m, dd = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + dd + b - 1524.5


def _sun_longitude(jd: float) -> float:
    """太阳视黄经（度）。Meeus 低精度公式，误差约 0.01°。"""
    t = (jd - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    omega = math.radians(125.04 - 1934.136 * t)
    return (l0 + c - 0.00569 - 0.00478 * math.sin(omega)) % 360.0


def _find_term_day(year: int, lon: float) -> date:
    """在给定年份里找太阳视黄经等于 lon 的那天（北京时间）。"""
    # 从该年 1 月 1 日开始逐日扫描，找到跨越目标经度的那一天
    d = date(year, 1, 1)
    prev = _sun_longitude(_jd(d))
    for _ in range(370):
        nxt_d = d + timedelta(days=1)
        nxt = _sun_longitude(_jd(nxt_d))
        # 处理 360 → 0 的环绕
        crossed = (prev <= lon < nxt) if nxt >= prev else (lon >= prev or lon < nxt)
        if crossed:
            # 二分细化到小时，判断落在哪一天（+8 时区）
            lo, hi = _jd(d), _jd(nxt_d)
            for _ in range(24):
                mid = (lo + hi) / 2
                v = _sun_longitude(mid)
                if (prev <= lon < v) if v >= prev else (lon >= prev or lon < v):
                    hi = mid
                else:
                    lo = mid
            jd_bj = lo + 8 / 24.0          # 转到北京时间
            # 儒略日 → 公历
            z = int(jd_bj + 0.5)
            f = jd_bj + 0.5 - z
            alpha = int((z - 1867216.25) / 36524.25)
            a = z + 1 + alpha - alpha // 4
            b = a + 1524
            c = int((b - 122.1) / 365.25)
            dd_ = int(365.25 * c)
            e = int((b - dd_) / 30.6001)
            day = b - dd_ - int(30.6001 * e) + int(f)
            month = e - 1 if e < 14 else e - 13
            yy = c - 4716 if month > 2 else c - 4715
            try:
                return date(yy, month, day)
            except ValueError:
                return d
        d, prev = nxt_d, nxt
    raise RuntimeError(f"{year} 找不到黄经 {lon}°")


_term_cache: dict = {}


def terms_of(year: int) -> dict:
    """返回 {date: 节气名}。"""
    if year in _term_cache:
        return _term_cache[year]
    out = {}
    for lon, name in TERMS.items():
        try:
            out[_find_term_day(year, lon)] = name
        except Exception:
            pass
    _term_cache[year] = out
    return out


# ---------------- 固定公历节日 ----------------
FIXED = {
    (1, 1): "元旦",
    (2, 14): "情人節",
    (3, 8): "婦女節",
    (5, 1): "勞動節",
    (6, 1): "兒童節",
    (10, 1): "國慶",
    (12, 24): "平安夜",
    (12, 25): "聖誕",
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """某月第 n 个星期几（weekday: 0=周一）。"""
    d = date(year, month, 1)
    shift = (weekday - d.weekday()) % 7
    return d + timedelta(days=shift + 7 * (n - 1))


def describe(d: date) -> dict | None:
    """今天是什么日子？返回 {"kind","name","songs"} 或 None。"""
    # 1) 节气
    t = terms_of(d.year).get(d)
    if t:
        return {"kind": "節氣", "name": t, "songs": TERM_SONGS.get(t, [])}

    # 2) 固定公历节日
    if (d.month, d.day) in FIXED:
        name = FIXED[(d.month, d.day)]
        return {"kind": "節日", "name": name, "songs": FIXED_SONGS.get(name, [])}

    # 3) 母亲节（5月第二个星期日）/ 父亲节（6月第三个星期日）
    if d == _nth_weekday(d.year, 5, 6, 2):
        return {"kind": "節日", "name": "母親節", "songs": ["單車/Beyond"]}
    if d == _nth_weekday(d.year, 6, 6, 3):
        return {"kind": "節日", "name": "父親節", "songs": ["單車/Beyond"]}

    return None


# ---------------- 节日 → 歌单 ----------------
# 只放「跟这天有关系、又不算烂大街」的歌；格式 "歌名/歌手"，要和曲库对得上
TERM_SONGS = {
    "冬至": ["葡萄成熟時/陳奕迅"],                  # 用戶的例子：冬至聽葡萄成熟時
    "立春": ["櫻花樹下/張敬軒"],
    "驚蟄": ["弱水三千/麥浚龍"],
    "清明": ["石頭記/達明一派"],
    "穀雨": ["下雨天/林憶蓮"],
    "夏至": ["沙龍/陳奕迅"],
    "大暑": ["夏日傾情/黎明"],
    "立秋": ["歲月無聲/Beyond"],
    "秋分": ["月半小夜曲/李克勤"],
    "霜降": ["夕陽之歌/梅艷芳"],
    "立冬": ["任我行/陳奕迅"],
    "小雪": ["化蝶/何韻詩"],
    "大雪": ["山丘/李宗盛"],                       # 可能不在曲库，会自动跳过
    "小寒": ["命硬/側田"],
    "大寒": ["再見理想/Beyond"],
}

FIXED_SONGS = {
    "元旦": ["年度之歌/謝安琪"],
    "情人節": ["小玩意/彭羚"],
    "聖誕": ["Lonely Christmas/陳奕迅"],
    "平安夜": ["Lonely Christmas/陳奕迅"],
    "國慶": ["獅子山下/羅文"],
    "母親節": ["單車/Beyond"],
    "父親節": ["單車/Beyond"],
}

# ---------------- 天气 → 歌单 ----------------
WEATHER_SONGS = {
    "rainy": ["冷雨夜/Beyond", "雨夜的浪漫/譚詠麟"],
    "storm": ["冷雨夜/Beyond"],
}


if __name__ == "__main__":
    import sys
    y = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    print(f"{y} 年 24 节气：")
    for d, name in sorted(terms_of(y).items()):
        print(f"  {d}  {name}")
