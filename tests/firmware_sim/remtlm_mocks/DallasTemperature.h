// DallasTemperature mock: fixed probe temperatures set by the test.
#pragma once
#include "OneWire.h"

#define DEVICE_DISCONNECTED_C -127

struct DallasSim {
  int count = 1;
  float temps[2] = {21.37f, 30.0f};
  int requests = 0;
};
extern DallasSim dallas;

class DallasTemperature {
 public:
  explicit DallasTemperature(OneWire *) {}
  void begin() {}
  int getDeviceCount() { return dallas.count; }
  void setResolution(int) {}
  void setWaitForConversion(bool) {}
  void requestTemperatures() { dallas.requests++; }
  float getTempCByIndex(int i) { return i < dallas.count ? dallas.temps[i] : DEVICE_DISCONNECTED_C; }
};
