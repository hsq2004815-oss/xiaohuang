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

