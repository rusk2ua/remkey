// Types used in function signatures in remkey.ino.
//
// The Arduino build generates function prototypes and inserts them near the top
// of the sketch, before anything the sketch itself declares. Any type that appears
// in a function's parameters or return value must therefore be declared in a
// header included at the top, not in the .ino.
#pragma once
#include <stdint.h>

enum TState : uint8_t { T_IDLE, T_ELEM, T_GAP, T_WAIT, T_TUNE };   // text sender
enum PState : uint8_t { P_IDLE, P_ELEM, P_GAP };                   // paddle keyer
enum Elem : uint8_t { E_NONE, E_DIT, E_DAH };                       // keyer element
