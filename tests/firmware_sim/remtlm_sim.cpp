// Host-side simulation of remtlm.ino, one build per role (see run.sh):
//   REMTLM_ROLE=1 tower, 2 base, 3 psu (tower also built with PWR_ENABLE=1)
#include "Arduino.h"
#include <cstdio>
#include <functional>
#include "remtlm_mocks/Wire.h"
#include "remtlm_mocks/DallasTemperature.h"

SimState sim;
MockSerial Serial;
InaSim ina;
DallasSim dallas;
TwoWire Wire;

#include "remtlm.ino"

void digitalWrite(int p, int v) { sim.pinOut[p] = v; }

static int failures = 0;
#define CHECK(cond, ...)                                   \
  do {                                                     \
    if (!(cond)) {                                         \
      failures++;                                          \
      std::printf("  FAIL %s:%d: ", __FILE__, __LINE__);   \
      std::printf(__VA_ARGS__);                            \
      std::printf("\n");                                   \
    }                                                      \
  } while (0)

static void step(uint32_t ms = 1) {
  for (uint32_t i = 0; i < ms; i++) {
    sim.now++;
    loop();
  }
}

// Complete lines the sketch has sent over LoRa since the last call (CR/LF stripped).
static std::vector<std::pair<uint32_t, std::string>> sent;
static size_t sentPos = 0;
static void collect() {
  std::string &o = loraSerial.out;
  size_t nl;
  while ((nl = o.find('\n', sentPos)) != std::string::npos) {
    std::string ln = o.substr(sentPos, nl - sentPos);
    if (!ln.empty() && ln.back() == '\r') ln.pop_back();
    sent.push_back({sim.now, ln});
    sentPos = nl + 1;
  }
}
static void run(uint32_t ms) {
  for (uint32_t i = 0; i < ms; i++) {
    step();
    collect();
  }
}
[[maybe_unused]] static int count(const char *prefix, uint32_t from = 0, uint32_t to = 0xFFFFFFFF) {
  int n = 0;
  for (auto &s : sent)
    if (s.first >= from && s.first <= to && s.second.rfind(prefix, 0) == 0) n++;
  return n;
}

[[maybe_unused]] static std::string rtLine(uint16_t seq) {
  char buf[TLM_MAX_LINE];
  TlmData d = {seq, 100, 50, 0, 1, 250, 300, 60, "K2UA"};
  tlmFormat(buf, sizeof(buf), &d);
  return buf;
}

static void boot() {
  sim.now = 0;
  setup();
  collect();
}

#if REMTLM_ROLE == ROLE_PSU
static void testPsu() {
  std::printf("psu\n");
  ina.bus = 11200;      // 14.000 V
  ina.shunt = 1600;     // 4.0 mV across 3.75 mOhm = 1066 mA
  dallas.count = 1;
  boot();
  CHECK(Serial.out.find("V:remtlm 0.4.0 psu") != std::string::npos, "version line: %s", Serial.out.c_str());
  CHECK(Serial.out.find("I:INA226 ok") != std::string::npos, "INA226 found");

  // 1. No tower: free-running every PSU_REPORT_MS
  run(7000);
  int n = count("$RS,", 0, 7000);
  CHECK(n == 3, "free-running $RS in 7 s: %d (want 3)", n);
  CHECK(count("$RT,") == 0 && count("$RP,") == 0, "PSU sends only $RS");
  const std::string &last = sent.back().second;
  CHECK(tlmValid(last.c_str()), "valid $RS: %s", last.c_str());
  CHECK(last.find(",14000,14000,14000,1066,1066,1066,1,214,") != std::string::npos,
        "fields (14.000 V, 1.066 A, 21.4 C): %s", last.c_str());

  // 2. Tower appears: $RS slotted PSU_SLOT_DELAY_MS after each $RT, nothing else
  sent.clear();
  uint32_t t0 = sim.now + 1;
  for (int k = 0; k < 6; k++) {
    loraSerial.feed(rtLine((uint16_t)k) + "\r\n");
    run(k < 3 ? 2000 : 500);        // idle, then transmitting
  }
  CHECK(Serial.out.find("I:tower heard") != std::string::npos, "tower heard");
  CHECK(count("$RS,") == 6, "one $RS per tower $RT: %d", count("$RS,"));
  uint32_t rtAt = t0;
  for (int k = 0; k < 6 && k < (int)sent.size(); k++) {
    uint32_t dt = sent[k].first - rtAt;
    CHECK(dt >= PSU_SLOT_DELAY_MS && dt <= PSU_SLOT_DELAY_MS + 2,
          "slot %d at +%u ms after $RT (want ~%lu)", k, dt, PSU_SLOT_DELAY_MS);
    rtAt += k < 3 ? 2000 : 500;
  }

  // 3. Corrupt $RT: no slot
  sent.clear();
  std::string bad = rtLine(99);
  bad[6] ^= 1;
  loraSerial.feed(bad + "\r\n");
  run(300);
  CHECK(count("$RS,") == 0, "no $RS after a corrupt $RT");

  // 4. A lock-change $RT 100 ms after a regular one: the min gap suppresses a second slot
  sent.clear();
  loraSerial.feed(rtLine(100) + "\r\n");
  run(100);
  loraSerial.feed(rtLine(101) + "\r\n");
  run(400);
  CHECK(count("$RS,") == 1, "min gap: %d $RS (want 1)", count("$RS,"));

  // 5. Tower goes quiet: back to free-running after PSU_TOWER_LOST_MS
  sent.clear();
  uint32_t lastRt = sim.now - 400;
  run(8000);
  CHECK(Serial.out.find("I:tower not heard") != std::string::npos, "tower lost reported");
  CHECK(count("$RS,") >= 2, "free-running resumed: %d $RS in 8 s", count("$RS,"));
  CHECK(!sent.empty() && sent.front().first - lastRt >= PSU_TOWER_LOST_MS,
        "nothing until the tower is declared lost (first at +%u)", sent.empty() ? 0 : sent.front().first - lastRt);

  // 6a. A few failed reads in a row (a byte arriving mid-transaction) are tolerated
  ina.present = false;
  run(30);                              // 3 reads at 10 ms
  ina.present = true;
  sent.clear();
  run(4100);
  CHECK(!sent.empty() && sent.back().second.find(",1066,1066,1066,1,") != std::string::npos,
        "short I2C glitch tolerated: %s", sent.empty() ? "(none)" : sent.back().second.c_str());

  // 6b. No I2C while the E220's AUX is low (it is passing a packet to the Nano)
  sim.pinIn[PIN_E220_AUX] = LOW;
  ina.shunt = 4000;                     // would read 2666 mA if polled
  run(500);
  sim.pinIn[PIN_E220_AUX] = HIGH;
  ina.shunt = 1600;
  sent.clear();
  run(2100);
  CHECK(!sent.empty() && sent.back().second.find("2666") == std::string::npos,
        "no INA226 reads while AUX low: %s", sent.empty() ? "(none)" : sent.back().second.c_str());

  // 6c. INA226 disappears: ok=0 and zeros, then recovers
  ina.present = false;
  sent.clear();
  run(4500);
  CHECK(!sent.empty() && sent.back().second.find(",0,0,0,0,0,0,0,") != std::string::npos,
        "INA226 gone -> ok 0: %s", sent.empty() ? "(none)" : sent.back().second.c_str());
  ina.present = true;
  sent.clear();
  run(12000);
  CHECK(!sent.empty() && sent.back().second.find(",1066,1066,1066,1,") != std::string::npos,
        "INA226 back: %s", sent.empty() ? "(none)" : sent.back().second.c_str());

  // 7. Reverse shunt reads negative
  ina.shunt = (uint16_t)(int16_t)-1600;
  sent.clear();
  run(4100);
  CHECK(!sent.empty() && sent.back().second.find(",-1066,-1066,-1066,") != std::string::npos,
        "negative current: %s", sent.empty() ? "(none)" : sent.back().second.c_str());
}
#endif

