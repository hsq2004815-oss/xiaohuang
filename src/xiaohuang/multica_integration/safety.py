"""Central safety policy for Multica CLI usage."""

from __future__ import annotations

from dataclasses import dataclass
import re
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
CONFIRMED_ISSUE_ASSIGN_KEY = "confirmed_issue_assign"
CONFIRMED_ISSUE_RUNS_KEY = "confirmed_issue_runs"
CONFIRMED_RUN_MESSAGES_KEY = "confirmed_run_messages"
ISSUE_CREATE_CONFIRMATION_TEXT = "CREATE_MULTICA_ISSUE"
ALLOWED_ASSIGN_AGENTS = ("claude", "codex", "opencode", "openclaw")
_SAFE_ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,80}$")

BLOCKED_COMMAND_KEYS: tuple[str, ...] = (
    "issue_create",
    "issue_assign",
    "issue_status",
    "issue_update",
    "issue_rerun",
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


def normalize_assign_agent(agent: str) -> str:
    return str(agent or "").strip().lower()


def is_supported_assign_agent(agent: str) -> bool:
    return normalize_assign_agent(agent) in ALLOWED_ASSIGN_AGENTS


def is_safe_issue_id(issue_id: str) -> bool:
    return bool(_SAFE_ISSUE_ID_RE.fullmatch(str(issue_id or "").strip()))


def expected_issue_assign_confirmation(issue_id: str, agent: str) -> str:
    return f"ASSIGN {str(issue_id or '').strip()} TO {normalize_assign_agent(agent)}"


def can_assign_issue(*, issue_id: str, agent: str, confirmed: bool, confirmation_text: str) -> bool:
    clean_issue_id = str(issue_id or "").strip()
    clean_agent = normalize_assign_agent(agent)
    if not bool(confirmed) or not is_safe_issue_id(clean_issue_id) or not is_supported_assign_agent(clean_agent):
        return False
    return str(confirmation_text or "").strip() == expected_issue_assign_confirmation(clean_issue_id, clean_agent)


def build_issue_assign_argv(
    *,
    issue_id: str,
    agent: str,
    confirmed: bool,
    confirmation_text: str,
) -> tuple[str, ...]:
    clean_issue_id = str(issue_id or "").strip()
    clean_agent = normalize_assign_agent(agent)
    if not clean_issue_id:
        raise ValueError("missing_issue_id")
    if not clean_agent:
        raise ValueError("missing_agent")
    if not is_supported_assign_agent(clean_agent):
        raise ValueError("unsupported_agent")
    if not is_safe_issue_id(clean_issue_id):
        raise ValueError("invalid_issue_id")
    if not can_assign_issue(
        issue_id=clean_issue_id,
        agent=clean_agent,
        confirmed=confirmed,
        confirmation_text=confirmation_text,
    ):
        raise ValueError("confirmation_required")
    return (
        "multica",
        "issue",
        "assign",
        clean_issue_id,
        "--to",
        clean_agent,
        "--output",
        "json",
    )


def is_allowed_confirmed_argv(command_key: str, argv: Sequence[str]) -> bool:
    values = tuple(str(item or "") for item in argv)
    key = str(command_key or "")
    if key == CONFIRMED_ISSUE_CREATE_KEY:
        return _is_allowed_issue_create_argv(values)
    if key == CONFIRMED_ISSUE_ASSIGN_KEY:
        return _is_allowed_issue_assign_argv(values)
    if key == CONFIRMED_ISSUE_RUNS_KEY:
        return _is_allowed_issue_runs_argv(values)
    if key == CONFIRMED_RUN_MESSAGES_KEY:
        return _is_allowed_run_messages_argv(values)
    return False


def _is_allowed_issue_create_argv(values: tuple[str, ...]) -> bool:
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


def _is_allowed_issue_assign_argv(values: tuple[str, ...]) -> bool:
    if len(values) != 8 or values[:3] != ("multica", "issue", "assign"):
        return False
    issue_id = values[3]
    return (
        is_safe_issue_id(issue_id)
        and values[4] == "--to"
        and is_supported_assign_agent(values[5])
        and values[6] == "--output"
        and values[7] == "json"
    )


def is_safe_task_id(task_id: str) -> bool:
    return bool(_SAFE_TASK_ID_RE.fullmatch(str(task_id or "").strip()))


def build_issue_runs_argv(*, issue_id: str) -> tuple[str, ...]:
    clean = str(issue_id or "").strip()
    if not clean:
        raise ValueError("missing_issue_id")
    if not is_safe_issue_id(clean):
        raise ValueError("invalid_issue_id")
    return ("multica", "issue", "runs", clean, "--output", "json")


def build_run_messages_argv(*, task_id: str) -> tuple[str, ...]:
    clean = str(task_id or "").strip()
    if not clean:
        raise ValueError("missing_task_id")
    if not is_safe_task_id(clean):
        raise ValueError("invalid_task_id")
    return ("multica", "issue", "run-messages", clean, "--output", "json")


def _is_allowed_issue_runs_argv(values: tuple[str, ...]) -> bool:
    if len(values) != 6 or values[:3] != ("multica", "issue", "runs"):
        return False
    return is_safe_issue_id(values[3]) and values[4] == "--output" and values[5] == "json"


def _is_allowed_run_messages_argv(values: tuple[str, ...]) -> bool:
    if len(values) != 6 or values[:3] != ("multica", "issue", "run-messages"):
        return False
    return is_safe_task_id(values[3]) and values[4] == "--output" and values[5] == "json"
