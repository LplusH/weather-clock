# ESP32 固件：环境准备 & 编译

適用於 `screen_test/` 和後面的 `weather_clock/`。

> 手邊只有 **Arduino Mega 2560** 也能先測屏 —— 見最後一節「用 Mega 先測」。

---

## 一、裝庫（這次報錯的原因）

### 一條命令裝好編譯鏈（不想開 IDE 的話）

```bash
# 1. arduino-cli
#    Windows: https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip
#    解壓出 arduino-cli.exe 就能用，不用安裝

# 2. 板子包
arduino-cli core update-index
arduino-cli core install arduino:avr        # Mega 2560
arduino-cli core install esp32:esp32        # ESP32-C3 / S3（比較大，約 1GB）

# 3. 庫
arduino-cli lib install "U8g2"

# 4. 編譯 / 上傳
arduino-cli compile --fqbn arduino:avr:mega        esp32/screen_test
arduino-cli upload  -p COM5 --fqbn arduino:avr:mega esp32/screen_test
```

以下 IDE 的操作說明同樣適用。

`fatal error: U8g2lib.h: No such file or directory` = **U8g2 庫沒裝**。
`U8g2lib.h` 不是 Arduino 內建的，也不是 ESP32 板子包帶的，必須單獨裝。

### 方法 A：Arduino IDE 2.x（推薦）

1. 左側豎排圖標點**第三個**（書本圖標），或菜單 `Sketch → Include Library → Manage Libraries…`
2. 搜索框輸入 **`U8g2`**
3. 找到 **`U8g2` by Oliver**（作者 olikraus，版本 2.35.x 以上）→ 點 **INSTALL**
4. 裝完直接重新點「驗證」，**不用重啟 IDE**

> 注意別裝錯：還有一個叫 `U8g2_for_Adafruit_GFX` 的庫，頭文件是
> `U8g2_for_Adafruit_GFX.h`，不是我們要的。認準 **U8g2 / olikraus**。

### 方法 B：arduino-cli

```bash
arduino-cli lib search u8g2
arduino-cli lib install "U8g2"
arduino-cli lib list            # 確認出現在列表裡
```

### 方法 C：裝不上（國內網絡拉不到索引）
1. 打開 <https://github.com/olikraus/u8g2> → 右側 **Code → Download ZIP**
2. IDE 菜單 `Sketch → Include Library → Add .ZIP Library…` → 選剛下載的 zip
3. 重新編譯

（zip 解壓後目錄名必須是 `U8g2`，裡面要有 `src/U8g2lib.h`。
裝好後可以在 `文件 → 示例 → U8g2` 裡看到一堆例子，能打開就說明裝對了。）

### 裝了卻還報找不到？先確認庫到底裝到哪了

IDE 的庫不是裝在程序目錄，而是裝在「**項目文件夾位置**」下：

| 系統 | 默認路徑 |
|---|---|
| 一般 Windows | `C:\Users\<你>\Documents\Arduino\libraries` |
| **這台機器（文檔被移到 D 盤）** | `D:\HuaweiMoveData\Users\<你>\Documents\Arduino\libraries` |

`文檔` 被 OneDrive / 廠商遷移工具搬走過的話，默認路徑就會變，
而網上教程一律寫 `C:\Users\...\Documents\Arduino`，照著找會找不到。
查真實路徑：IDE 菜單 `文件 → 首選項 → 項目文件夾位置`。

確認庫裝對的硬指標：`<項目文件夾位置>\libraries\U8g2\src\U8g2lib.h` 這個文件存在。

---

## 二、確認板子包

只裝庫還不夠，編譯 ESP32 需要 **ESP32 開發板包**（不是 ESP8266 那個）：

- IDE：`Tools → Board → Boards Manager` → 搜 `esp32` → 裝 **esp32 by Espressif Systems**
- CLI：
  ```bash
  arduino-cli core update-index
  arduino-cli core install esp32:esp32
  ```

板子型號對照（FQBN）：

| 你的板子 | FQBN |
|---|---|
| ESP32-C3 SuperMini | `esp32:esp32:esp32c3` |
| ESP32-S3 DevKitC / Mini | `esp32:esp32:esp32s3` |
| ESP32 DevKit（經典款） | `esp32:esp32:esp32` |

