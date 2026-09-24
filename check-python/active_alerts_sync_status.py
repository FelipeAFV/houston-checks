#!/usr/bin/env python3
# Name: Active Prometheus' Alertmanager and Keep Alerts check
# Description: Active Prometheus' Alertmanager and Keep Alerts, must be synced.
"""Check active alerts in Prometheus' Alertmanager and Keep via kubectl on this host."""

from __future__ import annotations
from utils import exec_cmd, resolve_kubeconfig, get_whitemon_pod

import json
import os
import sys


KUBECONFIG = resolve_kubeconfig()

WHITEMON_NAMESPACE = os.environ.get("WHITEMON_NAMESPACE", "whitemon")
WHITEMON_POD_PREFIX = os.environ.get("WHITEMON_POD_PREFIX", "whitemon-grafana")
WHITEMON_CONTAINER = os.environ.get("WHITEMON_CONTAINER", "grafana")
KEEP_NOC_API_KEY = os.environ.get("KEEP_NOC_API_KEY", "keep-noc-api-key")

ROOT_CMD = f"kubectl --kubeconfig {KUBECONFIG} -n {WHITEMON_NAMESPACE}"

PROMETHEUS_ALERTMANAGER_POD_PREFIX = "alertmanager-whitemon-alertmanager"
KEEP_BACKEND_POD_PREFIX = "whitemon-keep-backend"


def get_prometheus_alertmanager_active_alerts(whitemon_pod: str) -> list[json]:
    cmd = f"""{ROOT_CMD} exec {whitemon_pod} -c {WHITEMON_CONTAINER} -- sh -c 'curl -s "http://whitemon-alertmanager:9093/api/v2/alerts?active=true&silenced=false"'"""
    try:
        return json.loads(exec_cmd(cmd))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kubectl returned invalid JSON: {exc}") from exc


def get_keep_active_alerts(whitemon_pod: str) -> list[json]:
    cmd = f"""{ROOT_CMD} exec {whitemon_pod} -c {WHITEMON_CONTAINER} -- sh -c 'curl -s "http://whitemon-keep-backend:8080/alerts" -H "X-API-KEY: {KEEP_NOC_API_KEY}"'"""
    try:
        return json.loads(exec_cmd(cmd))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kubectl returned invalid JSON: {exc}") from exc


def active_alerts_synced(prometheus_alertmanager_active_alerts: list[dict], keep_active_alerts: list[dict]) -> bool:
    prometheus_alertmanager_active_alerts_fingerprints = {alert["fingerprint"] for alert in prometheus_alertmanager_active_alerts}
    keep_active_alerts_fingerprints = {alert["fingerprint"] for alert in keep_active_alerts if alert["status"] == "firing"}
    return prometheus_alertmanager_active_alerts_fingerprints.issubset(keep_active_alerts_fingerprints)


def main() -> int:

    try:

        prometheus_alertmanager_pod = get_whitemon_pod(ROOT_CMD, PROMETHEUS_ALERTMANAGER_POD_PREFIX)
        keep_backend_pod = get_whitemon_pod(ROOT_CMD, KEEP_BACKEND_POD_PREFIX)

        if prometheus_alertmanager_pod and keep_backend_pod:

            whitemon_pod = get_whitemon_pod(ROOT_CMD, WHITEMON_POD_PREFIX)
            if not whitemon_pod:
                print("Pod doesn't exist")
                return 1

            prometheus_alertmanager_active_alerts = get_prometheus_alertmanager_active_alerts(whitemon_pod)
            if not isinstance(prometheus_alertmanager_active_alerts, list):
                print(f"Prometheus' Alertmanager API: {prometheus_alertmanager_active_alerts}")
                return 1

            keep_active_alerts = get_keep_active_alerts(whitemon_pod)
            if not isinstance(keep_active_alerts, list):
                print(f"Keep API: {keep_active_alerts}")
                return 1
            if not active_alerts_synced(prometheus_alertmanager_active_alerts, keep_active_alerts):
                print("Active alerts are not synced")
                return 1

        elif not prometheus_alertmanager_pod:
            print("Prometheus' Alertmanager API pod not found.")
            return 0
        elif not keep_backend_pod:
            print("Keep API pod not found.")
            return 0
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    print("Active alerts are synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
