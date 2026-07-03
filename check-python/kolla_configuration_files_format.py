#!/usr/bin/env python3
# Name: Kolla configuration files format
# Description: Validate syntax of Kolla config files under /etc/whitecloud/.kolla on this host.
"""Validate ini/conf/json/yaml syntax for Kolla configuration files (runs locally on target node)."""

from __future__ import annotations

import configparser
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

KOLLA_ROOT = Path("/etc/whitecloud/.kolla")

CONFIG_KIND_LABELS = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".ini": "ini/conf",
    ".conf": "ini/conf",
}


def get_file_extension(path: Path) -> str:
    return path.suffix.lower()


def config_kind(path: Path) -> str:
    return CONFIG_KIND_LABELS.get(get_file_extension(path), "other")


def should_ignore_duplicate(allowlist: list, path: str, section: str, option: str) -> bool:
    for entry in allowlist:
        if not isinstance(entry, dict):
            continue
        if not path.endswith(str(entry.get("file", ""))):
            continue
        for allow in entry.get("allow") or []:
            if not isinstance(allow, dict):
                continue
            if allow.get("section") == section and option in (allow.get("options") or []):
                return True
    return False


def validate_ini_file(path: Path, content: str, allowlist: list) -> str | None:
    config = configparser.ConfigParser()
    try:
        config.read_string(content)
    except configparser.MissingSectionHeaderError:
        return None
    except configparser.DuplicateOptionError as exc:
        if should_ignore_duplicate(allowlist, str(path), exc.section, exc.option):
            return None
        return f"{path}: {exc}"
    except configparser.ParsingError as exc:
        return f"{path}: {exc}"
    except Exception as exc:
        return f"{path}: {exc}"
    return None


def validate_json_file(path: Path, content: str) -> str | None:
    try:
        json.loads(content)
    except json.JSONDecodeError as exc:
        return f"{path}: {exc}"
    return None


def validate_yaml_file(path: Path, content: str) -> str | None:
    try:
        import yaml
    except ImportError:
        print(f"skipping {path}: PyYAML not installed", file=sys.stderr)
        return None
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return f"{path}: {exc}"
    return None


def build_config_validators(allowlist: list) -> dict[str, Callable[[Path, str], str | None]]:
    return {
        ".yaml": validate_yaml_file,
        ".yml": validate_yaml_file,
        ".json": validate_json_file,
        ".ini": lambda p, c: validate_ini_file(p, c, allowlist),
        ".conf": lambda p, c: validate_ini_file(p, c, allowlist),
    }


def validate_file(
    path: Path,
    content: str,
    validators: dict[str, Callable[[Path, str], str | None]],
) -> str | None:
    validator = validators.get(get_file_extension(path))
    return validator(path, content) if validator else None


def discover_config_files(
    root: Path,
    validators: dict[str, Callable[[Path, str], str | None]],
) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if get_file_extension(path) in validators:
                found.append(path)
    return sorted(found)


def read_file_content(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except PermissionError:
        print(f"skipping {path}: permission denied", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"skipping {path}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    print(f"checking Kolla config under {KOLLA_ROOT}")

    if not KOLLA_ROOT.is_dir():
        print(f"directory not found: {KOLLA_ROOT}", file=sys.stderr)
        return 1

    allowlist: list = []
    validators = build_config_validators(allowlist)
    paths = discover_config_files(KOLLA_ROOT, validators)
    if not paths:
        print(f"no config files found under {KOLLA_ROOT}", file=sys.stderr)
        return 1

    malformed: list[str] = []
    validated: list[Path] = []

    for path in paths:
        content = read_file_content(path)
        if not content:
            continue
        error = validate_file(path, content, validators)
        if error:
            malformed.append(error)
        else:
            validated.append(path)

    if malformed:
        print("Kolla config files malformed:", file=sys.stderr)
        for line in malformed:
            print(f"  {line}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {"ini/conf": 0, "json": 0, "yaml": 0, "other": 0}
    for path in validated:
        kind = config_kind(path)
        counts[kind if kind in counts else "other"] += 1

    for path in validated:
        print(f"  {path}: syntax OK ({config_kind(path)})")

    print(
        f"Kolla config: {len(validated)} file(s) syntax OK "
        f"(ini/conf: {counts['ini/conf']}, json: {counts['json']}, yaml: {counts['yaml']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
