"""local_commands/service.py — capability routing and execution.

Deterministic Chinese keyword matching — no LLM function calling.
All side effects come from whitelisted capability handlers.
"""

from __future__ import annotations

from typing import Any

from xiaohuang.capabilities.local_commands.models import (
    LocalCommandIntent,
    LocalCommandResult,
    RouteDecision,
)
from xiaohuang.capabilities.local_commands.registry import get_capability, get_registry

# (keyword list, capability_name) — first match wins
_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["打开日志", "日志目录", "打开 logs", "打开log", "logs 目录"], "open_logs_folder"),
    (["启动前检查", "运行检查", "检查环境", "环境检查", "系统检查"], "run_preflight_check"),
    (["当前状态", "小黄状态", "查看状态", "运行状态", "状态查看"], "get_status"),
    (["导出诊断", "生成诊断", "诊断报告", "导出报告", "导出 txt"], "export_diagnostics"),
    (["打开控制面板", "显示控制面板", "控制中心", "打开控制中心"], "open_control_panel"),
]

# Tool-like keywords that are not whitelisted and must be denied.
_DENIED_KEYWORDS: list[str] = [
    "打开浏览器", "帮我打开",
    "下载",
    "搜索",
    "发消息", "发微信", "发qq",
    "运行", "执行",
    "写代码", "opencode",
    "爬取", "入库", "操作",
    "删除文件", "删除", "powershell", "cmd", "shell",
    "执行命令", "系统命令",
]

# High-risk patterns that MUST be denied regardless
_HIGH_RISK_PATTERNS: list[str] = [
    "powershell", "cmd.exe", "shell", "rm -", "rmdir", "del ",
    "format ", "shutdown", "reboot", "restart computer",
    "taskkill", "kill process", "regedit", "注册表",
    "browser automation", "微信", "wechat", "qq消息",
]


def route_capability(command_text: str) -> RouteDecision:
    normalized = str(command_text or "").replace(" ", "").lower()
    if not normalized:
        return RouteDecision(
            is_task_request=False,
            can_execute=False,
            reason="not_task",
            message="",
        )

    # Check high-risk patterns first (fail closed)
    for risk_pattern in _HIGH_RISK_PATTERNS:
        if risk_pattern in normalized:
            return RouteDecision(
                is_task_request=True,
                can_execute=False,
                reason="not_allowed",
                message="该操作不在安全白名单中，当前版本不能执行。",
                requires_confirmation=False,
            )

    # Check whitelisted capabilities
    for keywords, cap_name in _KEYWORD_MAP:
        if any(kw in normalized for kw in keywords):
            cap = get_capability(cap_name)
            if cap is None or not cap.enabled:
                return RouteDecision(
                    is_task_request=True,
                    can_execute=False,
                    reason="capability_disabled",
                    message=f"能力 {cap_name} 当前不可用。",
                )
            return RouteDecision(
                is_task_request=True,
                can_execute=True,
                command=cap_name,
                reason="capability_matched",
                message=f"匹配到能力：{cap.description}",
                intent=LocalCommandIntent(
                    command=cap_name,
                    original_text=command_text,
                    matched_phrase=keywords[0],
                ),
            )

    # Check old denied keywords (tool-like requests not in whitelist)
    for kw in _DENIED_KEYWORDS:
        if kw in normalized:
            return RouteDecision(
                is_task_request=True,
                can_execute=False,
                reason="not_allowed",
                message="该操作不在安全白名单中，当前版本不能执行。",
            )

    return RouteDecision(
        is_task_request=False,
        can_execute=False,
        reason="not_task",
        message="",
    )


def execute_capability(
    decision: RouteDecision,
    *,
    project_root: Any = None,
    config_path: Any = None,
) -> LocalCommandResult:
    if not decision.can_execute or not decision.command:
        return LocalCommandResult(
            ok=False,
            command=decision.command or "unknown",
            message=decision.message or "无法执行该操作。",
            error_code="cannot_execute",
            risk="low",
            executed=False,
        )

    cap = get_capability(decision.command)
    if cap is None or not cap.enabled:
        return LocalCommandResult(
            ok=False,
            command=decision.command,
            message=f"能力 {decision.command} 不可用。",
            error_code="capability_unavailable",
            risk="low",
            executed=False,
        )

    _record_capability_event(
        decision.command,
        "capability_invoked",
        f"执行能力：{cap.description}",
        "info",
        {"command": decision.command, "risk": cap.risk},
    )

    try:
        result = cap.handler(project_root=project_root, config_path=config_path)
        if result.ok:
            _record_capability_event(
                decision.command,
                "capability_completed",
                result.message,
                "info" if result.ok else "error",
                {"command": decision.command, "executed": result.executed},
            )
        else:
            _record_capability_event(
                decision.command,
                "capability_failed",
                result.message,
                "error",
                {"command": decision.command, "error_code": result.error_code},
            )
        return result
    except Exception as exc:
        err_msg = f"执行能力 {decision.command} 时出错：{exc}"
        _record_capability_event(
            decision.command,
            "capability_failed",
            err_msg,
            "error",
            {"command": decision.command, "error": str(exc)},
        )
        return LocalCommandResult(
            ok=False,
            command=decision.command,
            message=err_msg,
            error_code="handler_exception",
            risk=cap.risk,
            executed=True,
        )


def _record_capability_event(
    command: str,
    event_type: str,
    message: str,
    level: str,
    details: dict,
) -> None:
    try:
        from xiaohuang.capabilities.runtime_events.service import record_event
        record_event(
            "capability_router",
            event_type,
            message,
            level=level,
            details=details,
        )
    except Exception:
        pass
