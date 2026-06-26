#!/usr/bin/env bash
#
# Name: MD check deadlock fix
# Description: RAID5 arrays require followArray and mdcheck patches; skip when no RAID5.
#

has_raid5=0
raid5_names=()
for level_file in /sys/block/md*/md/level; do
  if [[ -f "$level_file" ]]; then
    level=$(tr -d '\r\n' <"$level_file" 2>/dev/null || true)
    if [[ "$level" == "raid5" ]]; then
      has_raid5=1
      md_name=$(basename "$(dirname "$(dirname "$level_file")")")
      raid5_names+=("$md_name")
    fi
  fi
done

if [[ "$has_raid5" -eq 0 ]]; then
  printf 'No RAID5 arrays present; check not applicable\n'
  exit 0
fi

follow_script=/usr/local/bin/followArray.sh
if [[ ! -x "$follow_script" ]]; then
  echo "followArray script does not exist or is not executable: ${follow_script}" >&2
  exit 1
fi

follow_svc=/etc/systemd/system/followArray.service
if [[ ! -f "$follow_svc" ]]; then
  echo "followArray.service is not present" >&2
  exit 1
fi

svc_state=$(systemctl is-enabled followArray.service 2>/dev/null || echo missing)
if [[ "$svc_state" == "masked" || "$svc_state" == "masked-runtime" ]]; then
  echo "followArray.service is masked" >&2
  exit 1
fi

for md_name in "${raid5_names[@]}"; do
  if ! grep -q "$md_name" "$follow_svc" 2>/dev/null; then
    if ! grep -q "RAID_DEVICE=\"${md_name}\"" "$follow_script" 2>/dev/null; then
      echo "RAID ${md_name} is not configured in followArray service or script" >&2
      exit 1
    fi
  fi
done

for unit_file in /lib/systemd/system/mdcheck_start.service /lib/systemd/system/mdcheck_continue.service; do
  if [[ ! -f "$unit_file" ]]; then
    echo "Missing ${unit_file}" >&2
    exit 1
  fi
  if ! grep -q 'ExecStartPre=/bin/systemctl start followArray.service' "$unit_file" 2>/dev/null; then
    echo "File ${unit_file} is unpatched (missing followArray ExecStartPre)" >&2
    exit 1
  fi
done

printf 'RAID5 mdcheck deadlock fix OK (%s)\n' "${raid5_names[*]}"