// remkey firmware configuration
// Edit this file, then build/upload with the Arduino IDE (board: Arduino Nano,
// processor ATmega328P or "ATmega328P (Old Bootloader)" for many clones).
#pragma once

// ---------------------------------------------------------------------------
// Role. Build the CLIENT image for the travel keyer and the STATION image for
// the shack keyer. Same sketch, different defaults.
// ---------------------------------------------------------------------------
#define ROLE_CLIENT  1
#define ROLE_STATION 2

#ifndef REMKEY_ROLE
#define REMKEY_ROLE ROLE_CLIENT
#endif

// ---------------------------------------------------------------------------
// Pins (Arduino Nano / Uno)
// ---------------------------------------------------------------------------
#define PIN_DIT        2    // paddle dit  (to GND when pressed, internal pull-up)
#define PIN_DAH        3    // paddle dah  (to GND when pressed, internal pull-up)
#define PIN_PTT_BTN    4    // PTT pushbutton / footswitch (to GND, client)
#define PIN_SIDETONE   9    // sidetone square wave -> 220 ohm -> piezo/headphone amp
#define PIN_KEY_OUT    10   // optocoupler LED for radio KEY line (station)
#define PIN_PTT_OUT    11   // optocoupler LED for radio PTT/SEND line (station)
#define PIN_LED        13   // on-board LED: flashes with the CW being sent (paddle or text)
#define PIN_PTT_LED    12   // optional external LED: PTT on (station) / PTT confirmed (client)
                            //   D12 -> 1k -> LED anode, cathode -> GND
#define PIN_SPEED_POT  A0   // optional 10k speed pot wiper (ends to 5V and GND)

// 1 if the on-board LED lights when PIN_LED is LOW (true on some Nano clones),
// 0 if it lights when HIGH (genuine Arduino Nano). PIN_PTT_LED is always active-high.
#ifndef LED_ACTIVE_LOW
#define LED_ACTIVE_LOW 1
#endif

// ---------------------------------------------------------------------------
// Keyer defaults
// ---------------------------------------------------------------------------
#define DEFAULT_WPM      18
#define WPM_MIN          5
#define WPM_MAX          50
#define POT_WPM_MIN      10   // speed pot range
#define POT_WPM_MAX      35
#ifndef KEYER_MODE_B
#define KEYER_MODE_B     1    // 1 = iambic B, 0 = iambic A
#endif
#define SWAP_PADDLES     0    // 1 = swap dit/dah
#define DEFAULT_TONE_HZ  600
#define TUNE_MAX_MS      30000UL  // hard cap on a tune carrier
#define QUEUE_SIZE       128      // text buffer (bytes)
#define WDOG_MS          3000UL   // no host traffic for this long -> PTT/key off

#if REMKEY_ROLE == ROLE_CLIENT
  #define USE_SPEED_POT        0  // set to 1 once a pot is wired to A0
  #define DEFAULT_SIDETONE     1
  #define DEFAULT_PADDLE_OUT   0  // client paddle never drives PIN_KEY_OUT
  #define DEFAULT_WDOG         0
#else
  #define USE_SPEED_POT        0  // never on the station (floating A0 = random speed)
  #define DEFAULT_SIDETONE     0  // station Nano usually has no speaker
  #define DEFAULT_PADDLE_OUT   1  // a paddle plugged into the station Nano keys the rig
  #define DEFAULT_WDOG         1
#endif
