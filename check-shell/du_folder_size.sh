#!/usr/bin/env bash
#
# Name: Directory size
# Description: Configured directories must have an apparent size strictly below their configured limits; missing paths are ignored.
#

# Paths and size limits are comma-separated and paired in the same order.
# Example: FOLDER_PATHS=/home/whitestack,/var/log
#          FOLDER_LIMIT_SIZES=1Gi,10Mi
# Size suffixes are case-sensitive: Ki, Mi, Gi (surrounding spaces are ignored; no final B).
# Paths cannot contain commas or control characters. Defaults apply when unset.
FOLDER_PATHS="${FOLDER_PATHS-/home/whitestack}"
FOLDER_LIMIT_SIZES="${FOLDER_LIMIT_SIZES-1Gi}"
export LC_ALL=C

declare -a FOLDERS=() LIMITS=() EXISTING_PATHS=() PRIVILEGE=()
declare -A LIMIT_BY_PATH=()
DU_STDERR=""
FAILURES=0
MEASURED=0
SKIPPED=0

exit_with_configuration_error() {
  printf 'Directory size configuration error: %s\n' "$*" >&2
  exit 2
}

exit_with_measurement_error() {
  printf 'Directory size measurement failed: %s\n' "$*" >&2
  exit 1
}

convert_limit_to_bytes() {
  local value=$1 bytes

  bytes=$(numfmt --from=iec-i -- "$value" 2>&1) \
    || exit_with_configuration_error \
      "invalid limit '$value': $bytes. Expected a positive byte count or a positive IEC binary size such as 50Ki, 10Mi or 1Gi"

  [ "$bytes" -gt 0 ] 2>/dev/null \
    || exit_with_configuration_error "invalid limit '$value': limit must be greater than zero"

  printf '%s' "$bytes"
}

validate_list() {
  local name=$1 value=$2
  [[ -n "$value" && "$value" != ,* && "$value" != *, && "$value" != *,,* ]] \
    || exit_with_configuration_error "$name must be a comma-separated list without empty entries"
  [[ ! "$value" =~ [[:cntrl:]] ]] \
    || exit_with_configuration_error "$name must not contain control characters"
}

trim_whitespace() {
  local value=$1

  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"

  printf '%s' "$value"
}

parse_list() {
  local value=$1 destination=$2 item
  local -a entries=()
  local -n result=$destination

  local IFS=','
  read -r -a entries <<< "$value"

  for item in "${entries[@]}"; do
    result+=("$(trim_whitespace "$item")")
  done
}

validate_list FOLDER_PATHS "$FOLDER_PATHS"
validate_list FOLDER_LIMIT_SIZES "$FOLDER_LIMIT_SIZES"
parse_list "$FOLDER_PATHS" FOLDERS
parse_list "$FOLDER_LIMIT_SIZES" LIMITS

[[ ${#FOLDERS[@]} -eq ${#LIMITS[@]} ]] \
  || exit_with_configuration_error 'FOLDER_PATHS and FOLDER_LIMIT_SIZES must have the same number of entries'

for command_name in du stat mktemp rm numfmt; do
  command -v "$command_name" >/dev/null 2>&1 \
    || exit_with_configuration_error "required command not found: $command_name"
done

for index in "${!FOLDERS[@]}"; do
  [[ "${FOLDERS[$index]}" == /* ]] \
    || exit_with_configuration_error "path must be absolute: ${FOLDERS[$index]}"
  
  limit=$(convert_limit_to_bytes "${LIMITS[$index]}") || exit $?
  LIMIT_BY_PATH["${FOLDERS[$index]}"]="$limit"
done

if ((EUID != 0)); then
  command -v sudo >/dev/null 2>&1 \
    || exit_with_configuration_error 'sudo is required when the check does not run as root'
  PRIVILEGE=(sudo -n)
fi

# Use privileged stat to distinguish missing paths from access errors.
missing_path_error='^stat: cannot statx? .+: No such file or directory$'
for folder in "${FOLDERS[@]}"; do
  if stat_output=$("${PRIVILEGE[@]}" stat --format='%F' -- "$folder" 2>&1); then
    EXISTING_PATHS+=("$folder")
  else
    stat_rc=$?
    if [[ $stat_rc == 1 && "$stat_output" =~ $missing_path_error && "$stat_output" != *$'\n'* ]]; then
      printf 'Skipping missing path: %s\n' "$folder"
      SKIPPED=$((SKIPPED + 1))
    else
      exit_with_measurement_error "cannot inspect $folder (exit $stat_rc): $stat_output"
    fi
  fi
done

if ((${#EXISTING_PATHS[@]} == 0)); then
  printf 'No configured paths exist; nothing to measure (missing paths are ignored).\n'
  exit 0
fi

cleanup() {
  if [[ -n "$DU_STDERR" ]]; then
    rm -f -- "$DU_STDERR"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

DU_STDERR=$(mktemp "${TMPDIR:-/tmp}/houston-du-size.XXXXXX") \
  || exit_with_measurement_error 'could not create the temporary stderr capture file'

# Run du once so hard links shared between paths are counted once.
# -b reports apparent bytes.
# Capture du's exit code explicitly because Rundeck runs checks with `set -e`.
du_rc=0
du_output=$("${PRIVILEGE[@]}" du -sb -- "${EXISTING_PATHS[@]}" 2>"$DU_STDERR") \
  || du_rc=$?

if ((du_rc != 0)) || [[ -s "$DU_STDERR" ]]; then
  exit_with_measurement_error "du exited with $du_rc: $(<"$DU_STDERR")"
fi

# du may omit repeated paths or subdirectories counted under an earlier path.
while IFS=$'\t' read -r current_size measured_path; do
  [ "$current_size" -ge 0 ] 2>/dev/null \
    || exit_with_measurement_error "invalid byte count in du output: $current_size"
  [[ -n "$measured_path" && -n "${LIMIT_BY_PATH[$measured_path]+set}" ]] \
    || exit_with_measurement_error "unexpected path in du output: $measured_path"

  limit=${LIMIT_BY_PATH[$measured_path]}
  current_human=$(numfmt --to=iec-i --format="%.2f" "$current_size")
  limit_human=$(numfmt --to=iec-i --format="%.2f" "$limit")

  if ((current_size >= limit)); then
    printf 'FAIL: %s is %s; must be below %s\n' \
      "$measured_path" "$current_human" "$limit_human" >&2
    FAILURES=$((FAILURES + 1))
  else
    printf 'OK: %s is %s; limit is %s (exclusive)\n' \
      "$measured_path" "$current_human" "$limit_human"
  fi
  MEASURED=$((MEASURED + 1))
  
done <<< "$du_output"

((MEASURED > 0)) \
  || exit_with_measurement_error 'du did not return directory measurements'

if ((FAILURES > 0)); then
  printf 'Directory size check failed: %s limit(s) reached or exceeded.\n' "$FAILURES" >&2
  exit 1
fi

printf 'Directory size check passed: %s measurement(s), %s missing path(s) skipped.\n' \
  "$MEASURED" "$SKIPPED"
exit 0
