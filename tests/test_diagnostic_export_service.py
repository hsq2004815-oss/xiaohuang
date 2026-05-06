"""test_diagnostic_export_service.py

Tests for diagnostic_export service — TXT formatting, file writing, security.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

from xiaohuang.capabilities.diagnostic_export.models import (
    DiagnosticExportInput,
    DiagnosticExportResult,
    DiagnosticHistoryEntry,
)
from xiaohuang.capabilities.diagnostic_export.service import (
    export_diagnostics_to_file,
    format_diagnostics_text,
    _sanitize_dict,
    _sanitize_history,
    _fmt_bool,
)


class FormatDiagnosticsTextTests(unittest.TestCase):
    """TXT formatting from payload."""

    def test_minimal_payload_produces_valid_text(self):
        text = format_diagnostics_text({})
        self.assertIn("小黄诊断信息导出", text)
        self.assertIn("导出时间：", text)
        self.assertIn("一、运行状态", text)
        self.assertIn("二、唤醒与语音", text)
        self.assertIn("三、模型与回复", text)
        self.assertIn("四、路径", text)
        self.assertIn("五、最近操作", text)
        self.assertIn("六、操作历史", text)

    def test_missing_fields_show_placeholder(self):
        text = format_diagnostics_text({})
        self.assertIn("无", text)

    def test_bool_values_formatted_yes_no(self):
        text = format_diagnostics_text({
            "status": {
                "stt_ready": True,
                "can_wake_now": False,
                "wake_fallback_enabled": True,
            }
        })
        lines = text.split("\n")
        self.assertIn("- STT Ready：是", lines)
        self.assertIn("- 可唤醒：否", lines)
        self.assertIn("- Wake Fallback：是", lines)

    def test_status_fields_populated(self):
        text = format_diagnostics_text({
            "status": {
                "overall_message": "已就绪 — 可以说贾维斯",
                "overall_status": "READY",
                "stt_running": True,
                "stt_ready": True,
                "stt_model_loaded": True,
                "overlay_running": True,
                "can_wake_now": True,
                "wake_engine": "openwakeword",
                "wake_device_index": 0,
                "wake_cooldown_seconds": 2.5,
                "wake_sensitivity": 0.5,
                "wake_fallback_enabled": True,
                "wake_phrases": ["贾维斯"],
                "assistant_display_name": "贾维斯",
                "llm_provider": "deepseek",
                "tts_enabled": True,
                "last_error": None,
            }
        })
        self.assertIn("已就绪", text)
        self.assertIn("openwakeword", text)
        self.assertIn("贾维斯", text)
        self.assertIn("deepseek", text)

    def test_history_formatted(self):
        text = format_diagnostics_text({
            "history": [
                {"time": "19:24:31", "op": "get_status", "ok": True, "detail": "完成 2955ms"},
                {"time": "19:24:28", "op": "get_log_paths", "ok": True, "detail": "完成 49ms"},
                {"time": "19:24:20", "op": "start_xiaohuang", "ok": False, "detail": "timeout"},
            ]
        })
        self.assertIn("get_status", text)
        self.assertIn("完成", text)
        self.assertIn("失败", text)
        self.assertIn("timeout", text)

    def test_html_tags_not_present_as_markup(self):
        text = format_diagnostics_text({
            "status": {"overall_message": "<script>alert(1)</script>"}
        })
        self.assertNotIn("<script>", text)
        self.assertNotIn("</script>", text)

    def test_sensitive_keys_not_exported(self):
        text = format_diagnostics_text({
            "status": {
                "api_key": "sk-secret-123",
                "api_key_env": "DEEPSEEK_API_KEY",
                "secret": "shh",
                "password": "pwd123",
                "token": "tok",
                "authorization": "Bearer xxx",
                "overall_status": "READY",
            }
        })
        self.assertNotIn("sk-secret-123", text)
        self.assertNotIn("DEEPSEEK_API_KEY", text)
        self.assertNotIn("shh", text)
        self.assertNotIn("pwd123", text)
        self.assertNotIn("tok", text)
        self.assertNotIn("Bearer xxx", text)
        self.assertIn("READY", text)

    def test_exported_from_field(self):
        text = format_diagnostics_text({"exported_from": "control_panel_web"})
        self.assertIn("control_panel_web", text)

    def test_empty_history_no_crash(self):
        text = format_diagnostics_text({"history": []})
        self.assertIn("六、操作历史", text)
        self.assertIn("（无操作历史）", text)

    def test_history_capped_at_30(self):
        many = [{"time": f"t{i}", "op": f"op{i}", "ok": True, "detail": ""} for i in range(50)]
        text = format_diagnostics_text({"history": many})
        self.assertIn("op0", text)
        self.assertIn("op29", text)
        self.assertNotIn("op49", text)


class ExportDiagnosticsToFileTests(unittest.TestCase):
    """File writing safety and correctness."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="xiaohuang_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_writes_file_to_diagnostic_exports_subdir(self):
        result = export_diagnostics_to_file("hello diagnostics", self._tmp)
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.path)
        resolved = Path(result.path)
        self.assertTrue(resolved.exists())
        self.assertIn("diagnostic_exports", str(resolved))
        self.assertIn("xiaohuang_diagnostics_", str(resolved))
        self.assertTrue(str(resolved).endswith(".txt"))

    def test_returns_content_in_result(self):
        result = export_diagnostics_to_file("test content", self._tmp)
        self.assertEqual(result.content, "test content")

    def test_file_content_is_utf8(self):
        result = export_diagnostics_to_file("中文诊断内容\n第二行", self._tmp)
        content = Path(result.path).read_text(encoding="utf-8")
        self.assertIn("中文诊断内容", content)
        self.assertIn("第二行", content)

    def test_rejects_relative_path(self):
        result = export_diagnostics_to_file("text", "relative/path")
        self.assertFalse(result.ok)
        self.assertIn("绝对路径", result.message)

    def test_multiple_exports_create_unique_files(self):
        r1 = export_diagnostics_to_file("a", self._tmp)
        r2 = export_diagnostics_to_file("b", self._tmp)
        self.assertTrue(r1.ok)
        self.assertTrue(r2.ok)
        self.assertNotEqual(r1.path, r2.path)


