#!/usr/bin/env bash
#
# Name: Ceph health checks
# Description: Ceph health detail must not report failed checks (severity beyond WARN).
#

if ! command -v ceph >/dev/null 2>&1; then
  echo "ceph CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi

detail_json=$(ceph health detail --format=json 2>/dev/null)
if [[ -z "$detail_json" ]]; then
  echo "ceph health detail failed" >&2
  exit 1
fi

failures=$(printf '%s' "$detail_json" | jq '[ (.checks // {}) | .[] | select(.severity != "HEALTH_OK" and .severity != "HEALTH_WARN") ] | length')
if [[ "$failures" -gt 0 ]]; then
  echo "At least one Ceph check is failed" >&2
  exit 1
fi

status=$(printf '%s' "$detail_json" | jq -r '.status // empty')
if [[ "$status" == *HEALTH_ERR* ]]; then
  echo "Ceph cluster status is ${status}" >&2
  exit 1
fi

printf 'Ceph health detail: %s (no failed checks)\n' "${status:-HEALTH_OK}"