---

## 三、用命令行編譯 / 上傳

不想開 IDE 的話：

```bash
# 編譯
arduino-cli compile --fqbn esp32:esp32:esp32c3 esp32/screen_test

# 看串口（先確認端口）
arduino-cli board list
arduino-cli monitor -p COM5 -c baudrate=115200

# 上傳
arduino-cli upload -p COM5 --fqbn esp32:esp32:esp32c3 esp32/screen_test
```

Windows 上如果 `upload` 報 `Failed to connect`，按住板子上的 **BOOT** 鍵再點上傳，
看到 `Connecting...` 就鬆手。

---

## 四、常見報錯對照

| 報錯 | 原因 | 解法 |
|---|---|---|
| `U8g2lib.h: No such file or directory` | U8g2 庫沒裝 | 見第一節 |
| `esp32-hal.h: No such file or directory` | 板子包沒裝 / 選了錯的板子 | 裝 `esp32:esp32`，選對型號 |
| `error: 'U8G2_SSD1322_NHD_256X64_F_4W_SW_SPI' was not declared` | U8g2 版本太老 | 庫管理器升級到 2.35+ |
| `u8g2_font_wqy12_t_gb2312 was not declared` | 字體名不對（不同版本命名有差異） | 改用 `u8g2_font_wqy12_t_chinese1` |
| `Sketch too big` | 板子 Flash 選小了 | `Tools → Flash Size` 選 4MB |
| 上傳時 `Connecting...` 卡住 | 沒進下載模式 / 佔用 | 按住 BOOT 再上傳；關掉佔用串口的軟件 |
| 串口監視器全是亂碼 | 波特率不對 | 改成 **115200** |

---

## 五、裝完後的驗證順序

1. 燒 `screen_test` → 看串口有沒有打 `U8g2 初始化完成` 和 `256x64`
2. 有打印但屏黑 → 回到 `screen_test.ino` 頂部的接線說明逐條查
3. 屏上有畫面 → 這一步過了，再去做天氣時鐘

---

## 六、順帶裝好的庫（後面會用到）

| 庫 | 用途 | 什麼時候裝 |
|---|---|---|
| **U8g2** | OLED 驅動 + 字體 | 現在 |
| ArduinoJson | 解析 `today.json` | 寫時鐘固件時 |
| TJpg_Decoder | 只在彩屏路線需要 | 用 OLED 就不用裝 |

現在只需要 U8g2。

---

## 七、用 Mega 2560 先測

手邊只有 Mega，完全可以先驗證「屏是好的」。`screen_test.ino` 已經支援：

```cpp
#define BOARD_MEGA2560          // 打開這個
// #define BOARD_ESP32
#define SCR_SSD1306_128X64_I2C  // Mega 上預設用 I2C 小屏，最省事
```

引腳會自動切到 Mega 的：**MOSI=51, SCK=52, SS=53, DC=9, RES=8, SDA=20, SCL=21**。

### 接線圖（照著插就行）

0.96" / 1.3" 128×64 OLED，I2C，4 根線：

![I2C 接線](site/wiring-i2c.png)

2.08" 256×64 OLED，SPI，7 根線：

![SPI 接線](site/wiring-spi.png)

（路徑相對於倉庫根目錄：`weather-clock/site/wiring-*.png`，
由 `pipeline/wiring.py` 生成，改引腳就改那個文件重跑。）

```bash
arduino-cli core install arduino:avr
arduino-cli compile --fqbn arduino:avr:mega esp32/screen_test
arduino-cli upload  -p COM5 --fqbn arduino:avr:mega esp32/screen_test
```

### Mega 的三個硬限制

| 限制 | 影響 | 怎麼處理 |
|---|---|---|
| **5V 邏輯** | 3.3V 屏的 IO 可能被燒 | 見下面的電平表 |
| **U8g2 沒給 AVR 編中文** | 引用 `u8g2_font_wqy12_t_gb2312` 會**連結失敗**（不是 flash 不夠） | 已在 AVR 上自動 `SHOW_CN=0` |
| **SRAM 8KB** | 128×64 緩衝 1KB、256×64 是 2KB | 夠用（實測 256×64 佔 4218B） |

