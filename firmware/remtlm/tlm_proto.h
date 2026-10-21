// remtlm packet format, shared by the tower and base roles (and the host tests).
//
//   $RT,<seq>,<pa_pk_mv>,<pa_avg_mv>,<xv_pk_mv>,<lock>,<temp_c10>,<uptime_s>,<call>*HH
//
//   seq        0..65535, wraps; lets the host count lost packets
//   pa_pk_mv   PA power-sense peak since the previous packet, mV at the PA's output pin
//   pa_avg_mv  PA power-sense average since the previous packet, mV
//   xv_pk_mv   transverter power-sense peak, mV
//   lock       1 = LO locked for the whole interval, 0 = unlocked at any point
//   temp_c10   heatsink temperature in 0.1 C, TLM_TEMP_NONE if no sensor reading
//   uptime_s   tower Nano uptime in seconds (shows resets / brown-outs)
//   call       station callsign, so every transmission is identified
//   HH         XOR of every byte between '$' and '*', two upper-case hex digits
//
// Plain ASCII, no encryption: legal under Part 15 and Part 97 alike.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define TLM_TEMP_NONE (-32768)
#define TLM_MAX_LINE  80

struct TlmData {
  uint16_t seq;
  uint16_t paPkMv;
  uint16_t paAvgMv;
  uint16_t xvPkMv;
  uint8_t  lock;
  int16_t  tempC10;
  uint32_t uptimeS;
  const char *call;
};

static inline uint8_t tlmXor(const char *s, size_t n) {
  uint8_t x = 0;
  for (size_t i = 0; i < n; i++) x ^= (uint8_t)s[i];
  return x;
}

// Writes a complete line including "\r\n". Returns its length, or 0 if it didn't fit.
static inline int tlmFormat(char *buf, size_t len, const TlmData *d) {
  int n = snprintf(buf, len, "$RT,%u,%u,%u,%u,%u,%d,%lu,%s",
                   (unsigned)d->seq, (unsigned)d->paPkMv, (unsigned)d->paAvgMv,
                   (unsigned)d->xvPkMv, (unsigned)d->lock, (int)d->tempC10,
                   (unsigned long)d->uptimeS, d->call);
  if (n <= 0 || (size_t)n + 6 > len) return 0;
  uint8_t x = tlmXor(buf + 1, (size_t)n - 1);
  int m = snprintf(buf + n, len - (size_t)n, "*%02X\r\n", x);
  return n + m;
}

static inline int tlmHexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

// True if line (without CR/LF) is "$RT,...*HH" with a correct checksum.
static inline bool tlmValid(const char *line) {
  size_t n = strlen(line);
  if (n < 8 || line[0] != '$' || strncmp(line, "$RT,", 4) != 0) return false;
  if (line[n - 3] != '*') return false;
  int hi = tlmHexNibble(line[n - 2]), lo = tlmHexNibble(line[n - 1]);
  if (hi < 0 || lo < 0) return false;
  return tlmXor(line + 1, n - 4) == (uint8_t)(hi * 16 + lo);
}
