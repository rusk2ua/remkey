// remtlm configuration: tower telemetry over an Ebyte E220-900T22D LoRa link.
// Three images from one sketch:
//   TOWER  Nano at the tower top: PA, transverter, temperatures
//   PSU    Nano in the supply box at the tower base: supply voltage/current, box temperature
//   BASE   Nano in the radio room, plugged into the shack PC by USB: receives both
#pragma once

#define ROLE_TOWER 1
#define ROLE_BASE  2
#define ROLE_PSU   3

#ifndef REMTLM_ROLE
#define REMTLM_ROLE ROLE_TOWER
#endif

// ---------------------------------------------------------------------------
// Station identity (sent in every packet)
// ---------------------------------------------------------------------------
#define CALLSIGN "K2UA"

// ---------------------------------------------------------------------------
// LoRa link. Both ends MUST match. The firmware writes these to the module at
// boot (only if they differ, to spare the module's flash).
//
// E220-900T22D frequency = 850.125 MHz + channel.  Channel 77 = 927.125 MHz:
// top of the US 902-928 MHz band, ~24 MHz clear of 902-903 weak-signal work.
// ---------------------------------------------------------------------------
#define LORA_CHANNEL     77
#define LORA_ADDH        0x00
#define LORA_ADDL        0x00
#define LORA_AIR_RATE    AIR_DATA_RATE_100_96   // 9.6 kbps: plenty of margin at 200 ft
#define LORA_TX_POWER    POWER_17               // POWER_22/17/13/10 dBm

// ---------------------------------------------------------------------------
// Pins (all roles). E220 logic is 3.3 V: see the README for the dividers.
// ---------------------------------------------------------------------------
#define PIN_E220_TXD   7    // Nano RX  <- E220 TXD
#define PIN_E220_RXD   8    // Nano TX  -> divider -> E220 RXD
#define PIN_E220_AUX   6    // Nano in  <- E220 AUX (high = idle)
#define PIN_E220_M0    9    // Nano out -> divider -> E220 M0
#define PIN_E220_M1    10   // Nano out -> divider -> E220 M1
#define PIN_LED        13

// TOWER and PSU
#define PIN_ONEWIRE    5    // DS18B20 probes (4.7k pull-up to 5 V); tower: up to 2, PSU: 1
// A4 = SDA, A5 = SCL: INA226 supply monitor (fixed by the Nano's I2C hardware)

// TOWER only
#define PIN_PA_SENSE   A0   // PA power-sense output (0-5 V) via divider
#define PIN_XV_SENSE   A1   // MKU 10 G5 CON1 pin 9 MON via divider
#define PIN_LO_LOCK    A2   // MKU 10 G5 CON1 pin 16 LD (3.3 V = locked), read as analog
#define PIN_PTT_SENSE  A3   // MKU CON1 pin 8 PTT out (active low, to the sequencer) via network
#define PIN_XV_RX      11   // Nano RX  <- level shifter <- MKU CON1 pin 11 TXD
#define PIN_XV_TX      12   // Nano TX  -> level shifter -> MKU CON1 pin 12 RXD

// ---------------------------------------------------------------------------
// Analog scaling (tower). The host converts mV to watts with your calibration
// table, so these only need to turn ADC counts into volts at the sense pins.
//   VREF_MV:   measure the Nano's 5V pin with a DMM and enter it here.
//   DIVIDER:   (Rtop + Rbottom) / Rbottom of the input divider, x1000.
//              10k over 22k -> 32/22 = 1.4545 -> 1455.
// ---------------------------------------------------------------------------
#define VREF_MV          5000UL
#define DIVIDER_X1000    1455UL

// MKU 10 G5 LD (pin 16) is 3.3 V only while locked to an EXTERNAL 10 MHz reference.
// Without an external reference it stays low: set LOCK_MONITOR 0 to stop alarms.
#ifndef LOCK_MONITOR
#define LOCK_MONITOR      1
#endif
#define LOCK_ACTIVE_HIGH  1
#define LOCK_THRESHOLD_MV 1650   // at the pin (no divider on A2)

