"""Host inventory parsing — inventory.yaml (Ansible format: all.children groups + vars).

The inventory file follows a subset of the Ansible static inventory YAML format::

    all:
      vars:
        node_username: debian
      children:
        web_servers:
          vars:
            tags: "server web"
          hosts:
            web01:
              hostname: 10.0.0.1
        border-leaf-switch:
          vars:
            netbox_kind: switch
          hosts: {}   # populated by NetBox import

This module only reads the *host* side of the inventory (groups, hosts, vars,
SSH credentials).  Check catalog functions live in :mod:`src.inventory.catalog`.
"""

from __future__ import annotations

import copy
import sys
from typing import Any

from src.configs.config import Config
from src.inventory.membership import HostIndexes
from src.inventory.tags import node_tag_tokens
from src.utils.util import fatal, filter_unique_tags, load_yaml_file, split_tags

InventorySource = str | dict[str, Any]


def _yaml_dict(path: str) -> dict[str, Any]:
    """Load a YAML file and return it as a dict (empty dict when the file is empty or not a mapping)."""
    data = load_yaml_file(path)
    return data if isinstance(data, dict) else {}


def load_inventory_dict(path: str) -> dict[str, Any]:
    """Load inventory.yaml once and return as a dict."""
    return _yaml_dict(path)


def _indexes_for(source: InventorySource, idx: HostIndexes | None) -> HostIndexes:
    if idx is not None:
        return idx
    return HostIndexes.build(_hosts_data(source))


# ---------------------------------------------------------------------------
# Group and host enumeration
# ---------------------------------------------------------------------------

def _hosts_data(source: InventorySource) -> dict[str, Any]:
    """Load inventory from an in-memory dict or a YAML file path."""
    if isinstance(source, dict):
        return source
    return _yaml_dict(source)


def group_ids(hosts: InventorySource, idx: HostIndexes | None = None) -> list[str]:
    """Sorted list of all group ids (all.children keys)."""
    if idx is not None:
        return list(idx.group_ids)
    children = (_hosts_data(hosts).get("all") or {}).get("children") or {}
    if not isinstance(children, dict):
        return []
    return sorted(children.keys())


def host_ids(hosts: InventorySource, idx: HostIndexes | None = None) -> list[str]:
    """Sorted list of all host ids across every group."""
    if idx is not None:
        return list(idx.host_ids)
    children = (_hosts_data(hosts).get("all") or {}).get("children") or {}
    if not isinstance(children, dict):
        return []
    ids: set[str] = set()
    for child in children.values():
        if not isinstance(child, dict):
            continue
        h = child.get("hosts") or {}
        if isinstance(h, dict):
            ids.update(h.keys())
    return sorted(ids)


# ---------------------------------------------------------------------------
# Group membership
# ---------------------------------------------------------------------------

def group_tags(hosts: InventorySource, group_id: str) -> list[str]:
    """Tag tokens for a group (falls back to group id if no tags declared)."""
    children = (_hosts_data(hosts).get("all") or {}).get("children") or {}
    child = children.get(group_id) if isinstance(children, dict) else None
    tags_raw = (child or {}).get("vars", {}).get("tags") if isinstance(child, dict) else []
    tokens = split_tags(tags_raw)
    if not tokens:
        tokens = [group_id]
    return filter_unique_tags(tokens)


def host_tag_tokens(hosts: InventorySource, host_id: str) -> list[str]:
    """Return the individual tag tokens declared directly on a host entry."""
    spec = host_spec(hosts, host_id)
    tags = spec.get("tags") or ""
    if isinstance(tags, list):
        return split_tags(" ".join(str(t) for t in tags))
    return split_tags(str(tags).replace(",", " "))


def host_in_group_explicit(hosts: InventorySource, host_id: str, group_id: str) -> bool:
    """Return True when host_id appears under ``all.children[group_id].hosts``."""
    children = (_hosts_data(hosts).get("all") or {}).get("children") or {}
    child = children.get(group_id) if isinstance(children, dict) else None
    h = (child or {}).get("hosts") if isinstance(child, dict) else {}
    return isinstance(h, dict) and host_id in h


