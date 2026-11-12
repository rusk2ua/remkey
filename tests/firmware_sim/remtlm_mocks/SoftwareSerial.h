// SoftwareSerial mock for the remtlm simulation: separate in/out buffers per port.
#pragma once
#include "Arduino.h"

class SoftwareSerial {
 public:
  std::string out;
  std::deque<char> in;
  SoftwareSerial(int, int) {}
  void begin(long) {}
  void listen() {}
  int available() { return (int)in.size(); }
  int read() {
    if (in.empty()) return -1;
    char c = in.front();
    in.pop_front();
    return (unsigned char)c;
  }
  size_t write(const uint8_t *b, size_t n) { out.append((const char *)b, n); return n; }
  size_t write(char c) { out += c; return 1; }
  void print(const char *s) { out += s; }
  void feed(const std::string &s) { for (char c : s) in.push_back(c); }
};
