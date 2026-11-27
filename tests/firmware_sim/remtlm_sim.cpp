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
AdxlSim adxl;
BmeSim bme;
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
  TlmData d = {seq, 100, 50, 0, 1, 250, 300, 60, 0, 12000, "K2UA"};
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
  CHECK(Serial.out.find("V:remtlm 0.7.1 psu") != std::string::npos, "version line: %s", Serial.out.c_str());
  CHECK(e220.cfg.TRANSMISSION_MODE.enableRSSI == RSSI_DISABLED, "psu keeps the RSSI byte off");
  CHECK(Serial.out.find("I:INA226 ok at 0x40") != std::string::npos, "INA226 found at 0x40");

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

  // 6d. A module strapped to another address (A1 to VS: 0x44) is found by the search
  ina.present = false;
  run(4500);
  ina.addr = 0x44;
  ina.present = true;
  Serial.out.clear();
  sent.clear();
  run(12000);
  CHECK(Serial.out.find("I:INA226 ok at 0x44") != std::string::npos, "found at 0x44: %s", Serial.out.c_str());
  CHECK(!sent.empty() && sent.back().second.find(",1066,1066,1066,1,") != std::string::npos,
        "readings at 0x44: %s", sent.empty() ? "(none)" : sent.back().second.c_str());
  ina.present = false;                  // nothing anywhere in 0x40-0x4F
  Serial.out.clear();
  run(12000);
  CHECK(Serial.out.find("I:INA226 not found") != std::string::npos, "not found anywhere");
  ina.present = true;
  run(12000);
  sent.clear();
  run(4100);
  CHECK(!sent.empty() && sent.back().second.find(",1066,1066,1066,1,") != std::string::npos,
        "back at 0x44: %s", sent.empty() ? "(none)" : sent.back().second.c_str());

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
  CHECK(Serial.out.find("V:remtlm 0.7.1 tower") != std::string::npos, "version line");
  CHECK(e220.cfg.TRANSMISSION_MODE.enableRSSI == RSSI_DISABLED, "tower keeps the RSSI byte off");
  CHECK(Serial.out.find("I:temperature probes=2") != std::string::npos, "two probes");
  run(4600);
  // the mock ADC reads mid-scale (~3.6 V PA sense), so the tower is in its 0.5 s "transmitting" rate
  CHECK(count("$RT,") == 9, "$RT every 0.5 s while the PA shows output: %d", count("$RT,"));
  CHECK(count("$RS,") == 0, "tower never sends $RS");
#if TILT_ENABLE
  // no sensors on the bus: one "not found" each at the first report, then every 30 s
  CHECK(Serial.out.find("I:ADXL355 not found") != std::string::npos, "ADXL355 not found");
  CHECK(Serial.out.find("I:BME280 not found") != std::string::npos, "BME280 not found");
  CHECK(count("$RA,") == 1 && count("$RB,") == 1, "one not-found $RA/$RB: %d %d", count("$RA,"), count("$RB,"));
  for (auto &s : sent)
    if (s.second.rfind("$RA,", 0) == 0)
      CHECK(s.second.find(",0,0,0,0,0,0,K2UA*") != std::string::npos, "$RA not found: %s", s.second.c_str());
  CHECK(count("$RC,") == 0, "no calibration without a BME280");
#else
  CHECK(count("$RA,") == 0 && count("$RB,") == 0 && count("$RC,") == 0, "no sensor packets when disabled");
  CHECK(Serial.out.find("ADXL355") == std::string::npos, "ADXL355 not probed");
