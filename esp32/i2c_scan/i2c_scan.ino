/* ==========================================================================
 *  I2C 扫描（不死版）/ I2C Scanner that can NOT hang
 *  --------------------------------------------------------------------------
 *  给「4 脚 OLED（VDD GND SCK SDA）」+ Arduino Mega 用。
 *
 *  为什么不用 Wire 库：
 *    AVR 的 Wire 没有总线超时。SDA 只要被拉低（线接错、短路、屏没供电
 *    但 IO 漏电），Wire.endTransmission() 就会在这个地址上死等，整个程序
 *    卡住，连串口都不再输出——就是「一直卡在扫描中」。
 *
 *  这个版本改用软件模拟 I2C：
 *    · 每一位都是「拉一下、等一会儿、看电平」，全部用 delayMicroseconds，
 *      不存在无限等待，最坏情况就是扫完没找到。
 *    · 扫描前先测 SDA/SCL 的静态电平，能直接看出「被拉死」还是「悬空」。
 *    · 发现 SDA 被拉低时，自动发 9 个时钟脉冲做总线恢复。
 *
 *  三种结果：
 *    扫到 0x3C / 0x3D → 接线通了，问题在驱动代码
 *    扫不到 + 电平正常 → 屏没供电 / 屏坏 / 不是 I2C 协议
 *    扫不到 + SDA 是低 → 线接错、短路、或引脚损坏（看串口的具体提示）
 *
 *  接线（Mega 2560）：
 *    VDD → 5V      GND → GND      SCK → 21(SCL)      SDA → 20
 *    直连，不要串分压电阻。
 * ========================================================================== */

#include <Arduino.h>

#define PIN_SDA   20      // Mega 的 SDA
#define PIN_SCL   21      // Mega 的 SCL
#define PIN_LED   13      // 板载 LED，心跳

// 扫描速度：半周期微秒数。60 = 约 8kHz，很慢很稳，线长也不怕
#define HALF_US   60

/* ------------------------------------------------------------------ */
static inline void sdaLow()  { pinMode(PIN_SDA, OUTPUT); digitalWrite(PIN_SDA, LOW); }
static inline void sdaHigh() { pinMode(PIN_SDA, OUTPUT); digitalWrite(PIN_SDA, HIGH); }
static inline void sdaIn()   { pinMode(PIN_SDA, INPUT_PULLUP); }
static inline void sclLow()  { pinMode(PIN_SCL, OUTPUT); digitalWrite(PIN_SCL, LOW); }
static inline void sclHigh() { pinMode(PIN_SCL, OUTPUT); digitalWrite(PIN_SCL, HIGH); }
static inline void tick()    { delayMicroseconds(HALF_US); }

void busIdle() {
  sdaIn();
  pinMode(PIN_SCL, INPUT_PULLUP);
  tick();
}

/* 总线恢复：SDA 被拉低时，补 9 个时钟让它自己吐出来 */
void busRecover() {
  sdaIn();
  sclHigh();
  for (int i = 0; i < 9; i++) {
    sclLow();  tick();
    sclHigh(); tick();
  }
  sdaLow();  tick();     // 手动补一个 STOP
  sclHigh(); tick();
  sdaHigh(); tick();
}

/* 探测一个地址，返回 true = 收到 ACK */
bool probe(uint8_t addr) {
  sdaHigh(); sclHigh(); tick();      // START
  sdaLow();  tick();
  sclLow();  tick();

  for (int i = 7; i >= 0; i--) {     // 地址 + 写位
    if ((addr >> i) & 1) sdaHigh(); else sdaLow();
    tick();
    sclHigh(); tick();
    sclLow();  tick();
  }

  sdaIn();                           // 第 9 个时钟：读 ACK
  tick();
  sclHigh(); tick();
  bool ack = (digitalRead(PIN_SDA) == LOW);
  sclLow();  tick();

  sdaLow();  tick();                 // STOP
  sclHigh(); tick();
  sdaHigh(); tick();

  return ack;
}

/* 只测量，不通信 */
void reportLevels() {
  busIdle();
  bool sda = digitalRead(PIN_SDA);
  bool scl = digitalRead(PIN_SCL);

  Serial.print("  静态电平: SDA=");
  Serial.print(sda ? "HIGH" : "LOW ");
  Serial.print("  SCL=");
  Serial.println(scl ? "HIGH" : "LOW ");

  if (!sda && !scl) {
    Serial.println("    两条线都是低 → 很可能 VDD 没电，或 GND 没接，或线插错");
  } else if (!sda) {
    Serial.println("    只有 SDA 是低 → SDA 被拉死：短路到 GND、接错脚，或屏在拉总线");
    Serial.println("    （这就是 Wire 版会卡住的原因）");
  } else if (!scl) {
    Serial.println("    只有 SCL 是低 → SCL 被拉死：短路或接错脚");
  } else {
    Serial.println("    两条线都是高 → 总线空闲，正常状态");
  }
}

