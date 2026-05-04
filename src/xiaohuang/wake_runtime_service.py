from __future__ import annotations

import queue
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from xiaohuang.openwakeword_adapter import (
    OpenWakeWordAdapter,
    OpenWakeWordDependencyStatus,
    OpenWakeWordRuntimeStatus,
    check_openwakeword_dependencies,
)
from xiaohuang.wake_command_bridge_service import WakeCommandBridge, WakeCommandBridgeConfig
from xiaohuang.wake_engine_service import WakeEvent
from xiaohuang.wake_loop_service import WakeLoopOptions

if TYPE_CHECKING:
    from xiaohuang.app_config_service import XiaoHuangConfig


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

WAKE_ENGINE_STT_TEXT = "stt_text"
WAKE_ENGINE_OPENWAKEWORD = "openwakeword"
OPENWAKEWORD_POLL_SECONDS = 1.0
OPENWAKEWORD_QUEUE_POLL_SECONDS = 0.1
OPENWAKEWORD_STATUS_INTERVAL_SECONDS = 5.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _log_runtime_message(logger, level: str, message: str) -> None:
    _safe_print(message)
    log_func = getattr(logger, level, logger.info)
    log_func(message)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


# ---------------------------------------------------------------------------
# config / selection dataclasses (V1.2F-B)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# config / selection functions (V1.2F-B)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------

class WakeEngineLoopStopped(Exception):
    pass


class WakeEngineRuntimeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# listener handle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenWakeWordListenerHandle:
    thread: threading.Thread
    adapter: object
    event_queue: queue.Queue[WakeEvent]
    error_queue: queue.Queue[str]
    bridge_runtime: "OpenWakeWordBridgeRuntime"


# ---------------------------------------------------------------------------
# bridge runtime
# ---------------------------------------------------------------------------

class OpenWakeWordBridgeRuntime:
    def __init__(
        self,
        cooldown_seconds: float,
        command_queue: queue.Queue[WakeEvent] | None = None,
    ) -> None:
        self.accepted_event: WakeEvent | None = None
        self.active_adapter = None
        self.command_queue = command_queue
        self._lock = threading.RLock()
        self.bridge = WakeCommandBridge(
            WakeCommandBridgeConfig(post_wake_cooldown_seconds=cooldown_seconds),
            self._accept_wake_event,
        )

    def begin_wait(self, adapter) -> None:
        with self._lock:
            self.accepted_event = None
            self.active_adapter = adapter

    def end_wait(self) -> None:
        with self._lock:
            self.active_adapter = None

    def handle_event(self, event: WakeEvent):
        with self._lock:
            return self.bridge.handle_wake_event(event)

    def mark_command_started(self) -> None:
        with self._lock:
            self.bridge.mark_command_started()

    def mark_command_finished(self) -> None:
        with self._lock:
            self.bridge.mark_command_finished()

    def mark_tts_started(self) -> None:
        with self._lock:
            self.bridge.mark_tts_started()

    def mark_tts_finished(self) -> None:
        with self._lock:
            self.bridge.mark_tts_finished()

    def state(self):
        with self._lock:
            return self.bridge.state()

    def _accept_wake_event(self, event: WakeEvent) -> object:
        command_queue = None
        with self._lock:
            self.accepted_event = event
            self.bridge.mark_command_started()
            command_queue = self.command_queue
        if command_queue is not None:
            command_queue.put(event)
        return {"accepted": True}


# ---------------------------------------------------------------------------
# adapter factory
# ---------------------------------------------------------------------------

def create_openwakeword_adapter(runtime_config: WakeEngineRuntimeConfig) -> OpenWakeWordAdapter:
    return OpenWakeWordAdapter(
        wake_phrase=runtime_config.wake_phrase,
        model_path=runtime_config.model_path,
        model_name=runtime_config.model_name,
        device=runtime_config.device,
        sample_rate=runtime_config.sample_rate,
        sensitivity=runtime_config.sensitivity,
        cooldown_seconds=runtime_config.cooldown_seconds,
    )


# ---------------------------------------------------------------------------
# listener lifecycle
# ---------------------------------------------------------------------------

def start_openwakeword_listener(
    *,
    app,
    runtime_config: WakeEngineRuntimeConfig,
    bridge_runtime: OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
    stop_event: threading.Event,
    adapter_factory: Callable[[WakeEngineRuntimeConfig], object] | None = None,
) -> OpenWakeWordListenerHandle:
    event_queue: queue.Queue[WakeEvent] = queue.Queue()
    error_queue: queue.Queue[str] = queue.Queue()
    bridge_runtime.command_queue = event_queue
    try:
        adapter = (adapter_factory or create_openwakeword_adapter)(runtime_config)
    except Exception as exc:
        error = str(exc)
        _log_runtime_message(logger, "error", f"openwakeword_listener_error error={error}")
        raise WakeEngineRuntimeError(error) from exc

    handle = OpenWakeWordListenerHandle(
        thread=threading.Thread(
            target=run_openwakeword_listener,
            kwargs={
                "app": app,
                "runtime_config": runtime_config,
                "bridge_runtime": bridge_runtime,
                "logger": logger,
                "debug": debug,
                "stop_event": stop_event,
                "adapter": adapter,
                "error_queue": error_queue,
            },
            name="openwakeword-listener",
            daemon=True,
        ),
        adapter=adapter,
        event_queue=event_queue,
        error_queue=error_queue,
        bridge_runtime=bridge_runtime,
    )
    handle.thread.start()
    return handle


