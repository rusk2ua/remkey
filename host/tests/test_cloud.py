"""Cloud copy: what gets uploaded, how often, and that failures never hurt the station."""

import asyncio
import json
import logging

import pytest

from remkey.cloud import CloudUploader
from remkey.config import StationConfig
from remkey.serial_link import FakeLink
from remkey.station import StationService
from remkey.telemetry import PowerPacket, format_supply

SECRET = "test-secret-0123456789"


class FakeS3:
    def __init__(self, fail=None, hang=False):
        self.puts = []
        self.fail = fail
        self.hang = hang

    def put_object(self, **kw):
        if self.hang:
            import time
            time.sleep(0.3)
        if self.fail:
            raise self.fail
        self.puts.append(kw)
        return {}


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def service(**kw):
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0, log_file="", tlm_csv="",
                        cloud_bucket="remkey-tlm-test", **kw)
    return StationService(cfg, FakeLink(), FakeLink())


async def test_uploads_state_recent_history_on_their_schedules():
    svc = service()
    s3, clock = FakeS3(), Clock()
    up = CloudUploader(svc, client_factory=lambda: s3, clock=clock)
    p = PowerPacket(1, 14.0, 13.98, 14.02, 1.1, 1.0, 1.4, True, "K2UA", "base", 21.0, 9)
    svc.tlm.on_line(format_supply(p))
    await up.tick()
    keys = [p["Key"] for p in s3.puts]
    assert keys == ["data/state.json", "data/summary.html", "data/recent.json", "data/history.json"]
    assert all(p["Bucket"] == "remkey-tlm-test" for p in s3.puts)
    assert [p["ContentType"] for p in s3.puts] == ["application/json", "text/html; charset=utf-8",
                                                    "application/json", "application/json"]
    assert s3.puts[0]["CacheControl"] == "max-age=5"
    st = json.loads(s3.puts[0]["Body"])
    assert st["supply"]["v_avg"] == pytest.approx(14.0) and st["interval_s"] == 15.0
    assert st["station"] is None                         # remote session never leaves the house
    s3.puts.clear()
    clock.t += 15
    await up.tick()
    assert [p["Key"] for p in s3.puts] == ["data/state.json"]
    s3.puts.clear()
    clock.t += 50                                        # 65 s since the first round
    await up.tick()
    assert [p["Key"] for p in s3.puts] == ["data/state.json", "data/summary.html", "data/recent.json"]
    s3.puts.clear()
    clock.t += 240                                       # 305 s
    await up.tick()
    assert [p["Key"] for p in s3.puts] == ["data/state.json", "data/summary.html", "data/recent.json",
                                           "data/history.json"]


async def test_failures_are_logged_once_and_retried(caplog):
    caplog.set_level(logging.INFO, logger="remkey.cloud")
    svc = service()
    s3, clock = FakeS3(fail=ConnectionError("no route to host")), Clock()
    up = CloudUploader(svc, client_factory=lambda: s3, clock=clock)
    for _ in range(5):
        await up.tick()
        clock.t += 15
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "no route to host" in warnings[0].getMessage()
    assert up.failures == 5                              # one try per round, nothing piled up
    clock.t += 600
    await up.tick()
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 2   # reminder every 10 min
    s3.fail = None
    await up.tick()
    assert any("working again" in r.getMessage() for r in caplog.records)
    assert [p["Key"] for p in s3.puts] == ["data/state.json", "data/summary.html", "data/recent.json",
                                           "data/history.json"]


async def test_bad_credentials_rebuild_the_client():
    svc = service()
    made = []

    class Denied(Exception):
        pass

    def factory():
        made.append(1)
        return FakeS3(fail=Denied("An error occurred (AccessDenied) when calling PutObject"))

    up = CloudUploader(svc, client_factory=factory, clock=Clock())
    await up.tick()
    await up.tick()
    assert len(made) == 2


async def test_missing_boto3_or_factory_error_does_not_raise():
    svc = service()

    def factory():
        raise ModuleNotFoundError("No module named 'boto3'")

    up = CloudUploader(svc, client_factory=factory, clock=Clock())
    await up.tick()                                      # must not raise
    assert up.failures == 1


async def test_station_runs_uploader_and_keying_is_unaffected():
    svc = service(cloud_interval_s=5)
    s3 = FakeS3(hang=True)                               # a slow upload
    from remkey import cloud as cloud_mod

    orig = cloud_mod.make_s3_client
    cloud_mod.make_s3_client = lambda region, profile: s3
    try:
        await svc.start()
        assert svc.cloud is not None
        t0 = asyncio.get_running_loop().time()
        await asyncio.sleep(0.05)
        assert asyncio.get_running_loop().time() - t0 < 0.2    # the loop isn't blocked by the upload
        await asyncio.sleep(0.5)
        assert s3.puts and s3.puts[0]["Key"] == "data/state.json"
    finally:
        await svc.stop()
        cloud_mod.make_s3_client = orig


async def test_summary_page_is_plain_escaped_html():
    svc = service()
    s3, clock = FakeS3(), Clock()
    up = CloudUploader(svc, client_factory=lambda: s3, clock=clock)
    p = PowerPacket(1, 14.02, 13.98, 14.06, 1.1, 1.0, 5.9, True, "K2UA", "base", 21.5, 9)
    svc.tlm.on_line(format_supply(p))
    svc.tlm.mark("<script>alert(1)</script> TX test")
    await up.tick()
    page = next(p["Body"] for p in s3.puts if p["Key"] == "data/summary.html").decode()
    assert page.startswith("<!doctype html>") and "<script>" not in page
    assert "&lt;script&gt;" in page and "MARK:" in page
    assert "avg 14.02 V, min 13.98 V, max 14.06 V" in page and "peak 5.90 A" in page
    assert "Supply box temperature" in page and "21.5 C" in page
    assert "Tower top</th><td>not heard" in page


async def test_summary_without_telemetry():
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0, log_file="", tlm_csv="",
                        cloud_bucket="b")
    svc = StationService(cfg, FakeLink(), None)
    s3 = FakeS3()
    up = CloudUploader(svc, client_factory=lambda: s3, clock=Clock())
    await up.tick()
    assert [p["Key"] for p in s3.puts] == ["data/state.json", "data/summary.html"]
    assert b"off (tlm_port not set" in s3.puts[1]["Body"]


def test_missing_boto3_message_names_the_interpreter(monkeypatch):
    import builtins
    import sys

    from remkey import cloud as cloud_mod

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "boto3" or name.startswith("botocore"):
            raise ModuleNotFoundError("No module named 'boto3'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as e:
        cloud_mod.make_s3_client("us-east-1", "x")
    assert sys.executable in str(e.value) and "[cloud]" in str(e.value)
