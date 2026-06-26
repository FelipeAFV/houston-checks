#!/usr/bin/env bash
#
# Name: Ceph health status
# Description: Ceph cluster health must be HEALTH_OK.
#

if ! command -v ceph >/dev/null 2>&1; then
  echo "ceph CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi

health_json=$(ceph health --format=json 2>/dev/null)
if [[ -z "$health_json" ]]; then
  echo "ceph health failed" >&2
  exit 1
fi

status=$(printf '%s' "$health_json" | jq -r '.status // empty' 2>/dev/null)
if [[ -z "$status" ]]; then
  echo "ceph health returned no status field" >&2
  exit 1
fi

if [[ "$status" == "HEALTH_OK" ]]; then
  printf 'Ceph health: %s\n' "$status"
  exit 0
fi

echo "Ceph status is not healthy: ${status}" >&2
exit 1
