/* ============================================================
 *  粵語天氣時鐘 · ESP32 固件骨架
 *  ------------------------------------------------------------
 *  硬體：ESP32-S3（或任何 ESP32）+ 480×320 SPI TFT（ST7796 / ILI9488）
 *  思路：時間由本機 NTP + 內建數字字體自己畫（不需要中文字庫），
 *        日期／天氣／歌詞由後端烘焙成一張 JPEG 拉下來顯示。
 *
 *  需要改的三處：
 *    1. WIFI_SSID / WIFI_PASS
 *    2. CARD_URL      —— 指向你的 card.jpg（樹莓派 / NAS / GitHub Pages）
 *    3. TFT_eSPI 的 User_Setup.h —— 按你的屏幕型號填驅動和引腳
 *
 *  依賴庫（Arduino 庫管理器）：
 *    TFT_eSPI      by Bodmer
 *    TJpg_Decoder  by Bodmer
 *
 *  注意：本文件沒有在真機上編譯過，是骨架。你選的屏、引腳、驅動
 *        不同，User_Setup.h 一定要自己配；其餘邏輯可以直接用。
 * ============================================================ */

#include <WiFi.h>
#include <HTTPClient.h>
#include <TFT_eSPI.h>
#include <TJpg_Decoder.h>
#include <time.h>

// ---------------- 要改的地方 ----------------
static const char *WIFI_SSID = "你的WiFi";
static const char *WIFI_PASS = "你的密碼";
static const char *CARD_URL  = "http://192.168.1.10:8000/card.jpg";  // 後端生成的卡片
static const char *TZ_INFO   = "CST-8";                              // 中國標準時間

static const uint32_t CARD_REFRESH_MS = 6UL * 60 * 60 * 1000;        // 每 6 小時重拉卡片
// -------------------------------------------

TFT_eSPI tft = TFT_eSPI();

// 卡片上用「紙色」畫的時間區（要和 render_card.py 的留白區域對得上）
static const int TIME_X = 24, TIME_Y = 44, TIME_W = 250, TIME_H = 86;
static const uint16_t C_PAPER = 0xF79D;   // #F7F3EA 轉 RGB565
static const uint16_t C_INK   = 0x18C2;   // #1F1B16 轉 RGB565

static uint32_t lastCard = 0;
static int lastMinute = -1;

/* TJpg_Decoder 每解出一塊就回調一次，直接推給屏幕 */
bool tft_output(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t *bitmap) {
  if (y >= tft.height()) return false;
  tft.pushImage(x, y, w, h, bitmap);
  return true;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " OK" : " FAILED");
}

void syncTime() {
  configTzTime(TZ_INFO, "ntp.aliyun.com", "cn.pool.ntp.org", "pool.ntp.org");
  struct tm t;
  for (int i = 0; i < 40; i++) {
    if (getLocalTime(&t, 500) && t.tm_year > 120) return;   // 年份 > 2020
    delay(250);
  }
  Serial.println("NTP 對時失敗，時間可能不準");
}

/* 畫時:分。fillRect 把上一次的數字蓋掉，所以不會有殘影 */
void drawClock() {
  struct tm t;
  if (!getLocalTime(&t, 100)) return;
  char buf[8];
  snprintf(buf, sizeof(buf), "%02d:%02d", t.tm_hour, t.tm_min);

  tft.fillRect(TIME_X, TIME_Y, TIME_W, TIME_H, C_PAPER);
  tft.setTextColor(C_INK, C_PAPER);
  tft.setTextDatum(TL_DATUM);
  tft.setTextFont(6);            // 6 = 48px 數字；想更大用 8（75px）再調座標
  tft.drawString(buf, TIME_X + 4, TIME_Y + 10);
}

/* 拉卡片 JPEG 並顯示 */
bool drawCard() {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  http.setTimeout(15000);
  http.begin(CARD_URL);
  int code = http.GET();
  if (code != 200) {
    Serial.printf("卡片下載失敗 HTTP %d\n", code);
    http.end();
    return false;
  }

  int len = http.getSize();
  if (len <= 0 || len > 400000) {          // 不知道長度或太大就放棄
    Serial.println("卡片大小異常");
    http.end();
    return false;
  }

  uint8_t *buf = (uint8_t *)ps_malloc(len); // 沒有 PSRAM 就改成 malloc 並壓小圖
  if (!buf) {
    Serial.println("記憶體不足");
    http.end();
    return false;
  }

  WiFiClient *stream = http.getStreamPtr();
  int got = 0;
  uint32_t t0 = millis();
  while (got < len && millis() - t0 < 20000) {
    size_t n = stream->readBytes(buf + got, len - got);
    got += n;
  }
  http.end();

  bool ok = false;
  if (got == len) {
    TJpg_Decoder.begin();
    TJpg_Decoder.setCallback(tft_output);
    ok = (TJpg_Decoder.drawJpg(buf, len, 0, 0) == 1);
  }
  free(buf);

  if (ok) drawClock();                     // 圖片蓋掉了時間區，補畫一次
  return ok;
}

void setup() {
  Serial.begin(115200);
  tft.init();
  tft.setRotation(1);                      // 橫屏
  tft.fillScreen(C_PAPER);

  connectWiFi();
  syncTime();

  TJpg_Decoder.begin();
  TJpg_Decoder.setCallback(tft_output);

  drawCard();
  lastCard = millis();
}

void loop() {
  struct tm t;
  if (getLocalTime(&t, 100) && t.tm_min != lastMinute) {
    lastMinute = t.tm_min;
    drawClock();
  }

  if (millis() - lastCard > CARD_REFRESH_MS) {
    lastCard = millis();
    if (!drawCard()) Serial.println("重試卡片中…");
  }

  if (WiFi.status() != WL_CONNECTED) {     // 掉線重連
    static uint32_t lastTry = 0;
    if (millis() - lastTry > 30000) {
      lastTry = millis();
      connectWiFi();
    }
  }

  delay(1000);
}
