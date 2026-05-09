from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from xiaohuang.text_task_registry_service import PendingTextTaskRegistry


class PendingTextTaskRegistryTests(unittest.TestCase):
    def test_register_then_get(self):
        registry = PendingTextTaskRegistry(now_func=lambda: 10.0)
        record = registry.register(_task("task-1"))
        loaded = registry.get("task-1")

        self.assertEqual(record.task_id, "task-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, "pending")
        self.assertTrue(loaded.task["registered"])
        self.assertEqual(loaded.task["registry_status"], "pending")
        self.assertEqual(loaded.task["expires_at"], 310.0)

    def test_register_deepcopies_task(self):
        registry = PendingTextTaskRegistry()
        task = _task("task-1")
        record = registry.register(task)
        task["task_type"] = "blocked_local_execution"
        record.task["task_type"] = "changed"

        loaded = registry.get("task-1")

        self.assertEqual(loaded.task["task_type"], "readonly_log_analysis")

    def test_claim_moves_pending_to_executing(self):
        registry = PendingTextTaskRegistry()
        registry.register(_task("task-1"))

        record, reason = registry.claim_for_execution("task-1")

        self.assertEqual(reason, "")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "executing")
        self.assertEqual(registry.get("task-1").status, "executing")

    def test_same_task_cannot_be_claimed_twice(self):
        registry = PendingTextTaskRegistry()
        registry.register(_task("task-1"))
        registry.claim_for_execution("task-1")

        record, reason = registry.claim_for_execution("task-1")

        self.assertIsNone(record)
        self.assertEqual(reason, "already_executing")

    def test_mark_completed_prevents_reclaim(self):
        registry = PendingTextTaskRegistry()
        registry.register(_task("task-1"))
        registry.claim_for_execution("task-1")
        registry.mark_completed("task-1")

        record, reason = registry.claim_for_execution("task-1")

        self.assertIsNone(record)
        self.assertEqual(reason, "already_completed")

    def test_cancel_prevents_claim(self):
        registry = PendingTextTaskRegistry()
        registry.register(_task("task-1"))
        cancelled = registry.cancel("task-1")

        record, reason = registry.claim_for_execution("task-1")

        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNone(record)
        self.assertEqual(reason, "already_cancelled")

    def test_expired_task_cannot_be_claimed(self):
        now = [0.0]
        registry = PendingTextTaskRegistry(ttl_seconds=1.0, now_func=lambda: now[0])
        registry.register(_task("task-1"))
        now[0] = 2.0

        record, reason = registry.claim_for_execution("task-1")

        self.assertIsNone(record)
        self.assertEqual(reason, "expired")
        self.assertEqual(registry.get("task-1").status, "expired")

    def test_purge_expired_removes_expired_tasks(self):
        now = [0.0]
        registry = PendingTextTaskRegistry(ttl_seconds=1.0, now_func=lambda: now[0])
        registry.register(_task("task-1"))
        now[0] = 2.0

        purged = registry.purge_expired()

        self.assertEqual(purged, 1)
        self.assertIsNone(registry.get("task-1"))

    def test_max_tasks_limits_capacity(self):
        now = [0.0]
        registry = PendingTextTaskRegistry(max_tasks=2, now_func=lambda: now[0])
        registry.register(_task("task-1"))
        now[0] = 1.0
        registry.register(_task("task-2"))
        now[0] = 2.0
        registry.register(_task("task-3"))

        self.assertIsNone(registry.get("task-1"))
        self.assertIsNotNone(registry.get("task-2"))
        self.assertIsNotNone(registry.get("task-3"))

    def test_record_is_json_friendly(self):
        registry = PendingTextTaskRegistry()
        record = registry.register(_task("task-1"))

        json.dumps(asdict(record))


def _task(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "task_type": "readonly_log_analysis",
        "title": "分析最近日志错误",
        "summary": "读取项目 logs 目录中的最近日志并总结错误信息。",
        "risk_level": "low",
        "status": "pending_confirmation",
        "allowed": True,
        "original_text": "帮我分析最近日志有没有错误",
    }
