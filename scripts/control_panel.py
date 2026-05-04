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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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


def _build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(SRC_DIR)
    env["PYTHONPATH"] = src_path + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    env.setdefault("PYTHONUTF8", "1")
    return env


def open_settings(config_path: Path) -> bool:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "settings_ui.py"), "--config", str(config_path)]
    try:
        subprocess.Popen(command, cwd=str(PROJECT_ROOT), env=_build_child_env(), shell=False)
        return True
    except Exception:
        return False


def open_log_dir() -> bool:
    log_dir = ensure_log_dir(PROJECT_ROOT)
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(log_dir))  # type: ignore[attr-defined]
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
    return f"当前 openWakeWord model label 是 {label}；中文“贾维斯”不是当前 openWakeWord 自定义中文模型。"


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


def run_control_panel(config_path: Path, refresh_interval_seconds: float) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("Tkinter is not available in this Python environment.")
        return 2

    root = tk.Tk()
    root.title("小黄控制面板")
    root.geometry("760x760")
    root.minsize(700, 650)

    state = {
        "closed": False,
        "active_operation": None,
        "last_operation": None,
        "last_elapsed": None,
        "last_error": None,
        "last_status": None,
        "refresh_in_progress": False,
        "pending_refresh": False,
        "refresh_generation": 0,
        "operation_completion_pending": False,
        "wake_config_dirty": False,
        "wake_config_syncing": False,
    }
    operation_buttons: list[ttk.Button] = []

    main = ttk.Frame(root, padding=12)
    main.pack(fill="both", expand=True)

    top = ttk.Frame(main)
    top.pack(fill="x")
    title_var = tk.StringVar(value="正在读取状态...")
    ttk.Label(top, textvariable=title_var, font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
    hint_var = tk.StringVar(value="暂时不要说唤醒词，等待系统就绪。")
    ttk.Label(top, textvariable=hint_var, foreground="gray").pack(anchor="w", pady=(4, 0))

    status_frame = ttk.LabelFrame(main, text="状态")
    status_frame.pack(fill="x", pady=(12, 0))
    fields = [
        ("总状态", "overall"),
        ("STT server", "stt"),
        ("Voice overlay", "overlay"),
        ("Health", "health"),
        ("是否可唤醒", "can_wake"),
        ("Wake Engine", "wake_engine"),
        ("Wake fallback", "wake_fallback"),
        ("Wake 参数", "wake_params"),
        ("Wake label", "wake_label"),
        ("助手", "assistant"),
        ("唤醒词", "wake"),
        ("LLM provider", "llm"),
        ("TTS", "tts"),
        ("Config", "config"),
    ]
    field_vars: dict[str, tk.StringVar] = {}
    for row, (label, key) in enumerate(fields):
        ttk.Label(status_frame, text=label + "：").grid(row=row, column=0, sticky="w", padx=10, pady=3)
        var = tk.StringVar(value="-")
        field_vars[key] = var
        ttk.Label(status_frame, textvariable=var, wraplength=620).grid(row=row, column=1, sticky="w", padx=6, pady=3)
    status_frame.columnconfigure(1, weight=1)

    stage_frame = ttk.LabelFrame(main, text="启动阶段")
    stage_frame.pack(fill="x", pady=(12, 0))
    stage_vars = [tk.StringVar(value="[ ] " + name) for name in (
        "启动 STT server",
        "加载 STT 模型",
        "启动 voice overlay",
        "检查 health",
        "已就绪",
    )]
    for index, var in enumerate(stage_vars):
        ttk.Label(stage_frame, textvariable=var).grid(row=index, column=0, sticky="w", padx=10, pady=2)

    actions = ttk.LabelFrame(main, text="操作")
    actions.pack(fill="x", pady=(12, 0))

    wake_engine_var = tk.StringVar(value=WAKE_ENGINE_STT_TEXT)
    wake_fallback_var = tk.BooleanVar(value=True)
    wake_device_var = tk.StringVar(value="0")
    wake_cooldown_var = tk.StringVar(value="2.5")
    wake_sensitivity_var = tk.StringVar(value="0.5")

    def mark_wake_config_dirty(*_args) -> None:
        if not state["wake_config_syncing"]:
            state["wake_config_dirty"] = True

    for variable in (wake_engine_var, wake_fallback_var, wake_device_var, wake_cooldown_var, wake_sensitivity_var):
        variable.trace_add("write", mark_wake_config_dirty)

    def sync_wake_config_fields(status: ControlPanelStatus) -> None:
        if state["wake_config_dirty"]:
            return
        state["wake_config_syncing"] = True
        try:
            wake_engine_var.set(status.wake_engine if status.wake_engine in WAKE_ENGINE_CHOICES else WAKE_ENGINE_STT_TEXT)
            wake_fallback_var.set(bool(status.wake_fallback_enabled))
            wake_device_var.set(str(status.wake_device_index if status.wake_device_index is not None else 0))
            wake_cooldown_var.set(_format_float(status.wake_cooldown_seconds))
            wake_sensitivity_var.set(_format_float(status.wake_sensitivity))
        finally:
            state["wake_config_syncing"] = False

    def set_buttons_enabled(enabled: bool) -> None:
        state_name = "normal" if enabled else "disabled"
        for button in operation_buttons:
            button.configure(state=state_name)

    def render(status: ControlPanelStatus) -> None:
        sync_wake_config_fields(status)
        title_var.set(status.overall_message)
        if status.can_wake_now:
            hint_var.set("系统已就绪。")
        else:
            hint_var.set("暂时不要说唤醒词，等待系统就绪。")
        field_vars["overall"].set(status.overall_status)
        field_vars["stt"].set(_status_line(status.stt_running) + (" / ready" if status.stt_ready else ""))
        field_vars["overlay"].set(_status_line(status.overlay_running))
        field_vars["health"].set(status.stt_health_status + (" / model_loaded" if status.stt_model_loaded else ""))
        field_vars["can_wake"].set("true" if status.can_wake_now else "false")
        field_vars["wake_engine"].set(format_wake_engine_display(status))
        field_vars["wake_fallback"].set(f"fallback_enabled={str(status.wake_fallback_enabled).lower()}")
        field_vars["wake_params"].set(format_wake_params(status))
        field_vars["wake_label"].set(format_wake_label_note(status))
        field_vars["assistant"].set(status.assistant_display_name)
        field_vars["wake"].set(", ".join(status.wake_phrases))
        field_vars["llm"].set(status.llm_provider)
        field_vars["tts"].set("enabled" if status.tts_enabled else "disabled")
        field_vars["config"].set(status.config_path)
        markers = stage_markers(status)
        for var, (mark, text) in zip(stage_vars, markers):
            var.set(f"[{mark}] {text}")
        error_text = status.last_error or "无"
        elapsed_text = "-" if status.last_operation_elapsed_seconds is None else f"{status.last_operation_elapsed_seconds:.1f}s"
        bottom_var.set(
            f"最近操作：{status.last_operation or '-'}    最近耗时：{elapsed_text}\n"
            f"最近错误：{error_text}\n"
            "提示：修改唤醒引擎后需重启小黄生效；关闭此窗口不会停止小黄。"
        )

    def collect_status(
        *,
        active_operation: str | None = None,
        last_operation: str | None = None,
        last_operation_elapsed_seconds: float | None = None,
        last_error: str | None = None,
    ) -> ControlPanelStatus:
        return build_status(
            PROJECT_ROOT,
            config_path,
            active_operation=active_operation,
            last_operation=last_operation,
            last_operation_elapsed_seconds=last_operation_elapsed_seconds,
            last_error=last_error,
        )

    def start_worker(target, name: str) -> None:
        threading.Thread(target=target, name=name, daemon=True).start()

    def schedule_ui(callback) -> None:
        if state["closed"]:
            return
        try:
            root.after(0, callback)
        except Exception:
            state["closed"] = True

    refresh_controller = StatusRefreshController(
        state=state,
        collect_status=collect_status,
        render=render,
        schedule_ui=schedule_ui,
        start_worker=start_worker,
    )

    def request_status_refresh() -> bool:
        return refresh_controller.request()

    def schedule_refresh() -> None:
        if state["closed"]:
            return
        request_status_refresh()
        root.after(max(500, int(refresh_interval_seconds * 1000)), schedule_refresh)

    def finish_operation(ui_result: OperationUiResult) -> None:
        apply_operation_ui_result(
            state,
            ui_result,
            render=render,
            set_buttons_enabled=set_buttons_enabled,
            show_result=lambda result: show_operation_result(messagebox, result),
            request_status_refresh=request_status_refresh,
        )

    def run_operation(operation_name: str, target) -> None:
        if state["active_operation"]:
            messagebox.showinfo("操作进行中", f"正在执行{state['active_operation']}操作，请稍候。")
            return
        state["active_operation"] = operation_name
        state["last_error"] = None
        state["operation_completion_pending"] = False
        state["refresh_generation"] += 1
        set_buttons_enabled(False)
        request_status_refresh()

        def worker() -> None:
            ui_result = collect_operation_ui_result(operation_name, target, collect_status)
            if not state["closed"]:
                state["operation_completion_pending"] = True
                schedule_ui(lambda: finish_operation(ui_result))

        threading.Thread(target=worker, name=f"xiaohuang-control-panel-{operation_name}", daemon=True).start()

    def do_start() -> None:
        run_operation("启动", lambda: run_start_operation(PROJECT_ROOT, config_path))

    def do_stop() -> None:
        run_operation("停止", lambda: run_stop_operation(PROJECT_ROOT))

    def do_restart() -> None:
        run_operation("重启", lambda: run_restart_operation(PROJECT_ROOT, config_path))

    def save_current_wake_config(*, show_popup: bool = True) -> bool:
        update, error = parse_wake_engine_config_input(
            engine=wake_engine_var.get(),
            fallback_enabled=bool(wake_fallback_var.get()),
            device_index=wake_device_var.get(),
            cooldown_seconds=wake_cooldown_var.get(),
            sensitivity=wake_sensitivity_var.get(),
        )
        if error or update is None:
            messagebox.showerror("配置无效", error or "Wake Engine 配置无效。")
            return False
        result = save_wake_engine_config(config_path, update)
        if not result.ok:
            messagebox.showerror("保存失败", result.message)
            return False
        state["wake_config_dirty"] = False
        request_status_refresh()
        if show_popup:
            messagebox.showinfo("配置已保存", result.message)
        return True

    def do_save_wake_config() -> None:
        save_current_wake_config(show_popup=True)

    def do_save_wake_config_and_restart() -> None:
        if state["active_operation"]:
            messagebox.showinfo("操作进行中", f"正在执行{state['active_operation']}操作，请稍候。")
            return
        if save_current_wake_config(show_popup=False):
            messagebox.showinfo("配置已保存", "已保存，正在重启小黄。")
            do_restart()

    operation_buttons.extend([
        ttk.Button(actions, text="启动小黄", command=do_start),
        ttk.Button(actions, text="停止小黄", command=do_stop),
        ttk.Button(actions, text="重启小黄", command=do_restart),
    ])
    for col, button in enumerate(operation_buttons):
        button.grid(row=0, column=col, padx=6, pady=8, sticky="ew")
    ttk.Button(actions, text="刷新状态", command=request_status_refresh).grid(row=0, column=3, padx=6, pady=8, sticky="ew")
    ttk.Button(actions, text="打开设置", command=lambda: open_settings(config_path)).grid(row=0, column=4, padx=6, pady=8, sticky="ew")
    ttk.Button(actions, text="打开日志目录", command=open_log_dir).grid(row=0, column=5, padx=6, pady=8, sticky="ew")
    for col in range(6):
        actions.columnconfigure(col, weight=1)

    wake_config_frame = ttk.LabelFrame(main, text="Wake Engine 配置")
    wake_config_frame.pack(fill="x", pady=(12, 0))
    ttk.Label(wake_config_frame, text="wake.engine：").grid(row=0, column=0, sticky="w", padx=10, pady=4)
    ttk.Combobox(
        wake_config_frame,
        textvariable=wake_engine_var,
        values=WAKE_ENGINE_CHOICES,
        state="readonly",
        width=18,
    ).grid(row=0, column=1, sticky="w", padx=6, pady=4)
    ttk.Checkbutton(
        wake_config_frame,
        text="fallback_enabled",
        variable=wake_fallback_var,
    ).grid(row=0, column=2, sticky="w", padx=6, pady=4)

    ttk.Label(wake_config_frame, text="device_index：").grid(row=1, column=0, sticky="w", padx=10, pady=4)
    ttk.Entry(wake_config_frame, textvariable=wake_device_var, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=4)
    ttk.Label(wake_config_frame, text="cooldown_seconds：").grid(row=1, column=2, sticky="w", padx=6, pady=4)
    ttk.Entry(wake_config_frame, textvariable=wake_cooldown_var, width=10).grid(row=1, column=3, sticky="w", padx=6, pady=4)
    ttk.Label(wake_config_frame, text="sensitivity：").grid(row=1, column=4, sticky="w", padx=6, pady=4)
    ttk.Entry(wake_config_frame, textvariable=wake_sensitivity_var, width=10).grid(row=1, column=5, sticky="w", padx=6, pady=4)

    ttk.Button(wake_config_frame, text="保存配置", command=do_save_wake_config).grid(
        row=2,
        column=0,
        columnspan=2,
        sticky="ew",
        padx=10,
        pady=8,
    )
    save_restart_button = ttk.Button(wake_config_frame, text="保存并重启小黄", command=do_save_wake_config_and_restart)
    save_restart_button.grid(row=2, column=2, columnspan=2, sticky="ew", padx=6, pady=8)
    operation_buttons.append(save_restart_button)
    ttk.Label(
        wake_config_frame,
        text="修改 wake.engine 后需要重启小黄生效。openWakeWord 当前唤醒模型 label 是 hey_jarvis，不是中文“贾维斯”自定义模型。",
        foreground="gray",
        wraplength=680,
    ).grid(row=3, column=0, columnspan=6, sticky="w", padx=10, pady=(0, 8))
    for col in range(6):
        wake_config_frame.columnconfigure(col, weight=1)

    bottom_var = tk.StringVar(value="提示：修改唤醒引擎后需重启小黄生效；关闭此窗口不会停止小黄。")
    ttk.Label(main, textvariable=bottom_var, foreground="gray", wraplength=700).pack(fill="x", pady=(12, 0))

    def on_close() -> None:
        state["closed"] = True
        state["refresh_generation"] += 1
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    request_status_refresh()
    root.after(max(500, int(refresh_interval_seconds * 1000)), schedule_refresh)
    root.mainloop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    refresh_interval = args.refresh_interval if args.refresh_interval > 0 else 2.0
    return run_control_panel(Path(args.config), refresh_interval)


if __name__ == "__main__":
    raise SystemExit(main())
