"""control_panel_app.py — pure functions for the Tkinter control panel.

Extracted from scripts/control_panel.py to keep the script a thin entrypoint.
No Tkinter imports — pure logic, formatting, validation, and operation helpers.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from xiaohuang.app_config_service import get_default_config_path
from xiaohuang.launch_control_service import ensure_log_dir
from xiaohuang.status_control_service import (
    ControlOperationResult,
    ControlPanelStatus,
    READY,
    WAKE_ENGINE_CHOICES,
    WAKE_ENGINE_OPENWAKEWORD,
    WAKE_ENGINE_STT_TEXT,
    WakeEngineConfigUpdate,
    build_status,
    run_restart_operation,
    run_start_operation,
    run_stop_operation,
    save_wake_engine_config,
    stage_markers,
)


READINESS_OPERATION_NAMES = {"启动", "重启"}
READINESS_TIMEOUT_ERRORS = (
    "timeout_voice_overlay_missing",
    "timeout_stt_server_missing",
    "timeout_health_not_ready",
    "timeout",
)
OPERATION_FINAL_STATUS_GRACE_SECONDS = 5.0
OPERATION_FINAL_STATUS_POLL_SECONDS = 0.5


@dataclass(frozen=True)
class StatusRefreshResult:
    generation: int
    status: ControlPanelStatus | None = None
    error: str | None = None


@dataclass(frozen=True)
class OperationUiResult:
    operation_name: str
    result: ControlOperationResult
    final_status: ControlPanelStatus | None = None
    error: str | None = None


class StatusRefreshController:
    def __init__(
        self,
        *,
        state: dict,
        collect_status: Callable[..., ControlPanelStatus],
        render: Callable[[ControlPanelStatus], None],
        schedule_ui: Callable[[Callable[[], None]], None],
        start_worker: Callable[[Callable[[], None], str], None],
        thread_name: str = "xiaohuang-control-panel-refresh",
    ) -> None:
        self.state = state
        self.collect_status = collect_status
        self.render = render
        self.schedule_ui = schedule_ui
        self.start_worker = start_worker
        self.thread_name = thread_name

    def request(self) -> bool:
        if self.state["closed"]:
            return False
        if self.state["refresh_in_progress"]:
            self.state["pending_refresh"] = True
            return False

        self.state["refresh_in_progress"] = True
        self.state["pending_refresh"] = False
        generation = int(self.state["refresh_generation"])
        snapshot = {
            "active_operation": self.state["active_operation"],
            "last_operation": self.state["last_operation"],
            "last_operation_elapsed_seconds": self.state["last_elapsed"],
            "last_error": self.state["last_error"],
        }
        self.start_worker(lambda: self._worker(generation, snapshot), self.thread_name)
        return True

    def _worker(self, generation: int, snapshot: dict) -> None:
        try:
            status = self.collect_status(**snapshot)
            result = StatusRefreshResult(generation=generation, status=status)
        except Exception as exc:
            result = StatusRefreshResult(generation=generation, error=summarize_exception(exc))
        try:
            self.schedule_ui(lambda: self.apply_result(result))
        except Exception:
            return

    def apply_result(self, result: StatusRefreshResult) -> None:
        self.state["refresh_in_progress"] = False
        if self.state["closed"]:
            return
        if self.state.get("operation_completion_pending"):
            self.state["pending_refresh"] = True
            return

        is_current = result.generation == self.state["refresh_generation"]
        if is_current:
            if result.error:
                self._apply_error(result.error)
            elif result.status is not None:
                self._apply_status(result.status)

        if self.state["pending_refresh"]:
            self.request()

    def _apply_error(self, error: str) -> None:
        self.state["last_error"] = error
        last_status = self.state.get("last_status")
        if last_status is None:
            return
        status = status_with_ui_metadata(
            last_status,
            last_operation=self.state["last_operation"],
            last_operation_elapsed_seconds=self.state["last_elapsed"],
            last_error=error,
        )
        self.state["last_status"] = status
        self.render(status)

    def _apply_status(self, status: ControlPanelStatus) -> None:
        cleared_error = clear_ready_state_error(self.state["last_error"], status)
        if cleared_error != self.state["last_error"]:
            self.state["last_error"] = cleared_error
        status = status_with_ui_metadata(
            status,
            last_operation=self.state["last_operation"],
            last_operation_elapsed_seconds=self.state["last_elapsed"],
            last_error=self.state["last_error"],
        )
        self.state["last_status"] = status
        self.render(status)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XiaoHuang status and wake engine control panel")
    parser.add_argument(
        "--config",
        default=str(get_default_config_path()),
        help="Path to config.json. Defaults to %%USERPROFILE%%\\.xiaohuang\\config.json",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=2.0,
        help="Status refresh interval in seconds. Defaults to 2.",
    )
    return parser.parse_args(argv)


def _build_child_env(src_dir: str) -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_dir + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    env.setdefault("PYTHONUTF8", "1")
    return env


def open_settings(project_root: Path, config_path: Path, src_dir: str) -> bool:
    command = [sys.executable, str(project_root / "scripts" / "settings_ui.py"), "--config", str(config_path)]
    try:
        subprocess.Popen(command, cwd=str(project_root), env=_build_child_env(src_dir), shell=False)
        return True
    except Exception:
        return False


def open_log_dir(project_root: Path) -> bool:
    log_dir = ensure_log_dir(project_root)
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(log_dir))
        else:
            subprocess.Popen(["explorer.exe", str(log_dir)], shell=False)
        return True
    except Exception:
        return False


def _status_line(value: bool, true_text: str = "running", false_text: str = "stopped") -> str:
    return true_text if value else false_text


def _format_float(value: float) -> str:
    return f"{float(value):g}"


def format_wake_engine_display(status: ControlPanelStatus) -> str:
    if status.wake_engine == WAKE_ENGINE_OPENWAKEWORD:
        return "openWakeWord"
    suffix = "（默认）" if status.wake_engine_is_default else ""
    return f"stt_text{suffix}"


def format_wake_params(status: ControlPanelStatus) -> str:
    device = status.wake_device_index if status.wake_device_index is not None else "未配置"
    return (
        f"device_index={device}, "
        f"cooldown_seconds={_format_float(status.wake_cooldown_seconds)}, "
        f"sensitivity={_format_float(status.wake_sensitivity)}"
    )


def format_wake_label_note(status: ControlPanelStatus) -> str:
    if status.wake_engine != WAKE_ENGINE_OPENWAKEWORD:
        return "-"
    label = status.wake_model_label or "hey_jarvis"
    return f'当前 openWakeWord model label 是 {label}；中文"贾维斯"不是当前 openWakeWord 自定义中文模型。'


def parse_wake_engine_config_input(
    *,
    engine: str,
    fallback_enabled: bool,
    device_index: str,
    cooldown_seconds: str,
    sensitivity: str,
) -> tuple[WakeEngineConfigUpdate | None, str | None]:
    normalized_engine = engine.strip().lower()
    if normalized_engine not in WAKE_ENGINE_CHOICES:
        return None, "wake.engine 必须是 stt_text 或 openwakeword。"
    try:
        parsed_device = int(device_index.strip())
    except ValueError:
        return None, "device_index 必须是整数。"
    if parsed_device < 0:
        return None, "device_index 必须是非负整数。"
    try:
        parsed_cooldown = float(cooldown_seconds.strip())
    except ValueError:
        return None, "cooldown_seconds 必须是正数。"
    if parsed_cooldown <= 0:
        return None, "cooldown_seconds 必须是正数。"
    try:
        parsed_sensitivity = float(sensitivity.strip())
    except ValueError:
        return None, "sensitivity 必须是 0 到 1 之间的数字。"
    if not 0.0 <= parsed_sensitivity <= 1.0:
        return None, "sensitivity 必须是 0 到 1 之间的数字。"
    return (
        WakeEngineConfigUpdate(
            engine=normalized_engine,
            fallback_enabled=bool(fallback_enabled),
            device_index=parsed_device,
            cooldown_seconds=parsed_cooldown,
            sensitivity=parsed_sensitivity,
        ),
        None,
    )


def is_final_ready_status(status: ControlPanelStatus) -> bool:
    return bool(status.can_wake_now or status.overall_status == READY)


def is_readiness_timeout_error(error: str | None) -> bool:
    return bool(error and any(marker in error for marker in READINESS_TIMEOUT_ERRORS))


def clear_ready_state_error(last_error: str | None, status: ControlPanelStatus) -> str | None:
    if is_final_ready_status(status) and is_readiness_timeout_error(last_error):
        return None
    return last_error


def resolve_operation_result_after_final_status(
    operation_name: str,
    result: ControlOperationResult,
    final_status: ControlPanelStatus,
) -> ControlOperationResult:
    if operation_name not in READINESS_OPERATION_NAMES or not is_final_ready_status(final_status):
        return result
    if operation_name == "重启":
        return ControlOperationResult(True, "重启完成", "小黄已重启并就绪。", result.elapsed_seconds)
    return ControlOperationResult(True, "小黄已就绪", "小黄已启动并就绪。", result.elapsed_seconds)


def resolve_operation_result_after_statuses(
    operation_name: str,
    result: ControlOperationResult,
    statuses: Sequence[ControlPanelStatus | None],
) -> ControlOperationResult:
    resolved = result
    for status in statuses:
        if status is not None:
            resolved = resolve_operation_result_after_final_status(operation_name, resolved, status)
    return resolved


def show_operation_result(messagebox_module, result: ControlOperationResult) -> None:
    if result.ok:
        messagebox_module.showinfo(result.title, result.message)
    else:
        messagebox_module.showerror(result.title, result.message)


def status_with_ui_metadata(
    status: ControlPanelStatus,
    *,
    last_operation: str | None,
    last_operation_elapsed_seconds: float | None,
    last_error: str | None,
) -> ControlPanelStatus:
    return replace(
        status,
        last_operation=last_operation,
        last_operation_elapsed_seconds=last_operation_elapsed_seconds,
        last_error=last_error,
    )


def summarize_exception(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)
    text = re.sub(r"(?i)(token|password|api[_-]?key|secret)\s*=\s*[^,\s;]+", r"\1=***", text)
    text = re.sub(r"(?i)secrets\.ps1[^\s,;]*", "secrets.ps1", text)
    return text[:240]


def apply_operation_ui_result(
    state: dict,
    ui_result: OperationUiResult,
    *,
    render: Callable[[ControlPanelStatus], None],
    set_buttons_enabled: Callable[[bool], None],
    show_result: Callable[[ControlOperationResult], None],
    request_status_refresh: Callable[[], bool],
) -> None:
    if state["closed"]:
        return

    state["refresh_generation"] += 1
    state["operation_completion_pending"] = False
    state["active_operation"] = None
    result = ui_result.result
    if ui_result.final_status is not None:
        result = resolve_operation_result_after_statuses(
            ui_result.operation_name,
            result,
            [ui_result.final_status],
        )
    elif ui_result.error and not result.error:
        result = replace(result, error=ui_result.error)

    state["last_operation"] = ui_result.operation_name
    state["last_elapsed"] = result.elapsed_seconds
    state["last_error"] = result.error
    set_buttons_enabled(True)

    if ui_result.final_status is not None:
        final_status = status_with_ui_metadata(
            ui_result.final_status,
            last_operation=ui_result.operation_name,
            last_operation_elapsed_seconds=result.elapsed_seconds,
            last_error=result.error,
        )
        cleared_error = clear_ready_state_error(result.error, final_status)
        if cleared_error != result.error:
            state["last_error"] = cleared_error
            final_status = status_with_ui_metadata(
                final_status,
                last_operation=ui_result.operation_name,
                last_operation_elapsed_seconds=result.elapsed_seconds,
                last_error=cleared_error,
            )
        state["last_status"] = final_status
        render(final_status)

    request_status_refresh()
    show_result(result)


def collect_operation_ui_result(
    operation_name: str,
    target: Callable[[], ControlOperationResult],
    collect_status: Callable[..., ControlPanelStatus],
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    final_status_grace_seconds: float = OPERATION_FINAL_STATUS_GRACE_SECONDS,
    final_status_poll_seconds: float = OPERATION_FINAL_STATUS_POLL_SECONDS,
) -> OperationUiResult:
    started_at = monotonic()
    try:
        result = target()
    except Exception as exc:
        error = summarize_exception(exc)
        result = ControlOperationResult(
            False,
            "操作异常",
            "操作异常，请查看 logs。",
            round(monotonic() - started_at, 2),
            error,
        )

    final_status, final_error = collect_operation_final_status(
        operation_name,
        result,
        collect_status,
        monotonic=monotonic,
        sleeper=sleeper,
        grace_seconds=final_status_grace_seconds,
        poll_seconds=final_status_poll_seconds,
    )
    return OperationUiResult(
        operation_name=operation_name,
        result=result,
        final_status=final_status,
        error=final_error,
    )


def collect_operation_final_status(
    operation_name: str,
    result: ControlOperationResult,
    collect_status: Callable[..., ControlPanelStatus],
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    grace_seconds: float = OPERATION_FINAL_STATUS_GRACE_SECONDS,
    poll_seconds: float = OPERATION_FINAL_STATUS_POLL_SECONDS,
) -> tuple[ControlPanelStatus | None, str | None]:
    deadline = monotonic() + max(0.0, grace_seconds)
    final_status: ControlPanelStatus | None = None
    final_error: str | None = None

    while True:
        try:
            final_status = collect_status(
                active_operation=None,
                last_operation=operation_name,
                last_operation_elapsed_seconds=result.elapsed_seconds,
                last_error=result.error,
            )
            final_error = None
        except Exception as exc:
            final_status = None
            final_error = summarize_exception(exc)

        if not should_retry_operation_final_status(operation_name, result, final_status):
            return final_status, final_error
        now = monotonic()
        if now >= deadline:
            return final_status, final_error
        sleep_seconds = min(max(0.01, poll_seconds), max(0.0, deadline - now))
        if sleep_seconds <= 0:
            return final_status, final_error
        sleeper(sleep_seconds)


def should_retry_operation_final_status(
    operation_name: str,
    result: ControlOperationResult,
    final_status: ControlPanelStatus | None,
) -> bool:
    if operation_name not in READINESS_OPERATION_NAMES:
        return False
    if not is_readiness_timeout_error(result.error):
        return False
    return final_status is None or not is_final_ready_status(final_status)


def is_config_path_valid(path: Path) -> bool:
    text = str(path or "").strip()
    if not text or text == ".":
        return False
    resolved = Path(path).resolve()
    if resolved.is_dir():
        return False
    return True
