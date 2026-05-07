"""control_panel_ui.py — Tkinter UI for the XiaoHuang control panel.

Extracted from scripts/control_panel.py. Contains only the UI assembly;
all pure logic lives in control_panel_app.py.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from xiaohuang.control_panel_app import (
    StatusRefreshController,
    apply_operation_ui_result,
    collect_operation_ui_result,
    format_wake_engine_display,
    format_wake_label_note,
    format_wake_params,
    is_config_path_valid,
    open_log_dir,
    open_settings,
    parse_wake_engine_config_input,
    show_operation_result,
    stage_markers,
    _format_float,
    _status_line,
)
from xiaohuang.status_control_service import (
    WAKE_ENGINE_CHOICES,
    WAKE_ENGINE_STT_TEXT,
    ControlPanelStatus,
    build_status,
    run_restart_operation,
    run_start_operation,
    run_stop_operation,
    save_wake_engine_config,
)


def run_control_panel(
    project_root: Path,
    config_path: Path,
    refresh_interval_seconds: float,
    *,
    src_dir: str = "",
) -> int:
    config_path = config_path.resolve()
    config_valid = is_config_path_valid(config_path)

    root = tk.Tk()
    root.title("小黄控制面板")
    root.geometry("760x650")
    root.minsize(620, 480)

    # --- scrollable canvas ---
    canvas = tk.Canvas(root, highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)

    main = ttk.Frame(canvas, padding=12)
    main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    _canvas_window = canvas.create_window((0, 0), window=main, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    def _on_canvas_width(event):
        canvas.itemconfig(_canvas_window, width=event.width)

    canvas.bind("<Configure>", _on_canvas_width)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_mw(_event):
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _unbind_mw(_event):
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<MouseWheel>", _on_mousewheel)
    canvas.bind("<Enter>", _bind_mw)
    canvas.bind("<Leave>", _unbind_mw)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

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
        field_vars["config"].set(str(config_path))
        markers = stage_markers(status)
        for var, (mark, text) in zip(stage_vars, markers):
            var.set(f"[{mark}] {text}")
        error_text = status.last_error or "无"
        elapsed_text = "-" if status.last_operation_elapsed_seconds is None else f"{status.last_operation_elapsed_seconds:.1f}s"
        if not config_valid:
            dirty_hint = "配置文件路径无效，无法保存 Wake Engine 配置"
        elif state["wake_config_dirty"]:
            dirty_hint = "下方 Wake Engine 配置已修改，请点击保存"
        else:
            dirty_hint = ""
        wake_dirty_var.set(dirty_hint)
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
            project_root,
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

    def finish_operation(ui_result) -> None:
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
        run_operation("启动", lambda: run_start_operation(project_root, config_path))

    def do_stop() -> None:
        run_operation("停止", lambda: run_stop_operation(project_root))

    def do_restart() -> None:
        run_operation("重启", lambda: run_restart_operation(project_root, config_path))

    def save_current_wake_config(*, show_popup: bool = True) -> bool:
        if not config_valid:
            messagebox.showerror("无法保存", "配置文件路径无效，无法保存。")
            return False
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
    ttk.Button(actions, text="打开设置", command=lambda: open_settings(project_root, config_path, src_dir)).grid(row=0, column=4, padx=6, pady=8, sticky="ew")
    ttk.Button(actions, text="打开日志目录", command=lambda: open_log_dir(project_root)).grid(row=0, column=5, padx=6, pady=8, sticky="ew")
    for col in range(6):
        actions.columnconfigure(col, weight=1)

    wake_config_frame = ttk.LabelFrame(main, text="Wake Engine 配置", padding=(14, 8))
    wake_config_frame.pack(fill="x", pady=(10, 0))

    # --- row 0: engine dropdown | fallback toggle | restart hint ---
    ttk.Label(wake_config_frame, text="wake.engine：").grid(
        row=0, column=0, sticky="w", padx=(0, 4), pady=3,
    )
    ttk.Combobox(
        wake_config_frame,
        textvariable=wake_engine_var,
        values=WAKE_ENGINE_CHOICES,
        state="readonly",
        width=14,
    ).grid(row=0, column=1, sticky="w", padx=(0, 14), pady=3)
    ttk.Checkbutton(
        wake_config_frame,
        text="fallback_enabled",
        variable=wake_fallback_var,
    ).grid(row=0, column=2, sticky="w", padx=(0, 14), pady=3)
    ttk.Label(
        wake_config_frame,
        text="修改后需重启小黄生效",
        foreground="gray",
    ).grid(row=0, column=3, sticky="e", padx=(0, 0), pady=3)

    # --- row 1: device_index | cooldown_seconds | sensitivity ---
    ttk.Label(wake_config_frame, text="device_index：").grid(
        row=1, column=0, sticky="w", padx=(0, 4), pady=3,
    )
    ttk.Entry(wake_config_frame, textvariable=wake_device_var, width=7).grid(
        row=1, column=1, sticky="w", padx=(0, 14), pady=3,
    )
    ttk.Label(wake_config_frame, text="cooldown_seconds：").grid(
        row=1, column=2, sticky="w", padx=(0, 4), pady=3,
    )
    ttk.Entry(wake_config_frame, textvariable=wake_cooldown_var, width=7).grid(
        row=1, column=3, sticky="w", padx=(0, 14), pady=3,
    )
    ttk.Label(wake_config_frame, text="sensitivity：").grid(
        row=1, column=4, sticky="w", padx=(0, 4), pady=3,
    )
    ttk.Entry(wake_config_frame, textvariable=wake_sensitivity_var, width=7).grid(
        row=1, column=5, sticky="w", padx=(0, 0), pady=3,
    )

    # --- row 2: action buttons ---
    ttk.Button(wake_config_frame, text="保存配置", command=do_save_wake_config).grid(
        row=2, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(8, 2),
    )
    save_restart_button = ttk.Button(wake_config_frame, text="保存并重启小黄", command=do_save_wake_config_and_restart)
    save_restart_button.grid(row=2, column=2, columnspan=2, sticky="ew", padx=(0, 8), pady=(8, 2))
    operation_buttons.append(save_restart_button)

    # --- row 3: unsaved hint (shown only when dirty) ---
    wake_dirty_var = tk.StringVar(value="")
    ttk.Label(
        wake_config_frame,
        textvariable=wake_dirty_var,
        foreground="#e67e22",
    ).grid(row=3, column=0, columnspan=6, sticky="w", padx=(0, 0), pady=(0, 2))

    # --- row 4: openWakeWord label note ---
    ttk.Label(
        wake_config_frame,
        text='openWakeWord 当前唤醒模型 label 是 hey_jarvis，不是中文"贾维斯"自定义模型。',
        foreground="gray",
        wraplength=480,
    ).grid(row=4, column=0, columnspan=6, sticky="w", padx=(0, 0), pady=(0, 4))

    wake_config_frame.columnconfigure(5, weight=1)

    bottom_var = tk.StringVar(value="提示：修改唤醒引擎后需重启小黄生效；关闭此窗口不会停止小黄。")
    ttk.Label(main, textvariable=bottom_var, foreground="gray", wraplength=700).pack(fill="x", pady=(8, 4))

    def on_close() -> None:
        state["closed"] = True
        state["refresh_generation"] += 1
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    request_status_refresh()
    root.after(max(500, int(refresh_interval_seconds * 1000)), schedule_refresh)
    root.mainloop()
    return 0
