#!/usr/bin/env bash
#
# Name: APT unattended-upgrades disabled
# Description: APT Periodic unattended upgrades must be explicitly set to 0.
#

line=$(sudo -n apt-config dump APT::Periodic::Unattended-Upgrade 2>/dev/null || false)

if [[ -z "$line" ]]; then
  line=$(apt-config dump APT::Periodic::Unattended-Upgrade 2>/dev/null || false)
fi

if [[ -z "$line" ]]; then
  echo 'Missing APT::Periodic::Unattended-Upgrade in apt-config dump (need explicit "0"; try sudo NOPASSWD?)' >&2
  exit 1
fi

if [[ "$line" =~ ^APT::Periodic::Unattended-Upgrade[[:space:]]+\"0\"[[:space:]]*\;?$ ]]; then
  exit 0
fi

echo "unattended-upgrades must be DISABLED (want APT::Periodic::Unattended-Upgrade \"0\"; got: ${line})" >&2
exit 1