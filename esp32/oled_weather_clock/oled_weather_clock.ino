/* ==========================================================================
 *  粤语天气时钟 / Cantonese Weather Clock  —— ESP32-S3 + 0.96" I2C OLED
 *  --------------------------------------------------------------------------
 *  这一版是「成品」：
 *    · WiFi 联网 + NTP 对时（北京时间）
 *    · 从你的网页/GitHub Pages 拉今天这一句歌词（today.txt）
 *    · 从 Open-Meteo 拉实时气温（免 key）
 *    · 128×64 OLED：大时间 + 顶部状态 + 歌词自动上滚
 *    · 繁体中文靠自建子集字库（cnfont.h），不依赖 U8g2 的简体字库
 *
 *  要改的只有三处（在下面的「配置」里）：
 *    1. WIFI_SSID / WIFI_PASS
 *    2. TXT_URL      —— 指向你的 today.txt
 *    3. PIN_SDA/PIN_SCL —— 按你的接线
 *
 *  依赖库：U8g2（库管理器装）。不用 ArduinoJson —— today.txt 是 key=value 格式，
 *          自己按行切就行，少一个依赖就少一个出错点。
 *
 *  板子：ESP32-S3-N16R8（16MB Flash / 8MB PSRAM，普通 4MB 板也能跑）
 *  FQBN：esp32:esp32:esp32s3
 * ========================================================================== */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include <U8g2lib.h>
#include <Wire.h>
#include <stdarg.h>
#include "cnfont.h"

/* ======================= 配置 ======================= */
// WiFi 凭据放在 secrets.h（本地私有文件，已被 .gitignore 排除）。
// 公开仓库里没有这个文件，别人编译时用下面的占位符。
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID   "你的WiFi名字"
#define WIFI_PASS   "你的WiFi密码"
#endif

// today.txt 的地址。可以是 GitHub Pages、树莓派上的 http 服务、或任意静态托管
#define TXT_URL     "https://lplush.github.io/weather-clock/today.txt"

// 天气用的经纬度（北京）
#define WX_LAT      "39.9042"
#define WX_LON      "116.4074"
#define WX_TZ       "Asia%2FShanghai"

// I2C 引脚（ESP32-S3 默认 8/9，按你的接线改）
#define PIN_SDA     8
#define PIN_SCL     9

// 时区：中国标准时间（不随夏令时）
#define TZ_INFO     "CST-8"

// 刷新节奏
static const uint32_t WX_REFRESH_MS  = 30UL * 60 * 1000;   // 天气 30 分钟
static const uint32_t TXT_REFRESH_MS = 6UL * 60 * 60 * 1000; // 歌词 6 小时

/* ======================= 显示 ======================= */
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

/* ======================= 状态 ======================= */
static String lyricLines[6];
static int    lyricN = 0;
static String songTitle, songArtist, weekdayCn;
static int    tempC = -999;        // -999 = 还没有数据
static int    wmoCode = -1;

static int    cyclePx = 0, yofs = 0;
static const int VIEW_TOP = 36, VIEW_BOT = 63;
static const int VIEW_H = VIEW_BOT - VIEW_TOP + 1;
static const int LINE_H = 14;
static const int GAP_LINES = 2;

static uint32_t lastStep = 0, lastWx = 0, lastTxt = 0;
static const uint16_t STEP_MS = 80;
static bool netOk = false;

/* ======================= 小工具 ======================= */
static void logf(const char *fmt, ...) {
  char buf[128];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
}

static void dottedLine(int y) {
  for (int x = 0; x < 128; x += 3) u8g2.drawPixel(x, y);
}

/* 连 WiFi，最多等 15 秒 */
static bool wifiConnect() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  logf("连接 WiFi %s ", WIFI_SSID);
  for (int i = 0; i < 30; i++) {
    if (WiFi.status() == WL_CONNECTED) {
      logf("\n  已连接，IP = %s\n", WiFi.localIP().toString().c_str());
      return true;
    }
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n  WiFi 连接失败");
  return false;
}

/* NTP 对时 */
static void syncTime() {
  configTzTime(TZ_INFO, "ntp.aliyun.com", "cn.pool.ntp.org", "ntp.tencent.com");
  struct tm t;
  for (int i = 0; i < 20; i++) {
    if (getLocalTime(&t, 500) && t.tm_year > 120) {
      logf("  时间已同步：%04d-%02d-%02d %02d:%02d\n",
           t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min);
      return;
    }
    delay(250);
  }
  Serial.println("  NTP 对时失败，时间可能不准");
}

