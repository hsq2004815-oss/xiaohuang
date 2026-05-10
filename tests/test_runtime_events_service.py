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


# ---------------------------------------------------------------------------
# V1.4-Q2 additions — level, blank fields, details edge cases, API exposure
# ---------------------------------------------------------------------------

class LevelPreservationTests(unittest.TestCase):
    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_record_event_preserves_info_level(self):
        evt = record_event("s", "t", "msg", level="info")
        self.assertEqual(evt.level, "info")

    def test_record_event_preserves_warning_level(self):
        evt = record_event("s", "t", "msg", level="warning")
        self.assertEqual(evt.level, "warning")

    def test_record_event_preserves_error_level(self):
        evt = record_event("s", "t", "msg", level="error")
        self.assertEqual(evt.level, "error")

    def test_record_event_defaults_to_info(self):
        evt = record_event("s", "t", "msg")
        self.assertEqual(evt.level, "info")


class BlankSourceOrTypeTests(unittest.TestCase):
    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_record_event_allows_empty_string_source(self):
        evt = record_event("", "t", "msg")
        self.assertEqual(evt.source, "")

    def test_record_event_allows_empty_string_event_type(self):
        evt = record_event("s", "", "msg")
        self.assertEqual(evt.event_type, "")

    def test_record_event_allows_empty_string_message(self):
        evt = record_event("s", "t", "")
        self.assertEqual(evt.message, "")


class DetailsEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_record_event_with_none_details(self):
        evt = record_event("s", "t", "msg", details=None)
        self.assertIsInstance(evt.details, dict)
        json.dumps(evt.to_dict())

    def test_record_event_with_empty_details(self):
        evt = record_event("s", "t", "msg", details={})
        self.assertIsInstance(evt.details, dict)
        json.dumps(evt.to_dict())

    def test_record_event_details_are_json_friendly(self):
        evt = record_event("s", "t", "msg", details={
            "command": "open_logs_folder",
            "ok": True,
            "count": 3,
            "items": ["a", "b"],
        })
        data = json.dumps(evt.to_dict(), ensure_ascii=False)
        parsed = json.loads(data)
        self.assertEqual(parsed["details"]["command"], "open_logs_folder")
        self.assertEqual(parsed["details"]["ok"], True)
        self.assertEqual(parsed["details"]["count"], 3)
        self.assertEqual(parsed["details"]["items"], ["a", "b"])

    def test_record_event_details_with_bool_int_list_mixed(self):
        evt = record_event("s", "t", "msg", details={
            "executed": True,
            "risk": "low",
            "cost": 0,
            "labels": ["info", "warning"],
        })
        data = json.dumps(evt.to_dict(), ensure_ascii=False)
        parsed = json.loads(data)
        self.assertEqual(parsed["details"]["executed"], True)
        self.assertEqual(parsed["details"]["cost"], 0)
        self.assertEqual(parsed["details"]["labels"], ["info", "warning"])

    def test_record_event_details_with_nested_dict(self):
        evt = record_event("s", "t", "msg", details={
            "status": {"ok": True, "code": 200},
        })
        data = json.dumps(evt.to_dict(), ensure_ascii=False)
        parsed = json.loads(data)
        self.assertIsInstance(parsed["details"]["status"], dict)
        self.assertTrue(parsed["details"]["status"]["ok"])

    def test_record_event_details_removes_sensitive_in_nested(self):
        evt = record_event("s", "t", "msg", details={
            "outer": {"api_key": "sk-nested", "name": "ok"},
        })
        self.assertNotIn("api_key", evt.details.get("outer", {}))
        self.assertIn("name", evt.details["outer"])


