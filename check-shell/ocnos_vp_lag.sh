#!/usr/bin/env bash
#
# Name: VP LAGs Check
# Description: Check the maximum number of VP LAGs and the number of VP LAG IDs on the switch.
# Executor: shell_bastion

set -euo pipefail

source "$SCRIPT_DIR/../lib/utils.sh"
load_expected_values

echo "Checking VP LAGs on switch $TARGET_HOST..."

send_commands_to_device > /dev/null <<'EOF'
enable
hw-shell
EOF

output_file=$(make_temp_file)
echo "dump sw trunk"  | send_commands_to_device > "$output_file"
echo "exit"           | send_commands_to_device > /dev/null

max_number_of_vp_lags=$(grep -E "Max\s+number\s+of\s+VP\s+LAGs:" "$output_file" | tail -n 1 | grep -oE '[0-9]+' || true)

if [[ -z "$max_number_of_vp_lags" ]]; then
  echo "Error: No Max number of VP LAGs found in output."
  exit 1
fi

if [[ $(grep -c "server-leaf-switch" <<< "$NODE_TAGS") -gt 0 ]]; then
  expected_max_number_of_vp_lags=$expected_max_number_of_vp_lags_leaf
fi

if [[ $(grep -c "border-leaf-switch" <<< "$NODE_TAGS") -gt 0 ]]; then
  expected_max_number_of_vp_lags=$expected_max_number_of_vp_lags_brlf
fi

if [[ -z "$expected_max_number_of_vp_lags" ]]; then
  echo "Error: Expected max number of VP LAGs is not defined for this switch type."
  exit 1
fi

if [[ $max_number_of_vp_lags -lt $expected_max_number_of_vp_lags ]]; then
  echo "Error: Max number of VP LAGs ($max_number_of_vp_lags) is less than expected ($expected_max_number_of_vp_lags)"
  exit 1
fi

vp_lag_ids_lines=$(grep -E "^\s*VP\s+LAG\s+[0-9]+:\s+vp_id" "$output_file" || true)

if [[ -z "$vp_lag_ids_lines" ]]; then
  echo "Error: No VP LAG IDs found in output."
  exit 1
fi

vp_lag_ids_count=$(echo "$vp_lag_ids_lines" | wc -l)
vp_lag_highest_id=$(echo "$vp_lag_ids_lines" | tail -n 1 | grep -oE 'LAG\s+[0-9]+' | grep -oE '[0-9]+' || true)

expected_max_vp_lag_usage_ratio_val="${expected_max_vp_lag_usage_ratio//%/}"

vp_lag_usage_ratio_val=$(( vp_lag_highest_id * 100 / max_number_of_vp_lags ))

if [[ $vp_lag_usage_ratio_val -gt $expected_max_vp_lag_usage_ratio_val ]]; then
  echo "Error: VP LAG usage ratio ($vp_lag_usage_ratio_val%) is more than expected ($expected_max_vp_lag_usage_ratio_val%)"
  exit 1
fi

echo "All VP LAG checks passed successfully. (Max: $max_number_of_vp_lags, Active IDs: $vp_lag_ids_count, Highest ID: $vp_lag_highest_id, Ratio: $expected_max_vp_lag_usage_ratio_val%)"
exit 0
