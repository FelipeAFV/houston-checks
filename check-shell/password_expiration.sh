#!/usr/bin/env bash
#
# Name: Password expiration
# Description: Non-root user passwords must expire beyond the configured warning window and must not be set to never expire.
#

# PASSWORD_EXPIRATION_WARNING_DAYS is a non-negative integer.
# Check UIDs 1000 through 65533. Only read aging data.
# Exit codes: 0 = passed/no applicable users, 1 = policy failure, 2 = check error.
PASSWORD_EXPIRATION_WARNING_DAYS="${PASSWORD_EXPIRATION_WARNING_DAYS-30}"
export LC_ALL=C

FAILURES=0
ERRORS=0
CHECKED_USERS=0
declare -a PRIVILEGE=()

exit_with_configuration_error() {
  printf 'Password expiration check error: %s\n' "$*" >&2
  exit 2
}

record_failure() {
  printf 'User %s: %s\n' "$1" "$2" >&2
  FAILURES=$((FAILURES + 1))
}

record_error() {
  printf 'User %s: check error: %s\n' "$1" "$2" >&2
  ERRORS=$((ERRORS + 1))
}

[[ "$PASSWORD_EXPIRATION_WARNING_DAYS" =~ ^[0-9]+$ ]] \
  || exit_with_configuration_error 'PASSWORD_EXPIRATION_WARNING_DAYS must be a non-negative integer'

for command_name in getent awk chage date; do
  command -v "$command_name" >/dev/null 2>&1 \
    || exit_with_configuration_error "required command not found: $command_name"
done

today=$(date +%F) || exit_with_configuration_error 'could not determine the current date'
# Use the target host calendar date, then normalize dates to UTC to avoid DST
# changing the length of a day when calculating the warning window.
today_epoch=$(date -u -d "$today" +%s) \
  || exit_with_configuration_error 'could not parse the current date'
threshold_epoch=$(date -u -d "$today +${PASSWORD_EXPIRATION_WARNING_DAYS} days" +%s) \
  || exit_with_configuration_error 'could not calculate the warning deadline from PASSWORD_EXPIRATION_WARNING_DAYS'

passwd_output=$(getent passwd) \
  || exit_with_configuration_error 'could not enumerate users with getent passwd'
users=$(awk -F: '$1 != "root" && $3 ~ /^[0-9]+$/ && $3 >= 1000 && $3 < 65534 {print $1}' <<<"$passwd_output") \
  || exit_with_configuration_error 'could not select users from getent passwd'

if [[ -z "$users" ]]; then
  printf 'No applicable users found (non-root UIDs 1000 through 65533)\n'
  exit 0
fi

if ((EUID != 0)); then
  command -v sudo >/dev/null 2>&1 \
    || exit_with_configuration_error 'sudo is required when the check does not run as root'

  # Validate the exact privileged command because generic sudo credential checks
  # may fail even when chage is allowed by a command-specific NOPASSWD rule.
  first_user=${users%%$'\n'*}
  sudo -n chage -l -- "$first_user" >/dev/null 2>&1 \
    || exit_with_configuration_error "sudo cannot read password aging data for user $first_user"

  PRIVILEGE=(sudo -n)
fi

printf 'Checking password expiration as of %s (warning window: %s days, inclusive)\n' \
  "$today" "$PASSWORD_EXPIRATION_WARNING_DAYS"

while IFS= read -r user_name; do
  CHECKED_USERS=$((CHECKED_USERS + 1))
  if ! chage_output=$("${PRIVILEGE[@]}" chage -l -- "$user_name"); then
    record_error "$user_name" 'chage -l failed while reading password aging data'
    continue
  fi

  if ! expiration=$(awk -F: '
    {
      key = $1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (key == "Password expires") {
        count++
        value = $2
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      }
    }
    END {
      if (count != 1 || value == "") exit 1
      print value
    }
  ' <<<"$chage_output"); then
    record_error "$user_name" 'missing or ambiguous Password expires field in chage output'
    continue
  fi

  case "$expiration" in
    never)
      record_failure "$user_name" 'password is set to never expire'
      continue
      ;;
    'password must be changed')
      record_failure "$user_name" 'password must be changed'
      continue
      ;;
  esac

  if [[ ! "$expiration" =~ ^[[:alpha:]]{3}[[:space:]]+[0-9]{1,2},[[:space:]]+[0-9]{4}$ ]]; then
    record_error "$user_name" "unrecognized password expiration date: $expiration"
    continue
  fi
  if ! expiration_epoch=$(date -u -d "$expiration" +%s); then
    record_error "$user_name" "invalid password expiration date: $expiration"
    continue
  fi

  if ((expiration_epoch <= threshold_epoch)); then
    days_remaining=$(((expiration_epoch - today_epoch) / 86400))
    record_failure "$user_name" "password expires on $expiration ($days_remaining day(s) remaining; warning window: $PASSWORD_EXPIRATION_WARNING_DAYS days)"
  fi
done <<<"$users"

printf 'Password expiration: %s user(s) checked, %s policy failure(s), %s error(s)\n' \
  "$CHECKED_USERS" "$FAILURES" "$ERRORS"

if ((ERRORS > 0)); then
  exit 2
fi
if ((FAILURES > 0)); then
  exit 1
fi

printf 'All applicable user passwords expire beyond the warning window\n'
exit 0
