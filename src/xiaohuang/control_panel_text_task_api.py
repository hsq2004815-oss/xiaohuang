"""Pending text-task confirmation API for the web control panel."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from xiaohuang.text_task_registry_service import PendingTextTaskRegistry


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "data": data, "message": message}


def _fail(error: str, code: str = "error") -> dict:
    return {"ok": False, "error": error, "code": code}


class ControlPanelTextTaskApi:
    """Confirm or cancel pending text tasks registered by chat turns."""

    def __init__(
        self,
        *,
        project_root: Path,
        task_registry: PendingTextTaskRegistry,
        resolve_config_path: Callable[[], Path],
        execute_text_task: Callable[..., Any],
        record_event: Callable[[str, str, str], None],
    ) -> None:
        self._project_root = project_root
        self._task_registry = task_registry
        self._resolve_config_path = resolve_config_path
        self._execute_text_task = execute_text_task
        self._record_event = record_event

    def confirm_text_task(self, payload: dict | None = None) -> dict:
        try:
            task_id = _extract_task_id(payload)
            if not task_id:
                return _ok(
                    data=_registry_blocked_result("", "missing_task_id"),
                    message="文本任务已拦截",
                )
            record, reason = self._task_registry.claim_for_execution(task_id)
            if record is None:
                return _ok(
                    data=_registry_blocked_result(task_id, reason),
                    message="文本任务已拦截",
                )
            try:
                result = self._execute_text_task(
                    record.task,
                    project_root=self._project_root,
                    config_path=self._resolve_config_path(),
                )
            except Exception:
                self._task_registry.mark_failed(task_id, "confirm_text_task_error")
                return _ok(
                    data=_registry_failed_result(task_id, "confirm_text_task_error"),
                    message="文本任务执行失败",
                )
            if result.ok and result.status == "completed":
                self._task_registry.mark_completed(task_id)
            elif result.status == "blocked":
                self._task_registry.mark_blocked(task_id, result.error)
            else:
                self._task_registry.mark_failed(task_id, result.error)

            if result.status in ("completed", "failed"):
                try:
                    from xiaohuang.task_result_history_service import append_task_result
                    append_task_result(self._project_root, result, task=record.task)
                except Exception:
                    self._record_event("control_panel", "task_history_append_failed", "warning")

            return _ok(data=asdict(result), message="文本任务执行完成" if result.ok else "文本任务已拦截")
        except Exception:
            return _fail("确认文本任务失败", "confirm_text_task_error")

    def cancel_text_task(self, payload: dict | None = None) -> dict:
        try:
            task_id = _extract_task_id(payload)
            record = self._task_registry.cancel(task_id) if task_id else None
            status = record.status if record else "not_found"
            return _ok(
                data={"task_id": task_id, "status": status},
                message="文本任务已取消" if record else "文本任务未找到",
            )
        except Exception:
            return _fail("取消文本任务失败", "cancel_text_task_error")


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