def run_openwakeword_listener(
    *,
    app,
    runtime_config: WakeEngineRuntimeConfig,
    bridge_runtime: OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
    stop_event: threading.Event,
    adapter,
    error_queue: queue.Queue[str],
) -> None:
    from xiaohuang.overlay_state_service import STATE_WAKE_CHECKING

    _log_runtime_message(logger, "info", "openwakeword_listener_starting")
    try:
        _log_runtime_message(logger, "info", "openwakeword_listener_running")
        app.thread_safe_set_state(STATE_WAKE_CHECKING, f"openWakeWord：{runtime_config.wake_phrase}")
        bridge_runtime.begin_wait(adapter)
        try:
            adapter.run_until_stopped(
                stop_event,
                on_event=lambda event: handle_openwakeword_event(event, bridge_runtime, logger, debug),
                debug=debug,
                on_status=lambda status: log_openwakeword_listener_status(logger, status),
                status_interval_seconds=OPENWAKEWORD_STATUS_INTERVAL_SECONDS,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            error = wake_engine_runtime_error(adapter, exc)
            _log_runtime_message(logger, "error", f"openwakeword_listener_error error={error}")
            error_queue.put(error)
            if runtime_config.fallback_enabled:
                _log_runtime_message(logger, "warning", f"fallback_to_stt_text reason={error}")
            else:
                stop_event.set()
            return
        finally:
            bridge_runtime.end_wait()
    finally:
        stop_adapter_safely(adapter)
        _log_runtime_message(logger, "info", "openwakeword_listener_stopped")


def stop_openwakeword_listener(listener: OpenWakeWordListenerHandle) -> None:
    stop_adapter_safely(listener.adapter)
    listener.thread.join(timeout=1.0)


def wait_for_openwakeword_event(
    listener: OpenWakeWordListenerHandle,
    stop_event: threading.Event,
) -> WakeEvent:
    while True:
        try:
            error = listener.error_queue.get_nowait()
        except queue.Empty:
            error = None
        if error is not None:
            raise WakeEngineRuntimeError(error)

        if stop_event.is_set():
            raise WakeEngineLoopStopped()

        try:
            return listener.event_queue.get(timeout=OPENWAKEWORD_QUEUE_POLL_SECONDS)
        except queue.Empty:
            pass

        if not listener.thread.is_alive():
            try:
                error = listener.error_queue.get_nowait()
            except queue.Empty:
                error = "openwakeword listener stopped unexpectedly"
            raise WakeEngineRuntimeError(error)


def handle_openwakeword_event(
    event: WakeEvent,
    bridge_runtime: OpenWakeWordBridgeRuntime,
    logger,
    debug: bool,
) -> None:
    _log_runtime_message(
        logger,
        "info",
        f"openwakeword_wake_event label={event.label} score={event.score}",
    )
    decision = bridge_runtime.handle_event(event)
    _log_runtime_message(
        logger,
        "info",
        "openwakeword_bridge_decision "
        f"accepted={_bool_text(decision.accepted)} reason={decision.reason}",
    )
    if debug:
        _safe_print(
            "openWakeWord event "
            f"label={event.label} score={event.score} "
            f"accepted={'true' if decision.accepted else 'false'} "
            f"reason={decision.reason}"
        )
    if not decision.accepted:
        logger.info("openWakeWord wake event suppressed: reason=%s label=%s", decision.reason, event.label)


def log_openwakeword_listener_status(logger, status: OpenWakeWordRuntimeStatus) -> None:
    labels = ",".join(status.model_labels) if status.model_labels else "-"
    max_label = status.max_label or "-"
    max_score = "-" if status.max_score is None else f"{status.max_score:.3f}"
    _log_runtime_message(
        logger,
        "info",
        "openwakeword_listener_status "
        f"device_index={status.device} sample_rate={status.sample_rate} "
        f"sensitivity={status.sensitivity} model_labels={labels} "
        f"frames={status.frames_read} max_label={max_label} max_score={max_score} "
        f"raw={status.raw_detections} coalesced={status.coalesced_events} "
        f"suppressed={status.suppressed_detections}",
    )


def stop_adapter_safely(adapter) -> None:
    if adapter is None:
        return
    try:
        adapter.stop()
    except Exception:
        pass


def wake_engine_runtime_error(adapter, exc: Exception) -> str:
    try:
        status = adapter.status()
    except Exception:
        status = None
    status_error = getattr(status, "error", None)
    return str(status_error or exc)