void scanOnce() {
  Serial.println();
  Serial.println("--- 扫描 ---");

  reportLevels();
  if (!digitalRead(PIN_SDA)) {
    Serial.println("  SDA 被拉低，先做总线恢复…");
    busRecover();
    busIdle();
    Serial.print("  恢复后 SDA=");
    Serial.println(digitalRead(PIN_SDA) ? "HIGH（好了）" : "LOW（还是低，硬件问题）");
  }

  int found = 0;
  uint8_t hit[8];
  for (uint8_t addr = 0x08; addr < 0x78; addr++) {
    if (probe(addr)) {
      if (found < 8) hit[found] = addr;
      found++;
    }
  }

  // 一条 I2C 总线上挂十几个设备已经很夸张了；扫到几十个必然是假 ACK
  if (found > 4) {
    Serial.print("  !! 扫到 ");
    Serial.print(found);
    Serial.println(" 个设备 —— 这不可能，是假 ACK");
    Serial.println("     含义：读 ACK 的时候 SDA 一直是低电平，所以每个地址都被当成\"应答\"。");
    Serial.println("     最常见原因：**屏没有供电**。模块上 SDA/SCL 各有一个上拉电阻接到 VDD，");
    Serial.println("     VDD 没电时，这两条线就被电阻拉到 0V 了。");
    Serial.println("     请按顺序查：");
    Serial.println("     1. 万用表量「屏的 VDD 脚」与「屏的 GND 脚」之间，应是 5V（或 3.3V）");
    Serial.println("     2. VDD 那根杜邦线是不是插在了没有 5V 的孔上（Mega 的 5V 在电源区）；");
    Serial.println("        杜邦线断芯很常见 —— 直接换一根试");
    Serial.println("     3. GND 是否真的连到屏的 GND");
    Serial.println("     4. 如果 VDD 是 5V 且 GND 通，还这样 → 屏可能已损坏");
    Serial.println("     5. 拔掉屏再扫：若变成「0 个设备 + SDA=HIGH」，就确认是屏侧把线拉低的");
    return;
  }

  for (int i = 0; i < found; i++) {
    Serial.print("  OK 找到设备: 0x");
    if (hit[i] < 16) Serial.print("0");
    Serial.print(hit[i], HEX);
    if (hit[i] == 0x3C)      Serial.print("   <- SSD1306/1315 OLED（代码默认地址）");
    else if (hit[i] == 0x3D) Serial.print("   <- SSD1306 备用地址");
    Serial.println();
  }

  if (found == 0) {
    Serial.println("  [X] 没有设备应答。按顺序查：");
    Serial.println("     1. 万用表量 VDD-GND 有没有 5V（屏不供电就一定扫不到）");
    Serial.println("     2. GND 共地：Mega 的 GND 必须和屏的 GND 相连");
    Serial.println("     3. SDA/SCL 对调试试（SCK 丝印 = SCL = 21）");
    Serial.println("     4. 把屏拔掉再扫：如果还是 SDA=LOW，是 Mega 的脚或杜邦线短路");
    Serial.println("     5. 换 20/21 以外的一组脚（改文件顶部 PIN_SDA/PIN_SCL）再扫");
  } else {
    Serial.println("  [OK] 总线通了。下一步烧 screen_test，用 SCR_SSD1306_128X64_I2C。");
  }
}

void setup() {
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  delay(1200);              // 等串口监视器连上

  Serial.println();
  Serial.println("==========================================");
  Serial.println("  I2C 扫描（软件 I2C，不会卡死）");
  Serial.print  ("  SDA="); Serial.print(PIN_SDA);
  Serial.print  ("  SCL="); Serial.println(PIN_SCL);
  Serial.println("==========================================");

  busIdle();
  scanOnce();
}

void loop() {
  digitalWrite(PIN_LED, HIGH); delay(120);
  digitalWrite(PIN_LED, LOW);  delay(1880);

  static uint8_t n = 0;
  if (++n % 3 == 0) scanOnce();   // 约 6 秒重扫一次，方便边插线边看
}
