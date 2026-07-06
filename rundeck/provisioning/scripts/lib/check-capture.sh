#!/usr/bin/env bash
# Shared capture helpers for run-check-step.sh.
# Emits CHECK_BODY_B64 + RUNDECK:DATA for Rundeck log filters (curl-step on Rundeck reads b64).

capture_validate_id() {
  case "${CHECK_ID}" in
    ''|*[!a-z0-9_-]*)
      printf '[check] invalid check id: %s\n' "${CHECK_ID}" >&2
      return 2
      ;;
  esac
}

capture_slug() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}

capture_ts() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

capture_log() {
  printf '[check %s] (%s) %s\n' "${CHECK_ID}" "$(capture_ts)" "$*"
}

capture_init() {
  CAPTURE_FILE=$(mktemp "${TMPDIR:-/tmp}/check-capture.${CHECK_ID}.XXXXXX")
  trap 'rm -f "${CAPTURE_FILE}"' EXIT
}

capture_b64_file() {
  if base64 -w0 /dev/null >/dev/null 2>&1; then
    base64 -w0 "$1"
  else
    base64 <"$1" | tr -d '\n'
  fi
}

capture_emit_b64() {
  local b64
  b64=$(capture_b64_file "${CAPTURE_FILE}")
  printf 'CHECK_BODY_B64=%s\n' "${b64}"
  printf 'RUNDECK:DATA:check_output_b64=%s\n' "${b64}"
}

capture_resolve_shell_path() {
  local check_dir=$1
  local path="${check_dir%/}/${CHECK_ID}.sh"
  if [[ -r "${path}" ]]; then
    printf '%s' "${path}"
    return 0
  fi
  return 1
}

capture_resolve_python_path() {
  local check_dir=$1
  local path="${check_dir%/}/${CHECK_ID}.py"
  if [[ -r "${path}" ]]; then
    printf '%s' "${path}"
    return 0
  fi
  local flat_dir flat_path
  flat_dir="$(dirname "${check_dir%/}")"
  flat_path="${flat_dir}/${CHECK_ID}.py"
  if [[ -r "${flat_path}" ]]; then
    printf '%s' "${flat_path}"
    return 0
  fi
  return 1
}

capture_run() {
  local mode=$1 script_path=$2
  capture_log "start (mode=${mode} script=${script_path} capture=${CAPTURE_FILE})"
  set +e
  if [[ "${mode}" == shell ]]; then
    (
      set -e
      # shellcheck source=/dev/null
      source "${script_path}"
    ) 2>&1 | tee -a "${CAPTURE_FILE}"
  else
    python3 "${script_path}" 2>&1 | tee -a "${CAPTURE_FILE}"
  fi
  local rc=${PIPESTATUS[0]}
  if [[ "$rc" -eq 0 ]]; then
    local declared_rc
    declared_rc=$(grep -E '^CHECK_RC=[0-9]+$' "${CAPTURE_FILE}" 2>/dev/null | tail -1 | cut -d= -f2-)
    if [[ -n "$declared_rc" ]]; then
      rc=$declared_rc
    fi
  fi
  set -e
  capture_log "finished rc=${rc}"
  capture_emit_b64
  rm -f "${CAPTURE_FILE}"
  return "${rc}"
}
