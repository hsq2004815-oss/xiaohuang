from __future__ import annotations

import subprocess
import unittest

from xiaohuang.multica_integration.run_reader_service import (
    _build_review_summary,
    _parse_run_messages_json,
    _parse_runs_json,
    read_issue_runs,
    read_run_messages,
)
from xiaohuang.multica_integration.models import MulticaRunMessage


def _runner_should_not_run(_argv, **_kwargs):
    raise AssertionError("runner should not be called")


class MulticaRunReaderBasicTests(unittest.TestCase):
    def test_read_issue_runs_rejects_empty_issue_id(self):
        result = read_issue_runs(issue_id="", runner=_runner_should_not_run)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "missing_issue_id")

    def test_read_issue_runs_rejects_dangerous_issue_id(self):
        result = read_issue_runs(
            issue_id="4e344c98;whoami",
            runner=_runner_should_not_run,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "invalid_issue_id")

    def test_read_issue_runs_rejects_shell_chars(self):
        for bad in ("4e344c98 | cmd", "4e344c98;ls", "4e344c98\nwhoami"):
            with self.subTest(issue_id=bad):
                result = read_issue_runs(issue_id=bad, runner=_runner_should_not_run)
                self.assertFalse(result.ok)

    def test_read_run_messages_rejects_empty_task_id(self):
        result = read_run_messages(task_id="", runner=_runner_should_not_run)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "missing_task_id")

    def test_read_run_messages_rejects_dangerous_task_id(self):
        result = read_run_messages(
            task_id="task-1;whoami",
            runner=_runner_should_not_run,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "invalid_task_id")


class MulticaRunReaderJsonParseTests(unittest.TestCase):
    def test_parse_runs_json_returns_runs(self):
        stdout = '[{"id":"r1","status":"completed","agent":"claude"}]'
        runs, warnings = _parse_runs_json(stdout, "HHH-19")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, "r1")
        self.assertEqual(runs[0].status, "completed")

    def test_parse_runs_json_empty_returns_empty(self):
        runs, _ = _parse_runs_json("", "HHH-19")
        self.assertEqual(len(runs), 0)

    def test_parse_runs_json_non_json_returns_empty_with_warning(self):
        runs, warnings = _parse_runs_json("not json", "HHH-19")
        self.assertEqual(len(runs), 0)
        self.assertGreater(len(warnings), 0)

    def test_parse_runs_json_dict_with_data_key(self):
        stdout = '{"data":[{"id":"r1","status":"running"}]}'
        runs, _ = _parse_runs_json(stdout, "HHH-19")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "running")

    def test_parse_run_messages_json_returns_messages(self):
        stdout = '[{"id":"m1","role":"assistant","content":"hello"}]'
        msgs, warnings = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "assistant")

    def test_parse_run_messages_dict_with_messages_key(self):
        stdout = '{"messages":[{"id":"m1","role":"user","content":"test"}]}'
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)


class MulticaRunReaderIntegrationTests(unittest.TestCase):
    def test_read_issue_runs_success_json(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv, 0,
                stdout='[{"id":"r1","task_id":"t1","status":"completed","agent":"claude"}]',
                stderr="",
            )

        result = read_issue_runs(issue_id="HHH-19", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertEqual(result.issue_id, "HHH-19")
        self.assertEqual(len(result.runs), 1)
        self.assertEqual(result.runs[0].run_id, "r1")

        argv, kwargs = calls[0]
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("rerun", argv)
        self.assertNotIn("assign", argv)
        self.assertNotIn("create", argv)

    def test_read_issue_runs_nonzero_exit(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 1,
                stdout="",
                stderr="issue not found",
            )

        result = read_issue_runs(issue_id="HHH-19", runner=fake_run)
        self.assertFalse(result.ok)

    def test_read_run_messages_success_json(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv, 0,
                stdout='[{"id":"m1","role":"assistant","content":"Task completed"}]',
                stderr="",
            )

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertEqual(result.task_id, "t1")
        self.assertEqual(len(result.messages), 1)
        self.assertIn("review_summary", result.to_dict())

        argv, kwargs = calls[0]
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("rerun", argv)

    def test_read_run_messages_nonzero_exit(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not found")

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertFalse(result.ok)

    def test_read_issue_runs_accepts_identifier(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(
                argv, 0,
                stdout='[{"id":"r1","task_id":"t1","status":"completed","agent":"claude"}]',
                stderr="",
            )

        result = read_issue_runs(issue_id="HHH-19", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertIn("HHH-19", calls[0])


class ReviewSummaryTests(unittest.TestCase):
    def test_empty_messages(self):
        summary = _build_review_summary([], "t1")
        self.assertIn("不足", summary)

    def test_messages_with_error(self):
        msg = MulticaRunMessage(
            role="assistant", author="claude",
            content="Error: something went wrong\nTraceback...",
        )
        summary = _build_review_summary([msg], "t1")
        self.assertIn("错误", summary)

    def test_messages_with_complete(self):
        msg = MulticaRunMessage(
            role="assistant", author="claude",
            content="Build complete, all tests passed.",
        )
        summary = _build_review_summary([msg], "t1")
        self.assertIn("完成", summary)

    def test_messages_with_both_signals(self):
        msgs = [
            MulticaRunMessage(role="assistant", author="claude",
                              content="Error: build failed"),
            MulticaRunMessage(role="assistant", author="claude",
                              content="Task complete, tests passed"),
        ]
        summary = _build_review_summary(msgs, "t1")
        self.assertIn("手动查看", summary)
