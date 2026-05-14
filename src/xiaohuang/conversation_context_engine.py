"""Entry point for building DeepSeek-visible conversation context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xiaohuang.conversation_compaction_service import compact_conversation_if_needed
from xiaohuang.conversation_context_pack_service import (
    ContextPack,
    build_context_pack,
    build_task_context_text,
)
from xiaohuang.conversation_context_usage_service import ContextBudgetConfig
from xiaohuang.conversation_history_service import ConversationHistoryStore


@dataclass(frozen=True)
class ConversationContextBuildResult:
    context_text: str
    context_pack: ContextPack | None = None
    error: str = ""


def build_context_pack_for_turn(
    conversation_id: str | None,
    current_user_text: str,
    history_store: ConversationHistoryStore | None,
    config: ContextBudgetConfig | None = None,
) -> ConversationContextBuildResult:
    conv_id = str(conversation_id or "").strip()
    if not conv_id or history_store is None:
        return ConversationContextBuildResult(context_text="")
    try:
        if history_store.get_conversation(conv_id) is None:
            return ConversationContextBuildResult(context_text="")
        tasks = history_store.get_bound_tasks(conv_id)
        cfg = config or ContextBudgetConfig()
        task_context_text = build_task_context_text(tasks, max_chars=cfg.max_task_summary_chars)
        compaction = compact_conversation_if_needed(
            conversation_id=conv_id,
            current_user_text=current_user_text,
            history_store=history_store,
            config=cfg,
            task_context_text=task_context_text,
        )
        pack = build_context_pack(
            conversation_id=conv_id,
            current_user_text=current_user_text,
            history_store=history_store,
            compaction_result=compaction,
            config=cfg,
        )
        return ConversationContextBuildResult(context_text=pack.rendered_context_text, context_pack=pack)
    except Exception as exc:
        return ConversationContextBuildResult(context_text="", error=str(exc))


def build_llm_conversation_context(
    conversation_id: str | None,
    current_user_text: str,
    history_store: ConversationHistoryStore | None,
    config: ContextBudgetConfig | None = None,
) -> str:
    return build_context_pack_for_turn(
        conversation_id,
        current_user_text,
        history_store,
        config,
    ).context_text
