from __future__ import annotations

import subprocess
import unittest

from xiaohuang.multica_integration.issue_assign_service import assign_issue_to_agent


class MulticaIssueAssignServiceTests(unittest.TestCase):
    def test_rejects_without_confirmation(self):
        result = assign_issue_to_agent(
            issue_id="4e344c98",
            agent="claude",
            confirmed=False,
            confirmation_text="",
            runner=_runner_should_not_run,
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.assigned)
        self.assertEqual(result.error_code, "confirmation_required")

    def test_rejects_wrong_confirmation_text(self):
        result = assign_issue_to_agent(
            issue_id="4e344c98",
            agent="claude",
            confirmed=True,
            confirmation_text="ASSIGN HHH-18 TO claude",
            runner=_runner_should_not_run,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "confirmation_required")

    def test_rejects_missing_issue_id_and_agent(self):
        missing_issue = assign_issue_to_agent(
            issue_id="",
            agent="claude",
            confirmed=True,
            confirmation_text="ASSIGN  TO claude",
            runner=_runner_should_not_run,
        )
        missing_agent = assign_issue_to_agent(
            issue_id="4e344c98",
            agent="",
            confirmed=True,
            confirmation_text="ASSIGN 4e344c98 TO ",
            runner=_runner_should_not_run,
        )

        self.assertEqual(missing_issue.error_code, "missing_issue_id")
        self.assertEqual(missing_agent.error_code, "missing_agent")

    def test_rejects_unsupported_agent_and_dangerous_issue_id(self):
        bad_agent = assign_issue_to_agent(
            issue_id="4e344c98",
            agent="powershell",
            confirmed=True,
            confirmation_text="ASSIGN 4e344c98 TO powershell",
            runner=_runner_should_not_run,
        )
        bad_issue = assign_issue_to_agent(
            issue_id="4e344c98;whoami",
            agent="claude",
            confirmed=True,
            confirmation_text="ASSIGN 4e344c98;whoami TO claude",
            runner=_runner_should_not_run,
        )

        self.assertEqual(bad_agent.error_code, "unsupported_agent")
        self.assertEqual(bad_issue.error_code, "invalid_issue_id")

    def test_confirmed_assign_uses_safe_argv(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"id":"4e344c98","assignee":"claude","status":"todo"}',
                stderr="",
            )

        result = assign_issue_to_agent(
            issue_id="4e344c98",
            agent="claude",
            confirmed=True,
            confirmation_text="ASSIGN 4e344c98 TO claude",
            runner=fake_run,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.assigned)
        self.assertEqual(result.issue_id, "4e344c98")
        self.assertEqual(result.agent, "claude")
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["multica", "issue", "assign", "4e344c98", "--to", "claude", "--output", "json"])
        self.assertFalse(kwargs["shell"])
        self.assertGreater(kwargs["timeout"], 0)
        self.assertNotIn("runs", argv)
        self.assertNotIn("run-messages", argv)
        self.assertNotIn("rerun", argv)

    def test_confirmed_assign_accepts_identifier_issue_id(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"identifier":"HHH-19","assignee":"claude","status":"todo"}',
                stderr="",
            )

        result = assign_issue_to_agent(
            issue_id="HHH-19",
            agent="claude",
            confirmed=True,
            confirmation_text="ASSIGN HHH-19 TO claude",
            runner=fake_run,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.assigned)
        self.assertEqual(calls[0], ["multica", "issue", "assign", "HHH-19", "--to", "claude", "--output", "json"])

    def test_non_json_stdout_returns_raw_summary_without_crashing(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout="assigned HHH-18 to codex", stderr="")

        result = assign_issue_to_agent(
            issue_id="HHH-18",
            agent="codex",
            confirmed=True,
            confirmation_text="ASSIGN HHH-18 TO codex",
            runner=fake_run,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.assigned)
        self.assertEqual(result.raw_summary, "assigned HHH-18 to codex")
        self.assertIn("非 JSON", " ".join(result.warnings))

    def test_nonzero_returncode_returns_structured_error(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 2, stdout="", stderr="not found")

        result = assign_issue_to_agent(
            issue_id="4e344c98",
            agent="openclaw",
            confirmed=True,
            confirmation_text="ASSIGN 4e344c98 TO openclaw",
            runner=fake_run,
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.assigned)
        self.assertEqual(result.error_code, "multica_nonzero_exit")
        self.assertIn("not found", result.raw_summary)


def _runner_should_not_run(argv, **kwargs):
    raise AssertionError("runner should not be called")


if __name__ == "__main__":
    unittest.main()
