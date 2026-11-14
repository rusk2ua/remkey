"""Push telemetry snapshots to S3, for the dashboard copy at tlm.microwavedx.com.

The station service writes three small JSON files under `data/` in the bucket:

    data/state.json     current readings and alerts        every cloud_interval_s (15 s)
    data/recent.json    the last hour, binned for charts    every 60 s
    data/history.json   the last 12 hours, binned           every 5 min
    data/summary.html   plain readable summary (for Claude's web fetch, which
                        reads HTML but not JSON from this site)   every 60 s

CloudFront serves them, with the dashboard page, from the same bucket (see
cloud/deploy.sh). Only data goes up: nothing on the internet can reach the
station, and the remote session (client address, PTT) is left out.

Safety: uploads run in a worker thread with short timeouts, one at a time. A
slow or dead internet connection only delays the next snapshot; it never
touches keying or the local dashboard.

Needs boto3 (`pip install -e ".[cloud]"`) and a credentials profile with
s3:PutObject on the bucket's data/ prefix (cloud/deploy.sh makes one).
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import sys
import time
from typing import Any

from .dashboard import _json_safe, build_state

log = logging.getLogger("remkey.cloud")

RECENT_EVERY_S = 60.0
SUMMARY_EVERY_S = 60.0
HISTORY_EVERY_S = 300.0
CALL_TIMEOUT_S = 25.0
COMPLAIN_EVERY_S = 600.0

FILES = {
    # name: (cache seconds, what it holds)
    "state.json": 5,
    "recent.json": 30,
    "history.json": 120,
    "summary.html": 30,
}
CONTENT_TYPES = {"summary.html": "text/html; charset=utf-8"}


def make_s3_client(region: str, profile: str):
    """boto3 S3 client with short timeouts. Imported here so boto3 stays optional."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError(
            f"boto3 isn't installed for the Python running the station ({sys.executable}); "
            f'install it with: "{sys.executable}" -m pip install -e ".[cloud]"  '
            "(or host\\Install-remkey.bat cloud)") from None

    session = boto3.Session(profile_name=profile or None, region_name=region or None)
    return session.client("s3", config=Config(connect_timeout=5, read_timeout=10,
                                              retries={"max_attempts": 2, "mode": "standard"}))


