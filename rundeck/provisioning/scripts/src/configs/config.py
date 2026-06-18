"""Configuration for houston-provision.

Non-secret settings are read from ``rundeck/provisioning/config.yaml`` under ``SCM_BASE_DIR``
(or ``PROVISION_CONFIG_PATH`` / ``CONFIG_PATH``).  They are not overridden by
environment variables or Rundeck job options.

Secrets (``UPTIME_API_TOKEN``, ``NETBOX_TOKEN``,
``OPENSTACK_PASSWORD``, ``SCM_GIT_PASSWORD``, optional ``NETBOX_TOKEN_FILE``)
are supplied via env / Key Storage only.

``SCM_BASE_DIR`` (or ``PROVISION_CONFIG_PATH``) is only used to locate
``config.yaml`` at startup.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields

from typing import Any

from src.utils.util import fatal, load_yaml_file


def _opt_env(name: str, *aliases: str) -> str:
    """Read an env var from ``NAME`` or ``RD_OPTION_NAME`` (Rundeck job options)."""
    for key in (name, f"RD_OPTION_{name}", *aliases, *(f"RD_OPTION_{a}" for a in aliases)):
        val = os.environ.get(key, "")
        if val:
            return val
    return ""


PROVISION_DIR = "rundeck/provisioning"


def _resolve_provision_config_path(scm_base_dir: str = "") -> str:
    """Return provision config YAML from env or ``{SCM_BASE_DIR}/rundeck/provisioning/config.yaml``."""
    explicit = _opt_env("PROVISION_CONFIG_PATH", "CONFIG_PATH")
    if explicit:
        return explicit
    scm = scm_base_dir or _opt_env("SCM_BASE_DIR")
    if scm:
        candidate = os.path.join(scm.rstrip("/"), PROVISION_DIR, "config.yaml")
        if os.path.isfile(candidate):
            return candidate
    return ""


_BOOL_FIELDS = frozenset({
    "dry_run", "scm_auto_push", "curl_secure",
})
_INT_FIELDS = frozenset({
    "netbox_curl_max_time", "netbox_curl_connect_timeout", "uptime_upsert_workers",
    "uptime_grace", "python_bastion_port", "switch_ssh_port",
})

_HTTP_BASE_URL_RE = re.compile(r"^https?://[^/\s'\"]+(?:/[^\s'\"]*)?$")


def _apply_yaml(cfg: Config, data: dict) -> None:
    """Populate ``cfg`` fields from a flat YAML mapping (snake_case keys)."""
    for f in fields(cfg):
        if f.name not in data or data[f.name] is None:
            continue
        raw = data[f.name]
        if f.name in _BOOL_FIELDS:
            setattr(cfg, f.name, bool(raw))
        elif f.name in _INT_FIELDS:
            setattr(cfg, f.name, int(raw))
        elif isinstance(raw, str):
            setattr(cfg, f.name, raw)
        else:
            setattr(cfg, f.name, str(raw))


def _apply_openstack_block(cfg: Config, data: dict) -> None:
    """Map nested ``openstack:`` from config.yaml onto flat Config fields."""
    block = data.get("openstack")
    if not isinstance(block, dict):
        return
    mapping = {
        "auth_url": "openstack_auth_url",
        "username": "openstack_username",
        "project_name": "openstack_project_name",
        "user_domain_name": "openstack_user_domain_name",
        "project_domain_name": "openstack_project_domain_name",
        "interface": "openstack_interface",
        "identity_api_version": "openstack_identity_api_version",
    }
    for src, dst in mapping.items():
        val = block.get(src)
        if val is not None:
            setattr(cfg, dst, str(val))


def _apply_uptime_block(cfg: Config, data: dict) -> None:
    block = data.get("uptime")
    if not isinstance(block, dict):
        return
    if block.get("grace") is not None:
        cfg.uptime_grace = int(block["grace"])
    if block.get("tz") is not None:
        cfg.uptime_tz = str(block["tz"])
    if block.get("api_base_url") is not None:
        cfg.uptime_api_base_url = str(block["api_base_url"])
    if block.get("ui_public_root") is not None:
        cfg.uptime_ui_public_root = str(block["ui_public_root"])
    if block.get("ping_base_url") is not None:
        cfg.uptime_ping_base_url = str(block["ping_base_url"])
    if block.get("upsert_workers") is not None:
        cfg.uptime_upsert_workers = int(block["upsert_workers"])


def _rundeck_jobs_source(data: dict) -> dict[str, Any] | None:
    """Return job-generation settings from ``rundeck.jobs`` or legacy ``rundeck_jobs``."""
    rd = data.get("rundeck")
    if isinstance(rd, dict):
        jobs = rd.get("jobs")
        if isinstance(jobs, dict):
            return jobs
    legacy = data.get("rundeck_jobs")
    return legacy if isinstance(legacy, dict) else None


def _apply_rundeck_jobs_block(cfg: Config, data: dict) -> None:
    block = _rundeck_jobs_source(data)
    if not block:
        return
    mapping = {
        "job_timeout": "rundeck_job_timeout",
        "ssh_connect_timeout_ms": "rundeck_ssh_connect_timeout_ms",
        "ssh_command_timeout_ms": "rundeck_ssh_command_timeout_ms",
        "node_threadcount": "rundeck_node_threadcount",
        "workflow_strategy": "rundeck_workflow_strategy",
        "sequence_keepgoing": "rundeck_sequence_keepgoing",
    }
    for src, dst in mapping.items():
        val = block.get(src)
        if val is not None:
            setattr(cfg, dst, str(val) if dst != "rundeck_sequence_keepgoing" else val)


def _apply_python_bastion_block(cfg: Config, data: dict) -> None:
    block = data.get("python_bastion")
    if not isinstance(block, dict):
        return
    if block.get("username") is not None:
        cfg.python_bastion_username = str(block["username"])
    if block.get("hostname") is not None:
        cfg.python_bastion_hostname = str(block["hostname"])
    if block.get("port") is not None:
        cfg.python_bastion_port = int(block["port"])
    if block.get("ssh_key_storage_path") is not None:
        cfg.python_bastion_ssh_key_storage_path = str(block["ssh_key_storage_path"])


def _apply_ssh_block(cfg: Config, data: dict) -> None:
    block = data.get("ssh")
    if not isinstance(block, dict):
        return
    if block.get("key_storage_default") is not None:
        cfg.ssh_key_storage_default = str(block["key_storage_default"])
    by_site = block.get("key_storage_by_site")
    if isinstance(by_site, dict):
        cfg.ssh_key_storage_by_site = {str(k): str(v) for k, v in by_site.items() if v}


def _apply_switch_ssh_block(cfg: Config, data: dict) -> None:
    block = data.get("switch_ssh")
    if not isinstance(block, dict):
        return
    if block.get("username") is not None:
        cfg.switch_ssh_username = str(block["username"])
    if block.get("port") is not None:
        cfg.switch_ssh_port = int(block["port"])
    if block.get("request_tty") is not None:
        cfg.switch_ssh_request_tty = bool(block["request_tty"])
    if block.get("password_key_storage_path") is not None:
        cfg.switch_ssh_password_key_storage_path = str(block["password_key_storage_path"])


def _apply_scm_block(cfg: Config, data: dict) -> None:
    block = data.get("scm")
    if not isinstance(block, dict):
        return
    if block.get("base_dir") is not None:
        cfg.scm_base_dir = str(block["base_dir"])
    if block.get("auto_push") is not None:
        cfg.scm_auto_push = bool(block["auto_push"])
    if block.get("git_username") is not None:
        cfg.scm_git_username = str(block["git_username"])


def _apply_provision_block(cfg: Config, data: dict) -> None:
    block = data.get("provision")
    if not isinstance(block, dict):
        return
    if block.get("dry_run") is not None:
        cfg.dry_run = bool(block["dry_run"])
    if block.get("check_script_base") is not None:
        cfg.check_script_base = str(block["check_script_base"])


def _apply_rundeck_block(cfg: Config, data: dict) -> None:
    block = data.get("rundeck")
    if not isinstance(block, dict):
        return
    mapping = {
        "resources_path": "rundeck_resources_path",
        "job_group": "rundeck_job_group",
        "job_group_groups": "rundeck_job_group_groups",
    }
    for src, dst in mapping.items():
        val = block.get(src)
        if val is not None:
            setattr(cfg, dst, str(val))


def _apply_netbox_block(cfg: Config, data: dict) -> None:
    block = data.get("netbox")
    if not isinstance(block, dict):
        return
    if block.get("url") is not None:
        cfg.netbox_url = str(block["url"])
    if block.get("curl_secure") is not None:
        cfg.curl_secure = bool(block["curl_secure"])
    if block.get("curl_max_time") is not None:
        cfg.netbox_curl_max_time = int(block["curl_max_time"])
    if block.get("curl_connect_timeout") is not None:
        cfg.netbox_curl_connect_timeout = int(block["curl_connect_timeout"])


def _finalize_paths(cfg: Config) -> None:
    """Derive checks/inventory paths from ``scm_base_dir`` when omitted in config.yaml."""
    scm = cfg.scm_base_dir.rstrip("/")
    if not scm:
        return
    if not cfg.checks_path:
        cfg.checks_path = f"{scm}/{PROVISION_DIR}/checks.yaml"
    if not cfg.inventory_path:
        cfg.inventory_path = f"{scm}/{PROVISION_DIR}/inventory.yaml"
    if not cfg.rundeck_scripts_dir:
        cfg.rundeck_scripts_dir = f"{scm}/{PROVISION_DIR}/scripts"


def _apply_env_secrets(cfg: Config) -> None:
    """Apply secret values from environment / Rundeck Key Storage (never from config.yaml)."""
    for field, env_name in (
        ("uptime_api_token", "UPTIME_API_TOKEN"),
        ("netbox_token", "NETBOX_TOKEN"),
        ("scm_git_password", "SCM_GIT_PASSWORD"),
        ("openstack_password", "OPENSTACK_PASSWORD"),
    ):
        val = _opt_env(env_name)
        if val:
            setattr(cfg, field, val)
    token_file = _opt_env("NETBOX_TOKEN_FILE")
    if token_file and os.path.isfile(token_file):
        with open(token_file, encoding="utf-8") as fh:
            cfg.netbox_token = fh.readline().strip()


@dataclass
class Config:
    """Flat bag of configuration values from rundeck/provisioning/config.yaml plus env secrets."""
    uptime_api_base_url: str = ""
    uptime_api_token: str = ""
    uptime_ui_public_root: str = ""
    uptime_ping_base_url: str = ""
    rundeck_resources_path: str = ""
    scm_base_dir: str = ""
    rundeck_scripts_dir: str = ""
    checks_path: str = ""
    inventory_path: str = ""
    dry_run: bool = False
    scm_auto_push: bool = False
    scm_git_password: str = ""
    scm_git_username: str = ""
    netbox_url: str = ""
    netbox_token: str = ""
    curl_secure: bool = False
    netbox_curl_max_time: int = 180
    netbox_curl_connect_timeout: int = 30
    rundeck_job_group: str = "houston"
    rundeck_job_group_groups: str = "houston-groups"
    uptime_upsert_workers: int = 0
    openstack_auth_url: str = ""
    openstack_username: str = ""
    openstack_project_name: str = ""
    openstack_user_domain_name: str = "Default"
    openstack_project_domain_name: str = "Default"
    openstack_interface: str = "public"
    openstack_identity_api_version: str = "3"
    openstack_password: str = ""
    uptime_grace: int = 3600
    uptime_tz: str = "UTC"
    check_script_base: str = "/var/tmp/rundeck"
    rundeck_job_timeout: str = ""
    rundeck_ssh_connect_timeout_ms: str = ""
    rundeck_ssh_command_timeout_ms: str = ""
    rundeck_node_threadcount: str = ""
    rundeck_workflow_strategy: str = ""
    rundeck_sequence_keepgoing: bool = False
    python_bastion_username: str = ""
    python_bastion_hostname: str = ""
    python_bastion_port: int = 22
    python_bastion_ssh_key_storage_path: str = ""
    ssh_key_storage_default: str = ""
    ssh_key_storage_by_site: dict[str, str] | None = None
    switch_ssh_username: str = ""
    switch_ssh_port: int = 22
    switch_ssh_request_tty: bool = True
    switch_ssh_password_key_storage_path: str = ""

    def uptime_defaults(self) -> dict[str, int | str]:
        """Uptime heartbeat defaults (grace, tz) from config.yaml."""
        return {"grace": self.uptime_grace, "tz": self.uptime_tz}

    def ssh_key_path_for_site(self, site_key: str) -> str:
        """Resolve SSH key storage path for a NetBox site slug."""
        by_site = self.ssh_key_storage_by_site or {}
        if site_key and site_key in by_site:
            return by_site[site_key]
        return self.ssh_key_storage_default

    def openstack_job_tokens(self) -> dict[str, str]:
        """Token map for per-check-openstack job template placeholders."""
        return {
            "OS_AUTH_URL": self.openstack_auth_url,
            "OS_USERNAME": self.openstack_username,
            "OS_PROJECT_NAME": self.openstack_project_name,
            "OS_USER_DOMAIN_NAME": self.openstack_user_domain_name,
            "OS_PROJECT_DOMAIN_NAME": self.openstack_project_domain_name,
            "OS_INTERFACE": self.openstack_interface,
            "OS_IDENTITY_API_VERSION": self.openstack_identity_api_version,
        }

    @classmethod
    def from_env(cls) -> Config:
        """Build a :class:`Config` from rundeck/provisioning/config.yaml plus env secrets."""
        scm_preview = _opt_env("SCM_BASE_DIR")
        config_path = _resolve_provision_config_path(scm_preview)
        if not config_path or not os.path.isfile(config_path):
            fatal(
                "provision config not found "
                "(set SCM_BASE_DIR or PROVISION_CONFIG_PATH to locate rundeck/provisioning/config.yaml)"
            )
        data = load_yaml_file(config_path)
        if not isinstance(data, dict):
            fatal(f"provision config must be a YAML mapping: {config_path}")
        cfg = cls()
        _apply_yaml(cfg, data)
        _apply_scm_block(cfg, data)
        _apply_provision_block(cfg, data)
        _apply_uptime_block(cfg, data)
        _apply_rundeck_block(cfg, data)
        _apply_rundeck_jobs_block(cfg, data)
        _apply_netbox_block(cfg, data)
        _apply_python_bastion_block(cfg, data)
        _apply_ssh_block(cfg, data)
        _apply_switch_ssh_block(cfg, data)
        _apply_openstack_block(cfg, data)
        _finalize_paths(cfg)
        _apply_env_secrets(cfg)
        return cfg

    def is_dry_run(self) -> bool:
        """Return True when the pipeline should simulate actions without writing."""
        return self.dry_run

    def scm_auto_push_enabled(self) -> bool:
        """Return True when the git push after provisioning is enabled."""
        return self.scm_auto_push

    def ping_base_url(self) -> str:
        """Return the origin used for uptime ping URLs reachable from Rundeck nodes."""
        return (self.uptime_ping_base_url or self.uptime_api_base_url).rstrip("/")

    def validate_http_base_url(self, var_name: str, value: str) -> None:
        """Validate that value is a well-formed http(s) URL without stray quotes or spaces."""
        if not value:
            fatal(f"{var_name} is empty")
        if not _HTTP_BASE_URL_RE.match(value):
            fatal(
                f"{var_name} must be http(s)://host[:port][/path] "
                f"without spaces or quotes, got: {value}"
            )
