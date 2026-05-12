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


@dataclass(frozen=True)
class MulticaIssueCreateRequest:
    title: str
    description: str
    assignee: str = ""
    priority: str = ""
    project: str = ""
    confirmed: bool = False
    confirmation_text: str = ""


@dataclass(frozen=True)
class MulticaIssueCreateResult:
    ok: bool
    created: bool = False
    issue_id: str = ""
    title: str = ""
    status: str = ""
    assignee: str = ""
    raw_summary: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "created": self.created,
            "issue_id": self.issue_id,
            "title": self.title,
            "status": self.status,
            "assignee": self.assignee,
            "raw_summary": self.raw_summary,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class MulticaIssueAssignRequest:
    issue_id: str
    agent: str
    confirmed: bool = False
    confirmation_text: str = ""


@dataclass(frozen=True)
class MulticaIssueAssignResult:
    ok: bool
    assigned: bool = False
    issue_id: str = ""
    agent: str = ""
    status: str = ""
    raw_summary: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "assigned": self.assigned,
            "issue_id": self.issue_id,
            "agent": self.agent,
            "status": self.status,
            "raw_summary": self.raw_summary,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "message": self.message,
        }
