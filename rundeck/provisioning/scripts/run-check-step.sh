#!/usr/bin/env bash
# Remote-exec: run check-shell or check-python; emit b64 for Rundeck curl-step (ping on Rundeck).
#
# Usage: run-check-step.sh shell <check_id> [check_shell_dir]
#        run-check-step.sh python <check_id> [check_python_dir]
# Env: NODE_NAME, JOB_EXECID.

MODE="${1:?missing mode (shell|python)}"
CHECK_ID="${2:?missing check id}"

case "${MODE}" in
  shell)
    CHECK_DIR="${3:-${CHECK_SHELL_DIR:-${CHECK_SCRIPT_BASE:-/var/tmp/rundeck}}}"
    ;;
  python)
    CHECK_DIR="${3:-${CHECK_PYTHON_DIR:-${CHECK_SCRIPT_BASE:+${CHECK_SCRIPT_BASE}/check-python}}}"
    CHECK_DIR="${CHECK_DIR:-/var/tmp/rundeck/check-python}"
    ;;
  *)
    printf '[check] mode must be shell or python, got %s\n' "${MODE}" >&2
    exit 2
    ;;
esac

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib/check-capture.sh
source "${SCRIPT_DIR}/lib/check-capture.sh"

capture_validate_id || exit $?

if [[ "${MODE}" == shell ]]; then
  if ! SCRIPT_PATH=$(capture_resolve_shell_path "${CHECK_DIR}"); then
    printf '[check %s] missing or unreadable: %s/%s.sh\n' "${CHECK_ID}" "${CHECK_DIR}" "${CHECK_ID}" >&2
    exit 127
  fi
else
  if ! SCRIPT_PATH=$(capture_resolve_python_path "${CHECK_DIR}"); then
    printf '[check %s] missing or unreadable: %s/%s.py\n' "${CHECK_ID}" "${CHECK_DIR}" "${CHECK_ID}" >&2
    exit 127
  fi
fi

capture_init
capture_run "${MODE}" "${SCRIPT_PATH}"
exit $?
