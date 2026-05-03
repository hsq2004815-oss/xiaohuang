from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from xiaohuang.app_config_service import XiaoHuangConfig, load_config
from xiaohuang.launch_control_service import (
    DEFAULT_HEALTH_URL,
    HealthCheckResult,
    ProcessStatus,
    XiaoHuangProcess,
    build_restart_commands,
    build_start_sequence_for_status,
    build_stop_command,
    check_stt_health,
    detect_xiaohuang_processes,
    summarize_process_status,
    wait_until_ready,
    wait_until_stopped,
)


NOT_RUNNING = "NOT_RUNNING"
STARTING = "STARTING"
LOADING_MODEL = "LOADING_MODEL"
READY = "READY"
PARTIAL = "PARTIAL"
STOPPING = "STOPPING"
RESTARTING = "RESTARTING"
ERROR = "ERROR"


@dataclass(frozen=True)
class ConfigSummary:
    assistant_display_name: str
    wake_phrases: list[str]
    llm_provider: str
    tts_enabled: bool


@dataclass(frozen=True)
class ControlPanelStatus:
    overall_status: str
    overall_message: str
    stt_running: bool
    stt_ready: bool
    stt_health_status: str
    stt_model_loaded: bool
    overlay_running: bool
    config_path: str
    assistant_display_name: str
    wake_phrases: list[str]
    llm_provider: str
    tts_enabled: bool
    last_operation: str | None
    last_operation_elapsed_seconds: float | None
    last_error: str | None
    can_wake_now: bool


@dataclass(frozen=True)
class ControlOperationResult:
    ok: bool
    title: str
    message: str
    elapsed_seconds: float
    error: str | None = None


def build_status(
    project_root: Path,
    config_path: Path,
    *,
    active_operation: str | None = None,
    last_operation: str | None = None,
    last_operation_elapsed_seconds: float | None = None,
    last_error: str | None = None,
    health_url: str = DEFAULT_HEALTH_URL,
    process_detector: Callable[[Path], Sequence[XiaoHuangProcess]] = detect_xiaohuang_processes,
    health_checker: Callable[[str], HealthCheckResult] = check_stt_health,
    config_loader: Callable[[Path], XiaoHuangConfig] = load_config,
) -> ControlPanelStatus:
    process_status = summarize_process_status(process_detector(project_root))
    health = health_checker(health_url)
    config_summary = load_config_summary(config_path, config_loader=config_loader)
    return compute_status(
        process_status,
        health,
        config_path,
        config_summary,
        active_operation=active_operation,
        last_operation=last_operation,
        last_operation_elapsed_seconds=last_operation_elapsed_seconds,
        last_error=last_error,
    )


def run_start_operation(
    project_root: Path,
    config_path: Path,
    *,
    timeout_seconds: float = 90.0,
) -> ControlOperationResult:
    started_at = time.monotonic()
    status = summarize_process_status(detect_xiaohuang_processes(project_root))
    if status.is_fully_running:
        if check_stt_health(DEFAULT_HEALTH_URL).ready:
            return _operation_result(True, "启动小黄", "小黄已在运行。", started_at)
        result = wait_until_ready(project_root, timeout_seconds=timeout_seconds, health_url=DEFAULT_HEALTH_URL)
        if result.ok:
            return _operation_result(True, "小黄已就绪", "小黄已启动并就绪。", started_at)
        return _operation_result(False, "启动未就绪", f"服务已运行，但尚未就绪：{result.reason}", started_at, result.reason)

    commands = build_start_sequence_for_status(status, project_root, config_path)
    for index, command in enumerate(commands):
        is_start_command = index == len(commands) - 1
        label = "启动小黄"
        if len(commands) > 1:
            label = "启动小黄：清理残留" if not is_start_command else "启动小黄：完整启动"
        if is_start_command:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(project_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=False,
                )
            except Exception as exc:
                return _operation_result(False, "启动失败", "启动命令未能发出。", started_at, str(exc))
            result = wait_until_ready(project_root, timeout_seconds=timeout_seconds, health_url=DEFAULT_HEALTH_URL)
            if result.ok:
                return _operation_result(True, "小黄已就绪", "小黄已启动并就绪。", started_at)
            if process.poll() is not None:
                _safe_collect_process(process)
            return _operation_result(False, "启动未就绪", f"启动命令已发出，但服务未就绪：{result.reason}", started_at, result.reason)
        if not _run_blocking_command(command, project_root, label):
            return _operation_result(False, "启动失败", "清理残留进程失败。", started_at, "cleanup_failed")
        stopped = wait_until_stopped(project_root, timeout_seconds=30.0)
        if not stopped.ok:
            return _operation_result(False, "启动失败", "清理残留进程后仍检测到运行进程。", started_at, stopped.reason)
        time.sleep(2)

    return _operation_result(True, "启动小黄", "没有需要执行的启动命令。", started_at)


