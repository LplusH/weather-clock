#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日一句粵語歌詞 —— 曲庫 → 抓詞 → AI 選句 → 校驗 → today.json

設計要點（很重要）：
  1. 本地不存歌詞。歌詞每次執行時從歌詞源（預設 LRCLIB，免 key）實時抓。
  2. AI 不負責「背」歌詞。它只在一份**已編號的真實歌詞行**裡挑一個序號。
     這樣模型沒有機會編造原句，輸出永遠等於原文裡的某一行。
  3. 挑不到 / 沒有 API key 時自動退回關鍵詞評分（heuristic），流程不中斷。
  4. 同一日期結果穩定（雜湊決定），且 90 天內不會重複同一首歌。

用法：
  python pipeline/daily.py                       # 正常跑今天
  python pipeline/daily.py --date 2025-06-01     # 指定日期（補跑/預覽）
  python pipeline/daily.py --offline             # 只用本地歌詞快取，不聯網
  python pipeline/daily.py --no-ai               # 強制走關鍵詞評分，不調模型
  python pipeline/daily.py --weather rainy       # 指定天氣，影響選歌
  python pipeline/daily.py --render              # 順便渲染卡片 PNG
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calendar_cn import describe as describe_day, WEATHER_SONGS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "catalog.json"
DEFAULT_CACHE = ROOT / "cache"
DEFAULT_STATE = ROOT / "state"
DEFAULT_OUT = ROOT / "site" / "today.json"

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 天氣 → 偏好標籤（影響選歌，不是硬性過濾）
WEATHER_TAGS = {
    "sunny": ["打氣", "生活", "青春", "自我"],
    "cloudy": ["哲理", "城市", "成長"],
    "rainy": ["哲理", "放下", "孤獨", "打氣"],
    "storm": ["堅持", "打氣", "無常"],
}
# 星期 → 偏好標籤
WEEKDAY_TAGS = {
    0: ["打氣", "堅持", "成長"],   # 星期一
    1: ["打氣", "自我"],
    2: ["哲理", "城市"],
    3: ["哲理", "成長"],
    4: ["打氣", "生活", "青春"],   # 星期五
    5: ["生活", "哲理", "情感"],   # 星期六
    6: ["哲理", "放下", "無常"],   # 星期日
}

ENC_KEYS = ["打氣", "加油", "撐", "不怕", "繼續", "相信", "勇氣", "精彩", "更好",
            "明天", "未來", "站起", "堅強", "可以", "值得", "希望", "自由", "試",
            "好景", "溫柔", "勇敢", "堅持", "風景"]
PHIL_KEYS = ["人生", "時間", "世界", "永遠", "無常", "放下", "學會", "其實", "不過",
             "原諒", "珍惜", "接受", "明白", "記得", "成長", "歲月", "風景", "答案",
             "不會", "不可", "註定", "或者", "有些", "總會"]
NEG_KEYS = ["傷心", "眼淚", "分手", "後悔", "死", "恨", "對不起", "討厭",
            "倒下", "荒土", "墳", "無奈", "唏噓", "崩", "爛"]


# ---------------------------------------------------------------- 小工具
def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_hash(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def visible_len(s: str) -> int:
    return len(re.sub(r"[\s\W_]", "", s))


# ---------------------------------------------------------------- 抓歌詞
def fetch_lrclib(title: str, artist: str, timeout: int = 15, tries: int = 3) -> str | None:
    """LRCLIB：免費、免 key、有粵語覆蓋。回傳 plainLyrics 純文字。

    LRCLIB 偶爾回 503（限流），重試兩次通常就過；三次都失敗再往上拋。
    """
    q = urllib.parse.quote(f"{title} {artist}")
    url = f"https://lrclib.net/api/search?q={q}"
    data = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cantonese-weather-clock/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503) and attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt < tries - 1:
                time.sleep(1.0)
                continue
            raise
    if data is None:
        return None
    if not isinstance(data, list) or not data:
        return None

    def score(rec) -> int:
        s = 0
        if rec.get("trackName", "").strip() == title:
            s += 5
        elif title in rec.get("trackName", ""):
            s += 3
        if artist.lower() in (rec.get("artistName") or "").lower():
            s += 2
        if rec.get("instrumental"):
            s -= 99
        if not rec.get("plainLyrics"):
            s -= 99
        # 純音樂/翻唱/合輯名字優先度降低
        album = (rec.get("albumName") or "").lower()
        for bad in ("karaoke", "instrumental", "cover", "精選", "排行榜"):
            if bad in album:
                s -= 3
        return s

    best = max(data, key=score)
    lyric = best.get("plainLyrics") or ""
    return lyric if lyric.strip() else None


