from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xiaohuang.task_result_history_service import (
    _redact_sensitive_text,
    _should_save_result,
    _tags_for_task_type,
    _truncate_text,
    append_task_result,
    get_recent_task_results,
    get_task_history_path,
    init_task_history,
    sanitize_task_result_for_history,
    _reset_for_test,
)
from xiaohuang.text_task_execution_models import TextTaskExecutionResult


def _result(**kwargs) -> TextTaskExecutionResult:
    defaults = {
        "ok": True,
        "task_id": "text-task-test123",
        "task_type": "readonly_health_report",
        "status": "completed",
        "title": "小黄健康检查",
        "summary": "总体状态：正常。",
        "details": "一、基础状态 — 6/6 正常\n二、配置状态\n  - LLM: 已启用",
        "risk_level": "low",
        "read_files": (),
        "error": "",
    }
    defaults.update(kwargs)
    return TextTaskExecutionResult(**defaults)


class TaskResultHistoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_test()
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        _reset_for_test()
        self.tmp.cleanup()

    # ── path ──

    def test_get_task_history_path_under_data_task_history(self):
        path = get_task_history_path(self.project_root)
        self.assertIn("data", path.parts)
        self.assertIn("task_history", path.parts)
        self.assertEqual(path.name, "task_results.jsonl")

    # ── init / read ──

    def test_get_recent_returns_empty_when_no_file(self):
        results = get_recent_task_results(self.project_root, limit=10)
        self.assertEqual(results, [])

    def test_get_recent_skips_bad_json_lines(self):
        file_path = get_task_history_path(self.project_root)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            '{"ok": true, "task_type": "readonly_health_report"}\n'
            'not valid json\n'
            '{"ok": true, "task_type": "readonly_status_check"}\n',
            encoding="utf-8",
        )
        _reset_for_test()
        results = get_recent_task_results(self.project_root, limit=10)
        self.assertEqual(len(results), 2)

    # ── append ──

    def test_append_completed_result_writes_jsonl(self):
        entry = append_task_result(self.project_root, _result())
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["task_type"], "readonly_health_report")
        self.assertTrue(entry["ok"])
        self.assertIn("history_id", entry)
        self.assertTrue(entry["history_id"].startswith("taskhist_"))

        file_path = get_task_history_path(self.project_root)
        self.assertTrue(file_path.is_file())

        text = file_path.read_text(encoding="utf-8")
        self.assertIn("taskhist_", text)
        self.assertIn("readonly_health_report", text)

        parsed = json.loads(text.strip())
        self.assertEqual(parsed["history_id"], entry["history_id"])

    def test_append_failed_result_writes_jsonl(self):
        entry = append_task_result(
            self.project_root,
            _result(ok=False, status="failed", summary="执行失败"),
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "failed")
        self.assertFalse(entry["ok"])

    def test_append_non_readonly_task_returns_none(self):
        entry = append_task_result(
            self.project_root,
            _result(task_type="some_unknown_type"),
        )
        self.assertIsNone(entry)

    def test_append_agent_handoff_task_writes_safe_summary(self):
        entry = append_task_result(
            self.project_root,
            _result(
                task_type="agent_handoff_draft",
                title="生成 Agent 交接提示词",
                summary="已生成 Claude Code 提示词草稿。",
                details="文件：runtime/agent_handoffs/demo.txt\n预览：短预览",
            ),
            task={"original_text": "给 Claude Code 生成提示词"},
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["task_type"], "agent_handoff_draft")
        self.assertEqual(entry["result_kind"], "agent_handoff")
        self.assertIn("handoff", entry["tags"])
        self.assertIn("claude_code", entry["tags"])
        self.assertIn("runtime/agent_handoffs/demo.txt", entry["safe_details_excerpt"])

    def test_append_agent_completion_review_writes_safe_summary(self):
        raw_report = "完成：Secret Raw Report\n一、改了哪些文件\n- src/x.py"
        entry = append_task_result(
            self.project_root,
            _result(
                task_type="agent_completion_review",
                title="Agent 完成报告审查",
                summary="建议保留，但需要补充复查",
                details=(
                    "【Agent 完成报告审查】\n"
                    "验收结论：建议保留，但需要补充复查\n"
                    "verdict：needs_review\n"
                    "commit：abc1234\n"
                    "四、风险点\n- 未做真实窗口点击验收"
                ),
            ),
            task={"original_text": raw_report},
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["task_type"], "agent_completion_review")
        self.assertEqual(entry["result_kind"], "agent_review")
        self.assertIn("agent", entry["tags"])
        self.assertIn("review", entry["tags"])
        self.assertIn("needs_review", entry["tags"])
        self.assertIn("commit：abc1234", entry["safe_details_excerpt"])
        self.assertNotIn("Secret Raw Report", entry["safe_details_excerpt"])

    def test_append_blocked_status_returns_none(self):
        entry = append_task_result(
            self.project_root,
            _result(status="blocked"),
        )
        self.assertIsNone(entry)

    def test_append_cancelled_status_returns_none(self):
        entry = append_task_result(
            self.project_root,
            _result(status="cancelled"),
        )
        self.assertIsNone(entry)

    def test_append_pending_status_returns_none(self):
        entry = append_task_result(
            self.project_root,
            _result(status="pending"),
        )
        self.assertIsNone(entry)

    # ── get_recent ──

    def test_get_recent_returns_newest_first(self):
        for i in range(5):
            append_task_result(
                self.project_root,
                _result(
                    task_id=f"task-{i}",
                    task_type="readonly_status_check",
                ),
            )
        results = get_recent_task_results(self.project_root, limit=3)
        self.assertEqual(len(results), 3)
        task_ids = [r["task_id"] for r in results]
        self.assertEqual(task_ids, ["task-4", "task-3", "task-2"])

    def test_get_recent_respects_limit(self):
        for i in range(5):
            append_task_result(
                self.project_root,
                _result(
                    task_id=f"task-{i}",
                    task_type="readonly_status_check",
                ),
            )
        results = get_recent_task_results(self.project_root, limit=2)
        self.assertEqual(len(results), 2)

    # ── read_files_count ──

    def test_read_files_count_saved_not_paths(self):
        entry = append_task_result(
            self.project_root,
            _result(read_files=("logs/a.log", "logs/b.log")),
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["read_files_count"], 2)
        self.assertNotIn("read_files", entry)
        lines = get_task_history_path(self.project_root).read_text(encoding="utf-8")
        self.assertNotIn("logs/a.log", lines)
        self.assertNotIn("logs/b.log", lines)

    # ── schema fields ──

    def test_entry_contains_required_schema_fields(self):
        entry = append_task_result(self.project_root, _result())
        self.assertIsNotNone(entry)
        required = [
            "history_id", "task_id", "created_at", "completed_at",
            "task_type", "title", "status", "ok", "risk_level",
            "summary", "safe_details_excerpt", "source", "read_files_count",
            "result_kind", "tags", "schema_version",
        ]
        for field in required:
            with self.subTest(field=field):
                self.assertIn(field, entry)

        self.assertEqual(entry["source"], "chat")
        self.assertEqual(entry["result_kind"], "readonly_report")
        self.assertEqual(entry["schema_version"], 1)


class SanitizeTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_test()
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        _reset_for_test()
        self.tmp.cleanup()

    def test_redact_api_key_in_summary(self):
        result = _result(summary="api_key=sk-test-value token=abc123")
        entry = append_task_result(self.project_root, result)
        self.assertIsNotNone(entry)
        self.assertNotIn("sk-test-value", entry["summary"])
        self.assertNotIn("abc123", entry["summary"])
        self.assertIn("<redacted>", entry["summary"])

    def test_redact_password_and_secret_in_details(self):
        result = _result(
            summary="empty",
            details="password=123 secret=hello authorization=Bearer abc.def",
        )
        entry = append_task_result(self.project_root, result)
        self.assertIsNotNone(entry)
        self.assertNotIn("123", entry["safe_details_excerpt"])
        self.assertNotIn("hello", entry["safe_details_excerpt"])
        self.assertNotIn("abc.def", entry["safe_details_excerpt"])
        self.assertNotIn("Bearer abc.def", entry["safe_details_excerpt"])

    def test_redact_case_insensitive(self):
        result = _result(summary="API_KEY=SEC VAL Token=XYZ")
        entry = append_task_result(self.project_root, result)
        self.assertIsNotNone(entry)
        self.assertNotIn("SEC", entry["summary"])
        self.assertNotIn("XYZ", entry["summary"])
        self.assertIn("<redacted>", entry["summary"])

    def test_redact_authorization_bearer(self):
        result = _result(
            summary="detected",
            details="Authorization=Bearer token123 and Bearer xyz789",
        )
        entry = append_task_result(self.project_root, result)
        self.assertIsNotNone(entry)
        excerpt = entry["safe_details_excerpt"]
        self.assertNotIn("token123", excerpt)
        self.assertNotIn("xyz789", excerpt)

    def test_redact_function_unit(self):
        text = "api_key=sk-secret token=mytoken password=hidden secret=val"
        clean = _redact_sensitive_text(text)
        self.assertNotIn("sk-secret", clean)
        self.assertNotIn("mytoken", clean)
        self.assertNotIn("hidden", clean)
        self.assertNotIn("val", clean)
        self.assertIn("<redacted>", clean)


class TruncationTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_test()
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        _reset_for_test()
        self.tmp.cleanup()

    def test_truncate_helper(self):
        long_text = "a" * 50
        truncated = _truncate_text(long_text, 10)
        self.assertLessEqual(len(truncated), 11)
        self.assertTrue(truncated.endswith("…"))

    def test_truncate_short_text_unchanged(self):
        short = "hello"
        self.assertEqual(_truncate_text(short, 100), short)

    def test_long_summary_truncated(self):
        long_val = "x" * 400
        entry = append_task_result(self.project_root, _result(summary=long_val))
        self.assertIsNotNone(entry)
        self.assertLessEqual(len(entry["summary"]), 301)
        self.assertTrue(entry["summary"].endswith("…"))

    def test_long_details_excerpt_truncated(self):
        long_val = "y" * 600
        entry = append_task_result(self.project_root, _result(details=long_val))
        self.assertIsNotNone(entry)
        self.assertLessEqual(len(entry["safe_details_excerpt"]), 501)
        self.assertTrue(entry["safe_details_excerpt"].endswith("…"))

    def test_long_title_truncated(self):
        long_title = "t" * 120
        entry = append_task_result(self.project_root, _result(title=long_title))
        self.assertIsNotNone(entry)
        self.assertLessEqual(len(entry["title"]), 101)


class TagsTests(unittest.TestCase):
    def test_health_report_tags(self):
        tags = _tags_for_task_type("readonly_health_report")
        self.assertIn("readonly", tags)
        self.assertIn("health", tags)

    def test_log_analysis_tags(self):
        tags = _tags_for_task_type("readonly_log_analysis")
        self.assertIn("logs", tags)

    def test_recent_errors_tags(self):
        tags = _tags_for_task_type("readonly_recent_errors_review")
        self.assertIn("logs", tags)

    def test_config_summary_tags(self):
        tags = _tags_for_task_type("readonly_config_summary")
        self.assertIn("config", tags)

    def test_events_review_tags(self):
        tags = _tags_for_task_type("readonly_runtime_events_review")
        self.assertIn("events", tags)

    def test_status_check_tags(self):
        tags = _tags_for_task_type("readonly_status_check")
        self.assertIn("diagnostic", tags)

    def test_diagnostic_review_tags(self):
        tags = _tags_for_task_type("readonly_diagnostic_review")
        self.assertIn("diagnostic", tags)

    def test_all_tags_include_readonly(self):
        for task_type in [
            "readonly_health_report", "readonly_log_analysis",
            "readonly_status_check", "readonly_diagnostic_review",
            "readonly_recent_errors_review", "readonly_runtime_events_review",
            "readonly_config_summary",
        ]:
            with self.subTest(task_type=task_type):
                self.assertIn("readonly", _tags_for_task_type(task_type))


