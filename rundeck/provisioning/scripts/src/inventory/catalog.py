"""Catalog parsing — checks.yaml (check definitions and groups)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

from src.inventory import paths
from src.utils.util import load_yaml_file

_CATALOG_INSTANCES: dict[str, ChecksCatalog] = {}


@dataclass
class ChecksCatalog:
    """Parsed checks.yaml with O(1) lookups by check id and group."""

    checks_path: str
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    check_ids: list[str] = field(default_factory=list)
    ids_by_group: dict[str, list[str]] = field(default_factory=dict)
    args_by_group: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, checks_path: str) -> ChecksCatalog:
        key = os.path.abspath(checks_path)
        if key not in _CATALOG_INSTANCES:
            data = load_yaml_file(checks_path)
            raw = data if isinstance(data, dict) else {}
            by_id: dict[str, dict[str, Any]] = {}
            ids_by_group: dict[str, set[str]] = {}
            for entry in raw.get("checks") or []:
                if not isinstance(entry, dict):
                    continue
                rel = validate_catalog_path(entry)
                script_stem = paths.check_id_from_path(rel)
                explicit_id = entry.get("id")
                if explicit_id is not None:
                    check_id = paths.validate_check_id(str(explicit_id))
                else:
                    check_id = script_stem
                spec = dict(entry)
                spec["path"] = rel
                spec["script_stem"] = script_stem
                by_id[check_id] = spec
                for group_id, group_spec in spec.get("groups").items() or []:
                    ids_by_group.setdefault(str(group_id), set()).add(check_id)

            _CATALOG_INSTANCES[key] = cls(
                checks_path=checks_path,
                by_id=by_id,
                check_ids=sorted(by_id.keys()),
                ids_by_group={g: sorted(ids) for g, ids in ids_by_group.items()},
            )
        return _CATALOG_INSTANCES[key]

    def spec(self, check_id: str) -> dict[str, Any]:
        """Return catalog entry for check_id (empty dict if missing)."""
        spec = self.by_id.get(check_id)
        return dict(spec) if spec else {}

    def group_check_ids(self, group_id: str) -> list[str]:
        """Return sorted check ids whose groups list includes group_id."""
        return list(self.ids_by_group.get(group_id, []))

    def validate_script_paths(self, scm_base: str) -> bool:
        """Verify every catalog check has a readable script under scm_base."""
        ok = True
        for check_id in self.check_ids:
            spec = self.by_id[check_id]
            try:
                rel = validate_catalog_path(spec)
                full = paths.resolve_check_path(scm_base, rel)
            except ValueError as exc:
                print(f"check {check_id}: {exc}", file=sys.stderr)
                ok = False
                continue
            if not full.is_file():
                print(
                    f"check {check_id} ({rel}): script not found under {scm_base}",
                    file=sys.stderr,
                )
                ok = False
        return ok

    def validate_groups(self, inv_children: dict[str, Any]) -> bool:
        """Verify every group referenced by a check exists in inventory."""
        missing = False
        for check_id, spec in self.by_id.items():
            rel = validate_catalog_path(spec)
            label = f"{check_id} ({rel})"
            for group_id in spec.get("groups") or []:
                if group_id not in inv_children:
                    print(
                        f"check {label} references unknown group {group_id} "
                        "(not in inventory all.children)",
                        file=sys.stderr,
                    )
                    missing = True
        return not missing
    
    def group_args(self, check_id: str, group_id: str) -> dict[str, Any]:
        spec = self.by_id.get(check_id, {})
        groups = spec.get("groups", {})
        group = groups.get(group_id, {})
        return dict(group.get("args", {}))


def validate_catalog_path(spec: dict[str, Any]) -> str:
    """Return the normalised repo-relative script path for a catalog entry."""
    raw_path = spec.get("path")
    if not raw_path:
        raise ValueError("check catalog entry missing path")
    return paths.normalize_check_path(str(raw_path))


def warm_checks_cache(checks_path: str) -> None:
    """Ensure checks.yaml for checks_path is loaded (backward-compatible)."""
    ChecksCatalog.load(checks_path)


def catalog_check_ids(checks_path: str) -> list[str]:
    return ChecksCatalog.load(checks_path).check_ids


def catalog_check_spec(checks_path: str, check_id: str) -> dict[str, Any]:
    return ChecksCatalog.load(checks_path).spec(check_id)


def validate_catalog_script_paths(checks_path: str, scm_base: str) -> bool:
    return ChecksCatalog.load(checks_path).validate_script_paths(scm_base)


def validate_check_groups(checks_path: str, inv_children: dict[str, Any]) -> bool:
    return ChecksCatalog.load(checks_path).validate_groups(inv_children)


def group_check_ids(checks_path: str, group_id: str) -> list[str]:
    return ChecksCatalog.load(checks_path).group_check_ids(group_id)

def group_args(checks_path: str, check_id: str, group_id: str) -> dict[str, Any]:
    return ChecksCatalog.load(checks_path).group_args(check_id, group_id)

