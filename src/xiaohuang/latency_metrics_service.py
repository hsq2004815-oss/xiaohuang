from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Callable

Clock = Callable[[], float]


@dataclass
class LatencySpan:
    name: str
    start: float
    end: float | None = None

    @property
    def elapsed_ms(self) -> float | None:
        if self.end is None:
            return None
        return round((self.end - self.start) * 1000.0, 1)


@dataclass
class LatencyTracker:
    clock: Clock = perf_counter
    spans: dict[str, LatencySpan] = field(default_factory=dict)

    def start(self, name: str) -> None:
        self.spans[name] = LatencySpan(name=name, start=self.clock())

    def end(self, name: str) -> None:
        span = self.spans.get(name)
        if span is not None and span.end is None:
            span.end = self.clock()

    def summary_ms(self) -> dict[str, float]:
        return {
            name: span.elapsed_ms
            for name, span in self.spans.items()
            if span.elapsed_ms is not None
        }


def format_latency_summary(
    summary: dict[str, float],
    *,
    turn: int = 1,
    source: str = "",
) -> str:
    parts = [f"turn={turn}"]
    if source:
        parts.append(f"source={source}")
    for key in sorted(summary):
        parts.append(f"{key}={summary[key]}")
    return "Overlay latency: " + " ".join(parts)
