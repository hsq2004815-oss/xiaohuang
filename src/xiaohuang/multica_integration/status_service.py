"""Readonly Multica status aggregation."""

from __future__ import annotations

import json
import re
from typing import Callable

from xiaohuang.multica_integration.cli_client import run_multica_command
from xiaohuang.multica_integration.models import (
    MulticaAgentInfo,
    MulticaCommandResult,
    MulticaStatus,
)

CommandRunner = Callable[[str], MulticaCommandResult]


def get_multica_status(command_runner: CommandRunner | None = None) -> MulticaStatus:
    run = command_runner or run_multica_command
    warnings: list[str] = []

    version_result = run("version")
    if not version_result.ok:
        return MulticaStatus(
            ok=False,
            installed=False,
            warnings=tuple(_result_warning(version_result)),
            error_code=version_result.error_code or "multica_unavailable",
            message=version_result.message or "Multica unavailable.",
        )

    version = _first_nonempty_line(version_result.stdout)

    daemon_result = run("daemon_status")
    daemon_running = False
    daemon_summary = "unknown"
    daemon_agents: tuple[str, ...] = ()
    if daemon_result.ok:
        daemon_running, daemon_summary = _parse_daemon_status(daemon_result.stdout)
        daemon_agents = _parse_daemon_agents(daemon_result.stdout)
    else:
        warnings.extend(_result_warning(daemon_result))

    agent_result = run("agent_list_json")
    agent_details: tuple[MulticaAgentInfo, ...] = ()
    if agent_result.ok:
        parsed_agents, parse_warnings = _parse_agent_list_json(agent_result.stdout)
        agent_details = parsed_agents
        warnings.extend(parse_warnings)
    else:
        warnings.extend(_result_warning(agent_result))

    workspace_summary, workspace_warnings = _read_workspace_summary(run)
    warnings.extend(workspace_warnings)

    agents = daemon_agents or tuple(agent.name for agent in agent_details if agent.name)

    return MulticaStatus(
        ok=True,
        installed=True,
        version=version,
        daemon_running=daemon_running,
        daemon_summary=daemon_summary,
        agents=agents,
        agent_details=agent_details,
        workspace_summary=workspace_summary,
        warnings=tuple(_dedupe(warnings)),
        message="Multica 状态已读取。",
    )


def _read_workspace_summary(run: CommandRunner) -> tuple[str, list[str]]:
    warnings: list[str] = []
    json_result = run("workspace_list_json")
    if json_result.ok:
        summary, parse_warnings = _parse_workspace_json(json_result.stdout)
        return summary, parse_warnings

    if _looks_like_unknown_output_flag(json_result):
        warnings.append("workspace list --output json unsupported; fallback to table output")
    else:
        warnings.extend(_result_warning(json_result))

    table_result = run("workspace_list_table")
    if table_result.ok:
        return _parse_workspace_table(table_result.stdout), warnings
    warnings.extend(_result_warning(table_result))
    return "unknown", warnings


def _parse_daemon_status(text: str) -> tuple[bool, str]:
    match = re.search(r"(?im)^\s*Daemon:\s*([^\r\n]+)", str(text or ""))
    if not match:
        return False, "unknown"
    value = " ".join(match.group(1).split())
    return value.lower().startswith("running"), value


def _parse_daemon_agents(text: str) -> tuple[str, ...]:
    match = re.search(r"(?im)^\s*Agents:\s*([^\r\n]+)", str(text or ""))
    if not match:
        return ()
    return tuple(_dedupe(part.strip() for part in match.group(1).split(",") if part.strip()))


def _parse_agent_list_json(text: str) -> tuple[tuple[MulticaAgentInfo, ...], list[str]]:
    try:
        data = json.loads(str(text or "[]"))
    except json.JSONDecodeError:
        return (), ["agent list json parse failed"]
    if not isinstance(data, list):
        return (), ["agent list json has unexpected shape"]

    agents: list[MulticaAgentInfo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "").strip()
        if not name:
            continue
        agents.append(
            MulticaAgentInfo(
                name=name,
                status=str(item.get("status") or ""),
                runtime_mode=str(item.get("runtime_mode") or ""),
                visibility=str(item.get("visibility") or ""),
            )
        )
    return tuple(agents), []


def _parse_workspace_json(text: str) -> tuple[str, list[str]]:
    try:
        data = json.loads(str(text or "[]"))
    except json.JSONDecodeError:
        return "unknown", ["workspace list json parse failed"]
    if isinstance(data, list):
        names = [
            str(item.get("name") or item.get("id") or "").strip()
            for item in data
            if isinstance(item, dict) and (item.get("name") or item.get("id"))
        ]
        return ", ".join(names) if names else "0", []
    if isinstance(data, dict):
        name = str(data.get("name") or data.get("id") or "").strip()
        return name or "1", []
    return "unknown", ["workspace list json has unexpected shape"]


def _parse_workspace_table(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    rows = [line for line in lines if not line.upper().startswith("ID ")]
    if not rows:
        return "unknown"
    return f"{len(rows)} workspace(s): " + "; ".join(rows[:3])


def _looks_like_unknown_output_flag(result: MulticaCommandResult) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "unknown flag" in text and "--output" in text


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        value = line.strip()
        if value:
            return value
    return ""


def _result_warning(result: MulticaCommandResult) -> list[str]:
    code = result.error_code or "multica_command_failed"
    message = result.message or result.stderr or result.stdout
    compact = " ".join(str(message or "").split())[:180]
    return [f"{result.command_key}: {code}" + (f" ({compact})" if compact else "")]


def _dedupe(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
