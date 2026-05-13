"""control_panel_web_service.py

Python API for the XiaoHuang Web Control Panel.
Exposes methods callable from JS via window.pywebview.api.
Reuses existing status_control_service for all business logic.
"""

from __future__ import annotations

import json
import os
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from xiaohuang.launch_control_service import get_project_root
from xiaohuang.status_control_service import (
    ControlPanelStatus,
    WakeEngineConfigSaveResult,
    WakeEngineConfigUpdate,
    build_status,
    load_config_summary,
    run_restart_operation,
    run_start_operation,
    run_stop_operation,
    save_wake_engine_config,
)
from xiaohuang.control_panel_conversation_api import ControlPanelConversationApi
from xiaohuang.control_panel_text_task_api import (
    ControlPanelTextTaskApi,
    _registry_blocked_result,
    _registry_failed_result,
    _registry_reason_text,
)
from xiaohuang.conversation_history_service import ConversationHistoryStore
from xiaohuang.llm_config_debug_service import build_llm_debug_summary
from xiaohuang.text_interaction_service import run_text_interaction_turn
from xiaohuang.text_interaction_session_service import TextInteractionSessionStore
from xiaohuang.text_task_execution_service import execute_confirmed_text_task
from xiaohuang.text_task_registry_service import PendingTextTaskRegistry

_SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "api_key_env"}


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "data": data, "message": message}


def _fail(error: str, code: str = "error") -> dict:
    return {"ok": False, "error": error, "code": code}


def _sanitize_dict(d: dict) -> dict:
    return {k: v for k, v in d.items() if k.lower() not in _SENSITIVE_KEYS}


def _status_to_dict(s: ControlPanelStatus) -> dict:
    d = asdict(s)
    d["config_path"] = str(d.get("config_path") or "")
    return _sanitize_dict(d)


