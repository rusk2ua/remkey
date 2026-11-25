// remtlm packet formats, shared by the tower, psu and base roles (and the host tests).
//
// Readings, every 0.5-2 s:
//   $RT,<seq>,<pa_pk_mv>,<pa_avg_mv>,<xv_pk_mv>,<lock>,<t1_c10>,<t2_c10>,<uptime_s>,<ptt>,<ptt_mv>,<call>*HH
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
//   ptt        MKU CON1 pin 8 (PTT out to the sequencer, active low): 1 = asserted at
//              any point in the interval, 0 = not asserted, 2 = not monitored (0.6.0+;
//              older towers send 9 fields and no ptt/ptt_mv)
//   ptt_mv     voltage on that line at the end of the interval, mV (0 if not monitored)
//   call       station callsign, so every transmission is identified
//
// Optional tower-top supply monitor (PWR_ENABLE 1 on the tower), sent just before
// the $RT with the same seq (same interval):
//   $RP,<seq>,<v_avg_mv>,<v_min_mv>,<v_max_mv>,<i_avg_ma>,<i_min_ma>,<i_max_ma>,<ok>,<call>*HH
//
//   v_*_mv     supply voltage at the tower enclosure (INA226 bus voltage), mV
//   i_*_ma     supply current through the shunt, mA (negative = shunt wired backwards)
//   ok         1 = INA226 answered for the whole interval, 0 = not (values are 0)
//
// Tower-base supply box (PSU node: INA226 + shunt at the supply, one DS18B20), every
// 0.5-2 s, slotted just after each tower $RT it hears:
//   $RS,<seq>,<v_avg_mv>,<v_min_mv>,<v_max_mv>,<i_avg_ma>,<i_min_ma>,<i_max_ma>,<ok>,<t_c10>,<uptime_s>,<call>*HH
//
//   seq        PSU node's own counter 0..65535 (independent of the tower's)
//   v_*_mv     supply output voltage (INA226 bus voltage, load side of the shunt), mV
//   i_*_ma     current into the tower cable through the shunt, mA
//   ok         1 = INA226 answered for the whole interval, 0 = not (V/I values are 0)
//   t_c10      box temperature in 0.1 C (TLM_TEMP_NONE if absent)
//   uptime_s   PSU Nano uptime in seconds
//
// Transverter serial replies (Kuhne "s" status / "v" version), relayed verbatim:
//   $RK,<id>,<cmd>,<part>,<total>,<text>,<call>*HH
//
//   id         capture number 0..255 (all parts of one reply share it)
//   cmd        the command that produced it: s or v
//   part/total 1-based part number and part count
//   text       reply text; line breaks become '|', and '$', '*' and ',' become ' '
//
// Dish elevation (TOWER with TILT_ENABLE, 0.7.0+): raw ADXL355 readings. Sent just
// before each $RT (averaged over the interval), and every LIVE_PERIOD_MS while the
// dish moves (averaged over that 200 ms):
//   $RA,<seq>,<x>,<y>,<z>,<t_raw>,<ok>,<moving>,<call>*HH
//
//   seq        0..255, the tower's own $RA counter
//   x, y, z    acceleration, 20-bit ADXL355 counts at +-2 g (256000 = 1 g, nominal)
//   t_raw      ADXL355 temperature, 12-bit (1885 at 25 C, -9.05 per C, nominal)
//   ok         1 = sensor answering; 0 = not found (all values 0, sent every 30 s)
//   moving     1 = live mode (the dish is moving), 0 = still
//
// Box environment (TOWER with ENV_ENABLE, 0.7.0+): raw BME280 readings every 10 s,
// just before a $RT, and the chip's calibration constants after boot and every 5 min.
// The host does the Bosch compensation.
//   $RB,<seq>,<p_raw>,<t_raw>,<h_raw>,<chip>,<ok>,<call>*HH
//   $RC,<chip>,<cal>,<call>*HH
//
//   p_raw, t_raw  20-bit ADC values; h_raw 16-bit (0 on a BMP280)
//   chip       96 = BME280 (chip id 0x60), 88 = BMP280 (0x58, no humidity)
//   ok         1 = sensor answering; 0 = not found (values 0, sent every 30 s)
//   cal        33 bytes in hex: registers 0x88-0xA1, then 0xE1-0xE7 (zeros on a BMP280)
//
// HH is the XOR of every byte between '$' and '*', two upper-case hex digits.
//
// The base also prints status lines of its own on USB (never sent over the air):
//   V:remtlm <version> base     at boot
//   C:ok ch=77 freq_khz=927125  (or C:written first, or C:ERR ...) LoRa configuration
//   E:bad packet #<n>           a packet that failed its checksum
//   R:tower,<dBm> / R:psu,<dBm> signal strength of the packet just received (0.5.0+)
//   N:<dBm>                     channel noise floor, every 10 s (0.5.0+)
// Plain ASCII, no encryption: legal under Part 15 and Part 97 alike.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define TLM_TEMP_NONE (-32768)
#define TLM_MAX_LINE  96      // worst-case $RC is 83 bytes and $RS 80, with CR/LF
#define TLM_CAL_BYTES 33      // BME280 calibration: 0x88-0xA1 (26) + 0xE1-0xE7 (7)
#define TLM_RK_TEXT   48      // reply text per $RK packet
#define TLM_RK_LINE   (TLM_RK_TEXT + 40)

