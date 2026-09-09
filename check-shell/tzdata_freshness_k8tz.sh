#!/usr/bin/env bash
#
# Name: k8tz tzdata freshness
# Description: Validate the IANA tzdata version mounted by k8tz init containers.
#

export LC_ALL=C

MINIMUM_TZDATA_VERSION="${MINIMUM_TZDATA_VERSION:-auto}"
TZDATA_ZI_PATH="${TZDATA_ZI_PATH:-/usr/share/zoneinfo/tzdata.zi}"
TZDATA_DIRECTORY=${TZDATA_ZI_PATH%/*}
K8TZ_LABEL_SELECTOR="${K8TZ_LABEL_SELECTOR:-app.kubernetes.io/name=k8tz}"
K8TZ_INIT_CONTAINER_NAME="${K8TZ_INIT_CONTAINER_NAME:-k8tz}"
KUBECTL="${KUBECTL:-kubectl}"

declare -a FAILURES=()
declare -a INIT_RECORDS=()
declare -a IMAGE_IDS=()
declare -A CANDIDATES_BY_IMAGE=()
declare -A CONTAINERS_BY_POD_VOLUME=()
declare -A IMAGE_DESCRIPTIONS=()
declare -A SEEN_IMAGE_IDS=()
declare -A VOLUMES_BY_INIT=()

exit_with_configuration_error() {
  printf 'k8tz tzdata freshness configuration error: %s\n' "$*" >&2
  exit 2
}

record_failure() {
  FAILURES+=("$*")
}

calculate_automatic_minimum_version() {
  local current_year_month current_year current_month

  current_year_month=$(date -u '+%Y %m')
  read -r current_year current_month <<<"$current_year_month"

  if ((10#$current_month <= 4)); then
    printf '%sb' "$((10#$current_year - 1))"
  else
    printf '%sa' "$current_year"
  fi
}

extract_version_from_header() {
  local first_line=${1%%$'\n'*}

  first_line=${first_line%$'\r'}
  if [[ "$first_line" =~ ^#[[:space:]]+version[[:space:]]+([0-9]{4}[a-z])[[:space:]]*$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

read_tzdata_version_from_container() {
  local namespace=$1
  local pod=$2
  local container=$3
  local first_line version

  if first_line=$("$KUBECTL" exec -n "$namespace" "$pod" -c "$container" -- \
    /bin/sh -c 'IFS= read -r line < "$1"; printf "%s\n" "$line"' sh "$TZDATA_ZI_PATH" 2>/dev/null) \
    && version=$(extract_version_from_header "$first_line"); then
    printf '%s' "$version"
    return 0
  fi

  if first_line=$("$KUBECTL" exec -n "$namespace" "$pod" -c "$container" -- \
    head -n 1 "$TZDATA_ZI_PATH" 2>/dev/null) \
    && version=$(extract_version_from_header "$first_line"); then
    printf '%s' "$version"
    return 0
  fi

  return 1
}

print_result() {
  if ((${#FAILURES[@]} == 0)); then
    printf 'k8tz timezone data is sufficiently up to date\n'
    exit 0
  fi

  printf 'k8tz tzdata freshness check failed:\n' >&2
  for failure in "${FAILURES[@]}"; do
    printf '  - %s\n' "$failure" >&2
  done
  exit 1
}

for command_name in date "$KUBECTL"; do
  command -v "$command_name" >/dev/null 2>&1 \
    || exit_with_configuration_error "required command not found: $command_name"
done

if [[ "$MINIMUM_TZDATA_VERSION" == auto ]]; then
  minimum_iana_version=$(calculate_automatic_minimum_version) \
    || exit_with_configuration_error 'could not calculate the automatic minimum IANA version'
  minimum_source='automatic annual policy'
elif [[ "$MINIMUM_TZDATA_VERSION" =~ ^[0-9]{4}[a-z]$ ]]; then
  minimum_iana_version=$MINIMUM_TZDATA_VERSION
  minimum_source='configured override'
else
  exit_with_configuration_error "MINIMUM_TZDATA_VERSION must be 'auto' or an IANA version in YYYYx format"
fi

deployment_template='{{range .items}}{{.metadata.namespace}}/{{.metadata.name}}{{"\n"}}{{end}}'
if ! deployment_output=$("$KUBECTL" get deployments.apps -A \
  -l "$K8TZ_LABEL_SELECTOR" -o "go-template=${deployment_template}" 2>/dev/null); then
  exit_with_configuration_error 'could not query k8tz deployments'
fi

mapfile -t deployments <<<"$deployment_output"
# Expect one cluster-wide k8tz controller: no match means it is unavailable,
# while multiple matches make the controller configuration ambiguous.
if [[ -z "$deployment_output" ]]; then
  record_failure "no deployment matched selector '$K8TZ_LABEL_SELECTOR'"
elif ((${#deployments[@]} > 1)); then
  record_failure "multiple deployments matched selector '$K8TZ_LABEL_SELECTOR'"
fi

if ((${#FAILURES[@]} > 0)); then
  printf 'Required IANA version: %s (%s)\n' "$minimum_iana_version" "$minimum_source"
  print_result
fi

# M = workload container mount
# B = k8tz bootstrap/init container mount
# I = init container status
pod_template='{{range .items}}{{$ns := .metadata.namespace}}{{$pod := .metadata.name}}'
pod_template+='{{$phase := .status.phase}}'
pod_template+='{{range .spec.containers}}{{$container := .name}}{{range .volumeMounts}}'
pod_template+='M|{{$ns}}|{{$pod}}|{{$phase}}|{{$container}}|{{.name}}|{{.mountPath}}{{"\n"}}{{end}}{{end}}'
pod_template+='{{range .spec.initContainers}}{{$init := .name}}{{range .volumeMounts}}'
pod_template+='B|{{$ns}}|{{$pod}}|{{$phase}}|{{$init}}|{{.name}}|{{.mountPath}}{{"\n"}}{{end}}{{end}}'
pod_template+='{{range .status.initContainerStatuses}}'
pod_template+='I|{{$ns}}|{{$pod}}|{{$phase}}|{{.name}}|{{.image}}|{{.imageID}}{{"\n"}}{{end}}{{end}}'

if ! pod_output=$("$KUBECTL" get pods -A -o "go-template=${pod_template}" 2>/dev/null); then
  exit_with_configuration_error 'could not inspect pods across all namespaces'
fi

while IFS='|' read -r record_type namespace pod phase first second third; do
  [[ "$phase" == Running ]] || continue
  case "$record_type" in
    M)
      # Fields: first=workload container, second=volume name, third=mount path.
      # Stores: key=namespace|pod|volume, value=workload container name(s).
      if [[ "$third" == "$TZDATA_DIRECTORY" ]]; then
        CONTAINERS_BY_POD_VOLUME["${namespace}|${pod}|${second}"]+="${first}"$'\n'
      fi
      ;;
    B)
      # Fields: first=init container, second=volume name, third=mount path.
      # Stores: key=namespace|pod|init container, value=volume name.
      if [[ "$first" == "$K8TZ_INIT_CONTAINER_NAME" && "$third" == /mnt/zoneinfo ]]; then
        VOLUMES_BY_INIT["${namespace}|${pod}|${first}"]=$second
      fi
      ;;
    I)
      # Fields: first=init container, second=image, third=image ID.
      # Stores: namespace|pod|image|image ID records.
      if [[ "$first" == "$K8TZ_INIT_CONTAINER_NAME" ]]; then
        INIT_RECORDS+=("${namespace}|${pod}|${second}|${third}")
      fi
      ;;
  esac
done <<<"$pod_output"

for init_record in "${INIT_RECORDS[@]}"; do
  IFS='|' read -r namespace pod image image_id <<<"$init_record"
  volume_name=${VOLUMES_BY_INIT["${namespace}|${pod}|${K8TZ_INIT_CONTAINER_NAME}"]:-}
  if [[ -z "$volume_name" ]]; then
    record_failure "init container $K8TZ_INIT_CONTAINER_NAME in ${namespace}/${pod} does not mount /mnt/zoneinfo"
    continue
  fi

  containers=${CONTAINERS_BY_POD_VOLUME["${namespace}|${pod}|${volume_name}"]:-}
  if [[ -z "$containers" ]]; then
    record_failure "volume $volume_name from init container $K8TZ_INIT_CONTAINER_NAME is not mounted at $TZDATA_DIRECTORY in ${namespace}/${pod}"
    continue
  fi

  if [[ -z "$image_id" ]]; then
    record_failure "pod ${namespace}/${pod} has init container $K8TZ_INIT_CONTAINER_NAME without an image ID"
    continue
  fi

  if [[ -z "${SEEN_IMAGE_IDS[$image_id]+x}" ]]; then
    SEEN_IMAGE_IDS["$image_id"]=1
    IMAGE_IDS+=("$image_id")
    IMAGE_DESCRIPTIONS["$image_id"]="${image} (${image_id})"
  fi

  while IFS= read -r container; do
    [[ -n "$container" ]] || continue
    CANDIDATES_BY_IMAGE["$image_id"]+="${namespace}|${pod}|${container}"$'\n'
  done <<<"$containers"
done

if ((${#INIT_RECORDS[@]} == 0)); then
  record_failure "no running pod has the k8tz init container '$K8TZ_INIT_CONTAINER_NAME'"
fi

printf 'k8tz deployment: %s\n' "${deployments[0]}"
printf 'k8tz init container: %s\n' "$K8TZ_INIT_CONTAINER_NAME"
printf 'Required IANA version: %s (%s)\n' "$minimum_iana_version" "$minimum_source"

for image_id in "${IMAGE_IDS[@]}"; do
  installed_iana_version=''
  while IFS='|' read -r namespace pod container; do
    if installed_iana_version=$(read_tzdata_version_from_container "$namespace" "$pod" "$container"); then
      break
    fi
  done <<<"${CANDIDATES_BY_IMAGE[$image_id]}"

  description=${IMAGE_DESCRIPTIONS[$image_id]}
  if [[ -z "$installed_iana_version" ]]; then
    record_failure "could not read $TZDATA_ZI_PATH from a workload using $description"
    continue
  fi

  printf 'Detected IANA version: %s [%s]\n' "$installed_iana_version" "$description"
  if [[ "$installed_iana_version" < "$minimum_iana_version" ]]; then
    record_failure \
      "$description provides IANA version $installed_iana_version, older than required $minimum_iana_version"
  fi
done

print_result
