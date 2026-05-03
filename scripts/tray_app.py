from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
LOG_DIR = PROJECT_ROOT / "logs"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from xiaohuang.launch_control_service import (
    build_restart_commands,
    build_start_command,
    build_start_sequence_for_status,
    build_stop_command,
    DEFAULT_HEALTH_URL,
    detect_xiaohuang_processes,
    ensure_log_dir as ensure_launch_log_dir,
    format_status_message,
    summarize_process_status,
    wait_until_ready,
    wait_until_stopped,
)

READINESS_TIMEOUT_SECONDS = 90.0
STOP_TIMEOUT_SECONDS = 30.0


class OperationGuard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_operation: str | None = None

    def begin(self, operation_name: str) -> tuple[bool, str | None]:
        with self._lock:
            if self._current_operation:
                return False, self._current_operation
            self._current_operation = operation_name
            return True, operation_name

    def finish(self) -> None:
        with self._lock:
            self._current_operation = None

    @property
    def current_operation(self) -> str | None:
        with self._lock:
            return self._current_operation


OPERATION_GUARD = OperationGuard()


@dataclass(frozen=True)
class OperationResult:
    title: str
    message: str
    error: bool = False


def get_default_config_path(env: Mapping[str, str] | None = None) -> Path:
    env_map = env or os.environ
    user_profile = env_map.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / ".xiaohuang" / "config.json"
    return Path.home() / ".xiaohuang" / "config.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XiaoHuang tray launch controller V1.1.4C")
    parser.add_argument(
        "--config",
        default=str(get_default_config_path()),
        help="Path to config.json. Defaults to %%USERPROFILE%%\\.xiaohuang\\config.json",
    )
    return parser.parse_args(argv)


def ensure_log_dir(project_root: Path = PROJECT_ROOT) -> Path:
    return ensure_launch_log_dir(project_root)


