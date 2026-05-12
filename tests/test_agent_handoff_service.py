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
            self.assertIn("目标项目类型：xiaohuang", brief_calls[0][0])
            self.assertIn("用户原始需求", brief_calls[0][0])
            self.assertIn("## 实际工程任务", result.handoff_preview)
            self.assertEqual(result.target_project_kind, "xiaohuang")
            self.assertEqual(result.target_project_path, str(root))
            self.assertTrue(result.can_open_terminal)

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

    def test_external_project_handoff_stays_in_xiaohuang_runtime(self):
        brief_calls = []

        def fetcher(query, domains):
            brief_calls.append((query, domains))
            return DatabaseBriefResult(True, "used", "external ui brief")

        text = (
            "给 Claude Code 生成一个提示词，让它根据我的数据库，在 E:\\Projects\\sample-project 里"
            "做一个高级产品展示官网首页。这个任务和小黄项目无关，不要修改 E:\\Projects\\xiaohuang。"
            "要求 React + Tailwind。"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = create_agent_handoff(
                AgentHandoffRequest(user_request=text, target_agent="claude_code"),
                project_root=root,
                brief_fetcher=fetcher,
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.handoff_path)
            self.assertTrue(result.handoff_path.startswith("runtime/agent_handoffs/"))
            handoff_file = root / result.handoff_path
            self.assertTrue(handoff_file.is_file())
            content = handoff_file.read_text(encoding="utf-8")

        self.assertIn("目标项目路径：E:\\Projects\\sample-project", content)
        self.assertIn("目标项目类型：external_new", content)
        self.assertIn("与小黄项目关系：unrelated_to_xiaohuang", content)
        self.assertIn("小黄只生成任务包，不创建外部项目", content)
        self.assertIn("只能在用户指定的目标路径内操作", content)
        self.assertIn("如果 package.json 不存在或没有这些 scripts，不要强行新增依赖或脚本", content)
        self.assertIn("不要修改", content)
        self.assertIn("E:\\Projects\\xiaohuang", content)
        self.assertNotIn("src/xiaohuang/task_result_history_service.py", content)
        self.assertNotIn("frontend/control_panel/assets/app.js", content)
        self.assertIn("高级产品展示官网首页", result.title)
        self.assertNotIn("xiaohuang_project", result.domains)
        self.assertIn("ui_design", result.domains)
        self.assertIn("agent_workflow", result.domains)
        self.assertIn("目标项目类型：external_new", brief_calls[0][0])
        self.assertIn("目标项目路径：E:\\Projects\\sample-project", brief_calls[0][0])
        self.assertNotIn("xiaohuang_project", brief_calls[0][1])
        self.assertEqual(result.target_project_path, "E:\\Projects\\sample-project")
        self.assertEqual(result.target_project_kind, "external_new")
        self.assertEqual(result.project_relation, "unrelated_to_xiaohuang")
        self.assertFalse(result.can_open_terminal)
        self.assertIn("不能回退到小黄项目", result.terminal_hint)

    def test_existing_external_project_can_open_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "xiaohuang"
            external = Path(tmp) / "sample-project"
            root.mkdir()
            external.mkdir()
            result = create_agent_handoff(
                AgentHandoffRequest(
                    user_request="给 Claude Code 生成提示词，在外部项目里优化首页",
                    target_agent="claude_code",
                    target_project_path=str(external),
                    target_project_kind="external_existing",
                    project_relation="unrelated_to_xiaohuang",
                ),
                project_root=root,
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.target_project_path, str(external))
            self.assertEqual(result.target_project_kind, "external_existing")
            self.assertEqual(result.project_relation, "unrelated_to_xiaohuang")
            self.assertTrue(result.can_open_terminal)

    def test_external_path_with_xiaohuang_boundary_stays_external(self):
        text = (
            '给 Claude Code 生成一个提示词，让它在 "E:\\Projects\\target-app" 里做一次 C5E smoke test，'
            "只创建说明文档草稿，不修改小黄项目，不启动任何 Agent。"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(user_request=text, target_agent="claude_code"),
                project_root=Path(tmp),
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable"),
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.target_project_path, "E:\\Projects\\target-app")
        self.assertIn(result.target_project_kind, ("external_existing", "external_new"))
        self.assertNotEqual(result.target_project_kind, "xiaohuang")
        self.assertEqual(result.project_relation, "unrelated_to_xiaohuang")
        self.assertNotIn("xiaohuang_project", result.domains)
        self.assertIn("不能回退到小黄项目", result.terminal_hint)

    def test_unspecified_external_project_cannot_open_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = create_agent_handoff(
                AgentHandoffRequest(
                    user_request="给 Claude Code 生成一个提示词，让它接手一个外部项目",
                    target_agent="claude_code",
                    target_project_kind="external_existing",
                    project_relation="unrelated_to_xiaohuang",
                ),
                project_root=Path(tmp),
                brief_fetcher=lambda query, domains: DatabaseBriefResult(False, "unavailable"),
            )

            self.assertTrue(result.ok)
            self.assertFalse(result.can_open_terminal)
            self.assertIn("未指定", result.terminal_hint)


if __name__ == "__main__":
    unittest.main()
