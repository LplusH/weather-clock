#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成接線圖（示意圖，不是實物照片）。

為什麼要畫：Mega 的引腳是「板子上一排數字」，OLED 的引腳是「模組上一排絲印」，
兩邊名字完全不一樣，純文字表格很容易接錯。畫成圖一眼就能對上。

輸出：
  site/wiring-i2c.png   Mega ↔ 0.96"/1.3" 128×64 OLED（I2C，4 根線）
  site/wiring-spi.png   Mega ↔ 2.08" 256×64 OLED（SPI，7 根線 + 電平轉換）
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"

BG = (246, 246, 243)
BOARD = (32, 84, 60)
MODULE = (26, 32, 40)
INK = (28, 28, 30)
DIM = (110, 110, 108)
WARN_BG = (255, 246, 232)
WARN_LINE = (226, 196, 150)
WARN_TX = (140, 96, 40)

COLORS = [
    (208, 58, 48),   # VCC 红
    (40, 40, 40),    # GND 黑
    (214, 168, 40),  # SCK 黄
    (46, 148, 96),   # 数据 绿
    (52, 108, 190),  # CS 蓝
    (222, 126, 42),  # DC 橙
    (140, 84, 170),  # RES 紫
]

W = 1060
ROW = 46


def f(size, bold=False):
    try:
        return ImageFont.truetype(FONT_B if bold else FONT, size)
    except Exception:
        return ImageFont.load_default()


def tw(d, s, font):
    b = d.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


def wrap(d, text, font, max_w):
    out, cur = [], ""
    for ch in text:
        if tw(d, cur + ch, font) <= max_w or not cur:
            cur += ch
        else:
            out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out


