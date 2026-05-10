from __future__ import annotations

import unittest

from xiaohuang.agent_handoff.intent_parser import parse_agent_handoff_intent


class AgentHandoffIntentParserTests(unittest.TestCase):
    def test_claude_code_prompt_request(self):
        result = parse_agent_handoff_intent("给 Claude Code 生成提示词，让它继续优化任务历史页面")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "claude_code")

    def test_codex_review_request(self):
        result = parse_agent_handoff_intent("让 Codex 审查这个 commit")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "codex")

    def test_openclaw_request(self):
        result = parse_agent_handoff_intent("给 OpenClaw 一个任务")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "openclaw")

    def test_opencode_request(self):
        result = parse_agent_handoff_intent("让 opencode 改这个项目")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "opencode")

    def test_generic_handoff_request(self):
        result = parse_agent_handoff_intent("帮我写一个交接提示词")
        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "generic")

    def test_health_check_is_not_handoff(self):
        self.assertIsNone(parse_agent_handoff_intent("帮我做一次健康检查"))


if __name__ == "__main__":
    unittest.main()
