from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from xiaohuang.agent_handoff.handoff_file_service import (
    get_handoff_dir,
    read_handoff_file,
    relative_handoff_path,
    write_handoff_file,
)


class AgentHandoffFileServiceTests(unittest.TestCase):
    def test_write_creates_runtime_agent_handoffs_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_handoff_file(
                project_root=root,
                target_agent="codex",
                user_request="优化任务历史页面",
                content="提示词内容",
                now=datetime(2026, 5, 10, 12, 0, 0),
            )

            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "提示词内容")
            self.assertEqual(path.parent, get_handoff_dir(root))
            self.assertIn("20260510_120000_codex_", path.name)
            self.assertEqual(relative_handoff_path(path, root).replace("\\", "/"), f"runtime/agent_handoffs/{path.name}")

    def test_write_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kwargs = {
                "project_root": root,
                "target_agent": "codex",
                "user_request": "same",
                "now": datetime(2026, 5, 10, 12, 0, 0),
            }
            first = write_handoff_file(content="one", **kwargs)
            second = write_handoff_file(content="two", **kwargs)

            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), "one")
            self.assertEqual(second.read_text(encoding="utf-8"), "two")

    def test_read_handoff_file_reads_utf8_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_handoff_file(
                project_root=root,
                target_agent="codex",
                user_request="copy",
                content="完整提示词内容",
                now=datetime(2026, 5, 10, 12, 0, 0),
            )
            result = read_handoff_file(root, relative_handoff_path(path, root))

            self.assertTrue(result["ok"])
            self.assertEqual(result["content"], "完整提示词内容")
            self.assertGreater(result["size"], 0)

    def test_read_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = read_handoff_file(root, "runtime/agent_handoffs/../secret.txt")

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "handoff path is not allowed")

    def test_read_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = read_handoff_file(root, str((root / "runtime" / "agent_handoffs" / "x.txt").resolve()))

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "handoff path is not allowed")

    def test_read_rejects_non_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = get_handoff_dir(root) / "x.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("no", encoding="utf-8")

            result = read_handoff_file(root, "runtime/agent_handoffs/x.md")

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "handoff file must be .txt")

    def test_read_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = read_handoff_file(Path(tmp), "runtime/agent_handoffs/missing.txt")

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "handoff file not found")

    def test_read_rejects_too_large_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = get_handoff_dir(root) / "big.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("abcdef", encoding="utf-8")

            result = read_handoff_file(root, "runtime/agent_handoffs/big.txt", max_bytes=3)

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "handoff file is too large")


if __name__ == "__main__":
    unittest.main()
