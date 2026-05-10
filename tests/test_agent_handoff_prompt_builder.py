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
            "项目路径",
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
            "不要保存完整 prompt 到 task history",
            "## 验收标准",
            "明确区分“用户原始需求”和“实际工程任务”",
            "允许修改范围",
            "禁止事项",
            "验证命令",
            "完成报告格式",
        ):
            self.assertIn(text, prompt)

    def test_title_prefers_actual_task(self):
        title = build_handoff_title(AgentHandoffRequest(
            user_request="给 Claude Code 生成一个提示词，让它继续优化小黄任务历史页面",
            target_agent="claude_code",
            actual_task="继续优化小黄任务历史页面",
        ))

        self.assertEqual(title, "Claude Code Agent Handoff：继续优化小黄任务历史页面")


if __name__ == "__main__":
    unittest.main()
