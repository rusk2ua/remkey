#!/bin/sh
# Build and run the firmware simulation for both roles and both keyer modes.
set -e
cd "$(dirname "$0")"
for role in 1 2; do
  for mode in 1 0; do
    for led in 1 0; do
      g++ -std=c++17 -Wall -Wno-unused-function -I. -I../../firmware/remkey \
          -DREMKEY_ROLE=$role -DKEYER_MODE_B=$mode -DLED_ACTIVE_LOW=$led \
          -x c++ sim_test.cpp -o sim_${role}_${mode}_${led}
      ./sim_${role}_${mode}_${led}
    done
  done
done
