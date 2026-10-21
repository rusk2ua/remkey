// Minimal Arduino API mock so remkey.ino can be compiled and exercised on a PC.
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define A0 14
#define PROGMEM
#define F(s) (s)
#define memcpy_P memcpy

struct SimState {
  uint32_t now = 0;
  int pinIn[32];        // what digitalRead returns
  int pinOut[32];       // last digitalWrite
  bool toneOn = false;
  // key-out transitions: (time, level)
  std::vector<std::pair<uint32_t, int>> keyLog;
  std::vector<std::pair<uint32_t, int>> pttLog;
  SimState() {
    for (int i = 0; i < 32; i++) { pinIn[i] = HIGH; pinOut[i] = LOW; }
  }
};
extern SimState sim;

inline uint32_t millis() { return sim.now; }
inline void pinMode(int, int) {}
inline int digitalRead(int p) { return sim.pinIn[p]; }
void digitalWrite(int p, int v);
inline int analogRead(int) { return 512; }
inline void tone(int, unsigned int) { sim.toneOn = true; }
inline void noTone(int) { sim.toneOn = false; }
inline long map(long x, long a, long b, long c, long d) { return (x - a) * (d - c) / (b - a) + c; }

class MockSerial {
 public:
  std::string out;
  std::deque<char> in;
  void begin(long) {}
  int available() { return (int)in.size(); }
  int read() { if (in.empty()) return -1; char c = in.front(); in.pop_front(); return (unsigned char)c; }
  void print(const char *s) { out += s; }
  void print(char c) { out += c; }
  void print(int v) { out += std::to_string(v); }
  void print(unsigned int v) { out += std::to_string(v); }
  void print(unsigned char v) { out += std::to_string((int)v); }
  void print(long v) { out += std::to_string(v); }
  void print(unsigned long v) { out += std::to_string(v); }
  template <typename T> void println(T v) { print(v); out += "\r\n"; }
  void println() { out += "\r\n"; }
  void feed(const std::string &s) { for (char c : s) in.push_back(c); }
};
extern MockSerial Serial;
