from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class WakeEvent:
    engine_type: str
    wake_phrase: str
    label: str
    score: float | None
    detected_at: float
    raw_event_count: int = 1
    suppressed_event_count: int = 0


@dataclass(frozen=True)
class WakeEngineStatus:
    engine_type: str
    running: bool
    ready: bool
    model_loaded: bool
    wake_phrase: str
    sensitivity: float
    last_wake_time: float | None = None
    last_score: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class WakeEventStats:
    raw_detections: int
    coalesced_events: int
    suppressed_detections: int
    cooldown_seconds: float


class WakeEngine(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def status(self) -> WakeEngineStatus:
        ...


@dataclass
class _LabelWindow:
    raw_event_count: int = 0
    suppressed_event_count: int = 0
    last_score: float | None = None


class WakeEventCoalescer:
    def __init__(self, cooldown_seconds: float = 2.5) -> None:
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be greater than or equal to 0")
        self.cooldown_seconds = float(cooldown_seconds)
        self._last_event_time_by_label: dict[str, float] = {}
        self._window_by_label: dict[str, _LabelWindow] = {}
        self._raw_detections = 0
        self._coalesced_events = 0
        self._suppressed_detections = 0

    def accept(
        self,
        label: str,
        now: float,
        score: float | None = None,
        *,
        coalesce: bool = True,
    ) -> bool:
        normalized_label = _normalize_label(label)
        now = float(now)
        self._raw_detections += 1

        if coalesce:
            last_event_time = self._last_event_time_by_label.get(normalized_label)
            if (
                last_event_time is not None
                and self.cooldown_seconds > 0
                and now - last_event_time < self.cooldown_seconds
            ):
                window = self._window_by_label.setdefault(normalized_label, _LabelWindow())
                window.raw_event_count += 1
                window.suppressed_event_count += 1
                window.last_score = score
                self._suppressed_detections += 1
                return False

        self._last_event_time_by_label[normalized_label] = now
        self._window_by_label[normalized_label] = _LabelWindow(
            raw_event_count=1,
            suppressed_event_count=0,
            last_score=score,
        )
        self._coalesced_events += 1
        return True

    def remaining_seconds(self, label: str, now: float) -> float:
        normalized_label = _normalize_label(label)
        last_event_time = self._last_event_time_by_label.get(normalized_label)
        if last_event_time is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (float(now) - last_event_time))

    def event_counts(self, label: str) -> tuple[int, int]:
        window = self._window_by_label.get(_normalize_label(label))
        if window is None:
            return 0, 0
        return window.raw_event_count, window.suppressed_event_count

    def reset(self) -> None:
        self._last_event_time_by_label.clear()
        self._window_by_label.clear()
        self._raw_detections = 0
        self._coalesced_events = 0
        self._suppressed_detections = 0

    def stats(self) -> WakeEventStats:
        return WakeEventStats(
            raw_detections=self._raw_detections,
            coalesced_events=self._coalesced_events,
            suppressed_detections=self._suppressed_detections,
            cooldown_seconds=self.cooldown_seconds,
        )


class FakeWakeEngine:
    def __init__(
        self,
        *,
        wake_phrase: str = "贾维斯",
        label: str = "fake",
        sensitivity: float = 0.5,
        cooldown_seconds: float = 2.5,
        now_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self.engine_type = "fake"
        self.wake_phrase = wake_phrase
        self.label = label
        self.sensitivity = float(sensitivity)
        self.coalescer = WakeEventCoalescer(cooldown_seconds)
        self._now_func = now_func
        self._running = False
        self._last_wake_time: float | None = None
        self._last_score: float | None = None
        self._error: str | None = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def set_error(self, error: str | None) -> None:
        self._error = error

    def status(self) -> WakeEngineStatus:
        ready = self._running and self._error is None
        return WakeEngineStatus(
            engine_type=self.engine_type,
            running=self._running,
            ready=ready,
            model_loaded=ready,
            wake_phrase=self.wake_phrase,
            sensitivity=self.sensitivity,
            last_wake_time=self._last_wake_time,
            last_score=self._last_score,
            error=self._error,
        )

    def emit_fake_event(
        self,
        *,
        label: str | None = None,
        score: float | None = None,
        now: float | None = None,
    ) -> WakeEvent | None:
        if not self._running or self._error is not None:
            return None

        resolved_label = _normalize_label(label or self.label)
        resolved_score = 1.0 if score is None else float(score)
        detected_at = self._now_func() if now is None else float(now)
        self._last_score = resolved_score
        if resolved_score < self.sensitivity:
            return None

        if not self.coalescer.accept(resolved_label, detected_at, resolved_score):
            return None

        raw_event_count, suppressed_event_count = self.coalescer.event_counts(resolved_label)
        self._last_wake_time = detected_at
        return WakeEvent(
            engine_type=self.engine_type,
            wake_phrase=self.wake_phrase,
            label=resolved_label,
            score=resolved_score,
            detected_at=detected_at,
            raw_event_count=raw_event_count,
            suppressed_event_count=suppressed_event_count,
        )


def _normalize_label(label: str) -> str:
    normalized = str(label or "").strip()
    return normalized or "unknown"
