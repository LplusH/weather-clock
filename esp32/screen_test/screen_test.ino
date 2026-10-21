/* ==========================================================================
 *  OLED 屏幕测试 / Screen Test
 *  --------------------------------------------------------------------------
 *  支援：Arduino Mega 2560（5V）、ESP32-C3 / S3（3.3V）
 *
 *  ⚠️ Mega 2560 是 5V 邏輯，OLED 是 3.3V，接錯會燒屏，先看第 0 節。
 *
 *  用途：屏一到手，先燒這個，確認「接線 / 驅動 IC / 可視角 / 刷新」四件事。
 *        每一步都同步往串口打一行說明，所以屏全黑也能從串口知道卡在哪。
 *
 *  依賴庫：U8g2（庫管理器搜 u8g2，作者 olikraus）
 * ==========================================================================
 *
 *  ===== 第 0 節：Mega 2560 的 5V 陷阱（先讀）=====
 *
 *  | 你的屏                        | VCC 接哪 | 信號線           |
 *  | 0.96"/1.3" I2C（帶 LDO）      | 5V 可以  | 直接接，板上有電平轉換 |
 *  | 2.42" 128×64 SPI（多數帶 LDO）| 5V 可以  | 直接接（確認背面有 3.3V LDO） |
 *  | 2.08" 256×64 SPI（多數沒有）  | **3.3V** | **必須降壓或加電平轉換** |
 *
 *  怎麼判斷：看模組背面有沒有 3.3V 穩壓芯片（如 662K / ME6211）和絲印
 *  「3.3V–5V」。有 = 可以直接接 5V；只標 3.3V = 只能接 3.3V。
 *
 *  沒有電平轉換模組時的窮辦法（測試用，低速可行）：
 *    SCK / MOSI / CS / DC / RES 各串一顆 1k 電阻，再對地接 2k 電阻，
 *    分壓後 5V → 3.3V。共 5 組。接線很醜但能測。
 *
 *  Mega 的 3.3V 腳由 LP2985 供電（約 150mA），OLED 40–60mA 帶得動。
 *
 *  ===== 第 0.5 節：Mega 的兩個硬限制 =====
 *    1. SRAM 只有 8KB：128×64 全屏緩衝 1KB、256×64 是 2KB，都夠用
 *       （實測 256×64 版本佔 4218B，剩 3974B 給棧）。
 *    2. U8g2 **沒有為 AVR 編譯 wqy 中文字體**，所以在 Mega 上引用中文字體
 *       不是「flash 放不下」而是直接連結失敗。本文件在 AVR 上自動 SHOW_CN=0。
 *       中文本來就要用自建子集字庫，那步在 ESP32 上做。
 * ========================================================================== */

#include <Arduino.h>
#include <stdarg.h>
#include <U8g2lib.h>
#ifdef U8X8_HAVE_HW_SPI
#include <SPI.h>
#endif
#ifdef U8X8_HAVE_HW_I2C
#include <Wire.h>
#endif

/* ===================== ① 選板子 ===================== */
// 只有 Mega 就留這個；用 ESP32 就註解掉它
#define BOARD_MEGA2560
// #define BOARD_ESP32

/* ===================== ② 選屏：只留一個 ===================== */
#define SCR_SSD1306_128X64_I2C   // 0.96"/1.3"，SSD1315 也選這個（Mega 上最省事）
// #define SCR_SSD1322_256X64_SPI   // 2.08"
// #define SCR_SSD1309_128X64_SPI   // 2.42"

/* ===================== ③ 引腳 ===================== */
#if defined(BOARD_MEGA2560)
  // Mega 的硬件 SPI 是固定腳：51=MOSI 52=SCK 53=SS；I2C 是 20=SDA 21=SCL
  #define PIN_SCK   52
  #define PIN_MOSI  51
  #define PIN_CS    53
  #define PIN_DC    9
  #define PIN_RES   8
  #define PIN_SDA   20
  #define PIN_SCL   21
  #define BOARD_NAME "Arduino Mega 2560"
#else
  #define PIN_SCK   4
  #define PIN_MOSI  6
  #define PIN_CS    7
  #define PIN_DC    5
  #define PIN_RES   10
  #define PIN_SDA   8
  #define PIN_SCL   9
  #define BOARD_NAME "ESP32-C3"
