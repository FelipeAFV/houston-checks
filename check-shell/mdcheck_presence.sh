#!/usr/bin/env bash
#
# Name: MD check presence
# Description: mdcheck systemd units must exist when MD RAID is present; skip if no arrays.
#

has_md=0
for level_file in /sys/block/md*/md/level; do
  if [[ -f "$level_file" ]]; then
    has_md=1
    break
  fi
done

if [[ "$has_md" -eq 0 ]]; then
  printf 'No MD RAID arrays present; check not applicable\n'
  exit 0
fi

check_service_unmasked() {
  local unit=$1
  local state
  state=$(systemctl is-enabled "$unit" 2>/dev/null || echo missing)
  if [[ "$state" == "masked" || "$state" == "masked-runtime" ]]; then
    echo "${unit}: masked (${state})" >&2
    return 1
  fi
  if [[ "$state" == "missing" || "$state" == "not-found" ]]; then
    echo "${unit}: not present" >&2
    return 1
  fi
  if ! systemctl cat "$unit" >/dev/null 2>&1; then
    echo "${unit}: unit file missing" >&2
    return 1
  fi
  return 0
}

check_timer_enabled() {
  local unit=$1
  local state
  state=$(systemctl is-enabled "$unit" 2>/dev/null || echo missing)
  if [[ "$state" == "missing" || "$state" == "not-found" ]]; then
    echo "${unit}: not present" >&2
    return 1
  fi
  if [[ "$state" != "enabled" && "$state" != "static" ]]; then
    echo "${unit}: not enabled (got ${state})" >&2
    return 1
  fi
  return 0
}

failures=0
for unit in mdcheck_start.service mdcheck_continue.service; do
  if ! check_service_unmasked "$unit"; then
    failures=$((failures + 1))
  fi
done
for unit in mdcheck_start.timer mdcheck_continue.timer; do
  if ! check_timer_enabled "$unit"; then
    failures=$((failures + 1))
  fi
done

if [[ "$failures" -gt 0 ]]; then
  echo "One or more mdcheck services are not present or masked/disabled" >&2
  exit 1
fi
printf 'All mdcheck services and timers are present and enabled\n'