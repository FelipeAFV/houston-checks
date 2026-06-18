"""Shared low-level helpers used across the whole provision package."""

from __future__ import annotations

import re
import sys
from typing import Any


SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


def log(msg: str) -> None:
    """Write a prefixed informational message to stderr."""
    print(f"[provision] {msg}", file=sys.stderr)


def fatal(msg: str) -> None:
    """Log a FATAL message and exit with code 1."""
    log(f"FATAL: {msg}")
    sys.exit(1)


def validate_slug(kind: str, value: str) -> bool:
    """Return True when value is a valid lowercase slug (a-z, 0-9, hyphens, underscores).

    Prints a descriptive error to stderr and returns False on failure so the caller
    can decide whether to skip the offending item or abort.
    """
    if not value or not SLUG_RE.match(value):
        print(
            f"invalid {kind}: {value} (use only a-z, 0-9, hyphens, underscores)",
            file=sys.stderr,
        )
        return False
    return True


def load_yaml_file(path: str) -> Any:
    """Parse a YAML file and return its contents (empty dict when the file is empty)."""
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if data is not None else {}


def split_tags(value: Any) -> list[str]:
    """Split a comma- or space-delimited tag string (or list) into individual tokens.

    Accepts:
    - ``None`` → empty list
    - ``str``  → split on commas and/or spaces
    - ``list`` → each element is recursively split
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [t for t in re.split(r"[, ]+", value.strip()) if t]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(split_tags(item))
        return out
    return []


def filter_unique_tags(items: list[str]) -> list[str]:
    """Return deduplicated, non-empty tags preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out
