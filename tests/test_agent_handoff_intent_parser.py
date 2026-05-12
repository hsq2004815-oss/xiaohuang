from __future__ import annotations

import unittest

from xiaohuang.agent_handoff.intent_parser import (
    detect_project_relation,
    detect_target_project_kind,
    extract_target_project_path,
    normalize_windows_paths_in_text,
    normalize_windows_target_path,
    parse_agent_handoff_intent,
)


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

    def test_extract_target_project_path_supports_windows_paths(self):
        self.assertEqual(
            extract_target_project_path("请在 E:\\Projects\\sample-project 里做官网"),
            "E:\\Projects\\sample-project",
        )
        self.assertEqual(
            extract_target_project_path("项目放在 E:/Projects/sample-project"),
            "E:/Projects/sample-project",
        )

    def test_extract_target_project_path_strips_quotes_and_trailing_punctuation(self):
        cases = (
            ('请在 "E:\\Projects\\target-app" 里实现某功能', "E:\\Projects\\target-app"),
            ("请在 “E:\\Projects\\target-app” 里实现某功能", "E:\\Projects\\target-app"),
            ("请在 'E:\\Projects\\target-app' 里实现某功能", "E:\\Projects\\target-app"),
            ('请在 E:\\Projects\\target-app" 里实现某功能', "E:\\Projects\\target-app"),
            ("请在 E:\\Projects\\target-app” 里实现某功能", "E:\\Projects\\target-app"),
            ("请在 E:\\Projects\\target-app。里实现某功能", "E:\\Projects\\target-app"),
            ("请在 E:\\Projects\\target-app. 里实现某功能", "E:\\Projects\\target-app"),
            ("请在 E:\\Projects\\target-app，后续文字", "E:\\Projects\\target-app"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_target_project_path(text), expected)

    def test_normalize_windows_target_path(self):
        for raw in ('"E:\\Projects\\target-app"', "“E:\\Projects\\target-app”", "E:\\Projects\\target-app。"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_windows_target_path(raw), "E:\\Projects\\target-app")

    def test_normalize_windows_paths_in_text(self):
        text = '请在 "E:\\Projects\\target-app" 里执行；另一个路径 E:\\Projects\\sample-project，后续文字'

        result = normalize_windows_paths_in_text(text)

        self.assertIn("E:\\Projects\\target-app 里执行", result)
        self.assertIn("E:\\Projects\\sample-project，后续文字", result)
        self.assertNotIn('E:\\Projects\\target-app"', result)

    def test_project_relation_detects_unrelated_to_xiaohuang(self):
        text = "这个任务和小黄项目无关，不要修改 E:\\Projects\\xiaohuang。"
        self.assertEqual(detect_project_relation(text), "unrelated_to_xiaohuang")

    def test_target_project_kind_variants(self):
        self.assertEqual(
            detect_target_project_kind(
                "给 Codex 一个任务，让它做一个目标项目的前端界面",
                "做一个目标项目的前端界面",
                None,
            ),
            "external_unspecified",
        )
        self.assertEqual(
            detect_target_project_kind(
                "在 E:\\Projects\\sample-project 里优化已有项目",
                "优化已有项目",
                "E:\\Projects\\sample-project",
            ),
            "external_existing",
        )
        self.assertEqual(
            detect_target_project_kind(
                "小黄任务历史页面",
                "继续优化小黄任务历史页面",
                None,
            ),
            "xiaohuang",
        )

    def test_external_project_request_extracts_generic_project_fields(self):
        text = (
            "给 Claude Code 生成一个提示词，让它根据我的数据库，在 E:\\Projects\\sample-project 里"
            "做一个高级产品展示官网首页。这个任务和小黄项目无关，不要修改 E:\\Projects\\xiaohuang。"
            "要求 React + Tailwind，深色高级质感，玻璃拟态，包含 Hero、核心产品、项目故事和 CTA。"
        )
        result = parse_agent_handoff_intent(text)

        self.assertIsNotNone(result)
        self.assertEqual(result.target_agent, "claude_code")
        self.assertIn("高级产品展示官网首页", result.actual_task)
        self.assertIn("React + Tailwind", result.actual_task)
        self.assertNotIn("不要修改", result.actual_task)
        self.assertEqual(result.target_project_path, "E:\\Projects\\sample-project")
        self.assertEqual(result.target_project_kind, "external_new")
        self.assertEqual(result.project_relation, "unrelated_to_xiaohuang")

    def test_quoted_target_path_does_not_leak_into_actual_task(self):
        result = parse_agent_handoff_intent(
            '给 Claude Code 生成一个提示词，让它在 "E:\\Projects\\target-app" 里实现某功能。'
            "这个任务和小黄项目无关，不要修改 E:\\Projects\\xiaohuang。"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.target_project_path, "E:\\Projects\\target-app")
        self.assertNotIn('E:\\Projects\\target-app"', result.actual_task)
        self.assertIn("实现某功能", result.actual_task)

    def test_xiaohuang_project_request_sets_project_fields(self):
        result = parse_agent_handoff_intent("给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面")

        self.assertIsNotNone(result)
        self.assertEqual(result.target_project_path, None)
        self.assertEqual(result.target_project_kind, "xiaohuang")
        self.assertEqual(result.project_relation, "xiaohuang_project")

    def test_health_check_is_not_handoff(self):
        self.assertIsNone(parse_agent_handoff_intent("帮我做一次健康检查"))

    def test_readonly_tasks_are_not_handoff(self):
        for text in ("最近错误摘要", "配置检查"):
            with self.subTest(text=text):
                self.assertIsNone(parse_agent_handoff_intent(text))


if __name__ == "__main__":
    unittest.main()
