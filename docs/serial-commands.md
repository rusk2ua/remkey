# Sending CW from the Serial Monitor

A quick reference for keying a remkey Nano by hand, with no station service
running. It's useful on the bench (Phases 1 and 2 of the [build plan](build-plan.md)).
The full serial protocol is in the header comment of
[`firmware/remkey/remkey.ino`](../firmware/remkey/remkey.ino).

**Serial Monitor settings:** 115200 baud, line ending **Newline**. Commands are
case-sensitive: type them in uppercase. A lowercase command such as `t:cq` returns `E:CMD`.

## Send CW: the `T:` command

This works on either Nano:
- **Station:** keys the KEY optocoupler and flashes the on-board LED.
- **Client:** sidetone and LED only. The client never drives the radio.

| Command | What it sends |
|---|---|
| `T:CQ DE K2UA` | Text. Spaces become word gaps. Lowercase text is fine: `T:cq` sends CQ. |
| `T:TU {...-.-}` | Braces send a raw element pattern (up to 10 elements): here TU, then SK. |
| `T:5NN` | Anything in the Morse table: letters, digits and `. , ? / = + - ( ) ' : " @ & ! ;` |

A character that isn't in the table is skipped silently. Text that overflows the
queue returns `E:QFULL`. When the queue has been sent, the Nano prints `D`.

## Station Nano: turn the watchdog off first

The station Nano's watchdog is on by default. If PTT is on or text is queued and the
Nano hears nothing on the serial port for 3 s, it stops sending, drops PTT and prints
`!:WDOG`. The station service sends a heartbeat every second, but the Serial Monitor
sends nothing between your lines. So by hand, anything that takes more than 3 s to
send gets cut off.

- `G:0` turns the watchdog off until the Nano is reset or reconnected.
- `G:1` turns it back on.

The station service never sends `G:0`, so the watchdog is always on in normal use.
The client Nano's watchdog is off by default.

## Useful companions

| Command | What it does |
|---|---|
| `W:20` | Sets the speed in WPM (5–50) before sending. |
| `X` | Stops sending mid-message. |
| `?` | Status line (`S:...`): version, role, speed, PTT, queue length. |
| `V` | Version line (`V:remkey <version> client` or `station`), also printed at boot. |
| `P:1` / `P:0` | Station: PTT on; PTT off after the queued CW and the 2 s hang. `O` drops it at once. |

## `K:` lines: output from the client Nano

`K:` is not a command; typing `K:` returns `E:CMD`. Every character you send with the
paddle comes out of the client as a `K:` line, which the Mac client forwards to the station.

| Line | Meaning |
|---|---|
| `K:C` | A character you sent. |
| `K: ` | A word space, after a pause of about 5 dits. |
| `K:{...-.-}` | A pattern the decoder doesn't have in its table, passed through as raw elements. |
