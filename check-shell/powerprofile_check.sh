#!/usr/bin/env bash
#
# Name: Powerprofile check
# Description: /sys/devices/system/cpu/cpu0/power/energy_perf_bias has the correct range value for indicated performance mode.
#

energy_perf_bias_file=/sys/devices/system/cpu/cpu0/power/energy_perf_bias

if [[ ! -f "$energy_perf_bias_file" ]]; then
  printf 'CHECK_RC=0\n'
  exit 0
fi

energy_perf_bias_value=$(cat "$energy_perf_bias_file")
# Check if the file contains the expected value for the performance mode 
if [[ "$energy_perf_bias_value" == "6" || "$energy_perf_bias_value" == "7" ]]; then
  printf 'CHECK_RC=0\n'
  exit 0
fi

printf 'CHECK_RC=1\n'
exit 1
