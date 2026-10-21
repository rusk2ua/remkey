import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from remkey import protocol as P
from remkey.client import ClientApp, Console
from remkey.config import ClientConfig, StationConfig
from remkey.serial_link import FakeLink
from remkey.station import StationService
from remkey.telemetry import Calibration, LinkStats, Packet, format_packet, parse_packet

from test_station_client import SECRET, NullOut, raw_connect, wait_for

REPO = Path(__file__).resolve().parents[2]


def pkt(seq=1, pa=0, avg=0, xv=0, lock=True, temp=30.0, up=10):
    return format_packet(Packet(seq, pa, avg, xv, lock, temp, up, "K2UA"))


def test_roundtrip_and_checksum():
    line = pkt(seq=42, pa=3210, avg=1500, xv=800, lock=False, temp=48.5, up=999)
    p = parse_packet(line)
    assert p == Packet(42, 3210, 1500, 800, False, 48.5, 999, "K2UA")
    bad = line[:6] + ("9" if line[6] != "9" else "8") + line[7:]
    assert parse_packet(bad) is None
    assert parse_packet("V:remtlm 0.1.0 base") is None
    assert parse_packet("$RT,1,2,3*00") is None


def test_no_temperature():
    assert parse_packet(pkt(temp=None)).temp_c is None


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs g++")
def test_firmware_packets_parse(tmp_path):
    exe = tmp_path / "tlm_proto_test"
    subprocess.run(["g++", "-std=c++17", "-I", str(REPO / "firmware/remtlm"),
                    str(REPO / "tests/firmware_sim/tlm_proto_test.cpp"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    lines = [l for l in out.stdout.splitlines() if l.startswith("$")]
    pk = [parse_packet(l) for l in lines]
    assert pk[0] == Packet(65535, 4987, 1234, 0, True, 45.2, 86400, "K2UA")
    assert pk[1].temp_c is None and pk[1].lock is False and pk[1].xv_pk_mv == 2500
    assert pk[2].temp_c == -10.5


def test_calibration():
    cal = Calibration([[4000, 10.0], [500, 0.5], [2000, 4.0]])   # unsorted on purpose
    assert cal.watts(0) == 0.5
    assert cal.watts(500) == 0.5
    assert cal.watts(1250) == pytest.approx(2.25)
    assert cal.watts(4000) == 10.0
    assert cal.watts(4500) == pytest.approx(11.5)           # extrapolates last segment
    assert Calibration([]).watts(1000) is None
    assert not Calibration([[1, 1]])


def test_link_stats_loss_and_reset():
    s = LinkStats()
    for i, seq in enumerate([10, 11, 13, 14]):                # 12 lost
        s.update(parse_packet(pkt(seq=seq, up=100 + i)), now=float(i))
    assert s.lost == 1 and s.received == 4
    assert s.loss_pct_5min() == pytest.approx(20.0)
    s.update(parse_packet(pkt(seq=0, up=1)), now=5.0)         # tower rebooted
    assert s.resets == 1 and s.lost == 1
    s.update(parse_packet(pkt(seq=65535, up=2)), now=6.0)
    s.update(parse_packet(pkt(seq=0, up=3)), now=7.0)          # wrap is not a loss
    assert s.lost == 1


@pytest.fixture
async def station_tlm(tmp_path):
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0,
                        heartbeat_timeout_s=2.0, log_file="",
                        pa_cal=[[0, 0], [5000, 10]], temp_warn_c=60,
                        tlm_stale_s=0.3, tlm_csv=str(tmp_path / "tlm.csv"))
    link, tlink = FakeLink(), FakeLink()
    svc = StationService(cfg, link, tlink)
    await svc.start()
    yield svc, link, tlink, tmp_path
    await svc.stop()


async def test_station_forwards_and_alerts(station_tlm):
    svc, link, tlink, tmp = station_tlm
    reader, writer, _ = await raw_connect(svc.port)
    await reader.readline()                                  # state

    async def next_of(t):
        while True:
            m = P.decode(await asyncio.wait_for(reader.readline(), 2))
            if m["t"] == t:
                return m

    tlink.inject(pkt(seq=1, pa=2500, avg=1000, temp=40.0))
    up = await next_of("alert")
    assert "link up" in up["msg"]
    m = await next_of("tlm")
    assert m["pa_pk_w"] == pytest.approx(5.0) and m["pa_avg_w"] == pytest.approx(2.0)

    tlink.inject(pkt(seq=2, lock=False, temp=61.0))
    alerts = [await next_of("alert"), await next_of("alert")]
    msgs = " ".join(a["msg"] for a in alerts)
    assert "LO UNLOCKED" in msgs and "HOT" in msgs

    # no packets -> stale alert from the 1 s housekeeping tick
    a = await next_of("alert")
    assert "lost" in a["msg"]

    rows = (tmp / "tlm.csv").read_text().splitlines()
    assert rows[0].startswith("time,seq") and len(rows) == 3
    writer.close()


async def test_client_tx_peak_summary(station_tlm):
    svc, slink, tlink, _ = station_tlm
    ccfg = ClientConfig(secret=SECRET, station_host="127.0.0.1", station_port=svc.port,
                        reconnect_s=0.1, heartbeat_s=0.1)
    out = NullOut()
    app = ClientApp(ccfg, FakeLink(), Console(out))
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)

    app.on_key("\x14")                                       # Ctrl-T: PTT on
    await wait_for(lambda: app.station_ptt)
    for i, mv in enumerate([1000, 4500, 3000]):
        tlink.inject(pkt(seq=10 + i, pa=mv, up=50 + i))
    await wait_for(lambda: app.tlm and app.tlm["seq"] == 12)
    app.on_key("\x14")                                       # PTT off
    await wait_for(lambda: "last TX: PA peak 9.0 W" in out.text)

    app.on_key("\x10")                                       # Ctrl-P
    await wait_for(lambda: "tower: PA peak" in out.text)
    app.quit.set()
    await asyncio.wait_for(task, 3)
