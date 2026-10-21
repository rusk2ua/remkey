// Checks tlm_proto.h and prints sample packets for the Python cross-check
// (host/tests/test_telemetry.py compiles and runs this if g++ is available).
#include "tlm_proto.h"
#include <cstdio>

int main() {
  int fails = 0;
  TlmData d = {65535, 4987, 1234, 0, 1, 452, 86400UL, "K2UA"};
  char buf[TLM_MAX_LINE];
  int n = tlmFormat(buf, sizeof(buf), &d);
  if (n <= 0) { std::printf("FAIL format\n"); return 1; }
  std::printf("%s", buf);
  d = {7, 0, 0, 2500, 0, TLM_TEMP_NONE, 3, "K2UA"};
  tlmFormat(buf, sizeof(buf), &d);
  std::printf("%s", buf);
  d = {8, 100, 50, 0, 1, -105, 4, "K2UA"};   // -10.5 C
  tlmFormat(buf, sizeof(buf), &d);
  std::printf("%s", buf);

  // validator on its own output and on corrupted copies
  buf[strcspn(buf, "\r\n")] = 0;
  if (!tlmValid(buf)) { fails++; std::printf("FAIL valid\n"); }
  buf[5] ^= 1;
  if (tlmValid(buf)) { fails++; std::printf("FAIL corrupt accepted\n"); }
  if (tlmValid("$RT,1,2*00")) { fails++; std::printf("FAIL bad checksum accepted\n"); }
  if (tlmValid("garbage")) { fails++; std::printf("FAIL garbage accepted\n"); }
  // a small buffer must fail cleanly, never overflow
  char tiny[20];
  if (tlmFormat(tiny, sizeof(tiny), &d) != 0) { fails++; std::printf("FAIL tiny buffer\n"); }
  return fails;
}