class ShouldSaveTests(unittest.TestCase):
    def test_completed_readonly_should_save(self):
        self.assertTrue(_should_save_result(_result(status="completed")))

    def test_failed_readonly_should_save(self):
        self.assertTrue(_should_save_result(_result(status="failed", ok=False)))

    def test_blocked_should_not_save(self):
        self.assertFalse(_should_save_result(_result(status="blocked")))

    def test_expired_should_not_save(self):
        self.assertFalse(_should_save_result(_result(status="expired")))

    def test_non_readonly_should_not_save(self):
        self.assertFalse(_should_save_result(
            _result(task_type="blocked_local_execution")
        ))

    def test_unknown_type_should_not_save(self):
        self.assertFalse(_should_save_result(
            _result(task_type="unknown_task_type")
        ))

    def test_agent_handoff_should_save(self):
        self.assertTrue(_should_save_result(
            _result(task_type="agent_handoff_draft")
        ))

    def test_agent_completion_review_should_save(self):
        self.assertTrue(_should_save_result(
            _result(task_type="agent_completion_review")
        ))


class FileIOEdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_test()
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        _reset_for_test()
        self.tmp.cleanup()

    def test_bad_json_line_skipped_on_read(self):
        file_path = get_task_history_path(self.project_root)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            '{broken json\n'
            '{"history_id": "taskhist_good", "task_id": "t1", "task_type": "readonly_status_check", "status": "completed", "ok": true}\n',
            encoding="utf-8",
        )
        _reset_for_test()
        results = get_recent_task_results(self.project_root, limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["history_id"], "taskhist_good")

    def test_empty_file_returns_empty_list(self):
        file_path = get_task_history_path(self.project_root)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("", encoding="utf-8")
        _reset_for_test()
        results = get_recent_task_results(self.project_root, limit=10)
        self.assertEqual(results, [])

    def test_file_not_exists_returns_empty_list(self):
        results = get_recent_task_results(self.project_root, limit=10)
        self.assertEqual(results, [])


class PathIsolationTests(unittest.TestCase):
    """Verify that different project_root values are fully isolated."""

    def setUp(self) -> None:
        _reset_for_test()
        self.tmp = tempfile.TemporaryDirectory()
        self.root_a = Path(self.tmp.name) / "a"
        self.root_b = Path(self.tmp.name) / "b"
        self.root_a.mkdir(parents=True, exist_ok=True)
        self.root_b.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        _reset_for_test()
        self.tmp.cleanup()

    def test_append_writes_to_correct_project_root(self):
        append_task_result(self.root_a, _result(task_id="task-a"))
        append_task_result(self.root_b, _result(task_id="task-b"))

        path_a = get_task_history_path(self.root_a)
        path_b = get_task_history_path(self.root_b)

        self.assertTrue(path_a.is_file())
        self.assertTrue(path_b.is_file())

        text_a = path_a.read_text(encoding="utf-8")
        text_b = path_b.read_text(encoding="utf-8")

        self.assertIn("task-a", text_a)
        self.assertNotIn("task-b", text_a)
        self.assertIn("task-b", text_b)
        self.assertNotIn("task-a", text_b)

    def test_get_recent_isolated_by_project_root(self):
        append_task_result(self.root_a, _result(task_id="task-a"))
        append_task_result(self.root_b, _result(task_id="task-b"))

        results_a = get_recent_task_results(self.root_a, limit=10)
        results_b = get_recent_task_results(self.root_b, limit=10)

        task_ids_a = [r["task_id"] for r in results_a]
        task_ids_b = [r["task_id"] for r in results_b]

        self.assertIn("task-a", task_ids_a)
        self.assertNotIn("task-b", task_ids_a)
        self.assertIn("task-b", task_ids_b)
        self.assertNotIn("task-a", task_ids_b)

    def test_root_switch_does_not_mix_data(self):
        append_task_result(self.root_a, _result(task_id="task-a"))
        results_a1 = get_recent_task_results(self.root_a, limit=10)
        self.assertEqual(len(results_a1), 1)
        self.assertEqual(results_a1[0]["task_id"], "task-a")

        append_task_result(self.root_b, _result(task_id="task-b"))
        results_b = get_recent_task_results(self.root_b, limit=10)
        self.assertEqual(len(results_b), 1)
        self.assertEqual(results_b[0]["task_id"], "task-b")

        results_a2 = get_recent_task_results(self.root_a, limit=10)
        self.assertEqual(len(results_a2), 1)
        self.assertEqual(results_a2[0]["task_id"], "task-a")
