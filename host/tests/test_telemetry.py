import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_station_client import SECRET, NullOut, raw_connect, wait_for

from remkey import protocol as P
from remkey.client import ClientApp, Console
from remkey.config import ClientConfig, StationConfig
from remkey.serial_link import FakeLink
from remkey.station import StationService
from remkey.telemetry import (
    CableFit,
    Calibration,
    CsvLog,
    LinkStats,
    Packet,
    PowerPacket,
    ReplyAssembler,
    ReplyPart,
    format_packet,
    format_power,
    format_reply,
    gauge_match,
    loop_resistance,
    parse_any,
    parse_packet,
)

REPO = Path(__file__).resolve().parents[2]


def pkt(seq=1, pa=0, avg=0, xv=0, lock=True, temp=30.0, up=10, temp2=25.0):
    return format_packet(Packet(seq, pa, avg, xv, lock, temp, temp2, up, "K2UA"))


def test_roundtrip_and_checksum():
    line = pkt(seq=42, pa=3210, avg=1500, xv=800, lock=False, temp=48.5, up=999)
    p = parse_packet(line)
    assert p == Packet(42, 3210, 1500, 800, False, 48.5, 25.0, 999, "K2UA")
    bad = line[:6] + ("9" if line[6] != "9" else "8") + line[7:]
    assert parse_packet(bad) is None
    assert parse_packet("V:remtlm 0.1.0 base") is None
    assert parse_packet("$RT,1,2,3*00") is None


def test_no_temperature_and_lock_disabled():
    p = parse_packet(pkt(temp=None, temp2=None, lock=None))
    assert p.temp_c is None and p.temp2_c is None and p.lock is None


