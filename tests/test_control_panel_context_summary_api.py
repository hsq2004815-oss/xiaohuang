from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xiaohuang.control_panel_context_summary_api import ControlPanelContextSummaryApi
from xiaohuang.control_panel_web_service import ControlPanelWebApi
from xiaohuang.conversation_history_service import ConversationHistoryStore


class ControlPanelContextSummaryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConversationHistoryStore(Path(self.tmp.name) / "conversations.sqlite3")
        self.api = ControlPanelContextSummaryApi(history_store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_refresh_summary_handles_empty_conversation(self):
        conv = self.store.create_conversation(title="空对话")

        result = self.api.refresh_conversation_context_summary({"conversation_id": conv.id})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["current_goal"], "")
        self.assertEqual(result["data"]["current_status"], "当前对话暂无绑定任务。")
        self.assertEqual(result["data"]["next_step"], "先描述本对话要完成的目标。")
        self.assertIn("不自动启动 Agent", result["data"]["important_constraints"])

    def test_refresh_summary_uses_first_user_message_as_goal(self):
        conv = self.store.create_conversation(title="目标")
        self.store.save_user_message(conv.id, "完成 C5G.2 Conversation Context Summary MVP")

        result = self.api.refresh_conversation_context_summary({"conversation_id": conv.id})

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["data"]["current_goal"],
            "完成 C5G.2 Conversation Context Summary MVP",
        )
        self.assertIn("目标：完成 C5G.2", result["data"]["context_summary"])

    def test_refresh_summary_completed_or_review_tasks_status(self):
        conv = self.store.create_conversation()
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-completed",
            run_status="completed",
        )
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-review",
            run_status="in_review",
        )

        result = self.api.refresh_conversation_context_summary({"conversation_id": conv.id})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["current_status"], "当前绑定任务已完成或待验收。")
        self.assertEqual(result["data"]["next_step"], "进行验收并决定是否收口。")
        self.assertIn("已绑定 2 个 Multica 任务", result["data"]["bound_tasks_summary"])

    def test_refresh_summary_failed_task_next_step(self):
        conv = self.store.create_conversation()
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-failed",
            run_status="failed",
            review_summary="测试失败",
        )

        result = self.api.refresh_conversation_context_summary({"conversation_id": conv.id})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["current_status"], "当前存在失败任务，需要检查。")
        self.assertEqual(result["data"]["next_step"], "检查失败任务日志或 run-messages。")
        self.assertTrue(result["data"]["blockers"])

    def test_update_summary_does_not_cross_conversations(self):
        conv_a = self.store.create_conversation(title="A")
        conv_b = self.store.create_conversation(title="B")

        self.api.update_conversation_context_summary({
            "conversation_id": conv_a.id,
            "current_goal": "目标 A",
            "current_status": "状态 A",
            "next_step": "下一步 A",
            "important_constraints": ["约束 A"],
        })
        self.api.update_conversation_context_summary({
            "conversation_id": conv_b.id,
            "current_goal": "目标 B",
            "current_status": "状态 B",
            "next_step": "下一步 B",
            "important_constraints": ["约束 B"],
        })

        a = self.api.get_conversation_context_summary({"conversation_id": conv_a.id})
        b = self.api.get_conversation_context_summary({"conversation_id": conv_b.id})

        self.assertEqual(a["data"]["current_goal"], "目标 A")
        self.assertEqual(b["data"]["current_goal"], "目标 B")
        self.assertEqual(a["data"]["important_constraints"], ["约束 A"])
        self.assertEqual(b["data"]["important_constraints"], ["约束 B"])

    def test_refresh_does_not_call_llm_shell_or_multica(self):
        conv = self.store.create_conversation()
        with patch("xiaohuang.text_interaction_service.run_text_interaction_turn") as mock_llm, \
             patch.object(subprocess, "run") as mock_run, \
             patch("xiaohuang.multica_integration.cli_client.run_multica_argv") as mock_multica:
            result = self.api.refresh_conversation_context_summary({"conversation_id": conv.id})

        self.assertTrue(result["ok"])
        mock_llm.assert_not_called()
        mock_run.assert_not_called()
        mock_multica.assert_not_called()

    def test_control_panel_web_api_context_methods_are_thin_proxies(self):
        conv = self.store.create_conversation()
        api = ControlPanelWebApi(config_path=Path(self.tmp.name) / "config.json")
        api._history_store = self.store

        with patch(
            "xiaohuang.control_panel_context_summary_api.ControlPanelContextSummaryApi.refresh_conversation_context_summary",
            return_value={"ok": True, "data": {"conversation_id": conv.id}},
        ) as mock_refresh:
            result = api.refresh_conversation_context_summary({"conversation_id": conv.id})

        self.assertTrue(result["ok"])
        mock_refresh.assert_called_once_with({"conversation_id": conv.id})


if __name__ == "__main__":
    unittest.main()
