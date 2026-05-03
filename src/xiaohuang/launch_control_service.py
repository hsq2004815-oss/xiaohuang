from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


DEFAULT_HEALTH_URL = "http://127.0.0.1:8766/health"


@dataclass(frozen=True)
class XiaoHuangProcess:
    process_id: int
    process_type: str


@dataclass(frozen=True)
class ProcessStatus:
    stt_server_running: bool
    voice_overlay_running: bool
    process_count: int

    @property
    def any_running(self) -> bool:
        return self.stt_server_running or self.voice_overlay_running

    @property
    def all_running(self) -> bool:
        return self.stt_server_running and self.voice_overlay_running

    @property
    def is_fully_running(self) -> bool:
        return self.all_running

    @property
    def is_partial(self) -> bool:
        return self.any_running and not self.all_running


@dataclass(frozen=True)
class HealthCheckResult:
    ready: bool
    summary: str


@dataclass(frozen=True)
class WaitResult:
    ok: bool
    reason: str
    status: ProcessStatus
    health: HealthCheckResult | None
    elapsed_seconds: float


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_powershell_executable() -> str:
    return shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"


def build_start_command(
    project_root: Path,
    config_path: Path,
    *,
    powershell_executable: str | None = None,
) -> list[str]:
    return [
        powershell_executable or resolve_powershell_executable(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project_root / "scripts" / "start_xiaohuang.ps1"),
        "-ConfigPath",
        str(config_path),
    ]


def build_stop_command(
    project_root: Path,
    *,
    powershell_executable: str | None = None,
) -> list[str]:
    return [
        powershell_executable or resolve_powershell_executable(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project_root / "scripts" / "stop_xiaohuang.ps1"),
        "-StopSttServer",
    ]


def build_restart_commands(
    project_root: Path,
    config_path: Path,
    *,
    powershell_executable: str | None = None,
) -> list[list[str]]:
    return [
        build_stop_command(project_root, powershell_executable=powershell_executable),
        build_start_command(project_root, config_path, powershell_executable=powershell_executable),
    ]


def build_start_sequence_for_status(
    status: ProcessStatus,
    project_root: Path,
    config_path: Path,
    *,
    powershell_executable: str | None = None,
) -> list[list[str]]:
    if status.is_fully_running:
        return []
    if status.is_partial:
        return build_restart_commands(project_root, config_path, powershell_executable=powershell_executable)
    return [build_start_command(project_root, config_path, powershell_executable=powershell_executable)]


def ensure_log_dir(project_root: Path) -> Path:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def normalize_process_command_line(command_line: str | Path) -> str:
    return str(command_line or "").lower().replace("/", "\\")


def classify_process_command_line(command_line: str, project_root: Path) -> str | None:
    normalized_command = normalize_process_command_line(command_line)
    project_text = normalize_process_command_line(project_root)
    if _contains_script_reference(normalized_command, project_text, "voice_overlay.py"):
        return "voice_overlay"
    if _contains_script_reference(normalized_command, project_text, "stt_server.py"):
        return "stt_server"
    return None


def _contains_script_reference(command_line: str, project_text: str, script_name: str) -> bool:
    script_fragment = f"scripts\\{script_name}"
    project_script = f"{project_text}\\{script_fragment}"
    if project_script in command_line:
        return True

    start = 0
    while True:
        index = command_line.find(script_fragment, start)
        if index < 0:
            break
        prefix = command_line[:index]
        previous = prefix[-1:] if prefix else ""
        previous_pair = prefix[-2:] if len(prefix) >= 2 else prefix
        if not previous or previous in (" ", '"', "'") or previous_pair == ".\\":
            return True
        start = index + len(script_fragment)

    start = 0
    while True:
        index = command_line.find(script_name, start)
        if index < 0:
            return False
        before = command_line[index - 1 : index] if index > 0 else ""
        after_index = index + len(script_name)
        after = command_line[after_index : after_index + 1]
        if before in ("", " ", '"', "'") and after in ("", " ", '"', "'"):
            return True
        start = after_index


