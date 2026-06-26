#!/usr/bin/env bash
#
# Name: VRouter HA active agent
# Description: Each HA router must have exactly one network agent in ha_state active.
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
routers_json=$(openstack --insecure router list --long -f json 2>"$err")
if [[ $? -ne 0 || -z "${routers_json//[[:space:]]}" ]]; then
  echo "openstack router list failed: $(cat "$err" 2>/dev/null)" >&2
  rm -f "$err"
  exit 1
fi
rm -f "$err"

failures=0
while IFS= read -r router_id; do
  [[ -z "$router_id" ]] && continue
  router_name=$(printf '%s' "$routers_json" | jq -r --arg id "$router_id" '.[] | select((.ID // .id) == $id) | .Name // .name // $id' 2>/dev/null | head -1)

  err=$(mktemp)
  agents_json=$(openstack --insecure network agent list --router "$router_id" -f json 2>"$err")
  if [[ $? -ne 0 || -z "${agents_json//[[:space:]]}" ]]; then
    echo "Router ${router_id} (${router_name}): failed to list agents: $(cat "$err" 2>/dev/null)" >&2
    rm -f "$err"
    failures=$((failures + 1))
    continue
  fi
  rm -f "$err"

  active_count=$(printf '%s' "$agents_json" | jq '[.[] | select(.["HA State"] == "active")] | length' 2>/dev/null)
  if [[ "$active_count" != "1" ]]; then
    echo "Router ${router_id} (${router_name}): ${active_count:-0} active HA agents (expected 1)" >&2
    printf '%s' "$agents_json" | jq -r '.[] | "  agent \(.ID) ha_state=\(.["HA State"]) host=\(.Host)"' 2>/dev/null >&2
    failures=$((failures + 1))
  fi
done < <(
  printf '%s' "$routers_json" | jq -r '
    .[] |
    select(
      .["HA State"] == true or .["HA state"] == true or .["is_ha"] == true
    ) | .ID // .id
  ' 2>/dev/null
)

if [[ "$failures" -gt 0 ]]; then
  exit 1
fi