#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从歌词 + UI 文案生成「子集点阵字库」，输出 C 头文件给单片机用。

为什么要自己生成：
  · U8g2 自带的中文字库是简体 GB2312，歌詞是繁體（願/謝/鐘/讓 不在里面）
  · AVR 版 U8g2 干脆没编中文字体（引用就链接失败）
  · 整套 GBK 太大，而我们只需要「曲库里出现过的字」

字库格式（见输出文件头注释）：
  码位表按升序排列，位图数据与之一一对应，每字 24 字节（12 行 × 2 字节）。
  运行时：UTF-8 解码成码位 → 线性查表 → 逐像素画到 U8g2 的缓冲里。

用法：
  python tools/make_font.py                     # 12px，输出 esp32/lyric_clock/cnfont.h
  python tools/make_font.py --size 16           # 16px（2.08 吋用）
  python tools/make_font.py --preview out.png   # 顺便渲染一张预览，检查字有没有糊
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"

# 界面上固定出现的字（不算歌曲本身）
UI_TEXT = (
    "每日一句粤语歌"
    "时间天气湿度雨最高低多云阴晴小中大雷阵雪雾今日星期一二三四五六日"
    "上午下午凌晨傍晚更新离线连接失败请检查无线网络"
    "好景不会每日常在天梯不可只往上爬"
    "喜帖街谢安琪林夕"
)

# ASCII 用 U8g2 自带字体，这里只收汉字和全角标点
def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (0x3000 <= o <= 0x303F)


