from __future__ import annotations

import unittest

from xiaohuang.agent_handoff.domain_router import route_domains


class AgentHandoffDomainRouterTests(unittest.TestCase):
    def test_xiaohuang_project(self):
        self.assertIn("xiaohuang_project", route_domains("小黄任务历史页面"))

    def test_ui_design(self):
        self.assertIn("ui_design", route_domains("高级 UI 页面"))

    def test_backend(self):
        self.assertIn("backend", route_domains("后端 API registry"))

    def test_agent_workflow(self):
        self.assertIn("agent_workflow", route_domains("Claude Code 提示词"))

    def test_database(self):
        self.assertIn("database", route_domains("数据库 brief"))

    def test_browser_automation(self):
        self.assertIn("browser_automation", route_domains("浏览器自动化"))

    def test_voice_assistant(self):
        self.assertIn("voice_assistant", route_domains("语音 ASR"))

    def test_default_domains(self):
        self.assertEqual(route_domains("整理一下需求"), ["agent_workflow", "xiaohuang_project"])


if __name__ == "__main__":
    unittest.main()
