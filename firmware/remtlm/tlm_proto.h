// remtlm packet formats, shared by the tower and base roles (and the host tests).
//
// Readings, every 0.5-2 s:
//   $RT,<seq>,<pa_pk_mv>,<pa_avg_mv>,<xv_pk_mv>,<lock>,<t1_c10>,<t2_c10>,<uptime_s>,<call>*HH
//
//   seq        0..65535, wraps; lets the host count lost packets
//   pa_pk_mv   PA power-sense peak since the previous packet, mV at the PA's output pin
//   pa_avg_mv  PA power-sense average since the previous packet, mV
//   xv_pk_mv   transverter MON (pin 9) peak, mV
//   lock       1 = reference locked for the whole interval, 0 = unlocked at any point,
//              2 = lock monitoring disabled
//   t1_c10     DS18B20 #1 in 0.1 C (TLM_TEMP_NONE if absent)
//   t2_c10     DS18B20 #2 in 0.1 C (TLM_TEMP_NONE if absent)
//   uptime_s   tower Nano uptime in seconds (shows resets / brown-outs)
//   call       station callsign, so every transmission is identified
//
// Supply monitor, sent just before the $RT with the same seq (same interval):
//   $RP,<seq>,<v_avg_mv>,<v_min_mv>,<v_max_mv>,<i_avg_ma>,<i_min_ma>,<i_max_ma>,<ok>,<call>*HH
//
//   v_*_mv     supply voltage at the tower enclosure (INA226 bus voltage), mV
//   i_*_ma     supply current through the shunt, mA (negative = shunt wired backwards)
//   ok         1 = INA226 answered for the whole interval, 0 = not (values are 0)
//
// Transverter serial replies (Kuhne "s" status / "v" version), relayed verbatim:
//   $RK,<id>,<cmd>,<part>,<total>,<text>,<call>*HH
//
//   id         capture number 0..255 (all parts of one reply share it)
//   cmd        the command that produced it: s or v
//   part/total 1-based part number and part count
//   text       reply text; line breaks become '|', and '$', '*' and ',' become ' '
//
// HH is the XOR of every byte between '$' and '*', two upper-case hex digits.
// Plain ASCII, no encryption: legal under Part 15 and Part 97 alike.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define TLM_TEMP_NONE (-32768)
#define TLM_MAX_LINE  80
#define TLM_RK_TEXT   48      // reply text per $RK packet
#define TLM_RK_LINE   (TLM_RK_TEXT + 40)

struct PwrData {
  uint16_t seq;
  uint16_t vAvgMv, vMinMv, vMaxMv;
  int32_t  iAvgMa, iMinMa, iMaxMa;
  uint8_t  ok;
  const char *call;
};

struct TlmData {
  uint16_t seq;
  uint16_t paPkMv;
  uint16_t paAvgMv;
  uint16_t xvPkMv;
  uint8_t  lock;
  int16_t  t1C10;
  int16_t  t2C10;
  uint32_t uptimeS;
  const char *call;
};

static inline uint8_t tlmXor(const char *s, size_t n) {
  uint8_t x = 0;
  for (size_t i = 0; i < n; i++) x ^= (uint8_t)s[i];
  return x;
}

// Append "*HH\r\n" to a body of length n already in buf. Returns total length or 0.
static inline int tlmSeal(char *buf, size_t len, int n) {
  if (n <= 0 || (size_t)n + 6 > len) return 0;
  uint8_t x = tlmXor(buf + 1, (size_t)n - 1);
  int m = snprintf(buf + n, len - (size_t)n, "*%02X\r\n", x);
  return n + m;
}

// Writes a complete $RT line including "\r\n". Returns its length, or 0 if it didn't fit.
static inline int tlmFormat(char *buf, size_t len, const TlmData *d) {
  int n = snprintf(buf, len, "$RT,%u,%u,%u,%u,%u,%d,%d,%lu,%s",
                   (unsigned)d->seq, (unsigned)d->paPkMv, (unsigned)d->paAvgMv,
                   (unsigned)d->xvPkMv, (unsigned)d->lock, (int)d->t1C10, (int)d->t2C10,
                   (unsigned long)d->uptimeS, d->call);
  if (n <= 0 || (size_t)n >= len) return 0;
  return tlmSeal(buf, len, n);
}

// Writes a complete $RP line including "\r\n". Returns its length, or 0.
static inline int tlmFormatPower(char *buf, size_t len, const PwrData *d) {
  int n = snprintf(buf, len, "$RP,%u,%u,%u,%u,%ld,%ld,%ld,%u,%s",
                   (unsigned)d->seq, (unsigned)d->vAvgMv, (unsigned)d->vMinMv,
                   (unsigned)d->vMaxMv, (long)d->iAvgMa, (long)d->iMinMa, (long)d->iMaxMa,
                   (unsigned)d->ok, d->call);
  if (n <= 0 || (size_t)n >= len) return 0;
  return tlmSeal(buf, len, n);
}

// Writes one $RK line for text[0..textLen). Text must already be sanitised.
static inline int tlmFormatReply(char *buf, size_t len, uint8_t id, char cmd, uint8_t part,
                                 uint8_t total, const char *text, size_t textLen,
                                 const char *call) {
  int n = snprintf(buf, len, "$RK,%u,%c,%u,%u,", (unsigned)id, cmd, (unsigned)part,
                   (unsigned)total);
  if (n <= 0 || (size_t)n + textLen + strlen(call) + 8 > len) return 0;
  memcpy(buf + n, text, textLen);
  n += (int)textLen;
  n += snprintf(buf + n, len - (size_t)n, ",%s", call);
  return tlmSeal(buf, len, n);
}

// Map one raw byte from the transverter into the text alphabet. 0 = drop.
static inline char tlmReplyChar(char c) {
  if (c == '\r' || c == '\n') return '|';
  if (c == '$' || c == '*' || c == ',') return ' ';
  if (c < 32 || c > 126) return 0;
  return c;
}

static inline int tlmHexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

// True if line (without CR/LF) is "$RT,...*HH" or "$RK,...*HH" with a correct checksum.
static inline bool tlmValid(const char *line) {
  size_t n = strlen(line);
  if (n < 8 || line[0] != '$') return false;
  if (strncmp(line, "$RT,", 4) != 0 && strncmp(line, "$RK,", 4) != 0 &&
      strncmp(line, "$RP,", 4) != 0) return false;
  if (line[n - 3] != '*') return false;
  int hi = tlmHexNibble(line[n - 2]), lo = tlmHexNibble(line[n - 1]);
  if (hi < 0 || lo < 0) return false;
  return tlmXor(line + 1, n - 4) == (uint8_t)(hi * 16 + lo);
}
