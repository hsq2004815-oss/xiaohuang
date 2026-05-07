from __future__ import annotations

import os
import unittest
from unittest.mock import patch


class V12GAShortenReplyTests(unittest.TestCase):
    """Tests for _shorten_reply — sentence-aware truncation."""

    def test_short_text_unchanged(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        result = _shorten_reply("你好", max_length=180)
        self.assertEqual(result, "你好")

    def test_text_within_limit_unchanged(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        text = "这是一个五十个字符左右的测试文本。" * 3  # about 57 chars
        result = _shorten_reply(text, max_length=180)
        self.assertEqual(result, text)

    def test_long_text_truncates_at_sentence_end(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        text = (
            "第一句话包含完整的句子信息在这里。"
            "第二句话是继续补充说明的内容。"
            "第三句话应该被完全截断因为超过限制。"
            "第四句话也不应该出现在结果中。"
        )
        result = _shorten_reply(text, max_length=50, max_sentences=3)
        # Last char should be a sentence end, not a half-cut word
        self.assertIn(result[-1], "。！？；")
        # Should contain first sentence completely
        self.assertIn("第一句话", result)

    def test_no_half_cut_words_like_bikong(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        text = "ECP协议是扩展控制协议，常用于工业自动化和设备通信，比如控。"
        result = _shorten_reply(text, max_length=50)
        # Should either keep full text or truncate at a natural boundary
        if len(result) < len(text):
            # Truncated — must not end mid-word
            self.assertNotIn("比如控", result[-5:])

    def test_no_sentence_end_falls_back_to_soft_break(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        text = "这是一个很长的测试句，没有句号结束，而是用逗号分隔，继续往下写很多内容直到超出限制"
        result = _shorten_reply(text, max_length=30, max_sentences=3)
        # Should end naturally, not mid-word
        self.assertFalse(result.endswith("很长的测"))

    def test_hard_truncate_when_no_boundary(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        text = "AAAAAAAAABBBBBBBBBBCCCCCCCCCCCDDDDDDDDDDDDD"
        result = _shorten_reply(text, max_length=10, max_sentences=3)
        self.assertTrue(result.endswith("。"))

    def test_respects_max_sentences(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        text = (
            "第一句包含许多额外的字符以确保超出限制。" * 3
            + "第二句也有很多很多很多很多很多很多字符。" * 3
            + "第三句还有更多更多更多更多更多更多字。" * 3
            + "第四句也填满了填满了填满了填满了字。" * 3
            + "第五句终于到了最后一段但还是不少字。" * 3
        )
        result = _shorten_reply(text, max_length=180, max_sentences=2)
        sent_count = sum(1 for ch in result if ch in "。！？；")
        self.assertEqual(sent_count, 2)

    def test_cleans_extra_whitespace(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        result = _shorten_reply("  hello   world  ", max_length=180)
        self.assertEqual(result, "hello world")

    def test_empty_string(self):
        from xiaohuang.llm_reply_service import _shorten_reply
        result = _shorten_reply("", max_length=180)
        self.assertEqual(result, "")


class V12GAMaxReplyCharsEnvTests(unittest.TestCase):
    """Tests for XIAOHUANG_MAX_REPLY_CHARS env var."""

    def test_env_var_controls_max_reply_chars(self):
        from xiaohuang.llm_reply_service import _get_default_max_reply_chars
        val = _get_default_max_reply_chars(env={"XIAOHUANG_MAX_REPLY_CHARS": "120"})
        self.assertEqual(val, 120)

    def test_env_var_invalid_falls_back_to_default(self):
        from xiaohuang.llm_reply_service import _get_default_max_reply_chars
        val = _get_default_max_reply_chars(env={"XIAOHUANG_MAX_REPLY_CHARS": "abc"})
        self.assertEqual(val, 180)

    def test_env_var_below_min_falls_back(self):
        from xiaohuang.llm_reply_service import _get_default_max_reply_chars
        val = _get_default_max_reply_chars(env={"XIAOHUANG_MAX_REPLY_CHARS": "5"})
        self.assertEqual(val, 180)

    def test_env_var_above_max_falls_back(self):
        from xiaohuang.llm_reply_service import _get_default_max_reply_chars
        val = _get_default_max_reply_chars(env={"XIAOHUANG_MAX_REPLY_CHARS": "9999"})
        self.assertEqual(val, 180)


class V12GAMaxTokensEnvTests(unittest.TestCase):
    """Tests for XIAOHUANG_LLM_MAX_TOKENS env var."""

    def test_env_var_controls_max_tokens(self):
        from xiaohuang.llm_reply_service import _get_default_llm_max_tokens
        val = _get_default_llm_max_tokens(env={"XIAOHUANG_LLM_MAX_TOKENS": "1024"})
        self.assertEqual(val, 1024)

    def test_env_var_invalid_falls_back_to_default(self):
        from xiaohuang.llm_reply_service import _get_default_llm_max_tokens
        val = _get_default_llm_max_tokens(env={"XIAOHUANG_LLM_MAX_TOKENS": "xyz"})
        self.assertEqual(val, 768)

    def test_env_var_below_min_falls_back(self):
        from xiaohuang.llm_reply_service import _get_default_llm_max_tokens
        val = _get_default_llm_max_tokens(env={"XIAOHUANG_LLM_MAX_TOKENS": "10"})
        self.assertEqual(val, 768)

    def test_env_var_above_max_falls_back(self):
        from xiaohuang.llm_reply_service import _get_default_llm_max_tokens
        val = _get_default_llm_max_tokens(env={"XIAOHUANG_LLM_MAX_TOKENS": "99999"})
        self.assertEqual(val, 768)


class V12GALoadConfigMaxTokensTests(unittest.TestCase):
    """Tests for load_deepseek_config and load_llm_provider_config max_tokens."""

    def test_load_deepseek_config_default_max_tokens_is_768(self):
        from xiaohuang.llm_reply_service import load_deepseek_config
        cfg = load_deepseek_config(env={}, timeout_seconds=10)
        self.assertEqual(cfg.max_tokens, 768)

    def test_load_deepseek_config_env_overrides_default(self):
        from xiaohuang.llm_reply_service import load_deepseek_config
        cfg = load_deepseek_config(
            env={"DEEPSEEK_API_KEY": "sk-test", "XIAOHUANG_LLM_MAX_TOKENS": "1024"},
            timeout_seconds=10,
        )
        self.assertEqual(cfg.max_tokens, 1024)

    def test_load_deepseek_config_override_wins_over_env(self):
        from xiaohuang.llm_reply_service import load_deepseek_config
        cfg = load_deepseek_config(
            env={"DEEPSEEK_API_KEY": "sk-test", "XIAOHUANG_LLM_MAX_TOKENS": "1024"},
            timeout_seconds=10,
            max_tokens_override=512,
        )
        self.assertEqual(cfg.max_tokens, 512)


class V12GAPersonaTests(unittest.TestCase):
    """Tests for default persona in build_openai_compatible_chat_request."""

    def test_default_persona_includes_voice_assistant_hint(self):
        from xiaohuang.llm_reply_service import build_openai_compatible_chat_request
        payload = build_openai_compatible_chat_request("你好", model="test", max_tokens=100)
        system = payload["messages"][0]["content"]
        self.assertIn("语音助手", system)
        self.assertIn("2-3 句", system)

    def test_custom_persona_not_overridden(self):
        from xiaohuang.llm_reply_service import build_openai_compatible_chat_request
        payload = build_openai_compatible_chat_request(
            "你好", model="test", max_tokens=100, persona="我是自定义助手。",
        )
        system = payload["messages"][0]["content"]
        self.assertEqual(system, "我是自定义助手。")


class V12GAExistingBehaviorTests(unittest.TestCase):
    """Verify existing behavior is preserved."""

    def test_execution_claim_returns_tool_unavailable(self):
        from xiaohuang.llm_reply_service import TOOL_UNAVAILABLE_REPLY, generate_llm_reply
        result = generate_llm_reply("帮我打开浏览器", config=None)
        self.assertEqual(result, TOOL_UNAVAILABLE_REPLY)

    def test_tool_unavailable_text_unchanged(self):
        from xiaohuang.llm_reply_service import TOOL_UNAVAILABLE_REPLY
        self.assertIn("还不能执行工具", TOOL_UNAVAILABLE_REPLY)

    def test_fallback_no_key_preserved(self):
        from xiaohuang.llm_reply_service import generate_llm_reply_result

        _ENV_KEYS = (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_MODEL",
            "DEEPSEEK_MAX_TOKENS",
        )
        saved = {k: os.environ.pop(k, None) for k in _ENV_KEYS}
        try:
            result = generate_llm_reply_result("你好", config=None)
            self.assertEqual(result.source, "rule_fallback_no_key")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_no_tkinter_import(self):
        from xiaohuang import llm_reply_service
        self.assertNotIn("tkinter", llm_reply_service.__dict__)
