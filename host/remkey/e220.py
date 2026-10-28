"""Read or program an Ebyte E220-900T22D LoRa module over a USB serial adapter.

    python -m remkey.e220 --port /dev/cu.usbserial-XXXX            read and decode
    python -m remkey.e220 --port /dev/cu.usbserial-XXXX --write    program remtlm settings

The module must be in configuration mode: M0 and M1 both tied HIGH (3.3 V) before
power-up. Configuration always runs at 9600 8N1, whatever UART speed is stored.
--write stores the settings remtlm uses (channel 77 = 927.125 MHz, 9.6 kbps air
rate, 17 dBm, transparent mode, no encryption) in the module's flash, then reads
them back to verify. Nothing is transmitted.

The remtlm firmware writes the same settings itself at boot, so this tool is for
checking modules on the bench, not a required step.
"""

from __future__ import annotations

import argparse
import sys
import time

READ = bytes([0xC1, 0x00, 0x08])        # read registers 00h-07h
WRITE_SAVE = 0xC0                        # write registers, kept through power-off
REPLY = 0xC1

UART_BAUD = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
PARITY = ["8N1", "8O1", "8E1", "8N1"]
AIR_KBPS = [2.4, 2.4, 2.4, 4.8, 9.6, 19.2, 38.4, 62.5]
POWER_DBM = [22, 17, 13, 10]             # E220-xxxT22 family
SUBPACKET = [200, 128, 64, 32]

# remtlm's settings (must match firmware/remtlm/config.h)
REMTLM = {"addh": 0, "addl": 0, "channel": 77, "air_kbps": 9.6, "power_dbm": 17}


def encode(addh: int, addl: int, channel: int, air_kbps: float, power_dbm: int) -> bytes:
    """The 8 register bytes (00h-07h) for transparent mode at 9600 8N1."""
    if not 0 <= channel <= 80:
        raise ValueError("channel must be 0-80 (850.125-930.125 MHz)")
    air = {2.4: 0b010, 4.8: 0b011, 9.6: 0b100, 19.2: 0b101, 38.4: 0b110, 62.5: 0b111}[air_kbps]
    power = POWER_DBM.index(power_dbm)
    sped = (0b011 << 5) | (0b00 << 3) | air          # 9600 baud, 8N1, air rate
    option = (0b00 << 6) | (0 << 5) | power           # 200-byte packets, no ambient RSSI
    tmode = 0b011                                     # no RSSI byte, transparent, LBT off, WOR 2 s
    return bytes([addh, addl, sped, option, channel, tmode, 0, 0])


def decode(regs: bytes) -> dict:
    sped, option, chan, tmode = regs[2], regs[3], regs[4], regs[5]
    return {
        "address": f"{regs[0]:02X}{regs[1]:02X}",
        "uart": f"{UART_BAUD[sped >> 5]} {PARITY[(sped >> 3) & 3]}",
        "air_kbps": AIR_KBPS[sped & 7],
        "subpacket_bytes": SUBPACKET[option >> 6],
        "ambient_rssi": bool(option & 0x20),
        "power_dbm": POWER_DBM[option & 3],
        "channel": chan,
        "freq_mhz": 850.125 + chan,
        "rssi_byte": bool(tmode & 0x80),
        "fixed_mode": bool(tmode & 0x40),
        "lbt": bool(tmode & 0x10),
        "wor_ms": 500 * ((tmode & 7) + 1),
    }


def transact(ser, cmd: bytes) -> bytes:
    ser.reset_input_buffer()
    ser.write(cmd)
    ser.flush()
    reply = ser.read(11)
    if len(reply) != 11 or reply[0] != REPLY or reply[1] != 0x00 or reply[2] != 0x08:
        hexs = reply.hex(" ") if reply else "nothing"
        raise RuntimeError(
            f"unexpected reply ({hexs}). Check: M0 and M1 tied HIGH before power-up, "
            "TX/RX crossed (adapter TX -> module RXD), adapter logic set to 3.3 V, common GND.")
    return reply[3:]


def show(regs: bytes) -> None:
    d = decode(regs)
    print(f"  registers  {regs[:6].hex(' ')}")
    print(f"  channel    {d['channel']}  ({d['freq_mhz']:.3f} MHz)")
    print(f"  air rate   {d['air_kbps']} kbps   power {d['power_dbm']} dBm   UART {d['uart']}")
    print(f"  address    {d['address']}   packet {d['subpacket_bytes']} B   "
          f"{'fixed' if d['fixed_mode'] else 'transparent'}   LBT {'on' if d['lbt'] else 'off'}   "
          f"RSSI byte {'on' if d['rssi_byte'] else 'off'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read or program an E220-900T22D (M0 = M1 = HIGH)")
    ap.add_argument("--port", required=True, help="USB serial adapter, e.g. /dev/cu.usbserial-A10K1234")
    ap.add_argument("--write", action="store_true", help="store remtlm's settings in the module")
    ap.add_argument("--channel", type=int, default=REMTLM["channel"], help="0-80; MHz = 850.125 + channel")
    ap.add_argument("--power", type=int, default=REMTLM["power_dbm"], choices=POWER_DBM, help="dBm")
    ap.add_argument("--air", type=float, default=REMTLM["air_kbps"],
                    choices=[2.4, 4.8, 9.6, 19.2, 38.4, 62.5], help="air data rate, kbps")
    args = ap.parse_args(argv)

    import serial

    with serial.Serial(args.port, 9600, timeout=1.0) as ser:
        time.sleep(0.3)                      # let the module settle after the port opens
        try:
            before = transact(ser, READ)
            print("current settings:")
            show(before)
            if not args.write:
                return 0
            want = encode(REMTLM["addh"], REMTLM["addl"], args.channel, args.air, args.power)
            if before == want[:6] + before[6:]:
                print("already set: nothing written")
                return 0
            echo = transact(ser, bytes([WRITE_SAVE, 0x00, 0x08]) + want)
            time.sleep(0.1)
            after = transact(ser, READ)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if after[:6] != want[:6] or echo[:6] != want[:6]:
        print("error: read-back does not match what was written:", file=sys.stderr)
        show(after)
        return 1
    print("written and verified:")
    show(after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
