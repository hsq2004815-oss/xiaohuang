from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaohuang.agent_handoff.models import AgentHandoffRequest, DatabaseBriefResult
from xiaohuang.agent_handoff.service import create_agent_handoff


class AgentHandoffServiceTests(unittest.TestCase):
    def test_complete_success_generates_file(self):
        brief_calls = []

        def fetcher(query, domains):
            brief_calls.append((query, domains))
            return DatabaseBriefResult(True, "used", "任务历史上下文")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_agent_handoff(
                AgentHandoffRequest(
                    user_request="给 Claude Code 生成提示词，让它继续优化小黄任务历史页面",
                    target_agent="claude_code",
                ),
                project_root=root,
                brief_fetcher=fetcher,
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.target_agent, "claude_code")
            self.assertTrue(result.handoff_path)
            self.assertIn("xiaohuang_project", result.domains)
            self.assertTrue((root / result.handoff_path).is_file())
            self.assertTrue(result.database_used)
            self.assertIn("继续优化小黄任务历史页面", result.title)
            self.assertIn("继续优化小黄任务历史页面", brief_calls[0][0])
            self.assertIn("用户原始需求", brief_calls[0][0])
            self.assertIn("## 实际工程任务", result.handoff_preview)

    def test_database_unavailable_still_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(user_request="让 Codex 审查这个 commit", target_agent="codex"),
                project_root=Path(tmp),
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable", "", "timeout"),
            )

            self.assertTrue(result.ok)
            self.assertFalse(result.database_used)
            self.assertEqual(result.database_status, "unavailable")

    def test_request_actual_task_is_used_for_title_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(
                    user_request="帮我给 Codex 写一个任务，让它审查 d5a611f 这个提交有没有问题",
                    target_agent="codex",
                    actual_task="审查 d5a611f 这个提交有没有问题",
                ),
                project_root=Path(tmp),
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable"),
            )

            self.assertTrue(result.ok)
            self.assertIn("审查 d5a611f 这个提交有没有问题", result.title)
            self.assertIn("实际工程任务", result.handoff_preview)

    def test_empty_user_request_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(user_request=""),
                project_root=Path(tmp),
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.error_message, "empty_user_request")

    def test_unknown_agent_uses_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(user_request="帮我写一个交接提示词"),
                project_root=Path(tmp),
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.target_agent, "generic")

    def test_file_write_failure_returns_failed_result(self):
        def fail_writer(root, target_agent, user_request, prompt):
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(user_request="让 opencode 改这个项目", target_agent="opencode"),
                project_root=Path(tmp),
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable"),
                file_writer=fail_writer,
            )

            self.assertFalse(result.ok)
            self.assertIn("disk full", result.error_message)


if __name__ == "__main__":
    unittest.main()
