#!/usr/bin/env bash
#
# Name: Ceph balancer status
# Description: Ceph balancer module must be active.
#

if ! command -v ceph >/dev/null 2>&1; then
  echo "ceph CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi

status_json=$(ceph balancer status --format=json 2>/dev/null)
if [[ -z "$status_json" ]]; then
  echo "ceph balancer status failed" >&2
  exit 1
fi

active=$(printf '%s' "$status_json" | jq -r '.active // empty' 2>/dev/null)
if [[ "$active" == "true" ]]; then
  printf 'Ceph balancer is active\n'
  exit 0
fi

echo "Ceph balancer is not active (active=${active:-unknown})" >&2
exit 1
