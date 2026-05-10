"""Readonly client for the local database /brief API."""

from __future__ import annotations

import json
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from xiaohuang.agent_handoff.models import DatabaseBriefResult

DEFAULT_BRIEF_ENDPOINT = "http://127.0.0.1:8765/brief"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_MAX_BRIEF_CHARS = 2400
_MAX_TASK_CHARS = 1000


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

    request = Request(
        endpoint,
        data=json.dumps(_brief_request_body(query, domains), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    open_func = opener or urlopen

    try:
        response = open_func(request, timeout=timeout)
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


def _brief_request_body(query: str, domains: list[str]) -> dict[str, object]:
    limits = _limits_for_domains(domains)
    return {
        "task": str(query or "")[:_MAX_TASK_CHARS],
        **limits,
    }


def _limits_for_domains(domains: list[str]) -> dict[str, int]:
    values = set(str(item or "") for item in (domains or []))
    limits = {
        "ui_limit": 0,
        "workflow_limit": 0,
        "automation_limit": 0,
        "backend_limit": 0,
        "asset_limit": 0,
    }
    if not values:
        limits["workflow_limit"] = 5
        return limits
    if "ui_design" in values:
        limits["ui_limit"] = 8
    if values.intersection({"agent_workflow", "xiaohuang_project", "database", "voice_assistant"}):
        limits["workflow_limit"] = 5
    if "backend" in values:
        limits["backend_limit"] = 6
    if "browser_automation" in values:
        limits["automation_limit"] = 5
    return limits


def _extract_brief_text(response_text: str) -> str:
    text = str(response_text or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("database brief response was not valid JSON")
    if isinstance(data, dict):
        parts: list[str] = []
        for key in ("brief", "summary", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
                break
        parts.extend(_guidance_lines(data.get("guidance")))
        for chunk_key in ("ui_chunks", "workflow_chunks", "backend_chunks"):
            parts.extend(_chunk_lines(chunk_key, data.get(chunk_key)))
        return _compact("\n".join(parts))[:_MAX_BRIEF_CHARS]
    return ""


def _guidance_lines(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value[:5]:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
        elif isinstance(item, dict):
            text = _first_text(item, ("summary", "content", "text", "title"))
            if text:
                lines.append(text)
    return lines


def _chunk_lines(label: str, value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value[:2]:
        if not isinstance(item, dict):
            continue
        heading = _first_text(item, ("source_name", "title", "source", "name"))
        section = _first_text(item, ("section",))
        content = _first_text(item, ("summary", "content", "text"))
        pieces = [part for part in (heading, section, content[:320] if content else "") if part]
        if pieces:
            lines.append(f"{label}: " + " | ".join(pieces))
    return lines


def _first_text(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _compact(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines)
