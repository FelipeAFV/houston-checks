#!/usr/bin/env bash
#
# Name: VXLAN MAC Table Check
# Description: Check for duplicated (conflict) MAC entries in the VXLAN MAC table.
# Executor: shell_bastion

set -euo pipefail

source "$SCRIPT_DIR/../lib/utils.sh"
load_expected_values

echo "Checking VXLAN MAC Table on switch $TARGET_HOST..."

output_file=$(make_temp_file)
echo "show nvo vxlan mac-table" | send_commands_to_device > "$output_file"
echo "exit"                     | send_commands_to_device > /dev/null

conflict_macs=$(tr -s ' ' < "$output_file" | cut -d' ' -f5,9 | grep -w "conflict" | cut -d' ' -f1 | sort -u || true)

if [[ -n "$conflict_macs" ]]; then
    echo "Error: Conflicted MAC entries found in VXLAN MAC table."
    echo "--- Conflicted entries detail ---"
    
    for mac in $conflict_macs; do
        grep -i "$mac" "$output_file" | sed 's/^/  > /'
    done
    
    exit 1
fi

echo "All VXLAN MAC table checks passed successfully. No duplicated or conflicted MAC entries detected."
exit 0
