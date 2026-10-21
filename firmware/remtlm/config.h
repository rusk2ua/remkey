// remtlm configuration: tower-top telemetry over an Ebyte E220-900T22D LoRa link.
// Build the TOWER image for the Nano at the tower top and the BASE image for the
// Nano in the radio room (plugged into the shack PC by USB).
#pragma once

#define ROLE_TOWER 1
#define ROLE_BASE  2

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
// Pins (both roles). E220 logic is 3.3 V: see the README for the dividers.
// ---------------------------------------------------------------------------
#define PIN_E220_TXD   7    // Nano RX  <- E220 TXD
#define PIN_E220_RXD   8    // Nano TX  -> divider -> E220 RXD
#define PIN_E220_AUX   6    // Nano in  <- E220 AUX (high = idle)
#define PIN_E220_M0    9    // Nano out -> divider -> E220 M0
#define PIN_E220_M1    10   // Nano out -> divider -> E220 M1
#define PIN_LED        13

// Tower-only
#define PIN_PA_SENSE   A0   // PA power-sense output (0-5 V) via divider
#define PIN_XV_SENSE   A1   // MKU 10 G5 CON1 pin 9 MON via divider
#define PIN_LO_LOCK    A2   // MKU 10 G5 CON1 pin 16 LD (3.3 V = locked), read as analog
#define PIN_ONEWIRE    5    // DS18B20 probes (4.7k pull-up to 5 V); up to 2 on one bus
#define PIN_XV_RX      11   // Nano RX  <- level shifter <- MKU CON1 pin 11 TXD
#define PIN_XV_TX      12   // Nano TX  -> level shifter -> MKU CON1 pin 12 RXD
// A4 = SDA, A5 = SCL: INA226 supply monitor (fixed by the Nano's I2C hardware)

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
#define LOCK_MONITOR      1
#define LOCK_ACTIVE_HIGH  1
#define LOCK_THRESHOLD_MV 1650   // at the pin (no divider on A2)

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
// Tower supply monitor: INA226 on I2C with a high-side shunt in the 13.8 V feed
// at the enclosure entry, ahead of everything in the box.
//   SHUNT_UOHM: shunt resistance in micro-ohms. The INA226 reads at most 81.92 mV
//               across the shunt, so this sets the full-scale current.
//               3750 = 20 A / 75 mV panel-meter shunt: 21.8 A full scale, 0.67 mA steps.
//               Other common values: 5000 (5 mOhm, 16.4 A), 2000 (2 mOhm, 41 A).
//               Remove a CJMCU-226 module's own R100 shunt: left in parallel with
//               the 3.75 mOhm shunt it reads 3.6% low (or set 3614).
//   Trim small gain errors against a DMM with v_scale / i_scale in station.toml.
// ---------------------------------------------------------------------------
#define PWR_ENABLE       1
#define INA226_ADDR      0x40     // A0 and A1 address pins to GND
#define SHUNT_UOHM       3750L    // 20 A / 75 mV panel shunt
#define PWR_SAMPLE_MS    10UL     // the INA226 produces a new averaged reading every 8.8 ms
#define PWR_RETRY_MS     5000UL   // re-initialise this often if the INA226 stops answering

// ---------------------------------------------------------------------------
// Reporting (tower)
// ---------------------------------------------------------------------------
#define SAMPLE_MS        5UL     // analog sampling: catches the peak of a 20 WPM dit
#define REPORT_IDLE_MS   2000UL  // packet rate while the PA is quiet
#define REPORT_ACTIVE_MS 500UL   // packet rate while the PA shows output
#define ACTIVE_MV        150     // PA sense above this = "transmitting"
#define TEMP_PERIOD_MS   2000UL  // DS18B20 conversion cadence
