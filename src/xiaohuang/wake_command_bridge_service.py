from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from xiaohuang.wake_engine_service import WakeEvent


REASON_ACCEPTED = "accepted"
REASON_DISABLED = "disabled"
REASON_COOLDOWN = "cooldown"
REASON_COMMAND_ACTIVE = "command_active"
REASON_TTS_ACTIVE = "tts_active"
REASON_BRIDGE_BUSY = "bridge_busy"
REASON_INVALID_EVENT = "invalid_event"
REASON_RECORDER_ERROR = "recorder_error"


@dataclass(frozen=True)
class WakeBridgeDecision:
    accepted: bool
    reason: str
    wake_event: WakeEvent | None = None


@dataclass(frozen=True)
class WakeCommandBridgeConfig:
    enabled: bool = True
    post_wake_cooldown_seconds: float = 2.5
    pause_wake_during_command: bool = True
    pause_wake_during_tts: bool = True


@dataclass(frozen=True)
class WakeCommandBridgeState:
    enabled: bool
    command_active: bool
    tts_active: bool
    bridge_busy: bool
    last_wake_time: float | None
    accepted_count: int
    suppressed_count: int
    last_reason: str | None


class WakeCommandBridge:
    def __init__(
        self,
        config: WakeCommandBridgeConfig,
        command_starter: Callable[[WakeEvent], object],
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        if config.post_wake_cooldown_seconds < 0:
            raise ValueError("post_wake_cooldown_seconds must be greater than or equal to 0")
        self.config = config
        self._command_starter = command_starter
        self._time_fn = time_fn or time.monotonic
        self._command_active = False
        self._tts_active = False
        self._bridge_busy = False
        self._last_wake_time: float | None = None
        self._accepted_count = 0
        self._suppressed_count = 0
        self._last_reason: str | None = None

    def handle_wake_event(self, event: WakeEvent) -> WakeBridgeDecision:
        if not self.config.enabled:
            return self._reject(REASON_DISABLED, event)
        if not _is_valid_wake_event(event):
            return self._reject(REASON_INVALID_EVENT, None)
        if self._command_active and self.config.pause_wake_during_command:
            return self._reject(REASON_COMMAND_ACTIVE, event)
        if self._tts_active and self.config.pause_wake_during_tts:
            return self._reject(REASON_TTS_ACTIVE, event)
        if self._bridge_busy:
            return self._reject(REASON_BRIDGE_BUSY, event)

        now = self._time_fn()
        if self._is_inside_cooldown(now):
            return self._reject(REASON_COOLDOWN, event)

        self._bridge_busy = True
        try:
            self._command_starter(event)
        except Exception:
            self._bridge_busy = False
            return self._reject(REASON_RECORDER_ERROR, event)

        self._bridge_busy = False
        self._accepted_count += 1
        self._last_wake_time = now
        self._last_reason = REASON_ACCEPTED
        return WakeBridgeDecision(accepted=True, reason=REASON_ACCEPTED, wake_event=event)

    def mark_command_started(self) -> None:
        self._command_active = True

    def mark_command_finished(self) -> None:
        self._command_active = False

    def mark_tts_started(self) -> None:
        self._tts_active = True

    def mark_tts_finished(self) -> None:
        self._tts_active = False

    def state(self) -> WakeCommandBridgeState:
        return WakeCommandBridgeState(
            enabled=self.config.enabled,
            command_active=self._command_active,
            tts_active=self._tts_active,
            bridge_busy=self._bridge_busy,
            last_wake_time=self._last_wake_time,
            accepted_count=self._accepted_count,
            suppressed_count=self._suppressed_count,
            last_reason=self._last_reason,
        )

    def reset(self) -> None:
        self._command_active = False
        self._tts_active = False
        self._bridge_busy = False
        self._last_wake_time = None
        self._accepted_count = 0
        self._suppressed_count = 0
        self._last_reason = None

    def _is_inside_cooldown(self, now: float) -> bool:
        if self._last_wake_time is None:
            return False
        return now - self._last_wake_time < self.config.post_wake_cooldown_seconds

    def _reject(self, reason: str, event: WakeEvent | None) -> WakeBridgeDecision:
        self._suppressed_count += 1
        self._last_reason = reason
        return WakeBridgeDecision(accepted=False, reason=reason, wake_event=event)


@dataclass
class FakeCommandStarter:
    raise_on_start: bool = False
    calls: list[WakeEvent] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, event: WakeEvent) -> object:
        if self.raise_on_start:
            raise RuntimeError("fake command recorder failed")
        self.calls.append(event)
        return {"started": True}


def _is_valid_wake_event(event: object) -> bool:
    if not isinstance(event, WakeEvent):
        return False
    return bool(event.engine_type and event.wake_phrase and event.label)
