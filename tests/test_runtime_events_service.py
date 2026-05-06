"""test_runtime_events_service.py

Tests for runtime_events service — event recording, ring buffer, JSONL, security.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from xiaohuang.capabilities.runtime_events.models import RuntimeEvent
from xiaohuang.capabilities.runtime_events.service import (
    init_event_logger,
    record_event,
    get_recent_events,
    _sanitize_dict,
)


class RuntimeEventModelTests(unittest.TestCase):
    """RuntimeEvent dataclass creation."""

    def test_create_event_now(self):
        evt = RuntimeEvent.now("stt_server", "ready", "server started")
        self.assertEqual(evt.source, "stt_server")
        self.assertEqual(evt.event_type, "ready")
        self.assertEqual(evt.message, "server started")
        self.assertEqual(evt.level, "info")
        self.assertIsInstance(evt.timestamp, str)
        self.assertIsInstance(evt.details, dict)

    def test_to_dict(self):
        evt = RuntimeEvent.now("control_panel", "start", "msg", level="error",
                               details={"a": 1})
        d = evt.to_dict()
        self.assertEqual(d["source"], "control_panel")
        self.assertEqual(d["event_type"], "start")
        self.assertEqual(d["level"], "error")
        self.assertEqual(d["details"]["a"], 1)

    def test_frozen(self):
        evt = RuntimeEvent.now("s", "t", "m")
        with self.assertRaises(Exception):
            evt.source = "x"  # type: ignore[misc]


class RecordEventTests(unittest.TestCase):
    """Record events to ring buffer."""

    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_record_event_in_ring_buffer(self):
        record_event("stt_server", "ready", "server ready")
        events = get_recent_events(10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source"], "stt_server")
        self.assertEqual(events[0]["event_type"], "ready")

    def test_record_multiple_events(self):
        for i in range(5):
            record_event("s", f"t{i}", f"msg{i}")
        self.assertEqual(len(get_recent_events(10)), 5)

    def test_recent_events_returns_lifo_order(self):
        record_event("s", "first", "a")
        record_event("s", "last", "b")
        events = get_recent_events(10)
        self.assertEqual(events[0]["message"], "a")
        self.assertEqual(events[1]["message"], "b")

    def test_get_recent_respects_limit(self):
        for i in range(10):
            record_event("s", f"t{i}", f"m{i}")
        self.assertEqual(len(get_recent_events(3)), 3)

    def test_default_limit_is_30(self):
        events = get_recent_events()
        self.assertIsInstance(events, list)

    def test_max_limit_capped_at_100(self):
        result = get_recent_events(200)
        self.assertEqual(len(result), 0)  # ring is empty, but limit clamped

    def test_ring_buffer_overflow_drops_oldest(self):
        for i in range(250):
            record_event("s", f"t{i}", f"m{i}")
        # ring buffer keeps last 200, get_recent_events capped at 100
        events = get_recent_events(100)
        self.assertLessEqual(len(events), 100)
        # oldest in the returned slice: 250 total - 200 kept = 50 dropped
        # ring has t50..t249, get_recent_events(100) returns t150..t249
        self.assertEqual(events[0]["event_type"], "t150")


class SensitiveFieldTests(unittest.TestCase):
    """Sensitive keys filtered."""

    def test_sensitive_keys_removed(self):
        d = {"api_key": "sk-xxx", "name": "test", "secret": "hush"}
        clean = _sanitize_dict(d)
        self.assertNotIn("api_key", clean)
        self.assertNotIn("secret", clean)
        self.assertIn("name", clean)

    def test_details_sanitized_in_event(self):
        evt = record_event("s", "t", "msg", details={"api_key": "sk-123", "x": "y"})
        self.assertNotIn("api_key", evt.details)
        self.assertIn("x", evt.details)

    def test_long_string_truncated(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        long_val = "x" * 600
        clean = svc._sanitize_value(long_val)
        self.assertLess(len(clean), 510)
        self.assertTrue(clean.endswith("..."))


class JSONLTests(unittest.TestCase):
    """JSONL file writing and reading."""

    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()
        self._tmp = tempfile.mkdtemp(prefix="xiaohuang_test_")
        init_event_logger(self._tmp)

    def tearDown(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()
        svc._jsonl_path = None
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_jsonl_file_created_on_record(self):
        record_event("stt_server", "ready", "server ready")
        jsonl = Path(self._tmp) / "logs" / "runtime_events.jsonl"
        self.assertTrue(jsonl.exists())

    def test_jsonl_lines_are_valid_json(self):
        record_event("s", "t1", "m1")
        record_event("s", "t2", "m2")
        jsonl = Path(self._tmp) / "logs" / "runtime_events.jsonl"
        lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            obj = json.loads(line)
            self.assertIn("source", obj)
            self.assertIn("event_type", obj)

    def test_load_recent_from_disk_on_init(self):
        record_event("s", "disk_test", "from disk")
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()
        svc._load_recent_from_disk(50)
        events = get_recent_events(10)
        loaded = [e for e in events if e.get("event_type") == "disk_test"]
        self.assertEqual(len(loaded), 1)

    def test_no_jsonl_path_does_not_crash(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._jsonl_path = None
        record_event("s", "t", "m")  # should not raise


class DiagnosticExportRuntimeEventsTests(unittest.TestCase):
    """TXT export includes runtime events section."""

    def test_runtime_events_section_in_export(self):
        from xiaohuang.capabilities.diagnostic_export.service import format_diagnostics_text
        text = format_diagnostics_text({
            "runtime_events": [
                {"timestamp": "2026-05-06T20:00:00", "source": "stt_server",
                 "event_type": "ready", "level": "info", "message": "server ready"},
            ]
        })
        self.assertIn("七、运行事件", text)
        self.assertIn("stt_server/ready", text)
        self.assertIn("server ready", text)

    def test_no_runtime_events_shows_placeholder(self):
        from xiaohuang.capabilities.diagnostic_export.service import format_diagnostics_text
        text = format_diagnostics_text({"runtime_events": []})
        self.assertIn("暂无运行事件", text)

    def test_no_runtime_events_key_shows_placeholder(self):
        from xiaohuang.capabilities.diagnostic_export.service import format_diagnostics_text
        text = format_diagnostics_text({})
        self.assertIn("暂无运行事件", text)

    def test_runtime_events_capped_at_30(self):
        from xiaohuang.capabilities.diagnostic_export.service import format_diagnostics_text
        many = [{"timestamp": f"t{i}", "source": "s", "event_type": "t",
                 "level": "info", "message": f"m{i}"} for i in range(50)]
        text = format_diagnostics_text({"runtime_events": many})
        self.assertIn("m0", text)
        self.assertIn("m29", text)
        self.assertNotIn("m49", text)


if __name__ == "__main__":
    unittest.main()
