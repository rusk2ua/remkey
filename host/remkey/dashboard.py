"""Telemetry dashboard: a small read-mostly web page served by the station service.

    http://<shack-pc>:8080/

Open it in any browser on the home network (or over Tailscale). It shows the
supply box and tower-top readings live, history charts, the transverter's status
replies and the alert log.

Deliberately limited:
- No route touches the keyer. The few buttons only clear the dashboard's alert
  list, reset its min/max and link counters, or write a marker into the log.
- Only clients from the networks in `dash_allow` get an answer (home LAN and
  Tailscale by default); anything else is dropped without a reply.
- The Host header must be an IP address, a bare machine name, *.local, *.lan,
  *.home.arpa, *.ts.net or a name in `dash_hostnames`. That stops a web page
  from some other site reaching this one through DNS rebinding.
- Buttons need a custom request header, which browsers only send from this page
  itself, so another site can't press them for you.

No third-party packages: plain asyncio, HTTP/1.1 and Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import csv
import ipaddress
import json
import logging
import math
import re
import time
from collections import deque
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

log = logging.getLogger("remkey.dashboard")

MAX_HEADER_LINE = 8192
MAX_HEADERS = 60
MAX_BODY = 2048
MAX_SSE_CLIENTS = 8
SSE_PERIOD_S = 1.0
MARK_MAX = 80

DEFAULT_ALLOW = [
    "127.0.0.0/8", "::1/128",                                   # this PC
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",            # home LAN
    "169.254.0.0/16", "fe80::/10",                              # link-local
    "100.64.0.0/10", "fd7a:115c:a1e0::/48",                     # Tailscale
]


# ---------------------------------------------------------------------------
# History: recent readings kept in memory for the charts
# ---------------------------------------------------------------------------
# Field order of each stored tuple. Time is the first field everywhere.
SUPPLY_FIELDS = ("t", "v_avg", "v_min", "v_max", "i_avg", "i_max", "temp")
TOWER_FIELDS = ("t", "pa_pk", "pa_avg", "xv_pk", "lock", "t1", "t2")
TOP_FIELDS = ("t", "v_avg", "v_min")

# How each field combines when several readings fall into one chart point.
_AGG = {"v_min": "min", "v_max": "max", "i_max": "max", "pa_pk": "max", "xv_pk": "max",
        "lock": "min"}


class History:
    """Time-limited ring buffers of readings, binned on request for the charts."""

    def __init__(self, hours: float = 12.0):
        self.keep_s = max(0.1, float(hours)) * 3600.0
        self.supply: deque[tuple] = deque()
        self.tower: deque[tuple] = deque()
        self.top: deque[tuple] = deque()
        self.pa_unit = "W"                      # "mV" when the PA power isn't calibrated

    def _add(self, buf: deque, row: tuple) -> None:
        if buf and row[0] < buf[-1][0]:         # clock stepped back: keep order anyway
            row = (buf[-1][0],) + row[1:]
        buf.append(row)
        cutoff = row[0] - self.keep_s
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def add_supply(self, t: float, p) -> None:
        if p.ok:
            self._add(self.supply, (t, p.v_avg, p.v_min, p.v_max, p.i_avg, p.i_max, p.temp_c))
        else:
            self._add(self.supply, (t, None, None, None, None, None, p.temp_c))

    def add_tower(self, t: float, pa_pk, pa_avg, xv_pk, lock, t1, t2) -> None:
        self._add(self.tower, (t, pa_pk, pa_avg, xv_pk,
                               None if lock is None else (1 if lock else 0), t1, t2))

    def add_top(self, t: float, p) -> None:
        if p.ok:
            self._add(self.top, (t, p.v_avg, p.v_min))

    def query(self, minutes: float, points: int, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        minutes = max(1.0, min(float(minutes), self.keep_s / 60.0))
        points = max(10, min(int(points), 2000))
        since = now - minutes * 60.0
        return {
            "since": since, "until": now, "step_s": minutes * 60.0 / points,
            "pa_unit": self.pa_unit,
            "supply": _bin(self.supply, SUPPLY_FIELDS, since, now, points),
            "tower": _bin(self.tower, TOWER_FIELDS, since, now, points),
            "top": _bin(self.top, TOP_FIELDS, since, now, points),
        }

    # ------------------------------------------------------------ CSV seeding
    def seed_from_csv(self, path: str, max_bytes: int = 24 * 1024 * 1024) -> int:
        """Load the tail of remkey-tlm.csv so the charts survive a restart. Returns rows loaded."""
        p = Path(path)
        if not path or not p.exists():
            return 0
        cutoff = time.time() - self.keep_s
        with p.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            header = f.readline().decode("utf-8", "replace")
            start = max(f.tell(), size - max_bytes)
            f.seek(start)
            if start > len(header.encode()):
                f.readline()                    # drop the partial line we landed in
            body = f.read().decode("utf-8", "replace")
        names = next(csv.reader([header]), [])
        if "time" not in names:
            return 0
        n = 0
        for rec in csv.DictReader(body.splitlines(), fieldnames=names):
            try:
                t = time.mktime(time.strptime(rec["time"], "%Y-%m-%d %H:%M:%S"))
            except (ValueError, TypeError, KeyError):
                continue
            if t < cutoff:
                continue
            n += self._seed_row(t, rec)
        return n

    def _seed_row(self, t: float, r: dict) -> int:
        def num(k):
            v = (r.get(k) or "").strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None

        added = 0
        if (r.get("pa_pk_mv") or "").strip():
            pk_w, avg_w = num("pa_pk_w"), num("pa_avg_w")
            if pk_w is None:
                pk, avg = num("pa_pk_mv"), num("pa_avg_mv")
                self.pa_unit = "mV"
            else:
                pk, avg = pk_w, avg_w
            lock = num("ref_lock")
            self._add(self.tower, (t, pk, avg, num("xv_pk_mv"),
                                   None if lock is None else int(lock), num("temp1_c"), num("temp2_c")))
            added = 1
        at = (r.get("supply_at") or "").strip()
        if at == "base":
            self._add(self.supply, (t, num("v_avg"), num("v_min"), num("v_max"),
                                    num("i_avg"), num("i_max"), num("box_temp_c")))
            top_v = num("top_v_avg")
            if top_v is not None:
                self._add(self.top, (t, top_v, top_v))
            added = 1
        elif at == "top":
            self._add(self.top, (t, num("v_avg"), num("v_min")))
            added = 1
        return added


def _bin(buf: deque, fields: tuple, since: float, until: float, points: int) -> dict:
    """Columnar arrays, at most `points` per field: averages, or min/max for the extreme fields."""
    out: dict[str, list] = {f: [] for f in fields}
    rows = [r for r in buf if r[0] >= since]
    if not rows:
        return out
    step = (until - since) / points
    groups: dict[int, list[tuple]] = {}
    for r in rows:
        groups.setdefault(min(points - 1, int((r[0] - since) / step)), []).append(r)
    for k in sorted(groups):
        g = groups[k]
        out["t"].append(round(sum(r[0] for r in g) / len(g), 1))
        for i, f in enumerate(fields[1:], start=1):
            vals = [r[i] for r in g if r[i] is not None]
            if not vals:
                out[f].append(None)
                continue
            how = _AGG.get(f, "avg")
            v = min(vals) if how == "min" else max(vals) if how == "max" else sum(vals) / len(vals)
            out[f].append(round(v, 4))
    return out


# ---------------------------------------------------------------------------
# Extremes since the last reset ("Reset min/max" button)
# ---------------------------------------------------------------------------
class Extremes:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.since = time.time()
        self.lo: dict[str, float] = {}
        self.hi: dict[str, float] = {}

    def add(self, key: str, lo: float | None, hi: float | None = None) -> None:
        hi = lo if hi is None else hi
        if lo is not None and (key not in self.lo or lo < self.lo[key]):
            self.lo[key] = lo
        if hi is not None and (key not in self.hi or hi > self.hi[key]):
            self.hi[key] = hi

    def as_dict(self) -> dict:
        keys = sorted(set(self.lo) | set(self.hi))
        return {"since": self.since, **{k: [self.lo.get(k), self.hi.get(k)] for k in keys}}


# ---------------------------------------------------------------------------
# Access checks
# ---------------------------------------------------------------------------
def parse_allow(items) -> list:
    nets = []
    for s in items or []:
        try:
            nets.append(ipaddress.ip_network(str(s).strip(), strict=False))
        except ValueError:
            log.warning("dashboard: ignoring bad dash_allow entry %r", s)
    return nets


def peer_allowed(peer: str | None, nets: list) -> bool:
    if not peer:
        return False
    try:
        ip = ipaddress.ip_address(peer.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip.version == n.version and ip in n for n in nets)


_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_OK_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".ts.net")


def host_allowed(host: str | None, extra: list[str]) -> bool:
    """True for an IP literal, a bare machine name, a home/Tailscale suffix, or a configured name."""
    if not host:
        return False
    h = host.strip().lower()
    if h.startswith("["):                                   # [IPv6]:port
        h = h[1:h.find("]")] if "]" in h else h[1:]
    elif h.count(":") == 1:
        h = h.split(":")[0]
    h = h.rstrip(".")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    if h in (e.strip().lower().rstrip(".") for e in extra):
        return True
    if h == "localhost" or _LABEL.match(h):                  # "shackpc"
        return True
    return h.endswith(_OK_SUFFIXES) and all(_LABEL.match(p) for p in h.split("."))


# ---------------------------------------------------------------------------
# The web server
# ---------------------------------------------------------------------------
def _page() -> bytes:
    return resources.files("remkey").joinpath("web/dashboard.html").read_bytes()


def _json_safe(o: Any) -> Any:
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


def _dumps(o: Any) -> bytes:
    return json.dumps(_json_safe(o), separators=(",", ":")).encode()


class Dashboard:
    """Serves the page and its API from the station service's own event loop."""

    def __init__(self, svc, host: str, port: int, allow, hostnames):
        self.svc = svc
        self.host = host
        self.port_cfg = port
        self.nets = parse_allow(allow if allow else DEFAULT_ALLOW)
        self.hostnames = [str(h) for h in (hostnames or [])]
        self.server: asyncio.base_events.Server | None = None
        self.sse: set[asyncio.Queue] = set()

    @property
    def port(self) -> int:
        assert self.server is not None
        return self.server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, self.host, self.port_cfg,
                                                 limit=MAX_HEADER_LINE)
        def url(sock) -> str:
            h, p = sock.getsockname()[:2]
            return f"http://[{h}]:{p}/" if ":" in h else f"http://{h}:{p}/"
        log.info("dashboard on %s (answers %s)", ", ".join(url(s) for s in self.server.sockets),
                 ", ".join(map(str, self.nets)))

    async def stop(self) -> None:
        for q in list(self.sse):
            q.put_nowait(None)
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), 2.0)
            except TimeoutError:
                pass

    def push_alert(self, alert: dict) -> None:
        for q in list(self.sse):
            if q.qsize() < 100:
                q.put_nowait(("alert", alert))

    # ------------------------------------------------------------ HTTP
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = (writer.get_extra_info("peername") or ("",))[0]
        try:
            if not peer_allowed(peer, self.nets):
                log.warning("dashboard: refused %s (not in dash_allow)", peer)
                return
            try:
                req = await asyncio.wait_for(self._read_request(reader), 10.0)
            except (TimeoutError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                await self._send(writer, 400, b"bad request\n", "text/plain")
                return
            if req is None:
                return
            method, path, query, headers, body = req
            if not host_allowed(headers.get("host"), self.hostnames):
                await self._send(writer, 421, b"unknown host name; add it to dash_hostnames\n",
                                 "text/plain")
                return
            await self._route(writer, peer, method, path, query, headers, body)
        except (ConnectionError, RuntimeError):
            pass
        except Exception:  # noqa: BLE001  the dashboard must never take the station down
            log.exception("dashboard: request failed")
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _read_request(self, reader):
        line = await reader.readline()
        if not line:
            return None
        parts = line.decode("latin-1").strip().split()
        if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
            raise ValueError("request line")
        method, target = parts[0].upper(), parts[1]
        headers: dict[str, str] = {}
        for _ in range(MAX_HEADERS + 1):
            h = await reader.readline()
            if h in (b"\r\n", b"\n", b""):
                break
            k, _, v = h.decode("latin-1").partition(":")
            headers[k.strip().lower()] = v.strip()
        else:
            raise ValueError("too many headers")
        body = b""
        n = int(headers.get("content-length") or 0)
        if n < 0 or n > MAX_BODY:
            raise ValueError("body size")
        if n:
            body = await reader.readexactly(n)
        u = urlsplit(target)
        return method, u.path, parse_qs(u.query), headers, body

    async def _send(self, writer, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        reason = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden",
                  404: "Not Found", 405: "Method Not Allowed", 421: "Misdirected Request",
                  503: "Service Unavailable"}.get(status, "OK")
        hdr = [f"HTTP/1.1 {status} {reason}", f"Content-Type: {ctype}",
               f"Content-Length: {len(body)}", "Cache-Control: no-store",
               "X-Content-Type-Options: nosniff", "X-Frame-Options: DENY",
               "Referrer-Policy: no-referrer", "Connection: close"]
        for k, v in (extra or {}).items():
            hdr.append(f"{k}: {v}")
        writer.write(("\r\n".join(hdr) + "\r\n\r\n").encode() + body)
        await writer.drain()

    async def _route(self, writer, peer, method, path, query, headers, body) -> None:
        if path in ("/", "/index.html"):
            if method != "GET":
                return await self._send(writer, 405, b"", "text/plain")
            csp = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                   "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            return await self._send(writer, 200, _page(), "text/html; charset=utf-8",
                                    {"Content-Security-Policy": csp})
        if path == "/api/state" and method == "GET":
            return await self._send(writer, 200, _dumps(self.state()), "application/json")
        if path == "/api/history" and method == "GET":
            def q(name, default):
                try:
                    return float(query.get(name, [default])[0])
                except ValueError:
                    return float(default)
            hub = self.svc.tlm
            data = hub.history.query(q("minutes", 60), int(q("points", 600))) if hub else None
            return await self._send(writer, 200, _dumps(data), "application/json")
        if path == "/api/events" and method == "GET":
            return await self._events(writer)
        if path == "/api/action":
            if method != "POST":
                return await self._send(writer, 405, b"", "text/plain")
            return await self._action(writer, peer, headers, body)
        await self._send(writer, 404, b"not found\n", "text/plain")

    async def _events(self, writer) -> None:
        if len(self.sse) >= MAX_SSE_CLIENTS:
            return await self._send(writer, 503, b"too many dashboard pages open\n", "text/plain")
        q: asyncio.Queue = asyncio.Queue()
        self.sse.add(q)
        try:
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                         b"Cache-Control: no-store\r\nX-Accel-Buffering: no\r\nConnection: close\r\n\r\n"
                         b"retry: 3000\n\n")
            await writer.drain()
            while True:
                writer.write(b"event: state\ndata: " + _dumps(self.state()) + b"\n\n")
                await writer.drain()
                try:
                    item = await asyncio.wait_for(q.get(), SSE_PERIOD_S)
                except TimeoutError:
                    continue
                if item is None:
                    return
                kind, data = item
                writer.write(f"event: {kind}\ndata: ".encode() + _dumps(data) + b"\n\n")
                await writer.drain()
        finally:
            self.sse.discard(q)

    async def _action(self, writer, peer, headers, body) -> None:
        # A custom header can't be sent cross-site without a CORS preflight, which
        # this server never approves; so only our own page can press the buttons.
        if headers.get("x-remkey-dash") != "1":
            return await self._send(writer, 403, b"forbidden\n", "text/plain")
        origin = headers.get("origin")
        if origin and urlsplit(origin).netloc.lower() != (headers.get("host") or "").lower():
            return await self._send(writer, 403, b"forbidden\n", "text/plain")
        try:
            msg = json.loads(body or b"{}")
            action = str(msg.get("action", ""))
        except (ValueError, AttributeError):
            return await self._send(writer, 400, b"bad json\n", "text/plain")
        hub = self.svc.tlm
        if hub is None:
            return await self._send(writer, 503, b"telemetry is off\n", "text/plain")
        if action == "clear_alerts":
            hub.alerts.clear()
            log.info("dashboard: alert list cleared (from %s)", peer)
        elif action == "reset_stats":
            hub.extremes.reset()
            for st in (hub.stats, hub.box_stats):
                st.received = st.lost = st.resets = 0
                st.recent.clear()
            log.info("dashboard: min/max and link counters reset (from %s)", peer)
        elif action == "mark":
            text = re.sub(r"[^\x20-\x7e]", "", str(msg.get("text", ""))).strip()[:MARK_MAX]
            if not text:
                return await self._send(writer, 400, b"empty marker\n", "text/plain")
            hub.mark(text, peer)
        else:
            return await self._send(writer, 400, b"unknown action\n", "text/plain")
        await self._send(writer, 200, _dumps({"ok": True, "state": self.state()}), "application/json")

    # ------------------------------------------------------------ state
    def state(self) -> dict:
        svc = self.svc
        cfg = svc.cfg
        now = time.time()
        sess = svc.session
        st: dict[str, Any] = {
            "now": now,
            "station": {"client": bool(sess),
                        "client_peer": str(sess.peer[0]) if sess and sess.peer else None,
                        "ptt": svc.ptt, "releasing": svc.releasing, "wpm": svc.wpm},
            "limits": {"v_min_alert": cfg.v_min_alert, "v_max_alert": cfg.v_max_alert,
                       "i_max_alert": cfg.i_max_alert, "i_min_alert": cfg.i_min_alert,
                       "temp_warn_c": cfg.temp_warn_c, "temp2_warn_c": cfg.temp2_warn_c,
                       "box_temp_warn_c": cfg.box_temp_warn_c, "stale_s": cfg.tlm_stale_s},
            "telemetry": svc.tlm is not None,
        }
        hub = svc.tlm
        if hub is None:
            return st
        box = hub.box
        st["supply"] = None if box is None else {
            "ok": box.ok, "v_avg": box.v_avg, "v_min": box.v_min, "v_max": box.v_max,
            "i_avg": box.i_avg, "i_min": box.i_min, "i_max": box.i_max,
            "temp_c": box.temp_c, "temp_name": cfg.box_temp_name, "uptime_s": box.uptime_s,
            "age_s": round(hub.box_stats.age_s() or 0.0, 1), "stale": hub.box_stale,
            "loss_pct": round(hub.box_stats.loss_pct_5min(), 1),
            "received": hub.box_stats.received, "lost": hub.box_stats.lost,
            "resets": hub.box_stats.resets,
        }
        top = hub.pwr
        st["top_supply"] = None if top is None else {
            "ok": top.ok, "v_avg": top.v_avg, "v_min": top.v_min, "i_avg": top.i_avg,
            "age_s": round(now - hub.pwr_time, 1),
        }
        lt = hub.latest
        st["tower"] = None if lt is None else {
            **{k: lt.get(k) for k in ("pa_pk_w", "pa_avg_w", "pa_pk_mv", "pa_avg_mv", "xv_pk_mv",
                                      "xv_pk_w", "lock", "temp_c", "temp2_c", "temp_names", "uptime_s")},
            "age_s": round(hub.stats.age_s() or 0.0, 1), "stale": hub.stale,
            "loss_pct": round(hub.stats.loss_pct_5min(), 1), "received": hub.stats.received,
            "lost": hub.stats.lost, "resets": hub.stats.resets,
        }
        st["drop_v"] = (box.v_avg - top.v_avg
                        if box and top and box.ok and top.ok and not hub.box_stale
                        and now - hub.pwr_time <= cfg.tlm_stale_s else None)
        st["xv"] = {k: {"text": v["text"], "age_s": round(now - v["time"])}
                    for k, v in hub.xv_replies.items()}
        st["extremes"] = hub.extremes.as_dict()
        st["alerts"] = list(hub.alerts)[-60:]
        st["alert_count"] = len(hub.alerts)
        return st
