#!/bin/sh
# Entry point for the houston-provision Rundeck job (localexec — no shell wrapper).
# Rundeck injects secret job options as RD_OPTION_*; Config.from_env() reads
# rundeck/provisioning/config.yaml plus those secrets.
set -eu

SCM_BASE="${SCM_BASE_DIR:-${RD_OPTION_SCM_BASE_DIR:-/home/rundeck/server/data/provision}}"
SCRIPTS_DIR="${RUNDECK_SCRIPTS_DIR:-${RD_OPTION_RUNDECK_SCRIPTS_DIR:-${SCM_BASE}/rundeck/provisioning/scripts}}"
MAIN="${SCRIPTS_DIR}/src/__main__.py"

if [ ! -f "${MAIN}" ]; then
  echo "[provision] FATAL: provisioner not found: ${MAIN}" >&2
  echo "[provision] SCM_BASE=${SCM_BASE} SCRIPTS_DIR=${SCRIPTS_DIR}" >&2
  ls -la "${SCRIPTS_DIR}" 2>/dev/null || true
  echo "[provision] Ensure rundeck/provisioning/scripts/ exists in the Git SCM checkout (SCM_BASE_DIR)" >&2
  exit 1
fi

export SCM_BASE_DIR="${SCM_BASE}"
export PYTHONPATH="${SCRIPTS_DIR}"
exec /usr/bin/python3 -m src
