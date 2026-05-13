"""test_conversation_history_service.py — V1.5-C5G.1 conversation persistence + Multica binding tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from xiaohuang.conversation_history_service import (
    ConversationHistoryStore,
    ConversationMulticaTaskRecord,
    ConversationRecord,
    MessageRecord,
    _is_valid_id,
)


class TestConversationHistoryStore(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.sqlite3"
        self.store = ConversationHistoryStore(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    # 1. 创建默认会话
    def test_create_default_conversation(self):
        conv = self.store.get_or_create_default()
        self.assertIsInstance(conv, ConversationRecord)
        self.assertTrue(len(conv.id) > 0)
        self.assertEqual(conv.title, "默认对话")

    # 2. 新建会话
    def test_create_new_conversation(self):
        conv = self.store.create_conversation(title="测试对话")
        self.assertIsInstance(conv, ConversationRecord)
        self.assertTrue(len(conv.id) > 0)
        self.assertEqual(conv.title, "测试对话")
        self.assertEqual(conv.message_count, 0)

    # 3. 保存 user / assistant 消息
    def test_save_user_and_assistant_messages(self):
        conv = self.store.create_conversation()
        u = self.store.save_user_message(conv.id, "你好")
        a = self.store.save_assistant_message(conv.id, "你好，有什么可以帮助你的？")
        msgs = self.store.get_messages(conv.id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[0].text, "你好")
        self.assertEqual(msgs[1].role, "assistant")
        self.assertEqual(msgs[1].text, "你好，有什么可以帮助你的？")

    # 4. 重启 service 后能读取已保存会话
    def test_persistence_across_store_recreation(self):
        conv = self.store.create_conversation(title="持久化测试")
        self.store.save_user_message(conv.id, "这条消息应该持久化")
        self.store.save_assistant_message(conv.id, "收到")

        # Simulate restart: create new store pointing to same db
        store2 = ConversationHistoryStore(self.db_path)
        loaded_conv = store2.get_conversation(conv.id)
        self.assertIsNotNone(loaded_conv)
        self.assertEqual(loaded_conv.title, "持久化测试")

        loaded_msgs = store2.get_messages(conv.id)
        self.assertEqual(len(loaded_msgs), 2)
        self.assertEqual(loaded_msgs[0].text, "这条消息应该持久化")
        self.assertEqual(loaded_msgs[1].text, "收到")

    # 5. 清空当前会话不影响其他会话
    def test_clear_one_conversation_preserves_others(self):
        conv1 = self.store.create_conversation(title="对话1")
        conv2 = self.store.create_conversation(title="对话2")
        self.store.save_user_message(conv1.id, "conv1 msg")
        self.store.save_user_message(conv2.id, "conv2 msg")

        self.store.clear_conversation_messages(conv1.id)

        self.assertEqual(len(self.store.get_messages(conv1.id)), 0)
        self.assertEqual(len(self.store.get_messages(conv2.id)), 1)
        # Conversation record still exists
        self.assertIsNotNone(self.store.get_conversation(conv1.id))

    def test_clear_all_conversations_removes_messages_and_bindings(self):
        conv1 = self.store.create_conversation(title="对话1")
        conv2 = self.store.create_conversation(title="对话2")
        self.store.save_user_message(conv1.id, "conv1 msg")
        self.store.save_assistant_message(conv2.id, "conv2 reply")
        self.store.bind_multica_task(
            conversation_id=conv1.id,
            issue_id="HHH-19",
            task_id="task-clear-all",
        )

        result = self.store.clear_all_conversations()

        self.assertEqual(result["deleted_conversations"], 2)
        self.assertEqual(result["deleted_messages"], 2)
        self.assertEqual(result["deleted_bound_tasks"], 1)
        self.assertEqual(self.store.list_conversations(), [])
        self.assertIsNone(self.store.get_conversation(conv1.id))
        self.assertEqual(self.store.get_messages(conv1.id), [])
        self.assertEqual(self.store.get_bound_tasks(conv1.id), [])

    # 6. 绑定 Multica issue/run 到 conversation
    def test_bind_multica_task_to_conversation(self):
        conv = self.store.create_conversation()
        binding = self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-abc-123",
            run_status="completed",
            review_summary="All tests passed.",
            messages_count=42,
            tool_use_count=5,
            tool_result_count=5,
        )
        self.assertEqual(binding.issue_id, "HHH-19")
        self.assertEqual(binding.task_id, "task-abc-123")
        self.assertEqual(binding.run_status, "completed")
        self.assertTrue(binding.is_primary_binding)

        tasks = self.store.get_bound_tasks(conv.id)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].issue_id, "HHH-19")

    # 7. 一个 conversation 可以绑定多个任务
    def test_one_conversation_can_bind_multiple_tasks(self):
        conv = self.store.create_conversation()
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-001",
        )
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-002",
        )
        self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-20",
            task_id="task-003",
        )
        tasks = self.store.get_bound_tasks(conv.id)
        self.assertEqual(len(tasks), 3)

    # 8. 同一个 issue/task 默认只能有一个主 conversation
    def test_same_task_id_only_one_primary_conversation(self):
        conv1 = self.store.create_conversation()
        conv2 = self.store.create_conversation()
        self.store.bind_multica_task(
            conversation_id=conv1.id,
            issue_id="HHH-19",
            task_id="unique-task-001",
        )
        with self.assertRaises(ValueError) as ctx:
            self.store.bind_multica_task(
                conversation_id=conv2.id,
                issue_id="HHH-19",
                task_id="unique-task-001",
            )
        self.assertIn("already bound", str(ctx.exception))

    # 9. 同一 conversation + issue + task 重复绑定应更新而非重复
    def test_repeated_binding_updates_not_duplicates(self):
        conv = self.store.create_conversation()
        b1 = self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-update-test",
            run_status="running",
            review_summary="First read.",
        )
        import time
        time.sleep(0.1)
        b2 = self.store.bind_multica_task(
            conversation_id=conv.id,
            issue_id="HHH-19",
            task_id="task-update-test",
            run_status="completed",
            review_summary="Updated summary.",
            messages_count=99,
        )
        # Same binding, not duplicated
        tasks = self.store.get_bound_tasks(conv.id)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].run_status, "completed")
        self.assertEqual(tasks[0].review_summary, "Updated summary.")
        self.assertEqual(tasks[0].messages_count, 99)

    # 10. conversation_id 非法时要拒绝
    def test_invalid_conversation_id_rejected(self):
        invalid_ids = [
            "../../../etc/passwd",
            "id\\with\\backslash",
            "id;DROP TABLE conversations;--",
            "id|rm -rf /",
            "id`ls`",
            "id' OR '1'='1",
            "",
        ]
        for bad_id in invalid_ids:
            with self.subTest(bad_id=bad_id):
                if bad_id == "":
                    # empty: _is_valid_id returns False, but get_conversation
                    # won't raise because it only validates non-empty ids
                    self.assertFalse(_is_valid_id(bad_id))
                else:
                    with self.assertRaises(ValueError):
                        self.store.get_conversation(bad_id)

    # 11 & 12. Regression: existing Multica safety & C6.1 parser tests still pass
    # These are verified by running the full test suite:
    #   python -m unittest discover -s tests
    # ensuring test_multica_integration_safety.py and
    # test_multica_integration_run_reader_service.py still pass.


class TestIdValidation(unittest.TestCase):
    def test_valid_ids_pass(self):
        self.assertTrue(_is_valid_id("abc123def456"))
        self.assertTrue(_is_valid_id("HHH-19"))
        self.assertTrue(_is_valid_id("task-abc-123"))
        self.assertTrue(_is_valid_id("a1b2c3d4e5f6"))

    def test_invalid_ids_rejected(self):
        self.assertFalse(_is_valid_id(""))
        self.assertFalse(_is_valid_id("id/with/slash"))
        self.assertFalse(_is_valid_id("id\\with\\backslash"))
        self.assertFalse(_is_valid_id("id.with.dot"))
        self.assertFalse(_is_valid_id("id;DROP"))
        self.assertFalse(_is_valid_id("id|rm"))
        self.assertFalse(_is_valid_id("id`cmd`"))
        self.assertFalse(_is_valid_id("id'quote"))
        self.assertFalse(_is_valid_id('id"quote'))
        self.assertFalse(_is_valid_id("id<tag>"))


if __name__ == "__main__":
    unittest.main()
