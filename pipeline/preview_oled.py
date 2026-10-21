#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OLED / 賽博風版面的像素級預覽。

為什麼要單獨寫一套：單色屏只有 1 bit、128×64 或 256×64 像素，
上一版那張 480×320 的彩色卡片完全用不上。這裡按**真實像素尺寸**排版，
所以你在採購前就能看到「到底塞不塞得下」。

輸出：
  site/oled-128.png / -zoom.png    128×64（0.96"–1.3" SSD1306/SSD1309）
  site/oled-256.png / -zoom.png    256×64（2.08" SSD1322 寬屏）
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

LATIN = r"C:\Windows\Fonts\consola.ttf"
LATIN_B = r"C:\Windows\Fonts\consolab.ttf"
CJK = r"C:\Windows\Fonts\msyh.ttc"


def f(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def tw(d, s, font):
    b = d.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


def split_lyric(d, text, font, max_w, limit=2):
    """先按空格斷句（歌詞常是兩句拼接），單句過寬才逐字硬切。"""
    out = []
    for chunk in text.split():
        if tw(d, chunk, font) <= max_w:
            out.append(chunk)
            continue
        cur = ""
        for ch in chunk:
            if tw(d, cur + ch, font) <= max_w or not cur:
                cur += ch
            else:
                out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
    return out[:limit]


def pxicon(d, x, y, desc):
    """11×10 點陣天氣圖示（矩形拼，不用 emoji/字體）。"""
    rainy = any(k in desc for k in ("雨", "雷", "雪"))
    sunny = ("晴" in desc) and not rainy
    if sunny:
        d.rectangle([x + 3, y + 2, x + 6, y + 5], fill=1)          # 太陽本體 4×4
        d.line([x + 4, y, x + 5, y], fill=1)                       # 上
        d.line([x + 4, y + 7, x + 5, y + 7], fill=1)               # 下
        d.line([x + 1, y + 3, x + 1, y + 4], fill=1)               # 左
        d.line([x + 8, y + 3, x + 8, y + 4], fill=1)               # 右
        return
    d.rectangle([x + 2, y + 5, x + 9, y + 7], fill=1)     # 雲底
    d.rectangle([x + 4, y + 3, x + 7, y + 5], fill=1)     # 雲峰
    d.rectangle([x + 8, y + 4, x + 10, y + 5], fill=1)    # 雲尾
    if rainy:
        for dx in (3, 6, 9):
            d.line([x + dx, y + 8, x + dx, y + 9], fill=1)


# ------------------------------------------------------------------ 128×64
def face_128(today, wx, clock, dow):
    W, H = 128, 64
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)

    f_lbl = f(LATIN_B, 9)
    f_clk = f(LATIN_B, 23)
    f_cn = f(CJK, 10)

    d.rectangle([0, 0, 2, 9], fill=1)                       # 左側實心塊，像終端光標
    d.text((4, 0), f"{dow} {today['date'][5:].replace('-', '.')}", font=f_lbl, fill=1)
    t = f"{wx['hi']}°"
    d.text((W - 2 - tw(d, t, f_lbl), 0), t, font=f_lbl, fill=1)

    d.text((2, 9), clock, font=f_clk, fill=1)
    pxicon(d, W - 21, 15, wx["desc"])

    for x in range(0, W, 3):                                # 虛線分隔
        d.point((x, 35), fill=1)

    lines = split_lyric(d, today["lyric"], f_cn, W - 6)
    y = 37 if len(lines) > 1 else 45
    for i, ln in enumerate(lines):
        d.text((3, y + i * 11), ln, font=f_cn, fill=1)
    return img


# ------------------------------------------------------------------ 256×64
def face_256(today, wx, clock, dow):
    W, H = 256, 64
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)

    f_clk = f(LATIN_B, 24)
    f_lbl = f(LATIN_B, 9)
    f_sm = f(CJK, 9)

    # 第一行：時間
    d.text((3, 0), clock, font=f_clk, fill=1)
    head = f"{dow} {today['date'][5:].replace('-', '.')}"
    d.text((W - 4 - tw(d, head, f_lbl), 3), head, font=f_lbl, fill=1)

    # 時間右側：天氣；右側第二行：出處
    wxline = f"{wx['hi']}/{wx['lo']}° {wx['desc']}"
    d.text((96, 14), wxline, font=f_sm, fill=1)
    pxicon(d, 82, 13, wx["desc"])
    s = today["song"]
    credit = f"{s['title']}·{s['artist']}"
    d.text((W - 4 - tw(d, credit, f_sm), 14), credit, font=f_sm, fill=1)

    # 歌詞：兩行 16px，是這台機器的重點
    f_cn = f(CJK, 16)
    lines = split_lyric(d, today["lyric"], f_cn, W - 8, limit=2)
    y = 27 if len(lines) > 1 else 34
    for i, ln in enumerate(lines):
        d.text((4, y + i * 16), ln, font=f_cn, fill=1)
    return img


