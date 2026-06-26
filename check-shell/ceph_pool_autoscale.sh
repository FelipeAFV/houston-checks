#!/usr/bin/env bash
#
# Name: Ceph pool autoscale
# Description: All Ceph pools must have pg_autoscale_mode on.
#

if ! command -v ceph >/dev/null 2>&1; then
  echo "ceph CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi

pools_json=$(ceph osd pool autoscale-status --format=json 2>/dev/null)
if [[ -z "$pools_json" ]]; then
  echo "ceph osd pool autoscale-status failed" >&2
  exit 1
fi

stats=$(printf '%s' "$pools_json" | jq -c '{
  total: length,
  bad: [.[] | select(.pg_autoscale_mode != "on") | {
    pool: (.pool_name // .name // "unknown"),
    mode: (.pg_autoscale_mode // "<unset>")
  }]
}')

failure_count=$(jq '.bad | length' <<<"$stats")
if [[ "$failure_count" -gt 0 ]]; then
  jq -r '.bad[] | "Pool \(.pool) is set to \(.mode)"' <<<"$stats" >&2
  echo "Ceph autoscaler is not active on these pools" >&2
  exit 1
fi