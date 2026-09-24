from __future__ import annotations
from collections.abc import Generator
from configparser import ConfigParser
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


def get_whitemon_pod(root_cmd: str, whitemon_pod_prefix: str) -> str:
    cmd = f"{root_cmd} get pods --no-headers -o custom-columns=':metadata.name' | grep '^{whitemon_pod_prefix}' | head -n 1"
    return exec_cmd(cmd)


def cat_file(file_path: str) -> subprocess.CompletedProcess:
    cmd = f"cat {file_path}"
    return exec_cmd(cmd)


def parse_csv_str(csv_str_header: str, csv_str_rows: str) -> list[dict]:
    return csv.DictReader(io.StringIO(csv_str_rows.strip()), fieldnames=csv_str_header.strip().split(","))


def parse_xml_str(xml_str: str, pattern: str) -> Generator[ElementTree]:
    for raw_xml_substr in re.split(pattern, xml_str):
        xml_substr = raw_xml_substr.strip()
        if not xml_substr:
            continue
        yield ElementTree.fromstring(xml_substr)


def parse_ini_config(config_file: str) -> dict:
    config = ConfigParser(default_section=None)
    config.read_string(config_file)
    return {section: dict(config[section]) for section in config.sections()}
