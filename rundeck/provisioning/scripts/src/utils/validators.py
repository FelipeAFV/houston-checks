"""Pre-flight validation for houston-provision."""

from __future__ import annotations

import os

from src.context import ProvisionContext
from src.configs.config import Config
from src.inventory import hosts, paths
from src.inventory.catalog import validate_catalog_path
from src.utils.util import fatal, load_yaml_file, log


def validate_paths(ctx: ProvisionContext) -> None:
    cfg = ctx.cfg
    if not cfg.scm_base_dir:
        fatal("scm.base_dir is required in rundeck/provisioning/config.yaml")
    if not cfg.rundeck_scripts_dir:
        fatal("rundeck_scripts_dir could not be derived (set scm.base_dir in rundeck/provisioning/config.yaml)")
    if not cfg.checks_path:
        fatal("checks_path could not be derived (set scm.base_dir in rundeck/provisioning/config.yaml)")
    if not cfg.inventory_path:
        fatal("inventory_path could not be derived (set scm.base_dir in rundeck/provisioning/config.yaml)")
    if not os.path.isfile(cfg.checks_path):
        fatal(f"checks catalog not readable: {cfg.checks_path}")
    if not os.path.isfile(cfg.inventory_path):
        fatal(f"inventory not readable: {cfg.inventory_path}")
    provision_main = os.path.join(cfg.rundeck_scripts_dir, "src", "__main__.py")
    if not os.path.isfile(provision_main):
        fatal(
            f"provisioner not found: {provision_main} "
            "(ensure rundeck/provisioning/scripts/ exists in the Git SCM checkout)"
        )


def validate_services(ctx: ProvisionContext) -> None:
    cfg = ctx.cfg
    cfg.validate_http_base_url("uptime_api_base_url", cfg.uptime_api_base_url)
    if not cfg.is_dry_run():
        if not cfg.uptime_api_token:
            fatal("uptime_api_token is required (env / Rundeck Key Storage)")
        if cfg.uptime_upsert_workers < 1:
            fatal("uptime.upsert_workers must be >= 1 in rundeck/provisioning/config.yaml")


def validate_inventory_content(ctx: ProvisionContext) -> None:
    hosts.validate_inventory_vars(ctx.static_inv)


def validate_provision_config(cfg: Config, static_inv: dict) -> None:
    """Raise fatal error when required operational keys are missing from config.yaml."""
    missing: list[str] = []
    if not cfg.scm_base_dir:
        missing.append("scm.base_dir")
    if not cfg.check_script_base:
        missing.append("provision.check_script_base")
    for key, attr in (
        ("rundeck.jobs.job_timeout", "rundeck_job_timeout"),
        ("rundeck.jobs.ssh_connect_timeout_ms", "rundeck_ssh_connect_timeout_ms"),
        ("rundeck.jobs.ssh_command_timeout_ms", "rundeck_ssh_command_timeout_ms"),
        ("rundeck.jobs.node_threadcount", "rundeck_node_threadcount"),
        ("rundeck.jobs.workflow_strategy", "rundeck_workflow_strategy"),
    ):
        if not getattr(cfg, attr, ""):
            missing.append(key)
    for key, attr in (
        ("python_bastion.hostname", "python_bastion_hostname"),
        ("python_bastion.username", "python_bastion_username"),
        ("python_bastion.ssh_key_storage_path", "python_bastion_ssh_key_storage_path"),
    ):
        if not getattr(cfg, attr, ""):
            missing.append(key)
    if not cfg.python_bastion_port:
        missing.append("python_bastion.port")
    if not cfg.ssh_key_storage_default:
        missing.append("ssh.key_storage_default")
    has_switch_roles = any(
        str(hosts.group_vars(static_inv, gid).get("netbox_kind") or "").lower() == "switch"
        for gid in hosts.netbox_role_slugs_from_inventory(static_inv)
    )
    if has_switch_roles:
        if not cfg.switch_ssh_username:
            missing.append("switch_ssh.username (required for switch role groups)")
        if not cfg.switch_ssh_password_key_storage_path:
            missing.append("switch_ssh.password_key_storage_path (required for switch role groups)")
    if missing:
        fatal("config.yaml missing required keys: " + ", ".join(missing))


