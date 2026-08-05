#!/usr/bin/env bash
#
# Name: Active Whitemon Alerts check
# Description: Check if there are any active alerts in Whitemon.
#

WHITEMON_NAMESPACE="${WHITEMON_NAMESPACE:-whitemon}"

alertmanager_svc=$(kubectl get svc -n "$WHITEMON_NAMESPACE" | awk '/whitemon-alertmanager/ {print $1; exit}')

json=""
alertmanager_svc_ip=$(kubectl get svc -n "$WHITEMON_NAMESPACE" "$alertmanager_svc" -o jsonpath='{.spec.clusterIP}')
alertmanager_cluster_svc_port=$(kubectl get svc -n "$WHITEMON_NAMESPACE" "$alertmanager_svc" -o jsonpath='{.spec.ports[0].port}')
grafana_pod=$(kubectl get pods -n "$WHITEMON_NAMESPACE" -l app.kubernetes.io/component=grafana -o jsonpath='{.items[0].metadata.name}')
json=$(kubectl exec -it -n "$WHITEMON_NAMESPACE" "$grafana_pod" -- curl -fsS "http://$alertmanager_svc_ip:$alertmanager_cluster_svc_port/api/v2/alerts")

printf "Checking for active alerts in Whitemon for namespace $WHITEMON_NAMESPACE in service $alertmanager_svc at $alertmanager_svc_ip:$alertmanager_cluster_svc_port.\n"

if command -v jq >/dev/null 2>&1; then
    active_alerts=$(jq '[.[] | select(.status.state=="active")] | length' <<< "$json")
else
    active_alerts=$(python3 -c '
import json, sys
alerts = json.load(sys.stdin)
print(sum(1 for a in alerts if a["status"]["state"] == "active"))
' <<< "$json")
fi

if [[ "$active_alerts" -gt 0 ]]; then
    printf "There are %d active alerts in Whitemon.\n" "$active_alerts"
    printf 'CHECK_RC=1\n'
    exit 1
else
    printf "There are no active alerts in Whitemon.\n"
    printf 'CHECK_RC=0\n'
    exit 0
fi
