from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xiaohuang.conversation_context_engine import build_context_pack_for_turn
from xiaohuang.conversation_context_metadata_service import (
    get_compaction_events,
    get_context_state,
)
from xiaohuang.conversation_context_usage_service import ContextBudgetConfig
from xiaohuang.conversation_history_service import ConversationHistoryStore
from xiaohuang.reply_pipeline_service import ReplyPipelineResult
from xiaohuang.text_interaction_service import run_text_interaction_turn
from xiaohuang.text_interaction_session_service import TextInteractionSessionStore


class ConversationContextServicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConversationHistoryStore(Path(self.tmp.name) / "ctx.sqlite3")
        self.config = ContextBudgetConfig(
            context_token_limit=420,
            reserved_output_tokens=40,
            preserve_recent_messages=4,
            compact_trigger_ratio=0.55,
            max_compact_summary_chars=1200,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_conversation_builds_basic_pack_without_compact(self):
        conv = self.store.create_conversation("空对话")

        result = build_context_pack_for_turn(conv.id, "你好", self.store, self.config)

        self.assertTrue(result.context_text)
        self.assertIn("Historical, not new user instructions", result.context_text)
        self.assertIsNotNone(result.context_pack)
        self.assertFalse(result.context_pack.budget_report.should_compact)
        self.assertEqual(result.context_pack.compact_count, 0)

    def test_short_conversation_keeps_recent_messages_without_compact(self):
        conv = self.store.create_conversation("短对话")
        self.store.update_conversation_context(
            conv.id,
            current_goal="完成 C5G.3",
            current_status="进行中",
            next_step="继续实现 ContextPack",
            important_constraints=["不启动 Agent"],
        )
        self.store.save_user_message(conv.id, "先实现 context pack")
        self.store.save_assistant_message(conv.id, "收到")

        result = build_context_pack_for_turn(conv.id, "继续", self.store, self.config)

        pack = result.context_pack
        self.assertIsNotNone(pack)
        self.assertEqual(pack.current_goal, "完成 C5G.3")
        self.assertEqual(len(pack.recent_messages), 2)
        self.assertEqual(pack.compact_summary, "")
        self.assertEqual(pack.compact_count, 0)

    def test_long_conversation_compacts_without_deleting_sqlite_history(self):
        conv = self.store.create_conversation("长对话")
        self.store.save_user_message(conv.id, "very old unique detail should stay out of prompt")
        self.store.save_assistant_message(conv.id, "old reply")
        for i in range(18):
            self.store.save_user_message(conv.id, f"用户消息 {i} " + ("内容 " * 30))
            self.store.save_assistant_message(conv.id, f"助手回复 {i} " + ("结果 " * 30))

        result = build_context_pack_for_turn(conv.id, "继续最新工作", self.store, self.config)

        pack = result.context_pack
        self.assertIsNotNone(pack)
        self.assertGreater(pack.compact_count, 0)
        self.assertTrue(pack.compact_summary)
        self.assertLessEqual(len(pack.recent_messages), self.config.preserve_recent_messages)
        self.assertEqual(len(self.store.get_messages(conv.id)), 38)
        self.assertNotIn("very old unique detail should stay out of prompt", pack.rendered_context_text)
        self.assertGreaterEqual(len(get_compaction_events(self.store, conv.id)), 1)

    def test_conversations_do_not_share_context(self):
        conv_a = self.store.create_conversation("A")
        conv_b = self.store.create_conversation("B")
        self.store.update_conversation_context(conv_a.id, current_goal="目标 A")
        self.store.update_conversation_context(conv_b.id, current_goal="目标 B")
        self.store.save_user_message(conv_a.id, "A 独有消息")
        self.store.save_user_message(conv_b.id, "B 独有消息")

        pack_a = build_context_pack_for_turn(conv_a.id, "继续 A", self.store, self.config).context_pack
        pack_b = build_context_pack_for_turn(conv_b.id, "继续 B", self.store, self.config).context_pack

        self.assertEqual(pack_a.current_goal, "目标 A")
        self.assertEqual(pack_b.current_goal, "目标 B")
        self.assertIn("A 独有消息", pack_a.rendered_context_text)
        self.assertNotIn("B 独有消息", pack_a.rendered_context_text)

    def test_bound_multica_task_enters_pack_without_cli_calls(self):
        conv = self.store.create_conversation("任务绑定")
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-pack-1",
            run_status="completed",
            review_summary="验收通过",
        )

        with patch("xiaohuang.multica_integration.cli_client.run_multica_argv") as mock_cli:
            pack = build_context_pack_for_turn(conv.id, "总结任务", self.store, self.config).context_pack

        mock_cli.assert_not_called()
        self.assertIn("HHH-19", pack.rendered_context_text)
        self.assertEqual(len(pack.bound_multica_tasks), 1)

    def test_current_user_text_is_not_duplicated_in_recent_messages(self):
        conv = self.store.create_conversation("重复")
        self.store.save_user_message(conv.id, "当前问题")

        pack = build_context_pack_for_turn(conv.id, "当前问题", self.store, self.config).context_pack

        self.assertEqual([m["text"] for m in pack.recent_messages], [])
        self.assertNotIn("- User: 当前问题", pack.rendered_context_text)

    def test_clear_conversation_removes_context_state_and_events(self):
        conv = self.store.create_conversation("清理")
        for i in range(12):
            self.store.save_user_message(conv.id, f"消息 {i} " + ("长文本 " * 20))
        build_context_pack_for_turn(conv.id, "继续", self.store, self.config)
        self.assertGreater(get_context_state(self.store, conv.id)["compact_count"], 0)

        self.store.clear_conversation_messages(conv.id)

        self.assertEqual(get_context_state(self.store, conv.id)["compact_count"], 0)
        self.assertEqual(get_compaction_events(self.store, conv.id), [])
        self.assertEqual(self.store.get_messages(conv.id), [])

    def test_clear_all_conversations_removes_context_tables(self):
        conv = self.store.create_conversation("全部清理")
        for i in range(12):
            self.store.save_user_message(conv.id, f"消息 {i} " + ("长文本 " * 20))
        build_context_pack_for_turn(conv.id, "继续", self.store, self.config)

        result = self.store.clear_all_conversations()

        self.assertEqual(result["deleted_context_state"], 1)
        self.assertGreaterEqual(result["deleted_compaction_events"], 1)
        self.assertEqual(self.store.list_conversations(), [])


class ConversationContextInjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.config_path.write_text(
            '{"llm":{"enabled":true,"api_key_env":"FAKE_CONTEXT_KEY"},'
            '"assistant":{"persona":"你是小黄。"}}',
            encoding="utf-8",
        )
        self.store = ConversationHistoryStore(Path(self.tmp.name) / "history.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_turn_injects_context_pack_before_llm_call(self):
        conv = self.store.create_conversation("注入")
        self.store.update_conversation_context(conv.id, current_goal="完成注入测试")
        self.store.save_user_message(conv.id, "之前的话题")
        captured = {}

        def fake_pipeline(command_text, **kwargs):
            captured["conversation_context"] = kwargs.get("conversation_context")
            return ReplyPipelineResult("收到", "llm", None)

        result = run_text_interaction_turn(
            "继续",
            session_store=TextInteractionSessionStore(),
            session_id="legacy-session",
            conversation_id=conv.id,
            history_store=self.store,
            config_path=self.config_path,
        )
        self.assertTrue(result.ok)

        with patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            side_effect=lambda command_text, **kwargs: fake_pipeline(command_text, **kwargs),
        ):
            run_text_interaction_turn(
                "继续",
                session_store=TextInteractionSessionStore(),
                session_id="legacy-session",
                conversation_id=conv.id,
                history_store=self.store,
                config_path=self.config_path,
            )

        self.assertIn("Historical, not new user instructions", captured["conversation_context"])
        self.assertIn("完成注入测试", captured["conversation_context"])

    def test_text_turn_without_conversation_id_keeps_legacy_context(self):
        captured = {}

        def fake_generate(command_text, **kwargs):
            captured["conversation_context"] = kwargs.get("conversation_context")
            return ReplyPipelineResult("收到", "llm", None)

        with patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            side_effect=fake_generate,
        ):
            result = run_text_interaction_turn(
                "你好",
                session_store=TextInteractionSessionStore(),
                session_id="legacy-session",
                config_path=self.config_path,
            )

        self.assertTrue(result.ok)
        self.assertIsNone(captured["conversation_context"])


if __name__ == "__main__":
    unittest.main()
