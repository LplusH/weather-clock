/* ==========================================================================
 *  粤语歌词时钟 / Lyric Clock  —— Mega 2560 + 0.96" I2C OLED
 *  --------------------------------------------------------------------------
 *  改动（相对上一版）：
 *    1. 软件 I2C → **硬件 I2C**（400kHz）。软件 I2C 传一帧 1KB 要 100ms 以上，
 *       滚动会卡成幻灯片；硬件 I2C 一帧约 25ms，滚动才顺。
 *    2. 歌词从「两行写死」改成**整段数组 + 平滑上滚**，放不下就自动滚，
 *       首尾之间留 2 行空白，循环不断句。
 *    3. 字库加了垂直裁剪窗口（cnClipTop/cnClipBot），滚出视口的像素不画。
 *
 *  版面（128×64）：
 *    ┌────────────────────────┐
 *    │ SAT 10.17        26C   │  7px  状态行
 *    │ 22:19          ■       │  21px 大时间（右上角心跳方块）
 *    │ · · · · · · · · · · ·  │  虚线 y=33
 *    ├────────────────────────┤  ← 歌词视口 y=32..63，高 32px
 *    │ 好景不會每日常在        │     12px 字，行高 14px
 *    │ 天梯不可只往上爬        │
 *    └────────────────────────┘
 *
 *  依赖：U8g2 + 本目录的 cnfont.h（由 tools/make_font.py 生成）
 * ========================================================================== */

#include <Arduino.h>
#include <U8g2lib.h>
#include <Wire.h>
#include <stdarg.h>
#include "cnfont.h"

/* ---------------- 屏幕：硬件 I2C，SCL=21 SDA=20 ---------------- */
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

/* ---------------- 歌词：先写死几句，正式版从 today.json 来 ---------------- */
static const char *LYRIC[] = {
  "階磚不會拒絕磨蝕",
  "窗花不可幽禁落霞",
  "有感情就會一生一世嗎",
  "又在惋惜有用嗎",
};
static const int LYRIC_N = sizeof(LYRIC) / sizeof(LYRIC[0]);

/* ---------------- 版面参数 ---------------- */
static const int VIEW_TOP = 36;                 // 歌词视口上沿
static const int VIEW_BOT = 63;                 // 视口下沿（含）
static const int VIEW_H   = VIEW_BOT - VIEW_TOP + 1;   // 28px
static const int LINE_H   = 14;                 // 12px 字 + 2px 行距
static const int GAP_LINES = 0;                 // 循环时首尾之间留几行空

static int cyclePx;                 // 一轮滚动的总高度
static int yofs = 0;                // 当前滚动偏移
static uint32_t lastStep = 0;
static const uint16_t STEP_MS = 80; // 每 80ms 上移 1px ≈ 12.5px/s，一行约 1.1 秒

static uint32_t bootMs;
static int startHour = 22, startMin = 19;

/* AVR 的 Serial 没有 printf */
static void logf(const char *fmt, ...) {
  char buf[80];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
}

static void dottedLine(int y) {
  for (int x = 0; x < 128; x += 3) u8g2.drawPixel(x, y);
}

/* 画歌词视口：整段歌词按 yofs 向上平移，只在视口内绘制 */
static void drawLyrics() {
  cnClipTop = VIEW_TOP;
  cnClipBot = VIEW_BOT;

  for (int i = 0; i < LYRIC_N; i++) {
    int y = VIEW_TOP + i * LINE_H - yofs;
    if (y > VIEW_BOT) break;                 // 后面的都在视口下方
    if (y + CN_H <= VIEW_TOP) continue;      // 完全滚出上方
    drawCNText(u8g2, 4, y, LYRIC[i]);
  }

  cnClipTop = -32768;
  cnClipBot = 32767;
}

/* 整屏重绘 */
static void drawFace(uint8_t hh, uint8_t mm) {
  char buf[12];

  u8g2.clearBuffer();

  // 状态行
  u8g2.setFont(u8g2_font_5x7_tf);
  u8g2.drawStr(2, 7, "SAT 10.17");
  u8g2.drawStr(108, 7, "26C");

  // 大时间
  snprintf(buf, sizeof(buf), "%02d:%02d", hh, mm);
  u8g2.setFont(u8g2_font_10x20_tf);
  u8g2.drawStr(2, 32, buf);

  // 心跳方块（证明刷新没停）
  if ((millis() / 500) & 1) u8g2.drawBox(118, 22, 6, 6);

  // 分隔线
  dottedLine(34);

  // 歌词
  drawLyrics();

  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  delay(1200);

  cyclePx = (LYRIC_N + GAP_LINES) * LINE_H;

  Serial.println();
  Serial.println("==========================================");
  Serial.println("  粤语歌词时钟（Mega 演示版 · 滚动歌词）");
  logf("  字库 %d 字, %d 字节\n", CN_COUNT, CN_COUNT * CN_BYTES_PER_GLYPH);
  logf("  歌词 %d 行, 内容高 %dpx, 视口 %dpx, 循环 %dpx\n",
       LYRIC_N, LYRIC_N * LINE_H, VIEW_H, cyclePx);
  if (cyclePx > VIEW_H) logf("  -> 放不下，自动滚动 %d px/s\n", 1000 / STEP_MS);
  else                  Serial.println("  -> 一屏放得下，不滚动");
  Serial.println("==========================================");

  u8g2.begin();
  u8g2.setBusClock(400000);        // 硬件 I2C 跑 400kHz
  u8g2.setContrast(180);

  // 开屏
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(4, 14, "Lyric Clock");
  drawCNText(u8g2, 4, 22, "粤语歌词时钟");
  u8g2.setFont(u8g2_font_5x7_tf);
  u8g2.drawStr(4, 46, "HW I2C 400kHz");
  u8g2.drawStr(4, 57, "scroll 5 lines");
  u8g2.sendBuffer();
  delay(1000);

  bootMs = millis();
  lastStep = millis();
  drawFace(startHour, startMin);
}

void loop() {
  uint32_t now = millis();

  bool stepped = false;
  if (cyclePx > VIEW_H && now - lastStep >= STEP_MS) {
    lastStep = now;
    if (++yofs >= cyclePx) yofs = 0;
    stepped = true;
  }

  // 演示时钟：每 60 秒 +1 分钟
  int total = startHour * 60 + startMin + (now - bootMs) / 60000;
  uint8_t hh = (total / 60) % 24;
  uint8_t mm = total % 60;

  static uint8_t lastH = 255, lastM = 255;
  bool minuteChanged = (hh != lastH || mm != lastM);

  static uint32_t lastBlink = 0;
  bool blinkChanged = ((now / 500) != (lastBlink / 500));

  if (stepped || minuteChanged || blinkChanged) {
    lastBlink = now;
    lastH = hh; lastM = mm;
    drawFace(hh, mm);
    if (minuteChanged) logf("%02d:%02d\n", hh, mm);
  }

  delay(5);
}
