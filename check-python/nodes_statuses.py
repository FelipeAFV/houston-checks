#!/usr/bin/env python3
# Name: Kubernetes nodes statuses
# Description: Kubernetes nodes must be schedulable, Ready, and without resource pressure.
"""Check Kubernetes node conditions via kubectl on this host."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PRESSURE_CHECKS = (
    ("MemoryPressure", "memory-pressure"),
    ("DiskPressure", "disk-pressure"),
    ("PIDPressure", "pid-pressure"),
    ("NetworkUnavailable", "network-unavailable"),
)


def resolve_kubeconfig() -> str:
    val = (os.environ.get("KUBECONFIG") or "").strip()
    if val:
        return val
    return str(Path.home() / ".kube" / "config")


def kubectl_nodes_json() -> dict:
    kubeconfig = resolve_kubeconfig()
    print(f"  kubeconfig={kubeconfig}")
    proc = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "get", "nodes", "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"kubectl get nodes failed: {err}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kubectl returned invalid JSON: {exc}") from exc


def node_condition_true(node: dict, condition_type: str) -> bool:
    conditions = (node.get("status") or {}).get("conditions") or []
    for condition in conditions:
        if condition.get("type") == condition_type:
            return condition.get("status") == "True"
    return False


def node_failure_lines(node: dict) -> list[str]:
    name = (node.get("metadata") or {}).get("name") or "?"
    lines: list[str] = []
    if (node.get("spec") or {}).get("unschedulable"):
        lines.append(f"{name}: unschedulable")
    if not node_condition_true(node, "Ready"):
        lines.append(f"{name}: not Ready")
    for cond, label in PRESSURE_CHECKS:
        if node_condition_true(node, cond):
            lines.append(f"{name}: {label}")
    return lines


def node_summary(node: dict) -> str:
    name = (node.get("metadata") or {}).get("name") or "?"
    sched = "unschedulable" if (node.get("spec") or {}).get("unschedulable") else "schedulable"
    ready = "Ready" if node_condition_true(node, "Ready") else "NotReady"
    pressures = [label for cond, label in PRESSURE_CHECKS if node_condition_true(node, cond)]
    pressure_txt = ", ".join(pressures) if pressures else "no pressure"
    return f"{name}: {ready}, {sched}, {pressure_txt}"


def main() -> int:
    try:
        payload = kubectl_nodes_json()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    items = payload.get("items") or []
    if not items:
        print("no nodes returned by kubectl", file=sys.stderr)
        return 1

    failures = "\n".join(
        f"  {line}"
        for node in items
        for line in node_failure_lines(node)
    )

    if failures:
        print("Kubernetes node status failures:", file=sys.stderr)
        print(failures, file=sys.stderr)
        return 1

    for node in sorted(items, key=lambda n: (n.get("metadata") or {}).get("name") or ""):
        print(f"  {node_summary(node)}")
    print(f"Kubernetes nodes: {len(items)} node(s) OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
