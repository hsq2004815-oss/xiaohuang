from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
LOG_DIR = PROJECT_ROOT / "logs"


def get_default_config_path(env: Mapping[str, str] | None = None) -> Path:
    env_map = env or os.environ
    user_profile = env_map.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / ".xiaohuang" / "config.json"
    return Path.home() / ".xiaohuang" / "config.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XiaoHuang minimal tray controller V1.1.4B")
    parser.add_argument(
        "--config",
        default=str(get_default_config_path()),
        help="Path to config.json. Defaults to %%USERPROFILE%%\\.xiaohuang\\config.json",
    )
    return parser.parse_args(argv)


def ensure_log_dir(project_root: Path = PROJECT_ROOT) -> Path:
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


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


def show_about() -> None:
    show_message(
        "小黄托盘控制器",
        "小黄托盘控制器 V1.1.4B\n\n当前版本只支持打开设置和日志。\n启动/停止/重启将在 V1.1.4C 实现。",
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
            pystray.MenuItem("打开设置", lambda _icon, _item: open_settings(config_path)),
            pystray.MenuItem("打开日志目录", lambda _icon, _item: open_log_dir()),
            pystray.MenuItem("关于/状态", lambda _icon, _item: show_about()),
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
