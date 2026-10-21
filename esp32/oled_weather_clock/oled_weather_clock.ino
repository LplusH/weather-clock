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

/* 连不上时扫一遍 2.4GHz 频段，把能看到的 SSID 打出来。
   手机热点最常见的坑：默认开 5GHz，ESP32 只支持 2.4GHz，根本扫不到。 */
static void scanAndReport() {
  Serial.println("  [扫描] 扫描 2.4GHz 频段…");
  int n = WiFi.scanNetworks();
  if (n <= 0) {
    Serial.println("  一个都扫不到：天线没接好？还是模块有问题？");
    return;
  }
  bool found = false;
  for (int i = 0; i < n; i++) {
    bool hit = (WiFi.SSID(i) == WIFI_SSID);
    if (hit) found = true;
    Serial.printf("    %2d. %-22s ch%-3d %4d dBm%s\n",
                  i + 1, WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i),
                  hit ? "   <== 目标" : "");
  }
  if (!found) {
    Serial.println("  [X] 没扫到目标 SSID —— 十有八九是热点只开了 5GHz：");
    Serial.println("      iPhone：设置 → 个人热点 → 打开「最大兼容性」");
    Serial.println("      Android：热点设置里把频段改成 2.4GHz");
  }
  WiFi.scanDelete();
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
  scanAndReport();
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

  // 只有歌词高度超过视口才滚动；放得下就静态显示
  int contentH = lyricN * LINE_H;
  cyclePx = (contentH <= VIEW_H) ? 0 : (contentH + GAP_LINES * LINE_H);
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
  // 没有歌词时把原因写出来，不然屏幕上是一片空白，看不出卡在哪
  if (lyricN == 0) {
    drawCNText(u8g2, 4, VIEW_TOP + 2, netOk ? "歌词加载失败" : "离线中");
    return;
  }
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

/* 星期：三个字母，索引对应 tm_wday（0=星期日） */
static const char *WD_EN[] = {"SUN","MON","TUE","WED","THU","FRI","SAT"};

/* ============ 天气图标：用形状画，不用中文字 ============
   12×12 的格子，画在状态行右侧。code 是 WMO 天气代码。 */
static void drawWeatherIcon(int x, int y, int code) {
  if (code < 0) return;

  if (code <= 1) {                       // 晴：圆 + 四道光线
    u8g2.drawDisc(x + 5, y + 6, 3);
    u8g2.drawLine(x + 5, y,      x + 5, y + 1);
    u8g2.drawLine(x + 5, y + 11, x + 5, y + 12);
    u8g2.drawLine(x,     y + 6,  x + 1, y + 6);
    u8g2.drawLine(x + 9, y + 6,  x + 10, y + 6);
    return;
  }
  if (code == 2 || code == 3) {          // 多云 / 阴：云
    u8g2.drawBox(x + 2, y + 6, 8, 3);
    u8g2.drawBox(x + 4, y + 4, 5, 2);
    return;
  }
  if (code <= 48) {                      // 雾：三道横线
    u8g2.drawLine(x + 1, y + 4, x + 9, y + 4);
    u8g2.drawLine(x + 2, y + 7, x + 10, y + 7);
    u8g2.drawLine(x + 1, y + 10, x + 9, y + 10);
    return;
  }
  if (code <= 67 || (code >= 80 && code <= 82)) {   // 雨：云 + 三滴
    u8g2.drawBox(x + 1, y + 3, 9, 3);
    u8g2.drawBox(x + 3, y + 1, 5, 2);
    u8g2.drawLine(x + 2, y + 8, x + 2, y + 10);
    u8g2.drawLine(x + 5, y + 8, x + 5, y + 10);
    u8g2.drawLine(x + 8, y + 8, x + 8, y + 10);
    return;
  }
  if (code <= 77 || code >= 85) {        // 雪：云 + 三个点
    u8g2.drawBox(x + 1, y + 3, 9, 3);
    u8g2.drawBox(x + 3, y + 1, 5, 2);
    u8g2.drawPixel(x + 2, y + 9);
    u8g2.drawPixel(x + 5, y + 9);
    u8g2.drawPixel(x + 8, y + 9);
    return;
  }
  u8g2.drawBox(x + 1, y + 1, 9, 3);      // 雷：云 + 闪电
  u8g2.drawLine(x + 6, y + 5, x + 4, y + 8);
  u8g2.drawLine(x + 4, y + 8, x + 6, y + 8);
  u8g2.drawLine(x + 6, y + 8, x + 4, y + 11);
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

  // 星期几：三个字母，接着日期往后画（5x7 字体，7px 高，不会压到大时间）
  if (haveTime) u8g2.drawStr(36, 7, WD_EN[t.tm_wday]);

  // WiFi 连接状态小点
  if (netOk) u8g2.drawBox(74, 2, 3, 3);

  // 右上：温度 + 天气字（中文用自建字库）
  char right[12];
  if (tempC > -900) snprintf(right, sizeof(right), "%dC", tempC);
  else              snprintf(right, sizeof(right), "--");
  int rw = u8g2.getStrWidth(right);
  u8g2.drawStr(126 - rw, 7, right);

  // 天气中文（晴/多云/雨…）用 12px 自建字库，画在右上角 y=0..11，
  // 正好落在 5x7 温度数字上方，不会压到大时间（大时间从 y=13 开始）
  // 天气用图标表示，画在温度左边，不会和数字重叠
  drawWeatherIcon(126 - rw - 15, 0, wmoCode);

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
