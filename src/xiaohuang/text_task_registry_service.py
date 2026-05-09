"""In-memory registry for pending text tasks."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import replace
from typing import Any, Callable

from xiaohuang.text_task_registry_models import PendingTaskRecord

PENDING_TASK_STATUS = "pending"
EXECUTING_TASK_STATUS = "executing"
COMPLETED_TASK_STATUS = "completed"
BLOCKED_TASK_STATUS = "blocked"
FAILED_TASK_STATUS = "failed"
CANCELLED_TASK_STATUS = "cancelled"
EXPIRED_TASK_STATUS = "expired"


class PendingTextTaskRegistry:
    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        max_tasks: int = 100,
        now_func: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = max(0.0, float(ttl_seconds))
        self._max_tasks = max(1, int(max_tasks))
        self._now = now_func or time.time
        self._records: dict[str, PendingTaskRecord] = {}
        self._lock = threading.RLock()

    def register(self, pending_task: dict[str, Any]) -> PendingTaskRecord:
        with self._lock:
            self.purge_expired()
            now = self._now()
            task = copy.deepcopy(pending_task if isinstance(pending_task, dict) else {})
            task_id = str(task.get("task_id") or f"text-task-{uuid.uuid4().hex}")
            expires_at = now + self._ttl_seconds
            task["task_id"] = task_id
            task["registered"] = True
            task["registry_status"] = PENDING_TASK_STATUS
            task["expires_at"] = expires_at
            task["expires_in_seconds"] = self._ttl_seconds
            record = PendingTaskRecord(
                task_id=task_id,
                task=task,
                status=PENDING_TASK_STATUS,
                created_at=now,
                expires_at=expires_at,
            )
            self._records[task_id] = record
            self._enforce_capacity()
            return self._copy_record(self._records[task_id])

    def get(self, task_id: str) -> PendingTaskRecord | None:
        with self._lock:
            record = self._records.get(str(task_id or ""))
            if record is None:
                return None
            if self._is_expired(record):
                record = self._mark_status(record.task_id, EXPIRED_TASK_STATUS, "expired")
            return self._copy_record(record)

    def claim_for_execution(self, task_id: str) -> tuple[PendingTaskRecord | None, str]:
        with self._lock:
            key = str(task_id or "")
            record = self._records.get(key)
            if record is None:
                return None, "not_found"
            if self._is_expired(record):
                self._mark_status(key, EXPIRED_TASK_STATUS, "expired")
                return None, "expired"
            if record.status != PENDING_TASK_STATUS:
                return None, self._reason_for_status(record.status)
            updated = self._mark_status(key, EXECUTING_TASK_STATUS)
            return self._copy_record(updated), ""

    def mark_completed(self, task_id: str) -> None:
        with self._lock:
            self._mark_status(str(task_id or ""), COMPLETED_TASK_STATUS)

    def mark_blocked(self, task_id: str, error: str = "") -> None:
        with self._lock:
            self._mark_status(str(task_id or ""), BLOCKED_TASK_STATUS, error)

    def mark_failed(self, task_id: str, error: str = "") -> None:
        with self._lock:
            self._mark_status(str(task_id or ""), FAILED_TASK_STATUS, error)

    def cancel(self, task_id: str) -> PendingTaskRecord | None:
        with self._lock:
            key = str(task_id or "")
            record = self._records.get(key)
            if record is None:
                return None
            if self._is_expired(record):
                record = self._mark_status(key, EXPIRED_TASK_STATUS, "expired")
            elif record.status == PENDING_TASK_STATUS:
                record = self._mark_status(key, CANCELLED_TASK_STATUS)
            return self._copy_record(record)

    def purge_expired(self) -> int:
        with self._lock:
            expired_keys = [
                task_id
                for task_id, record in self._records.items()
                if record.status == EXPIRED_TASK_STATUS or self._is_expired(record)
            ]
            for task_id in expired_keys:
                del self._records[task_id]
            return len(expired_keys)

    def _mark_status(self, task_id: str, status: str, error: str = "") -> PendingTaskRecord:
        record = self._records.get(task_id)
        if record is None:
            raise KeyError(task_id)
        task = copy.deepcopy(record.task)
        task["registry_status"] = status
        completed_at = record.completed_at
        if status in {
            COMPLETED_TASK_STATUS,
            BLOCKED_TASK_STATUS,
            FAILED_TASK_STATUS,
            CANCELLED_TASK_STATUS,
            EXPIRED_TASK_STATUS,
        }:
            completed_at = self._now()
        updated = replace(
            record,
            task=task,
            status=status,
            completed_at=completed_at,
            error=str(error or ""),
        )
        self._records[task_id] = updated
        return updated

    def _enforce_capacity(self) -> None:
        while len(self._records) > self._max_tasks:
            removable = sorted(
                (
                    record
                    for record in self._records.values()
                    if record.status != EXECUTING_TASK_STATUS
                ),
                key=lambda item: item.created_at,
            )
            if not removable:
                return
            del self._records[removable[0].task_id]

    def _is_expired(self, record: PendingTaskRecord) -> bool:
        return record.status == PENDING_TASK_STATUS and self._now() >= record.expires_at

    @staticmethod
    def _copy_record(record: PendingTaskRecord) -> PendingTaskRecord:
        return replace(record, task=copy.deepcopy(record.task))

    @staticmethod
    def _reason_for_status(status: str) -> str:
        if status == EXECUTING_TASK_STATUS:
            return "already_executing"
        if status == COMPLETED_TASK_STATUS:
            return "already_completed"
        if status == CANCELLED_TASK_STATUS:
            return "already_cancelled"
        if status == EXPIRED_TASK_STATUS:
            return "expired"
        return "not_pending"
