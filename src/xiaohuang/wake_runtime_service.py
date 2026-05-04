from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from xiaohuang.openwakeword_adapter import (
    OpenWakeWordDependencyStatus,
    check_openwakeword_dependencies,
)
from xiaohuang.wake_loop_service import WakeLoopOptions

if TYPE_CHECKING:
    from xiaohuang.app_config_service import XiaoHuangConfig


WAKE_ENGINE_STT_TEXT = "stt_text"
WAKE_ENGINE_OPENWAKEWORD = "openwakeword"
OPENWAKEWORD_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class WakeEngineRuntimeConfig:
    engine: str
    wake_phrase: str
    fallback_enabled: bool
    device: int | None
    sample_rate: int
    sensitivity: float
    cooldown_seconds: float
    model_path: str | None
    model_name: str | None
    poll_seconds: float = OPENWAKEWORD_POLL_SECONDS


@dataclass(frozen=True)
class WakeEngineRuntimePlan:
    engine: str
    warning: str | None = None
    error: str | None = None
    dependency_status: OpenWakeWordDependencyStatus | None = None


def normalize_wake_engine(engine: str | None) -> str:
    text = str(engine or WAKE_ENGINE_STT_TEXT).strip().lower().replace("-", "_")
    return text or WAKE_ENGINE_STT_TEXT


def build_wake_engine_runtime_config(app_config: "XiaoHuangConfig", options: WakeLoopOptions) -> WakeEngineRuntimeConfig:
    wake_phrase = app_config.wake.phrases[0] if app_config.wake.phrases else "小黄"
    wake_device = app_config.wake.device_index if app_config.wake.device_index is not None else options.device_id
    return WakeEngineRuntimeConfig(
        engine=normalize_wake_engine(app_config.wake.engine),
        wake_phrase=wake_phrase,
        fallback_enabled=bool(app_config.wake.fallback_enabled),
        device=wake_device,
        sample_rate=options.sample_rate,
        sensitivity=float(app_config.wake.sensitivity),
        cooldown_seconds=float(app_config.wake.cooldown_seconds),
        model_path=app_config.wake.model_path,
        model_name=app_config.wake.model_name,
        poll_seconds=max(0.1, min(float(app_config.wake.wake_window_seconds), OPENWAKEWORD_POLL_SECONDS)),
    )


def select_wake_engine_runtime(
    runtime_config: WakeEngineRuntimeConfig,
    *,
    dependency_status: OpenWakeWordDependencyStatus | None = None,
) -> WakeEngineRuntimePlan:
    engine = normalize_wake_engine(runtime_config.engine)
    if engine == WAKE_ENGINE_STT_TEXT:
        return WakeEngineRuntimePlan(engine=WAKE_ENGINE_STT_TEXT)

    if engine != WAKE_ENGINE_OPENWAKEWORD:
        message = f"Unsupported wake.engine={runtime_config.engine!r}"
        if runtime_config.fallback_enabled:
            return WakeEngineRuntimePlan(
                engine=WAKE_ENGINE_STT_TEXT,
                warning=f"{message}; falling back to stt_text",
            )
        return WakeEngineRuntimePlan(engine=engine, error=message)

    status = dependency_status or check_openwakeword_dependencies()
    if status.ready_for_realtime_demo:
        return WakeEngineRuntimePlan(engine=WAKE_ENGINE_OPENWAKEWORD, dependency_status=status)

    message = format_openwakeword_dependency_error(status)
    if runtime_config.fallback_enabled:
        return WakeEngineRuntimePlan(
            engine=WAKE_ENGINE_STT_TEXT,
            warning=f"{message}; falling back to stt_text",
            dependency_status=status,
        )
    return WakeEngineRuntimePlan(
        engine=WAKE_ENGINE_OPENWAKEWORD,
        error=message,
        dependency_status=status,
    )


def format_openwakeword_dependency_error(status: OpenWakeWordDependencyStatus) -> str:
    details = "; ".join(status.errors) if status.errors else "dependency check failed"
    return f"openwakeword dependency unavailable: {details}"
