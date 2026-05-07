"""local_commands/models.py — dataclasses for the capability router."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class LocalCommandIntent:
    command: str
    args: dict[str, Any] = field(default_factory=dict)
    original_text: str = ""
    confidence: float = 1.0
    matched_phrase: str | None = None


@dataclass(frozen=True)
class LocalCommandResult:
    ok: bool
    command: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    risk: str = "low"
    executed: bool = False


@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    description: str
    risk: str  # low / medium / high
    enabled: bool
    handler: Callable[..., LocalCommandResult]


@dataclass(frozen=True)
class RouteDecision:
    is_task_request: bool
    can_execute: bool
    command: str | None = None
    reason: str = ""
    message: str = ""
    requires_confirmation: bool = False
    intent: LocalCommandIntent | None = None
