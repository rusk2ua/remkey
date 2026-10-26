"""End-to-end tests: real TCP on localhost, fake keyers on both ends."""

import asyncio

import pytest

from remkey import protocol as P
from remkey.client import ClientApp, Console
from remkey.config import ClientConfig, StationConfig
from remkey.serial_link import FakeLink
from remkey.station import StationService

SECRET = "test-secret-0123456789"


class NullOut:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


async def wait_for(cond, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.01)


@pytest.fixture
async def station():
    cfg = StationConfig(secret=SECRET, listen_host="127.0.0.1", listen_port=0,
                        heartbeat_timeout_s=0.5, log_file="", ptt_hang_ms=300)
    link = FakeLink()
    svc = StationService(cfg, link)
    await svc.start()
    yield svc, link
    await svc.stop()


async def raw_connect(port, secret=SECRET):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hello = P.decode(await reader.readline())
    assert hello["t"] == "hello"
    writer.write(P.encode({"t": "auth", "mac": P.compute_mac(secret, hello["nonce"])}))
    await writer.drain()
    reply = P.decode(await reader.readline())
    return reader, writer, reply


async def test_bad_secret_rejected(station):
    svc, link = station
    reader, writer, reply = await raw_connect(svc.port, secret="wrong-secret-xxxxxxxx")
    assert reply["t"] == "err"
    assert await reader.read() == b""     # closed
    assert svc.session is None
    writer.close()


async def test_ptt_cw_and_disconnect_safety(station):
    svc, link = station
    reader, writer, reply = await raw_connect(svc.port)
    assert reply["t"] == "ok"
    assert P.decode(await reader.readline())["t"] == "state"

    writer.write(P.encode({"t": "ptt", "on": True}))
    writer.write(P.encode({"t": "wpm", "v": 18}))
    writer.write(P.encode({"t": "cw", "text": "cq <sk>"}))
    await writer.drain()
    await wait_for(lambda: "T:CQ {...-.-}" in link.sent)
    assert "P:1" in link.sent
    assert "W:20" in link.sent            # 18 + wpm_offset
    assert svc.ptt

    link.sent.clear()
    writer.close()
    await wait_for(lambda: svc.session is None)
    assert link.sent[-1] == "O"                # safety stop: immediate, no release hang
    assert not svc.ptt


async def test_heartbeat_loss_drops_ptt(station):
    svc, link = station
    reader, writer, reply = await raw_connect(svc.port)
    writer.write(P.encode({"t": "ptt", "on": True}))
    await writer.drain()
    await wait_for(lambda: svc.ptt)
    # go silent; timeout is 0.5 s in the fixture
    await wait_for(lambda: svc.session is None, timeout=2.0)
    assert not svc.ptt
    assert link.sent[-1] == "O"
    writer.close()


async def test_second_client_rejected(station):
    svc, link = station
    r1, w1, reply1 = await raw_connect(svc.port)
    assert reply1["t"] == "ok"
    r2, w2 = await asyncio.open_connection("127.0.0.1", svc.port)
    msg = P.decode(await r2.readline())
    assert msg["t"] == "err" and "busy" in msg["msg"]
    w1.close()
    w2.close()


async def test_tune_requires_ptt_and_is_capped(station):
    svc, link = station
    svc.cfg.max_tune_ms = 1000
    reader, writer, _ = await raw_connect(svc.port)
    await reader.readline()  # state
    writer.write(P.encode({"t": "tune", "ms": 5000}))
    await writer.drain()
    msg = P.decode(await reader.readline())
    assert msg["t"] == "log" and "PTT" in msg["msg"]
    writer.write(P.encode({"t": "ptt", "on": True}))
    writer.write(P.encode({"t": "tune", "ms": 5000}))
    await writer.drain()
    await wait_for(lambda: "U:1000" in link.sent)
    writer.close()


async def test_keyer_watchdog_reported(station):
    svc, link = station
    reader, writer, _ = await raw_connect(svc.port)
    await reader.readline()  # state
    link.inject("!:WDOG")
    msg = P.decode(await reader.readline())
    assert msg["t"] == "wdog"
    writer.close()


