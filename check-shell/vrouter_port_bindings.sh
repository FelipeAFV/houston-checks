#!/usr/bin/env bash
#
# Name: VRouter port bindings
# Description: Router ports (except HA interfaces) must bind to the active L3 agent host.
#

if ! command -v openstack >/dev/null 2>&1; then
  echo "openstack CLI is required but not found" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/openstack_auth.sh
source "${SCRIPT_DIR}/lib/openstack_auth.sh"
load_openstack_credentials || exit 1

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
  rm -f "$err"
  if [[ -z "${agents_json//[[:space:]]}" ]]; then
    continue
  fi

  active_hosts=$(printf '%s' "$agents_json" | jq -r '.[] | select(.["HA State"] == "active") | .Host' 2>/dev/null)
  if [[ -z "$active_hosts" ]]; then
    continue
  fi

  err=$(mktemp)
  ports_json=$(openstack --insecure port list --router "$router_id" -f json 2>"$err")
  rm -f "$err"
  if [[ -z "${ports_json//[[:space:]]}" ]]; then
    continue
  fi

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    port_id=$(printf '%s' "$line" | jq -r '.ID // .id' 2>/dev/null)
    owner=$(printf '%s' "$line" | jq -r '."Device Owner" // .device_owner' 2>/dev/null)
    binding=$(printf '%s' "$line" | jq -r '."Binding Host" // .binding_host_id' 2>/dev/null)
    if [[ "$owner" == "network:router_ha_interface" ]]; then
      continue
    fi
    ok=0
    while IFS= read -r host; do
      [[ -z "$host" ]] && continue
      if [[ "$binding" == "$host" ]]; then
        ok=1
        break
      fi
    done <<<"$active_hosts"
    if [[ "$ok" -eq 0 ]]; then
      echo "Router ${router_id} (${router_name}): port ${port_id} bound to ${binding:-<none>}, expected one of: $(echo "$active_hosts" | tr '\n' ' ')" >&2
      failures=$((failures + 1))
    fi
  done < <(printf '%s' "$ports_json" | jq -c '.[]' 2>/dev/null)
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