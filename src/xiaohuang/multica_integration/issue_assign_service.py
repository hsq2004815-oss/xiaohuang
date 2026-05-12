"""Confirmed Multica issue assignment service."""

from __future__ import annotations

import json
from typing import Any

from xiaohuang.multica_integration.cli_client import Runner, run_multica_argv
from xiaohuang.multica_integration.issue_draft_service import redact_sensitive_text
from xiaohuang.multica_integration.models import MulticaIssueAssignRequest, MulticaIssueAssignResult
from xiaohuang.multica_integration.safety import (
    CONFIRMED_ISSUE_ASSIGN_KEY,
    build_issue_assign_argv,
    expected_issue_assign_confirmation,
    normalize_assign_agent,
)

_MAX_RAW_SUMMARY_CHARS = 1200
_ASSIGN_WARNING = "分配给 Agent 后，Multica 可能会开始处理；小黄没有执行 run/rerun/runs/run-messages。"


def assign_issue_to_agent(
    *,
    issue_id: str,
    agent: str,
    confirmed: bool,
    confirmation_text: str,
    runner: Runner | None = None,
) -> MulticaIssueAssignResult:
    request = MulticaIssueAssignRequest(
        issue_id=str(issue_id or "").strip(),
        agent=normalize_assign_agent(agent),
        confirmed=bool(confirmed),
        confirmation_text=str(confirmation_text or "").strip(),
    )
    try:
        argv = build_issue_assign_argv(
            issue_id=request.issue_id,
            agent=request.agent,
            confirmed=request.confirmed,
            confirmation_text=request.confirmation_text,
        )
    except ValueError as exc:
        code = str(exc) or "issue_assign_rejected"
        return MulticaIssueAssignResult(
            ok=False,
            issue_id=request.issue_id,
            agent=request.agent,
            error_code=code,
            message=_error_message(code, request.issue_id, request.agent),
        )

    result = run_multica_argv(CONFIRMED_ISSUE_ASSIGN_KEY, argv, runner=runner)
    if not result.ok:
        return MulticaIssueAssignResult(
            ok=False,
            issue_id=request.issue_id,
            agent=request.agent,
            error_code=result.error_code or "multica_issue_assign_failed",
            raw_summary=_compact_raw(result.stderr or result.stdout),
            message=result.message or "Multica issue 分配失败。",
        )

    return _parse_assign_result(result.stdout, fallback_issue_id=request.issue_id, fallback_agent=request.agent)


def _parse_assign_result(stdout: str, *, fallback_issue_id: str, fallback_agent: str) -> MulticaIssueAssignResult:
    raw_summary = _compact_raw(stdout)
    warnings = (_ASSIGN_WARNING,)
    try:
        data = json.loads(str(stdout or "{}"))
    except json.JSONDecodeError:
        return MulticaIssueAssignResult(
            ok=True,
            assigned=True,
            issue_id=fallback_issue_id,
            agent=fallback_agent,
            raw_summary=raw_summary,
            warnings=warnings + ("Multica 返回非 JSON；已保留原始摘要。",),
            message=f"Multica issue 已分配给 {fallback_agent}。小黄未额外启动 Agent，未读取运行记录。",
        )

    issue = _issue_payload(data)
    issue_id = _first_text(issue, ("id", "issue_id", "uuid", "key", "identifier")) or fallback_issue_id
    agent = _extract_assignee(issue) or fallback_agent
    status = _first_text(issue, ("status", "state"))
    return MulticaIssueAssignResult(
        ok=True,
        assigned=True,
        issue_id=issue_id,
        agent=agent,
        status=status,
        raw_summary=raw_summary,
        warnings=warnings,
        message=f"Multica issue 已分配给 {agent}。小黄未额外启动 Agent，未读取运行记录。",
    )


def _issue_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        for key in ("issue", "data", "result"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return data
    return {}


def _extract_assignee(data: dict[str, Any]) -> str:
    assignee = data.get("assignee") or data.get("assigned_to")
    if isinstance(assignee, dict):
        return _first_text(assignee, ("name", "id"))
    if assignee is not None:
        return str(assignee).strip()
    return ""


def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _compact_raw(text: str) -> str:
    value = redact_sensitive_text(" ".join(str(text or "").split()))
    if len(value) > _MAX_RAW_SUMMARY_CHARS:
        return value[:_MAX_RAW_SUMMARY_CHARS].rstrip() + "...<truncated>"
    return value


def _error_message(code: str, issue_id: str, agent: str) -> str:
    if code == "missing_issue_id":
        return "Issue ID 不能为空。"
    if code == "missing_agent":
        return "Agent 不能为空。"
    if code == "unsupported_agent":
        return "Agent 不在允许分配名单中。"
    if code == "invalid_issue_id":
        return "Issue ID 格式不安全。"
    if code == "confirmation_required":
        expected = expected_issue_assign_confirmation(issue_id, agent)
        return f"分配真实 Multica issue 需要二次确认，确认短语必须是 {expected}。"
    return "Multica issue assign 请求被安全策略拒绝。"