/* HTTPS GET，返回 body；失败返回空串 */
static String httpGet(const char *url) {
  WiFiClientSecure client;
  client.setInsecure();                 // 不校验证书，省掉根证书维护
  HTTPClient http;
  http.setTimeout(8000);
  http.setConnectTimeout(8000);
  if (!http.begin(client, url)) return "";
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200) logf("  HTTP %d  %s\n", code, url);
  return body;
}

/* ======================= 拉今日歌词 ======================= */
static void fetchTxt() {
  logf("[歌词] GET %s\n", TXT_URL);
  String body = httpGet(TXT_URL);
  if (body.isEmpty()) {
    logf("  拉取失败，保留上一份歌词\n");
    return;
  }

  lyricN = 0;
  int start = 0;
  while (start < (int)body.length() && lyricN < 6) {
    int nl = body.indexOf('\n', start);
    if (nl < 0) nl = body.length();
    String line = body.substring(start, nl);
    line.trim();
    start = nl + 1;
    if (!line.length()) continue;

    int eq = line.indexOf('=');
    if (eq <= 0) continue;
    String k = line.substring(0, eq), v = line.substring(eq + 1);
    if      (k == "title")              songTitle = v;
    else if (k == "artist")             songArtist = v;
    else if (k == "weekday")            weekdayCn = v;
    else if (k.startsWith("lyric"))     lyricLines[lyricN++] = v;
  }

  cyclePx = (lyricN + GAP_LINES) * LINE_H;
  yofs = 0;
  logf("  收到 %d 行歌词：%s\n", lyricN, lyricN ? lyricLines[0].c_str() : "");
  for (int i = 0; i < lyricN; i++) logf("    [%d] %s\n", i + 1, lyricLines[i].c_str());
}

/* ======================= 拉天气 ======================= */
static int jsonInt(const String &s, const char *key, int from = 0) {
  String pat = String("\"") + key + "\":";
  int p = s.indexOf(pat, from);
  if (p < 0) return -999;
  p += pat.length();
  // 跳过空格/引号
  while (p < (int)s.length() && (s[p] == ' ' || s[p] == '"'))p++;
  return s.substring(p).toInt();
}

static void fetchWeather() {
  String url = String("https://api.open-meteo.com/v1/forecast?latitude=") + WX_LAT
             + "&longitude=" + WX_LON
             + "&current=temperature_2m,weather_code&timezone=" + WX_TZ;
  logf("[天气] GET open-meteo\n");
  String body = httpGet(url.c_str());
  if (body.isEmpty()) {
    logf("  天气拉取失败\n");
    return;
  }
  // 只在 "current":{ 之后找，避免命中 current_units 里的同名字段
  int cur = body.indexOf("\"current\":");
  if (cur < 0) return;
  tempC   = jsonInt(body, "temperature_2m", cur);
  wmoCode = jsonInt(body, "weather_code", cur);
  logf("  %d°C  代码 %d\n", tempC, wmoCode);
}

/* WMO 天气代码 → 中文（这些字都已收进字库） */
static const char *wmoCn(int c) {
  if (c < 0)   return "";
  if (c <= 1)  return "晴";
  if (c == 2)  return "多云";
  if (c == 3)  return "阴";
  if (c <= 48) return "雾";
  if (c <= 67) return "雨";
  if (c <= 77) return "雪";
  if (c <= 82) return "阵雨";
  return "雷";
}

/* ======================= 绘制 ======================= */
static void drawLyrics() {
  cnClipTop = VIEW_TOP;
  cnClipBot = VIEW_BOT;
  for (int i = 0; i < lyricN; i++) {
    int y = VIEW_TOP + i * LINE_H - yofs;
    if (y > VIEW_BOT) break;
    if (y + CN_H <= VIEW_TOP) continue;
    drawCNText(u8g2, 4, y, lyricLines[i].c_str());
  }
  cnClipTop = -32768;
  cnClipBot = 32767;
}

