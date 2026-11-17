"""HTTP client with retries, per-host politeness and an on-disk response cache.

Public job APIs are free because people use them gently. Every request goes through
this client so the whole tool respects that: one shared connection pool, a minimum
interval between calls to the same host, exponential back-off on 429/5xx, and a
cache so repeated local runs do not hit the APIs at all.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from . import __version__

log = logging.getLogger(__name__)

REPOSITORY_URL = "https://github.com/statemilbay-cyber/remote-radar"
DEFAULT_USER_AGENT = f"remote-radar/{__version__} (+{REPOSITORY_URL})"
_RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A source could not be fetched or parsed."""


class HttpClient:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        ttl_seconds: int = 6 * 3600,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 2.0,
        min_interval: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._ttl = ttl_seconds
        self._retries = max(1, retries)
        self._backoff = backoff
        self._min_interval = min_interval
        self._last_call: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, application/rss+xml;q=0.9, */*;q=0.8",
            },
        )
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        key = self._cache_key(url, params)
        cached = self._read_cache(key)
        if cached is not None:
            log.debug("cache hit %s %s", url, params or "")
            return cached
        body = self._request(url, params)
        self._write_cache(key, body)
        return body

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        body = self.get_text(url, params)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(f"{url}: response is not valid JSON ({exc})") from exc

    # -- internals -----------------------------------------------------------------------

    def _request(self, url: str, params: dict[str, Any] | None) -> str:
        host = urlsplit(url).netloc
        last_error = "no attempt made"
        for attempt in range(1, self._retries + 1):
            self._wait_for(host)
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    return response.text
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in _RETRY_STATUS:
                    break
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < self._retries:
                    time.sleep(min(int(retry_after), 60))
                    continue
            if attempt < self._retries:
                delay = self._backoff**attempt
                log.debug("retrying %s in %.1fs (%s)", url, delay, last_error)
                time.sleep(delay)
        raise FetchError(f"{url}: {last_error}")

    def _wait_for(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_call.get(host, 0.0)
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call[host] = time.monotonic()

    @staticmethod
    def _cache_key(url: str, params: dict[str, Any] | None) -> str:
        raw = url + "?" + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _read_cache(self, key: str) -> str | None:
        if self._cache_dir is None:
            return None
        path = self._cache_dir / f"{key}.body"
        try:
            if time.time() - path.stat().st_mtime > self._ttl:
                return None
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _write_cache(self, key: str, body: str) -> None:
        if self._cache_dir is None:
            return
        tmp = self._cache_dir / f"{key}.tmp"
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self._cache_dir / f"{key}.body")
