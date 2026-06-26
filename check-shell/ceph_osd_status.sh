#!/usr/bin/env bash
#
# Name: Ceph OSD status
# Description: All OSDs must be up with positive crush weight.
#

if ! command -v ceph >/dev/null 2>&1; then
  echo "ceph CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi

tree_json=$(ceph osd tree --format=json 2>/dev/null)
if [[ -z "$tree_json" ]]; then
  echo "ceph osd tree failed" >&2
  exit 1
fi

stats=$(printf '%s' "$tree_json" | jq -c '{
  total: ([(.nodes[]? // .[]?) | select(.type == "osd")] | length),
  bad: [(.nodes[]? // .[]?) | select(.type == "osd") | select(
    .status != "up" or
    ((.exists // 1) | tonumber) != 1 or
    ((.crush_weight // 0) | tonumber) <= 0
  ) | "\(.status) - \(.name) - \(.device_class // "") - crush weight: \(.crush_weight // 0) - reweight: \(.reweight // "")"]
}')

failure_count=$(jq '.bad | length' <<<"$stats")
if [[ "$failure_count" -gt 0 ]]; then
  jq -r '.bad[]' <<<"$stats" >&2
  echo "At least one Ceph OSD is failed" >&2
  exit 1
fi
printf 'All %d OSD(s) are up with positive crush weight\n' "$(jq '.total' <<<"$stats")"
exit 0
