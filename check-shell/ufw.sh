#!/usr/bin/env bash
#
# Name: UFW enabled
# Description: UFW firewall must be active on the target host.
#

if ! command -v ufw >/dev/null 2>&1; then
  echo "ufw command is required but not found" >&2
  exit 1
fi

status=$(sudo -n ufw status 2>/dev/null || false)

if [[ -z "$status" ]]; then
  status=$(ufw status 2>/dev/null || false)
fi

if [[ "$status" =~ Status:[[:space:]]+([Aa]ctive|[Ee]nabled) ]]; then
  exit 0
fi

echo "ufw is not active (got: ${status:-empty/unknown})" >&2
exit 1