"""Top-level orchestration for the houston-provision pipeline."""

from __future__ import annotations

import shutil
import tempfile
import traceback

from src.api import netbox_api
from src.configs.config import Config
from src.context import ProvisionContext
from src.rundeck import job_gen
from src.scm import git_publish
from src.sync.rundeck_sync import emit_rundeck_artifacts
from src.sync.uptime_sync import build_upsert_tasks, sync_uptime
from src.utils import validators
from src.utils.util import fatal, log


def run(cfg: Config) -> None:
    """Validate config, allocate a temp workdir, run the pipeline, and clean up."""
    ctx = ProvisionContext.load(cfg)
    validators.validate_all(ctx)

    try:
        effective_inv = netbox_api.build_effective_inventory(ctx)
    except RuntimeError as exc:
        fatal(str(exc))

    ctx.set_effective_inventory(effective_inv)
    validators.validate_catalog_against_inventory(ctx)
    validators.log_netbox_status(ctx)

    workdir = tempfile.mkdtemp()
    try:
        _run_provision(ctx, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _run_provision(ctx: ProvisionContext, workdir: str) -> None:
    """Core provision logic: inventory → Uptime sync → Rundeck artifacts → git push."""
    ctx.ensure_checks_meta()
    jg = job_gen.load_rundeck_defaults(ctx.cfg, ctx.checks_meta)
    log(
        f"rundeck: job_timeout={jg.job_timeout} ssh_connect_ms={jg.ssh_connect_timeout_ms} "
        f"ssh_command_ms={jg.ssh_command_timeout_ms} threadcount={jg.node_threadcount} "
        f"strategy={jg.workflow_strategy} sequence_keepgoing={jg.sequence_keepgoing}"
    )

    tasks, expected_slugs = build_upsert_tasks(ctx)
    pings = sync_uptime(ctx, tasks, expected_slugs)
    emit_rundeck_artifacts(ctx, jg, pings, workdir)

    git_publish.commit_and_push(
        ctx.cfg.scm_base_dir,
        workdir,
        dry_run=ctx.cfg.is_dry_run(),
        auto_push=ctx.cfg.scm_auto_push_enabled(),
        git_username=ctx.cfg.scm_git_username,
        git_password=ctx.cfg.scm_git_password,
    )
    log("done")


def main() -> None:
    """CLI entry point: read config from environment, run pipeline, catch unexpected errors."""
    cfg = Config.from_env()
    try:
        run(cfg)
    except SystemExit:
        traceback.print_exc()
        raise
    except Exception as exc:
        traceback.print_exc()
        fatal(str(exc))