#endif
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

  // PTT key line (A3): mid-scale = 2.50 V at the pin = 7.85 V on the line: not keyed.
  auto lastRt = [&]() {
    std::string r;
    for (auto &s : sent) if (s.second.rfind("$RT,", 0) == 0) r = s.second;
    return r;
  };
  auto field = [](const std::string &ln, int k) {   // k-th comma field (0 = "$RT")
    size_t a = 0;
    for (int i = 0; i < k; i++) a = ln.find(',', a) + 1;
    return ln.substr(a, ln.find(',', a) - a);
  };
  std::string rt = lastRt();
  CHECK(field(rt, 9) == "0", "not keyed: %s", rt.c_str());
  CHECK(field(rt, 10) == "7846", "line voltage 7846 mV: %s", rt.c_str());
  // The line goes low: a packet goes out right away (not 0.5 s later), marked keyed.
  size_t before = sent.size();
  uint32_t t0 = sim.now;
  sim.adc[A3] = 20;                     // 98 mV at the pin = 307 mV on the line
  run(CHANGE_GAP_MS + 30);
  bool quick = false;
  for (size_t i = before; i < sent.size(); i++)
    if (sent[i].second.rfind("$RT,", 0) == 0 && sent[i].first - t0 <= CHANGE_GAP_MS + 15 &&
        field(sent[i].second, 9) == "1")
      quick = true;
  CHECK(quick, "keying reported within the change gap, not the 0.5 s schedule");
  // A short key-down between packets is still caught: keyed at any point in the interval.
  sim.adc[A3] = 512;
  run(600);
  before = sent.size();
  sim.adc[A3] = 20;
  run(20);
  sim.adc[A3] = 512;
  run(1200);
  int keyed = 0;
  for (size_t i = before; i < sent.size(); i++)
    if (sent[i].second.rfind("$RT,", 0) == 0 && field(sent[i].second, 9) == "1") keyed++;
  rt = lastRt();
  CHECK(field(rt, 9) == "0", "released afterwards: %s", rt.c_str());
  for (auto &s : sent) CHECK(tlmValid(s.second.c_str()), "valid: %s", s.second.c_str());
  CHECK(keyed >= 1 && keyed <= 2, "a 20 ms key-down shows up (keyed at the start of the next interval too): %d", keyed);
  // Hysteresis: 1.2 V on the line (between 1.0 and 1.5 V) keeps whatever state it had.
  sim.adc[A3] = 20;
  run(400);
  sim.adc[A3] = 78;                     // 381 mV at the pin = 1.196 V on the line
  run(1200);
  CHECK(field(lastRt(), 9) == "1", "1.2 V after keyed: still keyed (%s)", lastRt().c_str());
  sim.adc[A3] = 512;
  run(1200);
  // A chattering line (an open input, a bad contact) can't flood the channel:
  // at most one extra packet per CHANGE_GAP_MS.
  before = sent.size();
  for (int i = 0; i < 400; i++) {
    sim.adc[A3] = (i & 1) ? 20 : 512;
    run(5);
  }
  int n = 0;
  for (size_t i = before; i < sent.size(); i++)
    if (sent[i].second.rfind("$RT,", 0) == 0) n++;
  CHECK(n <= 2000 / (int)CHANGE_GAP_MS + 1, "chatter limited: %d $RT in 2 s", n);
}
#endif


#if REMTLM_ROLE == ROLE_TOWER && TILT_ENABLE
static std::string fieldOf(const std::string &ln, int k) {   // k-th comma field (0 = "$RA")
  size_t a = 0;
  for (int i = 0; i < k; i++) a = ln.find(',', a) + 1;
  return ln.substr(a, ln.find_first_of(",*", a) - a);
}

