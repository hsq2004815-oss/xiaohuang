"""task_result_history_service.py — safe task result history persistence.

Saves sanitized summaries of completed/failed readonly text task results
to a local JSONL file. No database. No network. No sensitive data.

Module boundary:
- This module OWNS the history file path, sanitize rules, and JSONL I/O.
- control_panel_web_service.py only calls append_task_result() — never opens the file directly.
- text_task_execution_service.py does NOT persist history.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xiaohuang.text_task_execution_models import TextTaskExecutionResult
from xiaohuang.text_task_execution_service import (
    ALLOWED_AGENT_HANDOFF_TASK_TYPES,
    ALLOWED_AGENT_REVIEW_TASK_TYPES,
    ALLOWED_READONLY_TASK_TYPES,
)

_MAX_TITLE_CHARS = 100
_MAX_SUMMARY_CHARS = 300
_MAX_EXCERPT_CHARS = 500
_MAX_CACHE_SIZE = 100

_SAVEABLE_STATUSES = {"completed", "failed"}

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|apikey|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(bearer\s+)?([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+([^\s,;]+)"),
)

_cache: list[dict] = []
_cache_loaded: bool = False
_cache_project_root: Path | None = None


def _redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    value = _SENSITIVE_VALUE_PATTERNS[0].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_VALUE_PATTERNS[1].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_VALUE_PATTERNS[2].sub(r"Bearer <redacted>", value)
    return value


def _compact_text(text: str) -> str:
    s = str(text or "").replace("\n", " ").replace("\r", " ").strip()
    s = " ".join(s.split())
    idx = s.find("Traceback")
    if idx >= 0:
        s = s[:idx].strip() or "出现异常"
    return s


def _truncate_text(text: str, limit: int) -> str:
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def _tags_for_task_type(task_type: str) -> list[str]:
    tags: set[str] = {"readonly"}
    if task_type == "agent_handoff_draft":
        return ["agent", "handoff"]
    if task_type == "agent_completion_review":
        return ["agent", "review"]
    if task_type == "readonly_health_report":
        tags.add("health")
    elif task_type in ("readonly_recent_errors_review", "readonly_log_analysis"):
        tags.add("logs")
    elif task_type == "readonly_config_summary":
        tags.add("config")
    elif task_type == "readonly_runtime_events_review":
        tags.add("events")
    elif task_type in ("readonly_status_check", "readonly_diagnostic_review"):
        tags.add("diagnostic")
    return sorted(tags)


def _make_history_id() -> str:
    return "taskhist_" + uuid.uuid4().hex[:8]


def get_task_history_path(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / "data" / "task_history" / "task_results.jsonl"


def init_task_history(project_root: Path | str) -> None:
    """Load recent task history entries from JSONL into the in-memory cache."""
    global _cache, _cache_loaded, _cache_project_root
    root = Path(project_root).resolve()
    _cache_project_root = root
    _cache = []
    _cache_loaded = True

    file_path = get_task_history_path(root)
    try:
        if not file_path.is_file():
            return
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                _cache.append(entry)
        except (json.JSONDecodeError, TypeError):
            continue

    while len(_cache) > _MAX_CACHE_SIZE:
        _cache.pop(0)


def sanitize_task_result_for_history(
    result: TextTaskExecutionResult,
    task: dict | None = None,
) -> dict[str, Any]:
    """Transform a TextTaskExecutionResult into a safe history entry dict.

    Returns None-like empty dict fields if result should not be saved,
    but caller should check _should_save_result first.
    """
    task_dict = task if isinstance(task, dict) else {}
    now = datetime.now(timezone.utc).isoformat()

    raw_summary = str(result.summary or "")
    raw_details = str(result.details or "")
    raw_title = str(result.title or "")

    title = _truncate_text(_redact_sensitive_text(raw_title), _MAX_TITLE_CHARS)
    summary = _truncate_text(_redact_sensitive_text(raw_summary), _MAX_SUMMARY_CHARS)
    excerpt = _truncate_text(
        _redact_sensitive_text(_compact_text(raw_details)),
        _MAX_EXCERPT_CHARS,
    )

    task_type = str(result.task_type or "")
    tags = _tags_for_task_type(task_type)
    if task_type == "agent_handoff_draft":
        tags = _agent_handoff_tags(task_dict)
    elif task_type == "agent_completion_review":
        tags = _agent_review_tags(result)
    read_files_count = len(getattr(result, "read_files", ()) or ())
    result_kind = _result_kind_for_task_type(task_type)

    return {
        "history_id": _make_history_id(),
        "task_id": str(result.task_id or ""),
        "created_at": now,
        "completed_at": now,
        "task_type": task_type,
        "title": title,
        "status": str(result.status or ""),
        "ok": bool(result.ok),
        "risk_level": str(result.risk_level or "low"),
        "summary": summary,
        "safe_details_excerpt": excerpt,
        "source": "chat",
        "read_files_count": read_files_count,
        "result_kind": result_kind,
        "tags": tags,
        "schema_version": 1,
    }


def _should_save_result(result: TextTaskExecutionResult) -> bool:
    status = str(result.status or "").lower()
    if status not in _SAVEABLE_STATUSES:
        return False
    task_type = str(result.task_type or "")
    return task_type in (
        ALLOWED_READONLY_TASK_TYPES
        | ALLOWED_AGENT_HANDOFF_TASK_TYPES
        | ALLOWED_AGENT_REVIEW_TASK_TYPES
    )


def _result_kind_for_task_type(task_type: str) -> str:
    if task_type == "agent_handoff_draft":
        return "agent_handoff"
    if task_type == "agent_completion_review":
        return "agent_review"
    return "readonly_report"


def _agent_handoff_tags(task: dict[str, Any]) -> list[str]:
    tags = {"agent", "handoff"}
    try:
        from xiaohuang.agent_handoff.intent_parser import detect_target_agent
        target = detect_target_agent(str(task.get("original_text") or ""))
    except Exception:
        target = "generic"
    if target:
        tags.add(target)
    return sorted(tags)


def _agent_review_tags(result: TextTaskExecutionResult) -> list[str]:
    tags = {"agent", "review"}
    text = f"{result.summary}\n{result.details}".lower()
    if "verdict：reject" in text or "verdict: reject" in text or "不建议保留" in text:
        tags.add("reject")
    elif "verdict：insufficient" in text or "verdict: insufficient" in text or "信息不足" in text:
        tags.add("insufficient")
    elif "verdict：needs_review" in text or "verdict: needs_review" in text or "补充复查" in text:
        tags.add("needs_review")
    elif "verdict：keep" in text or "verdict: keep" in text or "建议保留" in text:
        tags.add("keep")
    return sorted(tags)


def _ensure_cache_for_root(project_root: Path | str) -> None:
    global _cache_project_root
    root = Path(project_root).resolve()
    if _cache_project_root != root:
        init_task_history(root)


def append_task_result(
    project_root: Path | str,
    result: TextTaskExecutionResult,
    task: dict | None = None,
) -> dict | None:
    """Sanitize and persist a task result to JSONL. Returns the entry or None.

    Never raises — all write/encode failures are caught internally.
    """
    global _cache

    if not _should_save_result(result):
        return None

    entry = sanitize_task_result_for_history(result, task=task)

    root = Path(project_root).resolve()
    _ensure_cache_for_root(root)
    file_path = get_task_history_path(root)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return None

    _cache.append(entry)
    while len(_cache) > _MAX_CACHE_SIZE:
        _cache.pop(0)

    return entry


def get_recent_task_results(
    project_root: Path | str,
    limit: int = 20,
) -> list[dict]:
    """Return the most recent task history entries (newest first) from cache."""
    root = Path(project_root).resolve()
    _ensure_cache_for_root(root)

    n = max(0, int(limit) if limit else 20)
    return list(reversed(_cache[-n:]))


def _reset_for_test() -> None:
    """Reset module-level state for test isolation. Test-only."""
    global _cache, _cache_loaded, _cache_project_root
    _cache = []
    _cache_loaded = False
    _cache_project_root = None