class SanitizeDictTests(unittest.TestCase):
    """Sensitive key redaction."""

    def test_removes_sensitive_keys(self):
        d = {"api_key": "sk-xxx", "name": "小黄", "secret": "hush"}
        clean = _sanitize_dict(d)
        self.assertNotIn("api_key", clean)
        self.assertNotIn("secret", clean)
        self.assertIn("name", clean)
        self.assertEqual(clean["name"], "小黄")

    def test_case_insensitive_match(self):
        d = {"API_KEY": "sk-xxx", "Api_Key_Env": "VAR"}
        clean = _sanitize_dict(d)
        self.assertNotIn("API_KEY", clean)
        self.assertNotIn("Api_Key_Env", clean)

    def test_keeps_safe_keys(self):
        d = {"wake_engine": "openwakeword", "device_id": 0}
        clean = _sanitize_dict(d)
        self.assertEqual(clean, d)


class SanitizeHistoryTests(unittest.TestCase):
    """History entry normalization."""

    def test_normalizes_entries(self):
        raw = [
            {"time": "19:00", "op": "start", "ok": True, "detail": "ok"},
            {"time": "19:01", "op": "stop", "ok": False, "detail": "err"},
        ]
        result = _sanitize_history(raw)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["time"], "19:00")
        self.assertEqual(result[0]["op"], "start")
        self.assertTrue(result[0]["ok"])
        self.assertEqual(result[1]["detail"], "err")

    def test_caps_at_30(self):
        raw = [{"time": f"t{i}", "op": f"o{i}", "ok": True, "detail": ""} for i in range(50)]
        result = _sanitize_history(raw)
        self.assertEqual(len(result), 30)

    def test_missing_fields_defaulted(self):
        result = _sanitize_history([{"time": "x"}])
        self.assertEqual(result[0]["time"], "x")
        self.assertEqual(result[0]["op"], "")
        self.assertIsNone(result[0]["ok"])


class FmtBoolTests(unittest.TestCase):
    def test_true_is_yes(self):
        self.assertEqual(_fmt_bool(True), "是")

    def test_false_is_no(self):
        self.assertEqual(_fmt_bool(False), "否")

    def test_none_is_dash(self):
        self.assertEqual(_fmt_bool(None), "--")


if __name__ == "__main__":
    unittest.main()
