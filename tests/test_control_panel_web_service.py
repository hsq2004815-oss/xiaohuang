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

    def test_get_multica_status_success_returns_data(self):
        from xiaohuang.multica_integration.models import MulticaStatus

        status = MulticaStatus(
            ok=True,
            installed=True,
            version="multica 0.2.16",
            daemon_running=True,
            daemon_summary="running",
            agents=("claude", "codex"),
            workspace_summary="hhh-ai-lab",
        )
        with patch(
            "xiaohuang.multica_integration.status_service.get_multica_status",
            return_value=status,
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.get_multica_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["version"], "multica 0.2.16")
        self.assertEqual(result["data"]["agents"], ["claude", "codex"])

    def test_get_multica_status_failure_returns_structured_error(self):
        from xiaohuang.multica_integration.models import MulticaStatus

        status = MulticaStatus(
            ok=False,
            installed=False,
            error_code="multica_not_found",
            message="未找到 multica CLI。",
        )
        with patch(
            "xiaohuang.multica_integration.status_service.get_multica_status",
            return_value=status,
        ):
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.get_multica_status()

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "multica_not_found")
        self.assertIn("未找到", result["error"])

    def test_build_multica_issue_draft_success_returns_data(self):
        from xiaohuang.multica_integration.models import MulticaIssueDraft

        draft = MulticaIssueDraft(
            ok=True,
            title="做页面",
            description="desc",
            target_project_path="E:\\Projects\\sample-project",
            suggested_assignees=("claude", "codex"),
            default_assignee="claude",
            create_command_preview="multica issue create --title '做页面'",
            markdown="# Multica Issue Draft",
            warnings=("仅草稿，未创建 Multica issue，未分配 Agent。",),
            message="done",
        )
        with patch(
            "xiaohuang.multica_integration.issue_draft_service.build_issue_draft_from_handoff",
            return_value=draft,
        ) as mock_build:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.build_multica_issue_draft({
                "handoff_title": "做页面",
                "handoff_prompt": "prompt",
                "target_project_path": "E:\\Projects\\sample-project",
                "related_domains": ["ui_design"],
                "preferred_agent": "claude",
            })

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["title"], "做页面")
        self.assertEqual(result["data"]["suggested_assignees"], ["claude", "codex"])
        self.assertEqual(mock_build.call_args.kwargs["related_domains"], ("ui_design",))

    def test_build_multica_issue_draft_missing_prompt_returns_error(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.build_multica_issue_draft({
            "handoff_title": "做页面",
            "handoff_prompt": "",
            "target_project_path": "E:\\Projects\\sample-project",
        })

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "missing_handoff_prompt")

    def test_create_multica_issue_from_draft_requires_confirmation(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.create_multica_issue_from_draft({
            "title": "C5E test",
            "description": "desc",
            "confirmed": False,
            "confirmation_text": "",
        })

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "confirmation_required")
        self.assertIn("二次确认", result["error"])

    def test_create_multica_issue_from_draft_success_returns_data(self):
        from xiaohuang.multica_integration.models import MulticaIssueCreateResult

        create_result = MulticaIssueCreateResult(
            ok=True,
            created=True,
            issue_id="iss_123",
            identifier="HHH-19",
            title="C5E test",
            status="todo",
            warnings=("未分配 Agent",),
            message="Multica issue 已创建；未分配 Agent。",
        )
        with patch(
            "xiaohuang.multica_integration.issue_create_service.create_issue_from_draft",
            return_value=create_result,
        ) as mock_create:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.create_multica_issue_from_draft({
                "title": "C5E test",
                "description": "desc",
                "confirmed": True,
                "confirmation_text": "CREATE_MULTICA_ISSUE",
            })

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["created"])
        self.assertEqual(result["data"]["issue_id"], "iss_123")
        self.assertEqual(result["data"]["identifier"], "HHH-19")
        self.assertEqual(mock_create.call_args.kwargs["confirmation_text"], "CREATE_MULTICA_ISSUE")

    def test_assign_multica_issue_to_agent_requires_confirmation(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.assign_multica_issue_to_agent({
            "issue_id": "4e344c98",
            "agent": "claude",
            "confirmed": False,
            "confirmation_text": "",
        })

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "confirmation_required")
        self.assertIn("二次确认", result["error"])

    def test_assign_multica_issue_to_agent_rejects_invalid_agent(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        result = api.assign_multica_issue_to_agent({
            "issue_id": "4e344c98",
            "agent": "powershell",
            "confirmed": True,
            "confirmation_text": "ASSIGN 4e344c98 TO powershell",
        })

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unsupported_agent")

    def test_assign_multica_issue_to_agent_success_returns_data(self):
        from xiaohuang.multica_integration.models import MulticaIssueAssignResult

        assign_result = MulticaIssueAssignResult(
            ok=True,
            assigned=True,
            issue_id="4e344c98",
            agent="claude",
            status="todo",
            warnings=("小黄没有执行 run/rerun/runs/run-messages。",),
            message="Multica issue 已分配给 claude。",
        )
        with patch(
            "xiaohuang.multica_integration.issue_assign_service.assign_issue_to_agent",
            return_value=assign_result,
        ) as mock_assign:
            api = ControlPanelWebApi(config_path=self.config_path)
            result = api.assign_multica_issue_to_agent({
                "issue_id": "4e344c98",
                "agent": "claude",
                "confirmed": True,
                "confirmation_text": "ASSIGN 4e344c98 TO claude",
            })

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["assigned"])
        self.assertEqual(result["data"]["issue_id"], "4e344c98")
        self.assertEqual(result["data"]["agent"], "claude")
        self.assertEqual(mock_assign.call_args.kwargs["confirmation_text"], "ASSIGN 4e344c98 TO claude")

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

    def test_health_report_full_flow(self):
        (Path(self.tmp.name) / "src" / "xiaohuang").mkdir(parents=True, exist_ok=True)
        (Path(self.tmp.name) / "scripts").mkdir(parents=True, exist_ok=True)
        (Path(self.tmp.name) / "scripts" / "control_panel_web.py").write_text("", encoding="utf-8")
        (Path(self.tmp.name) / "scripts" / "voice_overlay.py").write_text("", encoding="utf-8")
        (Path(self.tmp.name) / "frontend" / "control_panel").mkdir(parents=True, exist_ok=True)

        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-health", task_type="readonly_health_report",
        ))

        result = api.confirm_text_task({"task_id": "text-task-health"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertEqual(result["data"]["task_type"], "readonly_health_report")
        self.assertIn("总体状态", result["data"]["summary"])
        json.dumps(result)

    def test_confirm_task_writes_task_history_jsonl(self):
        from xiaohuang.task_result_history_service import (
            _reset_for_test,
            get_task_history_path,
        )
        _reset_for_test()

        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-hist", task_type="readonly_health_report",
        ))

        result = api.confirm_text_task({"task_id": "text-task-hist"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])

        jsonl_path = get_task_history_path(api._project_root)
        self.assertTrue(jsonl_path.is_file(), f"Expected {jsonl_path} to exist")

        text = jsonl_path.read_text(encoding="utf-8")
        entry = json.loads(text.strip())
        self.assertEqual(entry["task_type"], "readonly_health_report")
        self.assertEqual(entry["status"], "completed")
        self.assertTrue(entry["ok"])
        self.assertIn("summary", entry)
        self.assertIn("safe_details_excerpt", entry)
        _reset_for_test()

    def test_confirm_agent_handoff_task_generates_file_and_history(self):
        from xiaohuang.task_result_history_service import (
            _reset_for_test,
            get_task_history_path,
        )
        _reset_for_test()

        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        task = _pending_task("text-task-handoff", task_type="agent_handoff_draft")
        task["title"] = "生成 Agent 交接提示词"
        task["original_text"] = "给 Claude Code 生成提示词，让它继续优化小黄任务历史页面"
        api._text_task_registry.register(task)

        with patch(
            "xiaohuang.agent_handoff.service.fetch_database_brief",
            return_value=_brief_result(False, "unavailable"),
        ):
            result = api.confirm_text_task({"task_id": "text-task-handoff"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertEqual(result["data"]["task_type"], "agent_handoff_draft")
        self.assertIn("runtime/agent_handoffs/", result["data"]["details"])
        self.assertTrue((api._project_root / "runtime" / "agent_handoffs").is_dir())

        jsonl_path = get_task_history_path(api._project_root)
        entry = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["task_type"], "agent_handoff_draft")
        self.assertEqual(entry["result_kind"], "agent_handoff")
        self.assertIn("claude_code", entry["tags"])
        _reset_for_test()

    def test_confirm_agent_handoff_external_path_boundary_not_xiaohuang(self):
        from xiaohuang.task_result_history_service import _reset_for_test
        _reset_for_test()

        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        task = _pending_task("text-task-external-handoff", task_type="agent_handoff_draft")
        task["title"] = "生成 Agent 交接提示词"
        task["original_text"] = (
            '给 Claude Code 生成提示词，让它在 "E:\\Projects\\target-app" 里做一次 C5E smoke test，'
            "只创建说明文档草稿，不修改小黄项目，不启动任何 Agent。"
        )
        api._text_task_registry.register(task)

        with patch(
            "xiaohuang.agent_handoff.service.fetch_database_brief",
            return_value=_brief_result(False, "unavailable"),
        ):
            result = api.confirm_text_task({"task_id": "text-task-external-handoff"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertIn("目标项目路径：E:\\Projects\\target-app", result["data"]["details"])
        self.assertIn("目标项目类型：external_existing", result["data"]["details"])
        self.assertIn("与小黄项目关系：unrelated_to_xiaohuang", result["data"]["details"])
        self.assertNotIn("目标项目类型：xiaohuang", result["data"]["details"])
        self.assertNotIn("与小黄项目关系：xiaohuang_project", result["data"]["details"])
        _reset_for_test()

    def test_agent_completion_review_chat_confirm_flow_writes_history(self):
        from xiaohuang.task_result_history_service import (
            _reset_for_test,
            get_task_history_path,
        )
        _reset_for_test()

        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        sent = api.send_text_message({"text": _agent_completion_report()})
        self.assertTrue(sent["ok"])
        self.assertTrue(sent["data"]["requires_confirmation"])
        pending = sent["data"]["pending_task"]
        self.assertEqual(pending["task_type"], "agent_completion_review")
        self.assertEqual(pending["title"], "审查 Agent 完成报告")

        result = api.confirm_text_task({"task_id": pending["task_id"]})
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertEqual(result["data"]["task_type"], "agent_completion_review")
        self.assertIn("验收结论", result["data"]["details"])
        self.assertIn("commit：5dfce798f2e37e91ba7316004e72d4ccdfb8c485", result["data"]["details"])

        jsonl_path = get_task_history_path(api._project_root)
        entry = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["task_type"], "agent_completion_review")
        self.assertEqual(entry["result_kind"], "agent_review")
        self.assertIn("agent", entry["tags"])
        self.assertIn("review", entry["tags"])
        self.assertNotIn("完成：V1.5-C1.3", entry["safe_details_excerpt"])
        _reset_for_test()

    def test_read_agent_handoff_file_returns_content(self):
        from xiaohuang.agent_handoff.handoff_file_service import (
            relative_handoff_path,
            write_handoff_file,
        )

        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        path = write_handoff_file(
            project_root=api._project_root,
            target_agent="codex",
            user_request="copy",
            content="完整 handoff 内容",
        )

        result = api.read_agent_handoff_file({"path": relative_handoff_path(path, api._project_root)})

        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "完整 handoff 内容")
        self.assertIn("runtime/agent_handoffs/", result["path"])

    def test_read_agent_handoff_file_rejects_missing_path(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.read_agent_handoff_file({"path": ""})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing handoff path")

    def test_read_agent_handoff_file_rejects_escape_path(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.read_agent_handoff_file({"path": "runtime/agent_handoffs/../secret.txt"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "handoff path is not allowed")

    def test_read_agent_handoff_file_missing_file(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.read_agent_handoff_file({"path": "runtime/agent_handoffs/missing.txt"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "handoff file not found")

    def test_open_agent_handoff_terminal_uses_target_path(self):
        from xiaohuang.agent_handoff.terminal_launcher import TerminalOpenResult

        api = ControlPanelWebApi(config_path=self.config_path)
        target_path = str(Path(self.tmp.name))

        with patch(
            "xiaohuang.agent_handoff.terminal_launcher.open_target_project_terminal",
            return_value=TerminalOpenResult(True, "已向系统请求打开目标项目终端。", target_path),
        ) as launcher:
            result = api.open_agent_handoff_terminal({"target_project_path": target_path})

        self.assertTrue(result["ok"])
        self.assertIn("已向系统请求打开", result["message"])
        self.assertEqual(result["data"]["target_project_path"], target_path)
        launcher.assert_called_once_with(target_path)

    def test_open_agent_handoff_terminal_rejects_missing_path(self):
        api = ControlPanelWebApi(config_path=self.config_path)

        result = api.open_agent_handoff_terminal({"target_project_path": ""})

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "missing_target_project_path")
        self.assertIn("目标项目路径未指定", result["error"])

    def test_open_agent_handoff_terminal_rejects_nonexistent_path_without_fallback(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        missing = str(Path(self.tmp.name) / "missing-project")

        result = api.open_agent_handoff_terminal({"target_project_path": missing})

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "target_project_path_not_found")
        self.assertEqual(result["data"]["target_project_path"], missing)
        self.assertIn("不能回退到小黄项目", result["error"])

    def test_confirm_task_history_append_failure_does_not_affect_result(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-append-fail", task_type="readonly_health_report",
        ))

        with patch(
            "xiaohuang.task_result_history_service.append_task_result",
            side_effect=OSError("disk full"),
        ):
            result = api.confirm_text_task({"task_id": "text-task-append-fail"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["ok"])
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(result["data"]["task_type"], "readonly_health_report")
        json.dumps(result)

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

    # ------------------------------------------------------------------
    # module boundary: task history must not leak file I/O into other modules
    # ------------------------------------------------------------------

    def test_control_panel_web_service_does_not_open_task_results_jsonl(self):
        src = Path(__file__).resolve().parents[1] / "src" / "xiaohuang" / "control_panel_web_service.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("task_results.jsonl", text,
                         "control_panel_web_service.py must not reference task_results.jsonl directly")

    def test_text_task_execution_service_does_not_contain_task_results_jsonl(self):
        src = Path(__file__).resolve().parents[1] / "src" / "xiaohuang" / "text_task_execution_service.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("task_results.jsonl", text,
                         "text_task_execution_service.py must not reference task_results.jsonl")

    def test_text_task_execution_service_does_not_import_task_result_history(self):
        src = Path(__file__).resolve().parents[1] / "src" / "xiaohuang" / "text_task_execution_service.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("task_result_history_service", text,
                         "text_task_execution_service.py must not import task_result_history_service")

    # ------------------------------------------------------------------
    # get_recent_task_history API (B1.1)
    # ------------------------------------------------------------------

    def test_get_recent_task_history_returns_items(self):
        from xiaohuang.task_result_history_service import _reset_for_test
        _reset_for_test()

        logs = Path(self.tmp.name) / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\n", encoding="utf-8")
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-hist-api", task_type="readonly_health_report",
        ))
        api.confirm_text_task({"task_id": "text-task-hist-api"})

        result = api.get_recent_task_history({"limit": 5})
        self.assertTrue(result["ok"])
        items = result["data"]["items"]
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first["task_type"], "readonly_health_report")
        self.assertIn("summary", first)
        self.assertIn("safe_details_excerpt", first)
        json.dumps(result)
        _reset_for_test()

    def test_get_recent_task_history_empty_on_new_root(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name) / "nonexistent"

        result = api.get_recent_task_history({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["items"], [])
        json.dumps(result)

    def test_get_recent_task_history_limit_clamped(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.get_recent_task_history({"limit": 999})
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"]["items"], list)
        json.dumps(result)

    def test_get_recent_task_history_negative_limit_safe(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.get_recent_task_history({"limit": -1})
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"]["items"], list)
        json.dumps(result)

    def test_get_recent_task_history_string_limit_safe(self):
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)

        result = api.get_recent_task_history({"limit": "abc"})
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"]["items"], list)
        json.dumps(result)

    def test_get_recent_task_history_no_leak_path(self):
        from xiaohuang.task_result_history_service import _reset_for_test
        _reset_for_test()

        logs = Path(self.tmp.name) / "logs"
        logs.mkdir()
        (logs / "app.log").write_text("ERROR one\n", encoding="utf-8")
        api = ControlPanelWebApi(config_path=self.config_path)
        api._project_root = Path(self.tmp.name)
        api._text_task_registry.register(_pending_task(
            "text-task-no-leak", task_type="readonly_health_report",
        ))
        api.confirm_text_task({"task_id": "text-task-no-leak"})

        result = api.get_recent_task_history({"limit": 5})
        result_json = json.dumps(result)
        self.assertNotIn("task_results.jsonl", result_json,
                         "API response must not leak internal file paths")
        self.assertNotIn("data/task_history", result_json,
                         "API response must not leak internal dir paths")
        _reset_for_test()


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
                     "任务历史", "视频下载", "PDF 解析", "网页爬取", "安全设置"):
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

    def test_multica_status_panel_static_assets(self):
        html = self._read("frontend/control_panel/index.html")
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        for text in (
            "Multica 状态",
            "刷新 Multica 状态",
            "multica-installed",
            "multica-version",
            "multica-daemon",
            "multica-agents",
            "multica-workspace",
        ):
            self.assertIn(text, html)
        for text in (
            "get_multica_status",
            "renderMulticaStatus",
            "doRefreshMulticaStatus",
            "refresh-multica-status",
        ):
            self.assertIn(text, js)
        self.assertIn(".multica-status-card", css)
        self.assertNotIn("apiCall('multica issue", js)
        self.assertNotIn("apiCall(\"multica issue", js)
        self.assertNotIn("issue assign", js.lower())

    def test_control_panel_web_service_has_no_direct_subprocess_use_for_multica(self):
        source = self._read("src/xiaohuang/control_panel_web_service.py")
        self.assertIn("xiaohuang.multica_integration.status_service", source)
        self.assertIn("xiaohuang.multica_integration.issue_create_service", source)
        self.assertIn("xiaohuang.multica_integration.issue_assign_service", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("cli_client", source)
        self.assertNotIn("multica issue", source)

    def test_multica_issue_draft_static_assets(self):
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        for text in (
            "Multica Issue 草稿",
            "生成 Issue 草稿",
            "复制 Issue 标题",
            "复制 Issue 描述",
            "复制命令草稿",
            "下载草稿 .md",
            "仅草稿，未创建 issue，未分配 Agent",
            "build_multica_issue_draft",
            "准备创建 Issue",
            "CREATE_MULTICA_ISSUE",
            "确认创建 Issue",
            "将创建真实 Multica issue",
            "不会分配 Agent",
            "不会启动 Claude/Codex/opencode/OpenClaw",
            "create_multica_issue_from_draft",
            "准备分配 Agent",
            "确认分配 Agent",
            "未自动返回 Issue ID",
            "手动输入已有 Multica issue id",
            "Issue ID / Identifier",
            "例如：78480e61 或 HHH-19",
            "Identifier",
            "ASSIGN",
            "claude",
            "codex",
            "opencode",
            "openclaw",
            "不会额外启动本地 Agent",
            "不会读取 runs/run-messages",
            "assign_multica_issue_to_agent",
        ):
            self.assertIn(text, js)
        self.assertIn(".multica-draft-panel", css)
        self.assertIn(".multica-assign-panel", css)
        self.assertNotIn("分配给 Claude", js)
        self.assertNotIn("创建并运行", js)
        self.assertNotIn("创建并分配 Claude", js)
        self.assertNotIn("分配并运行", js)
        self.assertNotIn("一键派发并监听", js)
        self.assertNotIn("自动验收", js)
        self.assertNotIn("自动派发", js)

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

    def test_agent_handoff_copy_ux_static_assets(self):
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        for text in (
            "copyTextToClipboard",
            "renderAgentHandoffResultCard",
            "data-handoff-copy=\"full\"",
            "data-handoff-terminal",
            "data-target-project-path",
            "复制完整提示词",
            "打开目标项目终端",
            "复制文件路径",
            "复制预览",
            "read_agent_handoff_file",
            "open_agent_handoff_terminal",
            "parseAgentHandoffDetails",
            "target_project_path",
            "目标项目路径",
            "可打开终端",
        ):
            self.assertIn(text, js, f"Missing Agent Handoff copy UX JS: {text}")
        for text in (
            ".agent-handoff-actions",
            ".agent-handoff-target-meta",
            ".agent-handoff-preview",
            ".agent-handoff-detail",
            "user-select:text",
        ):
            self.assertIn(text, css, f"Missing Agent Handoff copy UX CSS: {text}")

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

    def test_js_has_health_report_card_rendering(self):
        js = self._read("frontend/control_panel/assets/app.js")
        for text in ("renderHealthReportResultCard", "getHealthStatusFromResult",
                     "splitHealthReportSections", "health-report-card",
                     "readonly_health_report"):
            self.assertIn(text, js, f"Missing health report card: {text}")

    def test_js_health_report_uses_escape_html(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(sec.title)", js,
                      "Health report sections must escape title")
        self.assertIn("escapeHtml(l)", js,
                      "Health report lines must be escaped")

    def test_css_has_health_report_styles(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for text in (".health-report-card", ".health-report-head", ".health-state-pill",
                     ".health-state-pill.healthy", ".health-state-pill.warning",
                     ".health-state-pill.error", ".health-state-pill.unknown",
                     ".health-report-summary", ".health-report-sections",
                     ".health-report-section", ".health-report-section-title",
                     ".health-report-section-body"):
            self.assertIn(text, css, f"Missing health report CSS: {text}")

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


def _brief_result(database_used, status):
    from xiaohuang.agent_handoff.models import DatabaseBriefResult
    return DatabaseBriefResult(database_used=database_used, database_status=status)


def _agent_completion_report():
    return """完成：V1.5-C1.3 Agent Handoff Copy UX

一、改了哪些文件
- src/xiaohuang/control_panel_web_service.py
- frontend/control_panel/assets/app.js

三、安全边界
- 不启动 Agent：是
- 不执行 shell：是

五、人工验收
- 真实窗口点击通过。

六、验证结果
- compileall：exit 0
- unittest discover：OK
- git diff --check：通过

七、最新提交
- 5dfce798f2e37e91ba7316004e72d4ccdfb8c485
- feat: add agent handoff copy ux
"""


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


class V15B2TaskHistoryUITests(unittest.TestCase):
    """V1.5-B2 Task History UI static/structure tests."""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def _read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_html_has_tasks_history_section(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("任务历史", html)
        self.assertIn("tasks-history-shell", html)
        self.assertIn("tasks-history-grid", html)
        self.assertIn("tasks-history-list", html)
        self.assertIn("tasks-history-list-scroll", html)
        self.assertIn("tasks-history-detail", html)
        self.assertIn("tasks-history-detail-scroll", html)
        self.assertIn("暂无任务历史", html)

    def test_section_tasks_does_not_have_shell_as_class(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertNotIn('class="content-section tasks-history-shell"', html,
                         "tasks-history-shell must be an inner wrapper, not a class on the section")

    def test_tasks_history_shell_is_inner_wrapper(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn('<div class="tasks-history-shell">', html,
                      "tasks-history-shell should be an inner div wrapper inside section-tasks")

    def test_html_tasks_has_refresh_button(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn('id="btn-tasks-refresh"', html)

    def test_html_tasks_has_loading_and_error_states(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("正在读取任务历史...", html)
        self.assertIn("任务历史暂时不可用", html)

    def test_js_has_task_history_functions(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("function loadTaskHistory", js)
        self.assertIn("function renderTaskHistory", js)
        self.assertIn("function renderTaskHistoryDetail", js)
        self.assertIn("function selectTaskHistoryItem", js)
        self.assertIn("function getHistorySignal", js)
        self.assertIn("function formatHistoryTime", js)
        self.assertIn("function setTaskHistoryViewState", js)
        self.assertIn("function getHistoryReadFilesCount", js)
        self.assertIn("function parseHealthReportSections", js)
        self.assertIn("function buildHistoryInsightSections", js)
        self.assertIn("get_recent_task_history", js)

    def test_js_task_history_uses_escape_html(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(item.title", js)
        self.assertIn("escapeHtml(item.summary", js)
        self.assertIn("escapeHtml(item.safe_details_excerpt", js)

    def test_js_task_history_badge_labels(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("任务：完成", js, "task status badge must include 任务： prefix")
        self.assertIn("任务：失败", js, "failed status badge must include 任务： prefix")
        self.assertIn("报告：", js, "report signal badge must include 报告： prefix")

    def test_js_health_report_sections_escape(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(sec.title)", js, "section title must be escapeHtml'd")
        self.assertIn("escapeHtml(body)", js, "section body must be escapeHtml'd")

    def test_js_detail_has_original_safe_summary(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("原始安全摘要", js)

    def test_css_has_detail_block_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (
            ".task-history-badge-row",
            ".tasks-history-detail-block",
            ".tasks-history-detail-block-title",
            ".tasks-history-detail-block-body",
            ".tasks-history-detail-overview",
            ".tasks-history-detail-muted",
        ):
            self.assertIn(cls_name, css, f"Missing B2.2 CSS class: {cls_name}")

    def test_css_has_scroll_container_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (
            ".tasks-history-list-pane",
            ".tasks-history-list-scroll",
            ".tasks-history-detail-pane",
            ".tasks-history-detail-scroll",
        ):
            self.assertIn(cls_name, css, f"Missing B2.3 scroll container class: {cls_name}")

    def test_html_has_scroll_container_elements(self):
        html = self._read("frontend/control_panel/index.html")
        for elem in ("tasks-history-list-pane", "tasks-history-list-scroll",
                     "tasks-history-detail-pane", "tasks-history-detail-scroll"):
            self.assertIn(elem, html, f"Missing B2.3 scroll element: {elem}")

    def test_js_read_files_count_is_escaped(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(getHistoryReadFilesCount(item))", js,
                       "read_files_count must be escaped via getHistoryReadFilesCount")
        self.assertNotIn("+ item.read_files_count +", js,
                         "raw read_files_count must not be directly concatenated into HTML")

    def test_js_no_dangerously_set_inner_html(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("dangerouslySetInnerHTML", js)

    def test_js_no_task_results_jsonl_direct_access(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("task_results.jsonl", js)

    def test_js_auto_loads_on_tasks_section(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("currentSection === 'tasks'", js)
        self.assertIn("loadTaskHistory()", js)

    def test_css_has_task_history_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (
            ".tasks-history-shell", ".tasks-history-grid",
            ".tasks-history-list", ".task-history-card",
            ".tasks-history-detail", ".task-history-signal",
            ".tasks-history-empty",
        ):
            self.assertIn(cls_name, css, f"Missing task history CSS class: {cls_name}")

    def test_css_has_signal_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        for cls_name in (
            ".task-history-signal.signal-ok",
            ".task-history-signal.signal-warn",
            ".task-history-signal.signal-err",
            ".task-history-signal.signal-unknown",
        ):
            self.assertIn(cls_name, css, f"Missing signal class: {cls_name}")

    def test_no_chat_tasks_rail_invasion(self):
        js = self._read("frontend/control_panel/assets/app.js")
        css = self._read("frontend/control_panel/assets/style.css")
        html = self._read("frontend/control_panel/index.html")
        self.assertNotIn("chat-recent-tasks", js)
        self.assertNotIn("chat-recent-tasks", css)
        self.assertNotIn("chat-recent-tasks", html)

    def test_no_unplanned_task_history_features(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("task-history-search", js)
        self.assertNotIn("task-history-delete", js)
        self.assertNotIn("task-history-pagination", js)
        self.assertNotIn("task-history-export", js)

    def test_view_state_has_four_modes(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("state === 'loading'", js)
        self.assertIn("state === 'error'", js)
        self.assertIn("state === 'empty'", js)
        self.assertIn("state === 'grid'", js)

    def test_view_state_not_calls_show_task_history_loading_in_finally(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("showTaskHistoryLoading(false)", js,
                         "finally block must not call showTaskHistoryLoading which could overwrite error state")


class V15C5F2StandaloneAssignUITests(unittest.TestCase):
    """V1.5-C5F.2 / C6.1 standalone assign existing Multica issue
    — now routed through the Multica Task Panel drawer."""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def _read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_html_has_standalone_assign_block(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("分配已有 Multica Issue", html)
        self.assertIn("multica-standalone-assign-block", html)
        self.assertIn("multica-panel-drawer", html)

    def test_html_has_toggle_button(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn('id="btn-toggle-sa"', html,
                      "toggle button must exist for opening standalone assign panel")

    def test_panel_is_drawer_not_inline_in_composer(self):
        html = self._read("frontend/control_panel/index.html")
        composer_start = html.index('class="text-chat-composer"')
        composer_end = html.index('class="text-chat-input-row"', composer_start)
        composer_section = html[composer_start:composer_end]
        self.assertNotIn("multica-standalone-assign-panel", composer_section,
                         "standalone assign panel must NOT be inside text-chat-composer (now drawer)")
        self.assertIn("multica-panel-backdrop", html,
                      "multica task panel drawer must exist")

    def test_html_has_assign_form_fields(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn('mp-assign-issue-id', html)
        self.assertIn('mp-assign-agent', html)
        self.assertIn('btn-mp-prepare-assign', html)
        self.assertIn('btn-mp-confirm-assign', html)
        self.assertIn('准备分配 Agent', html)
        self.assertIn('确认分配 Agent', html)

    def test_html_has_agent_options(self):
        html = self._read("frontend/control_panel/index.html")
        for agent in ("claude", "codex", "opencode", "openclaw"):
            self.assertIn('value="' + agent + '"', html,
                          "Missing agent option: " + agent)

    def test_html_has_safety_blurb(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("不会读取 runs/run-messages", html)
        self.assertIn("不会额外启动本地 Agent", html)

    def test_html_has_multica_task_panel_tabs(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("Multica 任务面板", html)
        self.assertIn("分配 Issue", html)
        self.assertIn("查看进度", html)

    def test_js_has_standalone_assign_functions(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("function prepareMulticaAssign", js)
        self.assertIn("function confirmMulticaAssign", js)
        self.assertIn("function initMulticaTaskPanel", js)
        self.assertIn("function renderMulticaAssignResult", js)
        self.assertIn("ASSIGN", js)

    def test_js_standalone_uses_escape_html(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(result.agent", js)
        self.assertIn("escapeHtml(issueId", js)

    def test_js_no_dangerous_standalone_text(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertNotIn("分配并运行", js)
        self.assertNotIn("自动验收", js)
        self.assertNotIn("启动 Agent", js)

    def test_css_has_standalone_assign_classes(self):
        css = self._read("frontend/control_panel/assets/style.css")
        self.assertIn(".multica-assign-workspace-block", css)
        self.assertIn(".multica-panel-drawer", css)
        self.assertIn(".multica-panel-backdrop", css)


class V15C6RunReaderUITests(unittest.TestCase):
    """V1.5-C6 / C6.1 Run Reader UI — now in Multica Task Panel drawer."""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def _read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_html_has_run_reader_block(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("查看 Multica 运行记录", html)
        self.assertIn("multica-panel-drawer", html)
        self.assertIn('btn-mp-read-runs', html)
        self.assertIn("读取 Runs", html)
        self.assertIn("验收摘要", html)
        self.assertIn("查看进度", html)
        self.assertIn("Issue ID / Identifier", html)
        self.assertIn("详细消息", html)

    def test_html_has_safety_blurb(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertIn("不会 rerun", html)
        self.assertIn("不会 assign", html)
        self.assertIn("不会启动本地 Agent", html)
        self.assertIn("优先使用 Identifier", html)

    def test_html_no_dangerous_run_text(self):
        html = self._read("frontend/control_panel/index.html")
        self.assertNotIn("重新运行", html)
        self.assertNotIn("自动验收通过", html)
        self.assertNotIn("分配并运行", html)
        self.assertNotIn("派发给 Agent", html)

    def test_js_has_run_reader_functions(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("function readMulticaRunsFromPanel", js)
        self.assertIn("function renderMulticaRuns", js)
        self.assertIn("function readMulticaRunMessagesFromPanel", js)
        self.assertIn("function renderMulticaRunMessages", js)
        self.assertIn("read_multica_issue_runs", js)
        self.assertIn("read_multica_run_messages", js)
        self.assertIn("读取消息", js)

    def test_js_run_reader_uses_escape_html(self):
        js = self._read("frontend/control_panel/assets/app.js")
        self.assertIn("escapeHtml(runs[0].task_id", js)
        self.assertIn("escapeHtml(runs[0].status", js)
        self.assertIn("escapeHtml(", js)