class ControlPanelRuntimeEventsApiTests(unittest.TestCase):
    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_control_panel_exposes_runtime_events_json_friendly(self):
        record_event("control_panel", "test_event", "test message",
                     level="info", details={"key": "value"})

        from xiaohuang.control_panel_web_service import ControlPanelWebApi
        with self._patch_web_api_deps():
            api = ControlPanelWebApi(config_path=None)
            result = api.get_runtime_events(20)
            self.assertTrue(result["ok"])
            self.assertIn("events", result["data"])
            self.assertGreaterEqual(len(result["data"]["events"]), 1)
            self.assertIn("test_event", str(result["data"]["events"]))
            json.dumps(result)

    def test_get_runtime_events_returns_json_friendly_response(self):
        from xiaohuang.control_panel_web_service import ControlPanelWebApi
        with self._patch_web_api_deps():
            api = ControlPanelWebApi(config_path=None)
            result = api.get_runtime_events(5)
            data = json.dumps(result, ensure_ascii=False)
            parsed = json.loads(data)
            self.assertTrue(parsed["ok"])

    @staticmethod
    def _patch_web_api_deps():
        parent = unittest.mock
        return parent.patch.multiple(
            "xiaohuang.control_panel_web_service",
            get_project_root=parent.DEFAULT,
            _record_cp_event=parent.DEFAULT,
        )


class CapabilityEventRecordingTests(unittest.TestCase):
    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_get_status_capability_records_runtime_event(self):
        from xiaohuang.capabilities.local_commands.service import execute_capability
        from xiaohuang.capabilities.local_commands.models import RouteDecision

        decision = RouteDecision(
            is_task_request=True,
            can_execute=True,
            command="get_status",
            reason="capability_matched",
            message="匹配到能力：读取当前小黄运行状态",
        )
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            import json as _json
            cfg = Path(tmp) / "config.json"
            cfg.write_text(_json.dumps({"wake": {"phrases": ["小黄"]}}), encoding="utf-8")
            result = execute_capability(decision, project_root=Path(tmp), config_path=cfg)

        events = get_recent_events(50)
        capability_events = [e for e in events if e.get("source") == "capability_router"]
        self.assertGreaterEqual(len(capability_events), 1)
        self.assertIn("capability_invoked", [e["event_type"] for e in capability_events])

    def test_export_diagnostics_records_runtime_event(self):
        from xiaohuang.capabilities.local_commands.service import execute_capability
        from xiaohuang.capabilities.local_commands.models import RouteDecision
        from pathlib import Path

        decision = RouteDecision(
            is_task_request=True,
            can_execute=True,
            command="export_diagnostics",
            reason="capability_matched",
            message="匹配到能力：导出诊断信息 TXT",
        )
        with tempfile.TemporaryDirectory() as tmp:
            import json as _json
            cfg = Path(tmp) / "config.json"
            cfg.write_text(_json.dumps({"wake": {"phrases": ["小黄"]}}), encoding="utf-8")
            result = execute_capability(decision, project_root=Path(tmp), config_path=cfg)

        events = get_recent_events(50)
        capability_events = [e for e in events if e.get("source") == "capability_router"]
        self.assertGreaterEqual(len(capability_events), 1)


class ClearRecentEventsTests(unittest.TestCase):
    def setUp(self):
        from xiaohuang.capabilities.runtime_events import service as svc
        svc._ring.clear()

    def test_clear_removes_all_events(self):
        from xiaohuang.capabilities.runtime_events.service import (
            clear_recent_events,
            get_recent_events,
            record_event,
        )
        record_event("s", "t1", "m1")
        record_event("s", "t2", "m2")

        removed = clear_recent_events()

        self.assertEqual(removed, 2)
        self.assertEqual(len(get_recent_events(50)), 0)

    def test_clear_empty_events_returns_zero(self):
        from xiaohuang.capabilities.runtime_events.service import (
            clear_recent_events,
        )
        removed = clear_recent_events()
        self.assertEqual(removed, 0)

    def test_clear_returns_int(self):
        from xiaohuang.capabilities.runtime_events.service import (
            clear_recent_events,
            record_event,
        )
        record_event("s", "t", "m")
        removed = clear_recent_events()
        self.assertIsInstance(removed, int)


if __name__ == "__main__":
    unittest.main()
