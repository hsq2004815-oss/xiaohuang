"""runtime_events/models.py — RuntimeEvent dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RuntimeEvent:
    timestamp: str  # ISO format
    source: str
    event_type: str
    message: str
    level: str = "info"  # debug / info / warning / error
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "event_type": self.event_type,
            "message": self.message,
            "level": self.level,
            "details": self.details,
        }

    @classmethod
    def now(
        cls,
        source: str,
        event_type: str,
        message: str,
        *,
        level: str = "info",
        details: dict | None = None,
    ) -> RuntimeEvent:
        return cls(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            source=source,
            event_type=event_type,
            message=message,
            level=level,
            details=details or {},
        )
