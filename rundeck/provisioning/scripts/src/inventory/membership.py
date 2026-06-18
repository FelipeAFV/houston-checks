"""Host/group membership indexes built in one pass over inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.util import filter_unique_tags, split_tags

InventoryDict = dict[str, Any]

SKIP_MEMBERSHIP_GROUPS = frozenset({"server"})


@dataclass
class HostIndexes:
    """Precomputed host↔group relationships for an inventory dict."""

    group_ids: list[str] = field(default_factory=list)
    host_ids: list[str] = field(default_factory=list)
    host_to_groups: dict[str, set[str]] = field(default_factory=dict)
    group_to_hosts: dict[str, set[str]] = field(default_factory=dict)
    group_tag_tokens: dict[str, list[str]] = field(default_factory=dict)
    host_tag_tokens: dict[str, list[str]] = field(default_factory=dict)
    host_specs: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def build(cls, inv: InventoryDict) -> HostIndexes:
        children = (inv.get("all") or {}).get("children") or {}
        if not isinstance(children, dict):
            return cls()

        idx = cls()
        idx.group_ids = sorted(children.keys())

        for gid, child in children.items():
            if not isinstance(child, dict):
                continue
            vars_block = child.get("vars") if isinstance(child.get("vars"), dict) else {}
            tags_raw = vars_block.get("tags") if isinstance(vars_block, dict) else []
            tokens = split_tags(tags_raw)
            if not tokens:
                tokens = [gid]
            idx.group_tag_tokens[gid] = filter_unique_tags(tokens)

            hosts_block = child.get("hosts") or {}
            if not isinstance(hosts_block, dict):
                continue
            for hid, raw in hosts_block.items():
                if not isinstance(raw, dict):
                    raw = {}
                spec = dict(raw)
                spec["id"] = hid
                spec.pop("checks", None)
                idx.host_specs[hid] = spec
                idx.host_to_groups.setdefault(hid, set()).add(gid)
                idx.group_to_hosts.setdefault(gid, set()).add(hid)

                tags = spec.get("tags") or ""
                if isinstance(tags, list):
                    ht = split_tags(" ".join(str(t) for t in tags))
                else:
                    ht = split_tags(str(tags).replace(",", " "))
                if ht:
                    idx.host_tag_tokens[hid] = filter_unique_tags(ht)

        idx.host_ids = sorted(idx.host_specs.keys())

        for hid in idx.host_ids:
            ht = set(idx.host_tag_tokens.get(hid, []))
            for gid, gt in idx.group_tag_tokens.items():
                if ht.intersection(gt):
                    idx.host_to_groups.setdefault(hid, set()).add(gid)
                    idx.group_to_hosts.setdefault(gid, set()).add(hid)

        return idx

    def host_in_group(self, host_id: str, group_id: str) -> bool:
        return group_id in self.host_to_groups.get(host_id, set())

    def membership_tags(self, host_id: str) -> list[str]:
        """Return group slug tags for a host (excludes umbrella groups like ``server``)."""
        out: list[str] = []
        for gid in sorted(self.host_to_groups.get(host_id, set())):
            if gid in SKIP_MEMBERSHIP_GROUPS:
                continue
            out.append(gid)
        return out
