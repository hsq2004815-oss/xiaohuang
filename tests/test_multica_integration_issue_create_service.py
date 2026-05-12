from __future__ import annotations

import subprocess
import unittest

from xiaohuang.multica_integration.issue_create_service import create_issue_from_draft


class MulticaIssueCreateServiceTests(unittest.TestCase):
    def test_rejects_without_confirmation(self):
        result = create_issue_from_draft(
            title="C5E test",
            description="desc",
            confirmed=False,
            confirmation_text="",
            runner=_runner_should_not_run,
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.created)
        self.assertEqual(result.error_code, "confirmation_required")

    def test_rejects_wrong_confirmation_text(self):
        result = create_issue_from_draft(
            title="C5E test",
            description="desc",
            confirmed=True,
            confirmation_text="CREATE",
            runner=_runner_should_not_run,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "confirmation_required")

    def test_rejects_missing_title_and_description(self):
        title_result = create_issue_from_draft(
            title="",
            description="desc",
            confirmed=True,
            confirmation_text="CREATE_MULTICA_ISSUE",
            runner=_runner_should_not_run,
        )
        description_result = create_issue_from_draft(
            title="C5E test",
            description="",
            confirmed=True,
            confirmation_text="CREATE_MULTICA_ISSUE",
            runner=_runner_should_not_run,
        )

        self.assertEqual(title_result.error_code, "missing_title")
        self.assertEqual(description_result.error_code, "missing_description")

    def test_confirmed_create_uses_safe_argv_without_assignee(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"id":"iss_123","title":"C5E test","status":"todo"}',
                stderr="",
            )

        result = create_issue_from_draft(
            title="C5E test",
            description="This is a confirmed create.",
            confirmed=True,
            confirmation_text="CREATE_MULTICA_ISSUE",
            assignee="claude",
            runner=fake_run,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.created)
        self.assertEqual(result.issue_id, "iss_123")
        self.assertEqual(result.status, "todo")
        argv, kwargs = calls[0]
        self.assertEqual(argv[:3], ["multica", "issue", "create"])
        self.assertIn("--title", argv)
        self.assertIn("--description", argv)
        self.assertIn("--output", argv)
        self.assertNotIn("--assignee", argv)
        self.assertFalse(kwargs["shell"])
        self.assertGreater(kwargs["timeout"], 0)

    def test_non_json_stdout_returns_raw_summary_without_crashing(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout="created issue ISS-1", stderr="")

        result = create_issue_from_draft(
            title="C5E test",
            description="desc",
            confirmed=True,
            confirmation_text="CREATE_MULTICA_ISSUE",
            runner=fake_run,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.created)
        self.assertEqual(result.raw_summary, "created issue ISS-1")
        self.assertIn("非 JSON", " ".join(result.warnings))

    def test_nonzero_returncode_returns_structured_error(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 2, stdout="", stderr="bad request")

        result = create_issue_from_draft(
            title="C5E test",
            description="desc",
            confirmed=True,
            confirmation_text="CREATE_MULTICA_ISSUE",
            runner=fake_run,
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.created)
        self.assertEqual(result.error_code, "multica_nonzero_exit")
        self.assertIn("bad request", result.raw_summary)

    def test_secret_redaction_applies_before_create_and_in_raw_summary(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="created token=server-secret", stderr="")

        result = create_issue_from_draft(
            title="C5E api_key=abc123",
            description="desc token=user-secret",
            confirmed=True,
            confirmation_text="CREATE_MULTICA_ISSUE",
            runner=fake_run,
        )

        self.assertTrue(result.ok)
        joined_argv = " ".join(calls[0])
        self.assertNotIn("abc123", joined_argv)
        self.assertNotIn("user-secret", joined_argv)
        self.assertNotIn("server-secret", result.raw_summary)
        self.assertIn("<redacted>", joined_argv)
        self.assertIn("<redacted>", result.raw_summary)


def _runner_should_not_run(argv, **kwargs):
    raise AssertionError("runner should not be called")


if __name__ == "__main__":
    unittest.main()
