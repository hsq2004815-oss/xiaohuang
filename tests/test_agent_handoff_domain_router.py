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
        self.assertEqual(route_domains("整理一下需求"), ["agent_workflow"])

    def test_combined_user_request_and_actual_task_routes_ui_agent_project(self):
        domains = route_domains("给 Claude Code 生成提示词 继续优化小黄任务历史页面")
        self.assertIn("agent_workflow", domains)
        self.assertIn("xiaohuang_project", domains)
        self.assertIn("ui_design", domains)

    def test_product_site_routes_ui_not_xiaohuang(self):
        domains = route_domains(
            "给 Claude Code 生成一个提示词，让它根据我的数据库，在 E:\\Projects\\sample-project "
            "里做一个高级产品展示官网首页"
        )

        self.assertIn("agent_workflow", domains)
        self.assertIn("ui_design", domains)
        self.assertNotIn("xiaohuang_project", domains)
        self.assertNotIn("backend", domains)

    def test_frontend_without_path_routes_ui_not_xiaohuang(self):
        domains = route_domains("给 Codex 一个任务，让它做一个目标项目的前端界面")

        self.assertIn("agent_workflow", domains)
        self.assertIn("ui_design", domains)
        self.assertNotIn("xiaohuang_project", domains)

    def test_unrelated_to_xiaohuang_suppresses_xiaohuang_domain(self):
        domains = route_domains(
            "这个任务和小黄项目无关，不要修改 E:\\Projects\\xiaohuang，在 E:\\Projects\\sample-project 做页面"
        )

        self.assertIn("ui_design", domains)
        self.assertNotIn("xiaohuang_project", domains)

    def test_do_not_modify_xiaohuang_boundary_suppresses_xiaohuang_domain(self):
        domains = route_domains(
            "给 Claude Code 生成提示词 在 E:\\Projects\\target-app 做一次 C5E smoke test "
            "不修改小黄项目 unrelated_to_xiaohuang"
        )

        self.assertIn("agent_workflow", domains)
        self.assertNotIn("xiaohuang_project", domains)


if __name__ == "__main__":
    unittest.main()