def parse_process_rows(rows: object, project_root: Path) -> list[XiaoHuangProcess]:
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []

    processes: list[XiaoHuangProcess] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        command_line = str(row.get("CommandLine") or "")
        process_type = classify_process_command_line(command_line, project_root)
        if not process_type:
            continue
        try:
            process_id = int(row.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        processes.append(XiaoHuangProcess(process_id=process_id, process_type=process_type))
    return processes


def detect_xiaohuang_processes(
    project_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[XiaoHuangProcess]:
    script = r"""
$ErrorActionPreference = "Stop"
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Select-Object ProcessId, CommandLine
$procs | ConvertTo-Json -Compress
"""
    try:
        result = runner(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return parse_process_rows(rows, project_root)


def summarize_process_status(processes: Sequence[XiaoHuangProcess]) -> ProcessStatus:
    stt_server_running = any(process.process_type == "stt_server" for process in processes)
    voice_overlay_running = any(process.process_type == "voice_overlay" for process in processes)
    return ProcessStatus(
        stt_server_running=stt_server_running,
        voice_overlay_running=voice_overlay_running,
        process_count=len(processes),
    )


def check_stt_health(health_url: str = DEFAULT_HEALTH_URL, *, timeout_seconds: float = 2.0) -> HealthCheckResult:
    try:
        with urllib.request.urlopen(health_url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return HealthCheckResult(ready=False, summary=f"health_unavailable:{type(exc).__name__}")

    ok = bool(payload.get("ok"))
    status = str(payload.get("status") or "")
    model_loaded = bool(payload.get("model_loaded"))
    ready = ok and (model_loaded or status.lower() == "ready")
    return HealthCheckResult(
        ready=ready,
        summary=f"ok={ok} status={status or 'unknown'} model_loaded={model_loaded}",
    )


def format_readiness_poll(status: ProcessStatus, health: HealthCheckResult | None) -> str:
    health_label = "ready" if health and health.ready else "not_ready"
    model_loaded = _health_summary_bool(health.summary if health else "", "model_loaded")
    return (
        "readiness poll "
        f"stt={status.stt_server_running} "
        f"overlay={status.voice_overlay_running} "
        f"health={health_label} "
        f"model_loaded={model_loaded}"
    )


def wait_until_ready(
    project_root: Path,
    *,
    timeout_seconds: float = 90.0,
    poll_interval_seconds: float = 2.0,
    health_url: str = DEFAULT_HEALTH_URL,
    process_detector: Callable[[Path], Sequence[XiaoHuangProcess]] = detect_xiaohuang_processes,
    health_checker: Callable[[str], HealthCheckResult] = check_stt_health,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    on_poll: Callable[[str], None] | None = None,
) -> WaitResult:
    started_at = monotonic()
    deadline = started_at + timeout_seconds
    last_status = summarize_process_status([])
    last_health: HealthCheckResult | None = None

    while True:
        now = monotonic()
        processes = process_detector(project_root)
        last_status = summarize_process_status(processes)
        last_health = health_checker(health_url)
        if on_poll:
            try:
                on_poll(format_readiness_poll(last_status, last_health))
            except Exception:
                pass
        if last_status.is_fully_running and last_health.ready:
            return WaitResult(True, "ready", last_status, last_health, now - started_at)
        if now >= deadline:
            reason = "timeout"
            if not last_status.stt_server_running:
                reason = "timeout_stt_server_missing"
            elif not last_status.voice_overlay_running:
                reason = "timeout_voice_overlay_missing"
            elif not last_health.ready:
                reason = "timeout_health_not_ready"
            return WaitResult(False, reason, last_status, last_health, now - started_at)
        sleeper(min(poll_interval_seconds, max(0.0, deadline - now)))


def _health_summary_bool(summary: str, key: str) -> bool:
    normalized = summary.replace(" ", "").lower()
    return f"{key.lower()}=true" in normalized or f"{key.lower()}=1" in normalized


def wait_until_stopped(
    project_root: Path,
    *,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 1.0,
    process_detector: Callable[[Path], Sequence[XiaoHuangProcess]] = detect_xiaohuang_processes,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> WaitResult:
    started_at = monotonic()
    deadline = started_at + timeout_seconds
    last_status = summarize_process_status([])

    while True:
        now = monotonic()
        processes = process_detector(project_root)
        last_status = summarize_process_status(processes)
        if not last_status.any_running:
            return WaitResult(True, "stopped", last_status, None, now - started_at)
        if now >= deadline:
            return WaitResult(False, "timeout_processes_still_running", last_status, None, now - started_at)
        sleeper(min(poll_interval_seconds, max(0.0, deadline - now)))


def format_status_message(status: ProcessStatus, config_path: Path) -> str:
    stt_text = "running" if status.stt_server_running else "not detected"
    overlay_text = "running" if status.voice_overlay_running else "not detected"
    return (
        "小黄托盘控制器 V1.1.4C\n\n"
        f"STT server: {stt_text}\n"
        f"Voice overlay: {overlay_text}\n"
        f"Config: {config_path}"
    )
