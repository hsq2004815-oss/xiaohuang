from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from xiaohuang.control_panel_web_service import ControlPanelWebApi, _fail, _ok, _sanitize_dict


class V13UAControlPanelWebApiTests(unittest.TestCase):
    """Tests for control_panel_web_service."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.config_path.write_text(
            json.dumps({"wake": {"engine": "stt_text", "phrases": ["小黄"]}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def test_ok_returns_ok_true_with_data(self):
        result = _ok(data={"test": 1}, message="done")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["test"], 1)
        self.assertEqual(result["message"], "done")

    def test_fail_returns_ok_false(self):
        result = _fail("something wrong", "test_code")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "something wrong")
        self.assertEqual(result["code"], "test_code")

    def test_sanitize_removes_sensitive_keys(self):
        d = {"api_key": "secret123", "name": "xiao", "secret": "hidden", "API_KEY_ENV": "env"}
        clean = _sanitize_dict(d)
        self.assertNotIn("api_key", clean)
        self.assertNotIn("secret", clean)
        self.assertNotIn("api_key_env", clean)
        self.assertIn("name", clean)

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def test_get_status_returns_ok_with_data(self):
        with patch(
            "xiaohuang.control_panel_web_service.build_status",
            return_value=_fake_status(),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.get_status()
            self.assertTrue(result["ok"])
            self.assertIn("data", result)
            self.assertIn("overall_status", result["data"])

    def test_get_status_exception_returns_fail(self):
        with patch(
            "xiaohuang.control_panel_web_service.build_status",
            side_effect=RuntimeError("crash"),
        ):
            api = ControlPanelWebApi(config_path="/nonexistent")
            result = api.get_status()
            self.assertFalse(result["ok"])
            self.assertIn("status_error", result["code"])

    # ------------------------------------------------------------------
    # save_wake_config
    # ------------------------------------------------------------------

    def test_save_wake_config_valid_payload(self):
        with patch(
            "xiaohuang.control_panel_web_service.save_wake_engine_config",
            return_value=_fake_save_result(True, None),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.save_wake_config({"engine": "openwakeword"})
            self.assertTrue(result["ok"])

    def test_save_wake_config_empty_engine_returns_fail(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.save_wake_config({"engine": ""})
        self.assertFalse(result["ok"])
        self.assertIn("validation", result["code"])

    def test_save_wake_config_missing_engine_returns_fail(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.save_wake_config({})
        self.assertFalse(result["ok"])
        self.assertIn("validation", result["code"])

    def test_save_wake_config_exception_returns_fail(self):
        with patch(
            "xiaohuang.control_panel_web_service.save_wake_engine_config",
            side_effect=OSError("permission denied"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.save_wake_config({"engine": "openwakeword"})
            self.assertFalse(result["ok"])
            self.assertIn("save_error", result["code"])

    # ------------------------------------------------------------------
    # start / stop / restart
    # ------------------------------------------------------------------

    def test_start_returns_ok(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_start_operation",
            return_value=_fake_op_result(True, "started"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.start_xiaohuang()
            self.assertTrue(result["ok"])

    def test_start_exception_returns_fail(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_start_operation",
            side_effect=OSError("failed"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.start_xiaohuang()
            self.assertFalse(result["ok"])
            self.assertIn("start_error", result["code"])

    def test_stop_returns_ok(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_stop_operation",
            return_value=_fake_op_result(True, "stopped"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.stop_xiaohuang()
            self.assertTrue(result["ok"])

    def test_restart_returns_ok(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_restart_operation",
            return_value=_fake_op_result(True, "restarted"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.restart_xiaohuang()
            self.assertTrue(result["ok"])

    def test_restart_exception_returns_fail(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_restart_operation",
            side_effect=OSError("failed"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.restart_xiaohuang()
            self.assertFalse(result["ok"])

    # ------------------------------------------------------------------
    # refresh / get_config_summary / log paths
    # ------------------------------------------------------------------

    def test_refresh_calls_get_status(self):
        with patch(
            "xiaohuang.control_panel_web_service.build_status",
            return_value=_fake_status(),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.refresh()
            self.assertTrue(result["ok"])

    def test_get_log_paths_returns_paths(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.get_log_paths()
        self.assertTrue(result["ok"])
        self.assertIn("logs_directory", result["data"])

    # ------------------------------------------------------------------
    # JSON serializable
    # ------------------------------------------------------------------

    def test_api_results_are_json_serializable(self):
        for result_fn in [_ok({"a": 1}), _fail("e", "c")]:
            json.dumps(result_fn)

    # ------------------------------------------------------------------
    # frontend files exist
    # ------------------------------------------------------------------

    def test_frontend_index_exists(self):
        import os
        root = Path(__file__).resolve().parents[1]
        index = root / "frontend" / "control_panel" / "index.html"
        self.assertTrue(index.exists(), f"Missing: {index}")

    def test_frontend_css_exists(self):
        root = Path(__file__).resolve().parents[1]
        css = root / "frontend" / "control_panel" / "assets" / "style.css"
        self.assertTrue(css.exists(), f"Missing: {css}")

    def test_frontend_js_exists(self):
        root = Path(__file__).resolve().parents[1]
        js = root / "frontend" / "control_panel" / "assets" / "app.js"
        self.assertTrue(js.exists(), f"Missing: {js}")


class V13UIFrontendStructureTests(unittest.TestCase):
    """Structural and content checks for redesigned frontend."""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def _read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_html_has_app_shell_layout(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("app-shell", html)
        self.assertIn("sidebar", html)
        self.assertIn("topbar", html)
        self.assertIn("main-workspace", html)
        self.assertIn("diagnostic-drawer", html)

    def test_html_has_glass_card_class(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("glass-card", html)

    def test_html_has_nav_sections(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("Overview", html)
        self.assertIn("Runtime", html)
        self.assertIn("Wake & Voice", html)
        self.assertIn("Models", html)
        self.assertIn("Tools", html)
        self.assertIn("Database", html)

    def test_html_no_project_template_keywords(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertNotIn("Create Project", html)
        self.assertNotIn("Invite", html)
        self.assertNotIn("Projects</", html)

    def test_html_references_local_assets(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn('href="assets/style.css"', html)
        self.assertIn('src="assets/app.js"', html)
        self.assertNotIn("cdn.", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_css_has_glass_tokens(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn("--glass-blur-md", css)
        self.assertIn("--fill-card", css)
        self.assertIn("--neon-ring", css)
        self.assertIn("--accent-blue", css)
        self.assertIn("--radius-card", css)

    def test_css_has_layout_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (".app-shell", ".sidebar", ".topbar", ".main-workspace", ".diagnostic-drawer"):
            self.assertIn(cls_name, css, f"Missing layout class: {cls_name}")

    def test_css_has_glass_component_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (".glass-card", ".glass-pill", ".glass-input", ".glass-toggle", ".glass-toast", ".status-badge", ".sidebar-item"):
            self.assertIn(cls_name, css, f"Missing component class: {cls_name}")

    def test_css_no_dark_theme_tokens(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertNotIn("--dark-fill", css)
        self.assertNotIn("--dark-neon-ring", css)
        self.assertNotIn("--dark-shadow-deep", css)
        self.assertNotIn("--dark-rim", css)

    def test_css_supports_reduced_motion(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn("prefers-reduced-motion", css)

    def test_js_has_pywebview_fallback(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("window.pywebview", js)
        self.assertIn("_mock", js)

    def test_js_no_external_url(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("http://", js)
        self.assertNotIn("https://", js)
        self.assertNotIn("cdn.", js)


def _fake_status():
    from xiaohuang.status_control_service import ControlPanelStatus
    return ControlPanelStatus(
        overall_status="READY",
        overall_message="系统就绪，可以说 小黄 唤醒",
        stt_running=True,
        stt_ready=True,
        stt_health_status="ready",
        stt_model_loaded=True,
        overlay_running=True,
        config_path="~/.xiaohuang/config.json",
        assistant_display_name="小黄",
        wake_phrases=["小黄"],
        llm_provider="deepseek",
        tts_enabled=True,
        last_operation=None,
        last_operation_elapsed_seconds=None,
        last_error=None,
        can_wake_now=True,
        wake_engine="stt_text",
        wake_engine_is_default=True,
        wake_fallback_enabled=True,
        wake_device_index=0,
        wake_cooldown_seconds=2.5,
        wake_sensitivity=0.5,
    )


def _fake_save_result(ok, error):
    from xiaohuang.status_control_service import WakeEngineConfigSaveResult
    return WakeEngineConfigSaveResult(ok=ok, message="", error=error)


def _fake_op_result(ok, message):
    from xiaohuang.status_control_service import ControlOperationResult
    return ControlOperationResult(ok=ok, title="", message=message, elapsed_seconds=1.0)
