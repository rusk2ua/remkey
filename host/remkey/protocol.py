"""Network protocol shared by the station service and the client.

Transport is one TCP connection carrying newline-delimited JSON objects.
Every object has a "t" (type) field.

Handshake:
    station -> client  {"t": "hello", "v": 1, "nonce": "<hex>"}
    client  -> station {"t": "auth", "mac": hex(HMAC-SHA256(secret, nonce))}
    station -> client  {"t": "ok"}  (or {"t": "err", ...} and close)

Client -> station after auth:
    {"t": "cw", "text": "CQ K2UA"}      characters to send (sanitised station-side too)
    {"t": "ptt", "on": true}            manual PTT (the TRANSMIT button)
    {"t": "wpm", "v": 18}               sending speed
    {"t": "tune", "ms": 5000}           key-down carrier, capped station-side
    {"t": "abort"}                      flush queued text / stop tune
    {"t": "hb", "ts": 12345.678}        heartbeat, echoed back for RTT

Station -> client:
    {"t": "state", "ptt": bool, "wpm": int}
    {"t": "drained"}                    station keyer finished sending
    {"t": "wdog", "why": "..."}         a safety stop happened
    {"t": "hb", "ts": ...}              heartbeat echo
    {"t": "log", "msg": "..."}          informational
    {"t": "err", "msg": "..."}
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any

PROTOCOL_VERSION = 1
MAX_LINE = 4096

# Characters the firmware knows how to send (see MORSE table in remkey.ino).
CW_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?/=+-()':\"@&!; ")

# Prosign shorthand -> what the firmware sends. Braces carry raw element patterns.
PROSIGNS = {
    "AR": "+",
    "BT": "=",
    "KN": "(",
    "AS": "&",
    "SK": "{...-.-}",
    "HH": "{........}",
    "SOS": "{...---...}",
    "CT": "{-.-.-}",
}

_PROSIGN_RE = re.compile(r"<([A-Z]{2,3})>")
_RAW_RE = re.compile(r"\{[.\-]{1,10}\}")


def encode(msg: dict[str, Any]) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_LINE:
        raise ValueError("line too long")
    obj = json.loads(line.decode("utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
        raise ValueError("not a protocol message")
    return obj


def make_nonce() -> str:
    return secrets.token_hex(16)


def compute_mac(secret: str, nonce: str) -> str:
    return hmac.new(secret.encode("utf-8"), nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_mac(secret: str, nonce: str, mac: str) -> bool:
    if not isinstance(mac, str):
        return False
    return hmac.compare_digest(compute_mac(secret, nonce), mac)


def sanitize_cw(text: str, max_len: int = 512) -> str:
    """Upper-case, expand <SK>-style prosigns, keep only sendable characters.

    Raw element patterns in braces ("{...-.-}") pass through unchanged.
    Runs of whitespace collapse to a single space (newline counts as space).
    """
    text = text.upper()
    text = _PROSIGN_RE.sub(lambda m: PROSIGNS.get(m.group(1), ""), text)
    out: list[str] = []
    i = 0
    while i < len(text):
        m = _RAW_RE.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        c = text[i]
        if c.isspace():
            if not out or out[-1] != " ":
                out.append(" ")
        elif c in CW_CHARS:
            out.append(c)
        i += 1
    result = "".join(out)
    return result[:max_len]


def chunk_for_keyer(text: str, size: int = 60) -> list[str]:
    """Split text into keyer-sized pieces without breaking a {raw} pattern."""
    chunks: list[str] = []
    cur = ""
    for token in re.findall(r"\{[.\-]{1,10}\}|.", text):
        if len(cur) + len(token) > size:
            chunks.append(cur)
            cur = ""
        cur += token
    if cur:
        chunks.append(cur)
    return chunks
