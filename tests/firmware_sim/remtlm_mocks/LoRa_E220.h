// Just enough of xreef's EByte LoRa E220 library for remtlm.ino to compile and boot.
#pragma once
#include "Arduino.h"
#include "SoftwareSerial.h"

enum { E220_SUCCESS = 1 };
enum { UART_BPS_9600 = 3, AIR_DATA_RATE_100_96 = 4, MODE_00_8N1 = 0, SPS_200_00 = 0,
       RSSI_AMBIENT_NOISE_DISABLED = 0, POWER_22 = 0, POWER_17 = 1, POWER_13 = 2, POWER_10 = 3,
       RSSI_DISABLED = 0, FT_TRANSPARENT_TRANSMISSION = 0, LBT_DISABLED = 0, WOR_2000_011 = 3 };
enum { WRITE_CFG_PWR_DWN_SAVE = 0xC0 };
enum { MODE_0_NORMAL = 0 };

struct Configuration {
  uint8_t ADDH = 0, ADDL = 0, CHAN = 18;
  struct { uint8_t uartBaudRate = 3, airDataRate = 2, uartParity = 0; } SPED;
  struct { uint8_t subPacketSetting = 0, RSSIAmbientNoise = 0, transmissionPower = 0; } OPTION;
  struct { uint8_t enableRSSI = 0, fixedTransmission = 0, enableLBT = 0, WORPeriod = 3; } TRANSMISSION_MODE;
  struct { uint8_t CRYPT_H = 0, CRYPT_L = 0; } CRYPT;
};

struct ResponseStatus {
  int code = E220_SUCCESS;
  const char *getResponseDescription() const { return "ok"; }
};

struct ResponseStructContainer {
  void *data = nullptr;
  ResponseStatus status;
  void close() {}
};

class LoRa_E220 {
 public:
  Configuration cfg;
  int writes = 0;
  LoRa_E220(SoftwareSerial *, int, int, int) {}
  bool begin() { return true; }
  ResponseStructContainer getConfiguration() {
    ResponseStructContainer c;
    c.data = &cfg;
    return c;
  }
  ResponseStatus setConfiguration(Configuration c, int) {
    cfg = c;
    writes++;
    return ResponseStatus();
  }
  ResponseStatus setMode(int) { return ResponseStatus(); }
};