def host_in_group_by_tags(hosts: InventorySource, host_id: str, group_id: str) -> bool:
    """Return True when the host's tag tokens overlap with the group's tag tokens."""
    return bool(set(host_tag_tokens(hosts, host_id)).intersection(group_tags(hosts, group_id)))


def host_in_group(
    hosts: InventorySource,
    host_id: str,
    group_id: str,
    idx: HostIndexes | None = None,
) -> bool:
    """Return True when a host belongs to a group either explicitly or by tag overlap."""
    indexes = _indexes_for(hosts, idx)
    return indexes.host_in_group(host_id, group_id)


def host_membership_tags(
    hosts: InventorySource, host_id: str, idx: HostIndexes | None = None
) -> list[str]:
    """Return deduplicated tag tokens from every group the host belongs to."""
    return _indexes_for(hosts, idx).membership_tags(host_id)


# ---------------------------------------------------------------------------
# Host spec and SSH resolution
# ---------------------------------------------------------------------------

def host_spec(
    hosts: InventorySource, host_id: str, idx: HostIndexes | None = None
) -> dict[str, Any]:
    """Raw host entry from the inventory (without checks key)."""
    indexes = _indexes_for(hosts, idx)
    if host_id in indexes.host_specs:
        return dict(indexes.host_specs[host_id])
    children = (_hosts_data(hosts).get("all") or {}).get("children") or {}
    if not isinstance(children, dict):
        return {}
    for child in children.values():
        if not isinstance(child, dict):
            continue
        h = child.get("hosts") or {}
        if isinstance(h, dict) and host_id in h:
            raw = dict(h[host_id])
            raw["id"] = host_id
            raw.pop("checks", None)
            return raw
    return {}


