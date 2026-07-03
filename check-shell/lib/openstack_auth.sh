# lib/openstack_auth.sh — optional admin-openrc sourcing for OpenStack CLI checks.

load_openstack_credentials() {
  local rc="${OPENSTACK_ADMIN_RC:-}"
  [[ -z "$rc" ]] && return 0
  if [[ ! -f "$rc" ]]; then
    echo "OPENSTACK_ADMIN_RC not found: $rc" >&2
    return 1
  fi
  set -a
  # shellcheck source=/dev/null
  source "$rc"
  set +a
}
