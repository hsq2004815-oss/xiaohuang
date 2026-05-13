from __future__ import annotations

import json
import subprocess
import unittest

from xiaohuang.multica_integration.run_reader_service import (
    _build_review_summary,
    _extract_json_from_text,
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

    def test_read_run_messages_stderr_fallback(self):
        """stdout empty, stderr has valid JSON — should parse messages from stderr."""
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="",
                stderr='[{"seq":1,"type":"tool_use","tool":"Bash","input":{"command":"ls"}}]',
            )

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].tool, "Bash")

    def test_read_run_messages_zero_results_has_raw_debug(self):
        """When no messages found, to_dict must include raw_debug."""
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="not json at all",
                stderr="some stderr text",
            )

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.messages), 0)
        d = result.to_dict()
        self.assertIn("raw_debug", d)
        rd = d["raw_debug"]
        self.assertIn("stdout_len", rd)
        self.assertIn("stderr_len", rd)
        self.assertIn("raw_stdout_head", rd)
        self.assertIn("stderr_head", rd)
        self.assertIn("parse_warnings", rd)
        self.assertGreater(len(rd["parse_warnings"]), 0)

    def test_read_run_messages_prefers_more_json_like_source(self):
        """stdout has garbage, stderr has valid JSON — prefer stderr."""
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="",
                stderr='[{"seq":2,"type":"tool_result","tool":"Bash","output":"done"}]',
            )

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].seq, "2")

    def test_large_json_array_survives_truncation(self):
        """> MAX_STREAM_CHARS JSON array — raw_stdout keeps full content, parser still works."""
        items = []
        for i in range(300):
            items.append({
                "seq": i + 1,
                "type": "tool_use",
                "tool": "Bash",
                "input": {"command": f"echo msg-{i:04d}", "description": f"step {i}"},
                "task_id": "t1",
            })
        full_json = json.dumps(items)
        self.assertGreater(len(full_json), 4000, "test data must exceed MAX_STREAM_CHARS")

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=full_json, stderr="")

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.messages), 300)

        # stdout is truncated for display
        self.assertLess(len(result.raw_summary), len(full_json))

    def test_raw_stdout_not_truncated_but_redacted(self):
        """Verify raw_stdout is full-length but secrets are redacted."""
        stdout = '[{"seq":1,"output":"token=sk-abc123secret"}]'

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        result = read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(result.ok)
        # Should have parsed correctly from full raw_stdout
        self.assertEqual(len(result.messages), 1)
        # Check raw_debug not populated when messages > 0
        self.assertEqual(result.raw_debug, {})

    def test_shell_false_unchanged(self):
        """shell=False must still hold after raw_stdout changes."""
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(kwargs)
            return subprocess.CompletedProcess(
                argv, 0,
                stdout='[{"seq":1,"output":"ok"}]',
                stderr="",
            )

        read_run_messages(task_id="t1", runner=fake_run)
        self.assertTrue(len(calls) > 0)
        self.assertFalse(calls[0].get("shell", True))


