"""Repo-relative check script path helpers.

All path operations are sandboxed to SCM_BASE_DIR: no ``..`` traversal is
permitted and every resolved path is verified to remain inside the repository
root before being returned to callers.
"""

from __future__ import annotations

from pathlib import Path


def normalize_check_path(raw: str) -> str:
    """Normalise a repo-relative check script path.

    Strips leading slashes and converts back-slashes to forward-slashes.
    Raises ``ValueError`` when the result is empty or contains ``..`` path
    segments that could escape the repository root.
    """
    path = str(raw or "").strip().replace("\\", "/").lstrip("/")
    if not path:
        raise ValueError("empty check path")
    if any(part == ".." for part in path.split("/")):
        raise ValueError(f"invalid check path (.. not allowed): {raw!r}")
    return path


def check_id_from_path(path: str) -> str:
    """Derive a check id from a repo-relative script path (filename stem without extension).

    Example: ``check-shell/disk_space.sh`` → ``disk_space``
    """
    return Path(normalize_check_path(path)).stem


def validate_check_id(check_id: str) -> str:
    """Return check_id if it is a valid catalog/job slug."""
    cid = str(check_id or "").strip()
    if not cid or any(ch for ch in cid if not (ch.isalnum() or ch in "-_")):
        raise ValueError(f"invalid check id: {check_id!r}")
    return cid


def resolve_check_path(scm_base: str, rel_path: str) -> Path:
    """Resolve a repo-relative check path to an absolute ``Path`` under SCM_BASE_DIR.

    Raises ``ValueError`` when the resolved path would escape the repository root,
    preventing directory-traversal attacks from user-supplied paths in YAML config.
    """
    rel = normalize_check_path(rel_path)
    base = Path(scm_base).resolve()
    full = (base / rel).resolve()
    try:
        full.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"check path escapes SCM_BASE_DIR: {rel_path!r}") from exc
    return full
