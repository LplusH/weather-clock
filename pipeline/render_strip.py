#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把歌词渲染成 1bit 位图，设备直接显示像素。

为什么这样做：设备端用「子集字库」画字，只要出现没收录的字就是方框（口）。
AI 每天找新歌，字库永远追不上。改成服务器渲染，设备就不需要中文字库了。

输出 site/lyric.bin 格式（极简，设备端 5 行代码就能解析）：
    byte 0   : 魔数 'L' (0x4C)
    byte 1   : 宽（固定 128）
    byte 2   : 高（行数 × 14）
    byte 3   : 保留 0
    byte 4.. : 位图，每行 16 字节（128 像素），MSB 在左

用法：
  python pipeline/render_strip.py                  # 读 site/today.txt
  python pipeline/render_strip.py --preview x.png  # 顺便出一张预览
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W = 128
LINE_H = 14
# 跨平台字体：本地是微软雅黑，GitHub runner 上是 Noto CJK
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def load_font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render(lines: list[str], out_bin: Path, preview: Path | None = None) -> tuple[int, int]:
    font = load_font(12)
    H = max(1, len(lines) * LINE_H)

    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((1, i * LINE_H + 1), line, font=font, fill=1)

    # 按行打包成字节（每行 16 字节）
    data = bytearray()
    for y in range(H):
        for bx in range(W // 8):
            b = 0
            for bit in range(8):
                if img.getpixel((bx * 8 + bit, y)):
                    b |= 0x80 >> bit
            data.append(b)

    blob = bytes([0x4C, W, H, 0]) + bytes(data)
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    out_bin.write_bytes(blob)

    if preview:
        img.convert("L").resize((W * 3, H * 3), Image.NEAREST).save(preview)

    print(f"已生成 {out_bin}  {W}×{H}  {len(blob)} 字节")
    return W, H


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=Path, default=ROOT / "site" / "today.txt")
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "lyric.bin")
    ap.add_argument("--preview", type=Path, default=None)
    args = ap.parse_args()

    lines = []
    for raw in args.today.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("lyric"):
            continue
        val = raw.split("=", 1)[1].strip()
        if val:
            lines.append(val)
    if not lines:
        raise SystemExit("today.txt 里没有 lyric 行")

    # 出处作为最后一行，跟着一起滚
    meta = {}
    for raw in args.today.read_text(encoding="utf-8").splitlines():
        if "=" in raw:
            k, v = raw.split("=", 1)
            meta[k] = v
    if meta.get("title"):
        credit = f"{meta['title']} {meta.get('artist', '')}".strip()
        lines.append(credit)

    render(lines, args.out, args.preview)
    for i, l in enumerate(lines):
        print(f"  {i+1}. {l}")


if __name__ == "__main__":
    main()