def deep_merge_vars(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two variable dicts, with ``override`` taking precedence.

    Nested dicts are merged depth-first; all other value types are replaced.
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge_vars(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def all_vars(hosts: InventorySource) -> dict[str, Any]:
    """all.vars block from the inventory (provision config + SSH defaults)."""
    av = (_hosts_data(hosts).get("all") or {}).get("vars") or {}
    return av if isinstance(av, dict) else {}


def group_vars(hosts: InventorySource, group_id: str) -> dict[str, Any]:
    """vars block for a specific group."""
    children = (_hosts_data(hosts).get("all") or {}).get("children") or {}
    child = children.get(group_id) if isinstance(children, dict) else None
    if isinstance(child, dict):
        v = child.get("vars")
        return v if isinstance(v, dict) else {}
    return {}


def merged_vars_for_group(hosts: InventorySource, group_id: str) -> dict[str, Any]:
    """Return all.vars deep-merged with the group's own vars block."""
    return deep_merge_vars(all_vars(hosts), group_vars(hosts, group_id))


def host_var_context(
    hosts: InventorySource, host_id: str, idx: HostIndexes | None = None
) -> dict[str, Any]:
    """Build the full variable context for a host: all.vars → group vars → host vars."""
    indexes = _indexes_for(hosts, idx)
    ctx = dict(all_vars(hosts))
    for gid in indexes.host_to_groups.get(host_id, set()):
        ctx = deep_merge_vars(ctx, group_vars(hosts, gid))
    raw = host_spec(hosts, host_id, indexes)
    if raw:
        ctx = deep_merge_vars(ctx, raw)
    return ctx


def ssh_from_context(
    cfg: Config,
    inv_ctx: dict[str, Any],
    *,
    kind: str = "server",
    site_key: str = "",
) -> dict[str, Any]:
    """Resolve SSH credentials from config.yaml and inventory vars.

    For ``kind="server"`` returns ``{username, key_storage_path}``, looking up
    the key path per site in ``ssh.key_storage_by_site`` and falling back to
    ``ssh.key_storage_default``.

    For ``kind="switch"`` returns ``{username, port, request_tty}`` from
    ``switch_ssh`` in config.yaml (password via Rundeck Key Storage job option).

    Raises ``ValueError`` when required keys are absent.
    """
    if kind == "switch":
        username = cfg.switch_ssh_username
        if not username:
            raise ValueError("switch_ssh.username is required in config.yaml")
        return {
            "username": username,
            "port": cfg.switch_ssh_port,
            "request_tty": cfg.switch_ssh_request_tty,
        }
    username = inv_ctx.get("node_username")
    if not username:
        raise ValueError("node_username is required in inventory all.vars")
    default = cfg.ssh_key_storage_default
    if not default:
        raise ValueError("ssh.key_storage_default is required in config.yaml")
    keypath = cfg.ssh_key_path_for_site(site_key)
    return {"username": username, "key_storage_path": keypath}


def effective_host_spec(
    hosts: InventorySource,
    host_id: str,
    idx: HostIndexes | None,
    cfg: Config,
    *,
    site_key: str = "",
) -> dict[str, Any]:
    """Return the fully-resolved host specification for Rundeck node generation.

    Starts from the raw inventory entry and layers on:
    1. All group vars for every group the host belongs to.
    2. SSH credentials derived via :func:`ssh_from_context`.
    3. ``kind`` (``server`` or ``switch``) inferred from context when not explicit.

    Returns an empty dict when the host is not found.
    """
    raw = host_spec(hosts, host_id, idx)
    if not raw:
        return {}
    ctx = host_var_context(hosts, host_id, idx)
    spec = dict(raw)
    spec["id"] = host_id

    kind = spec.get("kind") or ""
    if not kind:
        nk = str(ctx.get("netbox_kind") or "").lower()
        kind = "switch" if nk == "switch" else "server"
    spec["kind"] = kind

    ssh = dict(spec.get("ssh") or {}) if isinstance(spec.get("ssh"), dict) else {}
    derived = ssh_from_context(cfg, ctx, kind=kind, site_key=site_key)
    for key, val in derived.items():
        if key not in ssh or ssh.get(key) in ("", None):
            ssh[key] = val
    if ssh:
        spec["ssh"] = ssh

    if not spec.get("tags") and ctx.get("tags"):
        spec["tags"] = ctx["tags"]

    return spec


# ---------------------------------------------------------------------------
# Uptime tag helpers
# ---------------------------------------------------------------------------

def uptime_site_tag_names(
    hosts: InventorySource,
    host_id: str,
    check_id: str,
    idx: HostIndexes | None,
    cfg: Config,
) -> list[str]:
    """Tag names for an Uptime heartbeat (aligned with Rundeck node tags for this check)."""
    spec = effective_host_spec(hosts, host_id, idx, cfg) or {}
    kind = spec.get("kind") or "server"
    indexes = _indexes_for(hosts, idx)
    netbox_imported = bool(spec.get("netbox_id"))
    return node_tag_tokens(
        indexes,
        host_id,
        check_ids=[check_id],
        kind=kind,
        netbox_imported=netbox_imported,
        host_tags=None if netbox_imported else spec.get("tags"),
    )


# ---------------------------------------------------------------------------
# NetBox role group helpers
# ---------------------------------------------------------------------------

def is_netbox_role_group(hosts: InventorySource, group_id: str) -> bool:
    """True when the group is a NetBox role slug (not declared as local-only)."""
    gv = group_vars(hosts, group_id)
    if gv.get("local_only") is True:
        return False
    deny = all_vars(hosts).get("local_only_groups") or []
    if group_id in deny:
        return False
    return True


def netbox_enabled(hosts: InventorySource) -> bool:
    """Return True when the inventory declares at least one NetBox role group."""
    return bool(netbox_role_slugs_from_inventory(hosts))


def netbox_import_requested(hosts: InventorySource) -> bool:
    """Return True when the inventory is structured for NetBox import (not opted out)."""
    if not netbox_enabled(hosts):
        return False
    nb = all_vars(hosts).get("netbox")
    if isinstance(nb, dict) and nb.get("enabled") is False:
        return False
    return True


def netbox_import_active(hosts: InventorySource, *, netbox_url: str = "") -> bool:
    """Return True when NetBox API import should run (groups + NETBOX_URL configured)."""
    return netbox_import_requested(hosts) and bool(str(netbox_url or "").strip())


def netbox_role_slugs_from_inventory(hosts: InventorySource) -> list[str]:
    """NetBox device role slugs declared as all.children group ids."""
    return sorted(gid for gid in group_ids(hosts) if is_netbox_role_group(hosts, gid))


def resolved_netbox_role_slugs(
    hosts: InventorySource, nb: dict[str, Any] | None = None
) -> list[str]:
    """role_slugs from inventory vars, or inferred from all.children group ids."""
    nb = nb or {}
    explicit = [str(s) for s in (nb.get("role_slugs") or []) if s]
    if explicit:
        return filter_unique_tags(explicit)
    return netbox_role_slugs_from_inventory(hosts)


def resolved_netbox_switch_role_slugs(
    hosts: InventorySource, nb: dict[str, Any] | None = None
) -> list[str]:
    """switch_role_slugs from config, or children with vars.netbox_kind: switch."""
    nb = nb or {}
    explicit = [str(s) for s in (nb.get("switch_role_slugs") or []) if s]
    if explicit:
        return filter_unique_tags(explicit)
    out: list[str] = []
    for gid in netbox_role_slugs_from_inventory(hosts):
        kind = str(group_vars(hosts, gid).get("netbox_kind") or "")
        if kind.lower() == "switch":
            out.append(gid)
    return sorted(out)


def netbox_group_host_ids(
    hosts: InventorySource, group_id: str, idx: HostIndexes | None = None
) -> list[str]:
    """Return sorted host ids that belong to a specific NetBox role group."""
    return sorted(_indexes_for(hosts, idx).group_to_hosts.get(group_id, set()))


def netbox_role_host_ids(hosts: InventorySource) -> list[str]:
    """Unique host ids across all NetBox role groups."""
    ids: set[str] = set()
    for gid in netbox_role_slugs_from_inventory(hosts):
        ids.update(netbox_group_host_ids(hosts, gid))
    return sorted(ids)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inventory_vars(hosts: InventorySource) -> None:
    """Raise fatal error if required all.vars keys are missing or deprecated keys are present."""
    av = all_vars(hosts)
    missing: list[str] = []
    if not av.get("node_username"):
        missing.append("all.vars.node_username")
    deprecated: list[str] = []
    if av.get("ssh_key_storage_default") or av.get("ssh_key_storage_by_site"):
        deprecated.append("ssh_key_storage_* (move to config.yaml ssh: block)")
    switch_ssh = av.get("switch_ssh")
    if switch_ssh is not None:
        deprecated.append("switch_ssh (move to config.yaml switch_ssh: block)")
        if isinstance(switch_ssh, dict) and switch_ssh.get("password"):
            fatal("inventory.yaml must not contain switch_ssh.password — use config.yaml switch_ssh.password_key_storage_path + Rundeck Key Storage")
    if deprecated:
        fatal("inventory.yaml deprecated vars: " + ", ".join(deprecated))
    if missing:
        fatal("inventory.yaml missing required vars: " + ", ".join(missing))


# ---------------------------------------------------------------------------
# Catalog cross-reference (delegated to catalog module)
# ---------------------------------------------------------------------------

def host_checks_index(
    hosts: InventorySource,
    checks: Any,
    idx: HostIndexes | None = None,
) -> dict[str, list[str]]:
    """Precompute host -> [check_id, ...] using membership indexes.

    Checks with ``one_host: true`` in the catalog are assigned to a single
    eligible host (lowest ``host_id`` lexicographically).
    """
    from src.inventory.catalog import ChecksCatalog

    if isinstance(checks, str):
        catalog = ChecksCatalog.load(checks)
    else:
        catalog = checks
    indexes = _indexes_for(hosts, idx)
    eligible_by_check: dict[str, list[str]] = {}
    for hid in indexes.host_ids:
        groups = indexes.host_to_groups.get(hid, set())
        for check_id in catalog.check_ids:
            spec = catalog.by_id[check_id]
            if any(g in groups for g in (spec.get("groups") or [])):
                eligible_by_check.setdefault(check_id, []).append(hid)

    out: dict[str, list[str]] = {hid: [] for hid in indexes.host_ids}
    for check_id, eligible in eligible_by_check.items():
        if catalog.by_id[check_id].get("one_host"):
            if eligible:
                out[sorted(eligible)[0]].append(check_id)
        else:
            for hid in eligible:
                out[hid].append(check_id)
    return {hid: sorted(set(cids)) for hid, cids in out.items()}
