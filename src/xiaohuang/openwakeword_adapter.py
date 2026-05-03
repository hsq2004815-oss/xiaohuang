from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from xiaohuang.wake_engine_service import (
    WakeEngineStatus,
    WakeEvent,
    WakeEventCoalescer,
    WakeEventStats,
)


DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_MS = 80
DEFAULT_SENSITIVITY = 0.5
DEFAULT_COOLDOWN_SECONDS = 2.5


@dataclass(frozen=True)
class OpenWakeWordDependencyStatus:
    openwakeword_installed: bool
    numpy_installed: bool
    sounddevice_installed: bool
    onnxruntime_available: bool | None
    ready_for_realtime_demo: bool
    errors: list[str]


@dataclass(frozen=True)
class PredictionScore:
    label: str
    score: float
    detected: bool


def check_openwakeword_dependencies(
    *,
    import_module: Callable[[str], Any] = importlib.import_module,
) -> OpenWakeWordDependencyStatus:
    errors: list[str] = []

    openwakeword_installed = _dependency_installed(
        "openwakeword",
        errors,
        import_module=import_module,
    )
    numpy_installed = _dependency_installed("numpy", errors, import_module=import_module)
    sounddevice_installed = _dependency_installed(
        "sounddevice",
        errors,
        import_module=import_module,
    )
    onnxruntime_available: bool | None
    try:
        import_module("onnxruntime")
    except Exception as exc:
        onnxruntime_available = False
        errors.append(f"Missing optional dependency: onnxruntime ({exc})")
    else:
        onnxruntime_available = True

    ready_for_realtime_demo = (
        openwakeword_installed
        and numpy_installed
        and sounddevice_installed
        and onnxruntime_available is not False
    )
    return OpenWakeWordDependencyStatus(
        openwakeword_installed=openwakeword_installed,
        numpy_installed=numpy_installed,
        sounddevice_installed=sounddevice_installed,
        onnxruntime_available=onnxruntime_available,
        ready_for_realtime_demo=ready_for_realtime_demo,
        errors=errors,
    )


