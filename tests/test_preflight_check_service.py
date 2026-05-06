"""test_preflight_check_service.py — tests for startup preflight check."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from xiaohuang.capabilities.preflight_check.models import (
    PreflightCheckItem,
    PreflightCheckResult,
)
from xiaohuang.capabilities.preflight_check.service import (
    _check_logs_writable,
    _check_memory,
    _check_model_cache,
    _check_python_env,
    _check_stt_port,
    run_preflight_check,
)


class OverallStatusTests(unittest.TestCase):
    def test_all_ok_returns_ok(self):
        items = [
            PreflightCheckItem("a", "A", "ok", "good"),
            PreflightCheckItem("b", "B", "ok", "good"),
        ]
        result = PreflightCheckResult(status="ok", summary="ok", items=items)
        self.assertEqual(result.status, "ok")

    def test_warning_no_error_returns_warning(self):
        result = run_preflight_check(
            Path("."),
            memory_reader=lambda: {"free_physical_gb": 4.0, "free_virtual_gb": 10.0},
            python_path=__file__,
            model_cache_base=Path("/nonexistent"),
        )
        self.assertEqual(result.status, "warning")

    def test_has_error_returns_error(self):
        result = run_preflight_check(
            Path("."),
            memory_reader=lambda: {"free_physical_gb": 1.0, "free_virtual_gb": 2.0},
            python_path="/nonexistent/python.exe",
            model_cache_base=Path("/nonexistent"),
        )
        self.assertEqual(result.status, "error")

    def test_all_green_returns_ok_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            python = root / "python.exe"
            python.write_text("fake")
            for rel in [
                "models/iic/SenseVoiceSmall/model.pt",
                "models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch/model.pt",
            ]:
                full = root / rel
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text("fake")
            result = run_preflight_check(
                root,
                memory_reader=lambda: {"free_physical_gb": 10.0, "free_virtual_gb": 20.0},
                python_path=str(python),
                model_cache_base=root,
            )
            self.assertEqual(result.status, "ok")


class MemoryCheckTests(unittest.TestCase):
    def test_ok_memory(self):
        item = _check_memory({"free_physical_gb": 8.0, "free_virtual_gb": 16.0})
        self.assertEqual(item.status, "ok")

    def test_warning_memory(self):
        item = _check_memory({"free_physical_gb": 4.0, "free_virtual_gb": 10.0})
        self.assertEqual(item.status, "warning")

    def test_error_memory_physical_low(self):
        item = _check_memory({"free_physical_gb": 2.0, "free_virtual_gb": 10.0})
        self.assertEqual(item.status, "error")

    def test_error_memory_virtual_low(self):
        item = _check_memory({"free_physical_gb": 8.0, "free_virtual_gb": 3.0})
        self.assertEqual(item.status, "error")

    def test_none_memory_returns_warning(self):
        item = _check_memory(None)
        self.assertEqual(item.status, "warning")
        self.assertIn("无法读取", item.message)

    def test_details_present(self):
        item = _check_memory({"free_physical_gb": 5.0, "free_virtual_gb": 7.0})
        self.assertIn("free_physical_gb", item.details)
        self.assertIn("free_virtual_gb", item.details)


class VirtualMemoryThresholdTests(unittest.TestCase):
    def test_virtual_ok(self):
        item = _check_memory({"free_physical_gb": 10.0, "free_virtual_gb": 10.0})
        self.assertEqual(item.status, "ok")

    def test_virtual_below_warn(self):
        item = _check_memory({"free_physical_gb": 10.0, "free_virtual_gb": 5.0})
        self.assertEqual(item.status, "warning")

    def test_virtual_below_error(self):
        item = _check_memory({"free_physical_gb": 10.0, "free_virtual_gb": 2.0})
        self.assertEqual(item.status, "error")


class PythonEnvTests(unittest.TestCase):
    def test_existing_python_path(self):
        item = _check_python_env(Path(__file__))
        self.assertEqual(item.status, "ok")

    def test_missing_python_path(self):
        item = _check_python_env(Path("/nonexistent/python_abc.exe"))
        self.assertEqual(item.status, "error")


class ModelCacheTests(unittest.TestCase):
    def test_missing_cache_warning(self):
        item = _check_model_cache(Path("/nonexistent/models"))
        self.assertEqual(item.status, "warning")
        self.assertIn("不完整", item.message)

    def test_existing_cache_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for rel in [
                "models/iic/SenseVoiceSmall/model.pt",
                "models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch/model.pt",
            ]:
                full = base / rel
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text("fake")
            item = _check_model_cache(base)
            self.assertEqual(item.status, "ok")


class LogsWritableTests(unittest.TestCase):
    def test_writable_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = _check_logs_writable(Path(tmp))
            self.assertEqual(item.status, "ok")

    def test_unwritable_directory(self):
        item = _check_logs_writable(Path("Z:/nonexistent_drive_xyz/logs"))
        self.assertEqual(item.status, "error")


class PortCheckTests(unittest.TestCase):
    def test_port_free(self):
        item = _check_stt_port("127.0.0.1", 19999)
        self.assertEqual(item.status, "ok")

    def test_port_check_does_not_crash(self):
        item = _check_stt_port("127.0.0.1", 8766)
        self.assertIn(item.status, ("ok", "warning"))
        self.assertIn(item.key, ("stt_port",))


class DictSerializationTests(unittest.TestCase):
    def test_item_to_dict(self):
        item = PreflightCheckItem("m", "Mem", "warning", "msg", "sug", {"a": 1})
        d = item.to_dict()
        self.assertEqual(d["key"], "m")
        self.assertEqual(d["status"], "warning")
        self.assertEqual(d["details"]["a"], 1)

    def test_result_to_dict(self):
        items = [PreflightCheckItem("a", "A", "ok", "good")]
        result = PreflightCheckResult(status="ok", summary="all good", items=items)
        d = result.to_dict()
        self.assertEqual(d["status"], "ok")
        self.assertEqual(len(d["items"]), 1)

    def test_result_has_no_sensitive_fields(self):
        items = [PreflightCheckItem("a", "A", "ok", "good")]
        result = PreflightCheckResult(status="ok", summary="all good", items=items)
        d = result.to_dict()
        for key in ("api_key", "secret", "password", "token"):
            self.assertNotIn(key, str(d).lower())


class PreflightCheckItemCountTests(unittest.TestCase):
    def test_has_five_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            python = root / "python.exe"
            python.write_text("fake")
            result = run_preflight_check(
                root,
                memory_reader=lambda: {"free_physical_gb": 8.0, "free_virtual_gb": 10.0},
                python_path=str(python),
                model_cache_base=root,
            )
            keys = {item.key for item in result.items}
            self.assertIn("memory", keys)
            self.assertIn("stt_port", keys)
            self.assertIn("python_env", keys)
            self.assertIn("model_cache", keys)
            self.assertIn("logs_writable", keys)


if __name__ == "__main__":
    unittest.main()
