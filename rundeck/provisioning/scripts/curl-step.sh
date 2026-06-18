#!/usr/bin/env bash
# Localexec on Rundeck server: POST check output to Uptime ping URL (ok/fail).
#
# Usage:
#   curl-step.sh fail <ping_url>
#   curl-step.sh auto <ping_url>
#   curl-step.sh from-data <check_rc> <check_output_b64> <ping_url>
#
# Optional: UPTIME_PING_BASE_URL — rewrite ping URL host (Rundeck host network vs docker DNS).

if [[ "${1:-}" == "from-data" ]]; then
  CHECK_RC="${2:-1}"
  CHECK_BODY_B64="${3:-}"
  PING_URL="${4:?missing ping url}"
  export CHECK_RC CHECK_BODY_B64
  set -- auto "${PING_URL}"
fi

REQUESTED_OUTCOME="${1:?missing outcome (fail|auto)}"
PING_URL="${2:?missing ping url}"

_auto_rundeck_exit() {
  [[ "${REQUESTED_OUTCOME}" == "auto" ]] || return 0
  exit "${CHECK_RC:-1}"
}

case "${REQUESTED_OUTCOME}" in
  auto)
    OUTCOME=ok
    [[ "${CHECK_RC:-1}" != "0" ]] && OUTCOME=fail
    ;;
  fail) OUTCOME=fail ;;
  *) printf '[curl] outcome must be fail or auto, got %s\n' "${REQUESTED_OUTCOME}" >&2; exit 2 ;;
esac

if [[ -z "${PING_URL}" || "${PING_URL}" == "null" ]]; then
  printf '[curl] empty ping_url — skipping Uptime notification\n' >&2
  _auto_rundeck_exit
  exit 0
fi

_ping_origin="${UPTIME_PING_BASE_URL:-${PUBLIC_BASE_URL:-}}"
if [[ -n "${_ping_origin}" ]]; then
  _ping_origin="${_ping_origin%/}"
  PING_URL=$(printf '%s' "${PING_URL}" | sed -E "s|^https?://[^/]+|${_ping_origin}|")
fi

TARGET_URL="${PING_URL}"
if [[ "${OUTCOME}" == "fail" ]]; then
  _ping_base="${PING_URL%%\?*}"
  _ping_qs="${PING_URL#"${_ping_base}"}"
  TARGET_URL="${_ping_base%/}/fail${_ping_qs}"
fi

BODY_FILE=""
CLEANUP_FILE=""
trap 'if [[ -n "${CLEANUP_FILE}" && -f "${CLEANUP_FILE}" ]]; then rm -f "${CLEANUP_FILE}"; fi' EXIT

if [[ -n "${CHECK_BODY_B64:-}" ]]; then
  CLEANUP_FILE=$(mktemp)
  if printf '%s' "${CHECK_BODY_B64}" | base64 -d >"${CLEANUP_FILE}" 2>/dev/null && [[ -s "${CLEANUP_FILE}" ]]; then
    BODY_FILE="${CLEANUP_FILE}"
  else
    rm -f "${CLEANUP_FILE}"
    CLEANUP_FILE=""
  fi
fi

if [[ -z "${BODY_FILE}" && "${OUTCOME}" == "fail" ]]; then
  CLEANUP_FILE=$(mktemp)
  if [[ "${REQUESTED_OUTCOME}" == "auto" && "${CHECK_RC:-0}" != "0" ]]; then
    printf 'Check failed (rc=%s) but capture body was not passed to curl-step.\n' "${CHECK_RC}" >"${CLEANUP_FILE}"
  else
    printf 'Rundeck step failed before check output was captured.\n' >"${CLEANUP_FILE}"
  fi
  BODY_FILE="${CLEANUP_FILE}"
fi

CURL_OPTS=(-fsS -m "${CURL_TIMEOUT:-15}" --retry "${CURL_RETRY:-2}")
if [[ -n "${BODY_FILE}" ]]; then
  CURL_OPTS+=(-X POST --data-binary "@${BODY_FILE}")
else
  CURL_OPTS+=(-X GET)
fi

_body_desc="${BODY_FILE:-<empty>}"
if [[ -n "${BODY_FILE}" && -f "${BODY_FILE}" ]]; then
  _body_desc="$(wc -c <"${BODY_FILE}" | tr -d '[:space:]') bytes"
fi
printf '[curl] %s -> %s (body=%s)\n' "${OUTCOME}" "${TARGET_URL}" "${_body_desc}"
curl "${CURL_OPTS[@]}" "${TARGET_URL}"
_auto_rundeck_exit
