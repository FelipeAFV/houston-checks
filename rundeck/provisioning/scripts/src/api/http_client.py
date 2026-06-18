"""HTTP client using stdlib ``http.client`` with per-host connection reuse.

Provides three usage patterns:

1. **Stateless helpers** (``get_json``, ``post_json``, ``patch_json``, ``delete``):
   create a one-shot connection per call via ``urllib.request``.

2. **Session** (``HttpSession`` / ``http_session`` context manager):
   reuse a single TCP connection across multiple requests to the same host,
   which is the preferred pattern for the Uptime sync pre-load + upsert loop.

3. **Thread-local session** (``thread_session`` / ``close_thread_session``):
   maintain one connection per thread for the parallel upsert worker pool.
"""

from __future__ import annotations

import http.client
import json
import ssl
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse


class HttpSession:
    """Reusable HTTP session that keeps a single TCP connection alive per host.

    Thread-safe: a lock serialises requests so the same session can be shared
    across a caller's sequential operations.  For parallel workers, create one
    session per thread via :func:`thread_session`.
    """

    def __init__(self, *, insecure: bool = False, timeout: int = 180) -> None:
        self.insecure = insecure
        self.timeout = timeout
        self._lock = threading.Lock()
        self._conn: http.client.HTTPConnection | http.client.HTTPSConnection | None = None
        self._conn_key: tuple[str, str, int] | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, bytes]:
        """Send an HTTP request and return ``(status_code, raw_body)``."""
        parsed = urlparse(url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        hdrs = dict(headers or {})
        if body is not None and "Content-Length" not in hdrs:
            hdrs["Content-Length"] = str(len(body))

        with self._lock:
            conn = self._connection(scheme, host, port)
            try:
                conn.request(method.upper(), path, body=body, headers=hdrs)
                resp = conn.getresponse()
                status = resp.status
                raw = resp.read()
            except (http.client.HTTPException, OSError):
                self._reset_connection()
                raise
            return status, raw

    def _connection(
        self, scheme: str, host: str, port: int
    ) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        """Return (or create) the underlying connection object for the given host."""
        key = (scheme, host, port)
        if self._conn is not None and self._conn_key == key:
            return self._conn
        self._reset_connection()
        if scheme == "https":
            ctx = None
            if self.insecure:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self._conn = http.client.HTTPSConnection(
                host, port, timeout=self.timeout, context=ctx
            )
        else:
            self._conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
        self._conn_key = key
        return self._conn

    def _reset_connection(self) -> None:
        """Close and discard the current connection (called on error or host change)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        self._conn = None
        self._conn_key = None

    def close(self) -> None:
        """Close the underlying TCP connection and release resources."""
        with self._lock:
            self._reset_connection()


@contextmanager
def http_session(*, insecure: bool = False, timeout: int = 180) -> Iterator[HttpSession]:
    """Context manager that yields an :class:`HttpSession` and closes it on exit."""
    session = HttpSession(insecure=insecure, timeout=timeout)
    try:
        yield session
    finally:
        session.close()


_thread_local = threading.local()


def thread_session(*, insecure: bool = False, timeout: int = 180) -> HttpSession:
    """Return (or lazily create) an :class:`HttpSession` stored in thread-local storage.

    Intended for the parallel upsert worker pool: each worker thread gets its
    own connection so requests don't block each other.  Callers must call
    :func:`close_thread_session` when the thread's work is done.
    """
    session = getattr(_thread_local, "session", None)
    if session is None or session.insecure != insecure or session.timeout != timeout:
        session = HttpSession(insecure=insecure, timeout=timeout)
        _thread_local.session = session
    return session


def close_thread_session() -> None:
    """Close and discard the thread-local :class:`HttpSession`."""
    session = getattr(_thread_local, "session", None)
    if session is not None:
        session.close()
        _thread_local.session = None


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 180,
    insecure: bool = False,
    session: HttpSession | None = None,
) -> tuple[int, bytes]:
    """Send a raw HTTP request and return ``(status_code, raw_body)``.

    When ``session`` is provided the request is routed through it (connection
    reuse).  Otherwise a one-shot ``urllib.request`` call is made.
    HTTP errors (4xx/5xx) are returned as normal status codes; network-level
    errors raise ``RuntimeError``.
    """
    if session is not None:
        return session.request(method, url, headers=headers, body=body)
    ctx = None
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, data=body, method=method.upper())
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed: {exc}") from exc


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 180,
    insecure: bool = False,
    session: HttpSession | None = None,
) -> Any:
    """GET a URL and return the parsed JSON body.

    Raises ``RuntimeError`` on non-2xx responses.
    """
    status, raw = request(
        "GET",
        url,
        headers=headers,
        timeout=timeout,
        insecure=insecure,
        session=session,
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"GET {url} HTTP {status}: {raw[:1200]!r}")
    return json.loads(raw.decode("utf-8"))


def _json_body_request(
    method: str,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 180,
    insecure: bool = False,
    session: HttpSession | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """Send a JSON-body request and return (status, parsed_body)."""
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    body = json.dumps(payload).encode("utf-8")
    status, raw = request(
        method,
        url,
        headers=hdrs,
        body=body,
        timeout=timeout,
        insecure=insecure,
        session=session,
    )
    parsed = None
    if raw:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = None
    return status, parsed


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 180,
    insecure: bool = False,
    session: HttpSession | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """POST JSON payload and return (status, parsed_body)."""
    return _json_body_request(
        "POST", url, payload,
        headers=headers, timeout=timeout, insecure=insecure, session=session,
    )


def patch_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 180,
    insecure: bool = False,
    session: HttpSession | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    """PATCH JSON payload and return (status, parsed_body)."""
    return _json_body_request(
        "PATCH", url, payload,
        headers=headers, timeout=timeout, insecure=insecure, session=session,
    )


def delete(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    session: HttpSession | None = None,
    insecure: bool = False,
) -> int:
    """Send a DELETE request and return the HTTP status code."""
    status, _ = request(
        "DELETE",
        url,
        headers=headers,
        timeout=timeout,
        session=session,
        insecure=insecure,
    )
    return status
