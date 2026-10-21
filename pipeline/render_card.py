#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 today.json 渲染成 480×320 的卡片 PNG。

為什麼要「後端畫圖」而不是在單片機上寫中文？
  ESP32 沒有中文字庫，塞一套 24px 點陣字庫要幾百 KB，而且歌詞是繁體、
  字集隨時變。改成後端用系統字體畫好 PNG、設備只負責 pushImage()，
  一行中文相關的代碼都不用寫，換字體、換排版也只改這裡。

卡片的內容分工（重要）：
  · 日期 / 星期 / 今日天氣 / 歌詞  → 烘焙進 PNG，一天生成一次
  · 時:分                          → 留白，由設備自己每分鐘用數字字體畫
  這樣卡片不會過時（天氣用「今日預報」而不是「此刻溫度」），
  設備也不必為中文顯示操心。

用法：
  python pipeline/render_card.py                    # 抓天氣 + 畫卡片 → site/card.png
  python pipeline/render_card.py --preview          # 順便輸出帶時間的預覽圖
  python pipeline/render_card.py --desc 多雲 --hi 30 --lo 23 --pop 20   # 手動指定天氣
"""

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 480, 320
PAPER = (247, 243, 234)
INK = (31, 27, 22)
DIM = (128, 118, 104)
ACCENT = (168, 68, 42)
LINE = (214, 205, 189)

# Open-Meteo WMO weather code → 中文
WMO = {
    0: "晴", 1: "大致晴朗", 2: "多雲", 3: "陰", 45: "霧", 48: "霧",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "凍雨", 67: "凍雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "雪",
    80: "陣雨", 81: "陣雨", 82: "大雨", 85: "陣雪", 86: "陣雪",
    95: "雷雨", 96: "雷雨", 99: "雷雨",
}

FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),          # 微軟雅黑 Bold
    (r"C:\Windows\Fonts\msyh.ttc", 0),            # 微軟雅黑
    (r"C:\Windows\Fonts\simhei.ttf", 0),          # 黑體
    ("/System/Library/Fonts/PingFang.ttc", 0),    # macOS
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),  # Linux
]


def load_font(size: int, bold: bool = True):
    order = FONT_CANDIDATES if bold else FONT_CANDIDATES[1:] + FONT_CANDIDATES[:1]
    for path, idx in order:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def text_w(draw, s: str, font) -> int:
    box = draw.textbbox((0, 0), s, font=font)
    return box[2] - box[0]


def wrap(draw, text: str, font, max_w: int) -> list[str]:
    """先按空格斷句（歌詞常是兩句拼接），單句過寬才逐字硬切。"""
    out = []
    for chunk in text.split():
        if text_w(draw, chunk, font) <= max_w:
            out.append(chunk)
            continue
        cur = ""
        for ch in chunk:
            if text_w(draw, cur + ch, font) <= max_w or not cur:
                cur += ch
            else:
                out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
    return out[:3]


def draw_weather_icon(draw, cx: int, cy: int, desc: str, scale: float = 1.0) -> None:
    """手繪天氣圖示，避免依賴 emoji 字體（不同系統的 emoji 差很多）。"""
    s = scale
    rainy = any(k in desc for k in ("雨", "雷", "雪"))
    sunny = ("晴" in desc) and not rainy

    def rays(x, y, r1, r2, color, w):
        for k in range(8):
            a = math.radians(k * 45)
            draw.line([x + math.cos(a) * r1, y + math.sin(a) * r1,
                       x + math.cos(a) * r2, y + math.sin(a) * r2],
                      fill=color, width=w)

    if sunny:
        r = 11 * s
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(224, 164, 58))
        rays(cx, cy, r + 3 * s, r + 9 * s, (224, 164, 58), max(2, int(2 * s)))
        return

    sr = 9 * s                                  # 太陽躲在雲後，只露一角
    sx, sy = cx - 13 * s, cy - 15 * s
    draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(224, 164, 58))
    rays(sx, sy, sr + 2 * s, sr + 6 * s, (224, 164, 58), max(2, int(1.8 * s)))

    cloud = (150, 154, 160) if rainy else (176, 179, 185)
    by = cy + 3 * s
    draw.ellipse([cx - 15 * s, by - 6 * s, cx + 3 * s, by + 10 * s], fill=cloud)
    draw.ellipse([cx - 4 * s, by - 12 * s, cx + 16 * s, by + 6 * s], fill=cloud)
    draw.rounded_rectangle([cx - 17 * s, by + 2 * s, cx + 17 * s, by + 9 * s],
                           radius=int(4 * s), fill=cloud)
    if rainy:
        for dx in (-10, -1, 8):
            draw.line([cx + dx * s, by + 13 * s, cx + (dx - 3) * s, by + 21 * s],
                      fill=(90, 130, 170), width=max(2, int(1.6 * s)))


def fetch_weather(lat: float, lon: float, tz: str) -> dict:
    """Open-Meteo：免 key、免註冊。取今日預報（不是此刻溫度，卡片才不會過時）。"""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&current=temperature_2m,weather_code"
           f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
           f"precipitation_probability_max&timezone={tz}&forecast_days=1")
    req = urllib.request.Request(url, headers={"User-Agent": "cantonese-weather-clock/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    d = j["daily"]
    return {
        "desc": WMO.get(d["weather_code"][0], "—"),
        "hi": round(d["temperature_2m_max"][0]),
        "lo": round(d["temperature_2m_min"][0]),
        "pop": d["precipitation_probability_max"][0],
        "now": round(j["current"]["temperature_2m"]),
    }


def render(today: dict, out_path: Path, time_text: str | None = None,
           desc: str | None = None, hi: int | None = None, lo: int | None = None,
           pop: int | None = None, city: str | None = None) -> Path:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    f_date = load_font(20, bold=False)
    f_time = load_font(64)
    f_hi = load_font(38)
    f_label = load_font(13, bold=False)
    f_meta = load_font(17, bold=False)
    f_lyric = load_font(33)
    f_credit = load_font(16, bold=False)
    f_desc = load_font(21)

    d.rounded_rectangle([8, 8, W - 9, H - 9], radius=10, outline=LINE, width=2)

    # 頂部：日期 · 城市 / 星期
    head = today["date"].replace("-", ".")
    if city:
        head += f" · {city}"
    d.text((26, 22), head, font=f_date, fill=DIM)
    wk = today.get("weekday", "")
    d.text((W - 26 - text_w(d, wk, f_date), 22), wk, font=f_date, fill=DIM)

    # 時間：設備自己畫，這裡只在預覽時填
    if time_text:
        d.text((26, 50), time_text, font=f_time, fill=INK)

    # 天氣：右上角
    if desc:
        draw_weather_icon(d, 332, 68, desc, scale=1.1)
        if hi is not None:
            big = f"{hi}°"
            bw = text_w(d, big, f_hi)
            d.text((W - 28, 90), big, font=f_hi, fill=INK, anchor="rs")
            d.text((W - 28 - bw - 6, 90), "最高", font=f_label, fill=DIM, anchor="rs")
        bits = [desc]
        if lo is not None:
            bits.append(f"低 {lo}°")
        if pop is not None:
            bits.append(f"雨 {pop}%")
        d.text((W - 28, 114), " · ".join(bits), font=f_meta, fill=DIM, anchor="rs")

    d.line([26, 136, W - 26, 136], fill=LINE, width=2)

    # 歌詞
    lyric = today.get("lyric", "")
    lines = wrap(d, lyric, f_lyric, W - 100)
    lead = 46
    block_h = len(lines) * lead
    top = 152 + max(0, (96 - block_h) // 2)
    d.rounded_rectangle([30, top + 4, 34, top + block_h - 12], radius=2, fill=ACCENT)
    for i, ln in enumerate(lines):
        d.text((52, top + i * lead), ln, font=f_lyric, fill=INK)

    # 出處
    song = today.get("song", {})
    credit = f"《{song.get('title', '')}》 {song.get('artist', '')}"
    if song.get("year"):
        credit += f" · {song['year']}"
    d.text((W - 30 - text_w(d, credit, f_credit), H - 40), credit, font=f_credit, fill=DIM)
    d.text((28, H - 40), "每日一句 · 粵語歌", font=f_credit, fill=(178, 168, 152))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    if out_path.suffix.lower() == ".png":
        # 同一張圖順便存一份 JPEG：設備（ESP32）用 TJpg_Decoder 解 JPEG 比解 PNG 省記憶體
        img.save(out_path.with_suffix(".jpg"), quality=88, optimize=True)
    return out_path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=Path, default=ROOT / "site" / "today.json")
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "card.png")
    ap.add_argument("--config", type=Path, default=ROOT / "config.json")
    ap.add_argument("--preview", action="store_true", help="額外輸出一張帶時間/天氣的預覽圖")
    ap.add_argument("--preview-out", type=Path, default=None)
    ap.add_argument("--time", default="09:41", help="預覽圖上的時間")
    ap.add_argument("--desc", help="天氣描述，給定則不聯網抓取")
    ap.add_argument("--hi", type=int)
    ap.add_argument("--lo", type=int)
    ap.add_argument("--pop", type=int, help="降雨機率 %")
    args = ap.parse_args()

    today = json.loads(args.today.read_text(encoding="utf-8"))
    cfg = {}
    if args.config.exists():
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
    city = cfg.get("city", "廣州")

    wx = {"desc": args.desc, "hi": args.hi, "lo": args.lo, "pop": args.pop}
    if not args.desc:
        try:
            got = fetch_weather(cfg.get("lat", 23.13), cfg.get("lon", 113.26),
                                cfg.get("tz", "Asia/Shanghai"))
            wx.update(desc=got["desc"], hi=got["hi"], lo=got["lo"], pop=got["pop"])
            print(f"天氣：{got['desc']} {got['lo']}–{got['hi']}° 雨 {got['pop']}%")
        except Exception as exc:
            print(f"天氣抓取失敗（先畫卡片，天氣留白）：{exc}")

    render(today, args.out, city=city, **wx)
    print(f"已輸出 {args.out}（時間區域留白，由設備繪製）")

    if args.preview:
        prev = args.preview_out or args.out.with_name("preview.png")
        render(today, prev, time_text=args.time, city=city, **wx)
        print(f"已輸出 {prev}")


if __name__ == "__main__":
    main()