def test_reply_reassembly_and_loss():
    text = "MKU 10 G5|IF RX 028 MHz|" + "X" * 60
    lines = format_reply(5, "s", text)
    assert len(lines) == 2
    a = ReplyAssembler()
    assert a.add(parse_any(lines[0])) is None
    cmd, full = a.add(parse_any(lines[1]))
    assert cmd == "s" and full == text.replace("|", "\n")
    # lose part 1 of the next capture: still delivered, with a gap marker
    lines = format_reply(6, "s", text)
    cmd, full = a.add(parse_any(lines[1]))
    assert full.startswith("[...]")
    # text with no commas survives; call is split off the end
    rp = parse_any(format_reply(7, "v", "V1.3 2023")[0])
    assert isinstance(rp, ReplyPart) and rp.text == "V1.3 2023" and rp.call == "K2UA"


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs g++")
def test_firmware_packets_parse(tmp_path):
    exe = tmp_path / ("tlm_proto_test.exe" if sys.platform == "win32" else "tlm_proto_test")
    subprocess.run(["g++", "-std=c++17", "-I", str(REPO / "firmware/remtlm"),
                    str(REPO / "tests/firmware_sim/tlm_proto_test.cpp"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("$RT")]
    pk = [parse_packet(ln) for ln in lines]
    assert pk[0] == Packet(65535, 4987, 1234, 0, True, 45.2, 31.8, 86400, "K2UA")
    assert pk[1].temp_c is None and pk[1].temp2_c is None and pk[1].lock is False
    assert pk[1].xv_pk_mv == 2500
    assert pk[2].temp_c == -10.5 and pk[2].lock is None
    pw = [parse_any(ln) for ln in out.stdout.splitlines() if ln.startswith("$RP")]
    assert pw[0] == PowerPacket(42, 13.284, 12.851, 13.402, 4.012, 3.9, 6.104, True, "K2UA")
    assert (pw[1].i_avg, pw[1].i_min, pw[1].i_max) == (-0.512, -40.96, 40.959)
    a = ReplyAssembler()
    done = None
    for ln in out.stdout.splitlines():
        if ln.startswith("$RK"):
            done = a.add(parse_any(ln)) or done
    cmd, text = done
    assert cmd == "s"
    assert text.splitlines() == ["MKU 10 G5", "IF RX: 028 MHz IF TX: 028 MHz",
                                 "RF RX 10368 RF TX 10368", "D1 50 D2 50 D3 50 D4 50",
                                 "REF PLL locked"]


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
                        heartbeat_timeout_s=2.0, log_file="", ptt_hang_ms=200,
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

    tlink.inject(pkt(seq=2, lock=False, temp=61.0, temp2=56.0))
    alerts = [await next_of("alert") for _ in range(3)]
    msgs = " ".join(a["msg"] for a in alerts)
    assert "reference UNLOCKED" in msgs
    assert "PA heatsink HOT" in msgs and "transverter case HOT" in msgs

    # transverter reply relayed and queryable
    for ln in format_reply(1, "v", "MKU10G5 V2.1"):
        tlink.inject(ln)
    for ln in format_reply(2, "s", "D1 50 D2 50|REF PLL locked"):
        tlink.inject(ln)
    writer.write(P.encode({"t": "xvq"}))
    await writer.drain()
    while True:
        m = await next_of("xvstat")
        if m.get("query"):
            break
    assert m["text"] == "D1 50 D2 50\nREF PLL locked" and m["version"] == "MKU10G5 V2.1"

    # no packets -> stale alert from the 1 s housekeeping tick
    a = await next_of("alert")
    assert "lost" in a["msg"]

    rows = (tmp / "tlm.csv").read_text().splitlines()
    assert rows[0].startswith("time,seq") and len(rows) == 3
    assert rows[0].endswith("temp1_c,temp2_c,uptime_s,v_avg,v_min,v_max,i_avg,i_min,i_max")
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
    assert "PA heatsink 30.0 C" in out.text and "transverter case 25.0 C" in out.text

    for ln in format_reply(9, "s", "REF PLL locked"):
        tlink.inject(ln)
    app.on_key("\x0b")                                       # Ctrl-K
    await wait_for(lambda: "REF PLL locked" in out.text)
    app.quit.set()
    await asyncio.wait_for(task, 3)


# ----------------------------------------------------------------- supply monitor
def pwr(seq=1, v=13.3, vmin=None, vmax=None, i=4.0, imin=None, imax=None, ok=True):
    return format_power(PowerPacket(seq, v, vmin if vmin is not None else v, vmax if vmax is not None else v,
                                    i, imin if imin is not None else i, imax if imax is not None else i,
                                    ok, "K2UA"))


def test_power_packet_roundtrip():
    p = parse_any(pwr(seq=9, v=13.284, vmin=12.851, vmax=13.402, i=4.012, imin=3.9, imax=6.104))
    assert isinstance(p, PowerPacket) and p.ok and p.seq == 9
    assert (p.v_avg, p.v_min, p.v_max) == (13.284, 12.851, 13.402)
    assert (p.i_avg, p.i_min, p.i_max) == (4.012, 3.9, 6.104)
    assert parse_any(pwr(ok=False)).ok is False
    neg = parse_any(pwr(i=-0.5))
    assert neg.i_avg == -0.5                                  # shunt reversed: kept, not hidden


def test_wire_table_and_gauge_match():
    assert loop_resistance(10, 100) == pytest.approx(0.1998, abs=1e-4)
    assert loop_resistance(12, 100) == pytest.approx(0.3176, abs=1e-4)
    assert loop_resistance(10, 100, temp_c=40) == pytest.approx(0.1998 * 1.0786, rel=1e-3)
    assert gauge_match(0.205, 100)[0] == 10
    assert gauge_match(0.33, 100)[0] == 12
    assert "above #10" in gauge_match(0.24, 100)[2]
    assert "check connectors" in gauge_match(0.9, 100)[2]


def test_cable_fit_recovers_resistance_and_source():
    import random

    rnd = random.Random(1)
    fit = CableFit()
    for _ in range(19):
        fit.add(4.0, 13.3)
    assert fit.result() is None                               # too few points
    for _ in range(40):
        fit.add(4.0 + rnd.random() * 0.1, 13.3)
    assert fit.result() is None                               # not enough current spread
    fit = CableFit()
    for _ in range(200):
        i = 3.8 + rnd.random() * 2.6                          # RX ~3.8 A to TX ~6.4 A
        fit.add(i, 14.10 - 0.214 * i + rnd.gauss(0, 0.003))   # 3 mV noise (INA226 is better)
    r = fit.result()
    assert r["r_ohm"] == pytest.approx(0.214, abs=0.005)
    assert r["v_source"] == pytest.approx(14.10, abs=0.02)


def test_csv_rotates_old_header(tmp_path):
    path = tmp_path / "tlm.csv"
    path.write_text("time,seq,pa_pk_mv\n1,2,3\n")
    CsvLog(str(path))
    assert path.read_text().splitlines()[0].endswith("i_max")
    assert len(list(tmp_path.glob("tlm.*.csv"))) == 1


async def test_station_power_merge_alerts_and_fit(tmp_path):
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0, log_file="",
                        tlm_csv=str(tmp_path / "tlm.csv"), tlm_stale_s=60, base_supply_v=14.1,
                        v_min_alert=12.5, i_max_alert=7.0, i_scale=1.0)
    link, tlink = FakeLink(), FakeLink()
    svc = StationService(cfg, link, tlink)
    await svc.start()
    try:
        reader, writer, _ = await raw_connect(svc.port)
        await reader.readline()                               # state

        async def next_of(t, pred=lambda m: True):
            while True:
                m = P.decode(await asyncio.wait_for(reader.readline(), 2))
                if m["t"] == t and pred(m):
                    return m

        # $RP precedes the $RT with the same seq; CSV row carries both
        tlink.inject(pwr(seq=1, v=13.30, i=4.0))
        m = await next_of("pwr")
        assert m["drop_v"] == pytest.approx(0.80) and m["ok"]
        tlink.inject(pkt(seq=1, pa=0))
        row = (tmp_path / "tlm.csv").read_text().splitlines()[1].split(",")
        assert row[-6:] == ["13.300", "13.300", "13.300", "4.000", "4.000", "4.000"]

        # low voltage and high current alerts, then recovery
        assert "link up" in (await next_of("alert"))["msg"]   # from the first $RT
        tlink.inject(pwr(seq=2, v=12.9, vmin=12.3, i=5.0, imax=7.5))
        msgs = [(await next_of("alert"))["msg"] for _ in range(2)]
        assert any("supply LOW: 12.30 V" in x for x in msgs)
        assert any("current HIGH: 7.50 A" in x for x in msgs)
        tlink.inject(pwr(seq=3, v=13.3, i=4.0))
        msgs = [(await next_of("alert"))["msg"] for _ in range(2)]
        assert all("back to" in x for x in msgs)

        # INA226 stops answering
        tlink.inject(pwr(seq=4, ok=False))
        assert "not answering" in (await next_of("alert"))["msg"]
        tlink.inject(pwr(seq=5, v=13.3, i=4.0))
        assert "answering again" in (await next_of("alert"))["msg"]

        # enough RX/TX spread for the cable fit (#10: about 0.2 ohm)
        for k in range(30):
            i = 4.0 + (k % 5) * 0.6
            tlink.inject(pwr(seq=10 + k, v=14.1 - 0.2 * i, i=i))
        writer.write(P.encode({"t": "pwrq"}))
        await writer.drain()
        m = await next_of("pwr", lambda m: m.get("query"))
        assert m["fit"]["r_ohm"] == pytest.approx(0.2, abs=0.01)
        assert m["fit"]["awg"] == 10 and "consistent with #10" in m["fit"]["verdict"]
        writer.close()
    finally:
        await svc.stop()


async def test_client_supply_display_and_tx_summary(station_tlm):
    svc, slink, tlink, _ = station_tlm
    ccfg = ClientConfig(secret=SECRET, station_host="127.0.0.1", station_port=svc.port,
                        reconnect_s=0.1, heartbeat_s=0.1)
    out = NullOut()
    app = ClientApp(ccfg, FakeLink(), Console(out))
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)

    app.on_key("\x14")                                       # PTT on
    await wait_for(lambda: app.station_ptt)
    tlink.inject(pwr(seq=1, v=13.0, vmin=12.7, i=5.0, imax=6.2))
    tlink.inject(pwr(seq=2, v=13.1, vmin=12.8, i=4.8, imax=5.9))
    await wait_for(lambda: app.pwr and app.pwr["v_min"] == 12.8)
    app.on_key("\x14")                                       # PTT off
    await wait_for(lambda: "supply min 12.70 V, peak 6.20 A" in out.text)

    app.on_key("\x16")                                       # Ctrl-V
    await wait_for(lambda: "tower supply: 13.10 V" in out.text)
    await wait_for(lambda: "not enough data yet" in out.text)
    app.quit.set()
    await asyncio.wait_for(task, 3)


