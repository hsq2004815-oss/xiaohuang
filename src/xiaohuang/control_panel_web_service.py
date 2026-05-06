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
