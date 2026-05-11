"""Data models for safe Multica integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MulticaCommandResult:
    ok: bool
    command_key: str
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    error_code: str = ""
    message: str = ""


@dataclass(frozen=True)
class MulticaAgentInfo:
    name: str
    status: str = ""
    runtime_mode: str = ""
    visibility: str = ""


@dataclass(frozen=True)
class MulticaStatus:
    ok: bool
    installed: bool
    version: str = ""
    daemon_running: bool = False
    daemon_summary: str = ""
    agents: tuple[str, ...] = ()
    agent_details: tuple[MulticaAgentInfo, ...] = ()
    workspace_summary: str = ""
    warnings: tuple[str, ...] = ()
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "installed": self.installed,
            "version": self.version,
            "daemon_running": self.daemon_running,
            "daemon_summary": self.daemon_summary,
            "agents": list(self.agents),
            "agent_details": [
                {
                    "name": agent.name,
                    "status": agent.status,
                    "runtime_mode": agent.runtime_mode,
                    "visibility": agent.visibility,
                }
                for agent in self.agent_details
            ],
            "workspace_summary": self.workspace_summary,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class MulticaIssueDraft:
    ok: bool
    title: str = ""
    description: str = ""
    target_project_path: str = ""
    project_relation: str = ""
    suggested_assignees: tuple[str, ...] = ()
    default_assignee: str = ""
    create_command_preview: str = ""
    markdown: str = ""
    warnings: tuple[str, ...] = ()
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "title": self.title,
            "description": self.description,
            "target_project_path": self.target_project_path,
            "project_relation": self.project_relation,
            "suggested_assignees": list(self.suggested_assignees),
            "default_assignee": self.default_assignee,
            "create_command_preview": self.create_command_preview,
            "markdown": self.markdown,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "message": self.message,
        }
