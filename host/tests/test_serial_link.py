"""SerialLink reports a lost port, re-opens it, and reports it back."""

import asyncio

from remkey.serial_link import BACK, LOST, SerialLink


class FakePort:
    def __init__(self, ports, name):
        self.ports, self.name = ports, name
        self.rx = []
        self.tx = b""
        self.dead = False

    def reset_input_buffer(self):
        pass

    def read(self, n):
        if self.dead:
            raise OSError("device disconnected")
        return self.rx.pop(0) if self.rx else b""

    def write(self, data):
        if self.dead:
            raise OSError("device disconnected")
        self.tx += data

    def close(self):
        self.dead = True


async def test_lost_and_back():
    plugged = {"yes": True}
    opened = []

    def opener(port, baud, timeout):
        if not plugged["yes"]:
            raise OSError("no such port")
        p = FakePort(None, port)
        opened.append(p)
        return p

    lines = []
    link = SerialLink("COM9", loop=asyncio.get_running_loop(), opener=opener,
                      retry_s=0.05, boot_s=0)
    link.set_handler(lines.append)
    opened[0].rx.append(b"V:remkey 0.4.1 station\n")

    async def until(cond):
        for _ in range(200):
            if cond():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(lines)

    await until(lambda: "V:remkey 0.4.1 station" in lines)
    plugged["yes"] = False
    opened[0].dead = True
    await until(lambda: LOST in lines)
    link.send("H")                        # dropped quietly while unplugged
    assert not link.up
    await asyncio.sleep(0.15)
    assert len(opened) == 1               # retries failed
    plugged["yes"] = True
    await until(lambda: BACK in lines)
    assert lines.count(LOST) == 1 and link.up
    link.send("P:0")
    assert opened[-1].tx == b"P:0\n"
    link.close()
