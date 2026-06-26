#!/usr/bin/env python3
# Name: CPU vulnerabilities (lscpu)
# Description: CPU microcode vulnerability mitigations must not report Vulnerable.
"""Check lscpu JSON on this host for unmitigated CPU vulnerabilities."""

from __future__ import annotations

import json
import subprocess
import sys


def parse_lscpu_fields(items: list) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        field = str(item.get("field", "")).strip(":")
        value = item.get("data")
        children = item.get("children") or []
        if value is not None and field:
            result[field] = str(value)
        if children:
            result.update(parse_lscpu_fields(children))
    return result


def vulnerability_fields(fields: dict[str, str]) -> dict[str, str]:
    return {
        field: data
        for field, data in fields.items()
        if "vulnerability" in field.lower() or "Vulnerable" in data
    }


def run_lscpu_json() -> dict:
    proc = subprocess.run(
        ["lscpu", "--output-all", "-J"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"lscpu failed: {err}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid lscpu JSON: {exc}") from exc


def main() -> int:
    try:
        payload = run_lscpu_json()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    fields = parse_lscpu_fields(payload.get("lscpu") or [])
    vuln_fields = vulnerability_fields(fields)
    failures = [
        f"{field} {data}"
        for field, data in vuln_fields.items()
        if data and "Vulnerable" in data
    ]
    if failures:
        print("CPU vulnerabilities not mitigated:", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return 1

    arch = fields.get("Architecture", fields.get("CPU op-mode(s)", ""))
    model = fields.get("Model name", "")
    if arch:
        print(f"  Architecture: {arch}")
    if model:
        print(f"  Model name: {model}")
    for field, data in sorted(vuln_fields.items()):
        print(f"  {field}: {data}")
    checked = len(vuln_fields)
    print(
        f"CPU vulnerabilities: none reported as Vulnerable "
        f"({checked} mitigation field(s) checked)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
