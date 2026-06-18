"""Build merged check metadata (catalog + script headers) once per run."""

from __future__ import annotations

from typing import Any

from src.inventory.catalog import ChecksCatalog
from src.inventory import check_meta


def build_check_registry(checks: ChecksCatalog, scm_base: str) -> dict[str, dict[str, Any]]:
    """Merge catalog entries with script header metadata for every check id."""
    from src.inventory.catalog import validate_catalog_path

    registry: dict[str, dict[str, Any]] = {}
    for check_id in checks.check_ids:
        cat_entry = checks.spec(check_id)
        if not cat_entry:
            continue
        try:
            rel = validate_catalog_path(cat_entry)
            meta = check_meta.meta_for_path(scm_base, rel)
        except (ValueError, FileNotFoundError):
            meta = check_meta.meta_for_id(scm_base, check_id)
        merged = dict(cat_entry)
        merged["name"] = meta.get("name", check_id)
        merged["desc"] = meta.get("desc", "")
        merged["executor"] = meta["executor"]
        if meta.get("netmiko"):
            merged["netmiko"] = meta["netmiko"]
        registry[check_id] = merged
    return registry


def netmiko_from_registry(registry: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Resolve Netmiko settings from registry script headers."""
    for _check_id, spec in registry.items():
        nm = spec.get("netmiko")
        if isinstance(nm, dict) and nm.get("device_type") and nm.get("command"):
            return {
                "device_type": str(nm["device_type"]),
                "command": str(nm["command"]),
            }
    return {"device_type": "", "command": ""}