### 實測編譯結果（不是估計）

環境：`arduino-cli 1.5.2` + `arduino:avr 1.8.8` + `U8g2 2.36.19`，目標 `arduino:avr:mega`

| 配置 | Flash | SRAM | 剩餘棧 |
|---|---|---|---|
| SSD1306/1315 128×64 I2C | 24058 B (9%) | 3183 B (38%) | 5009 B |
| SSD1309 128×64 SPI | 23868 B (9%) | 3116 B (38%) | 5076 B |
| SSD1322 256×64 SPI | 24052 B (9%) | 4218 B (51%) | 3974 B |

三個配置都 **exit 0**。`SHOW_CN=1` 在 Mega 上必定失敗，報錯是：

```
undefined reference to `u8g2_font_wqy12_t_gb2312'
collect2.exe: error: ld returned 1 exit status
```

所以那不是「字庫太大塞不下」，而是 **U8g2 根本沒為 AVR 編這個字體**。

### 5V 接 3.3V 屏的判斷

| 你的屏 | VCC | 信號線 |
|---|---|---|
| 0.96"/1.3" I2C（背面有 LDO） | 5V 可以 | 直接接 |
| 2.42" 128×64 SPI（多數帶 LDO） | 5V 可以 | 直接接 |
| 2.08" 256×64 SPI（多數沒有） | **3.3V** | **必須分壓或加電平轉換** |

判斷方法：看背面有沒有 3.3V 穩壓芯片（662K / ME6211 之類）和「3.3V–5V」絲印。
沒有電平轉換模組時，5 根信號線各串 1kΩ、再對地接 2kΩ 分壓（5V → 3.3V），低速測試可行。

### 5V → 3.3V：到底哪幾根要降壓

**Mega 輸出的每一根都要降**，一共 5 根：

| 線 | Mega 腳 | 方向 | 要不要降壓 |
|---|---|---|---|
| SCK | 52 | Mega → 屏 | **要** |
| MOSI / SDA / D1 | 51 | Mega → 屏 | **要** |
| CS | 53 | Mega → 屏 | **要** |
| DC / RS | 9 | Mega → 屏 | **要** |
| RES / RST | 8 | Mega → 屏 | **要**（可省，見下） |
| MISO | 不接 | 屏 → Mega | 不用（我們不讀屏） |

原因：SSD1322 的 IO 絕對最大額定約 **VDD+0.3V ≈ 3.6V**，5V 會擊穿輸入端的 ESD 二極管。
「只降 SCK 和 MOSI，CS/DC 反正翻轉慢」是不行的——電壓超限和頻率無關。

**能省的一根**：RES 不必接信號，直接並到 3.3V（上電複位）。這樣只需要降 4 根。

三種做法，按省事程度排：

| 做法 | 成本 | 說明 |
|---|---|---|
| 電阻分壓 1k + 2k | ¥0.2 | 5V×2/3 = 3.33V。只適合低速（我們用軟件 SPI，幾十 kHz，完全夠） |
| 電平轉換模塊 | ¥3–5 | 認 **8 路**（TXS0108E），4 路的不夠用；VB 接 5V、VA 接 3.3V |
| 74HCT125 / 74HCT245 | ¥2 | **最乾淨**：芯片用 3.3V 供電，HCT 輸入能接受 5V，輸出就是 3.3V |

> 一句話：這堆麻煩是 Mega 的 5V 帶來的。換成 ESP32-C3（3.3V 原生）一根都不用降。


### Mega 能做什麼、不能做什麼

- ✅ 驗證屏的好壞、接線、驅動 IC、可視角、壞點
- ✅ 驗證 U8g2 的繪圖和 ASCII 字體
- ❌ 驗證中文歌詞（Mega 裝不下字庫，而且真正的字庫是繁體子集）
- ❌ 當成品（沒有 WiFi，拿不到天氣和每日歌詞）

所以 Mega 只當「點屏工具」，確認屏沒問題就換 ESP32-C3 做正事。
