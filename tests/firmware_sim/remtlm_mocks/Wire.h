// Wire mock with a fake INA226 behind it. The test sets the shunt and bus registers.
#pragma once
#include "Arduino.h"

struct InaSim {
  bool present = true;
  uint16_t shunt = 0;      // register 0x01, 2.5 uV LSB (two's complement)
  uint16_t bus = 0;        // register 0x02, 1.25 mV LSB
  uint16_t config = 0;
};
extern InaSim ina;

class TwoWire {
  uint8_t reg_ = 0;
  std::vector<uint8_t> tx_;
  std::deque<uint8_t> rx_;

 public:
  void begin() {}
  void setClock(long) {}
  void setWireTimeout(long, bool) {}
  void beginTransmission(uint8_t) { tx_.clear(); }
  size_t write(uint8_t b) { tx_.push_back(b); return 1; }
  uint8_t endTransmission() {
    if (!ina.present) return 2;
    if (!tx_.empty()) reg_ = tx_[0];
    if (tx_.size() == 3 && reg_ == 0x00) ina.config = (uint16_t)(tx_[1] << 8 | tx_[2]);
    return 0;
  }
  uint8_t requestFrom(uint8_t, uint8_t n) {
    if (!ina.present) return 0;
    uint16_t v = reg_ == 0xFE ? 0x5449 : reg_ == 0xFF ? 0x2260 : reg_ == 0x01 ? ina.shunt
               : reg_ == 0x02 ? ina.bus : ina.config;
    rx_.clear();
    rx_.push_back((uint8_t)(v >> 8));
    rx_.push_back((uint8_t)(v & 0xFF));
    return n;
  }
  int read() {
    if (rx_.empty()) return -1;
    int b = rx_.front();
    rx_.pop_front();
    return b;
  }
};
extern TwoWire Wire;
