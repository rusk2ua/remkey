// remtlm - tower-top telemetry for remkey over an Ebyte E220-900T22D LoRa link.
//
// TOWER role (Nano at the tower top, powered from the transverter's 13.8 V via a
// 5 V buck converter):
//   - samples the PA and transverter power-sense outputs every 5 ms, keeping the
//     peak and average since the last packet (so a dit's peak isn't missed)
//   - watches the LO-lock output (any unlock during an interval is reported)
//   - reads a DS18B20 probe on the PA heatsink
//   - transmits one ASCII packet every 2 s, or every 0.5 s while the PA shows output,
//     and immediately when LO lock changes
//
// BASE role (Nano in the radio room, USB to the shack PC):
//   - receives packets and forwards each valid one to USB serial, unchanged
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

#define FW_VERSION "0.1.0"

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

static uint16_t seq = 0;
static uint16_t paPk = 0, xvPk = 0;
static uint32_t paSum = 0;
static uint16_t nSamples = 0;
static bool lockAll = true;
static bool lastLock = true;
static int16_t tempC10 = TLM_TEMP_NONE;
static bool tempPending = false;
static uint32_t nextSample = 0, nextReport = 0, tempRequested = 0, nextTemp = 0;

static uint16_t readMv(uint8_t pin) {
  uint32_t counts = analogRead(pin);
  return (uint16_t)((counts * VREF_MV * DIVIDER_X1000) / (1023UL * 1000UL));
}

static bool loLocked() {
  bool hi = digitalRead(PIN_LO_LOCK) == HIGH;
  return LOCK_ACTIVE_HIGH ? hi : !hi;
}

static void sendReport() {
  char buf[TLM_MAX_LINE];
  TlmData d;
  d.seq = seq++;
  d.paPkMv = paPk;
  d.paAvgMv = nSamples ? (uint16_t)(paSum / nSamples) : 0;
  d.xvPkMv = xvPk;
  d.lock = lockAll ? 1 : 0;
  d.tempC10 = tempC10;
  d.uptimeS = millis() / 1000UL;
  d.call = CALLSIGN;
  int n = tlmFormat(buf, sizeof(buf), &d);
  if (n > 0 && digitalRead(PIN_E220_AUX) == HIGH) {   // module idle
    loraSerial.write((const uint8_t *)buf, n);
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
  }
  Serial.print(buf);   // also on USB for bench work
  paPk = xvPk = 0;
  paSum = 0;
  nSamples = 0;
  lockAll = loLocked();
}

static void serviceTemp(uint32_t now) {
  if (!tempPending && (int32_t)(now - nextTemp) >= 0) {
    probes.requestTemperatures();          // non-blocking (see setup)
    tempRequested = now;
    tempPending = true;
    nextTemp = now + TEMP_PERIOD_MS;
  }
  if (tempPending && now - tempRequested >= 800) {   // 12-bit conversion is 750 ms
    float c = probes.getTempCByIndex(0);
    tempC10 = (c <= DEVICE_DISCONNECTED_C + 1) ? TLM_TEMP_NONE : (int16_t)(c * 10.0f + (c >= 0 ? 0.5f : -0.5f));
    tempPending = false;
  }
}

void setup() {
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_LO_LOCK, INPUT_PULLUP);
  Serial.begin(115200);
  printVersion();
  e220.begin();
  configureLora();
  probes.begin();
  probes.setResolution(12);
  probes.setWaitForConversion(false);
  lastLock = lockAll = loLocked();
  nextReport = millis() + 500;
}

void loop() {
  uint32_t now = millis();
  if ((int32_t)(now - nextSample) >= 0) {
    nextSample = now + SAMPLE_MS;
    uint16_t pa = readMv(PIN_PA_SENSE);
    uint16_t xv = readMv(PIN_XV_SENSE);
    if (pa > paPk) paPk = pa;
    if (xv > xvPk) xvPk = xv;
    paSum += pa;
    nSamples++;
    bool lk = loLocked();
    if (!lk) lockAll = false;
    if (lk != lastLock) {          // report lock changes right away
      lastLock = lk;
      nextReport = now;
    }
  }
  serviceTemp(now);
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
static char line[TLM_MAX_LINE + 1];
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
    if (c == '\n' || lineLen >= TLM_MAX_LINE) {
      line[lineLen] = 0;
      if (lineLen > 0) {
        if (tlmValid(line)) {
          Serial.println(line);
          digitalWrite(PIN_LED, !digitalRead(PIN_LED));
        } else {
          badCount++;
          Serial.print(F("E:bad packet #"));
          Serial.println(badCount);
        }
      }
      lineLen = 0;
      if (c != '\n') line[lineLen++] = c;
    } else if (c == '$') {
      lineLen = 0;                 // resync on start-of-packet
      line[lineLen++] = c;
    } else if (lineLen > 0) {
      line[lineLen++] = c;
    }
  }
}
#endif
