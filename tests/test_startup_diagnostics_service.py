"""test_startup_diagnostics_service.py — tests for startup failure diagnostics."""

from __future__ import annotations

import unittest
from pathlib import Path

from xiaohuang.capabilities.startup_diagnostics.models import StartupDiagnostic
from xiaohuang.capabilities.startup_diagnostics.service import (
    diagnose_logs,
    diagnose_startup_failure,
    sanitize_diagnostic_value,
)


class MemoryErrorDiagnosticTests(unittest.TestCase):
    def test_recognises_not_enough_memory(self):
        diag = diagnose_logs({"stt_server.err.log": "DefaultCPUAllocator: not enough memory: 8GB requested"})
        self.assertEqual(diag.kind, "memory_error")
        self.assertEqual(diag.severity, "error")
        self.assertIn("内存不足", diag.summary)
        self.assertIn("logs/stt_server.err.log", diag.source_file or "")

    def test_recognises_model_init_error(self):
        diag = diagnose_logs({"stt_server.err.log": "ModelInitializationError: FunASR model initialization failed"})
        self.assertEqual(diag.kind, "memory_error")
        self.assertIn("模型初始化失败", diag.summary)

    def test_recognises_funasr_init_failed_alone(self):
        diag = diagnose_logs({"stt_server.out.log": "FunASR model initialization failed\nTraceback ..."})
        self.assertEqual(diag.kind, "memory_error")


class RunEnvParseErrorTests(unittest.TestCase):
    def test_recognises_parser_error_with_run_env(self):
        diag = diagnose_logs({
            "stt_server.err.log": (
                "ParserError: \n"
                "At scripts\\run_env.ps1:12 char:5\n"
                "+ & 'F:\\for_xiaohuang\\conda310\\python.exe'\n"
                "+ The ampersand (&) character is not allowed."
            ),
        })
        self.assertEqual(diag.kind, "run_env_parse_error")
        self.assertIn("run_env.ps1", diag.summary)

    def test_recognises_ampersand_not_allowed(self):
        diag = diagnose_logs({
            "stt_server.err.log": "AmpersandNotAllowed: The '&' character is not allowed in this context",
            "voice_overlay.err.log": "run_env.ps1 failed",
        })
        self.assertEqual(diag.kind, "run_env_parse_error")

    def test_parser_error_without_run_env_does_not_match(self):
        diag = diagnose_logs({"stt_server.err.log": "ParserError: some other script failed"})
        self.assertNotEqual(diag.kind, "run_env_parse_error")

    def test_recognises_chinese_parse_errors(self):
        diag = diagnose_logs({
            "stt_server.err.log": "不允许使用与号(&)。所在位置 行:1 字符: 2\nrun_env.ps1 failed",
        })
        self.assertEqual(diag.kind, "run_env_parse_error")


class PortHealthErrorTests(unittest.TestCase):
    def test_recognises_address_in_use(self):
        diag = diagnose_logs({"stt_server.err.log": "OSError: [Errno 10048] Only one usage of each socket address"})
        self.assertEqual(diag.kind, "port_or_health_error")
        self.assertIn("端口被占用", diag.summary)

    def test_recognises_connection_refused(self):
        diag = diagnose_logs({"voice_overlay.err.log": "ConnectionRefusedError: [WinError 1225] actively refused"})
        self.assertEqual(diag.kind, "port_or_health_error")

    def test_recognises_chinese_connection_error(self):
        diag = diagnose_logs({"stt_server.err.log": "无法连接到远程服务器"})
        self.assertEqual(diag.kind, "port_or_health_error")


class ModelCacheErrorTests(unittest.TestCase):
    def test_recognises_model_path_not_found(self):
        diag = diagnose_logs({"stt_server.err.log": "model_path_not_found: /home/user/.cache/modelscope/hub/..."})
        self.assertEqual(diag.kind, "model_cache_error")

    def test_recognises_checksum_error(self):
        diag = diagnose_logs({"stt_server.err.log": "checksum mismatch for model file"})
        self.assertEqual(diag.kind, "model_cache_error")

    def test_no_such_file_with_model_context(self):
        diag = diagnose_logs({"stt_server.err.log": "No such file: model/configuration.json"})
        self.assertEqual(diag.kind, "model_cache_error")

    def test_no_such_file_without_model_context(self):
        diag = diagnose_logs({"stt_server.err.log": "No such file: /tmp/foo.txt"})
        self.assertNotEqual(diag.kind, "model_cache_error")

    def test_recognises_connection_error(self):
        diag = diagnose_logs({"stt_server.err.log": "ConnectionError: Failed to download model"})
        self.assertEqual(diag.kind, "model_cache_error")


