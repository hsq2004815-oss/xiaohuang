"""Central safety policy for Multica CLI usage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MulticaCommandSpec:
    key: str
    argv: tuple[str, ...]
    readonly: bool = True


ALLOWED_COMMANDS: dict[str, MulticaCommandSpec] = {
    "version": MulticaCommandSpec("version", ("multica", "version")),
    "daemon_status": MulticaCommandSpec("daemon_status", ("multica", "daemon", "status")),
    "agent_list_json": MulticaCommandSpec("agent_list_json", ("multica", "agent", "list", "--output", "json")),
    "workspace_list_json": MulticaCommandSpec("workspace_list_json", ("multica", "workspace", "list", "--output", "json")),
    "workspace_list_table": MulticaCommandSpec("workspace_list_table", ("multica", "workspace", "list")),
}

BLOCKED_COMMAND_KEYS: tuple[str, ...] = (
    "issue_create",
    "issue_assign",
    "issue_status",
    "issue_update",
    "issue_rerun",
    "issue_runs",
    "issue_run_messages",
    "daemon_restart",
    "daemon_stop",
    "agent_launch",
)


def is_allowed_command(command_key: str) -> bool:
    return str(command_key or "") in ALLOWED_COMMANDS


def is_blocked_command(command_key: str) -> bool:
    return str(command_key or "") in BLOCKED_COMMAND_KEYS


def get_command_argv(command_key: str) -> tuple[str, ...]:
    key = str(command_key or "")
    if not is_allowed_command(key):
        raise ValueError("rejected_command")
    return ALLOWED_COMMANDS[key].argv