#endif

/* ===================== ④ 行為開關 ===================== */
#define AUTO_CYCLE   1
// AVR (Mega) 上必須關掉中文：U8g2 沒有為 AVR 編譯 wqy 中文字體，
// 直接引用會是連結錯誤 undefined reference to `u8g2_font_wqy12_t_gb2312`。
// （實測 2026-10：arduino:avr 1.8.8 + U8g2 2.36.19）
#if defined(__AVR__)
  #define SHOW_CN    0
#else
  #define SHOW_CN    1
#endif

/* ===================== ⑤ 構造 ===================== */
#if defined(SCR_SSD1322_256X64_SPI)
  U8G2_SSD1322_NHD_256X64_F_4W_SW_SPI u8g2(
      U8G2_R0, PIN_SCK, PIN_MOSI, PIN_CS, PIN_DC, PIN_RES);
  #define SCR_NAME  "SSD1322 256x64 SPI"

#elif defined(SCR_SSD1309_128X64_SPI)
  // 若報「找不到這個構造器」，把 NONAME0 換成 NONAME2
  U8G2_SSD1309_128X64_NONAME0_F_4W_SW_SPI u8g2(
      U8G2_R0, PIN_SCK, PIN_MOSI, PIN_CS, PIN_DC, PIN_RES);
  #define SCR_NAME  "SSD1309 128x64 SPI"

#elif defined(SCR_SSD1306_128X64_I2C)
  // SSD1315 與 SSD1306 指令兼容，用同一個構造器
  U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(
      U8G2_R0, PIN_SCL, PIN_SDA, U8X8_PIN_NONE);
  #define SCR_NAME  "SSD1306/1315 128x64 I2C"
#else
  #error "請在文件頂部選一個屏幕型號"
#endif

static int W, H;

/* ===================== 小工具 ===================== */
// AVR 的 Serial 沒有 printf，自己包一個，兩邊都能用
void logf(const char *fmt, ...) {
  char buf[96];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
}

void boot(const char *step) {
  Serial.println();
  logf(">>> %s", step);
  Serial.println();
}

void drawCorners() {
  const int m = 0;
  u8g2.drawLine(m, m, m + 6, m);
  u8g2.drawLine(m, m, m, m + 6);
  u8g2.drawLine(W - 1, m, W - 7, m);
  u8g2.drawLine(W - 1, m, W - 1, m + 6);
  u8g2.drawLine(m, H - 1, m + 6, H - 1);
  u8g2.drawLine(m, H - 1, m, H - 7);
  u8g2.drawLine(W - 1, H - 1, W - 7, H - 1);
  u8g2.drawLine(W - 1, H - 1, W - 1, H - 7);
}

void centered(const char *s, const uint8_t *font, int y) {
  u8g2.setFont(font);
  int w = u8g2.getUTF8Width(s);
  u8g2.drawUTF8((W - w) / 2, y, s);
}

/* ===================== 1. 全亮 / 全滅 ===================== */
void testPower() {
  boot("1/8 全亮 -> 全滅（看不到就查 VCC/GND/RES）");
  u8g2.clearBuffer();
  u8g2.drawBox(0, 0, W, H);
  u8g2.sendBuffer();
  delay(600);

  u8g2.clearBuffer();
  u8g2.sendBuffer();
  delay(300);
}

/* ===================== 2. 棋盤格 / 反色 ===================== */
void testChecker() {
  boot("2/8 棋盤格（8px）-> 反色（有連片亮/不亮 = 壞點）");
  u8g2.clearBuffer();
  for (int y = 0; y < H; y++)
    for (int x = 0; x < W; x++)
      if (((x >> 3) + (y >> 3)) & 1) u8g2.drawPixel(x, y);
  u8g2.sendBuffer();
  delay(700);

  u8g2.setDrawColor(2);            // 2 = XOR，整屏反色
  u8g2.drawBox(0, 0, W, H);
  u8g2.setDrawColor(1);
  u8g2.sendBuffer();
  delay(400);
}

