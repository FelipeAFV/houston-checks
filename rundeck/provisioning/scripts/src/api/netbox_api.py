"""NetBox device fetch and effective inventory merge (in-memory).

Loads the static ``inventory.yaml``, optionally queries the NetBox REST API for
devices whose role matches the group ids declared in ``all.children``, and
merges them into a deep copy of the inventory dict that is returned to callers.
No files are written; everything stays in memory.

Environment variables consulted at runtime:
- ``NETBOX_NODENAME_SUFFIX_ID=1`` — append the NetBox device id to every
  generated nodename to avoid collisions in large environments.
"""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Protocol

from src.api import http_client
from src.inventory import hosts
from src.inventory.hosts import InventorySource
from src.utils.util import load_yaml_file, log


def _netbox_vars(inv: InventorySource) -> dict[str, Any]:
    """Return the all.vars.netbox config block (empty dict if absent)."""
    nb = hosts.all_vars(inv).get("netbox")
    return nb if isinstance(nb, dict) else {}


def slugify_name(raw: str) -> str:
    """Convert a device name to a lowercase slug safe for Rundeck nodenames."""
    slug = raw.lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", slug)
    return slug.strip("-")


def nodename_for_device(name: str, dev_id: int | str, registry: set[str]) -> str:
    """Assign a unique nodename slug for a NetBox device."""
    if os.environ.get("NETBOX_NODENAME_SUFFIX_ID", "0") == "1":
        base = slugify_name(name) or "device"
        slug = f"{base}-{dev_id}"
        registry.add(slug)
        return slug
    base = slugify_name(name)
    if not base:
        slug = f"device-{dev_id}"
    elif base in registry:
        slug = f"{base}-{dev_id}"
    else:
        slug = base
    registry.add(slug)
    return slug


def slug_eq(a: str, b: str) -> bool:
    """Case-insensitive slug comparison."""
    return a.lower() == b.lower()


def device_passes_filter(
    dev: dict[str, Any],
    roles: list[str],
    suffixes: list[str],
    excludes: list[str],
    role: str,
    match: str,
) -> bool:
    """Return True when a NetBox device matches inventory role filter rules."""
    device_role_slug = (dev.get("device_role") or {}).get("slug") or ""

    def has_listed_role() -> bool:
        if not roles:
            return False if match == "any" else True
        return any(slug_eq(r, device_role_slug) for r in roles)

    def has_role_suffix() -> bool:
        if not suffixes:
            return False if match == "any" else True
        return any(device_role_slug.endswith(s) for s in suffixes)

    def excluded_by_role() -> bool:
        if not excludes:
            return False
        return any(device_role_slug.endswith(s) for s in excludes)

    def passes_identity() -> bool:
        return device_role_slug == role if role else True

    def passes_role_filter() -> bool:
        if match == "any":
            return has_listed_role() or has_role_suffix()
        return has_listed_role() and has_role_suffix()

    return passes_identity() and passes_role_filter() and not excluded_by_role()


class ConfigLike(Protocol):
    """Structural type for config objects consumed by netbox_api functions."""

    netbox_url: str
    netbox_token: str
    netbox_curl_max_time: int
    netbox_curl_connect_timeout: int
    curl_secure: bool


def query_string_from_inv(cfg: ConfigLike, inv: InventorySource) -> str:
    """Build NetBox devices API query string from inventory vars."""
    nb = _netbox_vars(inv)
    qs = "limit=100"
    extra = nb.get("query") or ""
    if extra and extra != "null":
        qs = f"{qs}&{extra.lstrip('&')}"
    for slug in hosts.resolved_netbox_role_slugs(inv, nb):
        if slug:
            qs = f"{qs}&role={slug}"
    role = nb.get("role_slug") or ""
    if role and role != "null":
        qs = f"{qs}&role={role}"
    return qs


def abs_url(base: str, u: str) -> str:
    """Return an absolute URL, prepending ``base`` when ``u`` is relative."""
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    base = base.rstrip("/")
    if u.startswith("/"):
        return f"{base}{u}"
    return f"{base}/{u}"


def fetch_page(cfg: ConfigLike, url: str) -> dict[str, Any]:
    """Fetch one paginated NetBox API page."""
    if not cfg.netbox_token:
        raise RuntimeError("NETBOX_TOKEN is required for hosts.netbox")
    insecure = not cfg.curl_secure
    try:
        return http_client.get_json(
            url,
            headers={"Authorization": f"Token {cfg.netbox_token}", "Accept": "application/json"},
            timeout=cfg.netbox_curl_max_time,
            insecure=insecure,
        )
    except RuntimeError as exc:
        msg = str(exc)
        if "HTTP 400" in msg:
            log(
                "netbox: hint: HTTP 400 often means invalid API filter — "
                "check all.vars.netbox.query and role slugs in all.children"
            )
        raise


