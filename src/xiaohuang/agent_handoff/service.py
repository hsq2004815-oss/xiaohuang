"""High-level Agent Handoff draft service."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from xiaohuang.agent_handoff.database_brief_client import fetch_database_brief
from xiaohuang.agent_handoff.domain_router import route_domains
from xiaohuang.agent_handoff.handoff_file_service import (
    relative_handoff_path,
    write_handoff_file,
)
from xiaohuang.agent_handoff.intent_parser import detect_target_agent
from xiaohuang.agent_handoff.intent_parser import extract_actual_task
from xiaohuang.agent_handoff.models import (
    AgentHandoffRequest,
    AgentHandoffResult,
    DatabaseBriefResult,
)
from xiaohuang.agent_handoff.prompt_builder import (
    agent_label,
    build_agent_handoff_prompt,
    build_handoff_preview,
    build_handoff_title,
)

BriefFetcher = Callable[[str, list[str]], DatabaseBriefResult]
FileWriter = Callable[[Path, str, str, str], Path]


def create_agent_handoff(
    request: AgentHandoffRequest,
    *,
    project_root: Path | str,
    brief_fetcher: BriefFetcher | None = None,
    file_writer: FileWriter | None = None,
) -> AgentHandoffResult:
    root = Path(project_root).resolve()
    user_request = str(request.user_request or "").strip()
    if not user_request:
        return AgentHandoffResult(
            ok=False,
            title="生成 Agent 交接提示词失败",
            summary="用户需求为空，无法生成 Agent Handoff 草稿。",
            target_agent="generic",
            domains=[],
            database_status="not_requested",
            error_message="empty_user_request",
            tags=["agent", "handoff"],
        )

    target_agent = request.target_agent if request.target_agent and request.target_agent != "generic" else detect_target_agent(user_request)
    actual_task = str(request.actual_task or "").strip() or extract_actual_task(user_request, target_agent=target_agent) or user_request
    route_text = f"{user_request} {actual_task}"
    domains = list(request.domain_hints or route_domains(route_text))

    if request.use_database:
        fetcher = brief_fetcher or _default_brief_fetcher
        database = fetcher(f"{actual_task}\n\n用户原始需求：{user_request}", domains)
    else:
        database = DatabaseBriefResult(database_used=False, database_status="not_requested")

    normalized_request = AgentHandoffRequest(
        user_request=user_request,
        target_agent=target_agent,
        actual_task=actual_task,
        project_hint=request.project_hint,
        domain_hints=domains,
        source=request.source,
        use_database=request.use_database,
    )
    title = build_handoff_title(normalized_request)
    prompt = build_agent_handoff_prompt(
        normalized_request,
        project_root=root,
        domains=domains,
        database_brief=database,
    )
    preview = build_handoff_preview(prompt)

    try:
        writer = file_writer or _default_file_writer
        path = writer(root, target_agent, actual_task, prompt)
        rel_path = relative_handoff_path(path, root)
    except Exception as exc:
        return AgentHandoffResult(
            ok=False,
            title=title,
            summary="Agent Handoff 草稿生成完成，但保存文件失败。",
            target_agent=target_agent,
            domains=domains,
            handoff_preview=preview,
            database_used=database.database_used,
            database_status=database.database_status,
            error_message=str(exc),
            tags=["agent", "handoff", target_agent],
        )

    return AgentHandoffResult(
        ok=True,
        title=title,
        summary=(
            f"已生成 {agent_label(target_agent)} 提示词草稿；"
            f"数据库 brief {'已使用' if database.database_used else '不可用，已安全降级'}。"
        ),
        target_agent=target_agent,
        domains=domains,
        handoff_path=rel_path,
        handoff_preview=preview,
        database_used=database.database_used,
        database_status=database.database_status,
        error_message="",
        tags=["agent", "handoff", target_agent],
    )


def _default_brief_fetcher(query: str, domains: list[str]) -> DatabaseBriefResult:
    return fetch_database_brief(query=query, domains=domains)


def _default_file_writer(root: Path, target_agent: str, user_request: str, prompt: str) -> Path:
    return write_handoff_file(
        project_root=root,
        target_agent=target_agent,
        user_request=user_request,
        content=prompt,
    )
