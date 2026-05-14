"""SQLite metadata access for conversation compaction state."""

from __future__ import annotations

import sqlite3
from typing import Any

from xiaohuang.conversation_history_service import (
    ConversationHistoryStore,
    _ensure_valid_id,
    _json_dumps,
    _json_loads,
    _make_id,
    _now_iso,
)

_UPSERT_CONTEXT_STATE_SQL = """INSERT INTO conversation_context_state
    (conversation_id, compact_summary, compact_count, last_removed_message_count,
     last_compacted_message_id, last_compacted_at, last_budget_report_json)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(conversation_id) DO UPDATE SET
      compact_summary=excluded.compact_summary,
      compact_count=excluded.compact_count,
      last_removed_message_count=excluded.last_removed_message_count,
      last_compacted_message_id=excluded.last_compacted_message_id,
      last_compacted_at=excluded.last_compacted_at,
      last_budget_report_json=excluded.last_budget_report_json"""

_INSERT_COMPACTION_EVENT_SQL = """INSERT INTO conversation_compaction_events
    (id, conversation_id, compact_summary, removed_message_count,
     preserved_recent_count, estimated_tokens_before, estimated_tokens_after,
     created_at, meta_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""


def get_context_state(store: ConversationHistoryStore, conversation_id: str) -> dict[str, Any]:
    _ensure_valid_id(conversation_id, "conversation_id")
    with store._lock:
        conn = store._connect()
        try:
            row = conn.execute(
                "SELECT * FROM conversation_context_state WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            return _row_to_context_state(row) if row else _default_context_state(conversation_id)
        finally:
            conn.close()


def save_context_state(
    store: ConversationHistoryStore,
    conversation_id: str,
    *,
    compact_summary: str,
    compact_count: int,
    last_removed_message_count: int = 0,
    last_compacted_message_id: str = "",
    last_budget_report: dict | None = None,
) -> None:
    _ensure_valid_id(conversation_id, "conversation_id")
    now = _now_iso()
    with store._lock:
        conn = store._connect()
        try:
            existing = conn.execute(
                "SELECT last_compacted_at FROM conversation_context_state WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            compacted_at = (
                now if last_removed_message_count > 0 and last_compacted_message_id
                else (existing["last_compacted_at"] if existing else "")
            )
            conn.execute(
                _UPSERT_CONTEXT_STATE_SQL,
                (
                    conversation_id,
                    compact_summary or "",
                    _nonnegative_int(compact_count),
                    _nonnegative_int(last_removed_message_count),
                    last_compacted_message_id or "",
                    compacted_at,
                    _json_dumps(last_budget_report or {}),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def append_compaction_event(
    store: ConversationHistoryStore,
    conversation_id: str,
    *,
    compact_summary: str,
    removed_message_count: int = 0,
    preserved_recent_count: int = 0,
    estimated_tokens_before: int = 0,
    estimated_tokens_after: int = 0,
    meta: dict | None = None,
) -> dict[str, Any]:
    _ensure_valid_id(conversation_id, "conversation_id")
    event_id = _make_id()
    now = _now_iso()
    values = (
        event_id,
        conversation_id,
        compact_summary or "",
        _nonnegative_int(removed_message_count),
        _nonnegative_int(preserved_recent_count),
        _nonnegative_int(estimated_tokens_before),
        _nonnegative_int(estimated_tokens_after),
        now,
        _json_dumps(meta or {}),
    )
    with store._lock:
        conn = store._connect()
        try:
            conn.execute(_INSERT_COMPACTION_EVENT_SQL, values)
            conn.commit()
        finally:
            conn.close()
    return {
        "id": event_id,
        "conversation_id": conversation_id,
        "created_at": now,
        "removed_message_count": _nonnegative_int(removed_message_count),
        "preserved_recent_count": _nonnegative_int(preserved_recent_count),
    }


def get_compaction_events(store: ConversationHistoryStore, conversation_id: str) -> list[dict[str, Any]]:
    _ensure_valid_id(conversation_id, "conversation_id")
    with store._lock:
        conn = store._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM conversation_compaction_events
                   WHERE conversation_id=? ORDER BY created_at ASC, id ASC""",
                (conversation_id,),
            ).fetchall()
            return [_row_to_compaction_event(row) for row in rows]
        finally:
            conn.close()


def _default_context_state(conversation_id: str) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "compact_summary": "",
        "compact_count": 0,
        "last_removed_message_count": 0,
        "last_compacted_message_id": "",
        "last_compacted_at": "",
        "last_budget_report": {},
    }


def _nonnegative_int(value) -> int:
    return max(0, int(value or 0))


def _row_to_context_state(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "conversation_id": row["conversation_id"],
        "compact_summary": row["compact_summary"],
        "compact_count": int(row["compact_count"] or 0),
        "last_removed_message_count": int(row["last_removed_message_count"] or 0),
        "last_compacted_message_id": row["last_compacted_message_id"],
        "last_compacted_at": row["last_compacted_at"],
        "last_budget_report": _json_loads(row["last_budget_report_json"]) or {},
    }


def _row_to_compaction_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "compact_summary": row["compact_summary"],
        "removed_message_count": int(row["removed_message_count"] or 0),
        "preserved_recent_count": int(row["preserved_recent_count"] or 0),
        "estimated_tokens_before": int(row["estimated_tokens_before"] or 0),
        "estimated_tokens_after": int(row["estimated_tokens_after"] or 0),
        "created_at": row["created_at"],
        "meta": _json_loads(row["meta_json"]) or {},
    }
