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
    build_status,
    run_restart_operation,
    run_start_operation,
    run_stop_operation,
    stage_markers,
)


READINESS_OPERATION_NAMES = {"启动", "重启"}
READINESS_TIMEOUT_ERRORS = (
    "timeout_voice_overlay_missing",
    "timeout_stt_server_missing",
    "timeout_health_not_ready",
    "timeout",
)


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
    parser = argparse.ArgumentParser(description="XiaoHuang status control panel V1.1.4D-A")
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


def run_control_panel(config_path: Path, refresh_interval_seconds: float) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("Tkinter is not available in this Python environment.")
        return 2

    root = tk.Tk()
    root.title("小黄控制面板")
    root.geometry("680x560")
    root.minsize(620, 500)

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
        ttk.Label(status_frame, textvariable=var, wraplength=520).grid(row=row, column=1, sticky="w", padx=6, pady=3)
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

    def set_buttons_enabled(enabled: bool) -> None:
        state_name = "normal" if enabled else "disabled"
        for button in operation_buttons:
            button.configure(state=state_name)

    def render(status: ControlPanelStatus) -> None:
        title_var.set(status.overall_message)
        if status.can_wake_now:
            hint_var.set("系统已就绪。")
        else:
            hint_var.set("暂时不要说唤醒词，等待系统就绪。")
        field_vars["overall"].set(status.overall_status)
        field_vars["stt"].set(_status_line(status.stt_running) + (" / ready" if status.stt_ready else ""))
        field_vars["overlay"].set(_status_line(status.overlay_running))
        field_vars["health"].set(status.stt_health_status + (" / model_loaded" if status.stt_model_loaded else ""))
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
            "提示：关闭此窗口不会停止小黄。"
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

    def collect_operation_ui_result(operation_name: str, target) -> OperationUiResult:
        started_at = time.monotonic()
        try:
            result = target()
        except Exception as exc:
            error = summarize_exception(exc)
            result = ControlOperationResult(
                False,
                "操作异常",
                "操作异常，请查看 logs。",
                round(time.monotonic() - started_at, 2),
                error,
            )

        final_status = None
        final_error = None
        try:
            final_status = collect_status(
                active_operation=None,
                last_operation=operation_name,
                last_operation_elapsed_seconds=result.elapsed_seconds,
                last_error=result.error,
            )
        except Exception as exc:
            final_error = summarize_exception(exc)

        return OperationUiResult(
            operation_name=operation_name,
            result=result,
            final_status=final_status,
            error=final_error,
        )

    def run_operation(operation_name: str, target) -> None:
        if state["active_operation"]:
            messagebox.showinfo("操作进行中", f"正在执行{state['active_operation']}操作，请稍候。")
            return
        state["active_operation"] = operation_name
        state["last_error"] = None
        state["refresh_generation"] += 1
        set_buttons_enabled(False)
        request_status_refresh()

        def worker() -> None:
            ui_result = collect_operation_ui_result(operation_name, target)
            if not state["closed"]:
                schedule_ui(lambda: finish_operation(ui_result))

        threading.Thread(target=worker, name=f"xiaohuang-control-panel-{operation_name}", daemon=True).start()

    def do_start() -> None:
        run_operation("启动", lambda: run_start_operation(PROJECT_ROOT, config_path))

    def do_stop() -> None:
        run_operation("停止", lambda: run_stop_operation(PROJECT_ROOT))

    def do_restart() -> None:
        run_operation("重启", lambda: run_restart_operation(PROJECT_ROOT, config_path))

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

    bottom_var = tk.StringVar(value="提示：关闭此窗口不会停止小黄。")
    ttk.Label(main, textvariable=bottom_var, foreground="gray", wraplength=620).pack(fill="x", pady=(12, 0))

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
