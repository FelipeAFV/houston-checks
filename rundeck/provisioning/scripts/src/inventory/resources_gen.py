"""Rundeck nodes.yaml generation from effective hosts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.context import ProvisionContext
from src.inventory import hosts
from src.inventory.bastion import bastion_connect_hostname, emit_bastion_ssh_key_attrs
from src.inventory.tags import node_tag_tokens
from src.rundeck.job_gen import JobGenDefaults
from src.utils.util import log


def pings_index(
    pings: list[Any] | dict[str, list[tuple[str, str]]],
) -> dict[str, list[tuple[str, str]]]:
    """Index ping records by host_id -> [(check_id, ping_url), ...]."""
    if isinstance(pings, dict):
        return pings
    index: dict[str, list[tuple[str, str]]] = {}
    for record in pings:
        host_id = record.host_id if hasattr(record, "host_id") else record[0]
        check_id = record.check_id if hasattr(record, "check_id") else record[1]
        ping_url = record.ping_url if hasattr(record, "ping_url") else record[2]
        index.setdefault(host_id, []).append((check_id, ping_url))
    return index


def _host_uses_bastion(
    ping_checks: list[tuple[str, str]],
    python_bastion_check_ids: set[str],
    kind: str,
) -> bool:
    """True when Rundeck should SSH to python_bastion (switches or python_bastion checks)."""
    if kind == "switch":
        return True
    check_ids = [c for c, _ in ping_checks]
    return any(cid in python_bastion_check_ids for cid in check_ids)


def _render_node_entry(
    hid: str,
    host_spec: dict[str, Any],
    jg: JobGenDefaults,
    ping_checks: list[tuple[str, str]],
    ctx: ProvisionContext,
    check_script_default: str,
    python_bastion_check_ids: set[str],
) -> list[str]:
    """Build YAML lines for a single Rundeck node."""
    kind = host_spec.get("kind") or "server"
    uses_bastion = _host_uses_bastion(ping_checks, python_bastion_check_ids, kind)
    ssh = host_spec.get("ssh") or {}
    ssh_user = ssh.get("username") or ""
    ssh_port = str(ssh.get("port") or "")
    ssh_key_storage = ssh.get("key_storage_path") or ""
    ssh_keypath = ssh.get("private_key_path") or ""
    if not ssh_keypath and not ssh_key_storage:
        if not uses_bastion:
            raise ValueError(
                f"host {hid}: missing ssh.key_storage_path or ssh.private_key_path in inventory"
            )
    hostname = host_spec.get("hostname") or ""
    request_tty = str(ssh.get("request_tty", False)).lower()
    pwd_lit = ""
    if kind != "switch" and ssh.get("password") is not None:
        pwd_lit = str(ssh.get("password") or "")
    target_host = hostname
    target_user = ssh_user
    target_port = ssh_port or "22"

    if uses_bastion:
        hostname = bastion_connect_hostname(jg.bastion_host, jg.bastion_port)
        ssh_user = jg.bastion_user
        ssh_port = ""
        if jg.bastion_ssh_keypath:
            ssh_key_storage = ""
            ssh_keypath = jg.bastion_ssh_keypath
        else:
            ssh_key_storage = jg.bastion_key_storage
            ssh_keypath = ""

    check_ids = [c for c, _ in ping_checks]
    netbox_imported = bool(host_spec.get("netbox_id"))
    filtered_tags = node_tag_tokens(
        ctx.indexes,
        hid,
        check_ids=check_ids,
        kind=kind,
        netbox_imported=netbox_imported,
        host_tags=None if netbox_imported else host_spec.get("tags"),
    )
    check_script_base = check_script_default

    lines: list[str] = [
        f"{hid}:",
        f"  nodename: {hid}",
        f"  hostname: {hostname}",
        "  osFamily: unix",
        f"  kind: {kind}",
        f"  tags: {','.join(filtered_tags)}",
    ]
    if ssh_user:
        lines.append(f"  username: {ssh_user}")
    if ssh_port:
        lines.append(f"  sshport: {ssh_port}")
    if ssh_key_storage:
        lines.extend(["  ssh-authentication: privateKey", f"  ssh-key-storage-path: {ssh_key_storage}"])
    elif ssh_keypath:
        lines.extend(["  ssh-authentication: privateKey", f"  ssh-keypath: {ssh_keypath}"])
    else:
        lines.append('  ssh-keypath: ""')
    lines.append(f'  ssh_request_tty: "{request_tty}"')
    lines.append(f'  ssh_password: "{pwd_lit}"')
    if host_spec.get("local_executor"):
        lines.extend(["  node-executor: local", "  file-copier: local"])
    else:
        lines.append(f"  ssh-connection-timeout: {jg.ssh_connect_timeout_ms}")
        lines.append(f"  ssh-command-timeout: {jg.ssh_command_timeout_ms}")
    lines.append(f"  check_script_base: {check_script_base}")
    if uses_bastion:
        lines.extend([
            f"  target_host: {target_host}",
            f"  target_user: {target_user}",
            f"  target_port: {target_port}",
        ])
    for check_id, ping_url in ping_checks:
        lines.append(f"  uptime_ping_{check_id}: {ping_url}")
    lines.append("")
    return lines


def build_resources_yaml(
    ctx: ProvisionContext,
    jg: JobGenDefaults,
    pings: list[Any] | dict[str, list[tuple[str, str]]],
    out_yaml: str,
) -> None:
    """Write Rundeck resources YAML (nodes) from in-memory effective hosts."""
    pings_by_host = pings_index(pings)
    check_script_default = ctx.cfg.check_script_base or "/tmp/rundeck"
    log(f"[rd] check_script_base={check_script_default}")
    checks_meta = ctx.ensure_checks_meta()
    python_bastion_check_ids = {
        cid
        for cid, spec in checks_meta.items()
        if spec.get("executor") in ("python_bastion", "shell_bastion")
    }

    lines = [
        "# Generated by houston-provision — do not edit by hand.",
        "# Inventory hosts (NetBox import + static all.children hosts).",
    ]

    host_id_list = hosts.host_ids(ctx.inv, ctx.indexes)
    if "python_bastion" not in host_id_list:
        lines.extend([
            "python_bastion:",
            "  nodename: python_bastion",
            f"  hostname: {bastion_connect_hostname(jg.bastion_host, jg.bastion_port)}",
            "  osFamily: unix",
            "  tags: houston-internal,python-bastion",
            f"  username: {jg.bastion_user}",
            *emit_bastion_ssh_key_attrs(jg),
            "",
        ])

    for hid in host_id_list:
        host_spec = hosts.effective_host_spec(ctx.inv, hid, ctx.indexes, ctx.cfg)
        if not host_spec:
            continue
        ping_checks = pings_by_host.get(hid, [])
        lines.extend(
            _render_node_entry(
                hid,
                host_spec,
                jg,
                ping_checks,
                ctx,
                check_script_default,
                python_bastion_check_ids,
            )
        )

    Path(out_yaml).parent.mkdir(parents=True, exist_ok=True)
    Path(out_yaml).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
