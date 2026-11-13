"""Push telemetry snapshots to S3, for the dashboard copy at tlm.microwavedx.com.

The station service writes three small JSON files under `data/` in the bucket:

    data/state.json     current readings and alerts        every cloud_interval_s (15 s)
    data/recent.json    the last hour, binned for charts    every 60 s
    data/history.json   the last 12 hours, binned           every 5 min

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
import json
import logging
import time
from typing import Any

from .dashboard import _json_safe, build_state

log = logging.getLogger("remkey.cloud")

RECENT_EVERY_S = 60.0
HISTORY_EVERY_S = 300.0
CALL_TIMEOUT_S = 25.0
COMPLAIN_EVERY_S = 600.0

FILES = {
    # name: (cache seconds, what it holds)
    "state.json": 5,
    "recent.json": 30,
    "history.json": 120,
}


def make_s3_client(region: str, profile: str):
    """boto3 S3 client with short timeouts. Imported here so boto3 stays optional."""
    import boto3
    from botocore.config import Config

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
        due: list[tuple[str, Any]] = [("state.json", self.public_state())]
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

    def public_state(self) -> dict:
        st = build_state(self.svc, public=True)
        st["uploaded_at"] = self._clock()
        st["interval_s"] = self.interval
        return st

    async def _put(self, name: str, data: Any) -> bool:
        body = json.dumps(_json_safe(data), separators=(",", ":")).encode()
        try:
            if self._client is None:
                self._client = await asyncio.to_thread(self._factory)
            await asyncio.wait_for(asyncio.to_thread(
                self._client.put_object, Bucket=self.bucket, Key=self.prefix + name, Body=body,
                ContentType="application/json", CacheControl=f"max-age={FILES[name]}"), CALL_TIMEOUT_S)
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