def test_powerstats_on_synthetic_log(tmp_path, capsys):
    import random

    from remkey import powerstats

    rnd = random.Random(7)
    path = tmp_path / "tlm.csv"
    log = CsvLog(str(path))
    for seq in range(400):
        tx = seq % 4 == 0
        i = (6.0 + rnd.random() * 0.4) if tx else (4.0 + rnd.random() * 0.1)
        v = 14.1 - 0.31 * i                                    # #12 run
        p = Packet(seq, 2500 if tx else 20, 1200 if tx else 10, 0, True, 30.0, 25.0, seq, "K2UA")
        log.write(p, None, None, PowerPacket(seq, v, v - 0.05, v + 0.02, i, i - 0.1, i + 0.3, True, "K2UA"))
    log.write(Packet(400, 0, 0, 0, True, 30.0, 25.0, 400, "K2UA"), None, None, None)   # no supply data

    assert powerstats.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "RECEIVE: 300 intervals" in out and "TRANSMIT: 100 intervals" in out
    assert "consistent with #12" in out
    groups = powerstats.summarise(list(__import__("csv").DictReader(path.open())), 150)
    s = powerstats.suggest(groups, 14.1)
    assert s["i_max_alert"] == 8.5                             # 6.7 A peak * 1.2 -> 8.04 -> 8.5
    assert s["v_max_alert"] == 14.3
    assert 3.1 <= s["i_min_alert"] <= 3.3
    assert s["v_min_alert"] < 12.0 and "below the MKU" in out  # 12.07 V lowest - 0.3