// Dish elevation and box environment (0.7.0): sensors found by the retry, report
// order, live mode with the supply-box guard, MKU polls deferred, drop-outs.
static void testTowerSensors() {
  std::printf("tower sensors (PWR_ENABLE=%d)\n", PWR_ENABLE);
  sim.adc[A0] = 0;                          // PA quiet: one report every 2 s
  sim.adc[A3] = 512;
  adxl.present = true;
  adxl.x = 4466;                            // about +1.0 deg
  adxl.y = -1200;
  adxl.z = 255961;
  adxl.temp = 1840;
  bme.present = true;
  bme.chip = 0x60;
  const uint8_t calHead[4] = {0x70, 0x6B, 0x43, 0x67};
  for (int i = 0; i < 4; i++) bme.regs[0x88 + i] = calHead[i];
  bme.regs[0xA1] = 75;
  bme.regs[0xE7] = 30;
  bme.set(415148, 519888, 27000);
  Serial.out.clear();
  sent.clear();
  run(SENSOR_RETRY_MS + 100);
  CHECK(Serial.out.find("I:ADXL355 ok") != std::string::npos, "ADXL355 found by the retry");
  CHECK(Serial.out.find("I:BME280 ok") != std::string::npos, "BME280 found by the retry");
  CHECK(adxl.regs[0x2D] == 0x00 && adxl.regs[0x2C] == 0x01 && adxl.regs[0x28] == TILT_ODR_LPF,
        "ADXL355 set up: power %02X range %02X filter %02X", adxl.regs[0x2D], adxl.regs[0x2C], adxl.regs[0x28]);
  sent.clear();
  run(24000);
  CHECK(bme.forced >= 2 && bme.ctrlHum == 0x01 && bme.ctrlMeas == 0x25,
        "BME280 forced readings: %d, hum %02X meas %02X", bme.forced, bme.ctrlHum, bme.ctrlMeas);
  CHECK(adxl.reads > 600, "ADXL355 read at ~31 Hz: %d in ~29 s", adxl.reads);
  // order: whatever goes with a report precedes its $RT, and every $RT has a $RA before it
  int rts = 0, withRa = 0;
  for (size_t i = 0; i < sent.size(); i++) {
    if (sent[i].second.rfind("$RT,", 0) != 0) continue;
    rts++;
    for (size_t j = i; j-- > 0 && sent[j].first == sent[i].first;)
      if (sent[j].second.rfind("$RA,", 0) == 0) withRa++;
  }
  CHECK(rts >= 11 && withRa == rts, "a $RA with every $RT: %d of %d", withRa, rts);
  int nb = count("$RB,"), nc = 0;
  for (auto &s : sent) {
    CHECK(tlmValid(s.second.c_str()), "valid: %s", s.second.c_str());
    if (s.second.rfind("$RA,", 0) == 0) {
      CHECK(fieldOf(s.second, 2) == "4466" && fieldOf(s.second, 3) == "-1200" && fieldOf(s.second, 4) == "255961" &&
            fieldOf(s.second, 5) == "1840" && fieldOf(s.second, 6) == "1" && fieldOf(s.second, 7) == "0",
            "$RA still: %s", s.second.c_str());
    }
    if (s.second.rfind("$RB,", 0) == 0)
      CHECK(s.second.find(",415148,519888,27000,96,1,K2UA*") != std::string::npos, "$RB: %s", s.second.c_str());
    if (s.second.rfind("$RC,96,706B4367", 0) == 0) nc++;
  }
  CHECK(nb >= 2 && nb <= 3, "$RB every 10 s: %d in 24 s", nb);
  CHECK(nc == 0, "calibration went out once, before this window: %d", nc);
  CHECK(Serial.out.find("$RC,96,706B4367") != std::string::npos, "$RC sent after the BME280 was found");

  // Live mode: the dish moves for 2 s. Live $RA every 200 ms (moving=1), none in
  // the guard after a $RT, and back to normal LIVE_HOLD_MS after it stops.
  sent.clear();
  uint32_t t0 = sim.now;
  for (int i = 0; i < 20; i++) {
    adxl.x += 400;                          // ~0.09 deg per 100 ms
    run(100);
  }
  uint32_t tStop = sim.now;
  run(LIVE_HOLD_MS + 2500);
  int live = 0, inGuard = 0;
  uint32_t lastRt = 0, firstLive = 0, lastLive = 0;
  for (auto &s : sent) {
    if (s.second.rfind("$RT,", 0) == 0) lastRt = s.first;
    if (s.second.rfind("$RA,", 0) == 0 && fieldOf(s.second, 7) == "1") {
      bool withRt = false;                  // the $RA that goes with a $RT is exempt
      for (auto &q : sent) if (q.first == s.first && q.second.rfind("$RT,", 0) == 0) withRt = true;
      if (withRt) continue;
      live++;
      if (!firstLive) firstLive = s.first;
      lastLive = s.first;
      if (lastRt && s.first - lastRt < LIVE_GUARD_MS) inGuard++;
    }
  }
  CHECK(firstLive && firstLive - t0 <= 2 * LIVE_PERIOD_MS + 50, "live starts within two ticks: +%u", firstLive - t0);
  CHECK(live >= 12, "live packets while moving and holding: %d", live);
  CHECK(inGuard == 0, "no live packet inside the guard after a $RT: %d", inGuard);
  CHECK(lastLive && lastLive - tStop <= LIVE_HOLD_MS + LIVE_PERIOD_MS + 50 && lastLive - tStop >= LIVE_HOLD_MS - LIVE_PERIOD_MS - LIVE_GUARD_MS,
        "live ends LIVE_HOLD_MS after the last movement: +%u", lastLive - tStop);
  CHECK(fieldOf(sent.back().second, 7) == "0" || sent.back().second.rfind("$RT,", 0) == 0, "still again");

  // No MKU poll starts while the dish moves; the poll waits until it stops.
  size_t polls = xvSerial.out.size();
  uint32_t until = sim.now + XV_POLL_MS + 5000;
  bool polledWhileLive = false;
  while (sim.now < until) {
    adxl.x = 4466 + (int32_t)((sim.now / 100) % 50) * 400;   // a slow sweep, ~0.09 deg per 100 ms
    run(100);
    if (xvSerial.out.size() != polls) polledWhileLive = true;
  }
  CHECK(!polledWhileLive, "no MKU poll while moving");
  run(LIVE_HOLD_MS + 500);
  CHECK(xvSerial.out.size() > polls, "the poll goes out once the dish is still");
  run(XV_REPLY_MAX_MS + 500);

  // ADXL355 drops off the bus: reported gone, $RA ok=0, then found again.
  adxl.present = false;
  sent.clear();
  run(3000);
  CHECK(Serial.out.find("I:ADXL355 not answering") != std::string::npos, "ADXL355 gone");
  bool gone = false;
  for (auto &s : sent) if (s.second.rfind("$RA,", 0) == 0 && fieldOf(s.second, 6) == "0") gone = true;
  CHECK(gone, "$RA ok=0 once it is gone");
  adxl.present = true;
  Serial.out.clear();
  sent.clear();
  run(SENSOR_RETRY_MS + 2100);
  CHECK(Serial.out.find("I:ADXL355 ok") != std::string::npos, "ADXL355 back");
  CHECK(!sent.empty() && count("$RA,") >= 1, "$RA again");

  // A BMP280 instead: chip 88, no humidity register writes, h_raw 0, calibration tail zero.
  bme.present = false;
  run(ENV_PERIOD_MS * (SENSOR_FAIL_LIMIT + 1) + 200);
  CHECK(Serial.out.find("I:BME280 not answering") != std::string::npos, "BME280 gone");
  bme.chip = 0x58;
  bme.ctrlHum = 0;
  bme.present = true;
  Serial.out.clear();
  sent.clear();
  run(SENSOR_RETRY_MS + ENV_PERIOD_MS + 2500);
  CHECK(Serial.out.find("I:BMP280 ok (no humidity)") != std::string::npos, "BMP280 found");
  bool rc = false, rb = false;
  for (auto &s : sent) {
    if (s.second.rfind("$RC,88,", 0) == 0 && s.second.find("00000000000000,K2UA*") != std::string::npos) rc = true;
    if (s.second.rfind("$RB,", 0) == 0 && s.second.find(",415148,519888,0,88,1,K2UA*") != std::string::npos) rb = true;
  }
  CHECK(rc && rb, "BMP280 packets: $RC %d $RB %d", rc, rb);
  CHECK(bme.ctrlHum == 0, "no humidity register writes on a BMP280");
}
#endif