def build_settings_command(
    config_path: Path,
    *,
    python_executable: str = sys.executable,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    return [
        python_executable,
        str(project_root / "scripts" / "settings_ui.py"),
        "--config",
        str(config_path),
    ]


def build_control_panel_command(
    config_path: Path,
    *,
    python_executable: str = sys.executable,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    return [
        python_executable,
        str(project_root / "scripts" / "control_panel.py"),
        "--config",
        str(config_path),
    ]


def write_tray_log(message: str, *, project_root: Path = PROJECT_ROOT) -> None:
    log_dir = ensure_log_dir(project_root)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {message}\n"
    try:
        with (log_dir / "tray_app.log").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        print(line, end="")


def _build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_path = str(SRC_DIR)
    if existing_pythonpath:
        env["PYTHONPATH"] = src_path + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = src_path
    env.setdefault("PYTHONUTF8", "1")
    return env


def show_message(title: str, message: str, *, error: bool = False) -> None:
    try:
        from tkinter import messagebox
        if error:
            messagebox.showerror(title, message)
        else:
            messagebox.showinfo(title, message)
    except Exception:
        prefix = "ERROR" if error else "INFO"
        print(f"{prefix}: {title}: {message}")


def open_settings(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> bool:
    command = build_settings_command(config_path, project_root=project_root)
    try:
        write_tray_log(f"open_settings config={config_path}", project_root=project_root)
        subprocess.Popen(command, cwd=str(project_root), env=_build_child_env())
        return True
    except Exception as exc:
        write_tray_log(f"open_settings failed: {exc}", project_root=project_root)
        show_message("打开设置失败", "无法打开 Settings UI，请查看 logs/tray_app.log", error=True)
        return False


def open_control_panel(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> bool:
    command = build_control_panel_command(config_path, project_root=project_root)
    try:
        write_tray_log(f"open_control_panel config={config_path}", project_root=project_root)
        subprocess.Popen(command, cwd=str(project_root), env=_build_child_env())
        return True
    except Exception as exc:
        write_tray_log(f"open_control_panel failed: {exc}", project_root=project_root)
        show_message("打开控制面板失败", "无法打开控制面板，请查看 logs/tray_app.log", error=True)
        return False


def open_log_dir(*, project_root: Path = PROJECT_ROOT) -> bool:
    log_dir = ensure_log_dir(project_root)
    try:
        write_tray_log(f"open_log_dir path={log_dir}", project_root=project_root)
        if hasattr(os, "startfile"):
            os.startfile(str(log_dir))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["explorer.exe", str(log_dir)])
        return True
    except Exception as exc:
        write_tray_log(f"open_log_dir failed: {exc}", project_root=project_root)
        show_message("打开日志目录失败", "无法打开 logs 目录，请查看 logs/tray_app.log", error=True)
        return False


def _run_background(name: str, target, *args) -> None:
    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()


def _execute_guarded_operation(operation_name: str, target, *args, guard: OperationGuard = OPERATION_GUARD) -> bool:
    started, current_operation = guard.begin(operation_name)
    if not started:
        show_message("操作进行中", f"正在执行{current_operation}操作，请稍候。")
        return False

    write_tray_log(f"operation={operation_name} acquired")
    result = OperationResult("操作失败", "操作异常，请查看 logs/tray_app.log。", error=True)
    release_reason = "exception"
    try:
        result = target(*args) or OperationResult("操作完成", "操作已结束。")
        release_reason = "success" if not result.error else "error"
    except Exception as exc:
        write_tray_log(f"operation={operation_name} exception: {exc}")
        result = OperationResult("操作异常", "操作异常，请查看 logs/tray_app.log。", error=True)
        release_reason = "exception"
    finally:
        guard.finish()
        write_tray_log(f"operation={operation_name} release reason={release_reason}")

    try:
        show_message(result.title, result.message, error=result.error)
    except Exception as exc:
        write_tray_log(f"operation={operation_name} messagebox failed after release: {exc}")
    return True


def _run_guarded_background(operation_name: str, target, *args) -> None:
    _run_background(f"xiaohuang-{operation_name}", _execute_guarded_operation, operation_name, target, *args)


def _sanitize_process_output(text: str, *, max_chars: int = 3000) -> str:
    redacted = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)
    redacted = re.sub(r"(DEEPSEEK_API_KEY\s*=\s*)\S+", r"\1***", redacted)
    if len(redacted) > max_chars:
        return redacted[:max_chars] + "\n...[truncated]"
    return redacted


def _write_command_output(label: str, stdout: str, stderr: str, *, project_root: Path = PROJECT_ROOT) -> None:
    if stdout.strip():
        write_tray_log(f"{label} stdout: {_sanitize_process_output(stdout).strip()}", project_root=project_root)
    if stderr.strip():
        write_tray_log(f"{label} stderr: {_sanitize_process_output(stderr).strip()}", project_root=project_root)


def _run_command(command: list[str], label: str, *, project_root: Path = PROJECT_ROOT, timeout: int = 120) -> bool:
    try:
        write_tray_log(f"{label} started", project_root=project_root)
        write_tray_log(f"{label} argv={_sanitize_process_output(repr(command))}", project_root=project_root)
        result = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_child_env(),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        write_tray_log(f"{label} timeout", project_root=project_root)
        show_message(label, "操作超时，请查看 logs/tray_app.log", error=True)
        return False
    except Exception as exc:
        write_tray_log(f"{label} failed: {exc}", project_root=project_root)
        show_message(label, "操作失败，请查看 logs/tray_app.log", error=True)
        return False

    write_tray_log(f"{label} completed returncode={result.returncode}", project_root=project_root)
    _write_command_output(label, result.stdout, result.stderr, project_root=project_root)
    if result.returncode != 0:
        show_message(label, "操作返回错误，请查看 logs/tray_app.log", error=True)
        return False
    return True


def _launch_command_async(
    command: list[str],
    label: str,
    *,
    project_root: Path = PROJECT_ROOT,
) -> subprocess.Popen | None:
    try:
        write_tray_log(f"{label} started async", project_root=project_root)
        write_tray_log(f"{label} argv={_sanitize_process_output(repr(command))}", project_root=project_root)
        process = subprocess.Popen(
            command,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_build_child_env(),
            shell=False,
        )
        write_tray_log(f"{label} pid={process.pid}", project_root=project_root)
        return process
    except Exception as exc:
        write_tray_log(f"{label} async launch failed: {exc}", project_root=project_root)
        return None


def _log_async_process_summary(label: str, process: subprocess.Popen | None, *, project_root: Path = PROJECT_ROOT) -> None:
    if process is None:
        write_tray_log(f"{label} async process missing", project_root=project_root)
        return
    returncode = process.poll()
    if returncode is None:
        write_tray_log(f"{label} async process still running pid={process.pid}", project_root=project_root)
        return
    write_tray_log(f"{label} async process returncode={returncode}", project_root=project_root)
    try:
        stdout, stderr = process.communicate(timeout=0.2)
    except Exception as exc:
        write_tray_log(f"{label} async output unavailable: {exc}", project_root=project_root)
        return
    _write_command_output(label, stdout or "", stderr or "", project_root=project_root)


def get_process_status(*, project_root: Path = PROJECT_ROOT):
    return summarize_process_status(detect_xiaohuang_processes(project_root))


def _log_wait_result(operation: str, result, *, project_root: Path = PROJECT_ROOT) -> None:
    health_summary = result.health.summary if result.health else "none"
    write_tray_log(
        (
            f"{operation} wait_result ok={result.ok} reason={result.reason} "
            f"elapsed={result.elapsed_seconds:.1f}s "
            f"stt={result.status.stt_server_running} overlay={result.status.voice_overlay_running} "
            f"health={_sanitize_process_output(health_summary)}"
        ),
        project_root=project_root,
    )


def _wait_ready_result(success_message: str, *, project_root: Path = PROJECT_ROOT) -> OperationResult:
    write_tray_log("readiness polling started", project_root=project_root)
    result = wait_until_ready(
        project_root,
        timeout_seconds=READINESS_TIMEOUT_SECONDS,
        poll_interval_seconds=2.0,
        health_url=DEFAULT_HEALTH_URL,
    )
    _log_wait_result("readiness", result, project_root=project_root)
    if result.ok:
        return OperationResult("小黄已就绪", success_message)
    return OperationResult(
        "启动未就绪",
        "启动命令已发出，但服务未在限定时间内就绪，请查看 logs/tray_app.log。",
        error=True,
    )


def _wait_stopped_result(success_message: str | None, *, project_root: Path = PROJECT_ROOT) -> OperationResult:
    write_tray_log("stop polling started", project_root=project_root)
    result = wait_until_stopped(
        project_root,
        timeout_seconds=STOP_TIMEOUT_SECONDS,
        poll_interval_seconds=1.0,
    )
    _log_wait_result("stopped", result, project_root=project_root)
    if result.ok:
        return OperationResult("小黄已停止", success_message or "小黄相关进程已停止。")
    return OperationResult("停止未确认", "停止命令已发出，但进程未在限定时间内退出，请查看 logs/tray_app.log。", error=True)


def start_xiaohuang(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> OperationResult:
    status = get_process_status(project_root=project_root)
    if status.is_fully_running:
        write_tray_log("start_xiaohuang skipped: fully running", project_root=project_root)
        return OperationResult("启动小黄", "小黄已在运行。")

    commands = build_start_sequence_for_status(status, project_root, config_path)
    if status.is_partial:
        write_tray_log(
            "start_xiaohuang detected partial state; stopping before full start",
            project_root=project_root,
        )
        show_message("启动小黄", "检测到小黄处于不完整状态，正在重新启动完整链路。")
    else:
        show_message("启动小黄", "正在启动小黄，请稍候。首次加载 STT 模型可能需要十几秒。")

    for index, command in enumerate(commands):
        label = "启动小黄"
        if len(commands) > 1:
            label = "启动小黄：清理残留" if index == 0 else "启动小黄：完整启动"
        is_start_command = index == len(commands) - 1
        if is_start_command:
            process = _launch_command_async(command, label, project_root=project_root)
            if process is None:
                return OperationResult("启动失败", "启动命令未能发出，请查看 logs/tray_app.log。", error=True)
            result = _wait_ready_result("小黄已启动并就绪，可以说“贾维斯”唤醒。", project_root=project_root)
            _log_async_process_summary(label, process, project_root=project_root)
            return result

        if not _run_command(command, label, project_root=project_root, timeout=60):
            return OperationResult("启动失败", "清理残留进程失败，请查看 logs/tray_app.log。", error=True)
        if index == 0 and len(commands) > 1:
            stopped = _wait_stopped_result(None, project_root=project_root)
            if stopped.error:
                return stopped
            time.sleep(2)

    return OperationResult("启动小黄", "没有需要执行的启动命令。")


def stop_xiaohuang(*, project_root: Path = PROJECT_ROOT) -> OperationResult:
    show_message("停止小黄", "正在停止小黄，请稍候。")
    command = build_stop_command(project_root)
    if _run_command(command, "停止小黄", project_root=project_root):
        return _wait_stopped_result("小黄已停止，托盘仍在运行。", project_root=project_root)
    return OperationResult("停止失败", "停止命令失败或超时，请查看 logs/tray_app.log。", error=True)


def restart_xiaohuang(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> OperationResult:
    show_message("重启小黄", "正在重启小黄，请稍候。首次加载 STT 模型可能需要十几秒。")
    stop_command, start_command = build_restart_commands(project_root, config_path)
    if not _run_command(stop_command, "重启小黄：停止", project_root=project_root, timeout=60):
        return OperationResult("重启失败", "停止旧进程失败，请查看 logs/tray_app.log。", error=True)
    stopped = _wait_stopped_result(None, project_root=project_root)
    if stopped.error:
        return OperationResult("重启失败", stopped.message, error=True)
    time.sleep(2)
    process = _launch_command_async(start_command, "重启小黄：启动", project_root=project_root)
    if process is None:
        return OperationResult("重启失败", "启动命令未能发出，请查看 logs/tray_app.log。", error=True)
    result = _wait_ready_result("重启完成，小黄已就绪。", project_root=project_root)
    _log_async_process_summary("重启小黄：启动", process, project_root=project_root)
    return result


def show_about(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> None:
    status = get_process_status(project_root=project_root)
    show_message(
        "小黄托盘控制器",
        format_status_message(status, config_path),
    )


def exit_tray(icon) -> None:
    write_tray_log("exit_tray")
    icon.stop()


def create_tray_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (16, 20, 24, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(167, 139, 250, 255))
    draw.ellipse((20, 20, 44, 44), fill=(16, 20, 24, 255))
    draw.rectangle((30, 10, 34, 54), fill=(245, 247, 250, 255))
    return image


def run_tray(config_path: Path) -> int:
    try:
        import pystray
    except ImportError:
        print("Missing dependency: pystray. Install requirements.txt before running the tray app.")
        return 2

    try:
        image = create_tray_image()
    except ImportError:
        print("Missing dependency: Pillow. Install requirements.txt before running the tray app.")
        return 2

    write_tray_log("tray_app started")

    icon = pystray.Icon(
        "xiaohuang_tray",
        image,
        "小黄托盘控制器",
        menu=pystray.Menu(
            pystray.MenuItem("启动小黄", lambda _icon, _item: _run_guarded_background("启动", start_xiaohuang, config_path)),
            pystray.MenuItem("停止小黄", lambda _icon, _item: _run_guarded_background("停止", stop_xiaohuang)),
            pystray.MenuItem("重启小黄", lambda _icon, _item: _run_guarded_background("重启", restart_xiaohuang, config_path)),
            pystray.MenuItem("打开控制面板", lambda _icon, _item: open_control_panel(config_path)),
            pystray.MenuItem("打开设置", lambda _icon, _item: open_settings(config_path)),
            pystray.MenuItem("打开日志目录", lambda _icon, _item: open_log_dir()),
            pystray.MenuItem("关于/状态", lambda _icon, _item: show_about(config_path)),
            pystray.MenuItem("退出托盘", lambda icon_obj, _item: exit_tray(icon_obj)),
        ),
    )
    icon.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_tray(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
