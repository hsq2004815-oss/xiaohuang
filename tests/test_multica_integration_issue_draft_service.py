from __future__ import annotations

import unittest

from xiaohuang.multica_integration.issue_draft_service import (
    build_issue_draft_from_handoff,
)


class MulticaIssueDraftServiceTests(unittest.TestCase):
    def test_builds_issue_draft_from_handoff(self):
        draft = _draft()

        self.assertTrue(draft.ok)
        self.assertTrue(draft.title)
        self.assertNotIn("\n", draft.title)
        self.assertLessEqual(len(draft.title), 83)
        self.assertIn("E:\\Projects\\sample-project", draft.description)
        self.assertIn("unrelated_to_xiaohuang", draft.description)
        self.assertIn("在目标项目中实现用户请求的功能", draft.description)
        self.assertIn("# Multica Issue Draft", draft.markdown)
        self.assertIn("## Safety Notes", draft.markdown)

    def test_assignee_candidates_and_preferred_codex(self):
        draft = _draft(preferred_agent="codex")

        self.assertEqual(draft.suggested_assignees, ("claude", "codex", "opencode", "openclaw"))
        self.assertEqual(draft.default_assignee, "codex")

    def test_preferred_claude_and_unknown_fallback(self):
        self.assertEqual(_draft(preferred_agent="claude").default_assignee, "claude")
        self.assertEqual(_draft(preferred_agent="unknown").default_assignee, "claude")

    def test_missing_target_path_warns_but_keeps_draft(self):
        draft = _draft(target_project_path="")

        self.assertTrue(draft.ok)
        self.assertIn("目标项目路径为空", " ".join(draft.warnings))

    def test_target_path_is_normalized_in_issue_draft_outputs(self):
        draft = _draft(
            handoff_prompt='请在 "E:\\Projects\\target-app" 里实现某功能。',
            target_project_path='E:\\Projects\\target-app"',
        )
        combined = "\n".join([draft.description, draft.markdown, draft.create_command_preview])

        self.assertEqual(draft.target_project_path, "E:\\Projects\\target-app")
        self.assertIn("Path: E:\\Projects\\target-app", combined)
        self.assertNotIn('E:\\Projects\\target-app"', combined)

    def test_missing_prompt_returns_error(self):
        draft = build_issue_draft_from_handoff(
            handoff_title="",
            handoff_prompt="",
            target_project_path="E:\\Projects\\sample-project",
            target_project_kind="external_existing",
            project_relation="unrelated_to_xiaohuang",
        )

        self.assertFalse(draft.ok)
        self.assertEqual(draft.error_code, "missing_handoff_prompt")

    def test_secret_redaction_applies_to_all_outputs(self):
        draft = _draft(
            handoff_prompt=(
                "实现页面\n"
                "api_key=abc123 token=tok_secret_123 password=pw secret=s1\n"
                "Authorization: Bearer bearer-token\n"
                "OpenAI key sk-123456789abcdef"
            )
        )
        combined = "\n".join([
            draft.title,
            draft.description,
            draft.create_command_preview,
            draft.markdown,
        ])

        for secret in ("abc123", "tok_secret_123", "password=pw", "secret=s1", "bearer-token", "sk-123456789abcdef"):
            self.assertNotIn(secret, combined)
        self.assertIn("<redacted>", combined)
        self.assertIn("sk-<redacted>", combined)

    def test_create_command_preview_is_string_only(self):
        draft = _draft(handoff_prompt="Update target project according to handoff prompt\n" + ("详细要求。" * 500))

        self.assertIsInstance(draft.create_command_preview, str)
        self.assertIn("multica issue create", draft.create_command_preview)
        self.assertIn("--output json", draft.create_command_preview)
        self.assertNotIn("--assignee", draft.create_command_preview)
        self.assertIn("description too long", draft.create_command_preview)
        self.assertIn("仅草稿", " ".join(draft.warnings))

    def test_vague_task_adds_warning_and_markdown_note(self):
        draft = _draft(
            handoff_title="在目标项目中实现用户请求的功能",
            handoff_prompt="在目标项目中实现用户请求的功能",
        )

        self.assertTrue(draft.ok)
        self.assertIn("任务描述过于泛", " ".join(draft.warnings))
        self.assertIn("This draft may be too vague", draft.markdown)
        self.assertIn("concrete acceptance criteria", draft.description)


def _draft(**overrides):
    data = {
        "handoff_title": "Claude Code Agent Handoff：在目标项目中实现用户请求的功能",
        "handoff_prompt": "在目标项目中实现用户请求的功能\n## 验收标准\n相关功能通过验证。",
        "target_project_path": "E:\\Projects\\sample-project",
        "target_project_kind": "external_existing",
        "project_relation": "unrelated_to_xiaohuang",
        "database_brief_status": "used",
        "related_domains": ("ui_design", "agent_workflow"),
        "preferred_agent": "",
    }
    data.update(overrides)
    return build_issue_draft_from_handoff(**data)


if __name__ == "__main__":
    unittest.main()
