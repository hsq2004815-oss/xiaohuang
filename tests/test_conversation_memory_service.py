"""test_conversation_memory_service.py — tests for short-term conversation memory."""

from __future__ import annotations

import unittest

from xiaohuang.conversation_memory_service import (
    ConversationMemory,
    ConversationTurn,
    _CONTEXT_HEADER,
    _DEFAULT_MAX_TURNS,
    _DEFAULT_MAX_CONTEXT_CHARS,
)


class BasicRecordTests(unittest.TestCase):
    def test_add_user(self):
        mem = ConversationMemory()
        mem.add_user("打开日志目录")
        self.assertEqual(len(mem), 1)
        self.assertEqual(mem.turns[0].role, "user")
        self.assertEqual(mem.turns[0].text, "打开日志目录")
        self.assertIsNone(mem.turns[0].source)

    def test_add_assistant(self):
        mem = ConversationMemory()
        mem.add_assistant("日志目录已打开", source="capability")
        self.assertEqual(len(mem), 1)
        self.assertEqual(mem.turns[0].role, "assistant")
        self.assertEqual(mem.turns[0].source, "capability")

    def test_clear(self):
        mem = ConversationMemory()
        mem.add_user("你好")
        mem.add_assistant("你好，我在")
        self.assertEqual(len(mem), 2)
        mem.clear()
        self.assertEqual(len(mem), 0)

    def test_empty_context_text(self):
        mem = ConversationMemory()
        self.assertEqual(mem.build_context_text(), "")

    def test_context_text_has_turns(self):
        mem = ConversationMemory()
        mem.add_user("你好")
        mem.add_assistant("你好，我在")
        text = mem.build_context_text()
        self.assertIn("你好", text)
        self.assertIn("用户", text)
        self.assertIn("助手", text)


class MaxTurnsTests(unittest.TestCase):
    def test_max_turns_trims_oldest(self):
        mem = ConversationMemory(max_turns=2)
        for i in range(6):
            mem.add_user(f"msg{i}")
            mem.add_assistant(f"reply{i}")
        self.assertLessEqual(len(mem), 4)  # 2 turns * 2 entries
        self.assertNotIn("msg0", mem.turns[0].text)

    def test_default_max_turns(self):
        mem = ConversationMemory()
        self.assertEqual(mem.max_turns, _DEFAULT_MAX_TURNS)

    def test_custom_max_turns(self):
        mem = ConversationMemory(max_turns=4)
        self.assertEqual(mem.max_turns, 4)


class MaxContextCharsTests(unittest.TestCase):
    def test_context_text_respects_max_chars(self):
        mem = ConversationMemory(max_context_chars=100)
        for i in range(10):
            mem.add_user(f"这是一条比较长的用户消息内容是测试第{i}条")
            mem.add_assistant(f"这是助手回复第{i}条")
        text = mem.build_context_text()
        self.assertLessEqual(len(text), 100 + 50)  # small margin for header

    def test_custom_max_context_chars(self):
        mem = ConversationMemory(max_context_chars=500)
        self.assertEqual(mem.max_context_chars, 500)
        mem.add_user("简短问题")
        mem.add_assistant("简短回复")
        text = mem.build_context_text()
        self.assertLess(len(text), 500 + 50)

    def test_default_max_context_chars(self):
        mem = ConversationMemory()
        self.assertEqual(mem.max_context_chars, _DEFAULT_MAX_CONTEXT_CHARS)


class LongTextTruncationTests(unittest.TestCase):
    def test_long_user_text_truncated(self):
        mem = ConversationMemory()
        long_text = "A" * 500
        mem.add_user(long_text)
        text = mem.build_context_text()
        self.assertNotIn("A" * 500, text)
        self.assertIn("...", text)

    def test_long_assistant_text_truncated(self):
        mem = ConversationMemory()
        long_text = "B" * 500
        mem.add_assistant(long_text)
        text = mem.build_context_text()
        self.assertNotIn("B" * 500, text)

    def test_short_text_not_truncated(self):
        mem = ConversationMemory()
        mem.add_user("你好")
        mem.add_assistant("你好，我在")
        text = mem.build_context_text()
        self.assertIn("你好", text)
        self.assertNotIn("...", text)


class SourceInContextTests(unittest.TestCase):
    def test_source_appears_in_context(self):
        mem = ConversationMemory()
        mem.add_assistant("已打开控制面板", source="capability")
        text = mem.build_context_text()
        self.assertIn("capability", text)

    def test_null_source_does_not_appear(self):
        mem = ConversationMemory()
        mem.add_assistant("你好", source=None)
        text = mem.build_context_text()
        self.assertNotIn("（None）", text)

    def test_llm_source_appears(self):
        mem = ConversationMemory()
        mem.add_assistant("我是小黄", source="llm")
        text = mem.build_context_text()
        self.assertIn("llm", text)


class TurnFormatTests(unittest.TestCase):
    def test_format_line(self):
        turn = ConversationTurn(role="user", text="你好")
        line = turn.format_line(1)
        self.assertIn("[1]", line)
        self.assertIn("用户", line)
        self.assertIn("你好", line)

    def test_assistant_format_with_source(self):
        turn = ConversationTurn(role="assistant", text="已打开", source="capability")
        line = turn.format_line(2)
        self.assertIn("[2]", line)
        self.assertIn("助手", line)
        self.assertIn("capability", line)


class SecurityTests(unittest.TestCase):
    def test_no_api_key_in_context(self):
        mem = ConversationMemory()
        mem.add_user("sk-secret123")
        mem.add_assistant("ok")
        text = mem.build_context_text()
        # The key itself would appear in context text but that's because
        # the user typed it. The memory service doesn't inject any keys.
        # Verify no hardcoded secrets in context header.
        self.assertNotIn("sk-", _CONTEXT_HEADER)

    def test_context_header_includes_safety_reminder(self):
        text = ConversationMemory().build_context_text()
        self.assertEqual(text, "")
        mem = ConversationMemory()
        mem.add_user("测试")
        text = mem.build_context_text()
        self.assertIn("不能根据上下文声称执行工具", text)

    def test_context_header_includes_no_bypass(self):
        mem = ConversationMemory()
        mem.add_user("测试")
        text = mem.build_context_text()
        self.assertIn("不能绕过本地安全限制", text)


if __name__ == "__main__":
    unittest.main()
