#!/usr/bin/env bash
#
# Name: Grub needs reboot
# Description: /etc/default/grub must not be newer than last boot (proc/1 mtime).
#

grub_file=/etc/default/grub

if [[ ! -f "$grub_file" ]]; then
  echo "Missing ${grub_file}" >&2
  exit 1
fi

grub_mtime=$(stat -c %Y "$grub_file" 2>/dev/null || false)
boot_mtime=$(stat -c %Y /proc/1 2>/dev/null || false)

if [[ -z "$grub_mtime" || -z "$boot_mtime" ]]; then
  echo "Could not read mtime for grub or last boot" >&2
  exit 1
fi

if [[ "$grub_mtime" -gt "$boot_mtime" ]]; then
  echo "Server reboot is required due to Grub changes" >&2
  exit 1
fi