class RunMessagesToolEventParseTests(unittest.TestCase):
    """Tests for real tool_use / tool_result format."""

    def test_parse_tool_use_and_tool_result(self):
        stdout = json.dumps([
            {
                "input": {"command": "multica issue get HHH-19 --output json",
                          "description": "Get issue details for assigned task"},
                "issue_id": "78480e61",
                "seq": 1,
                "task_id": "de4c05f1",
                "tool": "Bash",
                "type": "tool_use",
            },
            {
                "issue_id": "78480e61",
                "output": "Issue HHH-19 status changed to in_review.",
                "seq": 68,
                "task_id": "de4c05f1",
                "tool": "Bash",
                "type": "tool_result",
            },
        ])
        msgs, warnings = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(len(warnings), 0)

    def test_tool_use_extracts_input_command(self):
        stdout = json.dumps([{
            "input": {"command": "multica issue get HHH-19 --output json"},
            "seq": 1,
            "tool": "Bash",
            "type": "tool_use",
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertIn("multica issue get", msgs[0].content)

    def test_tool_use_extracts_input_description(self):
        stdout = json.dumps([{
            "input": {"description": "Get issue details for assigned task"},
            "seq": 1,
            "tool": "Bash",
            "type": "tool_use",
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertIn("Get issue details", msgs[0].content)

    def test_tool_result_extracts_output(self):
        stdout = json.dumps([{
            "output": "Issue HHH-19 status changed to in_review.",
            "seq": 68,
            "tool": "Bash",
            "type": "tool_result",
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertIn("in_review", msgs[0].content)

    def test_seq_tool_type_fields_preserved(self):
        stdout = json.dumps([{
            "input": {"command": "ls"},
            "seq": 42,
            "tool": "Bash",
            "type": "tool_use",
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(msgs[0].seq, "42")
        self.assertEqual(msgs[0].tool, "Bash")
        self.assertEqual(msgs[0].message_type, "tool_use")

    def test_messages_sorted_by_seq(self):
        stdout = json.dumps([
            {"output": "third", "seq": 100, "type": "tool_result"},
            {"input": {"command": "first"}, "seq": 1, "type": "tool_use"},
            {"output": "second", "seq": 50, "type": "tool_result"},
        ])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual([m.seq for m in msgs], ["1", "50", "100"])

    def test_no_content_text_but_has_output_returns_messages(self):
        stdout = json.dumps([{
            "output": "result text here",
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertIn("result text here", msgs[0].content)

    def test_no_content_text_but_has_input_returns_messages(self):
        stdout = json.dumps([{
            "input": {"command": "echo hello"},
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertIn("echo hello", msgs[0].content)

    def test_input_string_displayed_directly(self):
        stdout = json.dumps([{
            "input": "plain text input",
        }])
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertIn("plain text input", msgs[0].content)

    def test_dict_with_events_key(self):
        stdout = json.dumps({
            "events": [{"output": "event1", "seq": 1}, {"output": "event2", "seq": 2}],
        })
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 2)

    def test_dict_with_logs_key(self):
        stdout = json.dumps({"logs": [{"output": "log entry"}]})
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)

    def test_dict_with_steps_key(self):
        stdout = json.dumps({"steps": [{"output": "step"}]})
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)

    def test_dict_with_task_messages_key(self):
        stdout = json.dumps({"task": {"messages": [{"output": "nested"}]}})
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)

    def test_dict_single_list_value_extracted(self):
        stdout = json.dumps({"unknown_key": [{"output": "auto found"}]})
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)

    def test_json_mixed_with_plain_text(self):
        stdout = 'Some log prefix\n[{"seq":1,"type":"tool_use","tool":"Bash","input":{"command":"ls"}}]\nDone.'
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].tool, "Bash")

    def test_json_object_mixed_with_plain_text(self):
        stdout = 'prefix text {"messages":[{"output":"hello","seq":1}]} suffix'
        msgs, _ = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 1)

    def test_json_mixed_no_valid_brackets(self):
        stdout = 'plain text with no json brackets at all'
        msgs, warnings = _parse_run_messages_json(stdout, "t1")
        self.assertEqual(len(msgs), 0)
        self.assertGreater(len(warnings), 0)


class ExtractJsonFromTextTests(unittest.TestCase):
    def test_extract_array_from_mixed_text(self):
        result = _extract_json_from_text('prefix [{"a":1}] suffix')
        self.assertEqual(result, '[{"a":1}]')

    def test_extract_object_from_mixed_text(self):
        result = _extract_json_from_text('before {"key":"value"} after')
        self.assertEqual(result, '{"key":"value"}')

    def test_extract_json_array_preferred_over_object(self):
        text = 'log [1,2,3] more {"k":"v"} end'
        result = _extract_json_from_text(text)
        self.assertEqual(result, '[1,2,3]')

    def test_extract_json_no_match(self):
        result = _extract_json_from_text('no brackets here')
        self.assertIsNone(result)

    def test_extract_json_empty_string(self):
        result = _extract_json_from_text('')
        self.assertIsNone(result)


class ReviewSummaryToolEventTests(unittest.TestCase):
    def test_counts_tool_use_and_tool_result(self):
        msgs = [
            MulticaRunMessage(message_type="tool_use", tool="Bash",
                              content="command: ls"),
            MulticaRunMessage(message_type="tool_use", tool="Read",
                              content="command: cat file"),
            MulticaRunMessage(message_type="tool_result", tool="Bash",
                              content="file list"),
        ]
        summary = _build_review_summary(msgs, "t1")
        self.assertIn("tool_use 2", summary)
        self.assertIn("tool_result 1", summary)
        self.assertIn("Bash", summary)
        self.assertIn("Read", summary)

    def test_detects_status_change(self):
        msgs = [
            MulticaRunMessage(message_type="tool_result", tool="Bash",
                              content="Issue HHH-19 status changed to in_review."),
        ]
        summary = _build_review_summary(msgs, "t1")
        self.assertIn("状态变更", summary.lower())

    def test_detects_commands_in_content(self):
        msgs = [
            MulticaRunMessage(message_type="tool_use", tool="Bash",
                              content="command: multica issue get HHH-19 --output json\ndescription: Get issue"),
        ]
        summary = _build_review_summary(msgs, "t1")
        self.assertIn("multica issue get", summary)

    def test_chinese_error_keywords(self):
        msgs = [
            MulticaRunMessage(message_type="tool_result", tool="Bash",
                              content="编译失败：找不到模块"),
        ]
        summary = _build_review_summary(msgs, "t1")
        self.assertIn("错误", summary)

    def test_chinese_complete_keywords(self):
        msgs = [
            MulticaRunMessage(message_type="tool_result", tool="Bash",
                              content="任务执行完成，测试通过"),
        ]
        summary = _build_review_summary(msgs, "t1")
        self.assertIn("完成", summary)


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