class UnknownAndNoneTests(unittest.TestCase):
    def test_unrecognised_error_returns_unknown(self):
        diag = diagnose_logs({"stt_server.err.log": "SomeRandomError: something went wrong"})
        self.assertEqual(diag.kind, "unknown")
        self.assertEqual(diag.severity, "warning")

    def test_empty_logs_return_none(self):
        diag = diagnose_logs({})
        self.assertEqual(diag.kind, "none")
        self.assertEqual(diag.severity, "info")

    def test_empty_string_logs_return_none(self):
        diag = diagnose_logs({"stt_server.err.log": ""})
        self.assertEqual(diag.kind, "none")

    def test_whitespace_only_logs_return_none(self):
        diag = diagnose_logs({"stt_server.err.log": "\n  \n"})
        self.assertEqual(diag.kind, "none")


class SanitizationTests(unittest.TestCase):
    def test_summary_does_not_contain_api_key(self):
        diag = diagnose_logs({"stt_server.err.log": "api_key=sk-abc123\nDefaultCPUAllocator: not enough memory"})
        self.assertNotIn("sk-abc123", diag.summary)
        self.assertNotIn("sk-abc123", diag.suggestion)

    def test_matched_text_does_not_contain_secret(self):
        diag = diagnose_logs({"stt_server.err.log": "token=secret123\nAmpersandNotAllowed at run_env.ps1"})
        self.assertEqual(diag.kind, "run_env_parse_error")
        self.assertNotIn("secret123", diag.summary)

    def test_sanitize_dict_removes_sensitive_keys(self):
        result = sanitize_diagnostic_value({
            "api_key": "sk-secret",
            "name": "test",
            "password": "1234",
            "normal": "value",
        })
        self.assertNotIn("api_key", result)
        self.assertNotIn("password", result)
        self.assertIn("name", result)
        self.assertIn("normal", result)

    def test_text_truncation_in_matched_output(self):
        long_line = "A" * 300 + " not enough memory"
        diag = diagnose_logs({"stt_server.err.log": long_line})
        self.assertEqual(diag.kind, "memory_error")
        self.assertTrue(diag.matched_text is not None)
        self.assertLessEqual(len(diag.matched_text or ""), 203)


class FileEdgeCaseTests(unittest.TestCase):
    def test_read_nonexistent_directory_does_not_crash(self):
        diag = diagnose_startup_failure(Path("Z:/nonexistent/path/that/does/not/exist"))
        self.assertEqual(diag.kind, "none")

    def test_multiple_log_files_combined_matching(self):
        diag = diagnose_logs({
            "stt_server.out.log": "Some info log line",
            "stt_server.err.log": "DefaultCPUAllocator: not enough memory",
            "voice_overlay.err.log": "Voice overlay also failed",
        })
        self.assertEqual(diag.kind, "memory_error")
        self.assertIn("stt_server.err.log", diag.source_file or "")


class ModelTests(unittest.TestCase):
    def test_to_dict(self):
        diag = StartupDiagnostic(
            kind="memory_error",
            severity="error",
            summary="STT 模型加载失败",
            suggestion="关闭 Chrome 后重试",
            source_file="logs/stt_server.err.log",
        )
        d = diag.to_dict()
        self.assertEqual(d["kind"], "memory_error")
        self.assertEqual(d["severity"], "error")
        self.assertEqual(d["summary"], "STT 模型加载失败")
        self.assertEqual(d["suggestion"], "关闭 Chrome 后重试")
        self.assertEqual(d["source_file"], "logs/stt_server.err.log")

    def test_to_dict_without_optionals(self):
        diag = StartupDiagnostic(
            kind="unknown",
            severity="warning",
            summary="启动失败",
            suggestion="查看日志",
        )
        d = diag.to_dict()
        self.assertIsNone(d["source_file"])


if __name__ == "__main__":
    unittest.main()
