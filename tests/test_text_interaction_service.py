from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from xiaohuang.reply_pipeline_service import ReplyPipelineResult
from xiaohuang.text_interaction_service import run_text_interaction_turn
from xiaohuang.text_interaction_session_service import TextInteractionSessionStore


class TextInteractionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.config_path.write_text(
            '{"llm":{"enabled":true,"api_key_env":"FAKE_TEXT_CHAT_KEY"},'
            '"assistant":{"persona":"你是小黄。"}}',
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_input_returns_error(self):
        result = run_text_interaction_turn("", session_store=TextInteractionSessionStore())
        self.assertFalse(result.ok)
        self.assertIn("不能为空", result.error)

    def test_panel_command_guard_blocks_control_action(self):
        result = run_text_interaction_turn("启动小黄", session_store=TextInteractionSessionStore())
        self.assertTrue(result.ok)
        self.assertTrue(result.blocked_panel_command)
        self.assertEqual(result.reply_source, "panel_command_guard")
        self.assertIn("控制面板", result.reply_text)

    def test_memory_written_after_reply(self):
        store = TextInteractionSessionStore()
        with patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            return_value=ReplyPipelineResult("继续测试小黄项目。", "llm", None),
        ):
            result = run_text_interaction_turn(
                "我现在正在测试小黄项目",
                session_store=store,
                config_path=self.config_path,
            )
        self.assertTrue(result.ok)
        ctx = store.build_context_text("default")
        self.assertIn("小黄项目", ctx)
        self.assertIn("继续测试", ctx)

    def test_llm_result_mapping(self):
        with patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            return_value=ReplyPipelineResult("我是贾维斯", "llm", None),
        ):
            result = run_text_interaction_turn(
                "介绍一下你自己",
                session_store=TextInteractionSessionStore(),
                config_path=self.config_path,
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.reply_text, "我是贾维斯")
        self.assertEqual(result.reply_source, "llm")

    def test_result_does_not_leak_api_key(self):
        with patch.dict("os.environ", {"FAKE_TEXT_CHAT_KEY": "sk-test-secret"}), patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            return_value=ReplyPipelineResult("收到", "llm", None),
        ):
            result = run_text_interaction_turn(
                "介绍一下你自己",
                session_store=TextInteractionSessionStore(),
                config_path=self.config_path,
            )
        self.assertTrue(result.has_llm_key)
        self.assertTrue(result.llm_configured)
        self.assertNotIn("sk-", str(asdict(result)))


if __name__ == "__main__":
    unittest.main()
