// Wire mock: an I2C bus with a fake INA226 (0x40 unless the test moves it), ADXL355 (0x1D) and BME280 (0x76)
// on it. Each device answers only at its own address; the test sets their readings.
#pragma once
#include "Arduino.h"

struct InaSim {
  bool present = true;
  uint8_t addr = 0x40;     // A0/A1 straps: 0x40-0x4F
  uint16_t shunt = 0;      // register 0x01, 2.5 uV LSB (two's complement)
  uint16_t bus = 0;        // register 0x02, 1.25 mV LSB
  uint16_t config = 0;
};
extern InaSim ina;

// ADXL355: byte registers, auto-increment. Data registers are filled from x/y/z/temp.
struct AdxlSim {
  bool present = false;
  uint8_t addr = 0x1D;
  int32_t x = 0, y = 0, z = 256000;   // 20-bit counts
  uint16_t temp = 1885;               // 12-bit
  uint8_t regs[64] = {};
  int reads = 0;                      // data reads (register 0x06 onwards)
  AdxlSim() { regs[0] = 0xAD; regs[1] = 0x1D; regs[2] = 0xED; regs[0x2C] = 0x81; regs[0x2D] = 0x01; }
  void fill() {
    regs[6] = (uint8_t)(temp >> 8) & 0x0F;
    regs[7] = (uint8_t)temp;
    int32_t v[3] = {x, y, z};
    for (int k = 0; k < 3; k++) {
      uint32_t u = (uint32_t)v[k] & 0xFFFFF;
      regs[8 + 3 * k] = (uint8_t)(u >> 12);
      regs[9 + 3 * k] = (uint8_t)(u >> 4);
      regs[10 + 3 * k] = (uint8_t)((u & 0x0F) << 4);
    }
  }
};
extern AdxlSim adxl;

// BME280 (chip 0x60) or BMP280 (0x58): byte registers, auto-increment.
struct BmeSim {
  bool present = false;
  uint8_t addr = 0x76;
  uint8_t chip = 0x60;
  uint8_t regs[256] = {};
  uint8_t ctrlHum = 0, ctrlMeas = 0;
  int forced = 0;                     // forced-mode measurements started
  void set(uint32_t p, uint32_t t, uint16_t h) {
    regs[0xF7] = (uint8_t)(p >> 12); regs[0xF8] = (uint8_t)(p >> 4); regs[0xF9] = (uint8_t)((p & 0x0F) << 4);
    regs[0xFA] = (uint8_t)(t >> 12); regs[0xFB] = (uint8_t)(t >> 4); regs[0xFC] = (uint8_t)((t & 0x0F) << 4);
    regs[0xFD] = (uint8_t)(h >> 8); regs[0xFE] = (uint8_t)h;
  }
};
extern BmeSim bme;

class TwoWire {
  uint8_t addr_ = 0, reg_ = 0;
  std::vector<uint8_t> tx_;
  std::deque<uint8_t> rx_;

 public:
  void begin() {}
  void setClock(long) {}
  void setWireTimeout(long, bool) {}
  void beginTransmission(uint8_t a) { addr_ = a; tx_.clear(); }
  size_t write(uint8_t b) { tx_.push_back(b); return 1; }
  uint8_t endTransmission(uint8_t = 1) {
    if (addr_ == ina.addr) {
      if (!ina.present) return 2;
      if (!tx_.empty()) reg_ = tx_[0];
      if (tx_.size() == 3 && reg_ == 0x00) ina.config = (uint16_t)(tx_[1] << 8 | tx_[2]);
      return 0;
    }
    if (adxl.present && addr_ == adxl.addr) {
      if (!tx_.empty()) reg_ = tx_[0];
      for (size_t i = 1; i < tx_.size(); i++) adxl.regs[(reg_ + i - 1) & 63] = tx_[i];
      return 0;
    }
    if (bme.present && addr_ == bme.addr) {
      if (!tx_.empty()) reg_ = tx_[0];
      for (size_t i = 1; i < tx_.size(); i++) {
        uint8_t r = (uint8_t)(reg_ + i - 1);
        bme.regs[r] = tx_[i];
        if (r == 0xF2) bme.ctrlHum = tx_[i];
        if (r == 0xF4) { bme.ctrlMeas = tx_[i]; if ((tx_[i] & 3) == 1) bme.forced++; }
      }
      return 0;
    }
    return 2;                         // NACK: nobody at that address
  }
  uint8_t requestFrom(uint8_t a, uint8_t n) {
    rx_.clear();
    if (a == ina.addr) {
      if (!ina.present) return 0;
      uint16_t v = reg_ == 0xFE ? 0x5449 : reg_ == 0xFF ? 0x2260 : reg_ == 0x01 ? ina.shunt
                 : reg_ == 0x02 ? ina.bus : ina.config;
      rx_.push_back((uint8_t)(v >> 8));
      rx_.push_back((uint8_t)(v & 0xFF));
      return n;
    }
    if (adxl.present && a == adxl.addr) {
      adxl.fill();
      if (reg_ == 0x06) adxl.reads++;
      for (uint8_t i = 0; i < n; i++) rx_.push_back(adxl.regs[(reg_ + i) & 63]);
      return n;
    }
    if (bme.present && a == bme.addr) {
      bme.regs[0xD0] = bme.chip;
      for (uint8_t i = 0; i < n; i++) rx_.push_back(bme.regs[(uint8_t)(reg_ + i)]);
      return n;
    }
    return 0;
  }
  int read() {
    if (rx_.empty()) return -1;
    int b = rx_.front();
    rx_.pop_front();
    return b;
  }
};
extern TwoWire Wire;
