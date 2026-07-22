"""Uptime heartbeat sync — create, update, and prune heartbeat checks.

Orchestrates the full Uptime heartbeat lifecycle:

1. Pre-load all existing checks and tags from the Uptime API.
2. Build :class:`UpsertTask` objects from the effective inventory and catalog.
3. Upsert each task (parallel or serial depending on ``UPTIME_UPSERT_WORKERS``).
4. Prune orphan checks whose names match the ``host__check`` pattern but are no
   longer in the expected set.
5. Return a list of :class:`PingRecord` objects used to populate the Rundeck
   ``uptime_ping_<check_id>`` node attributes in ``nodes.yaml``.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from src.configs.config import Config
from src.context import ProvisionContext
from src.api import uptime_api, http_client
from src.inventory import hosts
from src.utils.util import log, validate_slug


@dataclass(frozen=True)
class PingRecord:
    """Resolved Uptime ping URL for a single host/check combination."""

    host_id: str
    check_id: str
    ping_url: str


@dataclass(frozen=True)
class UpsertTask:
    """All information needed to create or update one Uptime heartbeat check."""

    host_id: str
    check_id: str
    slug: str                      # stable name: ``<host_id>__<check_id>``
    check_spec: dict[str, Any]     # merged catalog entry + script metadata
    tag_names: tuple[str, ...]     # Uptime tag names to assign


@dataclass
class UpsertResult:
    """Outcome of a single upsert attempt."""

    host_id: str
    check_id: str
    ping_url: str
    slug: str
    action: str = ""   # "created" | "updated" | "existing" | "would_create"
    error: str = ""    # non-empty when the upsert failed


def _uptime_tag_names(ctx: ProvisionContext, host_id: str, check_id: str) -> tuple[str, ...]:
    """Return the Uptime tag names for a host/check pair as an immutable tuple."""
    return tuple(
        hosts.uptime_site_tag_names(ctx.inv, host_id, check_id, ctx.indexes, ctx.cfg)
    )


def _process_upsert_task(
    task: UpsertTask,
    cfg: Config,
    client: uptime_api.UptimeClient,
    defaults: dict[str, Any],
    *,
    ping_base: str,
    checks_by_name: dict[str, dict[str, Any]],
    tags_by_name: dict[str, dict[str, Any]],
    checks_lock: threading.Lock | None = None,
    tags_lock: threading.Lock | None = None,
    session: http_client.HttpSession | None = None,
    use_thread_session: bool = False,
) -> UpsertResult:
    """Execute one upsert task and return the outcome.

    In dry-run mode no API calls are made; the existing check is looked up from
    the pre-loaded cache and the result action is set to ``"existing"`` or
    ``"would_create"``.  In live mode tags are resolved/created, and the check
    is created or patched via the Uptime API.

    When ``use_thread_session`` is ``True`` a per-thread session is obtained and
    closed on exit (used by the parallel worker pool).
    """
    active_session = http_client.thread_session(insecure=client.insecure) if use_thread_session else session
    try:
        payload = uptime_api.build_payload(
            task.host_id, task.check_id, task.check_spec, defaults
        )
        if cfg.is_dry_run():
            existing = checks_by_name.get(task.slug)
            if existing:
                ping_url = uptime_api.resolve_ping_url(ping_base, existing)
                action = "existing"
            else:
                ping_url = ""
                action = "would_create"
            return UpsertResult(task.host_id, task.check_id, ping_url, task.slug, action)

        tag_ids = client.ensure_tag_ids(
            list(task.tag_names),
            tags_by_name=tags_by_name,
            tags_lock=tags_lock,
            session=active_session,
        )
        payload["tag_ids"] = tag_ids

        existing = checks_by_name.get(task.slug)
        action = "updated" if existing else "created"
        check = client.upsert_heartbeat(
            payload,
            existing=existing,
            session=active_session,
        )
        if checks_lock is not None:
            with checks_lock:
                checks_by_name[task.slug] = check
        else:
            checks_by_name[task.slug] = check
        ping_url = uptime_api.resolve_ping_url(ping_base, check)
        return UpsertResult(task.host_id, task.check_id, ping_url, task.slug, action)
    except RuntimeError as exc:
        return UpsertResult(task.host_id, task.check_id, "", task.slug, "", str(exc))
    finally:
        if use_thread_session:
            http_client.close_thread_session()


def _run_parallel(
    cfg: Config,
    client: uptime_api.UptimeClient,
    tasks: list[UpsertTask],
    defaults: dict[str, Any],
    *,
    workers: int,
    ping_base: str,
    checks_by_name: dict[str, dict[str, Any]],
    tags_by_name: dict[str, dict[str, Any]],
    on_result: Any,
) -> list[UpsertResult]:
    """Run upsert tasks concurrently using a thread pool."""
    checks_lock = threading.Lock()
    tags_lock = threading.Lock()
    results: list[UpsertResult] = []
    log(f"upsert workers={workers} tasks={len(tasks)}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _process_upsert_task,
                task,
                cfg,
                client,
                defaults,
                ping_base=ping_base,
                checks_by_name=checks_by_name,
                tags_by_name=tags_by_name,
                checks_lock=checks_lock,
                tags_lock=tags_lock,
                use_thread_session=True,
            )
            for task in tasks
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            on_result(result)
    return results


def _run_sequential(
    cfg: Config,
    client: uptime_api.UptimeClient,
    tasks: list[UpsertTask],
    defaults: dict[str, Any],
    *,
    ping_base: str,
    checks_by_name: dict[str, dict[str, Any]],
    tags_by_name: dict[str, dict[str, Any]],
    session: http_client.HttpSession | None,
    on_result: Any,
) -> list[UpsertResult]:
    """Run upsert tasks serially, reusing the provided session."""
    results: list[UpsertResult] = []
    for task in tasks:
        result = _process_upsert_task(
            task,
            cfg,
            client,
            defaults,
            ping_base=ping_base,
            checks_by_name=checks_by_name,
            tags_by_name=tags_by_name,
            session=session,
        )
        results.append(result)
        on_result(result)
    return results


def _run_upserts(
    cfg: Config,
    client: uptime_api.UptimeClient,
    tasks: list[UpsertTask],
    defaults: dict[str, Any],
    *,
    ping_base: str,
    checks_by_name: dict[str, dict[str, Any]],
    tags_by_name: dict[str, dict[str, Any]],
    session: http_client.HttpSession | None = None,
) -> list[PingRecord]:
    """Run all upsert tasks (parallel or sequential) and return ping records."""
    workers = 1 if cfg.is_dry_run() else cfg.uptime_upsert_workers
    parallel = workers > 1
    own_session = session is None and not parallel
    if own_session:
        session = http_client.HttpSession(insecure=client.insecure)

    stats: dict[str, int] = {"created": 0, "updated": 0, "existing": 0, "would_create": 0, "failed": 0}
    done_count = 0
    log_interval = 50
    progress_lock = threading.Lock()

    def on_result(result: UpsertResult) -> None:
        nonlocal done_count
        with progress_lock:
            done_count += 1
            if result.error:
                stats["failed"] += 1
                log(f"skip {result.slug}: {result.error}")
            else:
                if result.action in stats:
                    stats[result.action] += 1
                if done_count == 1 or done_count % log_interval == 0 or done_count == len(tasks):
                    log(f"upsert progress {done_count}/{len(tasks)} (latest {result.slug})")

    try:
        if parallel:
            results = _run_parallel(
                cfg, client, tasks, defaults,
                workers=workers, ping_base=ping_base,
                checks_by_name=checks_by_name, tags_by_name=tags_by_name,
                on_result=on_result,
            )
        else:
            results = _run_sequential(
                cfg, client, tasks, defaults,
                ping_base=ping_base,
                checks_by_name=checks_by_name, tags_by_name=tags_by_name,
                session=session, on_result=on_result,
            )
    finally:
        if own_session and session is not None:
            session.close()

    ok = [r for r in results if r.ping_url]
    log(
        f"uptime heartbeats: {len(ok)}/{len(tasks)} ping URL(s) "
        f"(created={stats['created']} updated={stats['updated']} "
        f"existing={stats['existing']} would_create={stats['would_create']} failed={stats['failed']})"
    )
    return [
        PingRecord(host_id=r.host_id, check_id=r.check_id, ping_url=r.ping_url)
        for r in ok
    ]


def build_upsert_tasks(
    ctx: ProvisionContext,
) -> tuple[list[UpsertTask], set[str]]:
    """Build Uptime upsert tasks from effective inventory and checks catalog."""
    checks_meta = ctx.ensure_checks_meta()
    host_checks = hosts.host_checks_index(ctx.inv, ctx.checks, ctx.indexes)
    tasks: list[UpsertTask] = []
    expected_slugs: set[str] = set()

    for host_id in hosts.host_ids(ctx.inv, ctx.indexes):
        if not host_id or not validate_slug("host id", host_id):
            continue
        for check_id in host_checks.get(host_id, []):
            if not check_id or not validate_slug("check id", check_id):
                continue
            check_spec = checks_meta.get(check_id) or {}
            if not check_spec:
                log(f"skip {host_id}/{check_id}: no spec found")
                continue
            slug = f"{host_id}__{check_id}"
            tag_names = _uptime_tag_names(ctx, host_id, check_id)
            expected_slugs.add(slug)
            tasks.append(
                UpsertTask(host_id, check_id, slug, check_spec, tag_names)
            )
    return tasks, expected_slugs


def sync_uptime(
    ctx: ProvisionContext,
    tasks: list[UpsertTask],
    expected_slugs: set[str],
) -> list[PingRecord]:
    """Sync Uptime heartbeat checks and return ping URLs per host/check."""
    cfg = ctx.cfg
    defaults = ctx.cfg.uptime_defaults()
    effective_inv = ctx.inv
    insecure = not cfg.curl_secure
    ping_base = cfg.ping_base_url()
    log(f"uptime: api={cfg.uptime_api_base_url} ping_urls={ping_base}")

    client = uptime_api.UptimeClient.create(
        cfg.uptime_api_base_url,
        cfg.uptime_api_token,
        insecure=insecure,
    )
    checks_by_name: dict[str, dict[str, Any]] = {}
    tags_by_name: dict[str, dict[str, Any]] = {}

    with http_client.http_session(insecure=insecure) as preload_session:
        try:
            all_checks = client.list_all_checks(session=preload_session)
            checks_by_name = uptime_api.index_by_name(all_checks)
            log(f"preloaded {len(checks_by_name)} provisioned heartbeat name(s) from Uptime")
        except (RuntimeError, OSError) as exc:
            if cfg.is_dry_run():
                log(f"warn: could not preload Uptime checks ({exc}); dry-run ping URLs will be placeholders")
            else:
                raise
        if not cfg.is_dry_run():
            try:
                all_tags = client.list_all_tags(session=preload_session)
                tags_by_name = uptime_api.index_tags_by_name(all_tags)
                log(f"preloaded {len(tags_by_name)} Uptime tag(s)")
            except RuntimeError as exc:
                raise RuntimeError(f"could not preload Uptime tags: {exc}") from exc

        pings = _run_upserts(
            cfg,
            client,
            tasks,
            defaults,
            ping_base=ping_base,
            checks_by_name=checks_by_name,
            tags_by_name=tags_by_name,
            session=preload_session,
        )

        if not cfg.is_dry_run():
            with http_client.http_session(insecure=insecure) as session:
                client.prune_orphans(expected_slugs, session=session)

    if hosts.netbox_enabled(effective_inv):
        nb_hosts = hosts.netbox_role_host_ids(effective_inv)
        hosts_with_ping = {p.host_id for p in pings}
        nb_in_pings = sum(1 for h in nb_hosts if h in hosts_with_ping)
        log(
            f"netbox pings: {nb_in_pings} host(s) with Uptime ping URL(s) "
            "across NetBox role groups"
        )

    return pings
