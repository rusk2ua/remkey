// Host-side simulation of remkey.ino. Build twice (station and client role):
//   g++ -std=c++17 -I. -I../../firmware/remkey -DREMKEY_ROLE=2 sim_test.cpp -o sim_station
//   g++ -std=c++17 -I. -I../../firmware/remkey -DREMKEY_ROLE=1 sim_test.cpp -o sim_client
#include "Arduino.h"
#include <cstdio>
#include <functional>

SimState sim;
MockSerial Serial;

#include "remkey.ino"

void digitalWrite(int p, int v) {
  if (p == PIN_KEY_OUT && sim.pinOut[p] != v) sim.keyLog.push_back({sim.now, v});
  if (p == PIN_PTT_OUT && sim.pinOut[p] != v) sim.pttLog.push_back({sim.now, v});
  sim.pinOut[p] = v;
}

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

// step until cond() or timeout; returns true if cond met
static bool until(std::function<bool()> cond, uint32_t timeoutMs) {
  for (uint32_t i = 0; i < timeoutMs; i++) {
    if (cond()) return true;
    step();
  }
  return cond();
}

static void reset() {
  sim = SimState();
  Serial.out.clear();
  Serial.in.clear();
  // reset sketch state
  qClear();
  tState = T_IDLE;
  pState = P_IDLE;
  dLen = 0;
  wordPending = false;
  textWasBusy = false;
  ditLatch = dahLatch = false;
  lastElem = E_NONE;
  btnLast = btnStable = HIGH;
  sidetoneOn = DEFAULT_SIDETONE;
  paddleKeysOut = DEFAULT_PADDLE_OUT;
  wdogEnabled = DEFAULT_WDOG;
  pttOn = ledOn = keyDown = false;
  setup();
  Serial.out.clear();
}

static void send(const std::string &line) { Serial.feed(line + "\n"); step(); }

static std::string decodedText() {
  std::string r;
  const std::string &o = Serial.out;
  size_t pos = 0;
  while ((pos = o.find("K:", pos)) != std::string::npos) {
    size_t eol = o.find("\r\n", pos);
    r += o.substr(pos + 2, eol - pos - 2);
    pos = eol;
  }
  return r;
}

// Is the sounding element visible? (station: KEY OUT pin; client: sidetone)
static bool sounding() {
  return REMKEY_ROLE == ROLE_STATION ? sim.pinOut[PIN_KEY_OUT] == HIGH : sim.toneOn;
}

// Operator model: tap each element, releasing once it starts sounding.
static void paddleSend(const std::string &text) {
  for (char c : text) {
    if (c == ' ') { step(4 * ditMs); continue; }
    char pat[MAX_PAT + 1];
    if (!lookupPattern(c, pat)) continue;
    for (char *p = pat; *p; p++) {
      int pin = (*p == '-') ? PIN_DAH : PIN_DIT;
      sim.pinIn[pin] = LOW;
      until([] { return sounding(); }, 500);
      step(ditMs / 2);
      sim.pinIn[pin] = HIGH;
      until([] { return !sounding(); }, 500);
    }
    step(3 * ditMs);  // operator's character gap
  }
}

static uint32_t totalKeyDown() {
  uint32_t total = 0, downAt = 0;
  for (auto &e : sim.keyLog) {
    if (e.second == HIGH) downAt = e.first;
    else total += e.first - downAt;
  }
  return total;
}

static int keyDownCount() {
  int n = 0;
  for (auto &e : sim.keyLog) if (e.second == HIGH) n++;
  return n;
}

// ---------------------------------------------------------------------------
static void test_paddle_decode() {
  std::printf("paddle decode\n");
  reset();
  send("W:20");
  paddleSend("CQ TEST K2UA");
  step(10 * ditMs);
  std::string d = decodedText();
  CHECK(d == "CQ TEST K2UA ", "decoded '%s'", d.c_str());
}

static void test_paddle_unknown_pattern() {
  std::printf("paddle unknown pattern\n");
  reset();
  send("W:20");
  // SK is not in the table: ...-.-
  for (char e : std::string("...-.-")) {
    int pin = (e == '-') ? PIN_DAH : PIN_DIT;
    sim.pinIn[pin] = LOW;
    until([] { return sounding(); }, 500);
    step(ditMs / 2);
    sim.pinIn[pin] = HIGH;
    until([] { return !sounding(); }, 500);
  }
  step(4 * ditMs);
  std::string d = decodedText();
  CHECK(d.rfind("{...-.-}", 0) == 0, "decoded '%s'", d.c_str());
}

static void test_iambic_squeeze() {
  std::printf("iambic squeeze\n");
  reset();
  send("W:20");
  // squeeze both paddles, dit first -> alternating .-.- ; release after 4 elements
  sim.pinIn[PIN_DIT] = LOW;
  step(2);
  sim.pinIn[PIN_DAH] = LOW;
  int elements = 0;
  bool was = false;
  for (int i = 0; i < 2000 && elements < 4; i++) {
    step();
    bool s = sounding();
    if (s && !was) elements++;
    was = s;
  }
  // release partway through the 4th element (a dah): iambic B completes one
  // more opposite element, giving .-.-. (AR, sent as '+'); iambic A stops.
  step(ditMs);
  sim.pinIn[PIN_DIT] = HIGH;
  sim.pinIn[PIN_DAH] = HIGH;
  step(10 * ditMs);
  std::string d = decodedText();
#if KEYER_MODE_B
  CHECK(d == "+ ", "decoded '%s'", d.c_str());
#else
  CHECK(d == "{.-.-} ", "decoded '%s'", d.c_str());
#endif
}

