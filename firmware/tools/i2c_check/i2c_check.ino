// i2c_check: bench diagnostic for the remtlm INA226.
//
// Flash this on the Nano temporarily (any role), open the Serial Monitor at
// 115200, and read the report. It repeats every 5 s. Reflash remtlm afterwards.
//
// It lists every I2C address that acknowledges, then for each one reads the
// registers remtlm checks (0xFE manufacturer ID, 0xFF die ID) plus the
// configuration (0x00, 0x4127 at power-up) and bus voltage (0x02, 1.25 mV/bit).
//   remtlm accepts:  address 0x40, 0xFE = 0x5449, 0xFF = 0x226x
// Nano pins: SDA = A4, SCL = A5.

#include <Wire.h>

static bool readReg(uint8_t addr, uint8_t reg, uint16_t *out) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)2) != 2) return false;
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  *out = ((uint16_t)hi << 8) | lo;
  return true;
}

static void hex4(uint16_t v) {
  if (v < 0x1000) Serial.print('0');
  if (v < 0x100) Serial.print('0');
  if (v < 0x10) Serial.print('0');
  Serial.print(v, HEX);
}

void setup() {
  Serial.begin(115200);
  pinMode(A4, INPUT);   // no internal pull-ups: show what the bus does on its own
  pinMode(A5, INPUT);
  delay(300);
  Serial.println(F("i2c_check: INA226 diagnostic for remtlm"));
}

void loop() {
  // Idle bus: both lines should read HIGH (pulled up by the module's resistors).
  Wire.end();
  pinMode(A4, INPUT);
  pinMode(A5, INPUT);
  delay(5);
  Serial.print(F("idle lines: SDA(A4)="));
  Serial.print(digitalRead(A4) ? F("HIGH") : F("LOW"));
  Serial.print(F("  SCL(A5)="));
  Serial.println(digitalRead(A5) ? F("HIGH") : F("LOW"));

  Wire.begin();
  Wire.setClock(100000);
  Wire.setWireTimeout(3000, true);

  uint8_t found = 0;
  for (uint8_t a = 0x08; a <= 0x77; a++) {
    Wire.beginTransmission(a);
    uint8_t err = Wire.endTransmission();
    if (err == 0) {
      found++;
      Serial.print(F("found 0x"));
      Serial.print(a, HEX);
      uint16_t mfr, die, cfg, bus;
      if (readReg(a, 0xFE, &mfr) && readReg(a, 0xFF, &die) && readReg(a, 0x00, &cfg) && readReg(a, 0x02, &bus)) {
        Serial.print(F("  mfr(0xFE)=0x")); hex4(mfr);
        Serial.print(F("  die(0xFF)=0x")); hex4(die);
        Serial.print(F("  config(0x00)=0x")); hex4(cfg);
        Serial.print(F("  bus="));
        Serial.print(bus * 1.25 / 1000.0, 3);
        Serial.print(F(" V"));
        bool ok = (a == 0x40) && mfr == 0x5449 && (die & 0xFFF0) == 0x2260;
        Serial.println(ok ? F("  -> remtlm would accept this") : F("  -> remtlm would NOT accept this"));
      } else {
        Serial.println(F("  (acknowledges, but register reads failed)"));
      }
    } else if (err == 5) {
      Serial.println(F("bus timeout: a line is stuck (check SDA/SCL wiring and GND)"));
      break;
    }
  }
  if (!found) Serial.println(F("no I2C device answered (check SDA/SCL swap, GND, module power)"));
  Serial.println(F("---"));
  delay(5000);
}
