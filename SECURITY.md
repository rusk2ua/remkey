# Security

The station service listens on a TCP port and can key a transmitter, so treat it
like any remote-control service.

**How it is protected**
- Every connection must answer an HMAC-SHA256 challenge (fresh nonce each time)
  using the shared `secret`; there is no password on the wire and no replay.
- One client at a time; CW text is filtered to a fixed character set.
- PTT drops if the client goes quiet for 3 s, and the station Nano drops it on its
  own if the PC stops talking to it.

**What it does not do**
- Traffic is not encrypted. CW text isn't secret, but someone on the network path
  could in principle interfere with an authenticated session. If that matters to
  you, use the AnyDesk tunnel option (nothing exposed on the router) or a VPN.

**Keep it safe**
- Generate the secret with `python -m remkey.genkey`; never commit `station.toml`
  or `client.toml` (both are in `.gitignore`).
- Remove the secret and your public IP from logs before posting them in an issue.

**Reporting a problem**
Please report security issues privately through GitHub's "Report a vulnerability"
(Security tab) rather than in a public issue.