# ------------------------------------------------------------------ 著色
def glow(img, color=(0, 255, 200), scale=4, scan=True):
    big = img.convert("L").resize((img.width * scale, img.height * scale), Image.NEAREST)
    out = Image.new("RGB", big.size, (5, 7, 7))
    px, bp = out.load(), big.load()
    for y in range(big.height):
        for x in range(big.width):
            if bp[x, y] > 128:
                px[x, y] = color
            elif scan and (y // scale) % 2 == 0:
                px[x, y] = (9, 13, 13)
    ImageDraw.Draw(out).rectangle([0, 0, out.width - 1, out.height - 1], outline=(18, 38, 36))
    return out


# ------------------------------------------------------------------ 尺寸對比
def compare(today, wx, clock, dow, out_path):
    """把幾塊屏按**真實物理尺寸**並排畫出來（同一個 mm 比例）。

    像素密度 = 對角線像素 / 對角線吋數；這裡取 5 px/mm，
    剛好讓 2.08" 256×64 那塊 1:1 呈現，其餘按比例縮放。
    """
    SCALE = 5.0                     # px per mm
    panels = [
        (face_128(today, wx, clock, dow), 1.3, "1.3\" 128x64  SSD1309"),
        (face_128(today, wx, clock, dow), 2.42, "2.42\" 128x64  SSD1309"),
        (face_256(today, wx, clock, dow), 2.08, "2.08\" 256x64  SSD1322"),
    ]

    f_lbl = f(CJK, 11)
    f_sm = f(LATIN, 10)
    pad, gap, label_w = 16, 14, 150

    # 先算畫布大小
    sizes, max_w = [], 0
    for img, inch, _ in panels:
        ppi = (img.width ** 2 + img.height ** 2) ** 0.5 / inch
        mm_w, mm_h = img.width / ppi * 25.4, img.height / ppi * 25.4
        w, h = round(mm_w * SCALE), round(mm_h * SCALE)
        sizes.append((w, h, mm_w, mm_h, ppi))
        max_w = max(max_w, w)
    total_h = sum(h for _, h, _, _, _ in sizes) + gap * (len(panels) - 1) + pad * 2 + 18

    canvas = Image.new("RGB", (pad * 2 + max_w + label_w, total_h), (12, 14, 14))
    d = ImageDraw.Draw(canvas)

    y = pad
    for (img, inch, name), (w, h, mm_w, mm_h, ppi) in zip(panels, sizes):
        scaled = img.convert("L").resize((w, h), Image.NEAREST)
        tinted = Image.new("RGB", (w, h), (0, 0, 0))
        tp, sp = tinted.load(), scaled.load()
        for yy in range(h):
            for xx in range(w):
                if sp[xx, yy] > 128:
                    tp[xx, yy] = (0, 255, 200)
        canvas.paste(tinted, (pad, y))
        d.rectangle([pad - 1, y - 1, pad + w, y + h], outline=(30, 60, 56))

        d.text((pad + w + 12, y + 2), name, font=f_lbl, fill=(210, 230, 226))
        d.text((pad + w + 12, y + 18), f"{mm_w:.0f} × {mm_h:.0f} mm  ·  {ppi:.0f} ppi",
               font=f_sm, fill=(120, 150, 146))
        d.text((pad + w + 12, y + 32),
               "每行 8–10 字" if img.width == 128 else "每行 16 字 × 2 行",
               font=f_lbl, fill=(200, 170, 90))
        y += h + gap

    # 10mm 比例尺
    y = total_h - pad - 8
    d.line([pad, y, pad + 10 * SCALE, y], fill=(150, 150, 150), width=2)
    d.line([pad, y - 3, pad, y + 3], fill=(150, 150, 150))
    d.line([pad + 10 * SCALE, y - 3, pad + 10 * SCALE, y + 3], fill=(150, 150, 150))
    d.text((pad + 10 * SCALE + 8, y - 6), "10 mm", font=f_sm, fill=(150, 150, 150))

    canvas.save(out_path)
    return canvas


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=Path, default=ROOT / "site" / "today.json")
    ap.add_argument("--time", default="22:19")
    ap.add_argument("--dow", default="SAT")
    ap.add_argument("--hi", type=int, default=34)
    ap.add_argument("--lo", type=int, default=25)
    ap.add_argument("--desc", default="晴")
    ap.add_argument("--pop", type=int, default=2)
    args = ap.parse_args()

    today = json.loads(args.today.read_text(encoding="utf-8"))
    wx = {"hi": args.hi, "lo": args.lo, "desc": args.desc, "pop": args.pop}

    out = ROOT / "site"
    for name, fn, size in (("oled-128", face_128, 4), ("oled-256", face_256, 3)):
        img = fn(today, wx, args.time, args.dow)
        img.save(out / f"{name}.png")
        glow(img, scale=size).save(out / f"{name}-zoom.png")
        print(f"已輸出 {name}.png ({img.width}×{img.height}) 與 {name}-zoom.png")

    compare(today, wx, args.time, args.dow, out / "oled-size-compare.png")
    print("已輸出 oled-size-compare.png（按真實物理尺寸比例）")

    n = len(today["lyric"].replace(" ", ""))
    print(f"\n歌詞：{today['lyric']}（{n} 字）")
    probe = ImageDraw.Draw(Image.new("1", (8, 8)))
    for px, fnt in ((128, f(CJK, 11)), (256, f(CJK, 16))):
        per = px // max(1, tw(probe, "國", fnt))
        print(f"  {px}px 寬 / {fnt.size}px 中文字 → 每行 {per} 字，兩行 {per * 2} 字"
              f"（今日 {n} 字 {'✓' if n <= per * 2 else '✗ 放不下'}）")


if __name__ == "__main__":
    main()
