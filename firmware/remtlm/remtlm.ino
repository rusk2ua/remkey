// remtlm - tower-top telemetry for remkey over an Ebyte E220-900T22D LoRa link.
//
// TOWER role (Nano at the tower top, powered from the 13.8 V supply via a 5 V buck):
//   - samples the PA power sense and the Kuhne MKU 10 G5 MON output every 5 ms,
//     keeping peak and average since the last packet (so a dit's peak isn't missed)
//   - watches the MKU's LD output (10 MHz reference lock); any unlock during an
//     interval is reported
//   - reads up to two DS18B20 probes (PA heatsink, transverter case)
//   - sends a $RT packet every 2 s, every 0.5 s while the PA shows output, and
//     immediately when lock changes
//   - polls the MKU's serial port: "v" once after boot, then "s" every minute, and
//     relays each reply verbatim as $RK packets. It never sends configuration commands.
//
// BASE role (Nano in the radio room, USB to the shack PC):
//   - forwards every valid packet to USB serial, unchanged
//   - prints "V:..." at boot and "C:..." with the LoRa configuration result
//
// Libraries (Arduino Library Manager):
//   "EByte LoRa E220 library" by Renzo Mischianti   (both roles)
//   "OneWire" by Paul Stoffregen                     (tower)
//   "DallasTemperature" by Miles Burton              (tower)

#include "config.h"
#include "tlm_proto.h"
#include <SoftwareSerial.h>

#define FREQUENCY_900   // E220-900: channel 0 = 850.125 MHz (only used for printing)
#define E220_22         // 22 dBm module family
#include "LoRa_E220.h"

#if REMTLM_ROLE == ROLE_TOWER
#include <OneWire.h>
#include <DallasTemperature.h>
#endif

#define FW_VERSION "0.2.0"

SoftwareSerial loraSerial(PIN_E220_TXD, PIN_E220_RXD);   // (rx, tx) from the Nano's side
LoRa_E220 e220(&loraSerial, PIN_E220_AUX, PIN_E220_M0, PIN_E220_M1);

// ---------------------------------------------------------------------------
// LoRa module configuration (both roles)
// ---------------------------------------------------------------------------
static bool configureLora() {
  ResponseStructContainer c = e220.getConfiguration();
  if (c.status.code != E220_SUCCESS) {
    Serial.print(F("C:ERR read config: "));
    Serial.println(c.status.getResponseDescription());
    c.close();
    return false;
  }
  Configuration cfg = *(Configuration *)c.data;
  c.close();

  Configuration want = cfg;
  want.ADDH = LORA_ADDH;
  want.ADDL = LORA_ADDL;
  want.CHAN = LORA_CHANNEL;
  want.SPED.uartBaudRate = UART_BPS_9600;
  want.SPED.airDataRate = LORA_AIR_RATE;
  want.SPED.uartParity = MODE_00_8N1;
  want.OPTION.subPacketSetting = SPS_200_00;
  want.OPTION.RSSIAmbientNoise = RSSI_AMBIENT_NOISE_DISABLED;
  want.OPTION.transmissionPower = LORA_TX_POWER;
  want.TRANSMISSION_MODE.enableRSSI = RSSI_DISABLED;
  want.TRANSMISSION_MODE.fixedTransmission = FT_TRANSPARENT_TRANSMISSION;
  want.TRANSMISSION_MODE.enableLBT = LBT_DISABLED;
  want.TRANSMISSION_MODE.WORPeriod = WOR_2000_011;
  want.CRYPT.CRYPT_H = 0;   // no encryption: amateur transmissions may not be obscured
  want.CRYPT.CRYPT_L = 0;

  bool same = cfg.ADDH == want.ADDH && cfg.ADDL == want.ADDL && cfg.CHAN == want.CHAN &&
              cfg.SPED.uartBaudRate == want.SPED.uartBaudRate &&
              cfg.SPED.airDataRate == want.SPED.airDataRate &&
              cfg.SPED.uartParity == want.SPED.uartParity &&
              cfg.OPTION.subPacketSetting == want.OPTION.subPacketSetting &&
              cfg.OPTION.RSSIAmbientNoise == want.OPTION.RSSIAmbientNoise &&
              cfg.OPTION.transmissionPower == want.OPTION.transmissionPower &&
              cfg.TRANSMISSION_MODE.enableRSSI == want.TRANSMISSION_MODE.enableRSSI &&
              cfg.TRANSMISSION_MODE.fixedTransmission == want.TRANSMISSION_MODE.fixedTransmission &&
              cfg.TRANSMISSION_MODE.enableLBT == want.TRANSMISSION_MODE.enableLBT;
  if (!same) {
    ResponseStatus rs = e220.setConfiguration(want, WRITE_CFG_PWR_DWN_SAVE);
    if (rs.code != E220_SUCCESS) {
      Serial.print(F("C:ERR write config: "));
      Serial.println(rs.getResponseDescription());
      return false;
    }
    Serial.println(F("C:written"));
  }
  Serial.print(F("C:ok ch="));
  Serial.print(LORA_CHANNEL);
  Serial.print(F(" freq_khz="));
  Serial.println(850125UL + 1000UL * LORA_CHANNEL);
  e220.setMode(MODE_0_NORMAL);
  return true;
}