def collect_chars() -> tuple[set, dict]:
    """从 cache/*.txt（歌词）、catalog.json（歌名/歌手）、UI 文案里收集所有汉字。"""
    chars = set(c for c in UI_TEXT if is_cjk(c))
    stat = {"ui": len(chars), "lyrics": 0, "catalog": 0}

    for f in sorted((ROOT / "cache").glob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        got = set(c for c in text if is_cjk(c))
        stat["lyrics"] += len(got - chars)
        chars |= got

    cat = ROOT / "catalog.json"
    if cat.exists():
        data = json.loads(cat.read_text(encoding="utf-8"))
        got = set()
        for s in data.get("songs", []):
            for k in ("title", "artist"):
                got |= set(c for c in str(s.get(k, "")) if is_cjk(c))
            for t in s.get("tags", []):
                got |= set(c for c in t if is_cjk(c))
        stat["catalog"] = len(got - chars)
        chars |= got

    return chars, stat


def render_glyph(ch: str, size: int, font) -> bytes:
    """把一个字渲染成 size×size 的 1bit 位图，按行存成 2 字节/行。"""
    img = Image.new("1", (size, size), 0)
    d = ImageDraw.Draw(img)
    d.text((size / 2, size / 2), ch, font=font, fill=1, anchor="mm")

    rows = bytearray()
    for y in range(size):
        bits = 0
        for x in range(size):
            if img.getpixel((x, y)):
                bits |= 1 << (15 - x)          # 高位在左，方便 MSB-first 读
        rows += bytes([(bits >> 8) & 0xFF, bits & 0xFF])
    return bytes(rows)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=12, help="字库点阵尺寸，12 或 16")
    ap.add_argument("--out", type=Path, default=None,
                    help="指定输出路径；默认为两个 sketch 目录各写一份")
    ap.add_argument("--preview", type=Path, default=None, help="渲染一张预览 PNG")
    args = ap.parse_args()

    size = args.size
    chars, stat = collect_chars()
    ordered = sorted(chars)
    font = ImageFont.truetype(FONT_PATH, size)

    data = b"".join(render_glyph(c, size, font) for c in ordered)
    per = len(data) // max(1, len(ordered))

    # ---------------- 生成头文件 ----------------
    lines = []
    lines.append("// 本文件由 tools/make_font.py 自动生成，请不要手改。")
    lines.append(f"// 字集来源：UI 固定文案 + cache/ 里的歌词 + catalog.json 的歌名歌手")
    lines.append(f"// 字号 {size}px，共 {len(ordered)} 字，位图 {len(data)} 字节（每字 {per} 字节）")
    lines.append("//")
    lines.append("// 用法：drawCN(u8g2, x, y, '好') 或 drawCNText(u8g2, x, y, \"好景不會\")")
    lines.append("#pragma once")
    lines.append("#include <Arduino.h>")
    lines.append("#include <U8g2lib.h>")
    lines.append("")
    lines.append(f"#define CN_W {size}")
    lines.append(f"#define CN_H {size}")
    lines.append(f"#define CN_BYTES_PER_GLYPH {per}")
    lines.append(f"#define CN_COUNT {len(ordered)}")
    lines.append("")
    lines.append(f"static const uint16_t cn_cp[CN_COUNT] PROGMEM = {{")
    for i in range(0, len(ordered), 12):
        chunk = ", ".join(f"0x{ord(c):04X}" for c in ordered[i:i + 12])
        lines.append("  " + chunk + ",")
    lines.append("};")
    lines.append("")
    lines.append("static const uint8_t cn_bitmap[] PROGMEM = {")
    for i in range(0, len(data), 16):
        chunk = ", ".join(f"0x{b:02X}" for b in data[i:i + 16])
        lines.append("  " + chunk + ",")
    lines.append("};")
    lines.append("")
    lines.append("// 查表：返回位图在 cn_bitmap 里的偏移，找不到返回 -1")
    lines.append("inline int cnFind(uint16_t cp) {")
    lines.append("  int lo = 0, hi = CN_COUNT - 1;")
    lines.append("  while (lo <= hi) {")
    lines.append("    int mid = (lo + hi) >> 1;")
    lines.append("    uint16_t v = pgm_read_word(&cn_cp[mid]);")
    lines.append("    if (v == cp) return mid * CN_BYTES_PER_GLYPH;")
    lines.append("    if (v < cp) lo = mid + 1; else hi = mid - 1;")
    lines.append("  }")
    lines.append("  return -1;")
    lines.append("}")
    lines.append("")
    lines.append("// 垂直裁剪窗口：滚动的歌词只在视口内绘制")
    lines.append("// 用法：cnClipTop = 32; cnClipBot = 63;  ...画字...; cnClipTop = -32768; cnClipBot = 32767;")
    lines.append("static int16_t cnClipTop = -32768;")
    lines.append("static int16_t cnClipBot =  32767;")
    lines.append("")
    lines.append("// 画一个汉字；返回 true 表示字库里有这个字")
    lines.append("inline bool drawCN(U8G2 &u8g2, int x, int y, uint16_t cp) {")
    lines.append("  int off = cnFind(cp);")
    lines.append("  if (off < 0) return false;")
    lines.append("  for (int r = 0; r < CN_H; r++) {")
    lines.append("    int gy = y + r;")
    lines.append("    if (gy < cnClipTop || gy > cnClipBot) continue;")
    lines.append("    uint16_t bits = ((uint16_t)pgm_read_byte(&cn_bitmap[off + r * 2]) << 8)")
    lines.append("                  | pgm_read_byte(&cn_bitmap[off + r * 2 + 1]);")
    lines.append("    if (!bits) continue;")
    lines.append("    for (int c = 0; c < CN_W; c++) {")
    lines.append("      if (bits & (0x8000 >> c)) u8g2.drawPixel(x + c, gy);")
    lines.append("    }")
    lines.append("  }")
    lines.append("  return true;")
    lines.append("}")
    lines.append("")
    lines.append("// 画一串 UTF-8 汉字，返回画完后下一个字的 x 坐标")
    lines.append("inline int drawCNText(U8G2 &u8g2, int x, int y, const char *s) {")
    lines.append("  while (*s) {")
    lines.append("    uint16_t cp; uint8_t b = (uint8_t)*s;")
    lines.append("    if (b < 0x80) { cp = b; s += 1; }")
    lines.append("    else if ((b & 0xE0) == 0xC0) { cp = ((b & 0x1F) << 6) | (s[1] & 0x3F); s += 2; }")
    lines.append("    else if ((b & 0xF0) == 0xE0) { cp = ((b & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F); s += 3; }")
    lines.append("    else { s += 1; continue; }")
    lines.append("    if (!drawCN(u8g2, x, y, cp)) {")
    lines.append("      // 字库里没有：画一个空心方块占位，方便一眼看出缺字")
    lines.append("      u8g2.drawFrame(x + 1, y + 1, CN_W - 2, CN_H - 2);")
    lines.append("    }")
    lines.append("    x += CN_W;")
    lines.append("  }")
    lines.append("  return x;")
    lines.append("}")
    lines.append("")

    targets = [args.out] if args.out else [
        ROOT / "esp32" / "lyric_clock" / "cnfont.h",
        ROOT / "esp32" / "oled_weather_clock" / "cnfont.h",
    ]
    text = "\n".join(lines)
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
        print(f"已生成 {t}")
    print(f"  字集来源：UI {stat['ui']} 字，歌词新增 {stat['lyrics']} 字，歌名歌手新增 {stat['catalog']} 字")
    print(f"  共 {len(ordered)} 字 × {per} 字节 = {len(data)} 字节（{len(data)/1024:.1f} KB）")
    print(f"  12px 下每行可放 {128 // size} 字（128 宽屏） / {256 // size} 字（256 宽屏）")

    # ---------------- 预览：直接用位图数据渲染，验证字库本身 ----------------
    if args.preview:
        W, H = 128, 64
        img = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(img)
        order = [ord(c) for c in ordered]

        def put_cn(ch, x, y):
            try:
                i = order.index(ord(ch))
            except ValueError:
                return False
            off = i * per
            for r in range(size):
                bits = (data[off + r * 2] << 8) | data[off + r * 2 + 1]
                for c in range(size):
                    if bits & (0x8000 >> c):
                        d.point((x + c, y + r), fill=255)
            return True

        def put_ascii(s, x, y, font):
            d.text((x, y), s, font=font, fill=255)

        f5 = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 8)
        f20 = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 21)

        put_ascii("SAT 10.17", 2, 0, f5)
        put_ascii("26°", 100, 0, f5)
        put_ascii("22:19", 2, 9, f20)
        for x in range(0, W, 3):
            d.point((x, 34), fill=255)
        preview_lyric = ["好景不會每日常在", "天梯不可只往上爬", "階磚不會拒絕磨蝕",
                         "窗花不可幽禁落霞", "有感情就會一生一世嗎"]
        for i, line in enumerate(preview_lyric):
            y = 36 + i * (size + 2)
            if y > H - 1:
                break
            for j, ch in enumerate(line):
                if put_cn(ch, 4 + j * size, y) is False:
                    pass
                # 模拟设备的垂直裁剪
                for c in range(size):
                    for r in range(size):
                        if y + r > H - 1:
                            d.point((4 + j * size + c, y + r), fill=0)

        img.resize((W * 4, H * 4), Image.NEAREST).save(args.preview)
        print(f"已输出预览 {args.preview}（左边是设备上的真实像素，放大 4 倍）")


if __name__ == "__main__":
    main()
