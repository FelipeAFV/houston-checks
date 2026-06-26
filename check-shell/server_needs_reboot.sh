#!/usr/bin/env bash
#
# Name: Server needs reboot
# Description: /var/run/reboot-required must not exist (pending kernel/package reboot).
#

reboot_flag=/var/run/reboot-required

if [[ ! -f "$reboot_flag" ]]; then
  printf 'CHECK_RC=0\n'
  exit 0
fi

pkgs_file=/var/run/reboot-required.pkgs
msg="Server reboot is required"
if [[ -f "$pkgs_file" ]]; then
  pkgs=$(cat "$pkgs_file" 2>/dev/null || true)
  if [[ -n "$pkgs" ]]; then
    msg="${msg}: ${pkgs}"
  fi
fi
echo "$msg" >&2
printf 'CHECK_RC=1\n'
exit 1