static void printVersion() {
  Serial.print(F("V:remtlm " FW_VERSION " "));
  Serial.println(REMTLM_ROLE == ROLE_TOWER ? F("tower") : F("base"));
}

#if REMTLM_ROLE == ROLE_TOWER
// ===========================================================================
// TOWER
// ===========================================================================
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature probes(&oneWire);
#if XV_SERIAL_ENABLE
SoftwareSerial xvSerial(PIN_XV_RX, PIN_XV_TX);
#endif

static uint16_t seq = 0;
static uint16_t paPk = 0, xvPk = 0;
static uint32_t paSum = 0;
static uint16_t nSamples = 0;
static bool lockAll = true;
static bool lastLock = true;
static int16_t tempC10[2] = {TLM_TEMP_NONE, TLM_TEMP_NONE};
static uint8_t probeCount = 0;
static bool tempPending = false;
static uint32_t nextSample = 0, nextReport = 0, tempRequested = 0, nextTemp = 0;

static uint16_t pinMv(uint8_t pin) {   // volts at the Nano pin
  return (uint16_t)(((uint32_t)analogRead(pin) * VREF_MV) / 1023UL);
}

static uint16_t senseMv(uint8_t pin) { // volts at the source, before the divider
  return (uint16_t)(((uint32_t)pinMv(pin) * DIVIDER_X1000) / 1000UL);
}

static bool refLocked() {
  bool hi = pinMv(PIN_LO_LOCK) > LOCK_THRESHOLD_MV;
  return LOCK_ACTIVE_HIGH ? hi : !hi;
}

// Wait (briefly) until the E220 can take more data, then send one line.
static void loraSend(const char *buf, int n) {
  uint32_t t0 = millis();
  while (digitalRead(PIN_E220_AUX) == LOW && millis() - t0 < 300) {}
  loraSerial.write((const uint8_t *)buf, n);
  Serial.print(buf);   // also on USB for bench work
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));
}

static void sendReport() {
  char buf[TLM_MAX_LINE];
  TlmData d;
  d.seq = seq++;
  d.paPkMv = paPk;
  d.paAvgMv = nSamples ? (uint16_t)(paSum / nSamples) : 0;
  d.xvPkMv = xvPk;
  d.lock = LOCK_MONITOR ? (lockAll ? 1 : 0) : 2;
  d.t1C10 = tempC10[0];
  d.t2C10 = tempC10[1];
  d.uptimeS = millis() / 1000UL;
  d.call = CALLSIGN;
  int n = tlmFormat(buf, sizeof(buf), &d);
  if (n > 0) loraSend(buf, n);
  paPk = xvPk = 0;
  paSum = 0;
  nSamples = 0;
  lockAll = refLocked();
}

static void serviceTemp(uint32_t now) {
  if (!tempPending && (int32_t)(now - nextTemp) >= 0) {
    probes.requestTemperatures();          // non-blocking (see setup)
    tempRequested = now;
    tempPending = true;
    nextTemp = now + TEMP_PERIOD_MS;
  }
  if (tempPending && now - tempRequested >= 800) {   // 12-bit conversion is 750 ms
    for (uint8_t i = 0; i < 2; i++) {
      float c = (i < probeCount) ? probes.getTempCByIndex(i) : DEVICE_DISCONNECTED_C;
      tempC10[i] = (c <= DEVICE_DISCONNECTED_C + 1)
                       ? TLM_TEMP_NONE
                       : (int16_t)(c * 10.0f + (c >= 0 ? 0.5f : -0.5f));
    }
    tempPending = false;
  }
}

#if XV_SERIAL_ENABLE
// --- Kuhne MKU 10 G5 serial polling ----------------------------------------
static char xvBuf[XV_BUF];
static uint16_t xvLen = 0;
static bool xvWaiting = false, xvVersionDone = false;
static char xvCmd = 'v';
static uint8_t xvCapture = 0;
static uint32_t xvT0 = 0, xvLast = 0, xvNextPoll = XV_FIRST_POLL_MS;

static void xvStartPoll(char cmd, uint32_t now) {
  while (xvSerial.available() > 0) xvSerial.read();
  xvSerial.write(cmd);
  xvSerial.print(F(XV_CMD_SUFFIX));
  xvCmd = cmd;
  xvLen = 0;
  xvT0 = xvLast = now;
  xvWaiting = true;
}

