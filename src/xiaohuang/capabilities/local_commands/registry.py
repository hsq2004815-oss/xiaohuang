"""local_commands/registry.py — whitelisted capability definitions.

Each capability has: name, description, risk level, enabled flag, and handler.
All handlers are lazy-loaded to avoid circular imports.
"""

from __future__ import annotations

from typing import Callable

from xiaohuang.capabilities.local_commands.models import (
    CapabilityDefinition,
    LocalCommandResult,
)

_registry: list[CapabilityDefinition] | None = None


def _build_registry() -> list[CapabilityDefinition]:
    return [
        CapabilityDefinition(
            name="open_logs_folder",
            description="打开项目日志目录",
            risk="low",
            enabled=True,
            handler=_open_logs_folder_handler,
        ),
        CapabilityDefinition(
            name="run_preflight_check",
            description="运行启动前环境检查",
            risk="low",
            enabled=True,
            handler=_preflight_check_handler,
        ),
        CapabilityDefinition(
            name="get_status",
            description="读取当前小黄运行状态",
            risk="low",
            enabled=True,
            handler=_get_status_handler,
        ),
        CapabilityDefinition(
            name="export_diagnostics",
            description="导出诊断信息 TXT",
            risk="low",
            enabled=True,
            handler=_export_diagnostics_handler,
        ),
        CapabilityDefinition(
            name="open_control_panel",
            description="打开 Web 控制面板",
            risk="low",
            enabled=True,
            handler=_open_control_panel_handler,
        ),
    ]


def get_registry() -> list[CapabilityDefinition]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_capability(name: str) -> CapabilityDefinition | None:
    for cap in get_registry():
        if cap.name == name:
            return cap
    return None


# ── capability handlers (module-level functions to avoid import side effects) ──

_LAZY_RESOLVED: dict[str, Callable[..., LocalCommandResult]] = {}


def _resolve_handler(name: str, factory: Callable[[], Callable[..., LocalCommandResult]]):
    if name not in _LAZY_RESOLVED:
        _LAZY_RESOLVED[name] = factory()
    return _LAZY_RESOLVED[name]


def _open_logs_folder_handler(
    project_root=None, **kwargs,
) -> LocalCommandResult:
    import os
    from pathlib import Path

    root = Path(project_root) if project_root else Path.cwd()
    logs_dir = (root / "logs").resolve()
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(logs_dir))  # type: ignore[attr-defined]
        return LocalCommandResult(
            ok=True,
            command="open_logs_folder",
            message=f"日志目录已打开：{logs_dir}",
            data={"path": str(logs_dir)},
            executed=True,
        )
    except Exception as exc:
        return LocalCommandResult(
            ok=False,
            command="open_logs_folder",
            message=f"打开日志目录失败：{exc}",
            error_code="open_failed",
            executed=True,
        )


def _preflight_check_handler(
    project_root=None, **kwargs,
) -> LocalCommandResult:
    from pathlib import Path
    from xiaohuang.capabilities.preflight_check.service import (
        run_preflight_check,
    )

    root = Path(project_root) if project_root else Path.cwd()
    try:
        result = run_preflight_check(root)
        d = result.to_dict()
        return LocalCommandResult(
            ok=True,
            command="run_preflight_check",
            message=result.summary,
            data=d,
            executed=True,
        )
    except Exception as exc:
        return LocalCommandResult(
            ok=False,
            command="run_preflight_check",
            message=f"启动前检查失败：{exc}",
            error_code="check_failed",
            executed=True,
        )


def _get_status_handler(
    project_root=None, config_path=None, **kwargs,
) -> LocalCommandResult:
    from pathlib import Path
    from xiaohuang.status_control_service import build_status
    from xiaohuang.app_config_service import get_default_config_path

    root = Path(project_root) if project_root else Path.cwd()
    cfg = Path(config_path) if config_path else get_default_config_path()
    try:
        status = build_status(root, cfg)
        from dataclasses import asdict
        return LocalCommandResult(
            ok=True,
            command="get_status",
            message=status.overall_message,
            data={"status": asdict(status)},
            executed=True,
        )
    except Exception as exc:
        return LocalCommandResult(
            ok=False,
            command="get_status",
            message=f"获取状态失败：{exc}",
            error_code="status_failed",
            executed=True,
        )


def _export_diagnostics_handler(
    project_root=None, **kwargs,
) -> LocalCommandResult:
    from pathlib import Path
    from xiaohuang.capabilities.diagnostic_export.service import (
        export_diagnostics_to_file,
        format_diagnostics_text,
    )
    from xiaohuang.status_control_service import build_status
    from xiaohuang.app_config_service import get_default_config_path

    root = Path(project_root) if project_root else Path.cwd()
    cfg = get_default_config_path()
    try:
        status = build_status(root, cfg)
        from dataclasses import asdict
        status_dict = asdict(status)
        status_dict["config_path"] = str(status_dict.get("config_path", ""))
        text = format_diagnostics_text({
            "exported_from": "capability_router",
            "bridge_ready": True,
            "status": status_dict,
            "log_paths": {
                "project_root": str(root),
                "logs_directory": str(root / "logs"),
                "config_path": str(cfg),
            },
            "drawer": {},
            "history": [],
            "runtime_events": [],
        })
        logs_dir = root / "logs"
        result = export_diagnostics_to_file(text, logs_dir)
        return LocalCommandResult(
            ok=result.ok,
            command="export_diagnostics",
            message=result.message,
            data={"path": result.path},
            executed=True,
        )
    except Exception as exc:
        return LocalCommandResult(
            ok=False,
            command="export_diagnostics",
            message=f"导出诊断信息失败：{exc}",
            error_code="export_failed",
            executed=True,
        )


def _open_control_panel_handler(
    project_root=None, config_path=None, **kwargs,
) -> LocalCommandResult:
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(project_root) if project_root else Path.cwd()
    cfg = Path(config_path) if config_path else Path.home() / ".xiaohuang" / "config.json"
    script = root / "scripts" / "control_panel_web.py"
    if not script.is_file():
        return LocalCommandResult(
            ok=False,
            command="open_control_panel",
            message="控制面板脚本不存在，请检查项目安装。",
            error_code="script_missing",
            executed=False,
        )
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen(
            [sys.executable, str(script), "--config", str(cfg)],
            cwd=str(root),
            env=env,
        )
        return LocalCommandResult(
            ok=True,
            command="open_control_panel",
            message="控制面板正在打开。",
            data={"script": str(script)},
            executed=True,
        )
    except Exception as exc:
        return LocalCommandResult(
            ok=False,
            command="open_control_panel",
            message=f"打开控制面板失败：{exc}",
            error_code="launch_failed",
            executed=False,
        )