def fetch_devices(
    cfg: ConfigLike, inv: InventorySource
) -> tuple[int, int, list[dict[str, Any]]]:
    """Paginate NetBox devices API; return (api_count, filtered_count, filtered_devices)."""
    nb = _netbox_vars(inv)
    roles = hosts.resolved_netbox_role_slugs(inv, nb)
    suffixes = list(nb.get("role_slug_suffixes") or [])
    excludes = list(nb.get("role_slug_exclude_suffixes") or [])
    role = str(nb.get("role_slug") or "")
    match = str(nb.get("match") or "all")

    filtered: list[dict[str, Any]] = []
    base = cfg.netbox_url.rstrip("/")
    qs = query_string_from_inv(cfg, inv)
    next_url = f"{base}/api/dcim/devices/?{qs}"
    api_count = 0
    pages = 0
    log(f"netbox: GET {next_url}")

    while next_url and pages < 500:
        pages += 1
        body = fetch_page(cfg, next_url)
        results = body.get("results") or []
        api_count += len(results)
        for dev in results:
            if not isinstance(dev, dict):
                continue
            if device_passes_filter(dev, roles, suffixes, excludes, role, match):
                filtered.append(dev)
        nxt = body.get("next")
        next_url = abs_url(base, nxt) if nxt else ""

    return api_count, len(filtered), filtered


def hostname_from_device(dev: dict[str, Any]) -> str:
    """Prefer primary_ip4 address; fall back to device name."""
    ip4 = dev.get("primary_ip4")
    ip = ""
    if isinstance(ip4, dict):
        ip = (ip4.get("address") or "").split("/")[0]
    return ip or dev.get("name") or ""


def site_from_device(dev: dict[str, Any]) -> str:
    """Return the lowercase site name/slug for a device, or empty string."""
    site = dev.get("site")
    if isinstance(site, dict):
        return (site.get("name") or site.get("slug") or "").lower()
    return ""


def device_tags_from_device(dev: dict[str, Any]) -> str:
    """Return a space-joined string of tag slugs for a NetBox device."""
    slugs: list[str] = []
    for t in dev.get("tags") or []:
        if isinstance(t, dict):
            s = t.get("slug") or t.get("name") or ""
        else:
            s = str(t)
        if s:
            slugs.append(s)
    return " ".join(slugs)


def role_groups_enabled(nb: dict[str, Any], inv: InventorySource = "") -> bool:
    """Return True when role-based group creation should be performed for the given config."""
    if inv:
        return len(hosts.resolved_netbox_role_slugs(inv, nb)) > 0
    return len(nb.get("role_slugs") or []) > 0


def is_switch_role(
    nb: dict[str, Any],
    role_slug: str,
    *,
    inv: InventorySource = "",
    switch_slugs: list[str] | None = None,
) -> bool:
    """Return True when the given role slug maps to a switch-type device."""
    if switch_slugs is not None:
        return role_slug in switch_slugs
    if inv:
        return role_slug in hosts.resolved_netbox_switch_role_slugs(inv, nb)
    return role_slug in (nb.get("switch_role_slugs") or [])


def ensure_child_group(data: dict[str, Any], gid: str, tags: list[str]) -> None:
    """Ensure ``all.children[gid]`` exists with a ``hosts`` dict; create it when absent."""
    all_block = data.setdefault("all", {})
    children = all_block.setdefault("children", {})
    if gid not in children:
        children[gid] = {"vars": {"tags": tags}, "hosts": {}}
    else:
        child = children[gid]
        if "hosts" not in child:
            child["hosts"] = {}
        if "vars" not in child:
            child["vars"] = {"tags": tags}


