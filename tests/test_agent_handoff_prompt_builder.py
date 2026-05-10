from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaohuang.agent_handoff.models import AgentHandoffRequest, DatabaseBriefResult
from xiaohuang.agent_handoff.prompt_builder import (
    build_agent_handoff_prompt,
    build_handoff_title,
)


class AgentHandoffPromptBuilderTests(unittest.TestCase):
    def test_prompt_contains_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_agent_handoff_prompt(
                AgentHandoffRequest(
                    user_request="给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面",
                    target_agent="claude_code",
                    actual_task="继续优化小黄任务历史页面",
                ),
                project_root=Path(tmp),
                domains=["xiaohuang_project", "ui_design", "agent_workflow"],
                database_brief=DatabaseBriefResult(
                    database_used=True,
                    database_status="used",
                    brief="任务历史页面已有列表和详情。",
                ),
            )

        for text in (
            "目标 Agent",
            "Claude Code",
            "小黄项目路径",
            "目标项目路径",
            "目标项目类型：xiaohuang",
            "与小黄项目关系：xiaohuang_project",
            "用户原始需求",
            "给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面",
            "实际工程任务",
            "继续优化小黄任务历史页面",
            "## 实际工程任务",
            "## 建议阅读文件",
            "frontend/control_panel/assets/app.js",
            "frontend/control_panel/assets/style.css",
            "src/xiaohuang/task_result_history_service.py",
            "## 数据库规则转译",
            "数据库 Brief 摘要",
            "任务历史页面已有列表和详情",
            "## 具体执行要求",
            "## 验收标准",
            "允许修改范围",
            "禁止事项",
            "验证命令",
            "完成报告格式",
        ):
            self.assertIn(text, prompt)

    def test_external_project_prompt_uses_target_project_path(self):
        prompt = build_agent_handoff_prompt(
            AgentHandoffRequest(
                user_request=(
                    "给 Claude Code 生成一个提示词，让它根据我的数据库，在 E:\\Projects\\wine-ui 里"
                    "做一个高级红酒品牌官网首页。这个任务和小黄项目无关，不要修改 E:\\Projects\\xiaohuang。"
                    "要求 React + Tailwind。"
                ),
                target_agent="claude_code",
                actual_task="做一个高级红酒品牌官网首页。要求 React + Tailwind",
                target_project_path="E:\\Projects\\wine-ui",
                target_project_kind="external_new",
                project_relation="unrelated_to_xiaohuang",
            ),
            project_root="E:\\Projects\\xiaohuang",
            domains=["ui_design", "agent_workflow"],
            database_brief=DatabaseBriefResult(
                database_used=True,
                database_status="used",
                brief="UI rules",
            ),
        )

        for text in (
            "小黄项目路径：E:\\Projects\\xiaohuang",
            "目标项目路径：E:\\Projects\\wine-ui",
            "目标项目类型：external_new",
            "与小黄项目关系：unrelated_to_xiaohuang",
            "不要修改 E:\\Projects\\xiaohuang",
            "package.json",
            "src/App.jsx 或 src/App.tsx",
            "vite.config.*",
            "做高端酒类品牌视觉",
            "Hero、精选酒款、品牌故事、年份/产区信息、品鉴 CTA",
            "ui_design, agent_workflow",
        ):
            self.assertIn(text, prompt)

        self.assertNotIn("src/xiaohuang/task_result_history_service.py", prompt)
        self.assertNotIn("frontend/control_panel/assets/app.js", prompt)

    def test_external_unspecified_prompt_requires_path_confirmation(self):
        prompt = build_agent_handoff_prompt(
            AgentHandoffRequest(
                user_request="给 Codex 一个任务，让它根据我的数据库做一个酒的前端界面",
                target_agent="codex",
                actual_task="做一个酒的前端界面",
                target_project_kind="external_unspecified",
                project_relation="auto",
            ),
            project_root="E:\\Projects\\xiaohuang",
            domains=["ui_design", "agent_workflow"],
            database_brief=DatabaseBriefResult(database_used=False, database_status="unavailable"),
        )

        self.assertIn("目标项目路径：未指定", prompt)
        self.assertIn("目标项目类型：external_unspecified", prompt)
        self.assertIn("目标路径未指定。不要执行修改；先向用户确认项目路径。", prompt)
        self.assertIn("不要修改 E:\\Projects\\xiaohuang", prompt)

    def test_title_prefers_actual_task(self):
        title = build_handoff_title(AgentHandoffRequest(
            user_request="给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面",
            target_agent="claude_code",
            actual_task="继续优化小黄任务历史页面",
        ))

        self.assertEqual(title, "Claude Code Agent Handoff：继续优化小黄任务历史页面")


if __name__ == "__main__":
    unittest.main()