class OpenWakeWordAdapter:
    def __init__(
        self,
        *,
        wake_phrase: str = "贾维斯",
        model_path: str | None = None,
        model_name: str | None = None,
        device: int | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_ms: int = DEFAULT_CHUNK_MS,
        sensitivity: float = DEFAULT_SENSITIVITY,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        coalesce: bool = True,
        time_fn: Callable[[], float] | None = None,
        import_module: Callable[[str], Any] = importlib.import_module,
        model_factory: Callable[["OpenWakeWordAdapter"], Any] | None = None,
        input_stream_factory: Callable[..., Any] | None = None,
        numpy_module: Any | None = None,
    ) -> None:
        self.engine_type = "openwakeword"
        self.wake_phrase = wake_phrase
        self.model_path = model_path
        self.model_name = model_name
        self.device = device
        self.sample_rate = int(sample_rate)
        self.chunk_ms = int(chunk_ms)
        self.chunk_samples = max(1, int(self.sample_rate * self.chunk_ms / 1000))
        self.sensitivity = float(sensitivity)
        self.coalesce = bool(coalesce)
        self.coalescer = WakeEventCoalescer(cooldown_seconds)
        self._time_fn = time_fn or time.monotonic
        self._import_module = import_module
        self._model_factory = model_factory
        self._input_stream_factory = input_stream_factory
        self._numpy_module = numpy_module
        self._model: Any | None = None
        self._running = False
        self._last_wake_time: float | None = None
        self._last_score: float | None = None
        self._error: str | None = None
        self._frames_read = 0

    @property
    def frames_read(self) -> int:
        return self._frames_read

    def start(self) -> None:
        if self._running:
            return
        self._error = None
        try:
            self._numpy_module = self._numpy_module or self._import_module("numpy")
            self._model = self._model or self._load_model()
            self._input_stream_factory = self._input_stream_factory or self._load_input_stream_factory()
        except Exception as exc:
            self._error = _summarize_exception(exc)
            self._running = False
            raise
        self._running = True

    def stop(self) -> None:
        self._running = False

    def status(self) -> WakeEngineStatus:
        model_loaded = self._model is not None and self._error is None
        ready = self._running and model_loaded
        return WakeEngineStatus(
            engine_type=self.engine_type,
            running=self._running,
            ready=ready,
            model_loaded=model_loaded,
            wake_phrase=self.wake_phrase,
            sensitivity=self.sensitivity,
            last_wake_time=self._last_wake_time,
            last_score=self._last_score,
            error=self._error,
        )

    def run_for_duration(
        self,
        duration_seconds: float,
        on_event: Callable[[WakeEvent], None] | None = None,
        debug: bool = False,
    ) -> WakeEventStats:
        self.start()
        self._frames_read = 0
        self.coalescer.reset()
        deadline = self._time_fn() + float(duration_seconds)
        try:
            with self._open_input_stream() as stream:
                while self._running and self._time_fn() < deadline:
                    data, overflowed = stream.read(self.chunk_samples)
                    frame = self._audio_frame_from_data(data)
                    prediction = self._model.predict(frame)
                    score = best_prediction_score(prediction, sensitivity=self.sensitivity)
                    if debug and score is not None:
                        print(
                            f"frame label={score.label} "
                            f"score={score.score:.3f} "
                            f"detected={_bool_text(score.detected)} "
                            f"threshold={self.sensitivity:.3f}"
                        )
                    if overflowed and debug:
                        print("audio_overflow=true")
                    self._handle_prediction_score(score, on_event=on_event, debug=debug)
                    self._frames_read += 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            self._error = _summarize_exception(exc)
            raise
        finally:
            self.stop()
        return self.coalescer.stats()

    def _load_model(self) -> Any:
        if self._model_factory is not None:
            return self._model_factory(self)

        if self.model_path and not Path(self.model_path).exists():
            raise RuntimeError(f"model_path_not_found path={self.model_path}")

        try:
            model_module = self._import_module("openwakeword.model")
        except Exception as exc:
            raise RuntimeError(
                "Missing optional dependency: openwakeword. Install in a test env with: pip install openwakeword"
            ) from exc

        wakeword_models: list[str] = []
        if self.model_path:
            wakeword_models.append(self.model_path)
        if self.model_name:
            wakeword_models.append(self.model_name)

        kwargs: dict[str, Any] = {"inference_framework": "onnx"}
        if wakeword_models:
            kwargs["wakeword_models"] = wakeword_models
        return model_module.Model(**kwargs)

    def _load_input_stream_factory(self) -> Callable[..., Any]:
        try:
            sounddevice = self._import_module("sounddevice")
        except Exception as exc:
            raise RuntimeError(
                "Missing optional dependency: sounddevice. Install in a test env with: pip install sounddevice"
            ) from exc
        return sounddevice.InputStream

    def _open_input_stream(self) -> Any:
        return self._input_stream_factory(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_samples,
            device=self.device,
        )

    def _audio_frame_from_data(self, data: Any) -> Any:
        np = self._numpy_module
        return np.asarray(data).reshape(-1).astype(np.int16)

    def _handle_prediction_score(
        self,
        score: PredictionScore | None,
        *,
        on_event: Callable[[WakeEvent], None] | None,
        debug: bool,
    ) -> None:
        if score is None:
            return
        self._last_score = score.score
        if not score.detected:
            return

        now = self._time_fn()
        accepted = self.coalescer.accept(
            score.label,
            now,
            score.score,
            coalesce=self.coalesce,
        )
        if not accepted:
            if debug:
                remaining = self.coalescer.remaining_seconds(score.label, now)
                print(
                    f"wake_suppressed label={score.label} "
                    f"score={score.score:.3f} "
                    f"reason=cooldown remaining={remaining:.3f}"
                )
            return

        raw_event_count, suppressed_event_count = self.coalescer.event_counts(score.label)
        self._last_wake_time = now
        event = WakeEvent(
            engine_type=self.engine_type,
            wake_phrase=self.wake_phrase,
            label=score.label,
            score=score.score,
            detected_at=now,
            raw_event_count=raw_event_count,
            suppressed_event_count=suppressed_event_count,
        )
        if on_event is not None:
            on_event(event)


def best_prediction_score(prediction: Any, *, sensitivity: float) -> PredictionScore | None:
    scores = _flatten_prediction(prediction)
    if not scores:
        return None
    label, score = max(scores.items(), key=lambda item: item[1])
    return PredictionScore(label=label, score=score, detected=score >= sensitivity)


def _dependency_installed(
    name: str,
    errors: list[str],
    *,
    import_module: Callable[[str], Any],
) -> bool:
    try:
        import_module(name)
    except Exception as exc:
        errors.append(f"Missing optional dependency: {name} ({exc})")
        return False
    return True


def _flatten_prediction(prediction: Any) -> dict[str, float]:
    if not isinstance(prediction, dict):
        return {}
    scores: dict[str, float] = {}
    for label, value in prediction.items():
        try:
            scores[str(label)] = float(value)
        except (TypeError, ValueError):
            continue
    return scores


def _summarize_exception(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
