// remtlm - tower telemetry for remkey over an Ebyte E220-900T22D LoRa link.
//
// TOWER role (Nano at the tower top, powered from the 13.8 V supply via a 5 V buck):
//   - samples the PA power sense and the Kuhne MKU 10 G5 MON output every 5 ms,
//     keeping peak and average since the last packet (so a dit's peak isn't missed)
//   - watches the MKU's LD output (10 MHz reference lock); any unlock during an
//     interval is reported
//   - reads up to two DS18B20 probes (PA heatsink, transverter case)
//   - optional (PWR_ENABLE 1): an INA226 in the top box, voltage at the enclosure
//     and current, sent as a $RP packet just before each $RT
//   - sends a $RT packet every 2 s, every 0.5 s while the PA shows output, and
//     immediately when lock changes
//   - polls the MKU's serial port: "v" once after boot, then "s" every minute, and
//     relays each reply verbatim as $RK packets. It never sends configuration commands.
//
// PSU role (Nano in the supply box at the tower base):
//   - reads an INA226 every 10 ms: supply output voltage and current into the tower
//     cable through a high-side shunt (min / max / average per interval)
//   - reads one DS18B20 (box temperature)
//   - listens on the LoRa channel and sends a $RS packet ~60 ms after each tower
//     $RT, in the gap before the tower's next packet; with no tower heard for
//     3.5 s it sends every 2 s on its own
//
// BASE role (Nano in the radio room, USB to the shack PC):
//   - forwards every valid packet (from the tower and the PSU box) to USB serial, unchanged
//   - prints "V:..." at boot and "C:..." with the LoRa configuration result
//
// Libraries (Arduino Library Manager):
//   "EByte LoRa E220 library" by Renzo Mischianti   (all roles)
//   "OneWire" by Paul Stoffregen                     (tower, PSU)
//   "DallasTemperature" by Miles Burton              (tower, PSU)

#include "config.h"
#include "tlm_proto.h"
#include <SoftwareSerial.h>

#define FREQUENCY_900   // E220-900: channel 0 = 850.125 MHz (only used for printing)
#define E220_22         // 22 dBm module family
#include "LoRa_E220.h"

#define HAS_SENSORS (REMTLM_ROLE == ROLE_TOWER || REMTLM_ROLE == ROLE_PSU)
#define HAS_INA226  ((REMTLM_ROLE == ROLE_TOWER && PWR_ENABLE) || REMTLM_ROLE == ROLE_PSU)
#define TEMP_PROBES (REMTLM_ROLE == ROLE_PSU ? 1 : 2)

#if HAS_SENSORS
#include <OneWire.h>
#include <DallasTemperature.h>
#endif
#if HAS_INA226
#include <Wire.h>
#endif

#define FW_VERSION "0.4.0"

SoftwareSerial loraSerial(PIN_E220_TXD, PIN_E220_RXD);   // (rx, tx) from the Nano's side
LoRa_E220 e220(&loraSerial, PIN_E220_AUX, PIN_E220_M0, PIN_E220_M1);

// ---------------------------------------------------------------------------
// LoRa module configuration (all roles)
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
#if REMTLM_ROLE == ROLE_TOWER
  Serial.println(F("tower"));
#elif REMTLM_ROLE == ROLE_PSU
  Serial.println(F("psu"));
#else
  Serial.println(F("base"));
#endif
}

#if HAS_SENSORS
// ===========================================================================
// Shared by TOWER and PSU: LoRa transmit, DS18B20 probes
// ===========================================================================
// Wait (briefly) until the E220 can take more data, then send one line.
static void loraSend(const char *buf, int n) {
  uint32_t t0 = millis();
  while (digitalRead(PIN_E220_AUX) == LOW && millis() - t0 < 300) {}
  loraSerial.write((const uint8_t *)buf, n);
  Serial.print(buf);   // also on USB for bench work
  digitalWrite(PIN_LED, !digitalRead(PIN_LED));
}

OneWire oneWire(PIN_ONEWIRE);
DallasTemperature probes(&oneWire);
static int16_t tempC10[2] = {TLM_TEMP_NONE, TLM_TEMP_NONE};
static uint8_t probeCount = 0;
static bool tempPending = false;
static uint32_t tempRequested = 0, nextTemp = 0;