class ControlPanelWebApi:
    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is not None and str(config_path).strip():
            self._config_path = Path(config_path)
        else:
            self._config_path = None
        self._project_root = get_project_root()
        self._text_interaction_sessions = TextInteractionSessionStore()
        self._text_task_registry = PendingTextTaskRegistry()
        self._history_store = ConversationHistoryStore(
            self._project_root / "data" / "conversations" / "conversations.sqlite3"
        )
        self._init_runtime_events()

    def _init_runtime_events(self) -> None:
        try:
            from xiaohuang.capabilities.runtime_events.service import init_event_logger
            init_event_logger(self._project_root)
        except Exception:
            pass

    def _resolve_config_path(self) -> Path:
        if self._config_path:
            return self._config_path
        from xiaohuang.app_config_service import get_default_config_path
        return get_default_config_path()

    def _conversation_api(self) -> ControlPanelConversationApi:
        return ControlPanelConversationApi(
            history_store=self._history_store,
            session_store=self._text_interaction_sessions,
            task_registry=self._text_task_registry,
            resolve_config_path=self._resolve_config_path,
            run_text_turn=run_text_interaction_turn,
        )

    def _text_task_api(self) -> ControlPanelTextTaskApi:
        return ControlPanelTextTaskApi(
            project_root=self._project_root,
            task_registry=self._text_task_registry,
            resolve_config_path=self._resolve_config_path,
            execute_text_task=execute_confirmed_text_task,
            record_event=_record_cp_event,
        )

    def get_status(self) -> dict:
        try:
            path = self._resolve_config_path()
            status = build_status(self._project_root, path)
            return _ok(data=_status_to_dict(status))
        except Exception:
            msg = f"获取状态失败: {traceback.format_exc()}"
            _record_cp_event("get_status", msg, "error")
            return _fail(msg, "status_error")

    def get_runtime_events(self, limit: int = 30) -> dict:
        try:
            from xiaohuang.capabilities.runtime_events.service import get_recent_events
            events = get_recent_events(int(limit) if limit else 30)
            return _ok(data={"events": events}, message="运行事件已加载")
        except Exception:
            return _fail(f"获取运行事件失败: {traceback.format_exc()}", "events_error")

    def get_config_summary(self) -> dict:
        try:
            path = self._resolve_config_path()
            summary = load_config_summary(path)
            return _ok(data=_sanitize_dict(asdict(summary)))
        except Exception:
            return _fail(f"读取配置失败: {traceback.format_exc()}", "config_error")

    def get_llm_debug_summary(self, payload: dict | None = None) -> dict:
        try:
            path = self._resolve_config_path()
            return _ok(data=build_llm_debug_summary(path), message="LLM 配置摘要已读取")
        except Exception:
            return _fail(f"读取 LLM 配置摘要失败: {traceback.format_exc()}", "llm_debug_error")

    def refresh(self) -> dict:
        return self.get_status()

    def start_xiaohuang(self) -> dict:
        try:
            path = self._resolve_config_path()
            result = run_start_operation(self._project_root, path)
            if result.ok:
                _record_cp_event("start_xiaohuang", "启动小黄成功")
                return _ok(
                    data={"success": True, "message": result.message},
                    message=result.message,
                )
            diagnostic = _run_startup_diagnostic(self._project_root)
            _record_startup_diagnostic_event(diagnostic)
            data = {"success": False, "message": result.message}
            if diagnostic.kind not in ("none",):
                data["diagnostic"] = diagnostic.to_dict()
            return _ok(data=data, message=result.message)
        except Exception:
            msg = f"启动失败: {traceback.format_exc()}"
            _record_cp_event("start_xiaohuang", msg, "error")
            return _fail(msg, "start_error")

    def stop_xiaohuang(self) -> dict:
        try:
            result = run_stop_operation(self._project_root)
            if result.ok:
                _record_cp_event("stop_xiaohuang", "停止小黄成功")
            else:
                _record_cp_event("stop_xiaohuang", f"停止失败: {result.message}", "error")
            return _ok(
                data={"success": result.ok, "message": result.message},
                message=result.message,
            )
        except Exception:
            msg = f"停止失败: {traceback.format_exc()}"
            _record_cp_event("stop_xiaohuang", msg, "error")
            return _fail(msg, "stop_error")

    def restart_xiaohuang(self) -> dict:
        try:
            path = self._resolve_config_path()
            result = run_restart_operation(self._project_root, path)
            if result.ok:
                _record_cp_event("restart_xiaohuang", "重启小黄成功")
                return _ok(
                    data={"success": True, "message": result.message},
                    message=result.message,
                )
            diagnostic = _run_startup_diagnostic(self._project_root)
            _record_startup_diagnostic_event(diagnostic)
            data = {"success": False, "message": result.message}
            if diagnostic.kind not in ("none",):
                data["diagnostic"] = diagnostic.to_dict()
            return _ok(data=data, message=result.message)
        except Exception:
            msg = f"重启失败: {traceback.format_exc()}"
            _record_cp_event("restart_xiaohuang", msg, "error")
            return _fail(msg, "restart_error")

    def save_wake_config(self, payload: dict) -> dict:
        try:
            path = self._resolve_config_path()
            engine = payload.get("engine", "")
            if not isinstance(engine, str) or not engine.strip():
                return _fail("wake.engine 不能为空", "validation_error")

            update = WakeEngineConfigUpdate(
                engine=str(engine).strip().lower(),
                fallback_enabled=bool(payload.get("fallback_enabled", True)),
                device_index=_coerce_optional_int(payload.get("device_index")) or 0,
                cooldown_seconds=_coerce_optional_float(payload.get("cooldown_seconds")) or 2.5,
                sensitivity=_coerce_optional_float(payload.get("sensitivity")) or 0.5,
            )
            result = save_wake_engine_config(path, update)
            return _ok(
                data={"saved": result.ok, "error": result.error},
                message="配置已保存" if result.ok else (result.error or "保存失败"),
            )
        except Exception:
            return _fail(f"保存配置失败: {traceback.format_exc()}", "save_error")

    def export_diagnostics_text(self, payload: dict) -> dict:
        try:
            from xiaohuang.capabilities.diagnostic_export.service import (
                export_diagnostics_to_file,
                format_diagnostics_text,
            )
            text = format_diagnostics_text(payload)
            logs_dir = self._project_root / "logs"
            result = export_diagnostics_to_file(text, logs_dir)
            if result.ok:
                _record_cp_event("export_diagnostics", "诊断信息已导出")
            else:
                _record_cp_event("export_diagnostics", f"导出失败: {result.message}", "error")
            return _ok(
                data={
                    "path": result.path,
                    "content": result.content,
                },
                message=result.message,
            )
        except Exception:
            return _fail(f"导出诊断信息失败: {traceback.format_exc()}", "export_error")

    def get_log_paths(self) -> dict:
        try:
            logs_dir = self._project_root / "logs"
            return _ok(data={
                "logs_directory": str(logs_dir),
                "project_root": str(self._project_root),
                "config_path": str(self._resolve_config_path()),
            })
        except Exception:
            return _fail(f"获取路径失败: {traceback.format_exc()}", "path_error")

    def open_logs_folder(self) -> dict:
        try:
            logs_dir = (self._project_root / "logs").resolve()
            logs_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(logs_dir))  # type: ignore[attr-defined]
            _record_cp_event("open_logs_folder", f"日志目录已打开: {logs_dir}")
            return _ok(data={"path": str(logs_dir)}, message="日志目录已打开")
        except Exception:
            msg = f"打开日志目录失败: {traceback.format_exc()}"
            _record_cp_event("open_logs_folder", msg, "error")
            return _fail(msg, "open_logs_error")

    def get_preflight_check(self) -> dict:
        try:
            from xiaohuang.capabilities.preflight_check.service import (
                run_preflight_check,
            )
            result = run_preflight_check(self._project_root)
            _record_cp_event(
                "preflight_check",
                result.summary,
                "info" if result.status == "ok" else result.status,
            )
            return _ok(data=result.to_dict(), message="启动前检查完成")
        except Exception:
            msg = f"启动前检查失败: {traceback.format_exc()}"
            _record_cp_event("preflight_check", msg, "error")
            return _fail(msg, "preflight_error")

    def get_multica_status(self) -> dict:
        try:
            from xiaohuang.multica_integration.status_service import get_multica_status
            status = get_multica_status()
            if not status.ok:
                return _fail(
                    status.message or "Multica 状态不可用。",
                    status.error_code or "multica_unavailable",
                )
            return _ok(data=status.to_dict(), message=status.message or "Multica 状态已读取")
        except Exception:
            return _fail("读取 Multica 状态失败", "multica_status_error")

    def build_multica_issue_draft(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            from xiaohuang.multica_integration.issue_draft_service import (
                build_issue_draft_from_handoff,
            )
            draft = build_issue_draft_from_handoff(
                handoff_title=str(data.get("handoff_title") or ""),
                handoff_prompt=str(data.get("handoff_prompt") or ""),
                target_project_path=str(data.get("target_project_path") or ""),
                target_project_kind=str(data.get("target_project_kind") or "auto"),
                project_relation=str(data.get("project_relation") or "unknown"),
                database_brief_status=str(data.get("database_brief_status") or ""),
                related_domains=_coerce_string_tuple(data.get("related_domains")),
                preferred_agent=str(data.get("preferred_agent") or ""),
            )
            if not draft.ok:
                return _fail(
                    draft.message or "Multica issue 草稿生成失败。",
                    draft.error_code or "multica_issue_draft_error",
                )
            return _ok(data=draft.to_dict(), message=draft.message or "Multica issue 草稿已生成")
        except Exception:
            return _fail("生成 Multica issue 草稿失败", "multica_issue_draft_error")

    def create_multica_issue_from_draft(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            from xiaohuang.multica_integration.issue_create_service import (
                create_issue_from_draft,
            )
            result = create_issue_from_draft(
                title=str(data.get("title") or ""),
                description=str(data.get("description") or ""),
                confirmed=bool(data.get("confirmed", False)),
                confirmation_text=str(data.get("confirmation_text") or ""),
                priority=str(data.get("priority") or ""),
                project=str(data.get("project") or ""),
            )
            if not result.ok:
                return _fail(
                    result.message or "Multica issue 创建失败。",
                    result.error_code or "multica_issue_create_error",
                )
            return _ok(data=result.to_dict(), message=result.message or "Multica issue 已创建")
        except Exception:
            return _fail("创建 Multica issue 失败", "multica_issue_create_error")

    def assign_multica_issue_to_agent(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            from xiaohuang.multica_integration.issue_assign_service import (
                assign_issue_to_agent,
            )
            result = assign_issue_to_agent(
                issue_id=str(data.get("issue_id") or ""),
                agent=str(data.get("agent") or ""),
                confirmed=bool(data.get("confirmed", False)),
                confirmation_text=str(data.get("confirmation_text") or ""),
            )
            if not result.ok:
                return _fail(
                    result.message or "Multica issue 分配失败。",
                    result.error_code or "multica_issue_assign_error",
                )
            return _ok(data=result.to_dict(), message=result.message or "Multica issue 已分配")
        except Exception:
            return _fail("分配 Multica issue 失败", "multica_issue_assign_error")

    def read_multica_issue_runs(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            issue_id = str(data.get("issue_id") or "")
            from xiaohuang.multica_integration.run_reader_service import read_issue_runs
            result = read_issue_runs(issue_id=issue_id)
            if not result.ok:
                return _fail(
                    result.message or "读取 Multica runs 失败。",
                    result.error_code or "multica_runs_error",
                )
            return _ok(data=result.to_dict(), message=result.message or "Multica runs 读取完成")
        except Exception:
            return _fail("读取 Multica runs 失败", "multica_runs_error")

    def read_multica_run_messages(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            task_id = str(data.get("task_id") or "")
            conversation_id = str(data.get("conversation_id") or "")
            issue_id = str(data.get("issue_id") or "")
            from xiaohuang.multica_integration.run_reader_service import read_run_messages
            result = read_run_messages(task_id=task_id)
            if not result.ok:
                return _fail(
                    result.message or "读取 Multica run-messages 失败。",
                    result.error_code or "multica_run_messages_error",
                )
            response_data = result.to_dict()
            response_data["conversation_id"] = conversation_id
            # Auto-bind to conversation on successful read
            if conversation_id and (issue_id or task_id):
                try:
                    summary = result.review_summary or ""
                    msgs = list(result.messages) if result.messages else []
                    tool_use = sum(1 for m in msgs if getattr(m, "message_type", "") == "tool_use")
                    tool_result = sum(1 for m in msgs if getattr(m, "message_type", "") == "tool_result")
                    binding = self._history_store.bind_multica_task(
                        conversation_id=conversation_id,
                        issue_id=issue_id,
                        task_id=task_id,
                        review_summary=summary,
                        messages_count=len(msgs),
                        tool_use_count=tool_use,
                        tool_result_count=tool_result,
                    )
                    response_data["binding"] = binding.to_dict()
                except ValueError:
                    response_data["binding_error"] = "task already bound to another conversation"
                except Exception:
                    pass
            return _ok(data=response_data, message=result.message or "Multica run-messages 读取完成")
        except Exception:
            return _fail("读取 Multica run-messages 失败", "multica_run_messages_error")

    # ── Conversation history API ──────────────────────────────────────

    def list_text_conversations(self, payload: dict | None = None) -> dict:
        return self._conversation_api().list_text_conversations(payload)

    def create_text_conversation(self, payload: dict | None = None) -> dict:
        return self._conversation_api().create_text_conversation(payload)

    def get_text_conversation(self, payload: dict | None = None) -> dict:
        return self._conversation_api().get_text_conversation(payload)

    def clear_text_conversation(self, payload: dict | None = None) -> dict:
        return self._conversation_api().clear_text_conversation(payload)

    def clear_all_text_conversations(self, payload: dict | None = None) -> dict:
        return self._conversation_api().clear_all_text_conversations(payload)

    def list_conversation_multica_tasks(self, payload: dict | None = None) -> dict:
        return self._conversation_api().list_conversation_multica_tasks(payload)

    def bind_multica_run_to_conversation(self, payload: dict | None = None) -> dict:
        return self._conversation_api().bind_multica_run_to_conversation(payload)

    def open_text_chat_window(self) -> dict:
        return _ok(
            data={"view": "text-chat", "same_window": True},
            message="请在当前窗口切换到文本对话",
        )

    # ── Legacy LLM turn (100% identical to pre-C5G.1 send_text_message) ─

    def _run_legacy_text_message_turn(self, payload: dict) -> dict:
        return self._conversation_api().run_legacy_text_message_turn(payload)

    def send_text_message(self, payload: dict) -> dict:
        return self._conversation_api().send_text_message(payload)

    def confirm_text_task(self, payload: dict | None = None) -> dict:
        return self._text_task_api().confirm_text_task(payload)

    def cancel_text_task(self, payload: dict | None = None) -> dict:
        return self._text_task_api().cancel_text_task(payload)

    def clear_text_session(self, payload: dict | None = None) -> dict:
        return self._conversation_api().clear_text_session(payload)

    def clear_runtime_events(self, payload: dict | None = None) -> dict:
        try:
            from xiaohuang.capabilities.runtime_events.service import clear_recent_events
            removed = clear_recent_events()
            return _ok(data={"removed": removed}, message="最近事件已清空")
        except Exception:
            return _fail("清空最近事件失败", "clear_runtime_events_error")

    def get_recent_task_history(self, payload: dict | None = None) -> dict:
        try:
            raw_limit = _coerce_optional_int(
                (payload or {}).get("limit") if isinstance(payload, dict) else None
            )
            if raw_limit is None:
                limit = 20
            else:
                limit = max(1, min(raw_limit, 50))

            from xiaohuang.task_result_history_service import get_recent_task_results
            items = get_recent_task_results(self._project_root, limit=limit)
            return _ok(data={"items": items}, message="任务历史读取完成")
        except Exception:
            return _ok(data={"items": []}, message="任务历史不可用")

    def read_agent_handoff_file(self, payload: dict | None = None) -> dict:
        try:
            raw_path = ""
            if isinstance(payload, dict):
                raw_path = str(payload.get("path") or "")
            from xiaohuang.agent_handoff.handoff_file_service import read_handoff_file
            return read_handoff_file(self._project_root, raw_path)
        except Exception:
            return {
                "ok": False,
                "path": "",
                "content": "",
                "size": 0,
                "error": "handoff file read failed",
            }

    def open_agent_handoff_terminal(self, payload: dict | None = None) -> dict:
        try:
            target_project_path = ""
            if isinstance(payload, dict):
                target_project_path = str(payload.get("target_project_path") or "")
            from xiaohuang.agent_handoff import terminal_launcher
            result = terminal_launcher.open_target_project_terminal(target_project_path)
            data = {"target_project_path": result.target_project_path}
            if result.ok:
                return _ok(data=data, message=result.message)
            return {
                "ok": False,
                "error": result.message,
                "code": result.error_code or "open_terminal_failed",
                "error_code": result.error_code or "open_terminal_failed",
                "data": data,
            }
        except Exception:
            return _fail("打开目标项目终端失败", "open_terminal_failed")


def _record_cp_event(event_type: str, message: str, level: str = "info") -> None:
    try:
        from xiaohuang.capabilities.runtime_events.service import record_event
        record_event("control_panel", event_type, message, level=level)
    except Exception:
        pass


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


def _run_startup_diagnostic(project_root: Path):
    try:
        from xiaohuang.capabilities.startup_diagnostics.service import (
            diagnose_startup_failure,
        )
        return diagnose_startup_failure(project_root)
    except Exception:
        from xiaohuang.capabilities.startup_diagnostics.models import StartupDiagnostic
        return StartupDiagnostic(
            kind="none",
            severity="info",
            summary="",
            suggestion="",
        )


def _record_startup_diagnostic_event(diagnostic) -> None:
    if diagnostic.kind in ("none",):
        return
    try:
        from xiaohuang.capabilities.runtime_events.service import record_event
        record_event(
            "control_panel",
            "startup_diagnostic",
            diagnostic.summary,
            level=diagnostic.severity,
            details={
                "kind": diagnostic.kind,
                "suggestion": diagnostic.suggestion,
                "source_file": diagnostic.source_file or "",
            },
        )
    except Exception:
        pass
