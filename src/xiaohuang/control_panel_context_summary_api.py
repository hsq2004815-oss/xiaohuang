"""Deterministic conversation context summary API for the control panel."""

from __future__ import annotations

from typing import Any

from xiaohuang.conversation_context_pack_service import build_task_context_text
from xiaohuang.conversation_context_metadata_service import get_context_state
from xiaohuang.conversation_context_usage_service import (
    ContextBudgetConfig,
    build_context_budget_report,
)
from xiaohuang.conversation_history_service import ConversationHistoryStore


DEFAULT_CONSTRAINTS = [
    "不自动启动 Agent",
    "不修改 E:\\DataBase",
    "不绕过 Multica 安全确认",
    "不泄露 API Key",
]


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "data": data, "message": message}


def _fail(error: str, code: str = "error") -> dict:
    return {"ok": False, "error": error, "code": code}


class ControlPanelContextSummaryApi:
    """Read and refresh per-conversation context summary without LLM calls."""

    def __init__(self, *, history_store: ConversationHistoryStore) -> None:
        self._history_store = history_store

    def get_conversation_context_summary(self, payload: dict | None = None) -> dict:
        try:
            conversation_id = _conversation_id_from_payload(payload)
            if not conversation_id:
                return _fail("会话 ID 不能为空", "missing_conversation_id")
            context = self._history_store.get_conversation_context(conversation_id)
            snapshot = self._history_store.build_basic_context_snapshot(conversation_id)
            data = _with_derived_fields(context, snapshot)
            data = _with_context_state_fields(data, snapshot, self._history_store)
            data["snapshot"] = snapshot
            return _ok(data=data, message="上下文摘要已加载")
        except ValueError:
            return _fail("会话不存在或 ID 无效", "conversation_context_not_found")
        except Exception:
            return _fail("读取上下文摘要失败", "conversation_context_get_error")

    def refresh_conversation_context_summary(self, payload: dict | None = None) -> dict:
        try:
            conversation_id = _conversation_id_from_payload(payload)
            if not conversation_id:
                return _fail("会话 ID 不能为空", "missing_conversation_id")
            context = self._history_store.get_conversation_context(conversation_id)
            snapshot = self._history_store.build_basic_context_snapshot(conversation_id)
            generated = _generate_context_from_snapshot(context, snapshot)
            updated = self._history_store.update_conversation_context(
                conversation_id,
                context_summary=generated["context_summary"],
                current_goal=generated["current_goal"],
                current_status=generated["current_status"],
                next_step=generated["next_step"],
                important_constraints=generated["important_constraints"],
            )
            data = _with_derived_fields(updated.to_dict(), snapshot)
            data["conversation_id"] = updated.id
            data["updated_at"] = updated.updated_at
            data = _with_context_state_fields(data, snapshot, self._history_store)
            data["snapshot"] = snapshot
            return _ok(data=data, message="上下文摘要已刷新")
        except ValueError:
            return _fail("会话不存在或 ID 无效", "conversation_context_not_found")
        except Exception:
            return _fail("刷新上下文摘要失败", "conversation_context_refresh_error")

    def update_conversation_context_summary(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            conversation_id = _conversation_id_from_payload(data)
            if not conversation_id:
                return _fail("会话 ID 不能为空", "missing_conversation_id")
            existing = self._history_store.get_conversation_context(conversation_id)
            updated = self._history_store.update_conversation_context(
                conversation_id,
                context_summary=str(data.get("context_summary") or existing.get("context_summary") or ""),
                current_goal=str(data.get("current_goal") or existing.get("current_goal") or ""),
                current_status=str(data.get("current_status") or existing.get("current_status") or ""),
                next_step=str(data.get("next_step") or existing.get("next_step") or ""),
                important_constraints=_coerce_constraints(
                    data.get("important_constraints"),
                    fallback=existing.get("important_constraints") or [],
                ),
            )
            snapshot = self._history_store.build_basic_context_snapshot(conversation_id)
            result = _with_derived_fields(updated.to_dict(), snapshot)
            result["conversation_id"] = updated.id
            result["updated_at"] = updated.updated_at
            result = _with_context_state_fields(result, snapshot, self._history_store)
            result["snapshot"] = snapshot
            return _ok(data=result, message="上下文摘要已更新")
        except ValueError:
            return _fail("会话不存在或 ID 无效", "conversation_context_not_found")
        except Exception:
            return _fail("更新上下文摘要失败", "conversation_context_update_error")


def _conversation_id_from_payload(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("conversation_id") or "").strip()


def _generate_context_from_snapshot(context: dict, snapshot: dict) -> dict:
    task_counts = snapshot.get("task_counts") or {}
    message_count = int(snapshot.get("message_count") or 0)
    constraints = _coerce_constraints(context.get("important_constraints"))
    if not constraints:
        constraints = list(DEFAULT_CONSTRAINTS)

    goal = str(context.get("current_goal") or "").strip()
    if not goal:
        first_user = str(snapshot.get("first_user_message") or "").strip()
        goal = first_user[:60]

    status = _derive_status(task_counts)
    next_step = _derive_next_step(task_counts, message_count)
    bound_tasks_summary = _summarize_bound_tasks(snapshot)
    blockers = list(snapshot.get("blockers") or [])
    completed_items = list(snapshot.get("completed_items") or [])
    summary = _compose_summary(goal, status, bound_tasks_summary, blockers, next_step)
    return {
        "context_summary": summary,
        "current_goal": goal,
        "current_status": status,
        "next_step": next_step,
        "important_constraints": constraints,
        "completed_items": completed_items,
        "bound_tasks_summary": bound_tasks_summary,
        "blockers": blockers,
    }


def _derive_status(task_counts: dict) -> str:
    statuses = {str(k).lower(): int(v or 0) for k, v in task_counts.items()}
    total = sum(statuses.values())
    if not total:
        return "当前对话暂无绑定任务。"
    if statuses.get("failed", 0) or statuses.get("error", 0):
        return "当前存在失败任务，需要检查。"
    if statuses.get("running", 0) or statuses.get("in_progress", 0):
        return "当前存在进行中的绑定任务。"
    review_or_done = sum(statuses.get(s, 0) for s in ("completed", "done", "in_review", "review"))
    if review_or_done == total:
        return "当前绑定任务已完成或待验收。"
    return "当前对话有绑定任务，状态需要继续跟进。"


def _derive_next_step(task_counts: dict, message_count: int) -> str:
    statuses = {str(k).lower(): int(v or 0) for k, v in task_counts.items()}
    if statuses.get("failed", 0) or statuses.get("error", 0):
        return "检查失败任务日志或 run-messages。"
    if statuses.get("in_review", 0) or statuses.get("review", 0):
        return "进行验收并决定是否收口。"
    if statuses.get("running", 0) or statuses.get("in_progress", 0):
        return "等待进行中的任务完成后读取 run-messages。"
    if message_count > 0:
        return "根据当前对话目标创建或绑定任务。"
    return "先描述本对话要完成的目标。"


def _summarize_bound_tasks(snapshot: dict) -> str:
    tasks = list(snapshot.get("bound_tasks") or [])
    if not tasks:
        return "暂无绑定 Multica 任务。"
    counts = snapshot.get("task_counts") or {}
    parts = [f"{status or 'unknown'} {count}" for status, count in sorted(counts.items())]
    return f"已绑定 {len(tasks)} 个 Multica 任务：" + "、".join(parts) + "。"


def _compose_summary(
    goal: str,
    status: str,
    bound_tasks_summary: str,
    blockers: list[str],
    next_step: str,
) -> str:
    lines = []
    if goal:
        lines.append(f"目标：{goal}")
    lines.append(f"状态：{status}")
    lines.append(f"绑定任务：{bound_tasks_summary}")
    if blockers:
        lines.append("阻塞点：" + "；".join(blockers[:3]))
    lines.append(f"下一步：{next_step}")
    return "\n".join(lines[:6])


def _with_derived_fields(context: dict, snapshot: dict) -> dict:
    task_summary = _summarize_bound_tasks(snapshot)
    return {
        "conversation_id": context.get("conversation_id") or context.get("id") or snapshot.get("conversation_id") or "",
        "context_summary": context.get("context_summary") or "",
        "current_goal": context.get("current_goal") or "",
        "current_status": context.get("current_status") or "",
        "next_step": context.get("next_step") or "",
        "important_constraints": _coerce_constraints(context.get("important_constraints")),
        "completed_items": list(snapshot.get("completed_items") or []),
        "bound_tasks_summary": task_summary,
        "blockers": list(snapshot.get("blockers") or []),
        "updated_at": context.get("updated_at") or "",
    }


def _with_context_state_fields(data: dict, snapshot: dict, history_store: ConversationHistoryStore) -> dict:
    conversation_id = str(data.get("conversation_id") or snapshot.get("conversation_id") or "")
    state = get_context_state(history_store, conversation_id) if conversation_id else {}
    cfg = ContextBudgetConfig()
    recent_messages = list(snapshot.get("recent_messages") or [])[-cfg.preserve_recent_messages:]
    tasks = history_store.get_bound_tasks(conversation_id) if conversation_id else []
    task_text = build_task_context_text(tasks, max_chars=cfg.max_task_summary_chars)
    budget = build_context_budget_report(
        compact_summary=str(state.get("compact_summary") or ""),
        recent_messages=recent_messages,
        task_context_text=task_text,
        current_user_text="",
        config=cfg,
    )
    result = dict(data)
    result.update({
        "compact_summary": state.get("compact_summary") or "",
        "compact_count": int(state.get("compact_count") or 0),
        "recent_message_count": len(recent_messages),
        "bound_task_count": len(tasks),
        "context_loaded": bool(snapshot.get("message_count") or tasks or state.get("compact_summary")),
        "context_budget_report": budget.to_dict(),
        "context_status_summary": _format_context_status(len(recent_messages), len(tasks), int(state.get("compact_count") or 0), budget),
    })
    return result


def _format_context_status(
    recent_count: int,
    task_count: int,
    compact_count: int,
    budget,
) -> str:
    loaded = "已加载" if recent_count or task_count or compact_count else "未生成"
    return (
        f"上下文{loaded} / 最近消息 {recent_count} 条 / "
        f"Compact {compact_count} 次 / Token {budget.estimated_total_tokens}/{budget.context_token_limit} / "
        f"绑定任务 {task_count} 个"
    )


def _coerce_constraints(value: Any, *, fallback: list[str] | None = None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split("\n") if part.strip()]
    return list(fallback or [])
