"""Uptime API helpers (heartbeats/checks for houston-provision)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.api import http_client

ORPHAN_NAME_RE = re.compile(r"^[a-z0-9_-]+__[a-z0-9_-]+$")


def site_origin(base: str) -> str:
    """Return scheme://host[:port] from an Uptime API or ping base URL."""
    base = base.rstrip("/")
    if "://" not in base:
        base = f"http://{base}"
    parsed = urlparse(base)
    return f"{parsed.scheme}://{parsed.netloc}"


def auth_headers(token: str) -> dict[str, str]:
    """Build the ``Authorization: Bearer <token>`` header dict."""
    return {"Authorization": f"Bearer {token}"}


@dataclass
class UptimeClient:
    """Single Uptime API client; reuse one instance per sync run."""

    origin: str
    headers: dict[str, str]
    insecure: bool

    @classmethod
    def create(
        cls,
        base: str,
        token: str,
        *,
        insecure: bool = False,
    ) -> UptimeClient:
        """Build a client for the given API base URL and token."""
        return cls(
            origin=site_origin(base),
            headers=auth_headers(token),
            insecure=insecure,
        )

    def get_json(
        self,
        path: str,
        *,
        session: http_client.HttpSession | None = None,
    ) -> dict[str, Any]:
        """GET the given API path and return the parsed JSON body as a dict."""
        data = http_client.get_json(
            f"{self.origin}{path}",
            headers=self.headers,
            insecure=self.insecure,
            session=session,
        )
        return data if isinstance(data, dict) else {}

    def get_paginated(
        self,
        path: str,
        *,
        limit: int = 500,
        session: http_client.HttpSession | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through an Uptime list endpoint and return all items.

        Stops when the returned batch is empty or the running offset reaches
        the ``total`` count reported by the API.
        """
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self.get_json(f"{path}?limit={limit}&offset={offset}", session=session)
            batch = data.get("data") or []
            out.extend(batch)
            total = int(data.get("total") or 0)
            offset += len(batch)
            if offset >= total or not batch:
                break
        return out

    def post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        session: http_client.HttpSession | None = None,
    ) -> tuple[int, Any]:
        """POST a JSON body to the given API path and return ``(status, parsed_body)``."""
        return http_client.post_json(
            f"{self.origin}{path}",
            body,
            headers=self.headers,
            insecure=self.insecure,
            session=session,
        )

    def patch_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        session: http_client.HttpSession | None = None,
    ) -> tuple[int, Any]:
        """PATCH a JSON body to the given API path and return ``(status, parsed_body)``."""
        return http_client.patch_json(
            f"{self.origin}{path}",
            body,
            headers=self.headers,
            insecure=self.insecure,
            session=session,
        )

    def delete(
        self,
        path: str,
        *,
        session: http_client.HttpSession | None = None,
    ) -> int:
        """Send a DELETE request to the given API path and return the HTTP status code."""
        return http_client.delete(
            f"{self.origin}{path}",
            headers=self.headers,
            session=session,
            insecure=self.insecure,
        )

    def list_all_checks(
        self,
        *,
        session: http_client.HttpSession | None = None,
    ) -> list[dict[str, Any]]:
        """List all heartbeat checks (REST /api/v1/sites, paginated)."""
        return self.get_paginated("/api/v1/sites", session=session)

    def list_all_tags(
        self,
        *,
        session: http_client.HttpSession | None = None,
    ) -> list[dict[str, Any]]:
        """List all Uptime tags."""
        data = self.get_json("/api/v1/tags", session=session)
        return list(data.get("data") or [])

    def create_tag(
        self,
        name: str,
        *,
        session: http_client.HttpSession | None = None,
    ) -> dict[str, Any]:
        """Create a tag via POST /api/v1/tags."""
        status, parsed = self.post_json("/api/v1/tags", {"name": name}, session=session)
        if status == 401:
            raise _auth_error()
        if status not in (200, 201) or not isinstance(parsed, dict) or parsed.get("id") is None:
            raise RuntimeError(f"POST tag {name!r} HTTP {status}: {parsed!r}")
        return parsed

    def ensure_tag(
        self,
        name: str,
        *,
        tags_by_name: dict[str, dict[str, Any]],
        tags_lock: threading.Lock | None = None,
        session: http_client.HttpSession | None = None,
    ) -> int:
        """Return tag id, creating the tag when missing."""
        def cached() -> dict[str, Any] | None:
            return tags_by_name.get(name)

        existing = cached()
        if existing and existing.get("id") is not None:
            return int(existing["id"])

        if tags_lock is not None:
            with tags_lock:
                existing = cached()
                if existing and existing.get("id") is not None:
                    return int(existing["id"])
                parsed = self.create_tag(name, session=session)
                tags_by_name[name] = parsed
                return int(parsed["id"])

        parsed = self.create_tag(name, session=session)
        tags_by_name[name] = parsed
        return int(parsed["id"])

    def ensure_tag_ids(
        self,
        names: list[str],
        *,
        tags_by_name: dict[str, dict[str, Any]],
        tags_lock: threading.Lock | None = None,
        session: http_client.HttpSession | None = None,
    ) -> list[int]:
        """Return a deduplicated list of Uptime tag ids, creating missing tags as needed."""
        ids: list[int] = []
        seen: set[int] = set()
        for name in names:
            tag_id = self.ensure_tag(
                name,
                tags_by_name=tags_by_name,
                tags_lock=tags_lock,
                session=session,
            )
            if tag_id not in seen:
                seen.add(tag_id)
                ids.append(tag_id)
        return ids

    def upsert_heartbeat(
        self,
        payload: dict[str, Any],
        *,
        existing: dict[str, Any] | None = None,
        session: http_client.HttpSession | None = None,
    ) -> dict[str, Any]:
        """Create or update a heartbeat check."""
        name = payload["name"]
        if existing is not None:
            check_id = existing["id"]
            status, parsed = self.patch_json(
                f"/api/v1/sites/{check_id}", payload, session=session
            )
            if status == 401:
                raise _auth_error()
            if status < 200 or status >= 300:
                raise RuntimeError(f"PATCH site {name} HTTP {status}: {parsed!r}")
            result = parsed if isinstance(parsed, dict) else existing
            if result.get("monitor_type") != "heartbeat":
                raise RuntimeError(
                    f"PATCH site {name}: expected monitor_type heartbeat, "
                    f"got {result.get('monitor_type')!r}"
                )
            return result

        status, parsed = self.post_json("/api/v1/sites", payload, session=session)
        if status == 401:
            raise _auth_error()
        if status < 200 or status >= 300:
            raise RuntimeError(f"POST site {name} HTTP {status}: {parsed!r}")
        if not isinstance(parsed, dict):
            raise RuntimeError(f"POST site {name}: empty or invalid JSON response")
        if parsed.get("monitor_type") != "heartbeat":
            raise RuntimeError(
                f"POST site {name}: expected monitor_type heartbeat, "
                f"got {parsed.get('monitor_type')!r}"
            )
        return parsed

    def delete_check(
        self,
        check_id: int | str,
        *,
        session: http_client.HttpSession | None = None,
    ) -> int:
        """Delete a heartbeat check by id."""
        return self.delete(f"/api/v1/sites/{check_id}", session=session)

    def prune_orphans(
        self,
        expected_slugs: set[str],
        *,
        checks: list[dict[str, Any]] | None = None,
        session: http_client.HttpSession | None = None,
    ) -> None:
        """Delete heartbeat checks whose slug is not in ``expected_slugs``.

        Only considers checks whose name matches the ``host__check`` slug
        pattern (``ORPHAN_NAME_RE``), so manually created monitors are
        never touched.  When ``checks`` is ``None`` the list is fetched from
        the API before pruning.
        """
        from src.utils.util import log

        if checks is None:
            checks = self.list_all_checks(session=session)
        pruned = 0
        for check in checks:
            name = check.get("name") or ""
            if not ORPHAN_NAME_RE.match(name):
                continue
            if name in expected_slugs:
                continue
            if check.get("monitor_type") and check.get("monitor_type") != "heartbeat":
                continue
            cid = check.get("id")
            if cid is None:
                continue
            status = self.delete_check(cid, session=session)
            if status in (200, 204):
                pruned += 1
                log(f"pruned orphan site {name} (id={cid})")
        if pruned:
            log(f"pruned {pruned} orphan site(s)")


def _auth_error() -> RuntimeError:
    return RuntimeError(
        "Uptime auth rejected the request. Verify UPTIME_API_TOKEN has write scope."
    )


def build_payload(
    host_id: str,
    check_id: str,
    check_spec: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Map inventory check spec to Uptime POST/PATCH body (without tag_ids)."""
    schedule = check_spec.get("schedule")
    timeout = check_spec.get("timeout")
    tz = check_spec.get("tz") or defaults.get("tz") or "UTC"
    grace = int(check_spec.get("grace") or defaults.get("grace") or 3600)

    if schedule is None and timeout is None:
        schedule = defaults.get("schedule")
    if schedule is None and timeout is None:
        raise RuntimeError(
            f"Check {host_id}/{check_id}: need schedule, timeout, or defaults.schedule"
        )

    core = check_spec.get("name") or check_id
    if defaults.get("prefix_host_in_check_name", True):
        display_name = f"[{host_id}] {core}"
    else:
        display_name = core

    stable_name = f"{host_id}__{check_id}"
    payload: dict[str, Any] = {
        "name": stable_name,
        "display_name": display_name,
        "monitor_type": "heartbeat",
        "heartbeat_grace_seconds": grace,
    }
    if check_spec.get("desc"):
        payload["notes"] = check_spec["desc"]

    if schedule is not None:
        payload["heartbeat_schedule_kind"] = "cron"
        payload["heartbeat_cron"] = schedule
        payload["heartbeat_timezone"] = tz
        payload["interval_seconds"] = max(10, int(timeout or defaults.get("timeout") or 3600))
    else:
        payload["heartbeat_schedule_kind"] = "interval"
        payload["interval_seconds"] = max(10, int(timeout))
    return payload


def index_by_name(checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index provisioned heartbeats by stable name (host__check slug)."""
    out: dict[str, dict[str, Any]] = {}
    for check in checks:
        name = check.get("name")
        if not name or not ORPHAN_NAME_RE.match(str(name)):
            continue
        out[str(name)] = check
    return out


def index_tags_by_name(tags: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index Uptime tags by name for O(1) lookup during upsert."""
    out: dict[str, dict[str, Any]] = {}
    for tag in tags:
        name = tag.get("name")
        if name:
            out[str(name)] = tag
    return out


def resolve_ping_url(base: str, check: dict[str, Any]) -> str:
    """Build the ping URL for a heartbeat check."""
    token = check.get("heartbeat_token") or ""
    if not token:
        raise RuntimeError(f"site {check.get('name')}: missing heartbeat_token")
    return f"{site_origin(base)}/ping/{token}"