static void tempSetup() {
  probes.begin();
  probeCount = probes.getDeviceCount();
  probes.setResolution(12);
  probes.setWaitForConversion(false);
  Serial.print(F("I:temperature probes="));
  Serial.println(probeCount);
}

static void serviceTemp(uint32_t now) {
  if (!tempPending && (int32_t)(now - nextTemp) >= 0) {
    probes.requestTemperatures();          // non-blocking (see setup)
    tempRequested = now;
    tempPending = true;
    nextTemp = now + TEMP_PERIOD_MS;
  }
  if (tempPending && now - tempRequested >= 800) {   // 12-bit conversion is 750 ms
    for (uint8_t i = 0; i < TEMP_PROBES; i++) {
      float c = (i < probeCount) ? probes.getTempCByIndex(i) : DEVICE_DISCONNECTED_C;
      tempC10[i] = (c <= DEVICE_DISCONNECTED_C + 1)
                       ? TLM_TEMP_NONE
                       : (int16_t)(c * 10.0f + (c >= 0 ? 0.5f : -0.5f));
    }
    tempPending = false;
  }
}

#endif

#if HAS_INA226
// ===========================================================================
// INA226 supply monitor (TOWER with PWR_ENABLE, and PSU)
// ===========================================================================
static bool pwrUp = false, pwrOkAll = false;
static uint8_t pwrFails = 0;
static uint32_t pwrNext = 0, pwrRetry = 0;
static uint32_t pwrVSum = 0;
static int32_t pwrISum = 0, pwrIMin = 0, pwrIMax = 0;
static uint16_t pwrVMin = 0, pwrVMax = 0, pwrN = 0;

static bool inaWrite(uint8_t reg, uint16_t v) {
  Wire.beginTransmission(INA226_ADDR);
  Wire.write(reg);
  Wire.write((uint8_t)(v >> 8));
  Wire.write((uint8_t)(v & 0xFF));
  return Wire.endTransmission() == 0;
}

static bool inaRead(uint8_t reg, uint16_t *v) {
  Wire.beginTransmission(INA226_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom((uint8_t)INA226_ADDR, (uint8_t)2) != 2) return false;
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  *v = ((uint16_t)hi << 8) | lo;
  return true;
}

static bool inaInit() {
  uint16_t mfr = 0, die = 0;
  if (!inaRead(0xFE, &mfr) || !inaRead(0xFF, &die)) return false;
  if (mfr != 0x5449 || (die & 0xFFF0) != 0x2260) return false;   // "TI", INA226
  // AVG=4, VBUS 1.1 ms, VSHUNT 1.1 ms, continuous shunt + bus: 8.8 ms per reading
  return inaWrite(0x00, 0x4000 | (1 << 9) | (4 << 6) | (4 << 3) | 7);
}

static void pwrResetInterval() {
  pwrVSum = 0;
  pwrISum = 0;
  pwrN = 0;
  pwrOkAll = pwrUp;
}

static void servicePower(uint32_t now) {
  if (!pwrUp) {
    if ((int32_t)(now - pwrRetry) >= 0) {
      pwrRetry = now + PWR_RETRY_MS;
      pwrUp = inaInit();
      Serial.println(pwrUp ? F("I:INA226 ok") : F("I:INA226 not found"));
    }
    return;
  }
  if ((int32_t)(now - pwrNext) < 0) return;
  pwrNext = now + PWR_SAMPLE_MS;
  uint16_t rawSh, rawBus;
  if (!inaRead(0x01, &rawSh) || !inaRead(0x02, &rawBus)) {
    // A SoftwareSerial byte arriving holds interrupts off for ~1 ms, which can
    // time out one I2C read. Only a run of failures means the INA226 is gone.
    if (++pwrFails >= PWR_FAIL_LIMIT) {
      pwrFails = 0;
      pwrUp = false;
      pwrOkAll = false;
      pwrRetry = now + PWR_RETRY_MS;
    }
    return;
  }
  pwrFails = 0;
  uint16_t vMv = (uint16_t)(((uint32_t)rawBus * 125UL) / 100UL);     // 1.25 mV LSB
  int32_t iMa = ((int32_t)(int16_t)rawSh * 2500L) / SHUNT_UOHM;       // 2.5 uV LSB
  if (pwrN == 0) {
    pwrVMin = pwrVMax = vMv;
    pwrIMin = pwrIMax = iMa;
  } else {
    if (vMv < pwrVMin) pwrVMin = vMv;
    if (vMv > pwrVMax) pwrVMax = vMv;
    if (iMa < pwrIMin) pwrIMin = iMa;
    if (iMa > pwrIMax) pwrIMax = iMa;
  }
  pwrVSum += vMv;
  pwrISum += iMa;
  pwrN++;
}

