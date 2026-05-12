"""Confirmed Multica issue creation service."""

from __future__ import annotations

import json
import re
from typing import Any

from xiaohuang.multica_integration.cli_client import Runner, run_multica_argv
from xiaohuang.multica_integration.issue_draft_service import redact_sensitive_text
from xiaohuang.multica_integration.models import MulticaIssueCreateRequest, MulticaIssueCreateResult
from xiaohuang.multica_integration.safety import (
    CONFIRMED_ISSUE_CREATE_KEY,
    ISSUE_CREATE_CONFIRMATION_TEXT,
    build_issue_create_argv,
    can_create_issue,
)

_MAX_RAW_SUMMARY_CHARS = 1200
_UNASSIGNED_WARNING = "已创建 issue，但未分配 Agent；C5F 才会在二次确认后执行 assign。"
_MANUAL_ISSUE_ID_WARNING = "未能自动解析 Issue ID，请手动输入已有 issue id 后再分配 Agent。"
_HEX_ISSUE_ID_RE = re.compile(r"\b[0-9a-fA-F]{7,12}\b")
_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,15}-\d+\b", re.IGNORECASE)


def create_issue_from_draft(
    *,
    title: str,
    description: str,
    confirmed: bool,
    confirmation_text: str,
    assignee: str = "",
    priority: str = "",
    project: str = "",
    runner: Runner | None = None,
) -> MulticaIssueCreateResult:
    request = MulticaIssueCreateRequest(
        title=redact_sensitive_text(title).strip(),
        description=redact_sensitive_text(description).strip(),
        assignee=str(assignee or "").strip(),
        priority=str(priority or "").strip(),
        project=str(project or "").strip(),
        confirmed=bool(confirmed),
        confirmation_text=str(confirmation_text or "").strip(),
    )
    if not can_create_issue(confirmed=request.confirmed, confirmation_text=request.confirmation_text):
        return MulticaIssueCreateResult(
            ok=False,
            error_code="confirmation_required",
            message="创建真实 Multica issue 需要二次确认。",
        )
    if not request.title:
        return MulticaIssueCreateResult(ok=False, error_code="missing_title", message="Issue title 不能为空。")
    if not request.description:
        return MulticaIssueCreateResult(ok=False, error_code="missing_description", message="Issue description 不能为空。")

    try:
        argv = build_issue_create_argv(
            title=request.title,
            description=request.description,
            confirmed=request.confirmed,
            confirmation_text=request.confirmation_text,
            priority=request.priority,
            project=request.project,
        )
    except ValueError as exc:
        code = str(exc) or "issue_create_rejected"
        return MulticaIssueCreateResult(ok=False, error_code=code, message=_error_message(code))

    result = run_multica_argv(CONFIRMED_ISSUE_CREATE_KEY, argv, runner=runner)
    if not result.ok:
        return MulticaIssueCreateResult(
            ok=False,
            error_code=result.error_code or "multica_issue_create_failed",
            raw_summary=_compact_raw(result.stderr or result.stdout),
            message=result.message or "Multica issue 创建失败。",
        )

    return _parse_create_result(result.stdout, fallback_title=request.title)


def _parse_create_result(stdout: str, *, fallback_title: str) -> MulticaIssueCreateResult:
    raw_summary = _compact_raw(stdout)
    warnings = (_UNASSIGNED_WARNING,)
    try:
        data = json.loads(str(stdout or "{}"))
    except json.JSONDecodeError:
        issue_id, identifier = _parse_issue_refs(stdout)
        if not issue_id:
            warnings = warnings + (_MANUAL_ISSUE_ID_WARNING,)
        return MulticaIssueCreateResult(
            ok=True,
            created=True,
            issue_id=issue_id,
            identifier=identifier,
            title=fallback_title,
            raw_summary=raw_summary,
            warnings=warnings + ("Multica 返回非 JSON；已保留原始摘要。",),
            message="Multica issue 已创建；未分配 Agent。",
        )

    issue = _issue_payload(data)
    issue_id = _first_text(issue, ("id", "issue_id", "uuid", "key"))
    identifier = _first_text(issue, ("identifier",))
    fallback_issue_id, fallback_identifier = _parse_issue_refs(stdout)
    issue_id = issue_id or identifier or fallback_issue_id or fallback_identifier
    identifier = identifier or fallback_identifier
    title = _first_text(issue, ("title", "name", "summary")) or fallback_title
    status = _first_text(issue, ("status", "state"))
    assignee = _first_text(issue, ("assignee", "assigned_to"))
    if isinstance(issue.get("assignee"), dict):
        assignee = _first_text(issue["assignee"], ("name", "id"))
    if not issue_id:
        warnings = warnings + (_MANUAL_ISSUE_ID_WARNING,)

    return MulticaIssueCreateResult(
        ok=True,
        created=True,
        issue_id=issue_id,
        identifier=identifier,
        title=title,
        status=status,
        assignee=assignee,
        raw_summary=raw_summary,
        warnings=warnings,
        message="Multica issue 已创建；未分配 Agent。",
    )


def _issue_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        for key in ("issue", "data", "result"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return data
    return {}


def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _parse_issue_refs(text: str) -> tuple[str, str]:
    value = str(text or "")
    hex_match = _HEX_ISSUE_ID_RE.search(value)
    identifier_match = _IDENTIFIER_RE.search(value)
    issue_id = hex_match.group(0) if hex_match else ""
    identifier = identifier_match.group(0) if identifier_match else ""
    if not issue_id and identifier:
        issue_id = identifier
    return issue_id, identifier


def _compact_raw(text: str) -> str:
    value = redact_sensitive_text(" ".join(str(text or "").split()))
    if len(value) > _MAX_RAW_SUMMARY_CHARS:
        return value[:_MAX_RAW_SUMMARY_CHARS].rstrip() + "...<truncated>"
    return value


def _error_message(code: str) -> str:
    if code == "confirmation_required":
        return f"创建真实 Multica issue 需要二次确认，确认短语必须是 {ISSUE_CREATE_CONFIRMATION_TEXT}。"
    if code == "missing_title":
        return "Issue title 不能为空。"
    if code == "missing_description":
        return "Issue description 不能为空。"
    return "Multica issue create 请求被安全策略拒绝。"
