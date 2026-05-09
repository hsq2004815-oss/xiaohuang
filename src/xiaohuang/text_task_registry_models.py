"""Models for server-side pending text task registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingTaskRecord:
    task_id: str
    task: dict[str, Any]
    status: str
    created_at: float
    expires_at: float
    completed_at: float | None = None
    error: str = ""
