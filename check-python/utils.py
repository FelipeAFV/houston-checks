from __future__ import annotations
from collections.abc import Generator
from pathlib import Path
from xml.etree import ElementTree

import csv
import io
import os
import re
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


def exec_cmd(cmd: str) -> subprocess.CompletedProcess:
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
    return proc.stdout.strip()


def parse_csv_str(csv_str_header: str, csv_str_rows: str) -> list[dict]:
    return csv.DictReader(io.StringIO(csv_str_rows.strip()), fieldnames=csv_str_header.strip().split(","))


def parse_xml_str(xml_str: str, pattern: str) -> Generator[ElementTree]:
    for raw_xml_substr in re.split(pattern, xml_str):
        xml_substr = raw_xml_substr.strip()
        if not xml_substr:
            continue
        yield ElementTree.fromstring(xml_substr)
