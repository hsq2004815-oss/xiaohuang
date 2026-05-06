"""preflight_check/models.py — dataclasses for startup preflight check."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PreflightCheckItem:
    key: str
    label: str
    status: str  # ok / warning / error
    message: str
    suggestion: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "suggestion": self.suggestion,
            "details": self.details,
        }


@dataclass(frozen=True)
class PreflightCheckResult:
    status: str  # ok / warning / error
    summary: str
    items: list[PreflightCheckItem]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
        }
