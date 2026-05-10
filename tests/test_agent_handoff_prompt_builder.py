from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaohuang.agent_handoff.models import AgentHandoffRequest, DatabaseBriefResult
from xiaohuang.agent_handoff.prompt_builder import build_agent_handoff_prompt


class AgentHandoffPromptBuilderTests(unittest.TestCase):
    def test_prompt_contains_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_agent_handoff_prompt(
                AgentHandoffRequest(
                    user_request="继续优化小黄任务历史页面",
                    target_agent="codex",
                ),
                project_root=Path(tmp),
                domains=["xiaohuang_project", "ui_design"],
                database_brief=DatabaseBriefResult(
                    database_used=True,
                    database_status="used",
                    brief="任务历史页面已有列表和详情。",
                ),
            )

        for text in (
            "目标 Agent",
            "Codex",
            "项目路径",
            "继续优化小黄任务历史页面",
            "数据库 Brief 摘要",
            "任务历史页面已有列表和详情",
            "允许修改范围",
            "禁止事项",
            "验证命令",
            "完成报告格式",
        ):
            self.assertIn(text, prompt)


if __name__ == "__main__":
    unittest.main()
