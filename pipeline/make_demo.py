#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 site/demo.txt —— 给固件「演示模式」用。

每行一条：日期|歌词第一行|歌词第二行|歌名|歌手
固件每 20 秒换一行，这样你能当场看到「每天不一样」。
"""
import contextlib
import io
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()

state = daily.DEFAULT_STATE.parent / "state-demo"
out = daily.DEFAULT_OUT.parent / "_demo.json"

rows = []
for i in range(DAYS):
    d = start + timedelta(days=i)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r = daily.build(d, "cloudy", daily.DEFAULT_CATALOG, daily.DEFAULT_CACHE,
                            state, out, False, True)
    except Exception as exc:
        print(f"  {d} 跳过：{str(exc).splitlines()[0][:50]}")
        continue
    lines = daily.wrap_lyric(r["lyric"], 10)
    l1 = "~".join(lines)          # 整段用 ~ 分隔，固件端拆开
    sp = (r["meta"].get("special") or "").split("·")[-1]
    rows.append(f"{d.strftime('%m.%d')}|{l1}||{r['song']['title']}|{r['song']['artist']}|{sp}")
    print(f"  {d}  《{r['song']['title']}》{r['song']['artist']}  {r['lyric']}")

if rows:
    dst = daily.DEFAULT_OUT.parent / "demo.txt"
    dst.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n已写 {dst}（{len(rows)} 天）")
