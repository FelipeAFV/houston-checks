#!/usr/bin/env bash
#
# Name: Powerprofile check
# Description: /sys/devices/system/cpu/cpu0/power/energy_perf_bias has the correct range value for indicated performance mode.
#

vendor=$(awk -F': ' '/vendor_id/ {print $2; exit}' /proc/cpuinfo)

# AMD does not implement energy_perf_bias.
if [[ "$vendor" == "AuthenticAMD" ]]; then
    printf "AMD CPU detected."
    printf "Check not applicable on AMD."
    printf 'CHECK_RC=0\n'
    exit 0
fi

energy_perf_bias_file=/sys/devices/system/cpu/cpu0/power/energy_perf_bias

if [[ ! -f "$energy_perf_bias_file" ]]; then
  printf "Not AMD CPU but energy_perf_bias file not found."
  printf 'CHECK_RC=0\n'
  exit 0
fi

energy_perf_bias_value=$(cat "$energy_perf_bias_file")
# Check if the file contains the expected value for the performance mode 
if [[ "$energy_perf_bias_value" == "6" || "$energy_perf_bias_value" == "7" ]]; then
  printf "Intel server"
  printf "energy_perf_bias=%s" "$energy_perf_bias_value"
  printf 'CHECK_RC=0\n'
  exit 0
fi

printf 'CHECK_RC=1\n'
exit 1
