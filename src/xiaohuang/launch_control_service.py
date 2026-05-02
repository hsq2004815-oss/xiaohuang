from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


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


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_start_command(project_root: Path, config_path: Path) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project_root / "scripts" / "start_xiaohuang.ps1"),
        "-ConfigPath",
        str(config_path),
    ]


def build_stop_command(project_root: Path) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project_root / "scripts" / "stop_xiaohuang.ps1"),
        "-StopSttServer",
    ]


def build_restart_commands(project_root: Path, config_path: Path) -> list[list[str]]:
    return [
        build_stop_command(project_root),
        build_start_command(project_root, config_path),
    ]


def ensure_log_dir(project_root: Path) -> Path:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def classify_process_command_line(command_line: str, project_root: Path) -> str | None:
    lower_command = command_line.lower()
    project_text = str(project_root).lower()
    if project_text not in lower_command and "xiaohuang" not in lower_command:
        return None
    if "voice_overlay.py" in lower_command or "voice_overlay" in lower_command:
        return "voice_overlay"
    if "stt_server.py" in lower_command or "stt_server" in lower_command:
        return "stt_server"
    return None


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


def format_status_message(status: ProcessStatus, config_path: Path) -> str:
    stt_text = "running" if status.stt_server_running else "not detected"
    overlay_text = "running" if status.voice_overlay_running else "not detected"
    return (
        "小黄托盘控制器 V1.1.4C\n\n"
        f"STT server: {stt_text}\n"
        f"Voice overlay: {overlay_text}\n"
        f"Config: {config_path}"
    )
