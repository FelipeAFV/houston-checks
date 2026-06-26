#!/usr/bin/env bash
#
# Name: Host aggregates consistency
# Description: Placement resource provider aggregates must match Nova aggregate UUIDs.
#              Skips when no host aggregates exist in Nova and Placement.
#

if ! command -v openstack >/dev/null 2>&1; then
  echo "openstack CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi
if [[ -z "${OS_AUTH_URL:-}" ]]; then
  echo "OS_AUTH_URL is not set (configure openstack block in rundeck/provisioning/config.yaml)" >&2
  exit 1
fi
if [[ -z "${OS_USERNAME:-}" ]]; then
  echo "OS_USERNAME is not set" >&2
  exit 1
fi
if [[ -z "${OS_PASSWORD:-}" ]]; then
  echo "OS_PASSWORD is not set (configure OPENSTACK_PASSWORD in Rundeck Key Storage)" >&2
  exit 1
fi

err=$(mktemp)
aggregates_json=$(openstack --insecure aggregate list -f json 2>"$err")
if [[ $? -ne 0 || -z "${aggregates_json//[[:space:]]}" ]]; then
  echo "openstack aggregate list failed: $(cat "$err" 2>/dev/null)" >&2
  rm -f "$err"
  exit 1
fi
rm -f "$err"

err=$(mktemp)
providers_json=$(openstack --insecure resource provider list -f json 2>"$err")
if [[ $? -ne 0 || -z "${providers_json//[[:space:]]}" ]]; then
  echo "openstack resource provider list failed: $(cat "$err" 2>/dev/null)" >&2
  rm -f "$err"
  exit 1
fi
rm -f "$err"

nova_uuids=$(printf '%s' "$aggregates_json" | jq -r '.[] | .UUID // .uuid' 2>/dev/null)
has_nova_aggregates=0
if [[ -n "$nova_uuids" ]]; then
  has_nova_aggregates=1
fi

failures=0
while IFS= read -r provider_id; do
  [[ -z "$provider_id" ]] && continue
  provider_name=$(printf '%s' "$providers_json" | jq -r --arg id "$provider_id" '.[] | select((.uuid // .id) == $id) | .name' 2>/dev/null | head -1)

  err=$(mktemp)
  prov_aggs_json=$(openstack --insecure resource provider aggregate list "$provider_id" -f json 2>"$err")
  if [[ $? -ne 0 || -z "${prov_aggs_json//[[:space:]]}" ]]; then
    echo "Host: ${provider_name:-?} | Provider UUID: ${provider_id} | could not list aggregates: $(cat "$err" 2>/dev/null)" >&2
    rm -f "$err"
    failures=$((failures + 1))
    continue
  fi
  rm -f "$err"

  prov_uuids=$(printf '%s' "$prov_aggs_json" | jq -r '.aggregates[]? // .[]? | .uuid? // .' 2>/dev/null)
  if [[ -z "$prov_uuids" ]]; then
    if [[ "$has_nova_aggregates" -eq 1 ]]; then
      echo "Host: ${provider_name:-?} | Provider UUID: ${provider_id} | Aggregate UUIDs: N/A" >&2
      failures=$((failures + 1))
    fi
    continue
  fi
  while IFS= read -r agg_uuid; do
    [[ -z "$agg_uuid" ]] && continue
    if ! printf '%s\n' "$nova_uuids" | grep -qxF "$agg_uuid"; then
      echo "Host: ${provider_name:-?} | Provider UUID: ${provider_id} | unknown aggregate UUID: ${agg_uuid}" >&2
      failures=$((failures + 1))
    fi
  done <<<"$prov_uuids"
done < <(printf '%s' "$providers_json" | jq -r '.[] | .uuid // .id' 2>/dev/null)

if [[ "$failures" -gt 0 ]]; then
  echo "Inconsistency between Nova and Placement host aggregates" >&2
  exit 1
fi
if [[ "$has_nova_aggregates" -eq 0 ]]; then
  printf 'No host aggregates configured in Nova or Placement; check not applicable\n'
  exit 0
fi
printf 'Nova and Placement host aggregates are consistent\n'