#if REMTLM_ROLE == ROLE_TOWER
static void testTower() {
  std::printf("tower (PWR_ENABLE=%d)\n", PWR_ENABLE);
  ina.bus = 10400;      // 13.000 V
  ina.shunt = 2400;     // 6 mV -> 1600 mA
  dallas.count = 2;
  boot();
  CHECK(Serial.out.find("V:remtlm 0.4.0 tower") != std::string::npos, "version line");
  CHECK(Serial.out.find("I:temperature probes=2") != std::string::npos, "two probes");
  run(4600);
  // the mock ADC reads mid-scale (~3.6 V PA sense), so the tower is in its 0.5 s "transmitting" rate
  CHECK(count("$RT,") == 9, "$RT every 0.5 s while the PA shows output: %d", count("$RT,"));
  CHECK(count("$RS,") == 0, "tower never sends $RS");
#if PWR_ENABLE
  CHECK(Serial.out.find("I:INA226 ok") != std::string::npos, "INA226 found");
  CHECK(count("$RP,") == 9, "$RP before each $RT: %d", count("$RP,"));
  bool found = false;
  for (auto &s : sent)
    if (s.second.rfind("$RP,", 0) == 0 && s.second.find(",13000,13000,13000,1600,1600,1600,1,") != std::string::npos)
      found = true;
  CHECK(found, "$RP fields (13.000 V, 1.600 A)");
#else
  CHECK(count("$RP,") == 0, "no $RP with PWR_ENABLE 0");
  CHECK(Serial.out.find("INA226") == std::string::npos, "INA226 not probed");
#endif
  for (auto &s : sent) CHECK(tlmValid(s.second.c_str()), "valid: %s", s.second.c_str());
}
#endif

#if REMTLM_ROLE == ROLE_BASE
static void testBase() {
  std::printf("base\n");
  boot();
  Serial.out.clear();
  char buf[TLM_MAX_LINE];
  SupData sd = {5, 14000, 13990, 14010, 1066, 1000, 4200, 1, 214, 77, "K2UA"};
  tlmFormatSupply(buf, sizeof(buf), &sd);
  std::string rs = buf;
  loraSerial.feed("noise" + rtLine(1) + rs);
  std::string bad = rtLine(2);
  bad[6] ^= 1;
  loraSerial.feed(bad);
  run(20);
  CHECK(Serial.out.find(rtLine(1).substr(0, rtLine(1).size() - 2)) != std::string::npos, "$RT forwarded");
  CHECK(Serial.out.find(rs.substr(0, rs.size() - 2)) != std::string::npos, "$RS forwarded: %s", Serial.out.c_str());
  CHECK(Serial.out.find("E:bad packet #1") != std::string::npos, "bad packet counted");
  CHECK(loraSerial.out.empty(), "base never transmits");
}
#endif

int main() {
#if REMTLM_ROLE == ROLE_PSU
  testPsu();
#elif REMTLM_ROLE == ROLE_TOWER
  testTower();
#else
  testBase();
#endif
  if (failures) std::printf("%d FAILED\n", failures);
  return failures ? 1 : 0;
}
