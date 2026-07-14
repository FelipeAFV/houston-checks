#!/usr/bin/env bash
#
# Name: Powerprofile check
# Description: /sys/devices/system/cpu/cpu0/power/energy_perf_bias has the correct range value for indicated performance mode.
#

EXPECTED_INTEL_PROFILE_LOWER_RANGE="${EXPECTED_INTEL_PROFILE_LOWER_RANGE:-6}"
EXPECTED_INTEL_PROFILE_UPPER_RANGE="${EXPECTED_INTEL_PROFILE_UPPER_RANGE:-7}"
EXPECTED_AMD_PROFILE_REGEX="${EXPECTED_AMD_PROFILE_REGEX:-^(PerfPerWattOptimized|PerfPerWattOptimizedDapc|PerfPerWattOptimizedOS)$}"

vendor=$(awk -F': ' '/vendor_id/ {print $2; exit}' /proc/cpuinfo)

# AMD does not implement energy_perf_bias.
if [[ "$vendor" == "AuthenticAMD" ]]; then
    printf "AMD server\n"
    manufacturer=$(sudo dmidecode -s system-manufacturer)
    if [[ "$manufacturer" == "Dell Inc." ]]; then
      if which racadm >/dev/null 2>&1; then
        sys_profile=$(sudo racadm get BIOS.SysProfileSettings.SysProfile | awk -F'=' '/SysProfile=/ {print $2; exit}')
        if [[ "$sys_profile" =~ $EXPECTED_AMD_PROFILE_REGEX ]]; then
          printf "Dell server detected, AMD CPU, and SysProfile is set to a optimized mode.\n"
          printf 'CHECK_RC=0\n'
          exit 0
        else
          printf "Dell server detected, AMD CPU, but SysProfile is not set to a optimized mode.\n"
          printf 'CHECK_RC=1\n'
          exit 1
        fi
      else
        printf "Dell server detected, but racadm not found.\n"
        printf 'CHECK_RC=0\n'
        exit 0
      fi
    else
      printf "No current support for HPE or other manufacturers.\n"
      printf 'CHECK_RC=0\n'
      exit 0
    
    fi
fi

energy_perf_bias_file=/sys/devices/system/cpu/cpu0/power/energy_perf_bias

if [[ ! -f "$energy_perf_bias_file" ]]; then
  printf "Intel server but energy_perf_bias file not found.\n"
  printf 'CHECK_RC=1\n'
  exit 1
fi


energy_perf_bias_value=$(cat "$energy_perf_bias_file")
# Check if the file contains the expected value for the performance mode 
printf "Intel server\n"
printf "energy_perf_bias=%s\n" "$energy_perf_bias_value"
if [[ "$energy_perf_bias_value" -ge "$EXPECTED_INTEL_PROFILE_LOWER_RANGE" && "$energy_perf_bias_value" -le "$EXPECTED_INTEL_PROFILE_UPPER_RANGE" ]]; then
  printf "Intel server in optimized mode.\n"
  printf 'CHECK_RC=0\n'
  exit 0
fi

printf 'CHECK_RC=1\n'
exit 1
fi