from __future__ import annotations

import unittest

from xiaohuang.agent_handoff.intent_parser import parse_agent_handoff_intent


class AgentHandoffIntentParserTests(unittest.TestCase):
    def test_claude_code_prompt_request(self):
        result = parse_agent_handoff_intent("给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "claude_code")
        self.assertEqual(result.actual_task, "继续优化小黄任务历史页面")

    def test_codex_review_request(self):
        result = parse_agent_handoff_intent("帮我给 Codex 写一个任务，让它审查 d5a611f 这个提交有没有问题")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "codex")
        self.assertEqual(result.actual_task, "审查 d5a611f 这个提交有没有问题")

    def test_openclaw_request(self):
        result = parse_agent_handoff_intent("给 OpenClaw 一个任务")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "openclaw")

    def test_opencode_request(self):
        result = parse_agent_handoff_intent("给 opencode 一个任务，让它修复数据库 brief 调用问题")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "opencode")
        self.assertEqual(result.actual_task, "修复数据库 brief 调用问题")

    def test_openclaw_voice_optimization_extracts_actual_task(self):
        result = parse_agent_handoff_intent("让 OpenClaw 看看小黄语音交互还能怎么优化")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "openclaw")
        self.assertIn("小黄语音交互", result.actual_task)

    def test_generic_handoff_request(self):
        result = parse_agent_handoff_intent("帮我写一个交接提示词")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "generic")

    def test_health_check_is_not_handoff(self):
        self.assertIsNone(parse_agent_handoff_intent("帮我做一次健康检查"))

    def test_readonly_tasks_are_not_handoff(self):
        for text in ("最近错误摘要", "配置检查"):
            with self.subTest(text=text):
                self.assertIsNone(parse_agent_handoff_intent(text))


if __name__ == "__main__":
    unittest.main()