def validate_netbox_config(ctx: ProvisionContext) -> None:
    cfg = ctx.cfg
    if hosts.netbox_import_active(ctx.static_inv, netbox_url=cfg.netbox_url):
        cfg.validate_http_base_url("netbox_url", cfg.netbox_url)
        if not cfg.netbox_token:
            fatal(
                "NETBOX_TOKEN (or NETBOX_TOKEN_FILE) is required "
                "when inventory declares NETBOX role groups (NetBox import enabled)"
            )
        if cfg.netbox_curl_max_time < 1:
            fatal("netbox.curl_max_time must be >= 1 in rundeck/provisioning/config.yaml")
        if cfg.netbox_curl_connect_timeout < 1:
            fatal("netbox.curl_connect_timeout must be >= 1 in rundeck/provisioning/config.yaml")
    elif hosts.netbox_import_requested(ctx.static_inv) and not cfg.netbox_url:
        log(
            "netbox: import skipped (netbox.url unset in rundeck/provisioning/config.yaml; static inventory hosts only). "
            "Set netbox.url in config.yaml + NETBOX_TOKEN in env, or all.vars.netbox.enabled: false to silence."
        )


def validate_catalog_against_inventory(ctx: ProvisionContext) -> None:
    inv_children = (ctx.inv.get("all") or {}).get("children") or {}
    if not ctx.checks.validate_groups(inv_children):
        fatal("checks reference unknown group(s) — see errors above")
    for check_id, spec in ctx.checks.by_id.items():
        one_host = spec.get("one_host")
        if one_host is not None and not isinstance(one_host, bool):
            fatal(f"check {check_id}: one_host must be a boolean")
        admin_rc = spec.get("admin_rc_path")
        if admin_rc is not None and (not isinstance(admin_rc, str) or not str(admin_rc).strip()):
            fatal(f"check {check_id}: admin_rc_path must be a non-empty string")
        explicit_id = spec.get("id")
        if explicit_id is not None and not isinstance(explicit_id, str):
            fatal(f"check {check_id}: id must be a string")
    seen_ids: set[str] = set()
    data = load_yaml_file(ctx.cfg.checks_path)
    for entry in (data.get("checks") if isinstance(data, dict) else []) or []:
        if not isinstance(entry, dict):
            continue
        rel = validate_catalog_path(entry)
        script_stem = paths.check_id_from_path(rel)
        explicit_id = entry.get("id")
        cid = paths.validate_check_id(str(explicit_id)) if explicit_id is not None else script_stem
        if cid in seen_ids:
            fatal(f"checks.yaml duplicate check id: {cid}")
        seen_ids.add(cid)
    if not ctx.checks.validate_script_paths(ctx.cfg.scm_base_dir):
        fatal("checks.yaml path(s) invalid or script(s) missing under SCM_BASE_DIR")


def log_netbox_status(ctx: ProvisionContext) -> None:
    cfg = ctx.cfg
    log(
        f"checks={cfg.checks_path} inventory={cfg.inventory_path} "
        f"job_group={cfg.rundeck_job_group} dry_run={cfg.is_dry_run()}"
    )
    if hosts.netbox_import_active(ctx.inv, netbox_url=cfg.netbox_url):
        log(f"netbox: NetBox role groups in inventory (NETBOX_URL={cfg.netbox_url})")
    elif hosts.netbox_import_requested(ctx.inv):
        log("netbox: role groups declared but NETBOX_URL unset — import skipped")
    else:
        log("netbox: no NETBOX role groups in inventory — NetBox device import disabled")


def validate_all(ctx: ProvisionContext) -> None:
    """Run all pre-NetBox validations."""
    validate_paths(ctx)
    validate_services(ctx)
    validate_inventory_content(ctx)
    validate_provision_config(ctx.cfg, ctx.static_inv)
    validate_netbox_config(ctx)