async def test_full_client_paddle_and_button(station):
    svc, slink = station
    ccfg = ClientConfig(secret=SECRET, station_host="127.0.0.1", station_port=svc.port,
                        reconnect_s=0.1, heartbeat_s=0.1)
    clink = FakeLink()
    out = NullOut()
    app = ClientApp(ccfg, clink, Console(out))
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)

    # paddle characters and a word space from the travel keyer
    for line in ["K:C", "K:Q", "K: ", "K:{...-.-}"]:
        clink.inject(line)
    await wait_for(lambda: "T:{...-.-}" in slink.sent)
    t_lines = [s for s in slink.sent if s.startswith("T:")]
    assert t_lines == ["T:C", "T:Q", "T: ", "T:{...-.-}"]
    assert "CQ {...-.-}" in out.text

    # PTT button -> station PTT on -> LED on the travel keyer
    clink.inject("B:P")
    await wait_for(lambda: app.station_ptt)
    assert "P:1" in slink.sent
    await wait_for(lambda: "L:1" in clink.sent)

    # typed keys: prosign buffered until '>' and echoed on local sidetone
    for ch in "<SK>":
        app.on_key(ch)
    await wait_for(lambda: slink.sent.count("T:{...-.-}") == 2)
    assert "T:{...-.-}" in clink.sent

    # speed change from keyboard
    app.on_key("\x06")  # Ctrl-F
    await wait_for(lambda: "W:21" in slink.sent)  # 19 + offset
    assert "W:19" in clink.sent

    # quit: client drops PTT on the way out
    app.on_key("\x11")  # Ctrl-Q
    await asyncio.wait_for(task, 3)
    await wait_for(lambda: not svc.ptt)
    await wait_for(lambda: svc.session is None)


async def test_client_reconnects_and_drops_paddle_when_offline(station):
    svc, slink = station
    ccfg = ClientConfig(secret=SECRET, station_host="127.0.0.1", station_port=svc.port,
                        reconnect_s=0.1, heartbeat_s=0.1)
    clink = FakeLink()
    out = NullOut()
    app = ClientApp(ccfg, clink, Console(out))
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)

    # kill the session from the station side
    svc.session.writer.close()
    await wait_for(lambda: not app.connected)
    clink.inject("K:E")
    assert "dropped" in out.text
    await wait_for(lambda: app.connected, timeout=3)   # reconnected
    app.quit.set()
    await asyncio.wait_for(task, 3)


# ----------------------------------------------------------------- graceful PTT release
async def next_msg(reader, t, pred=lambda m: True):
    while True:
        m = P.decode(await asyncio.wait_for(reader.readline(), 3))
        if m["t"] == t and pred(m):
            return m


async def test_ptt_off_is_graceful_and_reported_by_nano(station):
    svc, link = station
    assert link.sent[:3] == ["G:1", "J:300", "O"]
    reader, writer, _ = await raw_connect(svc.port)
    await next_msg(reader, "state")
    writer.write(P.encode({"t": "ptt", "on": True}))
    await writer.drain()
    await next_msg(reader, "state", lambda m: m["ptt"])
    writer.write(P.encode({"t": "cw", "text": "TU"}))
    writer.write(P.encode({"t": "ptt", "on": False}))
    await writer.drain()
    m = await next_msg(reader, "state", lambda m: m["releasing"])
    assert m["ptt"] is True and m["hang_ms"] == 300
    assert "X" not in link.sent and "O" not in link.sent[3:]     # nothing flushed
    assert link.sent.index("T:TU") < link.sent.index("P:0")       # CW queued ahead of release
    t0 = asyncio.get_running_loop().time()
    m = await next_msg(reader, "state", lambda m: not m["ptt"])   # Nano reported P:0
    assert asyncio.get_running_loop().time() - t0 >= 0.25
    assert m["releasing"] is False and not svc.ptt
    # a second PTT-off while already off sends nothing to the Nano
    n = len(link.sent)
    writer.write(P.encode({"t": "ptt", "on": False}))
    await writer.drain()
    await next_msg(reader, "state")
    assert [x for x in link.sent[n:] if x != "H"] == []
    writer.close()


async def test_ptt_on_during_release_keeps_transmitting(station):
    svc, link = station
    svc.cfg.heartbeat_timeout_s = 3.0                         # this test sends no heartbeats
    reader, writer, _ = await raw_connect(svc.port)
    writer.write(P.encode({"t": "ptt", "on": True}))
    writer.write(P.encode({"t": "ptt", "on": False}))
    writer.write(P.encode({"t": "ptt", "on": True}))
    await writer.drain()
    await asyncio.sleep(0.6)                                       # past the 300 ms hang
    assert svc.ptt and not svc.releasing and link.ptt
    writer.close()


async def test_abort_during_release_is_immediate(station):
    svc, link = station
    svc.cfg.heartbeat_timeout_s = 3.0
    reader, writer, _ = await raw_connect(svc.port)
    writer.write(P.encode({"t": "ptt", "on": True}))
    writer.write(P.encode({"t": "ptt", "on": False}))
    await writer.drain()
    await wait_for(lambda: svc.releasing)
    writer.write(P.encode({"t": "abort"}))
    await writer.drain()
    await wait_for(lambda: not svc.ptt)
    assert link.sent[-1] == "O" or "O" in link.sent[-3:]
    writer.close()