def warn_icon(d, x, y, size=14):
    """画一个三角警告标，代替 emoji（中文字体里没有彩色 emoji）。"""
    d.polygon([(x + size // 2, y), (x + size, y + size), (x, y + size)],
              fill=(214, 150, 40))
    d.rectangle([x + size // 2 - 1, y + 5, x + size // 2 + 1, y + 10], fill=(255, 255, 255))
    d.rectangle([x + size // 2 - 1, y + 11, x + size // 2 + 1, y + 12], fill=(255, 255, 255))


def panel(out, title, board_pins, module_pins, module_label,
          note_head, note_body, footer):
    f_title = f(23, True)
    f_pin = f(15, True)
    f_sub = f(12)
    f_note = f(14)
    f_note_b = f(16, True)
    f_small = f(13)

    rows = len(board_pins)
    board_h = 92 + rows * ROW + 18
    top = 78
    img_tmp = Image.new("RGB", (W, 10), BG)
    dtmp = ImageDraw.Draw(img_tmp)
    footer_lines = []
    for para in footer:
        footer_lines += wrap(dtmp, para, f_small, W - 120)
    footer_h = 26 + len(footer_lines) * 21

    H = top + max(board_h, 92 + rows * ROW + 18) + 26 + footer_h + 24
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((30, 22), title, font=f_title, fill=INK)

    # ---- Mega ----
    bx0, by0, bx1 = 40, top, 300
    by1 = by0 + board_h
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=10, fill=BOARD, outline=(20, 60, 42), width=2)
    d.text((bx0 + 18, by0 + 16), "Arduino", font=f(17, True), fill=(206, 232, 216))
    d.text((bx0 + 18, by0 + 38), "MEGA 2560", font=f(17, True), fill=(206, 232, 216))

    # ---- 模块 ----
    mx0 = 470
    mw = 230
    my0, my1 = by0, by0 + board_h - 40
    d.rounded_rectangle([mx0, my0, mx0 + mw, my1], radius=10, fill=MODULE, outline=(10, 12, 16), width=2)
    d.text((mx0 + 16, my0 + 14), module_label, font=f(15, True), fill=(198, 210, 222))

    for i, ((bl, bs), (ml, ms), color) in enumerate(zip(board_pins, module_pins, COLORS)):
        y = by0 + 92 + i * ROW
        lb = f"{bl}  {bs}".strip()
        lm = f"{ml}  {ms}".strip()

        px0, px1 = bx1 - 52, bx1 - 8
        d.rounded_rectangle([px0, y - 12, px1, y + 12], radius=4, fill=(226, 238, 230))
        d.text((px0 - 12 - tw(d, lb, f_pin), y - 9), lb, font=f_pin, fill=(222, 240, 228))

        qx0, qx1 = mx0 + 8, mx0 + 52
        d.rounded_rectangle([qx0, y - 12, qx1, y + 12], radius=4, fill=(232, 236, 240))
        d.text((qx1 + 12, y - 9), lm, font=f_pin, fill=(232, 238, 246))

        d.line([px1 + 2, y, qx0 - 2, y], fill=color, width=5)
        d.ellipse([px1 - 4, y - 5, px1 + 4, y + 3], fill=color)
        d.ellipse([qx0 - 4, y - 5, qx0 + 4, y + 3], fill=color)

    # ---- 右侧说明 ----
    nx = 750
    y = by0 + 6
    d.text((nx, y), note_head, font=f_note_b, fill=INK)
    y += 30
    for line in note_body:
        d.rectangle([nx, y + 6, nx + 6, y + 12], fill=(120, 120, 118))
        d.text((nx + 16, y), line, font=f_note, fill=DIM)
        y += 24

    # ---- 底部提醒 ----
    fy = H - footer_h - 18
    d.rounded_rectangle([30, fy, W - 30, H - 18], radius=8, fill=WARN_BG, outline=WARN_LINE, width=2)
    yy = fy + 12
    for i, line in enumerate(footer_lines):
        if i == 0:
            warn_icon(d, 44, yy + 1)
            d.text((64, yy), line, font=f_small, fill=WARN_TX)
        else:
            d.text((64, yy), line, font=f_small, fill=WARN_TX)
        yy += 21

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    site = ROOT / "site"

    p1 = panel(
        site / "wiring-i2c.png",
        "接法一：0.96\" / 1.3\" 128×64 OLED（I2C，4 根線）",
        [("5V", ""), ("GND", ""), ("21", "SCL"), ("20", "SDA")],
        [("VCC", ""), ("GND", ""), ("SCL", ""), ("SDA", "")],
        "OLED 128×64",
        "对应的代码",
        ["#define SCR_SSD1306_128X64_I2C",
         "SCL=21  SDA=20（不是 A4/A5）",
         "Mega 上这两个脚就是硬件 I2C"],
        ["4 根线全部直连，一个电阻都不要加（这是最常犯的错）：",
         "VDD 不能分压 —— 分压器等效内阻 667Ω，屏要 20mA，压降 13V，供电直接崩；",
         "SDA/SCL 不能分压 —— I2C 靠 4.7k 上拉，再加 2k 下拉会压到 0.98V，通信必废。"],
    )
    print("已输出", p1)

    p2 = panel(
        site / "wiring-spi.png",
        "接法二：2.08\" 256×64 OLED（SPI，7 根線）",
        [("3.3V", ""), ("GND", ""), ("52", "SCK"), ("51", "MOSI"),
         ("53", "CS"), ("9", "DC"), ("8", "RES")],
        [("VCC", ""), ("GND", ""), ("SCK", "D0"), ("SDA", "D1"),
         ("CS", ""), ("DC", "RS"), ("RES", "RST")],
        "OLED 256×64",
        "对应的代码",
        ["#define SCR_SSD1322_256X64_SPI",
         "SCK=52  MOSI=51  CS=53",
         "DC=9  RES=8",
         "51/52/53 是 Mega 的硬件 SPI"],
        ["2.08\" 模组多数没有稳压器：VCC 必须 3.3V，5V 信号线必须分压；",
         "穷办法：每根信号线串 1kΩ、再对地接 2kΩ（共 5 组）；",
         "想干净就买 4 路电平转换模块（¥3），5V 侧接 Mega，3.3V 侧接屏。"],
    )
    print("已输出", p2)


if __name__ == "__main__":
    main()

