"""Data models for safe Multica integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MulticaCommandResult:
    ok: bool
    command_key: str
    returncode: int = 0
    raw_stdout: str = ""
    raw_stderr: str = ""
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
    identifier: str = ""
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
            "identifier": self.identifier,
            "title": self.title,
            "status": self.status,
            "assignee": self.assignee,
            "raw_summary": self.raw_summary,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class MulticaRunSummary:
    run_id: str = ""
    task_id: str = ""
    issue_id: str = ""
    status: str = ""
    agent: str = ""
    title: str = ""
    started_at: str = ""
    updated_at: str = ""
    raw_summary: str = ""


@dataclass(frozen=True)
class MulticaRunMessage:
    message_id: str = ""
    seq: str = ""
    tool: str = ""
    message_type: str = ""
    role: str = ""
    author: str = ""
    content: str = ""
    created_at: str = ""
    raw_summary: str = ""


@dataclass(frozen=True)
class MulticaRunsResult:
    ok: bool
    issue_id: str = ""
    runs: tuple[MulticaRunSummary, ...] = ()
    raw_summary: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issue_id": self.issue_id,
            "runs": [
                {
                    "run_id": r.run_id,
                    "task_id": r.task_id,
                    "issue_id": r.issue_id,
                    "status": r.status,
                    "agent": r.agent,
                    "title": r.title,
                    "started_at": r.started_at,
                    "updated_at": r.updated_at,
                    "raw_summary": r.raw_summary,
                }
                for r in self.runs
            ],
            "raw_summary": self.raw_summary,
            "warnings": list(self.warnings),
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class MulticaRunMessagesResult:
    ok: bool
    task_id: str = ""
    messages: tuple[MulticaRunMessage, ...] = ()
    raw_summary: str = ""
    review_summary: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    raw_debug: dict = field(default_factory=dict)
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "task_id": self.task_id,
            "messages": [
                {
                    "message_id": m.message_id,
                    "seq": m.seq,
                    "tool": m.tool,
                    "message_type": m.message_type,
                    "role": m.role,
                    "author": m.author,
                    "content": m.content,
                    "created_at": m.created_at,
                    "raw_summary": m.raw_summary,
                }
                for m in self.messages
            ],
            "raw_summary": self.raw_summary,
            "review_summary": self.review_summary,
            "warnings": list(self.warnings),
            "raw_debug": self.raw_debug,
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