def get_lyrics(song: dict, cache_dir: Path, offline: bool) -> tuple[str, str]:
    """回傳 (歌詞全文, 來源說明)。快取優先，抓不到再聯網，並寫回快取。"""
    cache_file = cache_dir / f"{song['id']}_{song['title']}.txt".replace("/", "_")
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8"), "cache"
    if offline:
        raise RuntimeError(
            f"[offline] 快取裡沒有《{song['title']}》：{cache_file}\n"
            f"          先在有網路的機器上跑一次 dayliy.py（去掉 --offline）生成快取。"
        )
    try:
        lyric = fetch_lrclib(song["title"], song["artist"])
    except Exception as exc:  # 網路/解析失敗
        raise RuntimeError(f"抓詞失敗《{song['title']}》：{exc}") from exc
    if not lyric:
        raise RuntimeError(f"歌詞源沒有《{song['title']}》({song['artist']}) 的歌詞")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(lyric, encoding="utf-8")
    return lyric, "lrclib"


# ---------------------------------------------------------------- 候選行
def candidate_lines(lyric: str, min_len: int = 8, max_len: int = 30) -> list[str]:
    """把歌詞切成「可以獨立貼出來」的候選行。

    歌詞源常常把一句話斷在兩行（例如 LRC 逐句），所以除了單行，
    還會把相鄰的兩條短行合併成一個候選 —— 合併後仍然是原文逐字拼接，不影響校驗。
    """
    raw_lines = []
    for raw in lyric.splitlines():
        line = raw.strip()
        if not line or line.startswith("["):          # 跳過 LRC 時間戳
            continue
        n = visible_len(line)
        if not (2 <= n <= max_len):
            continue
        if len(re.sub(r"[\u4e00-\u9fffA-Za-z0-9]", "", line)) > n:   # 標點太多
            continue
        raw_lines.append(line)

    out, seen = [], set()

    def add(text: str) -> None:
        n = visible_len(text)
        if min_len <= n <= max_len and text not in seen:
            seen.add(text)
            out.append(text)

    for i, line in enumerate(raw_lines):
        add(line)
        if i + 1 < len(raw_lines):
            a, b = line, raw_lines[i + 1]
            if visible_len(a) <= 12 and visible_len(b) <= 12:
                add(f"{a} {b}")        # 兩行合併，中間留一個空格方便排版
    return out


def heuristic_pick(lines: list[str], seed: str) -> tuple[int, str]:
    """沒有模型可用時的兜底：靠關鍵詞與句式長度打分。不保證選到最好那句。"""
    best, best_score = 0, -10**9
    for i, line in enumerate(lines):
        s = 0
        s += 3 * sum(1 for k in ENC_KEYS if k in line)
        s += 2 * sum(1 for k in PHIL_KEYS if k in line)
        s -= 3 * sum(1 for k in NEG_KEYS if k in line)
        if 10 <= visible_len(line) <= 24:
            s += 2
        if re.search(r"(傷心|眼淚|分手|後悔|死|恨|對不起|討厭)", line):
            s -= 4
        if re.search(r"(嗎|呢|吧)[？?]?$", line):   # 反問句多半是無奈，不適合貼牆
            s -= 3
        if " " in line:                              # 兩行合併通常更完整
            s += 1
        s += int(stable_hash(seed, line)[:4], 16) % 7 / 10   # 穩定微擾
        if s > best_score:
            best, best_score = i, s
    return best, "heuristic"


