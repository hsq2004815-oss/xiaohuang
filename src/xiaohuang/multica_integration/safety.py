"""Central safety policy for Multica CLI usage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


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

CONFIRMED_ISSUE_CREATE_KEY = "confirmed_issue_create"
ISSUE_CREATE_CONFIRMATION_TEXT = "CREATE_MULTICA_ISSUE"

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


def can_create_issue(*, confirmed: bool, confirmation_text: str) -> bool:
    return bool(confirmed) and str(confirmation_text or "").strip() == ISSUE_CREATE_CONFIRMATION_TEXT


def build_issue_create_argv(
    *,
    title: str,
    description: str,
    confirmed: bool,
    confirmation_text: str,
    priority: str = "",
    project: str = "",
) -> tuple[str, ...]:
    if not can_create_issue(confirmed=confirmed, confirmation_text=confirmation_text):
        raise ValueError("confirmation_required")
    clean_title = str(title or "").strip()
    clean_description = str(description or "").strip()
    if not clean_title:
        raise ValueError("missing_title")
    if not clean_description:
        raise ValueError("missing_description")

    argv = [
        "multica",
        "issue",
        "create",
        "--title",
        clean_title,
        "--description",
        clean_description,
    ]
    clean_priority = str(priority or "").strip()
    clean_project = str(project or "").strip()
    if clean_priority:
        argv.extend(["--priority", clean_priority])
    if clean_project:
        argv.extend(["--project", clean_project])
    argv.extend(["--output", "json"])
    return tuple(argv)


def is_allowed_confirmed_argv(command_key: str, argv: Sequence[str]) -> bool:
    if str(command_key or "") != CONFIRMED_ISSUE_CREATE_KEY:
        return False
    values = tuple(str(item or "") for item in argv)
    if len(values) < 9 or values[:3] != ("multica", "issue", "create"):
        return False
    allowed_flags = {"--title", "--description", "--priority", "--project", "--output"}
    seen: dict[str, str] = {}
    idx = 3
    while idx < len(values):
        flag = values[idx]
        if flag not in allowed_flags or idx + 1 >= len(values):
            return False
        seen[flag] = values[idx + 1]
        idx += 2
    return bool(seen.get("--title")) and bool(seen.get("--description")) and seen.get("--output") == "json"
