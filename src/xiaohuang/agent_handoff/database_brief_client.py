"""Readonly client for the local database /brief API."""

from __future__ import annotations

import json
from typing import Callable
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from xiaohuang.agent_handoff.models import DatabaseBriefResult

DEFAULT_BRIEF_ENDPOINT = "http://127.0.0.1:8765/brief"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_MAX_BRIEF_CHARS = 2400


def fetch_database_brief(
    *,
    query: str,
    domains: list[str],
    endpoint: str = DEFAULT_BRIEF_ENDPOINT,
    timeout: float = 3.0,
    opener: Callable[..., object] | None = None,
) -> DatabaseBriefResult:
    if not _is_allowed_endpoint(endpoint):
        return DatabaseBriefResult(
            database_used=False,
            database_status="forbidden_endpoint",
            error_message="database brief endpoint must be localhost or 127.0.0.1",
        )

    params = urlencode({
        "query": str(query or "")[:500],
        "domain": ",".join(domains or []),
    })
    url = endpoint + ("&" if "?" in endpoint else "?") + params
    open_func = opener or urlopen

    try:
        response = open_func(url, timeout=timeout)
        try:
            raw = response.read()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        brief = _extract_brief_text(text)
        if not brief:
            return DatabaseBriefResult(
                database_used=False,
                database_status="empty",
                error_message="database brief response was empty",
            )
        return DatabaseBriefResult(
            database_used=True,
            database_status="used",
            brief=brief[:_MAX_BRIEF_CHARS],
        )
    except Exception as exc:
        return DatabaseBriefResult(
            database_used=False,
            database_status="unavailable",
            error_message=str(exc),
        )


def _is_allowed_endpoint(endpoint: str) -> bool:
    parsed = urlparse(str(endpoint or ""))
    return parsed.scheme == "http" and (parsed.hostname or "").lower() in _ALLOWED_HOSTS


def _extract_brief_text(response_text: str) -> str:
    text = str(response_text or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _compact(text)
    if isinstance(data, dict):
        for key in ("brief", "summary", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return _compact(value)
        items = data.get("items")
        if isinstance(items, list):
            parts = []
            for item in items[:8]:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for key in ("brief", "summary", "text", "content", "title"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value)
                            break
            return _compact("\n".join(parts))
    return _compact(text)


def _compact(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines)