def build_host_entry(
    *,
    slug: str,
    display: str,
    dev_id: int,
    hostname: str,
    tags: str,
    kind: str,
    ssh: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an Ansible-style host entry dict for the effective hosts."""
    entry: dict[str, Any] = {
        "id": slug,
        "name": display,
        "netbox_id": dev_id,
        "kind": kind,
        "hostname": hostname,
        "tags": tags,
    }
    if ssh:
        entry["ssh"] = ssh
    return entry


def _merge_device(
    dev: dict[str, Any],
    inv_data: dict[str, Any],
    nb_vars: dict[str, Any],
    switch_slugs: list[str],
    registry: set[str],
    counters: dict[str, int],
    cfg: Any,
) -> bool:
    """Merge one NetBox device into inv_data. Returns True if imported."""
    dev_id = dev.get("id")
    name = dev.get("name") or ""
    display = dev.get("display") or name
    slug = nodename_for_device(name, dev_id, registry)

    ip4 = dev.get("primary_ip4")
    if not (isinstance(ip4, dict) and (ip4.get("address") or "").split("/")[0]):
        counters["no_primary"] += 1

    hostname = hostname_from_device(dev)
    site_token = site_from_device(dev)
    if site_token:
        counters["ssh_by_site"] += 1
    else:
        counters["ssh_no_site"] += 1
        if counters["ssh_no_site"] <= 2:
            log(f"netbox: WARN no site for device {name} (using ssh_key_storage_default)")

    role_slug = (dev.get("device_role") or {}).get("slug") or ""
    role_gid = role_slug
    if not role_gid or not hosts.is_netbox_role_group(inv_data, role_gid):
        counters["skipped_role"] += 1
        if counters["skipped_role"] <= 5:
            log(
                f"netbox: WARN skip device {name} — role {role_slug!r} "
                "not declared in inventory all.children"
            )
        return False

    ctx = hosts.merged_vars_for_group(inv_data, role_gid)
    host_tags = role_gid

    if is_switch_role(nb_vars, role_slug, switch_slugs=switch_slugs):
        switch_ssh = hosts.ssh_from_context(cfg, ctx, kind="switch")
        ssh: dict[str, Any] = {
            "username": switch_ssh["username"],
            "port": switch_ssh["port"],
            "request_tty": switch_ssh["request_tty"],
        }
        kind = "switch"
    else:
        server_ssh = hosts.ssh_from_context(cfg, ctx, kind="server", site_key=site_token)
        ssh = {
            "username": server_ssh["username"],
            "key_storage_path": server_ssh["key_storage_path"],
        }
        kind = "server"

    entry = build_host_entry(
        slug=slug,
        display=display,
        dev_id=int(dev_id),
        hostname=hostname,
        tags=host_tags,
        kind=kind,
        ssh=ssh,
    )
    ensure_child_group(inv_data, role_gid, [])
    inv_data["all"]["children"][role_gid]["hosts"][slug] = entry
    return True


def build_effective_inventory(ctx: Any) -> dict[str, Any]:
    """Merge NetBox devices into a copy of the static inventory from context."""
    from src.context import ProvisionContext

    if not isinstance(ctx, ProvisionContext):
        raise TypeError("build_effective_inventory expects ProvisionContext")
    inv_data = copy.deepcopy(ctx.static_inv)

    if not hosts.netbox_import_requested(inv_data):
        return inv_data

    cfg = ctx.cfg
    if not cfg.netbox_url:
        return inv_data

    nb_vars = _netbox_vars(inv_data)
    api_count, filtered_count, devices = fetch_devices(cfg, inv_data)
    if api_count > 0 and filtered_count == 0:
        log(
            f"netbox: WARN API returned {api_count} device(s) but filter matched 0; "
            "check NetBox role groups in inventory all.children (group id = role slug) or role_slugs"
        )

    registry: set[str] = set()
    role_slugs = hosts.resolved_netbox_role_slugs(inv_data, nb_vars)
    switch_slugs = hosts.resolved_netbox_switch_role_slugs(inv_data, nb_vars)
    if role_groups_enabled(nb_vars, inv_data):
        for role in role_slugs:
            ensure_child_group(inv_data, role, [])

    counters: dict[str, int] = {
        "no_primary": 0, "ssh_by_site": 0, "ssh_no_site": 0,
        "skipped_role": 0, "imported": 0,
    }
    for dev in devices:
        if _merge_device(dev, inv_data, nb_vars, switch_slugs, registry, counters, cfg):
            counters["imported"] += 1

    log(
        f"netbox ssh keys: {counters['ssh_by_site']} by site, "
        f"{counters['ssh_no_site']} fallback (no site)"
    )
    log(
        f"netbox: {counters['imported']} device(s) -> {len(role_slugs)} role group(s) "
        f"(api_count={api_count}, filtered={filtered_count}, "
        f"{counters['no_primary']} without primary_ip4, "
        f"{counters['skipped_role']} skipped unknown role)"
    )
    return inv_data
