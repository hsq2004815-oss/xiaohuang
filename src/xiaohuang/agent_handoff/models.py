"""Models for Agent Handoff draft generation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentHandoffRequest:
    user_request: str
    target_agent: str = "generic"
    actual_task: str | None = None
    project_hint: str | None = None
    target_project_path: str | None = None
    target_project_kind: str = "auto"
    project_relation: str = "auto"
    domain_hints: list[str] = field(default_factory=list)
    source: str = "text"
    use_database: bool = True


@dataclass(frozen=True)
class DatabaseBriefResult:
    database_used: bool
    database_status: str
    brief: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class AgentHandoffResult:
    ok: bool
    title: str
    summary: str
    target_agent: str
    domains: list[str]
    handoff_path: str | None = None
    handoff_preview: str = ""
    database_used: bool = False
    database_status: str = "not_requested"
    error_message: str = ""
    tags: list[str] = field(default_factory=list)
