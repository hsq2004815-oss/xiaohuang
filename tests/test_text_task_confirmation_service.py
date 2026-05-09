from __future__ import annotations

import unittest
from dataclasses import asdict

from xiaohuang.text_task_confirmation_service import (
    build_pending_text_task,
    format_pending_task_reply,
)
from xiaohuang.text_task_models import TextTaskIntentResult


class TextTaskConfirmationServiceTests(unittest.TestCase):
    def test_build_pending_text_task_maps_intent(self):
        intent = TextTaskIntentResult(
            is_task=True,
            task_type="readonly_log_analysis",
            title="分析最近日志错误",
            summary="读取项目 logs 目录中的最近日志并总结错误信息。",
            risk_level="low",
            allowed=True,
            reason="只读日志分析任务",
        )
        task = build_pending_text_task(intent, "帮我分析最近日志有没有错误")

        self.assertTrue(task.task_id)
        self.assertEqual(task.status, "pending_confirmation")
        self.assertTrue(task.allowed)
        self.assertEqual(task.risk_level, "low")
        self.assertEqual(task.title, "分析最近日志错误")
        self.assertIn("logs", task.summary)
        self.assertEqual(task.original_text, "帮我分析最近日志有没有错误")
        self.assertIn("task_id", asdict(task))

    def test_format_pending_task_reply_requires_confirmation(self):
        intent = TextTaskIntentResult(
            is_task=True,
            task_type="readonly_status_check",
            title="检查小黄当前状态",
            summary="读取小黄运行状态并总结当前服务。",
            risk_level="low",
            allowed=True,
        )
        task = build_pending_text_task(intent, "检查小黄当前状态")
        reply = format_pending_task_reply(task)

        self.assertIn("任务：检查小黄当前状态", reply)
        self.assertIn("需要你确认", reply)

    def test_format_blocked_task_reply_does_not_allow_execution(self):
        intent = TextTaskIntentResult(
            is_task=True,
            task_type="blocked_local_execution",
            title="受限本地执行请求",
            summary="用户请求执行本地命令。",
            risk_level="high",
            allowed=False,
        )
        task = build_pending_text_task(intent, "执行 powershell 删除文件")
        reply = format_pending_task_reply(task)

        self.assertIn("不允许执行", reply)
        self.assertIn("不会执行", reply)


if __name__ == "__main__":
    unittest.main()
