#!/usr/bin/env bash

#
# Name: Sysctl parameters check
# Description: Check sysctl parameters are within configured min/max values.
#

SYSCTL_PARAMETERS="${SYSCTL_PARAMETERS:-fs.inotify.max_user_watches,fs.inotify.max_user_instances,fs.inotify.max_queued_events}"
MIN_SYSCTL_VALUES="${MIN_SYSCTL_VALUES:-2099999999,2099999999,2099999999}"
MAX_SYSCTL_VALUES="${MAX_SYSCTL_VALUES:-2099999999,2099999999,2099999999}"

IFS=',' read -ra sysctl_parameters <<< "$SYSCTL_PARAMETERS"
IFS=',' read -ra min_sysctl_values <<< "$MIN_SYSCTL_VALUES"
IFS=',' read -ra max_sysctl_values <<< "$MAX_SYSCTL_VALUES"

if [[ ${#sysctl_parameters[@]} -ne ${#min_sysctl_values[@]} ||
      ${#sysctl_parameters[@]} -ne ${#max_sysctl_values[@]} ]]; then
  printf "The number of sysctl parameters, minimum values, and maximum values must match.\n"
  printf 'CHECK_RC=1\n'
  exit 1
fi

failed=0

for i in "${!sysctl_parameters[@]}"; do
  parameter="${sysctl_parameters[$i]}"
  min_value="${min_sysctl_values[$i]}"
  max_value="${max_sysctl_values[$i]}"

  current_value=$(sudo sysctl -n "$parameter" 2>/dev/null)

  if [[ $? -ne 0 ]]; then
    printf "Unable to read sysctl parameter: %s\n" "$parameter"
    failed=1
    continue
  fi

  if (( current_value < min_value || current_value > max_value )); then
    printf "%s is out of range.\n" "$parameter"
    printf "Current value: %s\n" "$current_value"
    printf "Expected range: %s - %s\n" "$min_value" "$max_value"
    failed=1
  fi
done

if (( failed != 0 )); then
  printf 'CHECK_RC=1\n'
  exit 1
fi

printf "All sysctl parameters are within the expected ranges.\n"
printf 'CHECK_RC=0\n'
exit 0