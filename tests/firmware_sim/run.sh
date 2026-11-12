#!/bin/sh
# Build and run the firmware simulations:
#   remkey: both roles, both keyer modes, both LED polarities
#   remtlm: tower (with and without the top-box INA226), base and psu
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
for build in "1 0" "1 1" "2 0" "3 0"; do
  set -- $build
  g++ -std=c++17 -Wall -Wextra -Wno-unused-parameter -I. -Iremtlm_mocks -I../../firmware/remtlm \
      -DREMTLM_ROLE=$1 -DPWR_ENABLE=$2 -x c++ remtlm_sim.cpp -o remtlm_sim_$1_$2
  ./remtlm_sim_$1_$2
done
