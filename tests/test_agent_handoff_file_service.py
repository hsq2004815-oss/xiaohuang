from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from xiaohuang.agent_handoff.handoff_file_service import (
    get_handoff_dir,
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


if __name__ == "__main__":
    unittest.main()
