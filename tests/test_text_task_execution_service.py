from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xiaohuang.text_task_execution_service import (
    _recent_log_files,
    execute_confirmed_text_task,
)


class TextTaskExecutionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_readonly_log_analysis_reads_recent_logs_and_counts_keywords(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        (logs / "old.log").write_text("old warning\n", encoding="utf-8")
        (logs / "notes.txt").write_text("ERROR from txt\n", encoding="utf-8")
        recent = logs / "recent.log"
        recent.write_text(
            "INFO boot\nERROR failed startup\nTraceback here\nwarning only\nException raised\n",
            encoding="utf-8",
        )
        os.utime(logs / "old.log", (1, 1))
        os.utime(logs / "notes.txt", (2, 2))
        os.utime(recent, (3, 3))

        result = execute_confirmed_text_task(
            _task("readonly_log_analysis"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("error 2", result.summary)
        self.assertIn("traceback 1", result.summary)
        self.assertIn("warning", result.summary)
        self.assertIn("recent.log", result.details)
        self.assertIn("logs/recent.log", result.read_files)
        self.assertIn("logs/notes.txt", result.read_files)

    def test_log_analysis_without_logs_dir_completes_with_message(self):
        result = execute_confirmed_text_task(
            _task("readonly_log_analysis"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("未发现 logs 目录", result.summary)
        self.assertEqual(result.read_files, ())

    def test_allowed_false_is_blocked(self):
        result = execute_confirmed_text_task(
            _task("readonly_log_analysis", allowed=False),
            project_root=self.project_root,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.error, "blocked_task")

    def test_blocked_local_execution_is_blocked(self):
        result = execute_confirmed_text_task(
            _task("blocked_local_execution", risk_level="high", allowed=False),
            project_root=self.project_root,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")

    def test_high_risk_is_blocked(self):
        result = execute_confirmed_text_task(
            _task("readonly_log_analysis", risk_level="high"),
            project_root=self.project_root,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")

    def test_unknown_task_type_is_blocked(self):
        result = execute_confirmed_text_task(
            _task("unknown"),
            project_root=self.project_root,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")

    def test_read_files_are_relative_strings(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\n", encoding="utf-8")

        result = execute_confirmed_text_task(
            _task("readonly_log_analysis"),
            project_root=self.project_root,
        )

        self.assertTrue(all(isinstance(item, str) for item in result.read_files))
        self.assertTrue(all(not Path(item).is_absolute() for item in result.read_files))

    def test_log_analysis_skips_symlink_logs(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")
        logs = self.project_root / "logs"
        logs.mkdir()
        outside = self.project_root / "outside.log"
        outside.write_text("ERROR SHOULD_NOT_LEAK\n", encoding="utf-8")
        link = logs / "linked.log"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        (logs / "app.log").write_text("ERROR inside\n", encoding="utf-8")

        result = execute_confirmed_text_task(
            _task("readonly_log_analysis"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertIn("logs/app.log", result.read_files)
        self.assertNotIn("logs/linked.log", result.read_files)
        self.assertNotIn("SHOULD_NOT_LEAK", result.details)

    def test_recent_log_files_ignores_stat_errors(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        good = logs / "app.log"
        bad = logs / "bad.log"
        good.write_text("ERROR one\n", encoding="utf-8")
        bad.write_text("ERROR two\n", encoding="utf-8")
        original_stat = Path.stat

        def fake_stat(path: Path, *args, **kwargs):
            if path == bad:
                raise OSError("stat failed")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", fake_stat):
            files = _recent_log_files(logs)

        self.assertIn(good, files)

    def test_does_not_call_subprocess_or_os_system(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\n", encoding="utf-8")

        with patch("subprocess.run") as mock_run, patch("os.system") as mock_system:
            result = execute_confirmed_text_task(
                _task("readonly_log_analysis"),
                project_root=self.project_root,
            )

        self.assertTrue(result.ok)
        mock_run.assert_not_called()
        mock_system.assert_not_called()

    def test_readonly_status_check_is_conservative(self):
        (self.project_root / "src").mkdir()
        (self.project_root / "scripts").mkdir()
        (self.project_root / "frontend").mkdir()
        (self.project_root / "scripts" / "control_panel_web.py").write_text("", encoding="utf-8")

        result = execute_confirmed_text_task(
            _task("readonly_status_check"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("control_panel_web.py：可定位", result.details)

    def test_readonly_diagnostic_review_reuses_log_analysis_without_export(self):
        result = execute_confirmed_text_task(
            _task("readonly_diagnostic_review"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("未发现已有诊断文件", result.details)


def _task(
    task_type: str,
    *,
    risk_level: str = "low",
    allowed: bool = True,
) -> dict:
    return {
        "task_id": "text-task-test",
        "task_type": task_type,
        "title": "测试任务",
        "summary": "测试",
        "risk_level": risk_level,
        "status": "pending_confirmation",
        "allowed": allowed,
        "original_text": "测试",
    }
