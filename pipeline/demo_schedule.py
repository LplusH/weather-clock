#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日刷新演示：按天跑一遍选歌 → 抓词 → 选句，打印成一张表。

用途是让你确认三件事：
  1. 90 天内不重复（曲库 91 首，够撑三个多月）
  2. 节气/节日会优先用指定的歌（冬至 → 葡萄成熟時）
  3. 下雨会切到雨天的歌（冷雨夜）

用法：
  python pipeline/demo_schedule.py                 # 从今天起 30 天
  python pipeline/demo_schedule.py --start 2026-12-15 --days 30
  python pipeline/demo_schedule.py --rain-on 5,17  # 第 5、17 天下雨
"""

import argparse
import contextlib
import io
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--rain-on", default="", help="第几天设为下雨，逗号分隔，如 5,17")
    ap.add_argument("--offline", action="store_true", help="只用本地歌词缓存")
    args = ap.parse_args()

    start = date.fromisoformat(args.start) if args.start else date.today()
    rain = {int(x) for x in args.rain_on.split(",") if x.strip()}

    # 演示用独立的 state，别污染正式记录
    state = daily.DEFAULT_STATE.parent / "state-demo"
    out = daily.DEFAULT_OUT.parent / "_demo.json"

    print()
    print(f"每日刷新演示：{start} 起 {args.days} 天")
    print("=" * 104)
    print(f"{'日期':<12}{'星期':<5}{'触发':<12}{'歌曲':<18}{'歌手':<10}歌词")
    print("-" * 104)

    used = 0
    for i in range(args.days):
        d = start + timedelta(days=i)
        w = "rainy" if i in rain else "cloudy"
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                r = daily.build(d, w, daily.DEFAULT_CATALOG, daily.DEFAULT_CACHE,
                                state, out, args.offline, True)
        except Exception as e:
            msg = str(e).splitlines()[0][:40]
            print(f"{d.isoformat():<12}{daily.WEEKDAYS[d.weekday()]:<5}{'─':<12}{'（跳过）':<18}{'':<10}{msg}")
            continue

        used += 1
        meta = r["meta"]
        trig = meta.get("special") or ("雨"if w == "rainy" else "")
        print(f"{d.isoformat():<12}{r['weekday']:<5}{trig:<12}"
              f"《{r['song']['title']}》{'':<2}{r['song']['artist']:<10}{r['lyric']}")

    print("-" * 104)
    print(f"共 {used} 天，全部来自曲库 {len(daily.read_json(daily.DEFAULT_CATALOG)['songs'])} 首")
    print()


if __name__ == "__main__":
    main()
