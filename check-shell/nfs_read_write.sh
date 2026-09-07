#!/usr/bin/env bash
#
# Name: NFS read/write
# Description: Configured NFS mounts must support writing, reading back, and deleting a dummy file.
#

NFS_PATHS="${NFS_PATHS:-/data/nfs_1,/data/nfs_2}"
DUMMY_FILE_SIZE_MB="${DUMMY_FILE_SIZE_MB:-1}"
NFS_IO_TIMEOUT_SECONDS="${NFS_IO_TIMEOUT_SECONDS:-120}"
export LC_ALL=C

# Prevent accidental writes larger than 1 GiB to local temporary storage and NFS.
MAX_DUMMY_FILE_SIZE_MB=1024
MAX_NFS_IO_TIMEOUT_SECONDS=3600

REFERENCE_FILE=""
FAILURES=0
SUCCESSES=0
declare -a PRIVILEGE=()
declare -a DUMMY_FILES=()
declare -a MOUNT_PATHS=()

trim_whitespace() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

exit_with_configuration_error() {
  printf 'NFS read/write configuration error: %s\n' "$*" >&2
  exit 2
}

validate_nfs_path() {
  local path=$1

  [[ -n "$path" ]] \
    || exit_with_configuration_error "NFS_PATHS contains an empty path"
  [[ "$path" == /* ]] \
    || exit_with_configuration_error "NFS path must be absolute: $path"
  [[ "$path" != "/" ]] \
    || exit_with_configuration_error "refusing to use the filesystem root as an NFS test path"
  [[ "$path" != *$'\n'* && "$path" != *$'\r'* ]] \
    || exit_with_configuration_error "NFS paths must not contain line breaks"
}

record_failure() {
  local path=$1
  shift
  printf 'NFS path %s: %s\n' "$path" "$*" >&2
  FAILURES=$((FAILURES + 1))
}

run_io() {
  "${PRIVILEGE[@]}" timeout --signal=TERM --kill-after=5 \
    "${NFS_IO_TIMEOUT_SECONDS}" "$@"
}

cleanup_dummy() {
  local index=$1
  local dummy_file=${DUMMY_FILES[$index]:-}

  [[ -n "$dummy_file" ]] || return 0
  if run_io rm -f -- "$dummy_file" >/dev/null 2>&1; then
    DUMMY_FILES[$index]=""
    return 0
  fi
  return 1
}

cleanup() {
  local index

  for index in "${!DUMMY_FILES[@]}"; do
    cleanup_dummy "$index" || true
  done
  if [[ -n "$REFERENCE_FILE" ]]; then
    rm -f -- "$REFERENCE_FILE" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for command_name in cmp dd findmnt mktemp rm stat timeout; do
  command -v "$command_name" >/dev/null 2>&1 \
    || exit_with_configuration_error "required command not found: $command_name"
done

TEST_COMMAND=$(type -P test)
[[ -n "$TEST_COMMAND" ]] \
  || exit_with_configuration_error "required external command not found: test"

[[ -n "$NFS_PATHS" ]] \
  || exit_with_configuration_error "NFS_PATHS must contain at least one absolute mount path"

[[ "$DUMMY_FILE_SIZE_MB" =~ ^[0-9]{1,4}$ ]] \
  || exit_with_configuration_error "DUMMY_FILE_SIZE_MB must be a positive integer"
dummy_file_size=$((10#$DUMMY_FILE_SIZE_MB))
((dummy_file_size >= 1 && dummy_file_size <= MAX_DUMMY_FILE_SIZE_MB)) \
  || exit_with_configuration_error \
    "DUMMY_FILE_SIZE_MB must be between 1 and ${MAX_DUMMY_FILE_SIZE_MB}"

[[ "$NFS_IO_TIMEOUT_SECONDS" =~ ^[0-9]{1,4}$ ]] \
  || exit_with_configuration_error "NFS_IO_TIMEOUT_SECONDS must be a positive integer"
nfs_io_timeout=$((10#$NFS_IO_TIMEOUT_SECONDS))
((nfs_io_timeout >= 1 && nfs_io_timeout <= MAX_NFS_IO_TIMEOUT_SECONDS)) \
  || exit_with_configuration_error \
    "NFS_IO_TIMEOUT_SECONDS must be between 1 and ${MAX_NFS_IO_TIMEOUT_SECONDS}"
NFS_IO_TIMEOUT_SECONDS=$nfs_io_timeout

remaining_paths=$NFS_PATHS
while :; do
  if [[ "$remaining_paths" == *,* ]]; then
    path_entry=${remaining_paths%%,*}
    remaining_paths=${remaining_paths#*,}
    last_path=0
  else
    path_entry=$remaining_paths
    last_path=1
  fi

  path_entry=$(trim_whitespace "$path_entry")
  validate_nfs_path "$path_entry"
  MOUNT_PATHS+=("${path_entry%/}")
  ((last_path == 1)) && break
done

if ((EUID != 0)); then
  command -v sudo >/dev/null 2>&1 \
    || exit_with_configuration_error "sudo is required when the check does not run as root"
  sudo -n true >/dev/null 2>&1 \
    || exit_with_configuration_error "passwordless sudo is required for NFS I/O operations"
  PRIVILEGE=(sudo -n)
fi

REFERENCE_FILE=$(mktemp "${TMPDIR:-/tmp}/houston-nfs-reference.XXXXXX") \
  || exit_with_configuration_error "could not create the local reference file"

if ! timeout --signal=TERM --kill-after=5 "$NFS_IO_TIMEOUT_SECONDS" \
  dd if=/dev/urandom of="$REFERENCE_FILE" bs=1M count="$dummy_file_size" status=none; then
  printf 'Could not create the %s MiB local reference file\n' "$dummy_file_size" >&2
  exit 1
fi

for mount_path in "${MOUNT_PATHS[@]}"; do
  printf 'Checking NFS read/write/delete on %s (%s MiB dummy file)\n' \
    "$mount_path" "$dummy_file_size"

  if ! file_type=$(run_io stat -Lc '%F' -- "$mount_path" 2>/dev/null); then
    record_failure "$mount_path" "path is missing, inaccessible, or timed out"
    continue
  fi
  if [[ "$file_type" != "directory" ]]; then
    record_failure "$mount_path" "path is not a directory"
    continue
  fi

  if ! filesystem_type=$(run_io findmnt --noheadings --output FSTYPE \
    --target "$mount_path" 2>/dev/null); then
    record_failure "$mount_path" "could not determine the mounted filesystem type"
    continue
  fi
  filesystem_type=$(trim_whitespace "$filesystem_type")
  case "$filesystem_type" in
    nfs|nfs4) ;;
    *)
      record_failure "$mount_path" \
        "expected an NFS mount but found filesystem type '${filesystem_type:-unknown}'"
      continue
      ;;
  esac

  if ! dummy_file=$(run_io mktemp \
    "${mount_path}/.houston-nfs-rw.XXXXXX" 2>/dev/null); then
    record_failure "$mount_path" "could not create the dummy file"
    continue
  fi
  dummy_index=${#DUMMY_FILES[@]}
  DUMMY_FILES+=("$dummy_file")

  if ! run_io dd if="$REFERENCE_FILE" of="$dummy_file" bs=1M \
    conv=fsync status=none; then
    record_failure "$mount_path" "could not write and sync the dummy file"
    cleanup_dummy "$dummy_index" || \
      printf 'NFS path %s: emergency cleanup failed for %s\n' \
        "$mount_path" "$dummy_file" >&2
    continue
  fi

  run_io cmp --silent -- "$REFERENCE_FILE" "$dummy_file"
  cmp_rc=$?
  if [[ $cmp_rc == 0 ]]; then
    if ! run_io rm -f -- "$dummy_file"; then
      record_failure "$mount_path" "could not delete the dummy file: $dummy_file"
      continue
    fi
    if ! run_io "$TEST_COMMAND" ! -e "$dummy_file"; then
      record_failure "$mount_path" "dummy file still exists after deletion: $dummy_file"
      continue
    fi

    DUMMY_FILES[$dummy_index]=""
    SUCCESSES=$((SUCCESSES + 1))
    printf 'NFS path %s: write, read, content verification, and delete succeeded\n' \
      "$mount_path"
  elif [[ $cmp_rc == 1 ]]; then
    record_failure "$mount_path" "dummy file content did not match after reading it back"
    cleanup_dummy "$dummy_index" || \
      printf 'NFS path %s: emergency cleanup failed for %s\n' \
        "$mount_path" "$dummy_file" >&2
  else
    record_failure "$mount_path" \
      "could not read and compare the dummy file (exit ${cmp_rc})"
    cleanup_dummy "$dummy_index" || \
      printf 'NFS path %s: emergency cleanup failed for %s\n' \
        "$mount_path" "$dummy_file" >&2
  fi
done

if ((FAILURES > 0)); then
  printf 'NFS read/write check failed: %s path(s) passed, %s path(s) failed\n' \
    "$SUCCESSES" "$FAILURES" >&2
  exit 1
fi

printf 'NFS read/write check passed: %s path(s) validated\n' "$SUCCESSES"
exit 0
