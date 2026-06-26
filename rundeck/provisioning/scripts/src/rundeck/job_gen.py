"""Rundeck job YAML generation — per-check and per-group job files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.configs.config import Config
from src.utils.util import log


@dataclass
class JobGenDefaults:
    """Immutable snapshot of Rundeck job-generation parameters from ``config.yaml``."""

    scm_base_dir: str
    job_timeout: str
    ssh_connect_timeout_ms: str
    ssh_command_timeout_ms: str
    node_threadcount: str
    workflow_strategy: str
    sequence_keepgoing: str
    bastion_host: str
    bastion_user: str
    bastion_port: str
    bastion_key_storage: str
    bastion_ssh_keypath: str
    switch_password_key_storage: str


def load_rundeck_defaults(
    cfg: Config,
    checks_meta: dict[str, dict[str, Any]],
) -> JobGenDefaults:
    """Parse config.yaml and return a :class:`JobGenDefaults` ready for use."""
    keepgoing = cfg.rundeck_sequence_keepgoing
    return JobGenDefaults(
        scm_base_dir=str(cfg.scm_base_dir),
        job_timeout=str(cfg.rundeck_job_timeout),
        ssh_connect_timeout_ms=str(cfg.rundeck_ssh_connect_timeout_ms),
        ssh_command_timeout_ms=str(cfg.rundeck_ssh_command_timeout_ms),
        node_threadcount=str(cfg.rundeck_node_threadcount),
        workflow_strategy=str(cfg.rundeck_workflow_strategy),
        sequence_keepgoing=str(keepgoing).lower(),
        bastion_host=str(cfg.python_bastion_hostname),
        bastion_user=str(cfg.python_bastion_username),
        bastion_port=str(cfg.python_bastion_port),
        bastion_key_storage=str(cfg.python_bastion_ssh_key_storage_path),
        bastion_ssh_keypath="",
        switch_password_key_storage=str(cfg.switch_ssh_password_key_storage_path),
    )


def render_template(tpl_path: Path, out_path: Path, tokens: dict[str, str]) -> None:
    """Replace ``__KEY__`` placeholders in a template file and write the result."""
    text = tpl_path.read_text(encoding="utf-8")
    for key, value in tokens.items():
        escaped = value.replace("\\", "\\\\").replace("|", "\\|").replace("&", "\\&")
        text = text.replace(f"__{key}__", escaped)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")


def emit_per_check(
    cfg: Any,
    jg: JobGenDefaults,
    check_id: str,
    display_name: str,
    description: str,
    executor: str,
    *,
    catalog_spec: dict[str, Any] | None = None,
) -> None:
    """Render a per-check Rundeck job YAML and write it to the SCM repo."""
    job_dir = Path(cfg.scm_base_dir) / "rundeck/jobs/per-check"
    tpl_dir = Path(cfg.rundeck_scripts_dir) / "templates"
    out = job_dir / f"{check_id}.yaml"
    tokens: dict[str, str] = {
        "CHECK_ID": check_id,
        "DISPLAY_NAME": display_name,
        "DESCRIPTION": description,
        "EXECUTOR": executor,
        "JOB_GROUP": cfg.rundeck_job_group,
        "SCM_BASE_DIR": jg.scm_base_dir,
        "RUNDECK_SCRIPTS_DIR": f"{jg.scm_base_dir.rstrip('/')}/rundeck/provisioning/scripts",
        "JOB_TIMEOUT": jg.job_timeout,
        "SSH_CONNECT_TIMEOUT_MS": jg.ssh_connect_timeout_ms,
        "SSH_COMMAND_TIMEOUT_MS": jg.ssh_command_timeout_ms,
        "NODE_THREADCOUNT": jg.node_threadcount,
        "WORKFLOW_STRATEGY": jg.workflow_strategy,
        "SEQUENCE_KEEPGOING": jg.sequence_keepgoing,
        "CHECK_SCRIPT_BASE": str(cfg.check_script_base or "/var/tmp/rundeck"),
    }
    tpl = tpl_dir / "per-check.yaml.tpl"
    if executor == "python":
        tpl = tpl_dir / "per-check-python.yaml.tpl"
    elif executor == "python_bastion":
        tpl = tpl_dir / "per-check-python-bastion.yaml.tpl"
    elif executor == "shell_bastion":
        tpl = tpl_dir / "per-check-shell-bastion.yaml.tpl"
        tokens["SWITCH_PASSWORD_KEY_STORAGE"] = jg.switch_password_key_storage
    render_template(tpl, out, tokens)


def _jobrefs_yaml(cfg: Any, group_tag: str, check_ids: list[str]) -> str:
    if len(check_ids) == 1:
        check_id = check_ids[0]
        return f"""      - jobref:
          group: {cfg.rundeck_job_group}
          name: houston - {check_id}
          nodefilters:
            filter: "tags: {group_tag}+check-{check_id}"
            dispatch:
              keepgoing: true
              threadcount: 1
"""
    parts = []
    for check_id in check_ids:
        parts.append(
            f"""      - jobref:
          group: {cfg.rundeck_job_group}
          name: houston - {check_id}
          nodefilters:
            filter: "tags: check-{check_id} AND tags: {group_tag}"
            dispatch:
              keepgoing: true
              threadcount: 1
"""
        )
    return "\n".join(parts)


def emit_per_group(
    cfg: Any,
    jg: JobGenDefaults,
    group_id: str,
    group_tag: str,
    description: str,
    check_ids: list[str],
) -> None:
    """Render a per-group Rundeck job YAML that dispatches to each per-check job."""
    tpl_dir = Path(cfg.rundeck_scripts_dir) / "templates"
    out = Path(cfg.scm_base_dir) / "rundeck/jobs/per-group" / f"{group_id}.yaml"
    render_template(
        tpl_dir / "per-group.yaml.tpl",
        out,
        {
            "GROUP_ID": group_id,
            "GROUP_TAG": group_tag,
            "DESCRIPTION": description,
            "JOB_GROUP": cfg.rundeck_job_group_groups,
            "JOB_TIMEOUT": jg.job_timeout,
            "PARENT_NODE_FILTER": "name: local",
            "JOBREFS": _jobrefs_yaml(cfg, group_tag, check_ids),
        },
    )


def prune_dir(cfg: Any, kind: str, current_ids: list[str]) -> None:
    """Remove stale job YAML files from a ``rundeck/jobs/<kind>/`` directory."""
    d = Path(cfg.scm_base_dir) / "rundeck/jobs" / kind
    if not d.is_dir():
        return
    current = set(current_ids)
    for f in d.glob("*.yaml"):
        cid = f.stem
        if cid not in current:
            log(f"[jg] prune stale {kind} job: {f}")
            f.unlink()
