from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
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
    detect_xiaohuang_processes,
    ensure_log_dir as ensure_launch_log_dir,
    format_status_message,
    summarize_process_status,
)


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
        result = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_child_env(),
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


def get_process_status(*, project_root: Path = PROJECT_ROOT):
    return summarize_process_status(detect_xiaohuang_processes(project_root))


def start_xiaohuang(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> None:
    status = get_process_status(project_root=project_root)
    if status.is_fully_running:
        write_tray_log("start_xiaohuang skipped: fully running", project_root=project_root)
        show_message("启动小黄", "小黄已在运行。")
        return

    commands = build_start_sequence_for_status(status, project_root, config_path)
    if status.is_partial:
        write_tray_log(
            "start_xiaohuang detected partial state; stopping before full start",
            project_root=project_root,
        )
        show_message("启动小黄", "检测到小黄处于不完整状态，正在重新启动完整链路。")

    for index, command in enumerate(commands):
        label = "启动小黄"
        if len(commands) > 1:
            label = "启动小黄：清理残留" if index == 0 else "启动小黄：完整启动"
        timeout = 60 if index == 0 and len(commands) > 1 else 120
        if not _run_command(command, label, project_root=project_root, timeout=timeout):
            return
        if index == 0 and len(commands) > 1:
            time.sleep(2)

    if commands:
        show_message("启动小黄", "启动命令已完成。")


def stop_xiaohuang(*, project_root: Path = PROJECT_ROOT) -> None:
    command = build_stop_command(project_root)
    if _run_command(command, "停止小黄", project_root=project_root):
        show_message("停止小黄", "停止命令已完成。")


def restart_xiaohuang(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> None:
    stop_command, start_command = build_restart_commands(project_root, config_path)
    if not _run_command(stop_command, "重启小黄：停止", project_root=project_root, timeout=60):
        return
    time.sleep(2)
    if _run_command(start_command, "重启小黄：启动", project_root=project_root):
        show_message("重启小黄", "重启命令已完成。")


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
            pystray.MenuItem("启动小黄", lambda _icon, _item: _run_background("xiaohuang-start", start_xiaohuang, config_path)),
            pystray.MenuItem("停止小黄", lambda _icon, _item: _run_background("xiaohuang-stop", stop_xiaohuang)),
            pystray.MenuItem("重启小黄", lambda _icon, _item: _run_background("xiaohuang-restart", restart_xiaohuang, config_path)),
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