/* ===================== 3. 邊框 + 角標 + 十字 ===================== */
void testBorder() {
  boot("3/8 邊框 + 四角 + 十字（看是否偏移/裁切/鏡像）");
  u8g2.clearBuffer();
  u8g2.drawFrame(0, 0, W, H);
  drawCorners();
  u8g2.drawLine(W / 2, 0, W / 2, H - 1);
  u8g2.drawLine(0, H / 2, W - 1, H / 2);
  u8g2.drawDisc(W / 2, H / 2, min(W, H) / 12);
  centered("UP", u8g2_font_6x10_tf, 12);       // 字在上方 = 方向正確
  u8g2.sendBuffer();
  delay(900);
}

/* ===================== 4. 灰階漸變 ===================== */
void testGray() {
  boot("4/8 灰階漸變（1bit 屏靠抖動模擬）");
  u8g2.clearBuffer();
  const int bars = 8;
  int bw = W / bars;
  for (int b = 0; b < bars; b++) {
    for (int y = 0; y < H; y++) {
      for (int x = b * bw; x < (b + 1) * bw && x < W; x++) {
        int d = (x - b * bw) * (b + 1) / max(1, bw);
        if (((x + y) % 8) < d) u8g2.drawPixel(x, y);
      }
    }
  }
  u8g2.sendBuffer();
  delay(900);
}

/* ===================== 5. 英文字號 ===================== */
void testText() {
  boot("5/8 英文字號（窄屏自動換短句，避免被裁切誤判成壞屏）");
  const bool small = (W < 200);
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_5x7_tf);
  u8g2.drawStr(2, 8, small ? "5x7 0123456789 abc" : "5x7 The quick brown fox 0123456789");
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(2, 22, small ? "6x10 ABCDEFGHIJKLMN" : "6x10 ABCDEFGHIJKLMNOPQRSTUVWXYZ");
  u8g2.setFont(u8g2_font_10x20_tf);
  u8g2.drawStr(2, 46, "10x20 22:19");
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(2, H - 2, small ? "128x64 OK" : SCR_NAME);
  u8g2.sendBuffer();
  delay(900);
}

/* ===================== 6. 中文 ===================== */
void testChinese() {
#if SHOW_CN
  boot("6/8 中文點陣（U8g2 自帶 wqy12，只有簡體）");
  const bool small = (W < 200);
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_wqy12_t_gb2312);
  u8g2.drawUTF8(2, 12, "中文显示测试");
  u8g2.drawUTF8(2, 26, small ? "时间22:19 晴" : "时间 22:19 天气 晴");
  u8g2.drawUTF8(2, 40, "湿度78% 雨2%");
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawUTF8(2, H - 2, small ? "wqy12 (gb2312)" : "wqy12: only GB2312");
  u8g2.sendBuffer();
  delay(1200);
  Serial.println("    中文空白/方塊：確認 .ino 存成 UTF-8、字體是 _t_gb2312");
  Serial.println("    繁體（愿/谢/钟）不在 GB2312 裡，正式固件要自建子集字庫");
#else
  boot("6/8 跳過中文（AVR 版 U8g2 沒有 wqy 中文字體，不是 flash 不夠）");
  Serial.println("    實測：Mega 上引用 u8g2_font_wqy12_t_gb2312 會連結失敗");
  Serial.println("    中文本來就要用自建子集字庫，那步在 ESP32 上做");
#endif
}

/* ===================== 7. 動畫 + FPS ===================== */
void testAnim() {
  boot("7/8 動畫測刷新率（串口看 FPS）");
  uint32_t frames = 0, t0 = millis(), lastReport = t0;
  int x = 0, dir = 1;

  while (millis() - t0 < 3000) {
    u8g2.clearBuffer();
    u8g2.drawFrame(0, 0, W, H);
    u8g2.drawBox(x, H / 2 - 4, 8, 8);
    int prog = (int)((millis() - t0) * (W - 4) / 3000);
    u8g2.drawBox(2, H - 8, prog, 4);
    frames++;
    u8g2.sendBuffer();

    x += dir * 4;
    if (x <= 1) dir = 1;
    if (x >= W - 9) dir = -1;

    if (millis() - lastReport > 1000) {
      logf("    %lu FPS", frames * 1000UL / (millis() - lastReport));
      Serial.println();
      frames = 0;
      lastReport = millis();
    }
  }
  Serial.println("    FPS 低不用慌：軟件 SPI 本來就慢，時鐘夠用；滾動字幕才換硬件 SPI");
}

