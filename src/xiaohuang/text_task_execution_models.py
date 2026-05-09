"""Models for confirmed text task execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextTaskExecutionResult:
    ok: bool
    task_id: str
    task_type: str
    status: str
    title: str
    summary: str
    details: str = ""
    risk_level: str = "low"
    read_files: tuple[str, ...] = ()
    error: str = ""
