#!/usr/bin/env bash
#
# Name: Prometheus exporter check
# Description: Check if Prometheus exporters are being scrapped by the Prometheus server.
#

exporters_names=$(docker ps --format '{{.Names}}' | grep -E '(^prometheus_|.*exporter$|cadvisor$)')

exporters_no_scraped=""

for exporter in $exporters_names; do
  
  network_mode=$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$exporter")
  exporter_port=""
  if [[ "$network_mode" != "host" ]]; then
    exporter_port=$(docker inspect \
    --format '{{range $containerPort, $bindings := .NetworkSettings.Ports}}{{range $bindings}}{{.HostPort}}{{end}}{{end}}' \
    "$exporter")
  else

    main_pid=$(docker inspect --format '{{.State.Pid}}' "$exporter")
    container_pids=$(docker top "$exporter" | awk 'NR>1 {print $2}')
    listen_address=""
    while read -r pid; do
        listen_address=$(sudo nsenter -t "$main_pid" -n ss -ltnp | grep "pid=$pid," | awk '{print $4}')
        [[ -n "$listen_address" ]] && break
    done <<< "$container_pids"
    exporter_port=$(printf "$listen_address" | awk -F: '{print $NF}')

  fi
  printf "Checking if $exporter is being scrapped on port $exporter_port"
  if [[ -z "$exporter_port" ]]; then
    printf "Could not determine listening port for $exporter"
    exporters_no_scraped="$exporters_no_scraped $exporter"
    continue
  fi
  if sudo timeout 60 tcpdump -nn -c 1 -i any "tcp dst port $exporter_port" >/dev/null 2>&1; then
    printf "Exporter $exporter is being scrapped"
  else
    printf "Exporter $exporter is not being scrapped"
    exporters_no_scraped="$exporters_no_scraped $exporter"
  fi
done

if [[ -n "$exporters_no_scraped" ]]; then
  printf "Prometheus exporters are not being scrapped"
  printf "Not scrapped exporters: %s\n" "$exporters_no_scraped"
  printf 'CHECK_RC=1\n'
  exit 1
else
  printf "Prometheus exporters are being scrapped"
  printf 'CHECK_RC=0\n'
  exit 0
fi