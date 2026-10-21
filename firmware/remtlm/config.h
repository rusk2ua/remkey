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
#define PIN_XV_SENSE   A1   // transverter power-sense output (0-5 V) via divider
#define PIN_LO_LOCK    4    // transverter LO-lock output
#define PIN_ONEWIRE    5    // DS18B20 heatsink probe (4.7k pull-up to 5 V)

// ---------------------------------------------------------------------------
// Analog scaling (tower). The host converts mV to watts with your calibration
// table, so these only need to turn ADC counts into volts at the sense pins.
//   VREF_MV:   measure the Nano's 5V pin with a DMM and enter it here.
//   DIVIDER:   (Rtop + Rbottom) / Rbottom of the input divider, x1000.
//              10k over 22k -> 32/22 = 1.4545 -> 1455.
// ---------------------------------------------------------------------------
#define VREF_MV          5000UL
#define DIVIDER_X1000    1455UL

#define LOCK_ACTIVE_HIGH 1      // 1 if the LO-lock output is HIGH when locked

// ---------------------------------------------------------------------------
// Reporting (tower)
// ---------------------------------------------------------------------------
#define SAMPLE_MS        5UL     // analog sampling: catches the peak of a 20 WPM dit
#define REPORT_IDLE_MS   2000UL  // packet rate while the PA is quiet
#define REPORT_ACTIVE_MS 500UL   // packet rate while the PA shows output
#define ACTIVE_MV        150     // PA sense above this = "transmitting"
#define TEMP_PERIOD_MS   2000UL  // DS18B20 conversion cadence
