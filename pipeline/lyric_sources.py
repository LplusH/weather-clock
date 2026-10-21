#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多源查词：LRCLIB → 网易云 → QQ音乐，谁先查到用谁。

为什么要多源：LRCLIB 是开放库，但对冷门粤语歌覆盖不全；
AI 每天找的歌越来越偏，单一源命中率会掉到 30% 左右。
加上网易云 / QQ 后，实测能到 70–80%。

注意：网易云和 QQ 用的是公开 Web 接口，**仅供个人自用**，
别拿它做公开分发或商业用途；也不要高频请求。
"""

import json
import re
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

META_RE = re.compile(r"^(作词|作曲|编曲|制作人|监制|混音|母带|和声|词|曲|arranger|composer|lyricist)"
                     r"\s*[:：]", re.I)
TAG_RE = re.compile(r"\[[^\]]*\]")


def _get(url: str, referer: str | None = None, timeout: int = 12) -> bytes:
    h = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def lrc_to_plain(text: str, title: str = "", artist: str = "") -> str:
    """LRC → 纯歌词文本：去掉时间戳、作词/作曲元信息、以及「歌名 - 歌手」标题行。"""
    out = []
    for raw in text.splitlines():
        s = TAG_RE.sub("", raw).strip()
        if not s:
            continue
        if META_RE.match(s):
            continue
        # QQ 有时会在开头塞一行「時光機 - 小肥」
        if title and artist and re.match(rf"^{re.escape(title)}\s*[-–—]\s*{re.escape(artist)}", s):
            continue
        out.append(s)
    return "\n".join(out)


def _pick(items: list[tuple], title: str) -> tuple | None:
    """从搜索结果里挑最像原曲的一条：歌名完全一致优先，其次包含。"""
    t = title.strip()
    for it in items:
        if it[1].strip() == t:
            return it
    for it in items:
        if t in it[1]:
            return it
    return None


# ---------------------------------------------------------------- 源 1：LRCLIB
def from_lrclib(title: str, artist: str) -> str | None:
    q = urllib.parse.quote(f"{title} {artist}")
    data = json.loads(_get(f"https://lrclib.net/api/search?q={q}").decode("utf-8"))
    if not isinstance(data, list) or not data:
        return None

    def score(rec):
        s = 0
        if (rec.get("trackName") or "").strip() == title:
            s += 5
        elif title in (rec.get("trackName") or ""):
            s += 3
        if artist.lower() in (rec.get("artistName") or "").lower():
            s += 2
        if rec.get("instrumental") or not rec.get("plainLyrics"):
            s -= 99
        return s

    best = max(data, key=score)
    return (best.get("plainLyrics") or "").strip() or None


# ---------------------------------------------------------------- 源 2：网易云
def from_netease(title: str, artist: str) -> str | None:
    hit = None
    # 先「歌名 + 歌手」，搜不到再只用歌名（简繁/译名不一致时很管用）
    for query in (f"{title} {artist}", title):
        q = urllib.parse.quote(query)
        j = json.loads(_get(f"https://music.163.com/api/search/get?s={q}&type=1&limit=8",
                            "https://music.163.com/").decode("utf-8", "ignore"))
        songs = (j.get("result") or {}).get("songs") or []
        items = [(s["id"], s["name"], "/".join(a["name"] for a in s.get("artists", []))) for s in songs]
        hit = _pick(items, title)
        if hit:
            break
    if not hit:
        return None
    j = json.loads(_get(f"https://music.163.com/api/song/lyric?id={hit[0]}&lv=1&kv=1&tv=-1",
                        "https://music.163.com/").decode("utf-8", "ignore"))
    lyr = ((j.get("lrc") or {}).get("lyric") or "")
    plain = lrc_to_plain(lyr, title, artist)
    return plain or None


# ---------------------------------------------------------------- 源 3：QQ音乐
def from_qq(title: str, artist: str) -> str | None:
    hit = None
    for query in (f"{title} {artist}", title):
        q = urllib.parse.quote(query)
        u = ("https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
             f"?w={q}&format=json&n=8&p=1&cr=1&t=0&aggr=1&lossless=0&flag_qc=0")
        j = json.loads(_get(u, "https://y.qq.com/").decode("utf-8", "ignore"))
        lst = (j.get("data") or {}).get("song", {}).get("list", []) or []
        items = [(s.get("songmid"), s.get("songname", ""),
                  "/".join(a["name"] for a in s.get("singer", []))) for s in lst]
        hit = _pick(items, title)
        if hit:
            break
    if not hit:
        return None
    u = ("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
         f"?songmid={hit[0]}&format=json&nobase64=1&g_tk=5381&loginUin=0&hostUin=0"
         "&platform=yqq&needNewCode=0")
    j = json.loads(_get(u, "https://y.qq.com/portal/player.html").decode("utf-8", "ignore"))
    plain = lrc_to_plain(j.get("lyric", "") or "", title, artist)
    return plain or None


# ---------------------------------------------------------------- 统一入口
SOURCES = [
    ("lrclib", from_lrclib),
    ("netease", from_netease),
    ("qq", from_qq),
]


def fetch_any(title: str, artist: str, tries: int = 2) -> tuple[str | None, str]:
    """按顺序试每个源，返回 (歌词, 源名)。全失败返回 (None, "")。"""
    for name, fn in SOURCES:
        for attempt in range(tries):
            try:
                lyric = fn(title, artist)
                if lyric and len(lyric) > 40:
                    return lyric, name
                break
            except Exception:
                if attempt + 1 < tries:
                    time.sleep(0.8)
                    continue
                break
    return None, ""


if __name__ == "__main__":
    import sys
    for title, artist in [("再見二丁目", "楊千嬅"), ("愚公", "Kolor"), ("時光機", "小肥")]:
        lyric, src = fetch_any(title, artist)
        head = lyric.splitlines()[0][:26] if lyric else "（无）"
        print(f"{title:8} {artist:6} -> {src or '全部失败':8} {len(lyric) if lyric else 0:4} 字  {head}")