def run_stop_operation(project_root: Path, *, timeout_seconds: float = 30.0) -> ControlOperationResult:
    started_at = time.monotonic()
    command = build_stop_command(project_root)
    if not _run_blocking_command(command, project_root, "停止小黄"):
        return _operation_result(False, "停止失败", "停止命令失败或超时。", started_at, "stop_command_failed")
    result = wait_until_stopped(project_root, timeout_seconds=timeout_seconds)
    if result.ok:
        return _operation_result(True, "小黄已停止", "小黄相关进程已停止，控制面板仍在运行。", started_at)
    return _operation_result(False, "停止未确认", f"停止命令已发出，但进程未退出：{result.reason}", started_at, result.reason)


def run_restart_operation(
    project_root: Path,
    config_path: Path,
    *,
    timeout_seconds: float = 90.0,
) -> ControlOperationResult:
    started_at = time.monotonic()
    stop_command, start_command = build_restart_commands(project_root, config_path)
    if not _run_blocking_command(stop_command, project_root, "重启小黄：停止"):
        return _operation_result(False, "重启失败", "停止旧进程失败。", started_at, "stop_command_failed")
    stopped = wait_until_stopped(project_root, timeout_seconds=30.0)
    if not stopped.ok:
        return _operation_result(False, "重启失败", f"旧进程未退出：{stopped.reason}", started_at, stopped.reason)
    time.sleep(2)
    try:
        process = subprocess.Popen(
            start_command,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
    except Exception as exc:
        return _operation_result(False, "重启失败", "启动命令未能发出。", started_at, str(exc))
    ready = wait_until_ready(project_root, timeout_seconds=timeout_seconds, health_url=DEFAULT_HEALTH_URL)
    if ready.ok:
        return _operation_result(True, "重启完成", "小黄已重启并就绪。", started_at)
    if process.poll() is not None:
        _safe_collect_process(process)
    return _operation_result(False, "重启未就绪", f"启动命令已发出，但服务未就绪：{ready.reason}", started_at, ready.reason)


def load_config_summary(
    config_path: Path,
    *,
    config_loader: Callable[[Path], XiaoHuangConfig] = load_config,
) -> ConfigSummary:
    config = config_loader(config_path)
    return ConfigSummary(
        assistant_display_name=config.assistant.display_name,
        wake_phrases=list(config.wake.phrases),
        llm_provider=config.llm.provider,
        tts_enabled=bool(config.tts.enabled),
    )


def compute_status(
    process_status: ProcessStatus,
    health: HealthCheckResult,
    config_path: Path,
    config_summary: ConfigSummary,
    *,
    active_operation: str | None = None,
    last_operation: str | None = None,
    last_operation_elapsed_seconds: float | None = None,
    last_error: str | None = None,
) -> ControlPanelStatus:
    health_status = _health_status_text(health)
    model_loaded = _summary_bool(health.summary, "model_loaded")
    stt_ready = bool(process_status.stt_server_running and health.ready)

    overall_status = _overall_status(process_status, health, model_loaded, active_operation)
    can_wake_now = (
        overall_status == READY
        and process_status.stt_server_running
        and stt_ready
        and model_loaded
        and process_status.voice_overlay_running
    )

    display_wake_phrase = config_summary.wake_phrases[0] if config_summary.wake_phrases else "小黄"
    message = _overall_message(
        overall_status,
        can_wake_now=can_wake_now,
        wake_phrase=display_wake_phrase,
        health=health,
    )
    error_summary = last_error or _health_error_summary(process_status, health)

    return ControlPanelStatus(
        overall_status=overall_status,
        overall_message=message,
        stt_running=process_status.stt_server_running,
        stt_ready=stt_ready,
        stt_health_status=health_status,
        stt_model_loaded=model_loaded,
        overlay_running=process_status.voice_overlay_running,
        config_path=str(config_path),
        assistant_display_name=config_summary.assistant_display_name,
        wake_phrases=list(config_summary.wake_phrases),
        llm_provider=config_summary.llm_provider,
        tts_enabled=config_summary.tts_enabled,
        last_operation=last_operation,
        last_operation_elapsed_seconds=last_operation_elapsed_seconds,
        last_error=error_summary,
        can_wake_now=can_wake_now,
    )


def stage_markers(status: ControlPanelStatus) -> list[tuple[str, str]]:
    if status.overall_status == NOT_RUNNING:
        return [
            (" ", "启动 STT server"),
            (" ", "加载 STT 模型"),
            (" ", "启动 voice overlay"),
            (" ", "检查 health"),
            (" ", "已就绪"),
        ]
    return [
        ("✓" if status.stt_running else "~", "启动 STT server"),
        ("✓" if status.stt_model_loaded else "~", "加载 STT 模型"),
        ("✓" if status.overlay_running else " ", "启动 voice overlay"),
        ("✓" if status.stt_ready else "~", "检查 health"),
        ("✓" if status.can_wake_now else " ", "已就绪"),
    ]


def _run_blocking_command(command: list[str], project_root: Path, label: str) -> bool:
    try:
        result = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _safe_collect_process(process: subprocess.Popen[str]) -> None:
    try:
        process.communicate(timeout=0.2)
    except Exception:
        return


def _operation_result(
    ok: bool,
    title: str,
    message: str,
    started_at: float,
    error: str | None = None,
) -> ControlOperationResult:
    return ControlOperationResult(
        ok=ok,
        title=title,
        message=message,
        elapsed_seconds=round(time.monotonic() - started_at, 2),
        error=error,
    )


def _overall_status(
    process_status: ProcessStatus,
    health: HealthCheckResult,
    model_loaded: bool,
    last_operation: str | None,
) -> str:
    if last_operation == "停止":
        return STOPPING
    if last_operation == "重启":
        return RESTARTING
    if last_operation == "启动":
        return STARTING
    if process_status.stt_server_running and health.ready and process_status.voice_overlay_running:
        return READY
    if process_status.stt_server_running and health.ready and not process_status.voice_overlay_running:
        return PARTIAL
    if process_status.stt_server_running and not health.ready:
        return LOADING_MODEL if not model_loaded else STARTING
    if not process_status.stt_server_running and process_status.voice_overlay_running:
        return PARTIAL
    if not process_status.stt_server_running and not process_status.voice_overlay_running:
        return NOT_RUNNING
    return ERROR


def _overall_message(
    overall_status: str,
    *,
    can_wake_now: bool,
    wake_phrase: str,
    health: HealthCheckResult,
) -> str:
    if can_wake_now:
        return f"已就绪，可以说“{wake_phrase}”唤醒。"
    if overall_status == NOT_RUNNING:
        return "小黄未启动。"
    if overall_status == LOADING_MODEL:
        return "正在加载 STT 模型，请稍候，暂时不要说唤醒词。"
    if overall_status == STARTING:
        return "正在启动小黄，请等待系统就绪。"
    if overall_status == PARTIAL:
        return "检测到部分运行状态，暂时不要说唤醒词，建议重启小黄。"
    if overall_status == STOPPING:
        return "正在停止小黄。"
    if overall_status == RESTARTING:
        return "正在重启小黄。"
    if not health.ready and health.summary.startswith("health_unavailable"):
        return "STT health 不可用，请查看日志。"
    return "异常，请查看日志。"


def _health_status_text(health: HealthCheckResult) -> str:
    if health.ready:
        return "ready"
    if health.summary.startswith("health_unavailable"):
        return "unavailable"
    if _summary_bool(health.summary, "model_loaded"):
        return "loading"
    return "loading"


def _health_error_summary(process_status: ProcessStatus, health: HealthCheckResult) -> str | None:
    if health.ready:
        return None
    if not process_status.stt_server_running and not process_status.voice_overlay_running:
        return None
    if process_status.voice_overlay_running and not process_status.stt_server_running:
        return "STT server not detected"
    if health.summary.startswith("health_unavailable"):
        return health.summary
    return None


def _summary_bool(summary: str, key: str) -> bool:
    match = re.search(rf"\b{re.escape(key)}=(True|False|true|false|1|0)\b", summary)
    if not match:
        return False
    return match.group(1).lower() in ("true", "1")