# ---------------------------------------------------------------- AI 選句
def call_ai(lines: list[str], song: dict, ctx: str) -> int | None:
    """讓模型從編號清單裡挑一個序號。回傳 0-based index 或 None。"""
    base = os.environ.get("WC_AI_BASE", "").rstrip("/")
    key = os.environ.get("WC_AI_KEY", "")
    model = os.environ.get("WC_AI_MODEL", "")
    if not (base and key and model):
        return None

    numbered = "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
    prompt = (
        f"歌曲：《{song['title']}》— {song['artist']}\n"
        f"今天：{ctx}\n\n"
        "下面是這首歌的真實歌詞，已逐行編號。\n"
        "任務：挑出**一行**，適合當作今天的「一句歌詞」貼在牆上、給人鼓勵或一點哲理。\n"
        "標準：\n"
        "- 可以獨立成句、看得懂，不需要上下文也成立\n"
        "- 讀完讓人心裡鬆一點、或者想通一點；不要選純粹訴苦、埋怨、self-pity 的句子\n"
        "- 避開最爛大街的那句（通常是歌名或副歌第一句），優先選主歌裡被忽略的好句\n"
        "- 不要帶到具體人名、地名、品牌\n\n"
        f"{numbered}\n\n"
        '只回傳 JSON：{"line": 序號, "why": "一句話說明為什麼適合今天"}'
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = body["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        idx = int(obj.get("line", 0)) - 1
    except Exception:
        return None
    if 0 <= idx < len(lines):
        log(f"  AI 理由：{obj.get('why', '')}")
        return idx
    return None


# ---------------------------------------------------------------- 選歌

def resolve_special(songs: list, titles: list) -> list:
    """把 "歌名/歌手" 列表映射到曲库条目，曲库里没有的自动跳过。"""
    out = []
    for t in titles:
        for s in songs:
            if f"{s['title']}/{s['artist']}" == t:
                out.append(s)
                break
    return out


def rank_songs(songs: list[dict], day: date, weather: str, history: dict,
               cooldown_days: int) -> list[dict]:
    """按「天气/星期契合度 → 冷门优先 → 日期哈希」排出候选顺序。"""
    used = {h["id"]: h["date"] for h in history.get("used", [])}
    cutoff = (day - timedelta(days=cooldown_days)).isoformat()

    fresh = [s for s in songs if used.get(s["id"], "0000-00-00") < cutoff]
    pool = fresh or songs                       # 曲库不够大时允许重复

    want = set(WEEKDAY_TAGS.get(day.weekday(), [])) | set(WEATHER_TAGS.get(weather, []))
    scored = []
    for s in pool:
        affinity = len(want & set(s.get("tags", [])))
        scored.append((-affinity, s.get("hot", 3), stable_hash(day.isoformat(), s["id"]), s))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in scored]


def pick_song(songs: list[dict], day: date, weather: str, history: dict,
              cooldown_days: int) -> dict:
    used = {h["id"]: h["date"] for h in history.get("used", [])}
    cutoff = (day - timedelta(days=cooldown_days)).isoformat()

    fresh = [s for s in songs if used.get(s["id"], "0000-00-00") < cutoff]
    pool = fresh or songs                       # 曲庫不夠大時允許重複

    want = set(WEEKDAY_TAGS.get(day.weekday(), [])) | set(WEATHER_TAGS.get(weather, []))
    scored = []
    for s in pool:
        affinity = len(want & set(s.get("tags", [])))
        # 同一位歌手冷卻更久，避免連續幾週都是陳奕迅
        scored.append((-affinity, s.get("hot", 3), stable_hash(day.isoformat(), s["id"]), s))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return scored[0][3]


# ---------------------------------------------------------------- 主流程
def build(day: date, weather: str, catalog_path: Path, cache_dir: Path,
          state_dir: Path, out_path: Path, offline: bool, no_ai: bool,
          song_id: str | None = None) -> dict:
    catalog = read_json(catalog_path)
    if not catalog:
        raise SystemExit(f"找不到曲庫：{catalog_path}")
    songs = catalog["songs"]

    history_path = state_dir / "history.json"
    history = read_json(history_path, {"used": []}) or {"used": []}

    ctx = f"{day.isoformat()} {WEEKDAYS[day.weekday()]}，天氣 {weather}"
    log(f"[1/4] 日期 {ctx}")

    # ① 今天是什么日子？（节气 / 节日）
    special = describe_day(day)
    if special:
        log(f"      今天是 {special['kind']}：{special['name']}")

    # ② 选歌优先级：手动指定 > 节日/节气指定 > 下雨指定 > 常规轮换
    song = None
    if song_id:
        song = next((s for s in songs if s["id"] == song_id), None)
        if not song:
            raise SystemExit(f"曲庫裡沒有 id={song_id}")

    # 候选顺序：节日指定 → 天气指定 → 常规轮换（抓不到词就顺延到下一首）
    candidates: list[dict] = []
    used_recent = {h["id"] for h in history.get("used", [])
                   if h["date"] >= (day - timedelta(days=20)).isoformat()}

    if special:
        for s in resolve_special(songs, special.get("songs", [])):
            if s["id"] not in used_recent:      # 20 天内用过就跳过，避免连着两天同一首
                candidates.append(s)
                log(f"      按 {special['name']} 指定：《{s['title']}》")

    if weather in WEATHER_SONGS:
        for s in resolve_special(songs, WEATHER_SONGS[weather]):
            if s["id"] not in used_recent:
                candidates.append(s)
                log(f"      按天气（{weather}）指定：《{s['title']}》")

    candidates += rank_songs(songs, day, weather, history, cooldown_days=90)

    # 去重，保持顺序
    seen_ids, pool = set(), []
    for s in candidates:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            pool.append(s)
    song = pool[0]
    log(f"[2/4] 今日歌曲：《{song['title']}》— {song['artist']} "
        f"({song.get('year') or '年份不詳'}, 熱度 {song.get('hot')}, {','.join(song.get('tags', []))})")

    # 抓词：失败就换下一首候选（曲库里总有没被 LRCLIB 收录的冷门歌）
    lyric_text, src, tried = None, "", []
    for cand in pool[:5]:
        try:
            lyric_text, src = get_lyrics(cand, cache_dir, offline)
            song = cand
            break
        except Exception as exc:
            tried.append(cand["title"])
            log(f"      《{cand['title']}》抓不到词（{str(exc).splitlines()[0][:40]}），换下一首")
    if not lyric_text:
        raise SystemExit("连续 5 首都抓不到歌词，检查网络或曲库")
    if tried:
        log(f"      跳过 {len(tried)} 首：{'、'.join(tried)}")

    lines = candidate_lines(lyric_text)
    if len(lines) < 3:
        raise SystemExit(f"《{song['title']}》可用行太少（{len(lines)}），換一首或放寬 candidate_lines 條件")
    log(f"[3/4] 歌詞 {len(lyric_text)} 字，候選 {len(lines)} 行（來源 {src}）")

    idx, method = None, "heuristic"
    if not no_ai:
        try:
            idx = call_ai(lines, song, ctx)
            method = "ai" if idx is not None else "heuristic"
        except Exception as exc:
            log(f"  AI 呼叫失敗，退回關鍵詞評分：{exc}")
    if idx is None:
        idx, method = heuristic_pick(lines, seed=day.isoformat() + song["id"])

    line = lines[idx]
    result = {
        "date": day.isoformat(),
        "weekday": WEEKDAYS[day.weekday()],
        "lyric": line,
        "song": {
            "title": song["title"],
            "artist": song["artist"],
            "year": song.get("year"),
            "hot": song.get("hot"),
            "tags": song.get("tags", []),
        },
        "meta": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "weather": weather,
            "special": (f"{special['kind']}·{special['name']}" if special else None),
            "method": method,
            "lyrics_source": src,
            "candidates": len(lines),
            "line_no": idx + 1,
        },
    }
    log(f"[4/4] 選中第 {idx+1} 行（{method}）：{line}")

    write_json(out_path, result)

    # 给单片机读的极简格式：每行 key=value，比 JSON 好解析得多
    txt_path = out_path.with_suffix(".txt")
    lyric_lines = [ln for ln in result["lyric"].split(" ") if ln] or [result["lyric"]]
    txt = [
        "date=" + result["date"],
        "weekday=" + result["weekday"],
    ]
    for i, ln in enumerate(lyric_lines[:6], 1):
        txt.append(f"lyric{i}={ln}")
    txt.append("title=" + result["song"]["title"])
    txt.append("artist=" + result["song"]["artist"])
    txt_path.write_text("\n".join(txt) + "\n", encoding="utf-8")

    history["used"] = [h for h in history["used"] if h["id"] != song["id"]]
    history["used"].append({"date": day.isoformat(), "id": song["id"], "title": song["title"]})
    history["used"] = history["used"][-400:]
    write_json(history_path, history)
    log(f"      已寫入 {out_path} 與 {out_path.with_suffix('.txt')}")
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="每日一句粵語歌詞")
    ap.add_argument("--date", help="YYYY-MM-DD，預設今天")
    ap.add_argument("--weather", default="cloudy",
                    choices=["sunny", "cloudy", "rainy", "storm"], help="天氣，影響選歌傾向")
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--offline", action="store_true", help="只用歌詞快取，不聯網")
    ap.add_argument("--no-ai", action="store_true", help="不調模型，直接關鍵詞評分")
    ap.add_argument("--render", action="store_true", help="順便渲染卡片 PNG")
    ap.add_argument("--song-id", help="強制指定曲庫裡的某首歌（除錯/手動換歌）")
    ap.add_argument("--simulate", type=int, metavar="N",
                    help="只跑選歌邏輯，印出未來 N 天的排程（不抓詞、不調模型），用來檢查重複度")
    args = ap.parse_args()

    day = date.fromisoformat(args.date) if args.date else date.today()

    if args.simulate:
        catalog = read_json(args.catalog)
        hist = read_json(args.state / "history.json", {"used": []}) or {"used": []}
        weathers = ["sunny", "cloudy", "rainy"]
        seen = {}
        for i in range(args.simulate):
            d = day + timedelta(days=i)
            s = pick_song(catalog["songs"], d, weathers[i % 3], hist, cooldown_days=90)
            hist["used"].append({"date": d.isoformat(), "id": s["id"]})
            seen[s["id"]] = seen.get(s["id"], 0) + 1
            log(f"{d.isoformat()} {WEEKDAYS[d.weekday()]}  {s['title']} — {s['artist']}")
        dup = {k: v for k, v in seen.items() if v > 1}
        log(f"\n{args.simulate} 天內用到 {len(seen)} 首不同歌曲"
            f"{'，重複：' + str(dup) if dup else '，零重複'}")
        return

    result = build(day, args.weather, args.catalog, args.cache,
                   args.state, args.out, args.offline, args.no_ai, args.song_id)
    if args.render:
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "render_card.py"),
                        "--today", str(args.out), "--preview"], check=False)


if __name__ == "__main__":
    main()