/* ===================== 8. 對比度掃描 ===================== */
void testContrast() {
  boot("8/8 對比度掃描 0->255->0");
  for (int pass = 0; pass < 2; pass++) {
    for (int c = 0; c <= 255; c += 5) {
      u8g2.setContrast(pass == 0 ? c : 255 - c);
      u8g2.clearBuffer();
      u8g2.setFont(u8g2_font_6x10_tf);
      char buf[20];
      snprintf(buf, sizeof(buf), "contrast %3d", pass == 0 ? c : 255 - c);
      u8g2.drawStr(2, 10, buf);
      u8g2.drawBox(0, 14, (W - 1) * c / 255, 6);
      u8g2.drawStr(2, H - 2, "setContrast");
      u8g2.sendBuffer();
      delay(40);
    }
  }
  u8g2.setContrast(180);
}

/* ===================== 狀態頁 ===================== */
void statusPage(uint32_t seconds) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(2, 10, "SCREEN OK");
  u8g2.drawStr(2, 22, SCR_NAME);
  char buf[24];
  snprintf(buf, sizeof(buf), "%dx%d", W, H);
  u8g2.drawStr(2, 34, buf);
  snprintf(buf, sizeof(buf), "up %lus", (unsigned long)seconds);
  u8g2.drawStr(2, 46, buf);
  if ((seconds & 1) == 0) u8g2.drawBox(W - 10, 4, 6, 6);
  u8g2.sendBuffer();
}

/* ===================== setup / loop ===================== */
void setup() {
  Serial.begin(115200);
  delay(1200);                   // 等串口监视器连上，避免开头几行丢掉

  Serial.println();
  Serial.println("==========================================");
  Serial.println("  OLED 屏幕测试");
  logf("  开发板: %s\n", BOARD_NAME);
  logf("  型号:   %s\n", SCR_NAME);
#if defined(SCR_SSD1306_128X64_I2C)
  logf("  接线:   SCL=%d SDA=%d (I2C)\n", PIN_SCL, PIN_SDA);
#else
  logf("  接线:   SCK=%d MOSI=%d CS=%d DC=%d RES=%d\n",
       PIN_SCK, PIN_MOSI, PIN_CS, PIN_DC, PIN_RES);
#endif
#if defined(__AVR__)
  Serial.println("  ⚠️ Mega 是 5V 逻辑：只有标 3.3V-5V 的屏才能直接接；");
  Serial.println("     只标 3.3V 的屏必须降壓（1k+2k 分壓）或加電平轉換。");
#endif
  Serial.println("  串口一直在打印、屏却全黑，按顺序查：");
  Serial.println("    1. VCC 电压对不对（见上面警告）");
  Serial.println("    2. GND 有没有共地");
  Serial.println("    3. RES 接对没有");
  Serial.println("    4. 屏背面 IC 型号和顶部 #define 是否一致");
  Serial.println("==========================================");

  u8g2.begin();
  W = u8g2.getDisplayWidth();
  H = u8g2.getDisplayHeight();
  logf("  U8g2 初始化完成，缓冲区 %dx%d\n", W, H);

  u8g2.setContrast(180);

  u8g2.clearBuffer();
  centered("SCREEN TEST", u8g2_font_10x20_tf, H / 2 - 2);
  centered(SCR_NAME, u8g2_font_6x10_tf, H / 2 + 14);
  u8g2.sendBuffer();
  delay(1200);

  testPower();
  testChecker();
  testBorder();
  testGray();
  testText();
  testChinese();
  testAnim();
  testContrast();

  Serial.println();
  Serial.println(">>> 全部测试完成。一路正常的话，这块屏可以用了。");
  Serial.println();
}

void loop() {
#if AUTO_CYCLE
  static uint8_t round = 0;
  round++;
  if (round % 4 == 0)      testBorder();
  else if (round % 4 == 1) testChecker();
  else if (round % 4 == 2) testGray();
  else                     testText();

  uint32_t t0 = millis();
  while (millis() - t0 < 1500) {
    statusPage(millis() / 1000);
    delay(200);
  }
#else
  static uint32_t t0 = 0;
  if (t0 == 0) t0 = millis();
  statusPage((millis() - t0) / 1000);
  delay(300);
#endif
}
