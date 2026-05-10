"""runtime_events/service.py — event recording to ring buffer + JSONL.

No STT / LLM / TTS calls. No threads. No process launch.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from xiaohuang.capabilities.runtime_events.models import RuntimeEvent

_SENSITIVE_KEYS = {
    "api_key", "api_key_env", "secret", "password", "token",
    "authorization", "access_key", "private_key",
}
_MAX_BUFFER = 200
_DEFAULT_LIMIT = 30
_MAX_LIMIT = 100

_ring: list[dict] = []
_jsonl_path: Path | None = None


def init_event_logger(project_root: str | Path) -> None:
    """Set JSONL path and load recent events from disk into the ring buffer."""
    global _jsonl_path
    _jsonl_path = Path(project_root) / "logs" / "runtime_events.jsonl"
    _load_recent_from_disk(50)


def record_event(
    source: str,
    event_type: str,
    message: str,
    *,
    level: str = "info",
    details: dict | None = None,
) -> RuntimeEvent:
    """Record an event to memory ring buffer and JSONL. Never raises."""
    event = RuntimeEvent.now(
        source=source,
        event_type=event_type,
        message=message,
        level=level,
        details=_sanitize_dict(details or {}),
    )
    _append_to_ring(event.to_dict())
    _append_to_jsonl(event)
    return event


def get_recent_events(limit: int = _DEFAULT_LIMIT) -> list[dict]:
    """Return recent events from the memory ring buffer."""
    n = max(1, min(limit, _MAX_LIMIT))
    return list(_ring[-n:])


def clear_recent_events() -> int:
    """Clear in-memory runtime events and return the number of removed events.

    This only clears the memory ring buffer. It does not delete any files,
    logs, or diagnostic exports.
    """
    count = len(_ring)
    _ring.clear()
    return count


def _append_to_ring(entry: dict) -> None:
    _ring.append(entry)
    while len(_ring) > _MAX_BUFFER:
        _ring.pop(0)


def _append_to_jsonl(event: RuntimeEvent) -> None:
    if _jsonl_path is None:
        return
    try:
        _jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with open(_jsonl_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # write failure must not crash the main pipeline


def _load_recent_from_disk(count: int) -> None:
    if _jsonl_path is None or not _jsonl_path.exists():
        return
    try:
        lines = _jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-count:]:
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    _ring.append(_sanitize_dict(entry))
            except (json.JSONDecodeError, TypeError):
                pass
        while len(_ring) > _MAX_BUFFER:
            _ring.pop(0)
    except Exception:
        pass


def _sanitize_dict(d: dict) -> dict:
    return {
        k: _sanitize_value(v) for k, v in d.items()
        if k.lower() not in _SENSITIVE_KEYS
    }


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_dict(value)
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "..."
    return value