// Min / max / average since the last call, then start a new interval.
// (PwrStats lives in tlm_proto.h: the Arduino IDE puts a prototype for every
// function above the sketch's own code, so a return type defined here fails.)
static PwrStats pwrTake() {
  PwrStats p;
  bool ok = pwrOkAll && pwrN > 0;
  p.vAvgMv = ok ? (uint16_t)(pwrVSum / pwrN) : 0;
  p.vMinMv = ok ? pwrVMin : 0;
  p.vMaxMv = ok ? pwrVMax : 0;
  p.iAvgMa = ok ? pwrISum / (int32_t)pwrN : 0;
  p.iMinMa = ok ? pwrIMin : 0;
  p.iMaxMa = ok ? pwrIMax : 0;
  p.ok = ok ? 1 : 0;
  pwrResetInterval();
  return p;
}

static void pwrSetup() {
  Wire.begin();
  Wire.setClock(100000);
  Wire.setWireTimeout(3000, true);   // never hang on a bad I2C bus
  pwrUp = inaInit();
  Serial.println(pwrUp ? F("I:INA226 ok") : F("I:INA226 not found"));
  pwrRetry = millis() + PWR_RETRY_MS;
  pwrResetInterval();
}
#endif

#if REMTLM_ROLE != ROLE_TOWER
// ===========================================================================
// LoRa line receiver (PSU and BASE). Returns a complete, checksum-valid line
// (without CR/LF) or nullptr. Counts bad packets in rxBad.
// ===========================================================================
static char rxLine[TLM_RK_LINE + 8];
static uint8_t rxLen = 0;
static uint16_t rxBad = 0;

static const char *loraReadLine() {
  while (loraSerial.available() > 0) {
    char c = (char)loraSerial.read();
    if (c == '\r') continue;
    if (c == '$') {                // start of packet: resync
      rxLen = 0;
      rxLine[rxLen++] = c;
      continue;
    }
    if (rxLen == 0) continue;      // noise between packets
    if (c == '\n') {
      rxLine[rxLen] = 0;
      rxLen = 0;
      if (tlmValid(rxLine)) return rxLine;
      rxBad++;
      return nullptr;
    }
    if (rxLen < sizeof(rxLine) - 1) {
      rxLine[rxLen++] = c;
    } else {
      rxLen = 0;                   // overlong: drop and wait for the next '$'
    }
  }
  return nullptr;
}
#endif

#if REMTLM_ROLE == ROLE_TOWER
// ===========================================================================
// TOWER
// ===========================================================================
#if XV_SERIAL_ENABLE
SoftwareSerial xvSerial(PIN_XV_RX, PIN_XV_TX);
#endif

static uint16_t seq = 0;
static uint16_t paPk = 0, xvPk = 0;
static uint32_t paSum = 0;
static uint16_t nSamples = 0;
static bool lockAll = true;
static bool lastLock = true;
static uint32_t nextSample = 0, nextReport = 0;


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

#if PWR_ENABLE
static void sendPower(uint16_t seqForPacket) {
  char buf[TLM_MAX_LINE];
  PwrStats p = pwrTake();
  PwrData d;
  d.seq = seqForPacket;
  d.vAvgMv = p.vAvgMv;
  d.vMinMv = p.vMinMv;
  d.vMaxMv = p.vMaxMv;
  d.iAvgMa = p.iAvgMa;
  d.iMinMa = p.iMinMa;
  d.iMaxMa = p.iMaxMa;
  d.ok = p.ok;
  d.call = CALLSIGN;
  int n = tlmFormatPower(buf, sizeof(buf), &d);
  if (n > 0) loraSend(buf, n);
}
#endif

