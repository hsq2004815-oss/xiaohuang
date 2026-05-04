from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from xiaohuang.app_config_service import XiaoHuangConfig, load_config
from xiaohuang.launch_control_service import (
    DEFAULT_HEALTH_URL,
    HealthCheckResult,
    ProcessStatus,
    WaitResult,
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
WAKE_ENGINE_STT_TEXT = "stt_text"
WAKE_ENGINE_OPENWAKEWORD = "openwakeword"
WAKE_ENGINE_CHOICES = (WAKE_ENGINE_STT_TEXT, WAKE_ENGINE_OPENWAKEWORD)
OPENWAKEWORD_DEFAULT_MODEL_LABEL = "hey_jarvis"


@dataclass(frozen=True)
class ConfigSummary:
    assistant_display_name: str
    wake_phrases: list[str]
    llm_provider: str
    tts_enabled: bool
    wake_engine: str = WAKE_ENGINE_STT_TEXT
    wake_engine_is_default: bool = True
    wake_fallback_enabled: bool = True
    wake_device_index: int | None = None
    wake_cooldown_seconds: float = 2.5
    wake_sensitivity: float = 0.5
    wake_model_label: str | None = None


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
    wake_engine: str = WAKE_ENGINE_STT_TEXT
    wake_engine_is_default: bool = True
    wake_fallback_enabled: bool = True
    wake_device_index: int | None = None
    wake_cooldown_seconds: float = 2.5
    wake_sensitivity: float = 0.5
    wake_model_label: str | None = None


@dataclass(frozen=True)
class ControlOperationResult:
    ok: bool
    title: str
    message: str
    elapsed_seconds: float
    error: str | None = None


@dataclass(frozen=True)
class WakeEngineConfigUpdate:
    engine: str
    fallback_enabled: bool
    device_index: int
    cooldown_seconds: float
    sensitivity: float


@dataclass(frozen=True)
class WakeEngineConfigSaveResult:
    ok: bool
    message: str
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
        current = build_status(project_root, config_path)
        return _resolve_ready_operation_result(
            result,
            current,
            started_at,
            success_title="小黄已就绪",
            success_message="小黄已启动并就绪。",
            failure_title="启动未就绪",
            failure_prefix="服务已运行，但尚未就绪：",
        )

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
            current = build_status(project_root, config_path)
            resolved = _resolve_ready_operation_result(
                result,
                current,
                started_at,
                success_title="小黄已就绪",
                success_message="小黄已启动并就绪。",
                failure_title="启动未就绪",
                failure_prefix="启动命令已发出，但服务未就绪：",
            )
            if process.poll() is not None:
                _safe_collect_process(process)
            return resolved
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
    current = build_status(project_root, config_path)
    resolved = _resolve_ready_operation_result(
        ready,
        current,
        started_at,
        success_title="重启完成",
        success_message="小黄已重启并就绪。",
        failure_title="重启未就绪",
        failure_prefix="启动命令已发出，但服务未就绪：",
    )
    if process.poll() is not None:
        _safe_collect_process(process)
    return resolved


def load_config_summary(
    config_path: Path,
    *,
    config_loader: Callable[[Path], XiaoHuangConfig] = load_config,
) -> ConfigSummary:
    config = config_loader(config_path)
    wake_engine = _normalize_wake_engine(config.wake.engine)
    return ConfigSummary(
        assistant_display_name=config.assistant.display_name,
        wake_phrases=list(config.wake.phrases),
        llm_provider=config.llm.provider,
        tts_enabled=bool(config.tts.enabled),
        wake_engine=wake_engine,
        wake_engine_is_default=not _has_configured_wake_engine(config_path),
        wake_fallback_enabled=bool(config.wake.fallback_enabled),
        wake_device_index=config.wake.device_index,
        wake_cooldown_seconds=float(config.wake.cooldown_seconds),
        wake_sensitivity=float(config.wake.sensitivity),
        wake_model_label=_resolve_wake_model_label(wake_engine, config.wake.model_name),
    )


def save_wake_engine_config(config_path: Path, update: WakeEngineConfigUpdate) -> WakeEngineConfigSaveResult:
    error = _validate_wake_engine_update(update)
    if error:
        return WakeEngineConfigSaveResult(False, error, error)

    resolved = Path(config_path)
    if not resolved.exists():
        message = f"配置文件不存在：{resolved}"
        return WakeEngineConfigSaveResult(False, message, "config_not_found")

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        message = f"配置 JSON 无法解析：{exc}"
        return WakeEngineConfigSaveResult(False, message, "invalid_json")
    except Exception as exc:
        message = f"配置文件读取失败：{exc}"
        return WakeEngineConfigSaveResult(False, message, "read_failed")

    if not isinstance(data, dict):
        message = "配置根节点必须是 JSON object。"
        return WakeEngineConfigSaveResult(False, message, "invalid_root")

    wake_data = data.get("wake")
    if wake_data is None:
        wake_data = {}
        data["wake"] = wake_data
    elif not isinstance(wake_data, dict):
        message = "wake 配置必须是 JSON object。"
        return WakeEngineConfigSaveResult(False, message, "invalid_wake")

    wake_data["engine"] = _normalize_wake_engine(update.engine)
    wake_data["fallback_enabled"] = bool(update.fallback_enabled)
    wake_data["device_index"] = int(update.device_index)
    wake_data["cooldown_seconds"] = float(update.cooldown_seconds)
    wake_data["sensitivity"] = float(update.sensitivity)

    try:
        resolved.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        message = f"配置文件保存失败：{exc}"
        return WakeEngineConfigSaveResult(False, message, "write_failed")

    return WakeEngineConfigSaveResult(True, "已保存，重启小黄后生效")


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
        wake_engine=config_summary.wake_engine,
        wake_engine_is_default=config_summary.wake_engine_is_default,
        wake_fallback_enabled=config_summary.wake_fallback_enabled,
        wake_device_index=config_summary.wake_device_index,
        wake_cooldown_seconds=config_summary.wake_cooldown_seconds,
        wake_sensitivity=config_summary.wake_sensitivity,
        wake_model_label=config_summary.wake_model_label,
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


def _resolve_ready_operation_result(
    wait_result: WaitResult,
    current_status: ControlPanelStatus,
    started_at: float,
    *,
    success_title: str,
    success_message: str,
    failure_title: str,
    failure_prefix: str,
) -> ControlOperationResult:
    if wait_result.ok or current_status.can_wake_now:
        return _operation_result(True, success_title, success_message, started_at)
    return _operation_result(
        False,
        failure_title,
        f"{failure_prefix}{wait_result.reason}",
        started_at,
        wait_result.reason,
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


def _normalize_wake_engine(value: Any) -> str:
    engine = str(value).strip().lower() if value is not None else ""
    return engine if engine in WAKE_ENGINE_CHOICES else WAKE_ENGINE_STT_TEXT


def _resolve_wake_model_label(wake_engine: str, configured_model_name: str | None) -> str | None:
    if wake_engine != WAKE_ENGINE_OPENWAKEWORD:
        return None
    return configured_model_name or OPENWAKEWORD_DEFAULT_MODEL_LABEL


def _has_configured_wake_engine(config_path: Path) -> bool:
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    wake_data = data.get("wake")
    if not isinstance(wake_data, dict):
        return False
    engine = wake_data.get("engine")
    return isinstance(engine, str) and bool(engine.strip())


def _validate_wake_engine_update(update: WakeEngineConfigUpdate) -> str | None:
    if _normalize_wake_engine(update.engine) != str(update.engine).strip().lower():
        return "wake.engine 必须是 stt_text 或 openwakeword。"
    if not isinstance(update.fallback_enabled, bool):
        return "fallback_enabled 必须是 true 或 false。"
    if isinstance(update.device_index, bool) or not isinstance(update.device_index, int):
        return "device_index 必须是整数。"
    if update.device_index < 0:
        return "device_index 必须是非负整数。"
    try:
        cooldown_seconds = float(update.cooldown_seconds)
    except (TypeError, ValueError):
        return "cooldown_seconds 必须是正数。"
    if cooldown_seconds <= 0:
        return "cooldown_seconds 必须是正数。"
    try:
        sensitivity = float(update.sensitivity)
    except (TypeError, ValueError):
        return "sensitivity 必须是 0 到 1 之间的数字。"
    if not 0.0 <= sensitivity <= 1.0:
        return "sensitivity 必须是 0 到 1 之间的数字。"
    return None