// MKU 10 G5 CON1 pin 8: PTT out to the sequencer, active low. The tower only
// watches it, never drives it. Network (RK-302 Rev B, prototype rows 12-13):
//   line -> 100k to +5 V (so an open line reads high, ~2 V, not "keyed")
//   line -> 47k -> A3 -> 22k + 100 nF to GND   (safe up to ~15 V on the line)
// PTT_DIVIDER_X1000 = (47k + 22k) / 22k x1000, to report volts on the line.
#ifndef PTT_SENSE
#define PTT_SENSE           1        // 0 on a tower without the network (RK-302 Rev A)
#endif
#define PTT_DIVIDER_X1000   3136UL
#define PTT_ASSERT_MV       1000     // line below this = keyed
#define PTT_RELEASE_MV      1500     // and above this = released again (hysteresis)

// ---------------------------------------------------------------------------
// Kuhne MKU 10 G5 serial interface (3.3 V, 9600 8N1). Read-only: the tower
// only ever sends "s" (status) and "v" (version), never configuration commands.
// ---------------------------------------------------------------------------
#define XV_SERIAL_ENABLE  1
#define XV_BAUD           9600
#define XV_CMD_SUFFIX     ""       // add "\r" here if the transverter wants a terminator
#define XV_POLL_MS        60000UL  // status ("s") poll period
#define XV_FIRST_POLL_MS  5000UL   // first poll after boot ("v" then "s")
#define XV_REPLY_GAP_MS   300UL    // reply is complete after this much silence
#define XV_REPLY_MAX_MS   2000UL   // give up waiting for a reply
#define XV_BUF            240      // longest reply kept (bytes)

// ---------------------------------------------------------------------------
// Supply monitor: INA226 on I2C with a high-side shunt in the + feed.
//   PSU role:   always on. Shunt at the supply output, ahead of the tower cable;
//               the PSU Nano's own 5 V is taken from the supply side of the shunt.
//   TOWER role: optional (PWR_ENABLE 1), a second INA226 + shunt at the top-box
//               entry. With both, the host shows the measured cable drop.
//   SHUNT_UOHM: shunt resistance in micro-ohms. The INA226 reads at most 81.92 mV
//               across the shunt, so this sets the full-scale current.
//               3750 = 20 A / 75 mV panel-meter shunt: 21.8 A full scale, 0.67 mA steps.
//               Other common values: 5000 (5 mOhm, 16.4 A), 2000 (2 mOhm, 41 A).
//               Remove a CJMCU-226 module's own R100 shunt: left in parallel with
//               the 3.75 mOhm shunt it reads 3.6% low (or set 3614).
//   Trim small gain errors against a DMM with v_scale / i_scale in station.toml.
// ---------------------------------------------------------------------------
#ifndef PWR_ENABLE
#define PWR_ENABLE       0        // TOWER only: 1 = INA226 in the top box too
#endif
#ifndef INA226_ADDR
#define INA226_ADDR      0x40     // tried first; the firmware also searches 0x40-0x4F
#endif
#define SHUNT_UOHM       3750L    // 20 A / 75 mV panel shunt
#define PWR_SAMPLE_MS    10UL     // the INA226 produces a new averaged reading every 8.8 ms
#define PWR_RETRY_MS     5000UL   // re-initialize this often if the INA226 stops answering
#define PWR_FAIL_LIMIT   5        // consecutive failed reads before it counts as not answering

