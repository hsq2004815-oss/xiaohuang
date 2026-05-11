from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaohuang.agent_handoff.terminal_launcher import (
    _visible_console_popen_kwargs,
    open_target_project_terminal,
    quote_powershell_single,
)


class AgentHandoffTerminalLauncherTests(unittest.TestCase):
    def test_quote_powershell_single_escapes_single_quotes(self):
        self.assertEqual(quote_powershell_single("C:\\O'Hara"), "'C:\\O''Hara'")

    def test_open_terminal_uses_powershell_set_location_only(self):
        calls = []

        def fake_popen(args, **kwargs):
            calls.append((list(args), dict(kwargs)))
            return object()

        with tempfile.TemporaryDirectory() as tmp:
            result = open_target_project_terminal(tmp, popen_func=fake_popen, os_name="nt")

        self.assertTrue(result.ok)
        self.assertIn("已向系统请求打开", result.message)
        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(command[:3], ["powershell.exe", "-NoExit", "-Command"])
        self.assertIn("Set-Location -LiteralPath", command[3])
        self.assertEqual(kwargs.get("creationflags"), _visible_console_popen_kwargs().get("creationflags"))
        executable_parts = " ".join(command[:3] + [command[3].split(" -LiteralPath ", 1)[0]]).lower()
        for forbidden in ("claude", "codex", "opencode", "openclaw", "npm", "git", "python"):
            self.assertNotIn(forbidden, executable_parts)

    def test_missing_path_is_rejected(self):
        result = open_target_project_terminal("", os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "missing_target_project_path")

    def test_unspecified_path_is_rejected(self):
        result = open_target_project_terminal("未指定", os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "missing_target_project_path")

    def test_relative_path_is_rejected(self):
        result = open_target_project_terminal("relative\\project", os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "invalid_target_project_path")

    def test_parent_segment_is_rejected(self):
        result = open_target_project_terminal("C:\\Projects\\..\\secret", os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "invalid_target_project_path")

    def test_nonexistent_path_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "missing")
            result = open_target_project_terminal(missing, os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "target_project_path_not_found")
        self.assertIn("不能回退到小黄项目", result.message)

    def test_file_path_is_rejected(self):
        with tempfile.NamedTemporaryFile() as tmp:
            result = open_target_project_terminal(tmp.name, os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "target_project_path_not_directory")

    def test_non_windows_platform_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = open_target_project_terminal(tmp, os_name="posix")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "unsupported_platform")

    def test_powershell_missing_is_reported(self):
        def fake_popen(args, **kwargs):
            raise FileNotFoundError()

        with tempfile.TemporaryDirectory() as tmp:
            result = open_target_project_terminal(tmp, popen_func=fake_popen, os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "powershell_not_found")

    def test_launch_failure_is_reported(self):
        def fake_popen(args, **kwargs):
            raise OSError("blocked")

        with tempfile.TemporaryDirectory() as tmp:
            result = open_target_project_terminal(tmp, popen_func=fake_popen, os_name="nt")

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "terminal_launch_failed")
        self.assertIn("blocked", result.message)


if __name__ == "__main__":
    unittest.main()
