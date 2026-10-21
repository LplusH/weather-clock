#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 每天自己找歌（不用曲库）。

流程：
  1. 把「今天是什么日子 + 天气 + 最近用过哪些歌」丢给模型
  2. 模型推荐 5–6 首粤语歌（要求冷门、不要烂大街）
  3. **逐首去 LRCLIB 抓歌词验证**——抓不到就是模型编的，直接丢
  4. 抓到词的才进候选池，取第一首

为什么要「验证」：模型回忆歌名和歌手很容易编（尤其冷门歌）。
但只要拿 (歌名, 歌手) 去歌词库查，查不到就能立刻识破，
所以幻觉不会漏到屏上——最多是浪费一次推荐。

没有 API key 时 propose() 直接返回空，调用方回退到曲库。
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402

WEEK_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _ai_ready() -> bool:
    return bool(os.environ.get("WC_AI_BASE") and os.environ.get("WC_AI_KEY"))


def propose(day, weather: str, special: dict | None, used: list[str], n: int = 10) -> list[dict]:
    """让模型推荐 n 首粤语歌，返回 [{title, artist, why}]。没 key 或失败时返回 []。"""
    if not _ai_ready():
        return []

    base = os.environ["WC_AI_BASE"].rstrip("/")
    key = os.environ["WC_AI_KEY"]
    model = os.environ.get("WC_AI_MODEL", "")

    ctx = [f"日期：{day.isoformat()} {WEEK_CN[day.weekday()]}", f"天气：{weather}"]
    if special:
        ctx.append(f"今天是{special['kind']}：{special['name']}")
    if used:
        ctx.append("最近用过、这次不要重复：" + "、".join(used[-30:]))

    prompt = f"""{chr(10).join(ctx)}

请推荐 {n} 首**粤语歌**，用于「每天一句歌词」的墙上时钟。

硬性要求：
1. 不要烂大街的那几首（《海阔天空》《红日》《千千阙歌》《狮子吼下山》这类别来）
2. 优先非主打、B-side、冷门但词好的作品
3. 歌词要有鼓励或哲理，能单独贴出来给人力量
4. 如果今天有节日/节气/天气线索，尽量挑应景的
5. 只要**真实存在**的歌，宁可保守也不要编

只回 JSON 数组，每项 {{"title": "歌名", "artist": "歌手", "why": "一句话理由"}}
"""

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = body["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"  [AI] 调用失败：{exc}")
        return []

    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        print("  [AI] 返回里没有 JSON 数组")
        return []
    try:
        items = json.loads(m.group(0))
    except Exception:
        print("  [AI] JSON 解析失败")
        return []

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        t, a = str(it.get("title", "")).strip(), str(it.get("artist", "")).strip()
        if t and a:
            out.append({"title": t, "artist": a, "why": str(it.get("why", ""))})
    return out


def verify(song: dict, cache_dir: Path) -> str | None:
    """去歌词库验证这首是否真实存在。抓到词就算通过（同时写缓存）。"""
    try:
        lyric, _src = daily.get_lyrics(song, cache_dir, offline=False)
        return lyric if lyric and len(lyric) > 40 else None
    except Exception:
        return None


def candidates(day, weather: str, special: dict | None, used: list[str],
               cache_dir: Path, limit: int = 4) -> list[dict]:
    """返回**已验证有歌词**的候选歌，可直接喂给 daily.build()。"""
    props = propose(day, weather, special, used, n=10)
    if not props:
        return []

    print(f"  [AI] 推荐了 {len(props)} 首：")
    for p in props:
        print(f"       《{p['title']}》{p['artist']}  — {p['why']}")

    out = []
    for p in props:
        sid = "ai-" + hashlib.sha256(f"{p['title']}|{p['artist']}".encode()).hexdigest()[:8]
        song = {"id": sid, "title": p["title"], "artist": p["artist"],
                "year": None, "hot": 1, "tags": [], "why": p["why"]}
        lyric = verify(song, cache_dir)
        if lyric:
            print(f"       ✓ 歌词库确认存在（{len(lyric)} 字）")
            out.append(song)
            if len(out) >= limit:
                break
        else:
            print("       ✗ 歌词库查不到，判定为编造，丢弃")
    return out


if __name__ == "__main__":
    from datetime import date
    print("有 API key：", _ai_ready())
    cs = candidates(date.today(), "cloudy", None, [], daily.DEFAULT_CACHE)
    print(f"\n可用候选 {len(cs)} 首")
    for c in cs:
        print(" ", c["title"], c["artist"])
