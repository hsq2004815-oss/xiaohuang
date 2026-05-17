"""tool_transcript_service.py — SQLite persistence for tool call history.

Aligned with claw-code's session transcript pattern: every tool_use and
tool_result is persisted as an auditable record linked to conversations.

Tables:
- conversation_tool_turns: one row per agent turn with tool rounds
- conversation_tool_calls: one row per tool invocation
- conversation_tool_results: one row per tool result (paired with call)
- conversation_tool_permissions: one row per permission evaluation

Cleanup is coordinated with conversation deletions so tool records don't
outlive their parent conversation.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from xiaohuang.tool_runtime.tool_types import (
    ToolCall,
    ToolResult,
    ToolPermissionDecision,
    ToolTurnRecord,
)


def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class ToolTranscriptService:
    """Persist tool turn records to SQLite.

    Uses the same database as ConversationHistoryStore for transactional
    consistency when cleaning up conversations.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS conversation_tool_turns (
                        id                  TEXT PRIMARY KEY,
                        conversation_id     TEXT NOT NULL,
                        user_message_id     TEXT NOT NULL DEFAULT '',
                        first_assistant_message_id TEXT NOT NULL DEFAULT '',
                        final_assistant_message_id TEXT NOT NULL DEFAULT '',
                        status              TEXT NOT NULL DEFAULT '',
                        tool_rounds         INTEGER NOT NULL DEFAULT 0,
                        max_tool_rounds     INTEGER NOT NULL DEFAULT 0,
                        created_at          TEXT NOT NULL,
                        completed_at        TEXT NOT NULL DEFAULT '',
                        error               TEXT NOT NULL DEFAULT ''
                    );

                    CREATE TABLE IF NOT EXISTS conversation_tool_calls (
                        id                  TEXT PRIMARY KEY,
                        turn_id             TEXT NOT NULL,
                        conversation_id     TEXT NOT NULL,
                        assistant_message_id TEXT NOT NULL DEFAULT '',
                        tool_name           TEXT NOT NULL,
                        arguments_json      TEXT NOT NULL DEFAULT '{}',
                        source              TEXT NOT NULL DEFAULT '',
                        risk_level          TEXT NOT NULL DEFAULT '',
                        readonly            INTEGER NOT NULL DEFAULT 1,
                        created_at          TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS conversation_tool_results (
                        id                  TEXT PRIMARY KEY,
                        tool_call_id        TEXT NOT NULL,
                        conversation_id     TEXT NOT NULL,
                        tool_name           TEXT NOT NULL,
                        ok                  INTEGER NOT NULL DEFAULT 0,
                        output              TEXT NOT NULL DEFAULT '',
                        error               TEXT NOT NULL DEFAULT '',
                        truncated           INTEGER NOT NULL DEFAULT 0,
                        elapsed_ms          INTEGER NOT NULL DEFAULT 0,
                        created_at          TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS conversation_tool_permissions (
                        id                  TEXT PRIMARY KEY,
                        tool_call_id        TEXT NOT NULL,
                        conversation_id     TEXT NOT NULL,
                        allowed             INTEGER NOT NULL DEFAULT 0,
                        requires_confirmation INTEGER NOT NULL DEFAULT 0,
                        reason              TEXT NOT NULL DEFAULT '',
                        risk_level          TEXT NOT NULL DEFAULT '',
                        created_at          TEXT NOT NULL
                    );
                """)
            finally:
                conn.close()

    # -- write ---------------------------------------------------------------

    def record_turn(self, record: ToolTurnRecord) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO conversation_tool_turns
                       (id, conversation_id, user_message_id,
                        first_assistant_message_id, final_assistant_message_id,
                        status, tool_rounds, max_tool_rounds,
                        created_at, completed_at, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.id, record.conversation_id, record.user_message_id,
                        record.first_assistant_message_id, record.final_assistant_message_id,
                        record.status, record.tool_rounds, record.max_tool_rounds,
                        record.created_at, record.completed_at, record.error,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def record_tool_call(self, tool_call: ToolCall, spec_risk_level: str = "") -> None:
        import json

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT INTO conversation_tool_calls
                       (id, turn_id, conversation_id, assistant_message_id,
                        tool_name, arguments_json, source, risk_level, readonly, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tool_call.id, tool_call.turn_id, tool_call.conversation_id,
                        "", tool_call.tool_name,
                        json.dumps(tool_call.arguments, ensure_ascii=False, default=str),
                        "", spec_risk_level, 1, tool_call.created_at or _now_iso(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def record_tool_result(self, result: ToolResult) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT INTO conversation_tool_results
                       (id, tool_call_id, conversation_id, tool_name,
                        ok, output, error, truncated, elapsed_ms, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _make_id(), result.tool_call_id, "",
                        result.tool_name, 1 if result.ok else 0,
                        result.output, result.error, 1 if result.truncated else 0,
                        result.elapsed_ms, result.created_at or _now_iso(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def record_permission(
        self,
        tool_call_id: str,
        conversation_id: str,
        decision: ToolPermissionDecision,
    ) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT INTO conversation_tool_permissions
                       (id, tool_call_id, conversation_id,
                        allowed, requires_confirmation, reason, risk_level, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _make_id(), tool_call_id, conversation_id,
                        1 if decision.allowed else 0,
                        1 if decision.requires_confirmation else 0,
                        decision.reason, decision.risk_level, _now_iso(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    # -- read ----------------------------------------------------------------

    def get_turns(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """SELECT * FROM conversation_tool_turns
                       WHERE conversation_id = ? ORDER BY created_at DESC""",
                    (conversation_id,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    def get_calls_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """SELECT * FROM conversation_tool_calls
                       WHERE turn_id = ? ORDER BY created_at""",
                    (turn_id,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    def get_results_for_call(self, tool_call_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """SELECT * FROM conversation_tool_results
                       WHERE tool_call_id = ? ORDER BY created_at""",
                    (tool_call_id,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    # -- cleanup -------------------------------------------------------------

    def delete_for_conversation(self, conversation_id: str) -> None:
        """Delete all tool records for a conversation."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM conversation_tool_turns WHERE conversation_id = ?",
                    (conversation_id,),
                )
                conn.execute(
                    "DELETE FROM conversation_tool_calls WHERE conversation_id = ?",
                    (conversation_id,),
                )
                conn.execute(
                    "DELETE FROM conversation_tool_results WHERE conversation_id = ?",
                    (conversation_id,),
                )
                conn.execute(
                    "DELETE FROM conversation_tool_permissions WHERE conversation_id = ?",
                    (conversation_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_all(self) -> None:
        """Delete all tool records (for full conversation clear)."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM conversation_tool_turns")
                conn.execute("DELETE FROM conversation_tool_calls")
                conn.execute("DELETE FROM conversation_tool_results")
                conn.execute("DELETE FROM conversation_tool_permissions")
                conn.commit()
            finally:
                conn.close()
