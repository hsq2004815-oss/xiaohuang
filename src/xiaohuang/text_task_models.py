from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PendingTextTask:
    task_id: str
    title: str
    task_type: str
    summary: str
    risk_level: str
    status: str
    allowed: bool
    original_text: str
    reason: str = ""


@dataclass(frozen=True)
class TextTaskIntentResult:
    is_task: bool
    task_type: str = ""
    title: str = ""
    summary: str = ""
    risk_level: str = "low"
    allowed: bool = True
    reason: str = ""