#if REMTLM_ROLE == ROLE_BASE
// Run until the base sends something on the LoRa port (the noise query), at most ms.
static void runUntilSent(uint32_t ms) {
  for (uint32_t i = 0; i < ms && loraSerial.out.empty(); i++) step();
}

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
  {
    TiltData td = {9, 4466, -1200, 255961, 1840, 1, 1, "K2UA"};
    char ra[TLM_MAX_LINE];
    tlmFormatTilt(ra, sizeof(ra), &td);
    Serial.out.clear();
    loraSerial.feed(std::string(ra) + std::string(1, (char)0xA8));
    run(20);
    std::string ras(ra);
    CHECK(Serial.out.find(ras.substr(0, ras.size() - 2)) != std::string::npos, "$RA forwarded: %s", Serial.out.c_str());
    CHECK(Serial.out.find("R:tower,-88") != std::string::npos, "$RA counts as the tower's: %s", Serial.out.c_str());
  }
  CHECK(loraSerial.out.empty(), "base never transmits");
  CHECK(e220.cfg.TRANSMISSION_MODE.enableRSSI == RSSI_ENABLED, "base turns on the RSSI byte");
  CHECK(e220.cfg.OPTION.RSSIAmbientNoise == RSSI_AMBIENT_NOISE_ENABLED, "base turns on the noise register");

  // An RSSI byte after each packet: dBm = -(256 - byte). It names the packet's sender.
  Serial.out.clear();
  loraSerial.feed(rtLine(3) + std::string(1, (char)0x9C) + rs + std::string(1, (char)0xC1));
  run(20);
  size_t rt3 = Serial.out.find("$RT,3,"), r1 = Serial.out.find("R:tower,-100");
  size_t rsAt = Serial.out.find("$RS,5,"), r2 = Serial.out.find("R:psu,-63");
  CHECK(rt3 != std::string::npos && r1 != std::string::npos && r1 > rt3, "R:tower after its $RT: %s", Serial.out.c_str());
  CHECK(rsAt != std::string::npos && r2 != std::string::npos && r2 > rsAt, "R:psu after its $RS: %s", Serial.out.c_str());
  // No R: for a packet that failed its checksum: we can't tell who sent it.
  Serial.out.clear();
  loraSerial.feed(bad + std::string(1, (char)0xA0));
  run(20);
  CHECK(Serial.out.find("R:") == std::string::npos, "no R: after a bad packet: %s", Serial.out.c_str());

  // Noise floor: after NOISE_POLL_MS, once the link is quiet, the base sends
  // C0 C1 C2 C3 00 01 and prints the reply's value.
  Serial.out.clear();
  loraSerial.out.clear();
  runUntilSent(NOISE_POLL_MS + NOISE_QUIET_MS + 10);
  const std::string q("\xC0\xC1\xC2\xC3\x00\x01", 6);
  CHECK(loraSerial.out == q, "noise query sent once (%zu bytes)", loraSerial.out.size());
  loraSerial.feed(std::string("\xC1\x00\x01\x90", 4));
  run(5);
  CHECK(Serial.out.find("N:-112") != std::string::npos, "noise printed: %s", Serial.out.c_str());
  // A packet arriving during a query still gets its RSSI, even a 0xC1 one, and
  // the noise reply after it is still read.
  Serial.out.clear();
  loraSerial.out.clear();
  runUntilSent(NOISE_POLL_MS + NOISE_QUIET_MS + 10);
  CHECK(loraSerial.out == q, "second noise query");
  loraSerial.feed(rs + std::string("\xC1\xC1\x00\x01\x9A", 5));
  run(10);
  CHECK(Serial.out.find("R:psu,-63") != std::string::npos, "RSSI during a query: %s", Serial.out.c_str());
  CHECK(Serial.out.find("N:-102") != std::string::npos, "noise after that packet: %s", Serial.out.c_str());
  // No reply: the query times out and the next one goes out on schedule.
  loraSerial.out.clear();
  runUntilSent(NOISE_POLL_MS + NOISE_QUIET_MS + 10);
  CHECK(loraSerial.out == q, "query after a timeout");
  run(NOISE_REPLY_MS + 5);
  CHECK(nzState == 0, "timed-out query cleared");
}
#endif

int main() {
#if REMTLM_ROLE == ROLE_PSU
  testPsu();
#elif REMTLM_ROLE == ROLE_TOWER
  testTower();
#if TILT_ENABLE
  testTowerSensors();
#endif
#else
  testBase();
#endif
  if (failures) std::printf("%d FAILED\n", failures);
  return failures ? 1 : 0;
}