class CloudUploader:
    def __init__(self, svc, client_factory=None, clock=time.time):
        cfg = svc.cfg
        self.svc = svc
        self.bucket = cfg.cloud_bucket
        self.prefix = "data/"
        self.interval = max(5.0, float(cfg.cloud_interval_s))
        self.region = cfg.cloud_region
        self.profile = cfg.cloud_profile
        self._factory = client_factory or (lambda: make_s3_client(self.region, self.profile))
        self._client = None
        self._clock = clock
        self._task: asyncio.Task | None = None
        self._last_recent = 0.0
        self._last_history = 0.0
        self._last_summary = 0.0
        self._failing_since: float | None = None
        self._last_complaint = 0.0
        self.uploads = 0
        self.failures = 0

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="cloud-upload")
        log.info("cloud: uploading to s3://%s/%s every %.0f s", self.bucket, self.prefix, self.interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self.interval)

    # ------------------------------------------------------------ one round
    async def tick(self) -> None:
        """Upload what's due. Never raises."""
        now = self._clock()
        state = self.public_state()
        due: list[tuple[str, Any]] = [("state.json", state)]
        if now - self._last_summary >= SUMMARY_EVERY_S:
            due.append(("summary.html", summary_html(state)))
        hub = self.svc.tlm
        if hub is not None:
            if now - self._last_recent >= RECENT_EVERY_S:
                due.append(("recent.json", hub.history.query(60, 360, now=now)))
            if now - self._last_history >= HISTORY_EVERY_S:
                due.append(("history.json", hub.history.query(720, 720, now=now)))
        for name, data in due:
            ok = await self._put(name, data)
            if not ok:
                return                      # don't pile up: try again next round
            if name == "recent.json":
                self._last_recent = now
            elif name == "history.json":
                self._last_history = now
            elif name == "summary.html":
                self._last_summary = now

    def public_state(self) -> dict:
        st = build_state(self.svc, public=True)
        st["uploaded_at"] = self._clock()
        st["interval_s"] = self.interval
        return st

    async def _put(self, name: str, data: Any) -> bool:
        if isinstance(data, str):
            body = data.encode()
        else:
            body = json.dumps(_json_safe(data), separators=(",", ":")).encode()
        try:
            if self._client is None:
                self._client = await asyncio.to_thread(self._factory)
            await asyncio.wait_for(asyncio.to_thread(
                self._client.put_object, Bucket=self.bucket, Key=self.prefix + name, Body=body,
                ContentType=CONTENT_TYPES.get(name, "application/json"),
                CacheControl=f"max-age={FILES[name]}"), CALL_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001  any failure: log (rate-limited) and carry on
            self.failures += 1
            now = self._clock()
            if self._failing_since is None:
                self._failing_since = now
                self._last_complaint = now
                log.warning("cloud: upload of %s failed: %s", name, _short(exc))
            elif now - self._last_complaint >= COMPLAIN_EVERY_S:
                self._last_complaint = now
                log.warning("cloud: uploads still failing (%d min): %s",
                            round((now - self._failing_since) / 60), _short(exc))
            if _is_credentials_problem(exc):
                self._client = None          # pick up fixed credentials without a restart
            return False
        self.uploads += 1
        if self._failing_since is not None:
            log.info("cloud: uploads working again after %d min",
                     round((self._clock() - self._failing_since) / 60))
            self._failing_since = None
        return True


def _short(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) < 200 else text[:200] + "..."


def _is_credentials_problem(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in ("NoCredentialsError", "ProfileNotFound", "PartialCredentialsError") or \
        "AccessDenied" in str(exc) or "InvalidAccessKeyId" in str(exc) or "SignatureDoesNotMatch" in str(exc)


# ---------------------------------------------------------------------------
# Plain-HTML summary
# ---------------------------------------------------------------------------
def _f(v, d=2, unit=""):
    return "n/a" if v is None else f"{v:.{d}f}{unit}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def summary_html(st: dict) -> str:
    """A small, script-free page with the current readings: easy for any fetcher to read."""
    when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(st.get("uploaded_at") or st["now"]))
    rows: list[tuple[str, str]] = [("Station clock at upload", when)]
    if not st.get("telemetry"):
        rows.append(("Telemetry", "off (tlm_port not set on the shack PC)"))
    b = st.get("supply")
    if b is None:
        rows.append(("Supply box (tower base)", "not heard since the station started"))
    else:
        lim = st.get("limits", {})
        state = "LOST" if b["stale"] else ("INA226 not answering" if not b["ok"] else "OK")
        rows += [
            ("Supply box link", f"{state}; last packet {_f(b['age_s'], 0)} s before upload; "
                                f"{_f(b['loss_pct'], 1)}% loss over 5 min; uptime {b['uptime_s']} s"),
            ("Supply voltage at tower base",
             f"avg {_f(b['v_avg'])} V, min {_f(b['v_min'])} V, max {_f(b['v_max'])} V "
             f"(low alert {lim.get('v_min_alert')} V)"),
            ("Tower current", f"avg {_f(b['i_avg'])} A, peak {_f(b['i_max'])} A"),
            (f"{_cap(b.get('temp_name') or 'supply box')} temperature", _f(b["temp_c"], 1, " C")),
        ]
    if st.get("drop_v") is not None:
        rows.append(("Measured cable drop", _f(st["drop_v"], 2, " V")))
    t = st.get("tower")
    if t is None:
        rows.append(("Tower top", "not heard since the station started"))
    else:
        names = t.get("temp_names") or ["PA heatsink", "transverter case"]
        if t.get("pa_pk_w") is not None:
            pa = f"peak {_f(t['pa_pk_w'], 1)} W, avg {_f(t['pa_avg_w'], 1)} W"
        else:
            pa = f"peak {t['pa_pk_mv']} mV, avg {t['pa_avg_mv']} mV (uncalibrated)"
        lock = {True: "locked", False: "UNLOCKED", None: "not monitored"}[t.get("lock")]
        rows += [
            ("Tower-top link", f"{'LOST' if t['stale'] else 'OK'}; "
                               f"last packet {_f(t['age_s'], 0)} s before upload; "
                               f"{_f(t['loss_pct'], 1)}% loss over 5 min"),
            ("PA output", pa),
            ("10 MHz reference", lock),
            (f"{_cap(names[0])} temperature", _f(t.get("temp_c"), 1, " C")),
            (f"{_cap(names[1])} temperature", _f(t.get("temp2_c"), 1, " C")),
        ]
    xv = (st.get("xv") or {}).get("s")
    if xv:
        rows.append(("Transverter status (MKU 's' reply)", xv["text"]))
    alerts = st.get("alerts") or []
    items = "".join(
        f"<li>{html.escape(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(a['ts'])))} "
        f"[{html.escape(a['level'])}] {html.escape(a['msg'])}</li>"
        for a in reversed(alerts[-15:])) or "<li>none</li>"
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>Tower telemetry summary</title></head><body>"
            "<h1>Tower telemetry summary</h1>"
            f"<p>Uploaded by the station every {SUMMARY_EVERY_S:.0f} s. Live page: ../</p>"
            f"<table>{body}</table><h2>Recent alerts (newest first)</h2><ul>{items}</ul>"
            "</body></html>")
