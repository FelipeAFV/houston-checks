from __future__ import annotations
from pathlib import Path

import os
import subprocess


def resolve_kubeconfig() -> str:
    val = (os.environ.get("KUBECONFIG") or "").strip()
    if val:
        return val
    return str(Path.home() / ".kube" / "config")


def kubectl_exec_cmd(cmd: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"{err}. Command: {cmd}, failed.")
    return proc


def get_whitemon_pod(root_cmd: str, whitemon_pod_prefix: str) -> str:
    cmd = f"{root_cmd} get pods --no-headers -o custom-columns=':metadata.name' | grep '^{whitemon_pod_prefix}' | head -n 1"
    proc = kubectl_exec_cmd(cmd)
    return proc.stdout.strip()