struct PwrData {
  uint16_t seq;
  uint16_t vAvgMv, vMinMv, vMaxMv;
  int32_t  iAvgMa, iMinMa, iMaxMa;
  uint8_t  ok;
  const char *call;
};

// One interval of INA226 readings (min / avg / max), before it goes into a $RP or $RS.
struct PwrStats {
  uint16_t vAvgMv, vMinMv, vMaxMv;
  int32_t  iAvgMa, iMinMa, iMaxMa;
  uint8_t  ok;
};

struct SupData {
  uint16_t seq;
  uint16_t vAvgMv, vMinMv, vMaxMv;
  int32_t  iAvgMa, iMinMa, iMaxMa;
  uint8_t  ok;
  int16_t  tC10;
  uint32_t uptimeS;
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
  uint8_t  ptt;
  uint16_t pttMv;
  const char *call;
};

struct TiltData {
  uint8_t  seq;
  int32_t  x, y, z;
  uint16_t tRaw;
  uint8_t  ok;
  uint8_t  moving;
  const char *call;
};

struct EnvData {
  uint8_t  seq;
  uint32_t pRaw, tRaw;
  uint16_t hRaw;
  uint8_t  chip;
  uint8_t  ok;
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
  int n = snprintf(buf, len, "$RT,%u,%u,%u,%u,%u,%d,%d,%lu,%u,%u,%s",
                   (unsigned)d->seq, (unsigned)d->paPkMv, (unsigned)d->paAvgMv,
                   (unsigned)d->xvPkMv, (unsigned)d->lock, (int)d->t1C10, (int)d->t2C10,
                   (unsigned long)d->uptimeS, (unsigned)d->ptt, (unsigned)d->pttMv, d->call);
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

// Writes a complete $RS line including "\r\n". Returns its length, or 0.
static inline int tlmFormatSupply(char *buf, size_t len, const SupData *d) {
  int n = snprintf(buf, len, "$RS,%u,%u,%u,%u,%ld,%ld,%ld,%u,%d,%lu,%s",
                   (unsigned)d->seq, (unsigned)d->vAvgMv, (unsigned)d->vMinMv,
                   (unsigned)d->vMaxMv, (long)d->iAvgMa, (long)d->iMinMa, (long)d->iMaxMa,
                   (unsigned)d->ok, (int)d->tC10, (unsigned long)d->uptimeS, d->call);
  if (n <= 0 || (size_t)n >= len) return 0;
  return tlmSeal(buf, len, n);
}

// Writes a complete $RA line including "\r\n". Returns its length, or 0.
static inline int tlmFormatTilt(char *buf, size_t len, const TiltData *d) {
  int n = snprintf(buf, len, "$RA,%u,%ld,%ld,%ld,%u,%u,%u,%s", (unsigned)d->seq, (long)d->x,
                   (long)d->y, (long)d->z, (unsigned)d->tRaw, (unsigned)d->ok,
                   (unsigned)d->moving, d->call);
  if (n <= 0 || (size_t)n >= len) return 0;
  return tlmSeal(buf, len, n);
}

// Writes a complete $RB line including "\r\n". Returns its length, or 0.
static inline int tlmFormatEnv(char *buf, size_t len, const EnvData *d) {
  int n = snprintf(buf, len, "$RB,%u,%lu,%lu,%u,%u,%u,%s", (unsigned)d->seq,
                   (unsigned long)d->pRaw, (unsigned long)d->tRaw, (unsigned)d->hRaw,
                   (unsigned)d->chip, (unsigned)d->ok, d->call);
  if (n <= 0 || (size_t)n >= len) return 0;
  return tlmSeal(buf, len, n);
}

// Writes a complete $RC line (BME280 calibration, TLM_CAL_BYTES in hex). Returns its length, or 0.
static inline int tlmFormatEnvCal(char *buf, size_t len, uint8_t chip, const uint8_t *cal,
                                  const char *call) {
  static const char hex[] = "0123456789ABCDEF";
  int n = snprintf(buf, len, "$RC,%u,", (unsigned)chip);
  if (n <= 0 || (size_t)n + 2 * TLM_CAL_BYTES + strlen(call) + 8 > len) return 0;
  for (uint8_t i = 0; i < TLM_CAL_BYTES; i++) {
    buf[n++] = hex[cal[i] >> 4];
    buf[n++] = hex[cal[i] & 0x0F];
  }
  n += snprintf(buf + n, len - (size_t)n, ",%s", call);
  return tlmSeal(buf, len, n);
}

// Writes one $RK line for text[0..textLen). Text must already be sanitized.
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

// True if line (without CR/LF) is a $RT, $RP, $RS, $RK, $RA, $RB or $RC packet with a
// correct checksum.
static inline bool tlmValid(const char *line) {
  size_t n = strlen(line);
  if (n < 8 || line[0] != '$' || line[1] != 'R' || line[3] != ',') return false;
  if (!strchr("TPSKABC", line[2])) return false;
  if (line[n - 3] != '*') return false;
  int hi = tlmHexNibble(line[n - 2]), lo = tlmHexNibble(line[n - 1]);
  if (hi < 0 || lo < 0) return false;
  return tlmXor(line + 1, n - 4) == (uint8_t)(hi * 16 + lo);
}
