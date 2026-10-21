// Checks tlm_proto.h and prints sample packets for the Python cross-check
// (host/tests/test_telemetry.py compiles and runs this if g++ is available).
#include "tlm_proto.h"
#include <cstdio>

int main() {
  int fails = 0;
  char buf[TLM_MAX_LINE];
  TlmData d = {65535, 4987, 1234, 0, 1, 452, 318, 86400UL, "K2UA"};
  if (tlmFormat(buf, sizeof(buf), &d) <= 0) { std::printf("FAIL format\n"); return 1; }
  std::printf("%s", buf);
  d = {7, 0, 0, 2500, 0, TLM_TEMP_NONE, TLM_TEMP_NONE, 3, "K2UA"};
  tlmFormat(buf, sizeof(buf), &d);
  std::printf("%s", buf);
  d = {8, 100, 50, 0, 2, -105, 0, 4, "K2UA"};   // -10.5 C, lock monitoring off
  tlmFormat(buf, sizeof(buf), &d);
  std::printf("%s", buf);

  // validator on its own output and on corrupted copies
  buf[strcspn(buf, "\r\n")] = 0;
  if (!tlmValid(buf)) { fails++; std::printf("FAIL valid\n"); }
  buf[5] ^= 1;
  if (tlmValid(buf)) { fails++; std::printf("FAIL corrupt accepted\n"); }
  if (tlmValid("$RT,1,2*00")) { fails++; std::printf("FAIL bad checksum accepted\n"); }
  if (tlmValid("garbage")) { fails++; std::printf("FAIL garbage accepted\n"); }
  char tiny[20];
  if (tlmFormat(tiny, sizeof(tiny), &d) != 0) { fails++; std::printf("FAIL tiny buffer\n"); }

  // transverter reply relay: sanitise like the tower does, then split into parts
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
