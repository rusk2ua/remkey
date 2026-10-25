// remkey - remote CW keyer for Arduino Nano/Uno
//
// One sketch, two roles (see config.h):
//   CLIENT  (travel end): iambic keyer with local sidetone. Every character you
//           send with the paddle is decoded and reported to the host as "K:<c>".
//           A PTT pushbutton reports "B:P". The host app forwards both to the
//           station over the network.
//   STATION (shack end):  receives text ("T:...") from the host and re-keys it
//           with exact timing on an optocoupler wired to the radio's KEY jack.
//           "P:1"/"P:0" drive a second optocoupler on the radio's PTT/SEND line.
//           A watchdog drops PTT and stops keying if the host goes quiet.
//
// Serial protocol (115200 baud, newline-terminated lines):
//   host -> keyer                     keyer -> host
//   T:<text>   queue text to send     K:<c>    paddle character ("K: " = word space,
//   W:<wpm>    set speed                       "K:{.-..-}" = unrecognised pattern)
//   F:<hz>     sidetone frequency     B:P      PTT button pressed
//   M:<0|1>    sidetone on/off        W:<wpm>  speed pot changed
//   P:<0|1>    PTT output             D        text queue drained / tune ended
//   L:<0|1>    PTT LED (D12)          !:WDOG   watchdog fired (PTT + key dropped)
//   U:<ms>     tune carrier (capped)  E:<msg>  error
//   X          abort text/tune        S:...    status (reply to ?)
//   H          heartbeat              V:...    version (reply to V, and at boot)
//   G:<0|1>    watchdog on/off
//   R:<0|1>    paddle drives KEY OUT
//   ?          status
//   V          version
//
// Text may contain raw element patterns in braces, e.g. "{...-.-}" for SK.

#include "config.h"
#include "keyer_types.h"

#define FW_VERSION "0.2.0"

// ---------------------------------------------------------------------------
// Morse table
// ---------------------------------------------------------------------------
struct MorseEntry {
  char c;
  char pat[8];
};

static const MorseEntry MORSE[] PROGMEM = {
  {'A', ".-"},    {'B', "-..."},  {'C', "-.-."},  {'D', "-.."},   {'E', "."},
  {'F', "..-."},  {'G', "--."},   {'H', "...."},  {'I', ".."},    {'J', ".---"},
  {'K', "-.-"},   {'L', ".-.."},  {'M', "--"},    {'N', "-."},    {'O', "---"},
  {'P', ".--."},  {'Q', "--.-"},  {'R', ".-."},   {'S', "..."},   {'T', "-"},
  {'U', "..-"},   {'V', "...-"},  {'W', ".--"},   {'X', "-..-"},  {'Y', "-.--"},
  {'Z', "--.."},
  {'0', "-----"}, {'1', ".----"}, {'2', "..---"}, {'3', "...--"}, {'4', "....-"},
  {'5', "....."}, {'6', "-...."}, {'7', "--..."}, {'8', "---.."}, {'9', "----."},
  {'.', ".-.-.-"}, {',', "--..--"}, {'?', "..--.."}, {'/', "-..-."}, {'=', "-...-"},
  {'+', ".-.-."},  {'-', "-....-"}, {'(', "-.--."},  {')', "-.--.-"}, {'\'', ".----."},
  {':', "---..."}, {'"', ".-..-."}, {'@', ".--.-."}, {'&', ".-..."},  {'!', "-.-.--"},
  {';', "-.-.-."},
};
static const uint8_t MORSE_COUNT = sizeof(MORSE) / sizeof(MORSE[0]);

#define MAX_PAT 10   // longest element pattern we will send or decode

static bool lookupPattern(char c, char *out) {
  for (uint8_t i = 0; i < MORSE_COUNT; i++) {
    MorseEntry e;
    memcpy_P(&e, &MORSE[i], sizeof(e));
    if (e.c == c) {
      strcpy(out, e.pat);
      return true;
    }
  }
  return false;
}