// ---------------------------------------------------------------------------
// Dish elevation and box environment (TOWER). Both sensors are 3.3 V parts on I2C
// (A4/A5), through the 3.3 V side of the level shifter: channels 3 and 4 of the
// RK-302 Rev B's shifter and its sensor header, or the sensor board for a Rev A
// (docs/prototype). The tower sends raw readings; the shack PC turns them into
// degrees, temperature, humidity and pressure with the calibration in station.toml,
// so recalibrating never needs a reflash.
//   TILT_ENABLE  ADXL355 on the frame that carries both dishes (one actuator, one
//                sensor; address 0x1D or 0x53, found automatically)
//   ENV_ENABLE   BME280 in the box (0x76 or 0x77; a BMP280 works too, without humidity)
// A missing sensor costs nothing but a short "not found" packet every 30 s.
//
// Live elevation: while the dish moves, a $RA goes out every LIVE_PERIOD_MS, until
// it has been still for LIVE_HOLD_MS. "Moving" = an axis changed by more than
// LIVE_THRESHOLD counts between two 200 ms averages (256000 counts = 1 g, so 350 is
// about 0.08 deg). Raise it if wind sway keeps triggering live mode. Live packets
// skip LIVE_GUARD_MS after each $RT, which keeps the supply box's slot clear, and
// no MKU poll starts while the dish moves.
// ---------------------------------------------------------------------------
#ifndef TILT_ENABLE
#define TILT_ENABLE       1
#endif
#ifndef ENV_ENABLE
#define ENV_ENABLE        1
#endif
#define TILT_ODR_LPF      0x07     // ADXL355 filter: 31.25 Hz output, 7.8 Hz low-pass
#define TILT_SAMPLE_MS    32UL     // one read per output sample
#define LIVE_PERIOD_MS    200UL    // live elevation packet rate while the dish moves
#define LIVE_HOLD_MS      3000UL   // keep sending this long after the last movement
#define LIVE_THRESHOLD    350L     // counts between 200 ms averages that mean "moving"
#define LIVE_GUARD_MS     450UL    // no live packet this long after a $RT (supply box slot)
#define ENV_PERIOD_MS     10000UL  // BME280 reading
#define ENV_CAL_PERIOD_MS 300000UL // resend the BME280 calibration constants
#define SENSOR_RETRY_MS   5000UL   // look for a missing sensor this often
#define SENSOR_FAIL_LIMIT 5        // consecutive failed reads before a sensor counts as gone
#define SENSOR_MISSING_MS 30000UL  // report a missing sensor (ok 0) this often

// ---------------------------------------------------------------------------
// Reporting (TOWER)
// ---------------------------------------------------------------------------
#define SAMPLE_MS        5UL     // analog sampling: catches the peak of a 20 WPM dit
#define REPORT_IDLE_MS   2000UL  // packet rate while the PA is quiet
#define REPORT_ACTIVE_MS 500UL   // packet rate while the PA shows output
#define CHANGE_GAP_MS    300UL   // lock / key-line changes: at most one extra packet per 300 ms
#define ACTIVE_MV        150     // PA sense above this = "transmitting"
#define TEMP_PERIOD_MS   2000UL  // DS18B20 conversion cadence (tower and PSU)

// ---------------------------------------------------------------------------
// Reporting (PSU). Both transmitters share channel 77, so the PSU node listens
// and sends its $RS a moment after each tower $RT it hears, in the gap before
// the tower's next packet (>= 500 ms away). With no tower heard, it sends on
// its own every PSU_REPORT_MS.
// ---------------------------------------------------------------------------
#define PSU_SLOT_DELAY_MS 60UL    // after the end of a tower $RT
#define PSU_MIN_GAP_MS    400UL   // never send more often than this
#define PSU_REPORT_MS     2000UL  // free-running period when the tower is silent
#define PSU_TOWER_LOST_MS 3500UL  // no tower $RT this long -> free-running

// ---------------------------------------------------------------------------
// Signal reports (BASE). The base's E220 adds an RSSI byte to every packet it
// receives, and the base reads the module's noise-floor register between packets.
// ---------------------------------------------------------------------------
#define NOISE_POLL_MS     10000UL // how often to read the noise floor
#define NOISE_QUIET_MS    150UL   // only after the link has been quiet this long
#define NOISE_REPLY_MS    200UL   // give up on a reply after this
