"""conversation_history_service.py — persistent conversation history + Multica task binding.

Stores conversations, messages, and conversation→Multica-task links in SQLite.
No auto-summarization, no LLM context injection (that's C5G.2).
Backend is the sole writer of messages; frontend only renders.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

_VALID_ID_RE = None  # compiled lazily in _is_valid_id

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    title: str
    created_at: str
    updated_at: str
    archived: bool = False
    message_count: int = 0
    last_preview: str = ""
    context_summary: str = ""
    current_goal: str = ""
    current_status: str = ""
    next_step: str = ""
    important_constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "archived": self.archived,
            "message_count": self.message_count,
            "last_preview": self.last_preview,
            "context_summary": self.context_summary,
            "current_goal": self.current_goal,
            "current_status": self.current_status,
            "next_step": self.next_step,
            "important_constraints": self.important_constraints,
        }


@dataclass(frozen=True)
class MessageRecord:
    id: str
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    text: str
    created_at: str
    meta: dict = field(default_factory=dict)
    pending_task_snapshot: dict | None = None
    execution_result_snapshot: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "text": self.text,
            "created_at": self.created_at,
            "meta": self.meta or {},
            "pending_task_snapshot": self.pending_task_snapshot,
            "execution_result_snapshot": self.execution_result_snapshot,
        }


@dataclass(frozen=True)
class ConversationMulticaTaskRecord:
    id: str
    conversation_id: str
    issue_id: str
    task_id: str
    run_status: str
    review_summary: str
    last_read_at: str
    messages_count: int = 0
    tool_use_count: int = 0
    tool_result_count: int = 0
    is_primary_binding: bool = True
    target_project_path: str = ""
    agent: str = ""
    title: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "issue_id": self.issue_id,
            "task_id": self.task_id,
            "run_status": self.run_status,
            "review_summary": self.review_summary,
            "last_read_at": self.last_read_at,
            "messages_count": self.messages_count,
            "tool_use_count": self.tool_use_count,
            "tool_result_count": self.tool_result_count,
            "is_primary_binding": self.is_primary_binding,
            "target_project_path": self.target_project_path,
            "agent": self.agent,
            "title": self.title,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _is_valid_id(value: str) -> bool:
    if not value or not isinstance(value, str):
        return False
    if len(value) > 64:
        return False
    # reject path traversal and shell metacharacters
    for ch in value:
        if ch in ('\\', '/', '.', '\x00', ';', '|', '&', '$', '`', "'", '"', '<', '>', '\n', '\r', '\t'):
            return False
    return True


def _ensure_valid_id(value: str, label: str = "id") -> None:
    if not _is_valid_id(value):
        raise ValueError(f"invalid {label}: {value!r}")


def _json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _json_loads(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ConversationHistoryStore:
    """Persistent store for conversations, messages, and Multica task bindings."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # -- internal ----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id            TEXT PRIMARY KEY,
                        title         TEXT NOT NULL DEFAULT '',
                        created_at    TEXT NOT NULL,
                        updated_at    TEXT NOT NULL,
                        archived      INTEGER NOT NULL DEFAULT 0,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        last_preview  TEXT NOT NULL DEFAULT '',
                        context_summary      TEXT NOT NULL DEFAULT '',
                        current_goal         TEXT NOT NULL DEFAULT '',
                        current_status       TEXT NOT NULL DEFAULT '',
                        next_step            TEXT NOT NULL DEFAULT '',
                        important_constraints TEXT NOT NULL DEFAULT '[]'
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id              TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                        text            TEXT NOT NULL DEFAULT '',
                        created_at      TEXT NOT NULL,
                        meta            TEXT NOT NULL DEFAULT '{}',
                        pending_task_snapshot     TEXT,
                        execution_result_snapshot TEXT,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_conv
                        ON messages(conversation_id, created_at);

                    CREATE TABLE IF NOT EXISTS conversation_multica_tasks (
                        id                TEXT PRIMARY KEY,
                        conversation_id   TEXT NOT NULL,
                        issue_id          TEXT NOT NULL DEFAULT '',
                        task_id           TEXT NOT NULL DEFAULT '',
                        run_status        TEXT NOT NULL DEFAULT '',
                        review_summary    TEXT NOT NULL DEFAULT '',
                        last_read_at      TEXT NOT NULL,
                        messages_count    INTEGER NOT NULL DEFAULT 0,
                        tool_use_count    INTEGER NOT NULL DEFAULT 0,
                        tool_result_count INTEGER NOT NULL DEFAULT 0,
                        is_primary_binding INTEGER NOT NULL DEFAULT 1,
                        target_project_path TEXT NOT NULL DEFAULT '',
                        agent             TEXT NOT NULL DEFAULT '',
                        title             TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_multica_conv
                        ON conversation_multica_tasks(conversation_id);

                    CREATE UNIQUE INDEX IF NOT EXISTS idx_multica_task_primary
                        ON conversation_multica_tasks(task_id)
                        WHERE task_id != '' AND is_primary_binding = 1;
                """)
                conn.commit()
            finally:
                conn.close()

    # -- conversations -----------------------------------------------------

    def create_conversation(self, title: str = "") -> ConversationRecord:
        conv_id = _make_id()
        now = _now_iso()
        resolved_title = title.strip() if title else "新对话"
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT INTO conversations (id, title, created_at, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (conv_id, resolved_title, now, now),
                )
                conn.commit()
            finally:
                conn.close()
        return ConversationRecord(id=conv_id, title=resolved_title, created_at=now, updated_at=now)

    def get_or_create_default(self) -> ConversationRecord:
        """Return the most recently updated conversation, or create a default one."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM conversations WHERE archived=0 ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if row:
                    return self._row_to_conversation(row)
            finally:
                conn.close()
        return self.create_conversation(title="默认对话")

    def list_conversations(self) -> list[ConversationRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE archived=0 ORDER BY updated_at DESC"
                ).fetchall()
                return [self._row_to_conversation(r) for r in rows]
            finally:
                conn.close()

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        _ensure_valid_id(conversation_id, "conversation_id")
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone()
                if row:
                    return self._row_to_conversation(row)
                return None
            finally:
                conn.close()

    def update_conversation_meta(
        self, conversation_id: str, *, title: str | None = None, last_preview: str | None = None
    ) -> None:
        _ensure_valid_id(conversation_id, "conversation_id")
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                if title is not None:
                    conn.execute(
                        "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                        (title, now, conversation_id),
                    )
                if last_preview is not None:
                    conn.execute(
                        "UPDATE conversations SET last_preview=?, updated_at=? WHERE id=?",
                        (last_preview, now, conversation_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def clear_conversation_messages(self, conversation_id: str) -> None:
        """Clear only messages for this conversation. Bound tasks are preserved."""
        _ensure_valid_id(conversation_id, "conversation_id")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
                conn.execute(
                    "UPDATE conversations SET message_count=0, last_preview='', updated_at=? WHERE id=?",
                    (_now_iso(), conversation_id),
                )
                conn.commit()
            finally:
                conn.close()

    def clear_all_conversations(self) -> dict[str, int]:
        """Delete all conversations, messages, and task bindings."""
        with self._lock:
            conn = self._connect()
            try:
                bound_tasks = conn.execute("DELETE FROM conversation_multica_tasks").rowcount
                messages = conn.execute("DELETE FROM messages").rowcount
                conversations = conn.execute("DELETE FROM conversations").rowcount
                conn.commit()
                return {
                    "deleted_conversations": max(0, conversations),
                    "deleted_messages": max(0, messages),
                    "deleted_bound_tasks": max(0, bound_tasks),
                }
            finally:
                conn.close()

    # -- messages ----------------------------------------------------------

    def save_message(self, message: MessageRecord) -> None:
        _ensure_valid_id(message.conversation_id, "conversation_id")
        _ensure_valid_id(message.id, "message_id")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO messages
                       (id, conversation_id, role, text, created_at, meta,
                        pending_task_snapshot, execution_result_snapshot)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message.id,
                        message.conversation_id,
                        message.role,
                        message.text,
                        message.created_at,
                        _json_dumps(message.meta),
                        _json_dumps(message.pending_task_snapshot),
                        _json_dumps(message.execution_result_snapshot),
                    ),
                )
                # Update conversation metadata
                now = _now_iso()
                preview = message.text.strip()[:60].replace("\n", " ")
                conn.execute(
                    """UPDATE conversations
                       SET message_count = (SELECT COUNT(*) FROM messages WHERE conversation_id=?),
                           last_preview = ?,
                           updated_at = ?
                       WHERE id=?""",
                    (message.conversation_id, preview, now, message.conversation_id),
                )
                # Auto-derive title from first user message (only if still default)
                _DEFAULT_TITLES = {"新对话", "默认对话"}
                existing = conn.execute(
                    "SELECT title, message_count FROM conversations WHERE id=?",
                    (message.conversation_id,),
                ).fetchone()
                if (
                    existing
                    and existing["message_count"] == 1
                    and message.role == "user"
                    and existing["title"] in _DEFAULT_TITLES
                ):
                    auto_title = message.text.strip()[:40].replace("\n", " ")
                    if auto_title:
                        conn.execute(
                            "UPDATE conversations SET title=? WHERE id=?",
                            (auto_title, message.conversation_id),
                        )
                conn.commit()
            finally:
                conn.close()

    def save_user_message(self, conversation_id: str, text: str) -> MessageRecord:
        msg = MessageRecord(
            id=_make_id(),
            conversation_id=conversation_id,
            role="user",
            text=text,
            created_at=_now_iso(),
        )
        self.save_message(msg)
        return msg

    def save_assistant_message(
        self,
        conversation_id: str,
        text: str,
        *,
        meta: dict | None = None,
        pending_task_snapshot: dict | None = None,
        execution_result_snapshot: dict | None = None,
    ) -> MessageRecord:
        msg = MessageRecord(
            id=_make_id(),
            conversation_id=conversation_id,
            role="assistant",
            text=text,
            created_at=_now_iso(),
            meta=meta or {},
            pending_task_snapshot=pending_task_snapshot,
            execution_result_snapshot=execution_result_snapshot,
        )
        self.save_message(msg)
        return msg

    def get_messages(self, conversation_id: str) -> list[MessageRecord]:
        _ensure_valid_id(conversation_id, "conversation_id")
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
                    (conversation_id,),
                ).fetchall()
                return [self._row_to_message(r) for r in rows]
            finally:
                conn.close()

    # -- Multica task bindings ---------------------------------------------

    def bind_multica_task(
        self,
        *,
        conversation_id: str,
        issue_id: str,
        task_id: str = "",
        run_status: str = "",
        review_summary: str = "",
        messages_count: int = 0,
        tool_use_count: int = 0,
        tool_result_count: int = 0,
        target_project_path: str = "",
        agent: str = "",
        title: str = "",
    ) -> ConversationMulticaTaskRecord:
        """Bind a Multica task to a conversation.

        If task_id is non-empty, it is the primary uniqueness key:
        attempting to bind the same task_id as primary to a different
        conversation raises ValueError.  Duplicate bindings to the
        SAME conversation update last_read_at / review_summary.

        If task_id is empty, the binding is issue-level only (no
        uniqueness guard beyond the record's own id).
        """
        _ensure_valid_id(conversation_id, "conversation_id")
        if task_id:
            _ensure_valid_id(task_id, "task_id")
        if issue_id:
            _ensure_valid_id(issue_id, "issue_id")
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                if task_id:
                    existing = conn.execute(
                        """SELECT id, conversation_id FROM conversation_multica_tasks
                           WHERE task_id=? AND is_primary_binding=1""",
                        (task_id,),
                    ).fetchone()
                    if existing:
                        if existing["conversation_id"] == conversation_id:
                            # Same conversation — update in place
                            conn.execute(
                                """UPDATE conversation_multica_tasks
                                   SET run_status=?, review_summary=?, last_read_at=?,
                                       messages_count=?, tool_use_count=?, tool_result_count=?
                                   WHERE id=?""",
                                (
                                    run_status, review_summary, now,
                                    messages_count, tool_use_count, tool_result_count,
                                    existing["id"],
                                ),
                            )
                            conn.commit()
                            row = conn.execute(
                                "SELECT * FROM conversation_multica_tasks WHERE id=?",
                                (existing["id"],),
                            ).fetchone()
                            return self._row_to_multica_task(row)
                        else:
                            raise ValueError(
                                f"task {task_id} is already bound to conversation "
                                f"{existing['conversation_id']}"
                            )

                record_id = _make_id()
                conn.execute(
                    """INSERT INTO conversation_multica_tasks
                       (id, conversation_id, issue_id, task_id, run_status,
                        review_summary, last_read_at, messages_count,
                        tool_use_count, tool_result_count, is_primary_binding,
                        target_project_path, agent, title)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (
                        record_id, conversation_id, issue_id, task_id,
                        run_status, review_summary, now,
                        messages_count, tool_use_count, tool_result_count,
                        target_project_path, agent, title,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM conversation_multica_tasks WHERE id=?", (record_id,)
                ).fetchone()
                return self._row_to_multica_task(row)
            finally:
                conn.close()

    def get_bound_tasks(self, conversation_id: str) -> list[ConversationMulticaTaskRecord]:
        _ensure_valid_id(conversation_id, "conversation_id")
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """SELECT * FROM conversation_multica_tasks
                       WHERE conversation_id=? AND is_primary_binding=1
                       ORDER BY last_read_at DESC""",
                    (conversation_id,),
                ).fetchall()
                return [self._row_to_multica_task(r) for r in rows]
            finally:
                conn.close()

    def get_primary_conversation_for_task(self, task_id: str) -> str | None:
        """Return the primary conversation_id for a task_id, or None."""
        if not task_id:
            return None
        _ensure_valid_id(task_id, "task_id")
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """SELECT conversation_id FROM conversation_multica_tasks
                       WHERE task_id=? AND is_primary_binding=1""",
                    (task_id,),
                ).fetchone()
                return row["conversation_id"] if row else None
            finally:
                conn.close()

    def get_bound_task_counts(self, conversation_id: str) -> dict[str, int]:
        """Return {status: count} dict for bound tasks."""
        _ensure_valid_id(conversation_id, "conversation_id")
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """SELECT run_status, COUNT(*) as cnt
                       FROM conversation_multica_tasks
                       WHERE conversation_id=? AND is_primary_binding=1
                       GROUP BY run_status""",
                    (conversation_id,),
                ).fetchall()
                return {r["run_status"] or "unknown": r["cnt"] for r in rows}
            finally:
                conn.close()

    # -- row converters ----------------------------------------------------

    @staticmethod
    def _row_to_conversation(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived=bool(row["archived"]),
            message_count=row["message_count"],
            last_preview=row["last_preview"],
            context_summary=row["context_summary"],
            current_goal=row["current_goal"],
            current_status=row["current_status"],
            next_step=row["next_step"],
            important_constraints=_json_loads(row["important_constraints"]) or [],
        )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            text=row["text"],
            created_at=row["created_at"],
            meta=_json_loads(row["meta"]) or {},
            pending_task_snapshot=_json_loads(row["pending_task_snapshot"]),
            execution_result_snapshot=_json_loads(row["execution_result_snapshot"]),
        )

    @staticmethod
    def _row_to_multica_task(row: sqlite3.Row) -> ConversationMulticaTaskRecord:
        return ConversationMulticaTaskRecord(
            id=row["id"],
            conversation_id=row["conversation_id"],
            issue_id=row["issue_id"],
            task_id=row["task_id"],
            run_status=row["run_status"],
            review_summary=row["review_summary"],
            last_read_at=row["last_read_at"],
            messages_count=row["messages_count"],
            tool_use_count=row["tool_use_count"],
            tool_result_count=row["tool_result_count"],
            is_primary_binding=bool(row["is_primary_binding"]),
            target_project_path=row["target_project_path"],
            agent=row["agent"],
            title=row["title"],
        )
