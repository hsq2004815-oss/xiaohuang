"""Safe terminal launcher for Agent Handoff target projects."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class TerminalOpenResult:
    ok: bool
    message: str
    target_project_path: str = ""
    error_code: str = ""


PopenFunc = Callable[..., object]


def quote_powershell_single(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def open_target_project_terminal(
    target_project_path: str,
    *,
    popen_func: PopenFunc | None = None,
    os_name: str | None = None,
) -> TerminalOpenResult:
    raw_path = str(target_project_path or "").strip()
    validation = _validate_target_project_path(raw_path, os_name=os_name)
    if not validation.ok:
        return validation

    command = [
        "powershell.exe",
        "-NoExit",
        "-Command",
        "Set-Location -LiteralPath " + quote_powershell_single(raw_path),
    ]
    launcher = popen_func or subprocess.Popen
    popen_kwargs = _visible_console_popen_kwargs()
    try:
        launcher(command, **popen_kwargs)
    except FileNotFoundError:
        return TerminalOpenResult(
            ok=False,
            message="PowerShell 不可用，无法打开目标项目终端。",
            target_project_path=raw_path,
            error_code="powershell_not_found",
        )
    except Exception as exc:
        return TerminalOpenResult(
            ok=False,
            message=f"打开目标项目终端失败：{exc}",
            target_project_path=raw_path,
            error_code="terminal_launch_failed",
        )

    return TerminalOpenResult(
        ok=True,
        message="已向系统请求打开目标项目终端，如未看到窗口请检查任务栏或 Alt+Tab。",
        target_project_path=raw_path,
    )


def _visible_console_popen_kwargs() -> dict[str, Any]:
    create_new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    if create_new_console:
        return {"creationflags": create_new_console}
    return {}


def _validate_target_project_path(raw_path: str, *, os_name: str | None = None) -> TerminalOpenResult:
    if not raw_path or raw_path == "未指定":
        return TerminalOpenResult(
            ok=False,
            message="目标项目路径未指定，不能打开终端。",
            target_project_path=raw_path,
            error_code="missing_target_project_path",
        )
    if (os_name or os.name) != "nt":
        return TerminalOpenResult(
            ok=False,
            message="当前平台不支持从控制面板打开 Windows PowerShell 终端。",
            target_project_path=raw_path,
            error_code="unsupported_platform",
        )

    pure_path = PureWindowsPath(raw_path)
    if not pure_path.is_absolute() or ".." in pure_path.parts:
        return TerminalOpenResult(
            ok=False,
            message="目标项目路径必须是安全的 Windows 绝对目录。",
            target_project_path=raw_path,
            error_code="invalid_target_project_path",
        )

    path = Path(raw_path)
    if not path.exists():
        return TerminalOpenResult(
            ok=False,
            message="目标项目路径不存在，不能回退到小黄项目。",
            target_project_path=raw_path,
            error_code="target_project_path_not_found",
        )
    if not path.is_dir():
        return TerminalOpenResult(
            ok=False,
            message="目标项目路径不是目录，不能打开终端。",
            target_project_path=raw_path,
            error_code="target_project_path_not_directory",
        )
    return TerminalOpenResult(ok=True, message="", target_project_path=raw_path)
