"""Deterministic conversation compaction for model-visible context windows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from xiaohuang.conversation_context_usage_service import (
    ContextBudgetConfig,
    ContextBudgetReport,
    build_context_budget_report,
    estimate_messages_tokens,
)
from xiaohuang.conversation_context_metadata_service import (
    append_compaction_event,
    get_context_state,
    save_context_state,
)
from xiaohuang.conversation_history_service import ConversationHistoryStore, MessageRecord


@dataclass(frozen=True)
class ConversationCompactionState:
    conversation_id: str
    compact_summary: str = ""
    compact_count: int = 0
    last_removed_message_count: int = 0
    last_compacted_message_id: str = ""
    last_compacted_at: str = ""
    last_budget_report: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationCompactionState":
        return cls(
            conversation_id=str(data.get("conversation_id") or ""),
            compact_summary=str(data.get("compact_summary") or ""),
            compact_count=int(data.get("compact_count") or 0),
            last_removed_message_count=int(data.get("last_removed_message_count") or 0),
            last_compacted_message_id=str(data.get("last_compacted_message_id") or ""),
            last_compacted_at=str(data.get("last_compacted_at") or ""),
            last_budget_report=data.get("last_budget_report") if isinstance(data.get("last_budget_report"), dict) else {},
        )


@dataclass(frozen=True)
class ConversationCompactionResult:
    state: ConversationCompactionState
    recent_messages: list[MessageRecord]
    budget_report: ContextBudgetReport
    compacted: bool = False
    removed_message_count: int = 0


def compact_conversation_if_needed(
    *,
    conversation_id: str,
    current_user_text: str,
    history_store: ConversationHistoryStore,
    config: ContextBudgetConfig | None = None,
    task_context_text: str = "",
) -> ConversationCompactionResult:
    cfg = config or ContextBudgetConfig()
    messages = _without_current_user_duplicate(
        history_store.get_messages(conversation_id),
        current_user_text,
    )
    raw_state = get_context_state(history_store, conversation_id)
    state = ConversationCompactionState.from_dict(raw_state)

    if not state.compact_summary:
        full_report = build_context_budget_report(
            compact_summary="",
            recent_messages=messages,
            task_context_text=task_context_text,
            current_user_text=current_user_text,
            config=cfg,
        )
        if not full_report.should_compact or len(messages) <= cfg.preserve_recent_messages:
            save_context_state(
                history_store,
                conversation_id,
                compact_summary="",
                compact_count=0,
                last_removed_message_count=0,
                last_compacted_message_id="",
                last_budget_report=full_report.to_dict(),
            )
            return ConversationCompactionResult(
                state=state,
                recent_messages=messages,
                budget_report=full_report,
            )

    compactable, recent_messages = split_compactable_messages(
        messages,
        preserve_recent_count=cfg.preserve_recent_messages,
        last_compacted_message_id=state.last_compacted_message_id,
    )

    if compactable:
        new_summary = build_compact_summary(compactable, max_chars=cfg.max_compact_summary_chars)
        compact_summary = merge_compact_summaries(
            state.compact_summary,
            new_summary,
            max_chars=cfg.max_compact_summary_chars,
        )
        compact_count = state.compact_count + 1
        last_compacted_message_id = compactable[-1].id
        report_after = build_context_budget_report(
            compact_summary=compact_summary,
            recent_messages=recent_messages,
            task_context_text=task_context_text,
            current_user_text=current_user_text,
            config=cfg,
            reason_hint="compacted older conversation messages",
        )
        save_context_state(
            history_store,
            conversation_id,
            compact_summary=compact_summary,
            compact_count=compact_count,
            last_removed_message_count=len(compactable),
            last_compacted_message_id=last_compacted_message_id,
            last_budget_report=report_after.to_dict(),
        )
        append_compaction_event(
            history_store,
            conversation_id,
            compact_summary=compact_summary,
            removed_message_count=len(compactable),
            preserved_recent_count=len(recent_messages),
            estimated_tokens_before=estimate_messages_tokens(messages),
            estimated_tokens_after=report_after.estimated_total_tokens,
            meta={
                "last_compacted_message_id": last_compacted_message_id,
                "budget_report": report_after.to_dict(),
            },
        )
        updated_state = ConversationCompactionState(
            conversation_id=conversation_id,
            compact_summary=compact_summary,
            compact_count=compact_count,
            last_removed_message_count=len(compactable),
            last_compacted_message_id=last_compacted_message_id,
            last_compacted_at=get_context_state(history_store, conversation_id).get("last_compacted_at", ""),
            last_budget_report=report_after.to_dict(),
        )
        return ConversationCompactionResult(
            state=updated_state,
            recent_messages=recent_messages,
            budget_report=report_after,
            compacted=True,
            removed_message_count=len(compactable),
        )

    report = build_context_budget_report(
        compact_summary=state.compact_summary,
        recent_messages=recent_messages,
        task_context_text=task_context_text,
        current_user_text=current_user_text,
        config=cfg,
    )
    save_context_state(
        history_store,
        conversation_id,
        compact_summary=state.compact_summary,
        compact_count=state.compact_count,
        last_removed_message_count=state.last_removed_message_count,
        last_compacted_message_id=state.last_compacted_message_id,
        last_budget_report=report.to_dict(),
    )
    return ConversationCompactionResult(
        state=state,
        recent_messages=recent_messages,
        budget_report=report,
    )


def split_compactable_messages(
    messages: list[MessageRecord],
    *,
    preserve_recent_count: int,
    last_compacted_message_id: str = "",
) -> tuple[list[MessageRecord], list[MessageRecord]]:
    if not messages:
        return [], []
    preserve = max(0, preserve_recent_count)
    keep_from = max(0, len(messages) - preserve)
    keep_from = _adjust_boundary_for_paired_snapshots(messages, keep_from)
    recent = messages[keep_from:]
    already_index = _message_index(messages, last_compacted_message_id)
    compactable_start = already_index + 1 if already_index >= 0 else 0
    if compactable_start >= keep_from:
        return [], recent
    return messages[compactable_start:keep_from], recent


def build_compact_summary(messages: list[MessageRecord], *, max_chars: int = 2400) -> str:
    if not messages:
        return ""
    counts: dict[str, int] = {}
    for message in messages:
        counts[message.role] = counts.get(message.role, 0) + 1
    user_requests = [
        _truncate(message.text, 140)
        for message in messages
        if message.role == "user" and message.text.strip()
    ][-4:]
    pending = [
        _truncate(message.text, 140)
        for message in messages
        if _looks_pending(message.text)
    ][-4:]
    refs = _collect_key_refs(messages)
    lines = [
        "Conversation compact summary:",
        f"- Scope: {len(messages)} earlier messages compacted ({_format_counts(counts)}).",
    ]
    if user_requests:
        lines.append("- Recent user requests:")
        lines.extend(f"  - {item}" for item in user_requests)
    if pending:
        lines.append("- Pending or follow-up signals:")
        lines.extend(f"  - {item}" for item in pending)
    if refs:
        lines.append(f"- Key references: {', '.join(refs[:10])}.")
    lines.append("- Key timeline:")
    for message in messages[-12:]:
        lines.append(f"  - {message.role}: {_truncate(message.text, 160)}")
    return _truncate("\n".join(lines), max_chars)


def merge_compact_summaries(existing_summary: str, new_summary: str, *, max_chars: int = 2400) -> str:
    existing = str(existing_summary or "").strip()
    new = str(new_summary or "").strip()
    if not existing:
        return _truncate(new, max_chars)
    if not new:
        return _truncate(existing, max_chars)
    merged = "\n".join([
        "Conversation compact summary:",
        "- Previously compacted context:",
        _indent(_strip_summary_title(existing)),
        "- Newly compacted context:",
        _indent(_strip_summary_title(new)),
    ])
    return _truncate(merged, max_chars)


def select_recent_messages_safely(messages: list[MessageRecord], preserve_recent_count: int) -> list[MessageRecord]:
    _, recent = split_compactable_messages(messages, preserve_recent_count=preserve_recent_count)
    return recent


def _without_current_user_duplicate(messages: list[MessageRecord], current_user_text: str) -> list[MessageRecord]:
    text = str(current_user_text or "").strip()
    if not messages or not text:
        return messages
    last = messages[-1]
    if last.role == "user" and last.text.strip() == text:
        return messages[:-1]
    return messages


def _adjust_boundary_for_paired_snapshots(messages: list[MessageRecord], keep_from: int) -> int:
    k = max(0, keep_from)
    while k > 0 and k < len(messages):
        first = messages[k]
        previous = messages[k - 1]
        if _starts_with_result_snapshot(first) and _has_pending_snapshot(previous):
            k -= 1
            continue
        break
    return k


def _starts_with_result_snapshot(message: MessageRecord) -> bool:
    meta = message.meta or {}
    return bool(message.execution_result_snapshot or meta.get("tool_result_id") or meta.get("result_id"))


def _has_pending_snapshot(message: MessageRecord) -> bool:
    meta = message.meta or {}
    return bool(message.pending_task_snapshot or meta.get("tool_use_id") or meta.get("pending_task_id"))


def _message_index(messages: list[MessageRecord], message_id: str) -> int:
    if not message_id:
        return -1
    for index, message in enumerate(messages):
        if message.id == message_id:
            return index
    return -1


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{role}={count}" for role, count in sorted(counts.items())) or "none"


def _looks_pending(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in ("todo", "next", "pending", "follow up", "remaining", "下一步", "待", "继续"))


def _collect_key_refs(messages: list[MessageRecord]) -> list[str]:
    pattern = re.compile(r"([A-Za-z]:\\[^\s，。；;:]+|[\w./-]+\.(?:py|js|css|html|md|json)|[A-Z]{2,}-\d+|task-[\w-]+|[0-9a-f]{8,})")
    refs: list[str] = []
    for message in messages:
        for match in pattern.findall(message.text or ""):
            cleaned = match.strip("`'\".,;:()[]{}")
            if cleaned and cleaned not in refs:
                refs.append(cleaned)
    return refs[:12]


def _truncate(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in str(text or "").splitlines())


def _strip_summary_title(text: str) -> str:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if lines and lines[0].strip().lower() == "conversation compact summary:":
        return "\n".join(lines[1:])
    return "\n".join(lines)