static void test_text_timing() {
  std::printf("text timing (PARIS @20wpm)\n");
  reset();
  send("W:20");
  uint32_t t0 = sim.now;
  send("T:PARIS");
  bool done = until([] { return Serial.out.find("D\r\n") != std::string::npos; }, 10000);
  uint32_t elapsed = sim.now - t0;
  (void)elapsed;
#if REMKEY_ROLE == ROLE_STATION
  CHECK(done, "no D after PARIS");
  // 46 units: 31 element/gap units + 5 char gaps of 3
  CHECK(elapsed >= 46 * 60 && elapsed <= 46 * 60 + 10, "elapsed %u ms", elapsed);
  uint32_t down = totalKeyDown();
  CHECK(down >= 22 * 60 - 2 && down <= 22 * 60 + 2, "key down %u ms", down);
  CHECK(keyDownCount() == 14, "elements %d", keyDownCount());
#else
  CHECK(done, "client should still send queued text (sidetone)");
#endif
}

static void test_raw_pattern_and_space() {
  std::printf("raw pattern + word space\n");
  reset();
  send("W:20");
  send("T:E {...-.-}");
  until([] { return Serial.out.find("D\r\n") != std::string::npos; }, 10000);
#if REMKEY_ROLE == ROLE_STATION
  CHECK(keyDownCount() == 7, "elements %d", keyDownCount());
  // E down at t, raw starts after 1 + 3 + 4 = 8 units
  uint32_t gap = sim.keyLog[2].first - sim.keyLog[0].first;
  CHECK(gap >= 8 * 60 - 1 && gap <= 8 * 60 + 1, "E->SK start %u ms", gap);
#endif
}

static void test_tune_and_cap() {
  std::printf("tune + cap\n");
  reset();
  send("U:2000");
  CHECK(sim.pinOut[PIN_KEY_OUT] == HIGH, "tune not keyed");
  until([] { return Serial.out.find("D\r\n") != std::string::npos; }, 5000);
  CHECK(sim.pinOut[PIN_KEY_OUT] == LOW, "tune stuck");
  uint32_t down = totalKeyDown();
  CHECK(down >= 1999 && down <= 2002, "tune %u ms", down);

  reset();
  send("G:0");
  send("U:60000");
  step(30005);
  CHECK(sim.pinOut[PIN_KEY_OUT] == LOW, "tune not capped");
}

static void test_watchdog() {
  std::printf("watchdog\n");
  reset();
  send("G:1");
  send("P:1");
  CHECK(sim.pinOut[PIN_PTT_OUT] == HIGH, "PTT not on");
  // heartbeats keep it up
  for (int i = 0; i < 5; i++) { step(1000); send("H"); }
  CHECK(sim.pinOut[PIN_PTT_OUT] == HIGH, "PTT dropped with heartbeats");
  step(3100);
  CHECK(sim.pinOut[PIN_PTT_OUT] == LOW, "PTT not dropped by watchdog");
  CHECK(Serial.out.find("!:WDOG") != std::string::npos, "no WDOG message");

  reset();
  send("G:1");
  send("T:CQ CQ CQ CQ CQ CQ CQ CQ CQ CQ");
  step(3200);
  CHECK(sim.pinOut[PIN_KEY_OUT] == LOW && qLen == 0, "keying not stopped by watchdog");
}

static void test_paddle_aborts_text() {
  std::printf("paddle aborts text\n");
  reset();
  send("W:20");
  send("T:CQ CQ CQ CQ");
  step(500);
  sim.pinIn[PIN_DIT] = LOW;
  step(30);
  sim.pinIn[PIN_DIT] = HIGH;
  step(500);
  CHECK(qLen == 0, "queue not cleared (%d)", qLen);
}

static void test_ptt_button() {
  std::printf("ptt button\n");
  reset();
  sim.pinIn[PIN_PTT_BTN] = LOW;
  step(5);
  sim.pinIn[PIN_PTT_BTN] = HIGH;   // bounce
  step(3);
  sim.pinIn[PIN_PTT_BTN] = LOW;
  step(60);
  sim.pinIn[PIN_PTT_BTN] = HIGH;
  step(60);
  size_t n = 0, pos = 0;
  while ((pos = Serial.out.find("B:P", pos)) != std::string::npos) { n++; pos += 3; }
  CHECK(n == 1, "B:P count %zu", n);
}

static void test_client_paddle_does_not_key_rig() {
#if REMKEY_ROLE == ROLE_CLIENT
  std::printf("client paddle sidetone only\n");
  reset();
  send("W:20");
  paddleSend("E");
  CHECK(sim.keyLog.empty(), "client paddle drove KEY OUT");
#endif
}

static void test_status() {
  std::printf("status/version\n");
  reset();
  send("?");
  CHECK(Serial.out.find("S:v=0.1.0") != std::string::npos, "status: %s", Serial.out.c_str());
  send("V");
  CHECK(Serial.out.find("V:remkey") != std::string::npos, "version missing");
}

int main() {
  std::printf("== remkey firmware sim, role=%s ==\n", REMKEY_ROLE == ROLE_CLIENT ? "client" : "station");
  test_paddle_decode();
  test_paddle_unknown_pattern();
  test_iambic_squeeze();
  test_text_timing();
  test_raw_pattern_and_space();
#if REMKEY_ROLE == ROLE_STATION
  test_tune_and_cap();
  test_watchdog();
#endif
  test_paddle_aborts_text();
  test_ptt_button();
  test_client_paddle_does_not_key_rig();
  test_status();
  std::printf(failures ? "FAILED: %d\n" : "ALL PASSED\n", failures);
  return failures ? 1 : 0;
}
