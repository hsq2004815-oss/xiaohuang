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

    def test_readonly_recent_errors_review_reads_logs(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        (logs / "app.log").write_text(
            "INFO boot\nERROR failed startup\nWARNING disk full\nCRITICAL crash\n",
            encoding="utf-8",
        )

        result = execute_confirmed_text_task(
            _task("readonly_recent_errors_review"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("readonly_recent_errors_review", result.task_type)
        self.assertIn("logs/app.log", result.read_files)

    def test_readonly_recent_errors_review_no_logs_dir(self):
        result = execute_confirmed_text_task(
            _task("readonly_recent_errors_review"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("未发现可读取的日志文件", result.summary)

    def test_readonly_recent_errors_redacts_sensitive_info(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        (logs / "app.log").write_text(
            "ERROR api_key=sk-test-exposed-token\n"
            "WARNING token=abc123\n"
            "FAILED password=123456\n"
            "Exception secret=hello\n"
            "Traceback authorization=Bearer abc.def\n"
            "ERROR Bearer standalone-token\n",
            encoding="utf-8",
        )

        result = execute_confirmed_text_task(
            _task("readonly_recent_errors_review"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        details = result.details
        self.assertNotIn("sk-test-exposed-token", details)
        self.assertNotIn("abc123", details)
        self.assertNotIn("123456", details)
        self.assertNotIn("hello", details)
        self.assertNotIn("abc.def", details)
        self.assertNotIn("standalone-token", details)
        self.assertIn("<redacted>", details)
        self.assertIn("ERROR", details)
        self.assertIn("WARNING", details)
        self.assertIn("FAILED", details)

    def test_readonly_runtime_events_review_with_events(self):
        from xiaohuang.capabilities.runtime_events import service as es
        from xiaohuang.capabilities.runtime_events.service import record_event
        es._ring.clear()

        try:
            record_event("voice_overlay", "started", "overlay started")
            record_event("capability_router", "capability_failed", "failed",
                        level="error", details={"command": "test"})
            record_event("control_panel", "start_xiaohuang", "started")

            result = execute_confirmed_text_task(
                _task("readonly_runtime_events_review"),
                project_root=self.project_root,
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "completed")
            self.assertIn("3 条", result.summary)
            self.assertIn("error", result.summary)
            self.assertIn("voice_overlay", result.details)
            self.assertIn("capability_router", result.details)
            self.assertIn("capability_failed", result.details)
            self.assertIn("[ERROR]", result.details)
        finally:
            es._ring.clear()

    def test_readonly_runtime_events_review_empty_events(self):
        from xiaohuang.capabilities.runtime_events import service as es
        es._ring.clear()

        try:
            result = execute_confirmed_text_task(
                _task("readonly_runtime_events_review"),
                project_root=self.project_root,
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "completed")
            self.assertIn("没有可用运行事件", result.summary)
        finally:
            es._ring.clear()

    def test_readonly_runtime_events_review_does_not_clear_ring(self):
        from xiaohuang.capabilities.runtime_events import service as es
        from xiaohuang.capabilities.runtime_events.service import record_event, get_recent_events
        es._ring.clear()

        try:
            record_event("s", "t", "msg")
            before_count = len(get_recent_events(50))

            result = execute_confirmed_text_task(
                _task("readonly_runtime_events_review"),
                project_root=self.project_root,
            )

            after_count = len(get_recent_events(50))
            self.assertTrue(result.ok)
            self.assertEqual(after_count, before_count)
        finally:
            es._ring.clear()

    def test_readonly_config_summary(self):
        result = execute_confirmed_text_task(
            _task("readonly_config_summary"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertIn("LLM", result.details)
        self.assertIn("TTS", result.details)
        self.assertIn("deepseek", result.details)
        self.assertIn("DEEPSEEK_API_KEY", result.details)

    def test_readonly_config_summary_no_secrets(self):
        result = execute_confirmed_text_task(
            _task("readonly_config_summary"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        details_lower = result.details.lower()
        self.assertNotIn("secret", details_lower.split())
        self.assertNotIn("password", details_lower.split())

    def test_readonly_config_summary_uses_explicit_config_path(self):
        import os as _os
        cfg = self.project_root / "custom_config.json"
        cfg.write_text(
            '{"assistant":{"display_name":"小黄自定义配置"},'
            '"tts":{"enabled":true,"voice":"zh-CN-YunxiNeural"},'
            '"llm":{"enabled":true,"provider":"deepseek","model":"custom-model",'
            '"api_key_env":"CUSTOM_DEEPSEEK_KEY"}}',
            encoding="utf-8",
        )

        old = _os.environ.get("CUSTOM_DEEPSEEK_KEY")
        _os.environ["CUSTOM_DEEPSEEK_KEY"] = "real-secret-value"
        try:
            result = execute_confirmed_text_task(
                _task("readonly_config_summary"),
                project_root=self.project_root,
                config_path=cfg,
            )
        finally:
            if old is not None:
                _os.environ["CUSTOM_DEEPSEEK_KEY"] = old
            else:
                _os.environ.pop("CUSTOM_DEEPSEEK_KEY", None)

        self.assertTrue(result.ok)
        self.assertIn("小黄自定义配置", result.details)
        self.assertIn("zh-CN-YunxiNeural", result.details)
        self.assertIn("custom-model", result.details)
        self.assertIn("CUSTOM_DEEPSEEK_KEY", result.details)
        self.assertNotIn("real-secret-value", result.details)

    def test_readonly_config_summary_none_config_path_uses_default(self):
        result = execute_confirmed_text_task(
            _task("readonly_config_summary"),
            project_root=self.project_root,
            config_path=None,
        )
        self.assertTrue(result.ok)
        self.assertIn("deepseek", result.details)

    def test_readonly_health_report_returns_complete(self):
        (self.project_root / "src" / "xiaohuang").mkdir(parents=True, exist_ok=True)
        (self.project_root / "scripts").mkdir(parents=True, exist_ok=True)
        (self.project_root / "scripts" / "control_panel_web.py").write_text("", encoding="utf-8")
        (self.project_root / "scripts" / "voice_overlay.py").write_text("", encoding="utf-8")
        (self.project_root / "frontend" / "control_panel").mkdir(parents=True, exist_ok=True)

        result = execute_confirmed_text_task(
            _task("readonly_health_report"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.task_type, "readonly_health_report")
        self.assertIn("总体状态", result.summary)
        self.assertIn("基础状态", result.details)
        self.assertIn("配置状态", result.details)
        self.assertIn("运行事件", result.details)
        self.assertIn("最近错误", result.details)
        self.assertIn("建议", result.details)
        self.assertEqual(result.risk_level, "low")

    def test_readonly_health_report_with_missing_paths(self):
        result = execute_confirmed_text_task(
            _task("readonly_health_report"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertIn("缺失", result.details)
        self.assertIn("有错误", result.details)

    def test_readonly_health_report_does_not_clear_events(self):
        from xiaohuang.capabilities.runtime_events import service as es
        from xiaohuang.capabilities.runtime_events.service import record_event
        es._ring.clear()

        try:
            record_event("test", "test", "test msg")
            before = len(es._ring)

            result = execute_confirmed_text_task(
                _task("readonly_health_report"),
                project_root=self.project_root,
            )

            after = len(es._ring)
            self.assertTrue(result.ok)
            self.assertEqual(after, before, "Health report must not clear runtime events")
        finally:
            es._ring.clear()

    def test_readonly_health_report_no_sensitive_leak(self):
        logs = self.project_root / "logs"
        logs.mkdir()
        (logs / "app.log").write_text(
            "ERROR api_key=sk-leaked-key\nWARNING token=abc123\n", encoding="utf-8",
        )

        result = execute_confirmed_text_task(
            _task("readonly_health_report"),
            project_root=self.project_root,
        )

        self.assertTrue(result.ok)
        self.assertNotIn("sk-leaked-key", result.details)
        self.assertNotIn("abc123", result.details)


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