static char lookupChar(const char *pat) {
  for (uint8_t i = 0; i < MORSE_COUNT; i++) {
    MorseEntry e;
    memcpy_P(&e, &MORSE[i], sizeof(e));
    if (strcmp(e.pat, pat) == 0) return e.c;
  }
  return 0;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
static uint8_t  wpm = DEFAULT_WPM;
static uint16_t ditMs = 1200 / DEFAULT_WPM;
static uint16_t toneHz = DEFAULT_TONE_HZ;
static bool sidetoneOn = DEFAULT_SIDETONE;
static bool paddleKeysOut = DEFAULT_PADDLE_OUT;
static bool wdogEnabled = DEFAULT_WDOG;
static bool pttOn = false;
static bool ledOn = false;
static bool keyDown = false;
static uint32_t lastRxMs = 0;

static void setWpm(int w) {
  if (w < WPM_MIN) w = WPM_MIN;
  if (w > WPM_MAX) w = WPM_MAX;
  wpm = (uint8_t)w;
  ditMs = 1200 / wpm;
}

// Key the line. driveOutput=false keeps the radio optocoupler off (sidetone only).
static void cwLed(bool on) {
  digitalWrite(PIN_LED, (on != (bool)LED_ACTIVE_LOW) ? HIGH : LOW);
}

static void keyLine(bool down, bool driveOutput) {
  keyDown = down;
  digitalWrite(PIN_KEY_OUT, (down && driveOutput) ? HIGH : LOW);
  cwLed(down);             // on-board LED follows every element sent, on both roles
  if (sidetoneOn) {
    if (down) tone(PIN_SIDETONE, toneHz);
    else noTone(PIN_SIDETONE);
  }
}

static void updateLed() {
  digitalWrite(PIN_PTT_LED, (ledOn || pttOn) ? HIGH : LOW);
}

static void setPtt(bool on) {
  pttOn = on;
  digitalWrite(PIN_PTT_OUT, on ? HIGH : LOW);
  updateLed();
}

// ---------------------------------------------------------------------------
// Text queue (ring buffer)
// ---------------------------------------------------------------------------
static char q[QUEUE_SIZE];
static uint8_t qHead = 0, qTail = 0, qLen = 0;

static bool qPush(char c) {
  if (qLen >= QUEUE_SIZE) return false;
  q[qTail] = c;
  qTail = (qTail + 1) % QUEUE_SIZE;
  qLen++;
  return true;
}

static char qPop() {
  if (qLen == 0) return 0;
  char c = q[qHead];
  qHead = (qHead + 1) % QUEUE_SIZE;
  qLen--;
  return c;
}

static void qClear() { qHead = qTail = qLen = 0; }

// ---------------------------------------------------------------------------
// Text sender (station keys the rig from here)
// ---------------------------------------------------------------------------
static TState tState = T_IDLE;
static char tPat[MAX_PAT + 1];
static uint8_t tIdx = 0;
static uint32_t tEnd = 0;
static bool textWasBusy = false;

static void startTextElement() {
  uint16_t dur = (tPat[tIdx] == '-') ? 3 * ditMs : ditMs;
  keyLine(true, true);
  tState = T_ELEM;
  tEnd += dur;
}

// Pull the next symbol off the queue. Returns false if nothing sendable.
static bool loadNextSymbol(uint32_t now) {
  while (qLen > 0) {
    char c = qPop();
    tEnd = now;
    if (c == ' ') {
      tState = T_WAIT;
      tEnd += 4 * ditMs;   // + 3 from the previous char gap = 7-unit word space
      return true;
    }
    if (c == '{') {
      uint8_t n = 0;
      while (qLen > 0) {
        char e = qPop();
        if (e == '}') break;
        if ((e == '.' || e == '-') && n < MAX_PAT) tPat[n++] = e;
      }
      tPat[n] = 0;
      if (n == 0) continue;
    } else if (!lookupPattern(c, tPat)) {
      continue;  // unknown character: skip
    }
    tIdx = 0;
    startTextElement();
    return true;
  }
  return false;
}

static void abortText() {
  qClear();
  if (tState != T_IDLE) {
    keyLine(false, true);
    tState = T_IDLE;
  }
  textWasBusy = false;
}

// ---------------------------------------------------------------------------
// Iambic paddle keyer + decoder
// ---------------------------------------------------------------------------
static PState pState = P_IDLE;
static Elem curElem = E_NONE, lastElem = E_NONE;
static bool ditLatch = false, dahLatch = false;
static uint32_t pEnd = 0;
static uint32_t lastElemEnd = 0;
static char dPat[MAX_PAT + 1];
static uint8_t dLen = 0;
static bool dOverflow = false;
static bool wordPending = false;

static bool ditPressed() { return digitalRead(SWAP_PADDLES ? PIN_DAH : PIN_DIT) == LOW; }
static bool dahPressed() { return digitalRead(SWAP_PADDLES ? PIN_DIT : PIN_DAH) == LOW; }

static void startPaddleElement(Elem e, uint32_t now, bool fromIdle) {
  if (tState != T_IDLE || qLen > 0) {
    abortText();          // paddle always wins over queued text / tune
  }
  curElem = e;
  if (fromIdle) pEnd = now;
  pEnd += (e == E_DAH) ? 3 * ditMs : ditMs;
  pState = P_ELEM;
  keyLine(true, paddleKeysOut);
  if (dLen < MAX_PAT) dPat[dLen++] = (e == E_DAH) ? '-' : '.';
  else dOverflow = true;
  wordPending = false;
}

static Elem chooseNext(bool useLatches) {
  bool d = ditPressed() || (useLatches && ditLatch);
  bool h = dahPressed() || (useLatches && dahLatch);
  ditLatch = dahLatch = false;
  if (d && h) return (lastElem == E_DIT) ? E_DAH : E_DIT;
  if (d) return E_DIT;
  if (h) return E_DAH;
  return E_NONE;
}

static void emitDecoded() {
  dPat[dLen] = 0;
  char c = dOverflow ? 0 : lookupChar(dPat);
  Serial.print(F("K:"));
  if (c) {
    Serial.println(c);
  } else {
    Serial.print('{');
    Serial.print(dPat);
    Serial.println('}');
  }
  dLen = 0;
  dOverflow = false;
  wordPending = true;
}

static void servicePaddle(uint32_t now) {
  switch (pState) {
    case P_IDLE: {
      Elem e = chooseNext(false);
      if (e != E_NONE) {
        startPaddleElement(e, now, true);
      } else if (dLen > 0 && now - lastElemEnd >= 2UL * ditMs) {
        emitDecoded();
      } else if (wordPending && now - lastElemEnd >= 5UL * ditMs) {
        Serial.println(F("K: "));
        wordPending = false;
      }
      break;
    }
    case P_ELEM:
      // latch the opposite paddle while an element is sounding
      if (curElem == E_DIT && dahPressed()) dahLatch = true;
      if (curElem == E_DAH && ditPressed()) ditLatch = true;
      if ((int32_t)(now - pEnd) >= 0) {
        keyLine(false, paddleKeysOut);
        lastElem = curElem;
        pState = P_GAP;
        pEnd += ditMs;
      }
      break;
    case P_GAP:
      if (lastElem == E_DIT && dahPressed()) dahLatch = true;
      if (lastElem == E_DAH && ditPressed()) ditLatch = true;
      if ((int32_t)(now - pEnd) >= 0) {
        Elem e = chooseNext(KEYER_MODE_B);
        if (e != E_NONE) {
          startPaddleElement(e, now, false);
        } else {
          pState = P_IDLE;
          lastElemEnd = pEnd - ditMs;   // end of the last key-down
        }
      }
      break;
  }
}

static void serviceText(uint32_t now) {
  switch (tState) {
    case T_IDLE:
      if (qLen > 0 && pState == P_IDLE) {
        textWasBusy = true;
        loadNextSymbol(now);
      } else if (textWasBusy && qLen == 0) {
        textWasBusy = false;
        Serial.println(F("D"));
      }
      break;
    case T_ELEM:
      if ((int32_t)(now - tEnd) >= 0) {
        keyLine(false, true);
        tIdx++;
        if (tPat[tIdx]) {
          tState = T_GAP;
          tEnd += ditMs;
        } else {
          tState = T_WAIT;
          tEnd += 3 * ditMs;   // inter-character gap
        }
      }
      break;
    case T_GAP:
      if ((int32_t)(now - tEnd) >= 0) startTextElement();
      break;
    case T_WAIT:
      if ((int32_t)(now - tEnd) >= 0) {
        // chain straight into the next symbol to keep timing exact
        if (qLen > 0 && pState == P_IDLE) {
          uint32_t t0 = tEnd;
          if (!loadNextSymbol(t0)) tState = T_IDLE;
        } else {
          tState = T_IDLE;
        }
      }
      break;
    case T_TUNE:
      if ((int32_t)(now - tEnd) >= 0) {
        keyLine(false, true);
        tState = T_IDLE;
        textWasBusy = true;   // report D when tune ends
      }
      break;
  }
}

// ---------------------------------------------------------------------------
// PTT button and speed pot (client)
// ---------------------------------------------------------------------------
static bool btnLast = HIGH, btnStable = HIGH;
static uint32_t btnChange = 0;

static void serviceButton(uint32_t now) {
  bool r = digitalRead(PIN_PTT_BTN);
  if (r != btnLast) {
    btnLast = r;
    btnChange = now;
  }
  if (now - btnChange > 25 && r != btnStable) {
    btnStable = r;
    if (r == LOW) Serial.println(F("B:P"));
  }
}

#if USE_SPEED_POT
static int potLastRaw = -100;
static uint32_t potNext = 0;
static void servicePot(uint32_t now) {
  if ((int32_t)(now - potNext) < 0) return;
  potNext = now + 50;
  int raw = analogRead(PIN_SPEED_POT);
  if (abs(raw - potLastRaw) < 12) return;
  potLastRaw = raw;
  int w = map(raw, 0, 1023, POT_WPM_MIN, POT_WPM_MAX);
  if (w != wpm) {
    setWpm(w);
    Serial.print(F("W:"));
    Serial.println(wpm);
  }
}
#endif

// ---------------------------------------------------------------------------
// Serial command parser
// ---------------------------------------------------------------------------
static char line[QUEUE_SIZE + 8];
static uint8_t lineLen = 0;

static void printStatus() {
  Serial.print(F("S:v=" FW_VERSION " role="));
  Serial.print(REMKEY_ROLE == ROLE_CLIENT ? F("client") : F("station"));
  Serial.print(F(" wpm="));
  Serial.print(wpm);
  Serial.print(F(" ptt="));
  Serial.print(pttOn ? 1 : 0);
  Serial.print(F(" key="));
  Serial.print(keyDown ? 1 : 0);
  Serial.print(F(" q="));
  Serial.println(qLen);
}

static void printVersion() {
  Serial.print(F("V:remkey " FW_VERSION " "));
  Serial.println(REMKEY_ROLE == ROLE_CLIENT ? F("client") : F("station"));
}

static void handleLine(const char *s) {
  lastRxMs = millis();
  char cmd = s[0];
  const char *arg = (s[1] == ':') ? s + 2 : s + 1;
  switch (cmd) {
    case 'T': {
      for (const char *p = arg; *p; p++) {
        char c = *p;
        if (c >= 'a' && c <= 'z') c -= 32;
        if (!qPush(c)) {
          Serial.println(F("E:QFULL"));
          break;
        }
      }
      break;
    }
    case 'W': setWpm(atoi(arg)); break;
    case 'F': {
      int f = atoi(arg);
      if (f >= 200 && f <= 1500) toneHz = f;
      break;
    }
    case 'M': sidetoneOn = (atoi(arg) != 0); if (!sidetoneOn) noTone(PIN_SIDETONE); break;
    case 'P': setPtt(atoi(arg) != 0); break;
    case 'L': ledOn = (atoi(arg) != 0); updateLed(); break;
    case 'U': {
      unsigned long ms = strtoul(arg, 0, 10);
      if (ms > TUNE_MAX_MS) ms = TUNE_MAX_MS;
      if (ms > 0 && pState == P_IDLE) {
        abortText();
        keyLine(true, true);
        tState = T_TUNE;
        tEnd = millis() + ms;
      }
      break;
    }
    case 'X': {
      bool wasBusy = (tState != T_IDLE) || qLen > 0;
      abortText();
      if (wasBusy) Serial.println(F("D"));
      break;
    }
    case 'H': break;
    case 'G': wdogEnabled = (atoi(arg) != 0); break;
    case 'R': paddleKeysOut = (atoi(arg) != 0); break;
    case '?': printStatus(); break;
    case 'V': printVersion(); break;
    default:  Serial.println(F("E:CMD")); break;
  }
}

static void serviceSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      line[lineLen] = 0;
      if (lineLen > 0) handleLine(line);
      lineLen = 0;
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }
}

