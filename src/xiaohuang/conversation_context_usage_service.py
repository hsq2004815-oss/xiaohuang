"""Token-budget helpers for conversation context packs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ContextBudgetConfig:
    context_token_limit: int = 6000
    reserved_output_tokens: int = 768
    preserve_recent_messages: int = 8
    compact_trigger_ratio: float = 0.82
    max_compact_summary_chars: int = 2400
    max_recent_message_chars: int = 500
    max_task_summary_chars: int = 1000

    @property
    def usable_input_tokens(self) -> int:
        return max(256, int(self.context_token_limit) - int(self.reserved_output_tokens))


@dataclass(frozen=True)
class ContextBudgetReport:
    estimated_total_tokens: int
    estimated_summary_tokens: int
    estimated_recent_message_tokens: int
    estimated_task_tokens: int
    estimated_current_user_tokens: int
    context_token_limit: int
    reserved_output_tokens: int
    free_tokens: int
    used_percentage: float
    should_compact: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_text_tokens(text: str) -> int:
    value = str(text or "")
    if not value:
        return 0
    # Deliberately rough and conservative enough for preflight budgeting.
    return len(value) // 4 + 1


def estimate_message_tokens(message: Any) -> int:
    role = _message_role(message)
    text = _message_text(message)
    meta = _message_meta(message)
    meta_text = ""
    if isinstance(meta, dict) and meta:
        interesting = {
            key: meta.get(key)
            for key in ("reply_source", "task_id", "issue_id", "run_status")
            if meta.get(key)
        }
        meta_text = str(interesting) if interesting else ""
    return estimate_text_tokens(f"{role}: {text}\n{meta_text}")


def estimate_messages_tokens(messages: list[Any]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def build_context_budget_report(
    *,
    compact_summary: str = "",
    recent_messages: list[Any] | None = None,
    task_context_text: str = "",
    current_user_text: str = "",
    config: ContextBudgetConfig | None = None,
    reason_hint: str = "",
) -> ContextBudgetReport:
    cfg = config or ContextBudgetConfig()
    summary_tokens = estimate_text_tokens(compact_summary)
    recent_tokens = estimate_messages_tokens(list(recent_messages or []))
    task_tokens = estimate_text_tokens(task_context_text)
    current_tokens = estimate_text_tokens(current_user_text)
    total = summary_tokens + recent_tokens + task_tokens + current_tokens
    usable = cfg.usable_input_tokens
    threshold = int(usable * float(cfg.compact_trigger_ratio))
    free = max(0, usable - total)
    should = total >= threshold
    reason = reason_hint or ("estimated context exceeds compact threshold" if should else "within context budget")
    used_pct = round((total / max(1, usable)) * 100, 1)
    return ContextBudgetReport(
        estimated_total_tokens=total,
        estimated_summary_tokens=summary_tokens,
        estimated_recent_message_tokens=recent_tokens,
        estimated_task_tokens=task_tokens,
        estimated_current_user_tokens=current_tokens,
        context_token_limit=cfg.context_token_limit,
        reserved_output_tokens=cfg.reserved_output_tokens,
        free_tokens=free,
        used_percentage=used_pct,
        should_compact=should,
        reason=reason,
    )


def should_compact(report: ContextBudgetReport, message_count: int, preserve_recent_messages: int) -> bool:
    return bool(report.should_compact and message_count > max(0, preserve_recent_messages))


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("text") or "")
    return str(getattr(message, "text", "") or "")


def _message_meta(message: Any) -> dict:
    if isinstance(message, dict):
        meta = message.get("meta") or {}
    else:
        meta = getattr(message, "meta", {}) or {}
    return meta if isinstance(meta, dict) else {}