static void sendReport() {
#if PWR_ENABLE
  sendPower(seq);          // same seq as the $RT that follows
#endif
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
  tempSetup();
#if PWR_ENABLE
  pwrSetup();
#endif
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
#if PWR_ENABLE && XV_SERIAL_ENABLE
  if (!xvWaiting) servicePower(now);   // no I2C while a transverter reply may be arriving
#elif PWR_ENABLE
  servicePower(now);
#endif
#if XV_SERIAL_ENABLE
  serviceXv(now);
#endif
  if ((int32_t)(now - nextReport) >= 0) {
    bool active = paPk > ACTIVE_MV;
    sendReport();
    nextReport = now + (active ? REPORT_ACTIVE_MS : REPORT_IDLE_MS);
  }
}

#elif REMTLM_ROLE == ROLE_PSU
// ===========================================================================
// PSU (supply box at the tower base)
// ===========================================================================
static uint16_t seq = 0;
static bool towerHeard = false;
static bool slotPending = false;
static uint32_t towerAt = 0, slotAt = 0, lastSend = 0;

static void sendSupply(uint32_t now) {
  char buf[TLM_MAX_LINE];
  PwrStats p = pwrTake();
  SupData d;
  d.seq = seq++;
  d.vAvgMv = p.vAvgMv;
  d.vMinMv = p.vMinMv;
  d.vMaxMv = p.vMaxMv;
  d.iAvgMa = p.iAvgMa;
  d.iMinMa = p.iMinMa;
  d.iMaxMa = p.iMaxMa;
  d.ok = p.ok;
  d.tC10 = tempC10[0];
  d.uptimeS = now / 1000UL;
  d.call = CALLSIGN;
  int n = tlmFormatSupply(buf, sizeof(buf), &d);
  if (n > 0) loraSend(buf, n);
  lastSend = now;
}

void setup() {
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  printVersion();
  e220.begin();
  configureLora();
  tempSetup();
  pwrSetup();
  lastSend = millis();
}

void loop() {
  uint32_t now = millis();
  // AUX goes low a few ms before the E220 passes a received packet to the Nano,
  // and stays low until it's done: no I2C while those bytes arrive.
  if (digitalRead(PIN_E220_AUX) == HIGH) servicePower(now);

  const char *ln = loraReadLine();
  if (ln && strncmp(ln, "$RT,", 4) == 0) {      // tower readings just ended: our slot follows
    if (!towerHeard) Serial.println(F("I:tower heard, sending in its gaps"));
    towerHeard = true;
    towerAt = now;
    slotPending = true;
    slotAt = now + PSU_SLOT_DELAY_MS;
  }
  if (towerHeard && now - towerAt >= PSU_TOWER_LOST_MS) {
    towerHeard = false;
    slotPending = false;
    Serial.println(F("I:tower not heard, sending on own timer"));
  }

  bool sent = false;
  if (slotPending && (int32_t)(now - slotAt) >= 0) {
    slotPending = false;
    if (now - lastSend >= PSU_MIN_GAP_MS) {
      sendSupply(now);
      sent = true;
    }
  } else if (!towerHeard && now - lastSend >= PSU_REPORT_MS) {
    sendSupply(now);
    sent = true;
  }
  // The DS18B20 bus briefly blocks interrupts, which can garble a byte arriving
  // on the LoRa SoftwareSerial. Touch it only right after our own packet, when
  // the tower's next one is still >= 400 ms away (or the tower isn't there).
  if (sent || !towerHeard) serviceTemp(now);
}

#else
// ===========================================================================
// BASE
// ===========================================================================
void setup() {
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  printVersion();
  e220.begin();
  configureLora();
}

void loop() {
  static uint16_t badSeen = 0;
  const char *ln = loraReadLine();
  if (ln) {
    Serial.println(ln);
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  }
  if (rxBad != badSeen) {
    badSeen = rxBad;
    Serial.print(F("E:bad packet #"));
    Serial.println(rxBad);
  }
}
#endif
