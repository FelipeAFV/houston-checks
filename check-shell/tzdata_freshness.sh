#!/usr/bin/env bash
#
# Name: tzdata freshness
# Description: Ubuntu tzdata must not be older than the local APT candidate or the configured IANA version floor.
#

export LC_ALL=C

MINIMUM_TZDATA_VERSION="${MINIMUM_TZDATA_VERSION:-auto}"
TZDATA_ZI_PATH="${TZDATA_ZI_PATH:-/usr/share/zoneinfo/tzdata.zi}"
declare -a FAILURES=()
declare -a WARNINGS=()

exit_with_configuration_error() {
  printf 'tzdata freshness configuration error: %s\n' "$*" >&2
  exit 2
}

record_failure() {
  FAILURES+=("$*")
}

record_warning() {
  WARNINGS+=("$*")
}

extract_iana_version() {
  local package_version=$1
  local version_without_epoch=$package_version

  if [[ "$version_without_epoch" == *:* ]]; then
    version_without_epoch=${version_without_epoch#*:}
  fi

  if [[ "$version_without_epoch" =~ ^([0-9]{4}[a-z]+)([-+~].*)?$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi

  return 1
}

calculate_automatic_minimum_version() {
  local current_year_month current_year current_month previous_year

  current_year_month=$(date -u '+%Y %m')
  read -r current_year current_month <<<"$current_year_month"

  current_month=$((10#$current_month))

  # IANA has historically published the year's first release by April 30.
  # Before May require the previous year's "b"; from May require this year's "a".
  if ((current_month <= 4)); then
    previous_year=$((10#$current_year - 1))
    printf '%sb' "$previous_year"
  else
    printf '%sa' "$current_year"
  fi
}

compare_dpkg_versions() {
  local first=$1
  local operator=$2
  local second=$3
  local compare_rc

  if dpkg --compare-versions "$first" "$operator" "$second"; then
    return 0
  else
    compare_rc=$?
  fi

  if ((compare_rc == 1)); then
    return 1
  fi

  exit_with_configuration_error "could not compare versions '$first' and '$second'"
}

print_result() {
  for warning in "${WARNINGS[@]}"; do
    printf 'WARNING: %s\n' "$warning" >&2
  done

  if ((${#FAILURES[@]} > 0)); then
    printf 'tzdata freshness check failed:\n' >&2
    for failure in "${FAILURES[@]}"; do
      printf '  - %s\n' "$failure" >&2
    done
    exit 1
  fi

  printf 'tzdata is sufficiently up to date\n'
  exit 0
}

for command_name in apt-cache awk date dpkg dpkg-query; do
  command -v "$command_name" >/dev/null 2>&1 \
    || exit_with_configuration_error "required command not found: $command_name"
done

if ! package_info=$(dpkg-query -W -f='${Status}\t${Version}' tzdata 2>/dev/null); then
  printf 'tzdata package is not installed\n' >&2
  exit 1
fi

package_status=${package_info%%$'\t'*}
installed_version=${package_info#*$'\t'}

if [[ "$package_status" != 'install ok installed' || -z "$installed_version" || "$installed_version" == "$package_info" ]]; then
  printf 'tzdata package is not fully installed (status: %s)\n' "${package_status:-unknown}" >&2
  exit 1
fi

if ! installed_iana_version=$(extract_iana_version "$installed_version"); then
  exit_with_configuration_error "could not extract the IANA version from installed package '$installed_version'"
fi

if [[ "$MINIMUM_TZDATA_VERSION" == auto ]]; then
  minimum_iana_version=$(calculate_automatic_minimum_version) \
    || exit_with_configuration_error 'could not calculate the automatic minimum IANA version'
  minimum_source='automatic annual policy'
elif [[ "$MINIMUM_TZDATA_VERSION" =~ ^[0-9]{4}[a-z]+$ ]]; then
  minimum_iana_version=$MINIMUM_TZDATA_VERSION
  minimum_source='configured override'
else
  exit_with_configuration_error "MINIMUM_TZDATA_VERSION must be 'auto' or an IANA version such as 2026a"
fi

candidate_version=''
apt_installed_version=''
# Read only the package metadata already available on the host; do not run apt update.
if apt_policy=$(apt-cache policy tzdata 2>/dev/null); then
  apt_installed_version=$(awk '$1 == "Installed:" {print $2; exit}' <<<"$apt_policy")
  candidate_version=$(awk '$1 == "Candidate:" {print $2; exit}' <<<"$apt_policy")

  if [[ -n "$apt_installed_version" && "$apt_installed_version" != '(none)' && "$apt_installed_version" != "$installed_version" ]]; then
    record_warning \
      "apt-cache reports installed version $apt_installed_version, but dpkg-query reports $installed_version"
  fi

  if [[ -n "$candidate_version" && "$candidate_version" != '(none)' ]]; then
    if compare_dpkg_versions "$candidate_version" gt "$installed_version"; then
      record_failure \
        "a newer tzdata package is available in the local APT cache: $candidate_version"
    fi
  else
    candidate_version='unavailable'
    record_warning 'APT candidate is unavailable; using the IANA version floor as the offline fallback'
  fi
else
  candidate_version='unavailable'
  record_warning 'apt-cache policy failed; using the IANA version floor as the offline fallback'
fi

if compare_dpkg_versions "$installed_iana_version" lt "$minimum_iana_version"; then
  record_failure "installed IANA version $installed_iana_version is older than required $minimum_iana_version"
fi

tzdata_zi_version='unavailable'
if [[ -r "$TZDATA_ZI_PATH" ]]; then
  tzdata_zi_version=$(awk \
    'NR == 1 && $1 == "#" && $2 == "version" {print $3; exit}' \
    "$TZDATA_ZI_PATH")

  if [[ ! "$tzdata_zi_version" =~ ^[0-9]{4}[a-z]+$ ]]; then
    record_warning "$TZDATA_ZI_PATH does not contain a recognizable IANA version header"
    tzdata_zi_version='unknown'
  elif [[ "$tzdata_zi_version" != "$installed_iana_version" ]]; then
    record_failure \
      "$TZDATA_ZI_PATH reports $tzdata_zi_version, but the installed package reports $installed_iana_version"
  fi
else
  record_warning "$TZDATA_ZI_PATH is not readable; package metadata is the only installed-version source"
fi

printf 'Installed package: %s\n' "$installed_version"
printf 'Candidate package: %s\n' "$candidate_version"
printf 'Installed IANA version: %s\n' "$installed_iana_version"
printf 'tzdata.zi IANA version: %s\n' "$tzdata_zi_version"
printf 'Required IANA version: %s (%s)\n' "$minimum_iana_version" "$minimum_source"

print_result
