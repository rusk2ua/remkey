// Checks tlm_proto.h and prints sample packets for the Python cross-check
// (host/tests/test_telemetry.py compiles and runs this if g++ is available).
#include "tlm_proto.h"
#include <cstdio>

int main() {
  int fails = 0;
  char buf[TLM_MAX_LINE];
  TlmData d = {65535, 4987, 1234, 0, 1, 452, 318, 86400UL, 1, 210, "K2UA"};
  if (tlmFormat(buf, sizeof(buf), &d) <= 0) { std::printf("FAIL format\n"); return 1; }
  std::printf("%s", buf);
  d = {7, 0, 0, 2500, 0, TLM_TEMP_NONE, TLM_TEMP_NONE, 3, 0, 12650, "K2UA"};
  tlmFormat(buf, sizeof(buf), &d);
  std::printf("%s", buf);
  d = {8, 100, 50, 0, 2, -105, 0, 4, 2, 0, "K2UA"};   // -10.5 C, lock and PTT monitoring off
  tlmFormat(buf, sizeof(buf), &d);
  std::printf("%s", buf);

  {
    TlmData worst = {65535, 65535, 65535, 65535, 2, -32768, -32768, 4294967295UL, 2, 65535, "K2UA"};
    char big[TLM_MAX_LINE];
    int m = tlmFormat(big, sizeof(big), &worst);
    if (m <= 0 || m > 80) { fails++; std::printf("FAIL worst-case $RT length %d\n", m); }
  }

  // supply monitor packet, including a negative current (reversed shunt)
  PwrData pw = {42, 13284, 12851, 13402, 4012, 3900, 6104, 1, "K2UA"};
  if (tlmFormatPower(buf, sizeof(buf), &pw) <= 0) { fails++; std::printf("FAIL power format\n"); }
  std::printf("%s", buf);
  pw = {43, 14100, 14100, 14100, -512, -40960, 40959, 1, "K2UA"};
  tlmFormatPower(buf, sizeof(buf), &pw);
  std::printf("%s", buf);
  {
    char chk[TLM_MAX_LINE];
    memcpy(chk, buf, sizeof(chk));
    chk[strcspn(chk, "\r\n")] = 0;
    if (!tlmValid(chk)) { fails++; std::printf("FAIL power valid\n"); }
  }

  // tower-base supply box packet: normal, then the worst case that must still fit
  SupData sd = {77, 14012, 13890, 14105, 1066, 412, 5980, 1, 214, 3600, "K2UA"};
  if (tlmFormatSupply(buf, sizeof(buf), &sd) <= 0) { fails++; std::printf("FAIL supply format\n"); }
  std::printf("%s", buf);
  sd = {78, 0, 0, 0, 0, 0, 0, 0, TLM_TEMP_NONE, 12, "K2UA"};
  tlmFormatSupply(buf, sizeof(buf), &sd);
  std::printf("%s", buf);
  {
    SupData worst = {65535, 65535, 65535, 65535, -40960, -40960, -40960, 1, -32768, 4294967295UL, "K2UA"};
    char big[TLM_MAX_LINE];
    int m = tlmFormatSupply(big, sizeof(big), &worst);
    if (m <= 0 || m > 80) { fails++; std::printf("FAIL worst-case supply length %d\n", m); }
    big[strcspn(big, "\r\n")] = 0;
    if (!tlmValid(big)) { fails++; std::printf("FAIL supply valid\n"); }
  }

  // dish elevation ($RA): about +1 deg, a negative axis, the worst case that must fit
  TiltData td = {12, 4466, -1200, 255961, 1840, 1, 0, "K2UA"};
  if (tlmFormatTilt(buf, sizeof(buf), &td) <= 0) { fails++; std::printf("FAIL tilt format\n"); }
  std::printf("%s", buf);
  td = {13, 0, 0, 0, 0, 0, 0, "K2UA"};            // sensor not found
  tlmFormatTilt(buf, sizeof(buf), &td);
  std::printf("%s", buf);
  {
    TiltData worst = {255, -524288, -524288, -524288, 4095, 1, 1, "K2UA"};
    char big[TLM_MAX_LINE];
    int m = tlmFormatTilt(big, sizeof(big), &worst);
    if (m <= 0 || m > 56) { fails++; std::printf("FAIL worst-case tilt length %d\n", m); }
    big[strcspn(big, "\r\n")] = 0;
    if (!tlmValid(big)) { fails++; std::printf("FAIL tilt valid\n"); }
  }

  // box environment ($RB, $RC). Pressure/temperature calibration and readings are the
  // worked example in Bosch's BMP280 datasheet (25.08 C, 100653.27 Pa); the humidity
  // constants are typical BME280 values.
  {
    const int16_t pt[12] = {27504, 26435, -1000, (int16_t)36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000};
    uint8_t cal[TLM_CAL_BYTES] = {};
    for (int i = 0; i < 12; i++) { cal[2 * i] = (uint8_t)(pt[i] & 0xFF); cal[2 * i + 1] = (uint8_t)((uint16_t)pt[i] >> 8); }
    cal[25] = 75;                                   // dig_H1 (0xA1)
    int16_t h2 = 362, h4 = 313, h5 = 50;
    cal[26] = (uint8_t)(h2 & 0xFF); cal[27] = (uint8_t)(h2 >> 8);   // 0xE1-0xE2
    cal[28] = 0;                                    // dig_H3
    cal[29] = (uint8_t)(h4 >> 4);                   // 0xE4: H4[11:4]
    cal[30] = (uint8_t)(((h5 & 0x0F) << 4) | (h4 & 0x0F));   // 0xE5
    cal[31] = (uint8_t)(h5 >> 4);                   // 0xE6: H5[11:4]
    cal[32] = 30;                                   // dig_H6
    char big[TLM_MAX_LINE];
    int m = tlmFormatEnvCal(big, sizeof(big), 96, cal, "K2UA");
    if (m <= 0 || m > 83) { fails++; std::printf("FAIL env cal length %d\n", m); }
    std::printf("%s", big);
    big[strcspn(big, "\r\n")] = 0;
    if (!tlmValid(big)) { fails++; std::printf("FAIL env cal valid\n"); }
  }
  EnvData ed = {3, 415148, 519888, 27000, 96, 1, "K2UA"};
  if (tlmFormatEnv(buf, sizeof(buf), &ed) <= 0) { fails++; std::printf("FAIL env format\n"); }
  std::printf("%s", buf);
  ed = {4, 0, 0, 0, 0, 0, "K2UA"};                  // sensor not found
  tlmFormatEnv(buf, sizeof(buf), &ed);
  std::printf("%s", buf);
  {
    EnvData worst = {255, 1048575, 1048575, 65535, 96, 1, "K2UA"};
    char big[TLM_MAX_LINE];
    int m = tlmFormatEnv(big, sizeof(big), &worst);
    if (m <= 0 || m > 56) { fails++; std::printf("FAIL worst-case env length %d\n", m); }
    big[strcspn(big, "\r\n")] = 0;
    if (!tlmValid(big)) { fails++; std::printf("FAIL env valid\n"); }
  }
  if (tlmValid("$RX,1,2,K2UA*00")) { fails++; std::printf("FAIL unknown type accepted\n"); }

  // validator on its own output and on corrupted copies
  buf[strcspn(buf, "\r\n")] = 0;
  if (!tlmValid(buf)) { fails++; std::printf("FAIL valid\n"); }
  buf[5] ^= 1;
  if (tlmValid(buf)) { fails++; std::printf("FAIL corrupt accepted\n"); }
  if (tlmValid("$RT,1,2*00")) { fails++; std::printf("FAIL bad checksum accepted\n"); }
  if (tlmValid("garbage")) { fails++; std::printf("FAIL garbage accepted\n"); }
  char tiny[20];
  if (tlmFormat(tiny, sizeof(tiny), &d) != 0) { fails++; std::printf("FAIL tiny buffer\n"); }

  // transverter reply relay: sanitize like the tower does, then split into parts
  const char *raw = "MKU 10 G5\r\nIF RX: 028 MHz, IF TX: 028 MHz\r\nRF RX $10368* RF TX 10368\r\nD1 50 D2 50 D3 50 D4 50\r\nREF PLL locked\r\n";
  char text[240];
  size_t n = 0;
  for (const char *p = raw; *p; p++) {
    char c = tlmReplyChar(*p);
    if (!c) continue;
    if (c == '|' && (n == 0 || text[n - 1] == '|')) continue;
    if (c == ' ' && n > 0 && text[n - 1] == ' ') continue;
    text[n++] = c;
  }
  while (n && text[n - 1] == '|') n--;
  unsigned total = (unsigned)((n + TLM_RK_TEXT - 1) / TLM_RK_TEXT);
  char line[TLM_RK_LINE];
  for (unsigned part = 0; part < total; part++) {
    size_t off = part * TLM_RK_TEXT;
    size_t len = n - off < TLM_RK_TEXT ? n - off : TLM_RK_TEXT;
    int m = tlmFormatReply(line, sizeof(line), 3, 's', part + 1, total, text + off, len, "K2UA");
    if (m <= 0) { fails++; std::printf("FAIL reply format\n"); break; }
    std::printf("%s", line);
    char chk[TLM_RK_LINE];
    memcpy(chk, line, m);
    chk[strcspn(chk, "\r\n")] = 0;
    if (!tlmValid(chk)) { fails++; std::printf("FAIL reply valid\n"); }
  }
  return fails;
}
