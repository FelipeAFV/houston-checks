"""Unified tag token assembly for Uptime and Rundeck nodes."""

from __future__ import annotations

from src.inventory.membership import HostIndexes, SKIP_MEMBERSHIP_GROUPS
from src.utils.util import split_tags

TAG_DENYLIST = frozenset({"i-brain"})


def _token_allowed(token: str, *, kind: str) -> bool:
    if not token:
        return False
    if token in TAG_DENYLIST:
        return False
    if token.startswith("NETBOX_"):
        return False
    if token.startswith("hc-check-"):
        return False
    if kind == "switch" and token == "server":
        return False
    return True


def _dedupe_tokens(parts: list[str], *, kind: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in parts:
        if not _token_allowed(token, kind=kind):
            continue
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def node_tag_tokens(
    idx: HostIndexes,
    host_id: str,
    *,
    check_ids: list[str] | None = None,
    kind: str = "server",
    host_tags: str | list | None = None,
    netbox_imported: bool = False,
) -> list[str]:
    """Deduplicated tag tokens: kind, check-*, group slugs, optional static host tags."""
    parts: list[str] = []
    if kind:
        parts.append(kind)
    if check_ids:
        parts.extend(f"check-{c}" for c in check_ids)
    for gid in sorted(idx.host_to_groups.get(host_id, set())):
        if gid not in SKIP_MEMBERSHIP_GROUPS:
            parts.append(gid)
    if not netbox_imported:
        if host_tags is not None:
            if isinstance(host_tags, list):
                parts.extend(split_tags(" ".join(str(t) for t in host_tags)))
            else:
                parts.extend(split_tags(str(host_tags).replace(",", " ")))
        else:
            parts.extend(idx.host_tag_tokens.get(host_id, []))
    return _dedupe_tokens(parts, kind=kind)