static void serviceWatchdog(uint32_t now) {
  if (!wdogEnabled) return;
  if (!(pttOn || tState != T_IDLE || qLen > 0)) return;
  if (now - lastRxMs > WDOG_MS) {
    abortText();
    setPtt(false);
    Serial.println(F("!:WDOG"));
  }
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------
void setup() {
  pinMode(PIN_DIT, INPUT_PULLUP);
  pinMode(PIN_DAH, INPUT_PULLUP);
  pinMode(PIN_PTT_BTN, INPUT_PULLUP);
  pinMode(PIN_KEY_OUT, OUTPUT);
  pinMode(PIN_PTT_OUT, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_PTT_LED, OUTPUT);
  pinMode(PIN_SIDETONE, OUTPUT);
  digitalWrite(PIN_KEY_OUT, LOW);
  digitalWrite(PIN_PTT_OUT, LOW);
  cwLed(false);
  digitalWrite(PIN_PTT_LED, LOW);
  Serial.begin(115200);
  setWpm(DEFAULT_WPM);
  lastRxMs = millis();
  printVersion();
}

void loop() {
  uint32_t now = millis();
  serviceSerial();
  servicePaddle(now);
  serviceText(now);
  serviceButton(now);
#if USE_SPEED_POT
  servicePot(now);
#endif
  serviceWatchdog(now);
}
