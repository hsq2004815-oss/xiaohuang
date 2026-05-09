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

    def open_text_chat_window(self) -> dict:
        return _ok(
            data={"view": "text-chat", "same_window": True},
            message="请在当前窗口切换到文本对话",
        )

    def send_text_message(self, payload: dict) -> dict:
        try:
            text = ""
            session_id = "control_panel"
            if isinstance(payload, dict):
                text = str(payload.get("text") or "")
                session_id = str(payload.get("session_id") or "control_panel")

            result = run_text_interaction_turn(
                text,
                session_store=self._text_interaction_sessions,
                session_id=session_id,
                config_path=self._resolve_config_path(),
            )
            data = asdict(result)
            if data.get("requires_confirmation") and isinstance(data.get("pending_task"), dict):
                record = self._text_task_registry.register(data["pending_task"])
                data["pending_task"] = dict(record.task)
            return _ok(data=data, message="消息已回复" if result.ok else "消息处理失败")
        except Exception:
            return _fail("文本消息处理失败", "send_text_message_error")

    def confirm_text_task(self, payload: dict | None = None) -> dict:
        try:
            task_id = _extract_task_id(payload)
            if not task_id:
                return _ok(
                    data=_registry_blocked_result("", "missing_task_id"),
                    message="文本任务已拦截",
                )
            record, reason = self._text_task_registry.claim_for_execution(task_id)
            if record is None:
                return _ok(
                    data=_registry_blocked_result(task_id, reason),
                    message="文本任务已拦截",
                )
            try:
                result = execute_confirmed_text_task(
                    record.task,
                    project_root=self._project_root,
                    config_path=self._resolve_config_path(),
                )
            except Exception:
                self._text_task_registry.mark_failed(task_id, "confirm_text_task_error")
                return _ok(
                    data=_registry_failed_result(task_id, "confirm_text_task_error"),
                    message="文本任务执行失败",
                )
            if result.ok and result.status == "completed":
                self._text_task_registry.mark_completed(task_id)
            elif result.status == "blocked":
                self._text_task_registry.mark_blocked(task_id, result.error)
            else:
                self._text_task_registry.mark_failed(task_id, result.error)
            return _ok(data=asdict(result), message="文本任务执行完成" if result.ok else "文本任务已拦截")
        except Exception:
            return _fail("确认文本任务失败", "confirm_text_task_error")

    def cancel_text_task(self, payload: dict | None = None) -> dict:
        try:
            task_id = _extract_task_id(payload)
            record = self._text_task_registry.cancel(task_id) if task_id else None
            status = record.status if record else "not_found"
            return _ok(
                data={"task_id": task_id, "status": status},
                message="文本任务已取消" if record else "文本任务未找到",
            )
        except Exception:
            return _fail("取消文本任务失败", "cancel_text_task_error")

    def clear_text_session(self, payload: dict | None = None) -> dict:
        try:
            session_id = "control_panel"
            if isinstance(payload, dict):
                session_id = str(payload.get("session_id") or "control_panel")
            self._text_interaction_sessions.clear(session_id)
            return _ok(data={"session_id": session_id}, message="文本会话已清空")
        except Exception:
            return _fail("清空文本会话失败", "clear_text_session_error")


def _record_cp_event(event_type: str, message: str, level: str = "info") -> None:
    try:
        from xiaohuang.capabilities.runtime_events.service import record_event
        record_event("control_panel", event_type, message, level=level)
    except Exception:
        pass


def _extract_task_id(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    task_id = payload.get("task_id")
    if task_id:
        return str(task_id)
    pending_task = payload.get("pending_task")
    if isinstance(pending_task, dict) and pending_task.get("task_id"):
        return str(pending_task.get("task_id"))
    return ""


def _registry_blocked_result(task_id: str, reason: str) -> dict:
    summary, details = _registry_reason_text(reason)
    return {
        "ok": False,
        "task_id": task_id,
        "task_type": "registry",
        "status": "blocked",
        "title": "文本任务无法执行",
        "summary": summary,
        "details": details,
        "risk_level": "medium",
        "read_files": [],
        "error": reason or "registry_blocked",
    }


def _registry_failed_result(task_id: str, reason: str) -> dict:
    return {
        "ok": False,
        "task_id": task_id,
        "task_type": "registry",
        "status": "failed",
        "title": "文本任务执行失败",
        "summary": "任务执行过程中出现异常，已标记为失败。",
        "details": "原因：confirm_text_task_error",
        "risk_level": "medium",
        "read_files": [],
        "error": reason or "confirm_text_task_error",
    }


def _registry_reason_text(reason: str) -> tuple[str, str]:
    mapping: dict[str, tuple[str, str]] = {
        "missing_task_id": (
            "没有找到要确认的任务。",
            "前端没有提供有效 task_id，请重新发起任务。",
        ),
        "not_found": (
            "这个任务不存在或已经被清理。",
            "后端注册表中没有找到该 task_id，请重新发起任务。",
        ),
        "expired": (
            "这个任务已过期。",
            "为了安全，待确认任务只在短时间内有效，请重新发起任务。",
        ),
        "already_executing": (
            "这个任务正在执行中。",
            "请等待当前执行结果，不要重复点击确认。",
        ),
        "already_completed": (
            "这个任务已经执行过。",
            "为了避免重复操作，同一个任务不能再次执行。",
        ),
        "already_cancelled": (
            "这个任务已经取消。",
            "已取消的任务不能再执行，请重新发起任务。",
        ),
        "not_pending": (
            "这个任务当前状态不允许执行。",
            "只有 pending 状态的任务可以确认执行。",
        ),
    }
    if reason in mapping:
        return mapping[reason]
    return (
        "该任务无法执行。",
        f"原因：{reason or 'registry_blocked'}",
    )


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
