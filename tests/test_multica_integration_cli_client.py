from __future__ import annotations

import subprocess
import unittest

from xiaohuang.multica_integration.cli_client import MAX_STREAM_CHARS
from xiaohuang.multica_integration.cli_client import run_multica_command
from xiaohuang.multica_integration.cli_client import run_multica_argv
from xiaohuang.multica_integration.safety import CONFIRMED_ISSUE_ASSIGN_KEY
from xiaohuang.multica_integration.safety import CONFIRMED_ISSUE_CREATE_KEY


class MulticaIntegrationCliClientTests(unittest.TestCase):
    def test_runs_version_with_safe_subprocess_options(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="multica 0.2.16\n", stderr="")

        result = run_multica_command("version", timeout=3, runner=fake_run)

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "multica 0.2.16\n")
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["multica", "version"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 3)
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])

    def test_file_not_found_returns_structured_error(self):
        def fake_run(argv, **kwargs):
            raise FileNotFoundError("missing")

        result = run_multica_command("version", runner=fake_run)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "multica_not_found")
        self.assertIn("未找到", result.message)

    def test_timeout_returns_structured_error(self):
        def fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, timeout=1, output="api_key=abc", stderr="late")

        result = run_multica_command("daemon_status", timeout=1, runner=fake_run)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "multica_timeout")
        self.assertIn("<redacted>", result.stdout)

    def test_os_error_returns_structured_error(self):
        def fake_run(argv, **kwargs):
            raise OSError("boom")

        result = run_multica_command("agent_list_json", runner=fake_run)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "multica_command_failed")
        self.assertIn("boom", result.message)

    def test_nonzero_returncode_is_not_ok(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 2, stdout="", stderr="unknown flag: --output")

        result = run_multica_command("workspace_list_json", runner=fake_run)

        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.error_code, "multica_nonzero_exit")
        self.assertIn("unknown flag", result.message)

    def test_limits_and_redacts_stdout_stderr(self):
        long_secret = "token=secret-value " + ("x" * (MAX_STREAM_CHARS + 50))

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=long_secret, stderr="Authorization: Bearer abc")

        result = run_multica_command("version", runner=fake_run)

        self.assertTrue(result.ok)
        self.assertIn("token=<redacted>", result.stdout)
        self.assertIn("<truncated>", result.stdout)
        self.assertIn("authorization=<redacted>", result.stderr.lower())

    def test_unknown_command_key_is_rejected_before_runner(self):
        def fake_run(argv, **kwargs):
            raise AssertionError("runner should not be called")

        result = run_multica_command("issue_create", runner=fake_run)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "rejected_command")

    def test_runs_confirmed_issue_create_argv_with_safe_subprocess_options(self):
        calls = []
        argv = (
            "multica",
            "issue",
            "create",
            "--title",
            "C5E test",
            "--description",
            "desc",
            "--output",
            "json",
        )

        def fake_run(run_argv, **kwargs):
            calls.append((run_argv, kwargs))
            return subprocess.CompletedProcess(run_argv, 0, stdout='{"id":"iss_1"}', stderr="")

        result = run_multica_argv(CONFIRMED_ISSUE_CREATE_KEY, argv, timeout=5, runner=fake_run)

        self.assertTrue(result.ok)
        run_argv, kwargs = calls[0]
        self.assertEqual(run_argv, list(argv))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 5)
        self.assertTrue(kwargs["capture_output"])

    def test_rejects_unknown_confirmed_argv_before_runner(self):
        def fake_run(argv, **kwargs):
            raise AssertionError("runner should not be called")

        result = run_multica_argv(
            CONFIRMED_ISSUE_CREATE_KEY,
            ("multica", "issue", "assign", "iss_1", "--to", "claude"),
            runner=fake_run,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "rejected_command")

    def test_runs_confirmed_issue_assign_argv_with_safe_subprocess_options(self):
        calls = []
        argv = ("multica", "issue", "assign", "4e344c98", "--to", "claude", "--output", "json")

        def fake_run(run_argv, **kwargs):
            calls.append((run_argv, kwargs))
            return subprocess.CompletedProcess(run_argv, 0, stdout='{"id":"4e344c98"}', stderr="")

        result = run_multica_argv(CONFIRMED_ISSUE_ASSIGN_KEY, argv, timeout=6, runner=fake_run)

        self.assertTrue(result.ok)
        run_argv, kwargs = calls[0]
        self.assertEqual(run_argv, list(argv))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 6)
        self.assertTrue(kwargs["capture_output"])

    def test_rejects_dangerous_confirmed_assign_argv_before_runner(self):
        def fake_run(argv, **kwargs):
            raise AssertionError("runner should not be called")

        result = run_multica_argv(
            CONFIRMED_ISSUE_ASSIGN_KEY,
            ("multica", "issue", "runs", "4e344c98"),
            runner=fake_run,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "rejected_command")


if __name__ == "__main__":
    unittest.main()