static void drawFace() {
  struct tm t;
  bool haveTime = getLocalTime(&t, 10);

  u8g2.clearBuffer();

  /* --- 状态行 --- */
  u8g2.setFont(u8g2_font_5x7_tf);
  char left[20];
  if (haveTime) snprintf(left, sizeof(left), "%02d.%02d", t.tm_mon + 1, t.tm_mday);
  else          snprintf(left, sizeof(left), "--.--");
  u8g2.drawStr(2, 7, left);

  // WiFi 连接状态小点
  if (netOk) u8g2.drawBox(46, 2, 3, 3);

  // 右上：温度 + 天气字（中文用自建字库）
  char right[12];
  if (tempC > -900) snprintf(right, sizeof(right), "%dC", tempC);
  else              snprintf(right, sizeof(right), "--");
  int rw = u8g2.getStrWidth(right);
  u8g2.drawStr(126 - rw, 7, right);

  // 天气中文（晴/多云/雨…）用 12px 自建字库，画在右上角 y=0..11，
  // 正好落在 5x7 温度数字上方，不会压到大时间（大时间从 y=13 开始）
  const char *wx = wmoCn(wmoCode);
  if (wx && *wx) {
    int n = 0;
    for (const char *q = wx; *q; q++) if (((uint8_t)*q & 0xC0) != 0x80) n++;
    drawCNText(u8g2, 126 - n * CN_W, 0, wx);
  }

  /* --- 大时间 --- */
  if (haveTime) {
    char hhmm[8];
    snprintf(hhmm, sizeof(hhmm), "%02d:%02d", t.tm_hour, t.tm_min);
    u8g2.setFont(u8g2_font_10x20_tf);
    u8g2.drawStr(2, 32, hhmm);
  } else {
    u8g2.setFont(u8g2_font_10x20_tf);
    u8g2.drawStr(2, 32, "--:--");
  }

  // 心跳方块
  if ((millis() / 500) & 1) u8g2.drawBox(118, 22, 6, 6);

  dottedLine(34);
  drawLyrics();

  u8g2.sendBuffer();
}

/* ======================= setup / loop ======================= */
void setup() {
  Serial.begin(115200);
  delay(1200);

  Serial.println();
  Serial.println("==========================================");
  Serial.println("  粤语天气时钟 (ESP32-S3 + 0.96 OLED)");
  logf("  字库 %d 字 / %d 字节\n", CN_COUNT, CN_COUNT * CN_BYTES_PER_GLYPH);
  Serial.println("==========================================");

  Wire.setPins(PIN_SDA, PIN_SCL);
  u8g2.begin();
  u8g2.setBusClock(400000);
  u8g2.setContrast(180);

  // 开屏
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(4, 14, "Weather Clock");
  drawCNText(u8g2, 4, 22, "粤语天气时钟");
  u8g2.setFont(u8g2_font_5x7_tf);
  u8g2.drawStr(4, 46, "ESP32-S3  booting");
  u8g2.sendBuffer();

  netOk = wifiConnect();
  if (netOk) {
    syncTime();
    fetchTxt();
    fetchWeather();
    lastTxt = lastWx = millis();
  } else {
    lyricLines[0] = "连不上网络";
    lyricN = 1;
    cyclePx = 0;
  }

  drawFace();
}

void loop() {
  uint32_t now = millis();

  // 断网重连
  if (WiFi.status() != WL_CONNECTED) {
    static uint32_t lastTry = 0;
    if (now - lastTry > 30000) {
      lastTry = now;
      netOk = wifiConnect();
      if (netOk) { syncTime(); fetchTxt(); fetchWeather(); }
    }
  } else {
    netOk = true;
  }

  // 定时刷新
  if (netOk && now - lastWx > WX_REFRESH_MS)  { lastWx = now;  fetchWeather(); }
  if (netOk && now - lastTxt > TXT_REFRESH_MS) { lastTxt = now; fetchTxt(); }

  // 滚动
  bool stepped = false;
  if (cyclePx > VIEW_H && now - lastStep >= STEP_MS) {
    lastStep = now;
    if (++yofs >= cyclePx) yofs = 0;
    stepped = true;
  }

  // 整屏只在需要时重绘：滚动步进 / 每分钟 / 心跳翻转
  static uint32_t lastBlink = 0;
  static int lastMin = -1;
  struct tm t;
  bool haveTime = getLocalTime(&t, 5);
  bool minuteChanged = haveTime && (t.tm_min != lastMin);
  bool blinkChanged = ((now / 500) != (lastBlink / 500));

  if (stepped || minuteChanged || blinkChanged) {
    if (minuteChanged) lastMin = t.tm_min;
    lastBlink = now;
    drawFace();
  }

  delay(5);
}
