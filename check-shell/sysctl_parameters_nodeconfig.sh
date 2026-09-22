#!/usr/bin/env bash

#
# Name: NodeConfig sysctl parameters check
# Description: Check sysctl parameters are configured in NodeConfig resource.
#

SYSCTL_PARAMETERS="${SYSCTL_PARAMETERS:-fs.inotify.max_user_watches,fs.inotify.max_user_instances,fs.inotify.max_queued_events}"
MIN_SYSCTL_VALUES="${MIN_SYSCTL_VALUES:-2099999999,2099999999,2099999999}"
MAX_SYSCTL_VALUES="${MAX_SYSCTL_VALUES:-2099999999,2099999999,2099999999}"

NODECONFIG_NAME="${NODECONFIG_NAME:-nodeconfig-kernel-params}"
NODECONFIG_NAMESPACE="${NODECONFIG_NAMESPACE:-default}"

IFS=',' read -ra sysctl_parameters <<< "$SYSCTL_PARAMETERS"
IFS=',' read -ra min_sysctl_values <<< "$MIN_SYSCTL_VALUES"
IFS=',' read -ra max_sysctl_values <<< "$MAX_SYSCTL_VALUES"

if [[ ${#sysctl_parameters[@]} -ne ${#min_sysctl_values[@]} ||
      ${#sysctl_parameters[@]} -ne ${#max_sysctl_values[@]} ]]; then
    printf "The number of sysctl parameters, minimum values, and maximum values must match.\n"
    printf 'CHECK_RC=1\n'
    exit 1
fi

nodeconfig=$(kubectl get nodeconfig "$NODECONFIG_NAME" \
    -n "$NODECONFIG_NAMESPACE" \
    -o json 2>/dev/null)

if [[ $? -ne 0 ]]; then
    printf "Unable to get NodeConfig: %s/%s\n" \
        "$NODECONFIG_NAMESPACE" "$NODECONFIG_NAME"
    printf 'CHECK_RC=1\n'
    exit 1
fi

failed=0

printf "Configured sysctl parameters in NodeConfig:\n"

for i in "${!sysctl_parameters[@]}"; do
    parameter="${sysctl_parameters[$i]}"
    min_value="${min_sysctl_values[$i]}"
    max_value="${max_sysctl_values[$i]}"

    configured_value=$(echo "$nodeconfig" | jq -r \
        --arg parameter "$parameter" \
        '.spec.kernelParameters.parameters[] |
         select(.name == $parameter) |
         .value' | head -n 1)

    if [[ -z "$configured_value" || "$configured_value" == "null" ]]; then
        printf "%s: NOT CONFIGURED\n" "$parameter"
        printf "Sysctl parameter is not configured in NodeConfig: %s\n" "$parameter"
        failed=1
        continue
    fi

    printf "%s: %s\n" "$parameter" "$configured_value"

    if (( configured_value < min_value || configured_value > max_value )); then
        printf "%s is out of range.\n" "$parameter"
        printf "Current value: %s\n" "$configured_value"
        printf "Expected range: %s - %s\n" "$min_value" "$max_value"
        failed=1
    fi
done

if (( failed != 0 )); then
    printf 'CHECK_RC=1\n'
    exit 1
fi

printf "All sysctl parameters are configured correctly in NodeConfig.\n"
printf 'CHECK_RC=0\n'

exit 0