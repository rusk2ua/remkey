"""Web dashboard: access checks, history, API and buttons (no browser needed)."""

import asyncio
import json
import time

import pytest

from remkey.config import StationConfig
from remkey.dashboard import Dashboard, History, host_allowed, parse_allow, peer_allowed
from remkey.serial_link import FakeLink
from remkey.station import StationService
from remkey.telemetry import CsvLog, Packet, PowerPacket, format_packet, format_supply

SECRET = "test-secret-0123456789"


def box(seq=1, v=14.0, i=1.0, temp=21.5, up=100, ok=True):
    return format_supply(PowerPacket(seq, v, v - 0.02, v + 0.02, i, i, i + 0.5, ok, "K2UA", "base", temp, up))


def tower(seq=1, pa=0, lock=True, t1=30.0, t2=25.0, up=10):
    return format_packet(Packet(seq, pa, pa // 2, 0, lock, t1, t2, up, "K2UA"))


# ----------------------------------------------------------------- access checks
@pytest.mark.parametrize("host,ok", [
    ("192.168.1.20:8080", True), ("127.0.0.1", True), ("[::1]:8080", True), ("localhost:8080", True),
    ("shackpc:8080", True), ("SHACK-PC", True), ("shackpc.local", True), ("shackpc.lan:8080", True),
    ("shackpc.tail1234.ts.net", True), ("evil.example.com", False), ("example.com:8080", False),
    ("shackpc.ts.net.evil.com", False), ("", False), (None, False), ("bad_name", False),
])
def test_host_allowed(host, ok):
    assert host_allowed(host, []) is ok


def test_host_allowed_extra_names():
    assert host_allowed("radio.k2ua.net:8080", ["radio.k2ua.net"])
    assert not host_allowed("radio.k2ua.net", [])


@pytest.mark.parametrize("peer,ok", [
    ("127.0.0.1", True), ("192.168.1.7", True), ("10.0.0.2", True), ("100.101.102.103", True),
    ("::ffff:192.168.1.7", True), ("fd7a:115c:a1e0::5", True), ("::1", True),
    ("8.8.8.8", False), ("2001:db8::1", False), ("", False), ("not-an-ip", False),
])
def test_peer_allowed_defaults(peer, ok):
    from remkey.dashboard import DEFAULT_ALLOW
    assert peer_allowed(peer, parse_allow(DEFAULT_ALLOW)) is ok


def test_parse_allow_skips_bad_entries():
    nets = parse_allow(["192.168.1.0/24", "nonsense"])
    assert len(nets) == 1 and peer_allowed("192.168.1.9", nets) and not peer_allowed("192.168.2.9", nets)


# ----------------------------------------------------------------- history
def test_history_bins_and_ages_out():
    h = History(hours=1)
    now = 1_000_000.0
    for k in range(600):                                   # one point per second, 10 minutes
        t = now - 600 + k
        h.add_supply(t, PowerPacket(k, 14.0, 13.9 - (k == 300), 14.1, 1.0 + (k == 450) * 5, 1.0, 1.0,
                                    True, "K2UA", "base", 20.0, k))
    q = h.query(minutes=10, points=60, now=now)
    s = q["supply"]
    assert 55 <= len(s["t"]) <= 60
    assert min(s["v_min"]) == pytest.approx(12.9)          # min survives binning
    assert max(s["i_avg"]) < 6                              # averages are averaged...
    assert s["v_avg"][0] == pytest.approx(14.0)
    h.add_supply(now + 7200, PowerPacket(1, 14, 14, 14, 1, 1, 1, True, "K2UA", "base", None, 1))
    assert len(h.supply) == 1                               # older than an hour: gone


def test_history_records_dead_ina226_as_gap():
    h = History()
    h.add_supply(time.time(), PowerPacket(1, 0, 0, 0, 0, 0, 0, False, "K2UA", "base", 22.0, 1))
    s = h.query(5, 20)["supply"]
    assert s["v_avg"] == [None] and s["temp"] == [22.0]


def test_history_seeds_from_csv(tmp_path):
    path = tmp_path / "tlm.csv"
    log = CsvLog(str(path))
    for seq in range(5):
        p = Packet(seq, 3000, 1500, 100, True, 31.0, 26.0, seq, "K2UA")
        sup = PowerPacket(seq, 14.0, 13.9, 14.1, 2.0, 1.9, 2.5, True, "K2UA", "base", 19.5, seq)
        top = PowerPacket(seq, 13.2, 13.1, 13.3, 2.0, 1.9, 2.5, True, "K2UA")
        log.write(p, 8.0, 4.0, sup, top)
    alone = PowerPacket(9, 14.0, 13.9, 14.1, 1.0, 1.0, 1.0, True, "K2UA", "base", 19.0, 9)
    log.write(None, None, None, alone)
    h = History()
    assert h.seed_from_csv(str(path)) == 6
    assert len(h.tower) == 5 and len(h.supply) == 6 and len(h.top) == 5
    assert h.tower[0][1] == 8.0 and h.pa_unit == "W"
    assert h.supply[-1][6] == 19.0 and h.top[0][1] == 13.2
    assert History().seed_from_csv(str(tmp_path / "missing.csv")) == 0


# ----------------------------------------------------------------- the server
async def http(port, method, path, body=None, headers=None, host="127.0.0.1"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    h = {"Host": f"{host}:{port}", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else b""
    if data:
        h["Content-Type"] = "application/json"
        h["Content-Length"] = str(len(data))
    req = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
    writer.write(req.encode() + data)
    await writer.drain()
    try:
        raw = await asyncio.wait_for(reader.read(), 5)
    except ConnectionResetError:
        raw = b""
    writer.close()
    if not raw:
        return None, {}, b""
    head, _, payload = raw.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    status = int(lines[0].split()[1])
    hdrs = {k.lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
    return status, hdrs, payload


@pytest.fixture
async def dash(tmp_path):
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0, log_file="",
                        tlm_csv=str(tmp_path / "tlm.csv"), tlm_stale_s=60, v_min_alert=13.5,
                        pa_cal=[[0, 0], [4000, 10]])
    tlink = FakeLink()
    svc = StationService(cfg, FakeLink(), tlink)
    await svc.start()
    d = Dashboard(svc, "127.0.0.1", 0, [], [])
    await d.start()
    svc.dashboard = d
    svc.tlm.on_alert = d.push_alert
    try:
        yield svc, tlink, d
    finally:
        await d.stop()
        await svc.stop()


async def test_page_and_headers(dash):
    _, _, d = dash
    status, hdrs, body = await http(d.port, "GET", "/")
    assert status == 200 and b"Tower telemetry" in body
    assert "frame-ancestors 'none'" in hdrs["content-security-policy"]
    assert hdrs["x-frame-options"] == "DENY"
    assert (await http(d.port, "GET", "/nope"))[0] == 404
    assert (await http(d.port, "POST", "/"))[0] == 405


async def test_state_follows_packets(dash):
    svc, tlink, d = dash
    status, _, body = await http(d.port, "GET", "/api/state")
    st = json.loads(body)
    assert status == 200 and st["telemetry"] and st["supply"] is None and st["tower"] is None
    tlink.inject(box(seq=1, v=14.05, i=1.2, temp=22.0))
    tlink.inject(tower(seq=7, pa=2000, lock=False))
    await asyncio.sleep(0.05)
    st = json.loads((await http(d.port, "GET", "/api/state"))[2])
    assert st["supply"]["v_avg"] == pytest.approx(14.05) and st["supply"]["temp_c"] == 22.0
    assert st["tower"]["pa_pk_w"] == pytest.approx(5.0) and st["tower"]["lock"] is False
    assert st["extremes"]["v"] == [pytest.approx(14.03), pytest.approx(14.07)]
    msgs = [a["msg"] for a in st["alerts"]]
    assert "tower-base supply box link up" in msgs and "10 MHz reference UNLOCKED" in msgs
    assert st["station"]["ptt"] is False and st["limits"]["v_min_alert"] == 13.5
    hist = json.loads((await http(d.port, "GET", "/api/history?minutes=5&points=50"))[2])
    assert hist["supply"]["v_avg"] == [pytest.approx(14.05)]
    assert hist["tower"]["pa_pk"] == [pytest.approx(5.0)]
    assert hist["tower"]["lock"] == [0] and hist["pa_unit"] == "W"


async def test_foreign_host_and_cross_site_buttons_refused(dash):
    _, _, d = dash
    assert (await http(d.port, "GET", "/api/state", host="evil.example.com"))[0] == 421
    # no custom header: a plain cross-site form/fetch can't press buttons
    assert (await http(d.port, "POST", "/api/action", {"action": "clear_alerts"}))[0] == 403
    # custom header but another site's Origin
    st, _, _ = await http(d.port, "POST", "/api/action", {"action": "clear_alerts"},
                          {"X-Remkey-Dash": "1", "Origin": "http://evil.example.com"})
    assert st == 403
    st, _, _ = await http(d.port, "POST", "/api/action", {"action": "key_the_radio"}, {"X-Remkey-Dash": "1"})
    assert st == 400


async def test_buttons(dash):
    svc, tlink, d = dash
    tlink.inject(box(seq=1, v=14.0, i=6.0))
    await asyncio.sleep(0.05)
    hdr = {"X-Remkey-Dash": "1", "Origin": f"http://127.0.0.1:{d.port}"}
    mark = {"action": "mark", "text": "TX test\n<b>1</b>"}
    st, _, body = await http(d.port, "POST", "/api/action", mark, hdr)
    assert st == 200
    alerts = json.loads(body)["state"]["alerts"]
    assert alerts[-1]["level"] == "info" and alerts[-1]["msg"] == "MARK: TX test<b>1</b>"
    assert (await http(d.port, "POST", "/api/action", {"action": "mark", "text": "  "}, hdr))[0] == 400
    st, _, body = await http(d.port, "POST", "/api/action", {"action": "reset_stats"}, hdr)
    s = json.loads(body)["state"]
    assert "v" not in s["extremes"] and s["supply"]["received"] == 0
    st, _, body = await http(d.port, "POST", "/api/action", {"action": "clear_alerts"}, hdr)
    assert json.loads(body)["state"]["alerts"] == []
    # nothing a button does reaches the keyer
    assert not any(c.startswith(("P:", "T:", "U:")) for c in svc.link.sent)


async def test_event_stream(dash):
    svc, tlink, d = dash
    reader, writer = await asyncio.open_connection("127.0.0.1", d.port)
    writer.write(f"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{d.port}\r\n\r\n".encode())
    await writer.drain()
    buf = b""
    while b"event: state" not in buf:
        buf += await asyncio.wait_for(reader.read(4096), 3)
    assert b"text/event-stream" in buf
    tlink.inject(box(seq=1))
    while b"event: alert" not in buf:
        buf += await asyncio.wait_for(reader.read(4096), 3)
    assert b"supply box link up" in buf
    writer.close()


async def test_refuses_peers_outside_allow_list(tmp_path):
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0, log_file="", tlm_csv="")
    svc = StationService(cfg, FakeLink(), FakeLink())
    await svc.start()
    d = Dashboard(svc, "127.0.0.1", 0, ["192.168.0.0/16"], [])
    await d.start()
    try:
        status, _, _ = await http(d.port, "GET", "/api/state")
        assert status is None                            # dropped without a reply
    finally:
        await d.stop()
        await svc.stop()


async def test_station_starts_dashboard_and_survives_port_in_use(tmp_path):
    blocker = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = blocker.sockets[0].getsockname()[1]
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0, log_file="", tlm_csv="",
                        dash_port=port, dash_host="127.0.0.1")
    svc = StationService(cfg, FakeLink(), FakeLink())
    await svc.start()                                    # must not raise: keying comes first
    try:
        assert svc.dashboard is None and svc.server is not None
    finally:
        await svc.stop()
        blocker.close()
