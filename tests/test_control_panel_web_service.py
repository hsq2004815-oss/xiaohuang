from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xiaohuang.control_panel_web_service import (
    ControlPanelWebApi,
    _fail,
    _ok,
    _registry_blocked_result,
    _registry_failed_result,
    _registry_reason_text,
    _sanitize_dict,
)
from xiaohuang.text_interaction_models import TextInteractionResult


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
        ) as mock_build:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.get_status()
            self.assertTrue(result["ok"])
            self.assertIn("data", result)
            self.assertIn("overall_status", result["data"])
            # Verify build_status received project_root AND config_path
            self.assertEqual(mock_build.call_count, 1)
            args = mock_build.call_args[0]
            self.assertEqual(len(args), 2, "build_status needs 2 positional args")

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

    def test_start_calls_run_start_operation_with_correct_args(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_start_operation",
            return_value=_fake_op_result(True, "started"),
        ) as mock_start:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.start_xiaohuang()
            self.assertTrue(result["ok"])
            mock_start.assert_called_once()
            args = mock_start.call_args[0]
            self.assertGreater(len(args), 0, "run_start_operation needs project_root")

    def test_start_exception_returns_fail(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_start_operation",
            side_effect=OSError("failed"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.start_xiaohuang()
            self.assertFalse(result["ok"])
            self.assertIn("start_error", result["code"])

    def test_stop_calls_run_stop_operation(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_stop_operation",
            return_value=_fake_op_result(True, "stopped"),
        ) as mock_stop:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.stop_xiaohuang()
            self.assertTrue(result["ok"])
            mock_stop.assert_called_once()

    def test_restart_calls_run_restart_operation(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_restart_operation",
            return_value=_fake_op_result(True, "restarted"),
        ) as mock_restart:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.restart_xiaohuang()
            self.assertTrue(result["ok"])
            mock_restart.assert_called_once()

    def test_restart_exception_returns_fail(self):
        with patch(
            "xiaohuang.control_panel_web_service.run_restart_operation",
            side_effect=OSError("failed"),
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.restart_xiaohuang()
            self.assertFalse(result["ok"])

    def test_construct_with_none_config_path_does_not_crash(self):
        api = ControlPanelWebApi(config_path=None)
        self.assertIsNotNone(api._project_root)

    def test_construct_with_empty_config_path_does_not_crash(self):
        api = ControlPanelWebApi(config_path="")
        self.assertIsNotNone(api._project_root)

    def test_open_text_chat_window_returns_same_window_hint(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.open_text_chat_window()
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["same_window"])
        self.assertEqual(result["data"]["view"], "text-chat")

    def test_send_text_message_returns_data(self):
        fake = TextInteractionResult(
            ok=True,
            session_id="control_panel",
            user_text="介绍一下你自己",
            reply_text="我是小黄",
            reply_source="llm",
        )
        with patch("xiaohuang.control_panel_web_service.run_text_interaction_turn", return_value=fake) as mock_run:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.send_text_message({"text": "介绍一下你自己"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["reply_text"], "我是小黄")
        self.assertEqual(mock_run.call_args.kwargs["session_id"], "control_panel")

    def test_send_text_message_returns_pending_task_fields(self):
        fake = TextInteractionResult(
            ok=True,
            session_id="control_panel",
            user_text="帮我分析最近日志有没有错误",
            reply_text="这个任务需要你确认后才能执行。",
            reply_source="pending_task",
            requires_confirmation=True,
            pending_task=_pending_task("text-task-1"),
        )
        with patch("xiaohuang.control_panel_web_service.run_text_interaction_turn", return_value=fake):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.send_text_message({"text": "帮我分析最近日志有没有错误"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["requires_confirmation"])
        self.assertEqual(result["data"]["pending_task"]["task_type"], "readonly_log_analysis")
        self.assertTrue(result["data"]["pending_task"]["registered"])
        self.assertEqual(result["data"]["pending_task"]["registry_status"], "pending")
        self.assertIn("expires_at", result["data"]["pending_task"])
        self.assertIn("expires_in_seconds", result["data"]["pending_task"])
        json.dumps(result)

    def test_confirm_text_task_exists_and_completes_readonly_log_analysis(self):
        logs = Path(self.tmp.name) / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\nWARNING two\n", encoding="utf-8")
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task("text-task-1"))

        result = api.confirm_text_task({"task_id": "text-task-1"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(result["data"]["task_type"], "readonly_log_analysis")
        json.dumps(result)

    def test_confirm_text_task_blocks_disallowed_task(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-2",
            task_type="blocked_local_execution",
            risk_level="high",
            allowed=False,
        ))

        result = api.confirm_text_task({"task_id": "text-task-2"})

        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "blocked")
        self.assertEqual(result["data"]["error"], "blocked_task")
        json.dumps(result)

    def test_confirm_text_task_unknown_task_id_is_blocked(self):
        api = ControlPanelWebApi(config_path=self.config_path)

        result = api.confirm_text_task({"task_id": "missing-task"})

        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "blocked")
        self.assertEqual(result["data"]["error"], "not_found")
        json.dumps(result)

    def test_confirm_text_task_repeated_confirm_is_blocked(self):
        logs = Path(self.tmp.name) / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\n", encoding="utf-8")
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task("text-task-3"))

        first = api.confirm_text_task({"task_id": "text-task-3"})
        second = api.confirm_text_task({"task_id": "text-task-3"})

        self.assertTrue(first["data"]["ok"])
        self.assertFalse(second["data"]["ok"])
        self.assertEqual(second["data"]["status"], "blocked")
        self.assertEqual(second["data"]["error"], "already_completed")
        json.dumps(second)

    def test_confirm_text_task_does_not_execute_forged_pending_task(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.confirm_text_task({"pending_task": _pending_task("forged-task")})

        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "blocked")
        self.assertEqual(result["data"]["error"], "not_found")
        json.dumps(result)

    def test_confirm_text_task_exception_marks_failed(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task("text-task-x"))

        with patch(
            "xiaohuang.control_panel_web_service.execute_confirmed_text_task",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = api.confirm_text_task({"task_id": "text-task-x"})

        self.assertTrue(result["ok"])
        self.assertFalse(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "failed")
        self.assertEqual(result["data"]["error"], "confirm_text_task_error")
        self.assertEqual(api._text_task_registry.get("text-task-x").status, "failed")
        json.dumps(result)

    def test_confirm_text_task_exception_does_not_affect_normal_result(self):
        logs = Path(self.tmp.name) / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\n", encoding="utf-8")
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task("text-task-normal"))

        result = api.confirm_text_task({"task_id": "text-task-normal"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(api._text_task_registry.get("text-task-normal").status, "completed")

    def test_registry_reason_text_missing_task_id(self):
        result = api_call_confirm_blocked({}, "missing_task_id")
        self.assertIn("没有找到", result["data"]["summary"])
        self.assertIn("task_id", result["data"]["details"])

    def test_registry_reason_text_not_found(self):
        result = api_call_confirm_blocked({"task_id": "ghost-task"}, "not_found")
        self.assertIn("不存在", result["data"]["summary"])

    def test_registry_reason_text_expired(self):
        result = api_call_confirm_blocked({"task_id": "old-task"}, "expired")
        self.assertIn("已过期", result["data"]["summary"])

    def test_registry_reason_text_already_completed(self):
        result = api_call_confirm_blocked({"task_id": "done-task"}, "already_completed")
        self.assertIn("已经执行过", result["data"]["summary"])

    def test_registry_reason_text_already_cancelled(self):
        result = api_call_confirm_blocked({"task_id": "cancelled-task"}, "already_cancelled")
        self.assertIn("已经取消", result["data"]["summary"])

    def test_registry_reason_text_preserves_error_field(self):
        result = api_call_confirm_blocked({"task_id": "any-task"}, "not_pending")
        self.assertEqual(result["data"]["error"], "not_pending")
        self.assertEqual(result["data"]["status"], "blocked")

    def test_cancel_text_task_blocks_later_confirm(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task("text-task-4"))

        cancelled = api.cancel_text_task({"task_id": "text-task-4"})
        confirmed = api.confirm_text_task({"task_id": "text-task-4"})

        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["data"]["status"], "cancelled")
        self.assertTrue(confirmed["ok"])
        self.assertFalse(confirmed["data"]["ok"])
        self.assertEqual(confirmed["data"]["error"], "already_cancelled")
        json.dumps(cancelled)
        json.dumps(confirmed)

    def test_clear_text_session_returns_ok(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._text_interaction_sessions.get_or_create("control_panel").memory.add_user("测试")
        result = api.clear_text_session({"session_id": "control_panel"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["session_id"], "control_panel")
        self.assertEqual(len(api._text_interaction_sessions.get_or_create("control_panel").memory), 0)

    def test_new_task_type_runtime_events_review_full_flow(self):
        from xiaohuang.capabilities.runtime_events import service as es
        from xiaohuang.capabilities.runtime_events.service import record_event
        es._ring.clear()

        try:
            record_event("voice_overlay", "started", "test")

            api = ControlPanelWebApi(config_path=self.config_path)
            api._project_root = Path(self.tmp.name)
            api._text_task_registry.register(_pending_task(
                "text-task-events", task_type="readonly_runtime_events_review",
            ))

            result = api.confirm_text_task({"task_id": "text-task-events"})

            self.assertTrue(result["ok"])
            self.assertTrue(result["data"]["ok"])
            self.assertEqual(result["data"]["status"], "completed")
            self.assertEqual(result["data"]["task_type"], "readonly_runtime_events_review")
            self.assertIn("voice_overlay", result["data"]["details"])
            json.dumps(result)
        finally:
            es._ring.clear()

    def test_new_task_type_config_summary_uses_api_config_path(self):
        cfg = Path(self.tmp.name) / "xiao_config.json"
        cfg.write_text(
            '{"assistant":{"display_name":"小黄控制面板自定义"},'
            '"tts":{"voice":"zh-CN-YunxiNeural"}}',
            encoding="utf-8",
        )
        api = ControlPanelWebApi(config_path=cfg)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-cfg-path", task_type="readonly_config_summary",
        ))

        result = api.confirm_text_task({"task_id": "text-task-cfg-path"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertIn("小黄控制面板自定义", result["data"]["details"])

    def test_new_task_type_repeated_confirm_still_blocked(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-cfg", task_type="readonly_config_summary",
        ))

        first = api.confirm_text_task({"task_id": "text-task-cfg"})
        second = api.confirm_text_task({"task_id": "text-task-cfg"})

        self.assertTrue(first["data"]["ok"])
        self.assertFalse(second["data"]["ok"])
        self.assertEqual(second["data"]["error"], "already_completed")

    def test_clear_runtime_events_removes_events(self):
        from xiaohuang.capabilities.runtime_events import service as es
        from xiaohuang.capabilities.runtime_events.service import (
            get_recent_events,
            record_event,
        )
        es._ring.clear()

        try:
            record_event("control_panel", "test", "test message")
            before = len(es._ring)
            self.assertGreaterEqual(before, 1)

            api = ControlPanelWebApi(config_path=self.config_path)
            api._project_root = Path(self.tmp.name)
            result = api.clear_runtime_events({})

            self.assertTrue(result["ok"])
            self.assertGreaterEqual(result["data"]["removed"], 1)
            self.assertEqual(get_recent_events(20), [],
                             "Ring should be empty after clear — no residual event")
            json.dumps(result)
        finally:
            es._ring.clear()

    def test_clear_runtime_events_returns_ok(self):
        from xiaohuang.capabilities.runtime_events import service as es
        es._ring.clear()

        try:
            api = ControlPanelWebApi(config_path=self.config_path)
            api._project_root = Path(self.tmp.name)
            result = api.clear_runtime_events({})
            self.assertTrue(result["ok"])
            self.assertIn("removed", result["data"])
            json.dumps(result)
        finally:
            es._ring.clear()

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

    def test_html_has_localized_nav(self):
        html = self._read("frontend/control_panel/index.html")
        for text in ("首页", "对话", "任务", "工具", "诊断", "设置"):
            self.assertIn(text, html, f"Missing localized text: {text}")
        self.assertIn("文本对话", html, "Top text chat entry should remain")
        self.assertIn('id="btn-sidebar-toggle"', html)
        for section in ("home", "chat", "tasks", "tools", "diagnostics", "settings"):
            self.assertIn(f'data-section="{section}"', html, f"Missing app shell nav section: {section}")
        for old_section in ("overview", "runtime", "wake", "models", "automation", "database", "logs", "developer", "text-chat"):
            self.assertNotIn(f'data-section="{old_section}"', html, f"Old sidebar section should be removed: {old_section}")

    def test_html_no_english_nav_labels(self):
        html = self._read("frontend/control_panel/index.html")
        for text in ("Overview</", "Runtime</", "Wake &amp; Voice</", "Diagnostics</", "Quick Actions</", "Wake Engine Settings</", "Recent Events</"):
            self.assertNotIn(text, html, f"English label should be removed: {text}")
        self.assertNotIn(">Overview<", html)
        self.assertNotIn(">Runtime<", html)
        self.assertNotIn(">Core<", html)
        self.assertNotIn(">Capabilities<", html)
        self.assertNotIn(">System<", html)

    def test_html_has_localized_main_content(self):
        html = self._read("frontend/control_panel/index.html")
        for text in ("小黄控制中心", "快速操作", "唤醒与语音设置", "最近事件", "诊断信息",
                     "配置文件", "日志目录", "最近错误", "最近操作", "操作历史",
                     "兜底唤醒", "冷却时间", "灵敏度", "保存配置", "保存并重启",
                     "任务中心", "视频下载", "PDF 解析", "网页爬取", "安全设置"):
            self.assertIn(text, html, f"Missing localized content: {text}")

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
        for cls_name in (".app-shell", ".sidebar", ".topbar", ".main-workspace", ".diagnostic-drawer",
                         ".page-heading", ".task-status-grid", ".tool-grid", ".settings-grid"):
            self.assertIn(cls_name, css, f"Missing layout class: {cls_name}")

    def test_css_has_glass_component_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (".glass-card", ".glass-pill", ".glass-input", ".glass-toggle", ".glass-toast", ".status-badge", ".sidebar-item"):
            self.assertIn(cls_name, css, f"Missing component class: {cls_name}")
        for state in (".glass-pill:hover", ".glass-pill:active", ".glass-pill:focus-visible", ".glass-pill.is-loading"):
            self.assertIn(state, css, f"Missing button feedback state: {state}")

    def test_css_has_text_task_confirmation_card_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (".text-task-card", ".text-task-risk", ".text-task-actions",
                         ".text-task-confirm", ".text-task-cancel",
                         ".text-task-card.blocked", ".text-task-card.confirmed", ".text-task-card.cancelled",
                         ".text-task-card.executing", ".text-task-card.completed", ".text-task-card.failed",
                         ".text-task-original", ".text-task-original-label", ".text-task-original-text"):
            self.assertIn(cls_name, css, f"Missing text task confirmation class: {cls_name}")

    def test_css_has_text_task_result_card_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (".text-task-result-card", ".text-task-result-card.completed",
                         ".text-task-result-card.blocked", ".text-task-result-card.failed",
                         ".text-task-result-details", ".text-task-result-files",
                         ".text-task-result-error"):
            self.assertIn(cls_name, css, f"Missing text task result class: {cls_name}")

    def test_css_no_dark_theme_tokens(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertNotIn("--dark-fill", css)
        self.assertNotIn("--dark-neon-ring", css)
        self.assertNotIn("--dark-shadow-deep", css)
        self.assertNotIn("--dark-rim", css)

    def test_css_supports_reduced_motion(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn("prefers-reduced-motion", css)

    def test_js_has_pywebviewready_listener(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("pywebviewready", js)

    def test_js_has_bridge_status(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("drawer-bridge-status", js)
        self.assertIn("已连接", js)

    def test_html_has_data_action_buttons(self):
        html = self._read("frontend/control_panel/index.html")
        for action in ("data-action=\"start\"", "data-action=\"stop\"", "data-action=\"restart\"",
                       "data-action=\"refresh\"", "data-action=\"open-text-chat\"",
                       "data-action=\"open-diagnostics\"",
                       "data-action=\"save-config\"", "data-action=\"save-restart\""):
            self.assertIn(action, html, f"Missing data-action: {action}")

    def test_html_has_chat_page(self):
        html = self._read("frontend/control_panel/index.html")
        for text in ("control-shell", "section-chat", "text-chat-messages",
                     "text-chat-input", "text-chat-send", "text-chat-workspace"):
            self.assertIn(text, html, f"Missing chat page element: {text}")
        self.assertNotIn('id="section-text-chat"', html)
        self.assertNotIn('id="text-chat-shell"', html)

    def test_css_has_no_legacy_text_chat_shell(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertNotIn("text-chat-shell", css)
        self.assertNotIn("mode-text-chat", css)

    def test_app_shell_scopes_context_panel_to_home(self):
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn("function updateShellLayoutForSection", js)
        self.assertIn("section === 'home'", js)
        self.assertIn("document.body.classList.toggle('home-page'", js)
        self.assertIn("document.body.classList.toggle('non-home-page'", js)
        self.assertIn("document.body.classList.toggle('drawer-page'", js)
        self.assertIn("document.body.classList.toggle('no-drawer-page'", js)
        self.assertIn("updateShellLayoutForSection(currentSection)", js)
        self.assertIn("body.non-home-page .diagnostic-drawer", css)
        self.assertIn("body.non-home-page .drawer-rail", css)
        self.assertIn("body.non-home-page .drawer-toggle", css)
        self.assertIn("body.no-drawer-page .diagnostic-drawer", css)
        self.assertIn("body.no-drawer-page .drawer-rail", css)
        self.assertIn("grid-template-areas:\"topbar topbar\" \"sidebar main\"", css)

    def test_top_diagnostics_button_opens_diagnostics_page(self):
        html = self._read("frontend/control_panel/index.html")
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn('id="btn-diagnostics-entry"', html)
        self.assertIn('data-action="open-diagnostics"', html)
        self.assertNotIn('id="btn-drawer-toggle"', html)
        self.assertIn("if (action === 'open-diagnostics') { doOpenDiagnostics(); return; }", js)
        self.assertIn("switchSection('diagnostics')", js)

    def test_chat_layout_has_no_right_workspace_column(self):
        html = self._read("frontend/control_panel/index.html")
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertLess(html.index('class="text-chat-main'), html.index('class="text-chat-sessions'))
        self.assertIn(".text-chat-workspace{display:none}", css)
        self.assertIn("#section-chat .text-chat-workspace{display:none!important}", css)
        self.assertIn("grid-template-columns:minmax(0,1fr) minmax(250px,300px)", css)

    def test_chat_layout_has_internal_scroll_container(self):
        css = self._read("frontend/control_panel/assets/style.css")
        js = self._read("frontend/control_panel/assets/app.js")
        for text in (
            "#section-chat.content-section.active",
            "body.chat-page .main-workspace{overflow:hidden}",
            "#section-chat .text-chat-layout",
            "#section-chat .text-chat-main",
            "#section-chat .text-chat-messages",
            "overscroll-behavior:contain",
            "grid-template-rows:minmax(0,1fr) auto",
        ):
            self.assertIn(text, css, f"Missing chat scroll layout rule: {text}")
        self.assertIn("function scrollTextChatToBottom", js)
        self.assertIn("messages.scrollTop = messages.scrollHeight", js)

    def test_chat_surface_has_compact_polish_rules(self):
        html = self._read("frontend/control_panel/index.html")
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn("直接和小黄对话，任务确认和结果会显示在这里。", html)
        self.assertIn("你好，我是小黄。直接输入消息，我会在这里回复。", js)
        for text in (
            "/* ─── Minimal Chat Polish ─── */",
            "#section-chat .text-chat-header",
            "min-height:44px",
            "#section-chat .text-chat-status",
            "#section-chat .text-chat-message.assistant:first-child .text-chat-bubble",
            "#section-chat .text-chat-input-row{grid-template-columns:minmax(0,1fr) auto}",
            "#section-chat .text-chat-model{display:none}",
            "body.chat-page .main-workspace{padding-top:clamp(12px,1.8vh,18px)}",
        ):
            self.assertIn(text, css, f"Missing compact chat polish rule: {text}")

    def test_user_chat_message_uses_dark_text(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn(".text-chat-message.user .text-chat-bubble", css)
        self.assertIn("color:var(--text-primary)", css)
        self.assertNotIn(".text-chat-message.user .text-chat-bubble{\n  color:#fff", css)

    def test_chat_focus_mode_removes_header_chrome(self):
        html = self._read("frontend/control_panel/index.html")
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn('<header class="topbar glass-card" id="topbar">', html)
        for text in (
            "/* ─── Chat Focus Mode ─── */",
            "body.chat-page .topbar",
            "display:none!important",
            "body.chat-page .app-shell",
            "grid-template-rows:minmax(0,1fr)",
            'grid-template-areas:"sidebar main"',
            "body.chat-page.sidebar-collapsed .app-shell",
            "grid-template-columns:var(--sidebar-collapsed-w) minmax(0,1fr)",
            "body.chat-page #section-chat .text-chat-header",
            "body.chat-page #section-chat .text-chat-layout",
        ):
            self.assertIn(text, css, f"Missing chat focus mode rule: {text}")

    def test_sidebar_has_collapsible_state(self):
        html = self._read("frontend/control_panel/index.html")
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        for text in (
            "SIDEBAR_STORAGE_KEY",
            "xiaohuang.controlPanel.sidebarCollapsed",
            "function toggleSidebarCollapsed",
            "function applySidebarCollapsedState",
            "document.body.classList.toggle('sidebar-collapsed'",
            "safeLocalStorageSet(SIDEBAR_STORAGE_KEY",
            "initSidebarControls()",
        ):
            self.assertIn(text, js, f"Missing sidebar collapse logic: {text}")
        for text in (
            "--sidebar-collapsed-w",
            "body.sidebar-collapsed .app-shell",
            "body.sidebar-collapsed.non-home-page .app-shell",
            "body.sidebar-collapsed .sidebar-text{display:none}",
            ".sidebar-collapse-btn",
        ):
            self.assertIn(text, css, f"Missing sidebar collapse style: {text}")
        self.assertIn('class="sidebar-collapse-btn"', html)

    def test_html_has_bridge_indicator(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("桌面桥接", html)
        self.assertIn("drawer-bridge-status", html)

    def test_js_has_chinese_status_text(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("运行中", "已停止", "已就绪", "未检测到", "加载中", "未知"):
            self.assertIn(text, js, f"Missing Chinese status text: {text}")

    def test_js_has_data_action_handling(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("data-action", js)
        self.assertIn("handleButtonClick", js)
        self.assertIn("switchSection('chat')", js)
        self.assertIn("send_text_message", js)
        self.assertIn("clear_text_session", js)
        self.assertNotIn("apiCall('open_text_chat_window'", js)

    def test_js_renders_text_task_confirmation_cards_without_execution_api(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("requires_confirmation", "pending_task", "renderPendingTaskCard",
                     "handlePendingTaskConfirm", "handlePendingTaskCancel",
                     "data-task-action", "确认执行", "不处理",
                     "已取消该任务。",
                     "risk_level", "original_text", "task.risk_level || task.risk", "原始输入",
                     "confirm_text_task", "cancel_text_task", "task_id: msg.pendingTask.task_id",
                     "任务已注册", "expires_in_seconds", "executing", "completed", "failed"):
            self.assertIn(text, js, f"Missing text task confirmation UI behavior: {text}")
        self.assertNotIn("apiCall('confirm_text_task', { pending_task:", js)
        self.assertNotIn("execute_text_task", js)
        self.assertNotIn("local_commands", js)

    def test_js_renders_text_task_execution_result_cards(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("normalizeTextTaskExecutionResult", "renderTextTaskExecutionResultCard",
                     "getExecutionStatusLabel", "getExecutionStatusClass", "splitExecutionDetails",
                     "executionResult", "text_task_execution", "completed", "blocked", "failed",
                     "read_files", "details", "任务执行完成", "任务已拦截", "任务执行失败"):
            self.assertIn(text, js, f"Missing text task execution result UI behavior: {text}")
        self.assertIn("appendTextChatMessage('assistant', '',", js)
        self.assertNotIn("execute_text_task", js)
        self.assertNotIn("local_commands", js)

    def test_js_has_immediate_feedback(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("setButtonLoading", js)
        self.assertIn("正在启动", js)

    def test_js_has_finally_restore(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn(".finally", js)

    def test_js_has_action_api_calls(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for method in ("start_xiaohuang", "stop_xiaohuang", "restart_xiaohuang"):
            self.assertIn(method, js, f"Missing API call: {method}")

    def test_js_has_button_recovery(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("启动小黄", js)

    def test_js_no_external_url(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("http://", js)
        self.assertNotIn("https://", js)
        self.assertNotIn("cdn.", js)

    def test_js_has_format_task_expiry_label(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("formatTaskExpiryLabel", "约", "分钟内有效", "expires_at", "expires_in_seconds"):
            self.assertIn(text, js, f"Missing formatTaskExpiryLabel behavior: {text}")

    def test_js_expiry_no_longer_hardcodes_300_seconds(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("300 秒内有效", js, "No longer hardcode 300 seconds expiry label")

    def test_js_has_compact_runtime_event_text(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("compactRuntimeEventText", "Traceback", "出现异常"):
            self.assertIn(text, js, f"Missing compact runtime event text: {text}")

    def test_js_has_clear_runtime_events_api(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("clear_runtime_events", "handleClearRuntimeEvents",
                     "clear-runtime-events", "refreshRuntimeEvents"):
            self.assertIn(text, js, f"Missing clear runtime events: {text}")

    def test_js_runtime_event_summary_is_escape_htmled(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(summary)", js,
                      "runtime event summary must be HTML-escaped")

    def test_html_has_clear_runtime_events_button(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("data-action=\"clear-runtime-events\"", html)
        self.assertIn("清空事件", html)


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


def _pending_task(task_id, task_type="readonly_log_analysis", risk_level="low", allowed=True):
    return {
        "task_id": task_id,
        "title": "分析最近日志错误" if allowed else "受限本地执行请求",
        "task_type": task_type,
        "summary": "读取项目 logs 目录中的最近日志并总结错误信息。",
        "risk_level": risk_level,
        "status": "pending_confirmation",
        "allowed": allowed,
        "original_text": "帮我分析最近日志有没有错误",
        "reason": "" if allowed else "文本入口当前不允许执行本地命令或操作外部应用。",
    }


def _fake_save_result(ok, error):
    from xiaohuang.status_control_service import WakeEngineConfigSaveResult
    return WakeEngineConfigSaveResult(ok=ok, message="", error=error)


def _fake_op_result(ok, message):
    from xiaohuang.status_control_service import ControlOperationResult
    return ControlOperationResult(ok=ok, title="", message=message, elapsed_seconds=1.0)


def api_call_confirm_blocked(payload, reason):
    """Helper: call _registry_blocked_result directly to test reason text mapping."""
    return {
        "ok": True,
        "data": _registry_blocked_result(
            payload.get("task_id", ""),
            reason,
        ),
        "message": "文本任务已拦截",
    }