static void xvSendReply() {
  while (xvLen > 0 && xvBuf[xvLen - 1] == '|') xvLen--;     // trailing line breaks
  if (xvLen == 0) {
    const char *none = "(no reply)";
    xvLen = strlen(none);
    memcpy(xvBuf, none, xvLen);
  }
  uint8_t total = (uint8_t)((xvLen + TLM_RK_TEXT - 1) / TLM_RK_TEXT);
  char line[TLM_RK_LINE];
  for (uint8_t part = 0; part < total; part++) {
    uint16_t off = part * TLM_RK_TEXT;
    uint16_t len = xvLen - off < TLM_RK_TEXT ? xvLen - off : TLM_RK_TEXT;
    int n = tlmFormatReply(line, sizeof(line), xvCapture, xvCmd, part + 1, total,
                           xvBuf + off, len, CALLSIGN);
    if (n > 0) loraSend(line, n);
  }
  xvCapture++;
}

static void serviceXv(uint32_t now) {
  if (!xvWaiting) {
    if ((int32_t)(now - xvNextPoll) >= 0) xvStartPoll(xvVersionDone ? 's' : 'v', now);
    return;
  }
  while (xvSerial.available() > 0) {
    char c = tlmReplyChar((char)xvSerial.read());
    xvLast = now;
    if (!c) continue;
    if (c == '|' && (xvLen == 0 || xvBuf[xvLen - 1] == '|')) continue;   // collapse breaks
    if (c == ' ' && xvLen > 0 && xvBuf[xvLen - 1] == ' ') continue;      // collapse spaces
    if (xvLen < XV_BUF) xvBuf[xvLen++] = c;
  }
  bool quiet = xvLen > 0 && now - xvLast >= XV_REPLY_GAP_MS;
  if (quiet || now - xvT0 >= XV_REPLY_MAX_MS) {
    xvWaiting = false;
    xvSendReply();
    if (xvCmd == 'v') {
      xvVersionDone = true;
      xvNextPoll = now + 1000;
    } else {
      xvNextPoll = now + XV_POLL_MS;
    }
  }
}
#endif

void setup() {
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_LO_LOCK, INPUT);
  Serial.begin(115200);
  printVersion();
  e220.begin();
  configureLora();
  probes.begin();
  probeCount = probes.getDeviceCount();
  probes.setResolution(12);
  probes.setWaitForConversion(false);
  Serial.print(F("I:temperature probes="));
  Serial.println(probeCount);
#if XV_SERIAL_ENABLE
  xvSerial.begin(XV_BAUD);
  xvSerial.listen();     // the E220 port is only written from here on
#endif
  lastLock = lockAll = refLocked();
  nextReport = millis() + 500;
}

void loop() {
  uint32_t now = millis();
  if ((int32_t)(now - nextSample) >= 0) {
    nextSample = now + SAMPLE_MS;
    uint16_t pa = senseMv(PIN_PA_SENSE);
    uint16_t xv = senseMv(PIN_XV_SENSE);
    if (pa > paPk) paPk = pa;
    if (xv > xvPk) xvPk = xv;
    paSum += pa;
    nSamples++;
    if (LOCK_MONITOR) {
      bool lk = refLocked();
      if (!lk) lockAll = false;
      if (lk != lastLock) {        // report lock changes right away
        lastLock = lk;
        nextReport = now;
      }
    }
  }
  serviceTemp(now);
#if XV_SERIAL_ENABLE
  serviceXv(now);
#endif
  if ((int32_t)(now - nextReport) >= 0) {
    bool active = paPk > ACTIVE_MV;
    sendReport();
    nextReport = now + (active ? REPORT_ACTIVE_MS : REPORT_IDLE_MS);
  }
}

#else
// ===========================================================================
// BASE
// ===========================================================================
static char line[TLM_RK_LINE + 8];
static uint8_t lineLen = 0;
static uint16_t badCount = 0;

void setup() {
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  printVersion();
  e220.begin();
  configureLora();
}

void loop() {
  while (loraSerial.available() > 0) {
    char c = (char)loraSerial.read();
    if (c == '\r') continue;
    if (c == '$') {                // start of packet: resync
      lineLen = 0;
      line[lineLen++] = c;
      continue;
    }
    if (lineLen == 0) continue;    // noise between packets
    if (c == '\n') {
      line[lineLen] = 0;
      if (tlmValid(line)) {
        Serial.println(line);
        digitalWrite(PIN_LED, !digitalRead(PIN_LED));
      } else {
        badCount++;
        Serial.print(F("E:bad packet #"));
        Serial.println(badCount);
      }
      lineLen = 0;
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    } else {
      lineLen = 0;                 // overlong: drop and wait for the next '$'
    }
  }
}
#endif