async def test_client_shows_release_and_quit_waits_for_it(station):
    svc, slink = station
    svc.cfg.heartbeat_timeout_s = 3.0
    ccfg = ClientConfig(secret=SECRET, station_host="127.0.0.1", station_port=svc.port,
                        reconnect_s=0.1, heartbeat_s=0.1)
    out = NullOut()
    app = ClientApp(ccfg, FakeLink(), Console(out))
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)

    app.on_key("\x14")                                       # PTT on
    await wait_for(lambda: app.station_ptt)
    app.on_key("\x14")                                       # PTT off -> releasing
    await wait_for(lambda: app.releasing)
    assert "STATION PTT releasing: finishing queued CW, then 0.3 s" in out.text
    app.on_key("\x14")                                       # pressed again: stay on
    await wait_for(lambda: not app.releasing)
    await asyncio.sleep(0.5)
    assert app.station_ptt and svc.ptt

    # quit with PTT on: the client asks for a release and waits for it, so the
    # station is never cut off by the disconnect safety stop
    app.on_key("\x11")
    await asyncio.wait_for(task, 3)
    assert "waiting for the station to finish sending" in out.text
    assert "O" not in slink.sent[3:]                         # no immediate drop happened
    assert not svc.ptt


def _latching_client(svc, ptt_switch="latching"):
    ccfg = ClientConfig(secret=SECRET, station_host="127.0.0.1", station_port=svc.port,
                        reconnect_s=0.1, heartbeat_s=0.1, ptt_switch=ptt_switch)
    clink = FakeLink()
    out = NullOut()
    return ClientApp(ccfg, clink, Console(out)), clink, out


async def test_latching_switch_follows_and_rearms_after_safety_drop(station):
    svc, slink = station
    app, clink, out = _latching_client(svc)
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)

    clink.inject("B:P")                                   # switch ON
    await wait_for(lambda: app.station_ptt)
    clink.inject("B:R")                                   # switch off -> graceful release
    await wait_for(lambda: app.releasing)
    await wait_for(lambda: not app.station_ptt)

    clink.inject("B:P")                                   # ON again
    await wait_for(lambda: app.station_ptt and not app.releasing)
    slink.inject("!:WDOG")                                # safety stop at the station
    await wait_for(lambda: not app.station_ptt)
    assert "PTT switch is still ON" in out.text
    n = len([s for s in slink.sent if s.startswith("P:")])
    clink.inject("B:R")                                   # switch off: nothing to do
    await asyncio.sleep(0.2)
    assert len([s for s in slink.sent if s.startswith("P:")]) == n
    clink.inject("B:P")                                   # switch on: transmits again
    await wait_for(lambda: app.station_ptt)

    clink.inject("B:R")
    await wait_for(lambda: not app.station_ptt)
    app.on_key("\x11")
    await asyncio.wait_for(task, 3)


async def test_latching_switch_on_at_boot_does_not_key(station):
    svc, slink = station
    app, clink, out = _latching_client(svc)
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)
    clink.inject("B:H")
    await asyncio.sleep(0.3)
    assert not app.station_ptt and "P:1" not in slink.sent
    assert "PTT switch is ON at startup" in out.text
    app.on_key("\x11")
    await asyncio.wait_for(task, 3)


async def test_momentary_button_ignores_release_edge(station):
    svc, slink = station
    app, clink, out = _latching_client(svc, ptt_switch="momentary")
    task = asyncio.create_task(app.run())
    await wait_for(lambda: app.connected)
    clink.inject("B:P")
    clink.inject("B:R")
    await wait_for(lambda: app.station_ptt)
    await asyncio.sleep(0.5)                              # past the 300 ms hang
    assert app.station_ptt and not app.releasing
    clink.inject("B:P")                                   # second press toggles off
    await wait_for(lambda: not app.station_ptt)
    app.on_key("\x11")
    await asyncio.wait_for(task, 3)


def test_ptt_switch_config_validated(tmp_path):
    from remkey.config import load_client
    p = tmp_path / "c.toml"
    p.write_text(f'secret = "{SECRET}"\nptt_switch = "toggle"\n')
    with pytest.raises(ValueError, match="ptt_switch"):
        load_client(p)
    p.write_text(f'secret = "{SECRET}"\nptt_switch = "latching"\n')
    assert load_client(p).ptt_switch == "latching"
