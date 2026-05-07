"""wake_engine_demo_service.py — wake engine demo logic extracted from scripts.

Contains all dataclasses, formatting, runners, and helpers for the
openWakeWord demo harness. The script entrypoint only handles PATH setup.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import time
from typing import Any, Callable, Sequence

from xiaohuang.openwakeword_adapter import (
    OpenWakeWordAdapter,
    OpenWakeWordDependencyStatus,
    check_openwakeword_dependencies,
)
from xiaohuang.wake_engine_service import WakeEvent, WakeEventCoalescer, WakeEventStats


DEFAULT_ENGINE = "openwakeword"
DEFAULT_WAKE_PHRASE = "贾维斯"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_MS = 80
DEFAULT_SENSITIVITY = 0.5
DEFAULT_COOLDOWN_SECONDS = 2.5
OPENWAKEWORD_INSTALL_HINT = "pip install openwakeword"
AUDIO_INSTALL_HINT = "pip install sounddevice"


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    import_name: str
    installed: bool
    version: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class DemoConfig:
    engine: str
    model_path: str | None
    model_name: str | None
    wake_phrase: str
    device: int | None
    duration_seconds: float
    chunk_ms: int
    chunk_samples: int
    sensitivity: float
    cooldown_seconds: float
    coalesce_events: bool
    debug: bool


@dataclass
class DetectionStats:
    frames: int = 0
    raw_detections: int = 0
    coalesced_events: int = 0
    suppressed_detections: int = 0

    def update_from_wake_stats(self, wake_stats: WakeEventStats) -> None:
        self.raw_detections = wake_stats.raw_detections
        self.coalesced_events = wake_stats.coalesced_events
        self.suppressed_detections = wake_stats.suppressed_detections


@dataclass(frozen=True)
class SafetyCheckResult:
    rounds: int
    completed_rounds: int
    all_rounds_completed: bool
    microphone_released: bool | None
    errors: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an isolated V1.2B openWakeWord demo without touching XiaoHuang's main wake path.",
    )
    parser.add_argument("--engine", default=DEFAULT_ENGINE, choices=[DEFAULT_ENGINE], help="Wake engine to test.")
    parser.add_argument("--model-path", default=None, help="Path to an openWakeWord .onnx/.tflite model.")
    parser.add_argument("--model-name", default=None, help="openWakeWord built-in model name, for example 'hey jarvis'.")
    parser.add_argument("--wake-phrase", default=DEFAULT_WAKE_PHRASE, help="Display label for the target wake phrase.")
    parser.add_argument("--device", type=int, default=None, help="Input device index. Defaults to the audio backend default.")
    parser.add_argument("--list-devices", action="store_true", help="List microphone devices if an optional audio backend exists.")
    parser.add_argument("--duration-seconds", type=positive_float, default=10.0, help="Maximum demo duration. Defaults to 10.")
    parser.add_argument("--chunk-ms", type=positive_int, default=DEFAULT_CHUNK_MS, help="Audio chunk size in milliseconds. Defaults to 80.")
    parser.add_argument("--sensitivity", type=sensitivity_value, default=DEFAULT_SENSITIVITY, help="Display/demo detection threshold from 0.0 to 1.0.")
    parser.add_argument(
        "--cooldown-seconds",
        type=positive_float,
        default=DEFAULT_COOLDOWN_SECONDS,
        help="Seconds to coalesce repeated detections for the same label. Defaults to 2.5.",
    )
    parser.add_argument(
        "--no-coalesce",
        action="store_false",
        dest="coalesce_events",
        help="Disable wake_event coalescing and emit every raw detection.",
    )
    parser.add_argument("--debug", action="store_true", help="Print every frame score instead of periodic summaries.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved configuration only; do not load models or open the microphone.")
    parser.add_argument("--check-install", action="store_true", help="Check optional dependencies without opening the microphone.")
    parser.add_argument("--safety-check", action="store_true", help="Run repeated adapter start/stop rounds to validate microphone release.")
    parser.add_argument("--repeat", type=positive_int, default=2, help="Safety-check rounds. Defaults to 2.")
    parser.add_argument("--gap-seconds", type=nonnegative_float, default=1.0, help="Seconds to wait between safety-check rounds. Defaults to 1.0.")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed


def sensitivity_value(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise argparse.ArgumentTypeError("must be between 0.0 and 1.0")
    return parsed


def build_demo_config(args: argparse.Namespace) -> DemoConfig:
    chunk_samples = max(1, int(DEFAULT_SAMPLE_RATE * args.chunk_ms / 1000))
    return DemoConfig(
        engine=args.engine,
        model_path=args.model_path,
        model_name=args.model_name,
        wake_phrase=args.wake_phrase,
        device=args.device,
        duration_seconds=float(args.duration_seconds),
        chunk_ms=int(args.chunk_ms),
        chunk_samples=chunk_samples,
        sensitivity=float(args.sensitivity),
        cooldown_seconds=float(args.cooldown_seconds),
        coalesce_events=bool(args.coalesce_events),
        debug=bool(args.debug),
    )


def check_optional_dependency(
    name: str,
    *,
    import_name: str | None = None,
    import_module: Callable[[str], Any] = importlib.import_module,
) -> DependencyStatus:
    module_name = import_name or name
    try:
        module = import_module(module_name)
    except Exception as exc:
        return DependencyStatus(
            name=name,
            import_name=module_name,
            installed=False,
            error=f"Missing optional dependency: {name}. Install in a test env with: {install_hint_for(name)} ({exc})",
        )
    return DependencyStatus(
        name=name,
        import_name=module_name,
        installed=True,
        version=str(getattr(module, "__version__", "unknown")),
    )


def collect_install_statuses(
    *,
    import_module: Callable[[str], Any] = importlib.import_module,
) -> list[DependencyStatus]:
    return [
        check_optional_dependency("openwakeword", import_module=import_module),
        check_optional_dependency("numpy", import_module=import_module),
        check_optional_dependency("sounddevice", import_module=import_module),
        check_optional_dependency("pyaudio", import_module=import_module),
        check_optional_dependency("PyAudioWPatch", import_name="pyaudiowpatch", import_module=import_module),
    ]


def print_install_report(statuses: OpenWakeWordDependencyStatus | Sequence[DependencyStatus]) -> None:
    if isinstance(statuses, OpenWakeWordDependencyStatus):
        print("V1.2B openWakeWord demo install check")
        print("adapter_harness=true")
        print(f"openwakeword_installed={_bool_text(statuses.openwakeword_installed)}")
        print(f"numpy_installed={_bool_text(statuses.numpy_installed)}")
        print(f"sounddevice_installed={_bool_text(statuses.sounddevice_installed)}")
        onnxruntime_text = (
            "unknown"
            if statuses.onnxruntime_available is None
            else _bool_text(statuses.onnxruntime_available)
        )
        print(f"onnxruntime_available={onnxruntime_text}")
        print(f"audio_backend_available={_bool_text(statuses.sounddevice_installed)}")
        print(f"ready_for_realtime_demo={_bool_text(statuses.ready_for_realtime_demo)}")
        for error in statuses.errors:
            print(f"dependency_error message={error}")
        if not statuses.openwakeword_installed:
            print(f"install_hint_openwakeword={OPENWAKEWORD_INSTALL_HINT}")
        if not statuses.sounddevice_installed:
            print(f"install_hint_audio={AUDIO_INSTALL_HINT}")
        return

    print("V1.2B openWakeWord demo install check")
    for status in statuses:
        print(
            "dependency "
            f"name={status.name} "
            f"import={status.import_name} "
            f"installed={_bool_text(status.installed)} "
            f"version={status.version or '-'}"
        )
        if status.error:
            print(f"dependency_error name={status.name} message={status.error}")
    openwakeword_ready = _status_by_name(statuses, "openwakeword").installed
    audio_ready = any(_status_by_name(statuses, name).installed for name in ("sounddevice", "pyaudio", "PyAudioWPatch"))
    print(f"openwakeword_installed={_bool_text(openwakeword_ready)}")
    print(f"audio_backend_available={_bool_text(audio_ready)}")
    print(f"ready_for_realtime_demo={_bool_text(openwakeword_ready and audio_ready)}")
    if not openwakeword_ready:
        print(f"install_hint_openwakeword={OPENWAKEWORD_INSTALL_HINT}")
    if not audio_ready:
        print(f"install_hint_audio={AUDIO_INSTALL_HINT}")


def print_dry_run(config: DemoConfig) -> None:
    print("V1.2B wake engine demo dry run")
    print_config(config, dry_run=True)
    print("will_load_model=false")
    print("will_open_microphone=false")
    print("will_start_stt_server=false")
    print("will_start_voice_overlay=false")
    print("will_call_llm=false")
    print("will_call_tts=false")


def print_config(config: DemoConfig, *, dry_run: bool = False) -> None:
    print(f"dry_run={_bool_text(dry_run)}")
    print(f"engine={config.engine}")
    print(f"wake_phrase={config.wake_phrase}")
    print(f"model_path={config.model_path or '-'}")
    print(f"model_name={config.model_name or '-'}")
    print(f"device={config.device if config.device is not None else '-'}")
    print(f"duration_seconds={config.duration_seconds:g}")
    print(f"sample_rate={DEFAULT_SAMPLE_RATE}")
    print(f"chunk_ms={config.chunk_ms}")
    print(f"chunk_samples={config.chunk_samples}")
    print(f"sensitivity={config.sensitivity:g}")
    print(f"cooldown_seconds={config.cooldown_seconds:g}")
    print(f"coalesce_events={_bool_text(config.coalesce_events)}")
    print(f"debug={_bool_text(config.debug)}")


def list_devices() -> int:
    sounddevice_result = _list_sounddevice_devices()
    if sounddevice_result is not None:
        return 0
    pyaudio_result = _list_pyaudio_devices()
    if pyaudio_result is not None:
        return 0
    print("No optional audio backend is available.")
    print(f"Missing optional dependency: sounddevice. Install in a test env with: {AUDIO_INSTALL_HINT}")
    return 0


def run_realtime_demo(config: DemoConfig) -> int:
    print("V1.2B openWakeWord realtime demo")
    print_config(config, dry_run=False)

    if config.model_path and not Path(config.model_path).exists():
        print(f"error=model_path_not_found path={config.model_path}")
        return 2

    adapter = OpenWakeWordAdapter(
        wake_phrase=config.wake_phrase,
        model_path=config.model_path,
        model_name=config.model_name,
        device=config.device,
        sample_rate=DEFAULT_SAMPLE_RATE,
        chunk_ms=config.chunk_ms,
        sensitivity=config.sensitivity,
        cooldown_seconds=config.cooldown_seconds,
        coalesce=config.coalesce_events,
    )
    listening_started = False
    try:
        adapter.start()
        print("audio_backend=sounddevice")
        print("listening=true")
        listening_started = True
        wake_stats = adapter.run_for_duration(
            config.duration_seconds,
            on_event=lambda event: _print_wake_event(event, coalesced=config.coalesce_events),
            debug=config.debug,
        )
    except KeyboardInterrupt:
        print("interrupted=true")
        return 130
    except Exception as exc:
        status = adapter.status()
        print(f"openwakeword_runtime_error={status.error or exc}")
        print(f"install_hint_openwakeword={OPENWAKEWORD_INSTALL_HINT}")
        return 2
    finally:
        if listening_started:
            print("listening=false")

    stats = DetectionStats(frames=adapter.frames_read)
    stats.update_from_wake_stats(wake_stats)
    print_detection_summary(stats, config)
    return 0


def run_safety_check(
    config: DemoConfig,
    *,
    repeat: int = 2,
    gap_seconds: float = 1.0,
    adapter_factory: Callable[[DemoConfig], Any] | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
    print_func: Callable[[str], None] = print,
) -> int:
    result = collect_safety_check_result(
        config,
        repeat=repeat,
        gap_seconds=gap_seconds,
        adapter_factory=adapter_factory,
        sleep_func=sleep_func,
        print_func=print_func,
    )
    return 0 if result.all_rounds_completed else 2


def collect_safety_check_result(
    config: DemoConfig,
    *,
    repeat: int = 2,
    gap_seconds: float = 1.0,
    adapter_factory: Callable[[DemoConfig], Any] | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
    print_func: Callable[[str], None] = print,
) -> SafetyCheckResult:
    factory = adapter_factory or create_openwakeword_adapter
    completed_rounds = 0
    errors = 0
    release_checks: list[bool] = []

    print_func("V1.2D-B openWakeWord adapter safety check")
    print_config(config, dry_run=False)
    print_func("safety_check=true")
    print_func(f"rounds={repeat}")
    print_func(f"gap_seconds={gap_seconds:g}")

    for round_index in range(1, repeat + 1):
        adapter = factory(config)
        stats = WakeEventStats(
            raw_detections=0,
            coalesced_events=0,
            suppressed_detections=0,
            cooldown_seconds=config.cooldown_seconds,
        )
        round_error: str | None = None
        started = False
        stopped = False
        status_after_stop = None
        try:
            adapter.start()
            started = bool(adapter.status().running)
            print_func(f"round={round_index} started={_bool_text(started)}")
            stats = adapter.run_for_duration(
                config.duration_seconds,
                on_event=lambda event: _print_wake_event(event, coalesced=config.coalesce_events),
                debug=config.debug,
            )
            completed_rounds += 1
        except KeyboardInterrupt:
            errors += 1
            round_error = "KeyboardInterrupt"
            print_func(f"round={round_index} interrupted=true")
        except Exception as exc:
            errors += 1
            status = adapter.status()
            round_error = str(status.error or exc)
            print_func(f"round={round_index} error={round_error}")
        finally:
            try:
                adapter.stop()
                stopped = True
            except Exception as exc:
                errors += 1
                stopped = False
                round_error = str(exc)
                print_func(f"round={round_index} stop_error={round_error}")
            status_after_stop = adapter.status()
            release_checks.append(not bool(status_after_stop.running))
            _print_safety_round_summary(
                round_index,
                adapter=adapter,
                stats=stats,
                stopped=stopped,
                status=status_after_stop,
                error=round_error,
                print_func=print_func,
            )

        if round_error is not None:
            break
        if round_index < repeat and gap_seconds > 0:
            sleep_func(gap_seconds)

    all_rounds_completed = completed_rounds == repeat and errors == 0
    microphone_released = all(release_checks) if release_checks else None
    print_func(f"all_rounds_completed={_bool_text(all_rounds_completed)}")
    print_func(f"microphone_released={_bool_or_unknown(microphone_released)}")
    print_func(f"errors={errors}")
    return SafetyCheckResult(
        rounds=repeat,
        completed_rounds=completed_rounds,
        all_rounds_completed=all_rounds_completed,
        microphone_released=microphone_released,
        errors=errors,
    )


def create_openwakeword_adapter(config: DemoConfig) -> OpenWakeWordAdapter:
    return OpenWakeWordAdapter(
        wake_phrase=config.wake_phrase,
        model_path=config.model_path,
        model_name=config.model_name,
        device=config.device,
        sample_rate=DEFAULT_SAMPLE_RATE,
        chunk_ms=config.chunk_ms,
        sensitivity=config.sensitivity,
        cooldown_seconds=config.cooldown_seconds,
        coalesce=config.coalesce_events,
    )


def _print_safety_round_summary(
    round_index: int,
    *,
    adapter: Any,
    stats: WakeEventStats,
    stopped: bool,
    status: Any,
    error: str | None,
    print_func: Callable[[str], None],
) -> None:
    print_func(f"round={round_index} stopped={_bool_text(stopped)}")
    print_func(f"round={round_index} frames={getattr(adapter, 'frames_read', 0)}")
    print_func(f"round={round_index} raw_detections={stats.raw_detections}")
    print_func(f"round={round_index} coalesced_events={stats.coalesced_events}")
    print_func(f"round={round_index} suppressed_detections={stats.suppressed_detections}")
    print_func(
        f"round={round_index} status_after_stop "
        f"running={_bool_text(bool(status.running))} "
        f"ready={_bool_text(bool(status.ready))} "
        f"model_loaded={_bool_text(bool(status.model_loaded))} "
        f"error={status.error or error or '-'}"
    )


def print_detection_summary(stats: DetectionStats, config: DemoConfig) -> None:
    print(f"frames={stats.frames}")
    print(f"raw_detections={stats.raw_detections}")
    print(f"coalesced_events={stats.coalesced_events}")
    print(f"suppressed_detections={stats.suppressed_detections}")
    print(f"cooldown_seconds={config.cooldown_seconds:g}")


def _print_wake_event(event: WakeEvent, *, coalesced: bool) -> None:
    print(
        f"wake_event engine={event.engine_type} "
        f"wake_phrase={event.wake_phrase} "
        f"label={event.label} "
        f"score={event.score:.3f} "
        "raw_event=true "
        f"coalesced={_bool_text(coalesced)}"
    )


def install_hint_for(name: str) -> str:
    if name == "openwakeword":
        return OPENWAKEWORD_INSTALL_HINT
    if name == "sounddevice":
        return AUDIO_INSTALL_HINT
    if name in {"pyaudio", "PyAudioWPatch"}:
        return "pip install PyAudioWPatch"
    return f"pip install {name}"


def _list_sounddevice_devices() -> bool | None:
    try:
        sd = importlib.import_module("sounddevice")
    except Exception:
        return None
    print("audio_backend=sounddevice")
    try:
        devices = sd.query_devices()
    except Exception as exc:
        print(f"list_devices_error={exc}")
        return True
    count = 0
    for index, device in enumerate(devices):
        max_inputs = _device_value(device, "max_input_channels", 0)
        if int(max_inputs or 0) <= 0:
            continue
        name = _device_value(device, "name", "unknown")
        samplerate = _device_value(device, "default_samplerate", "-")
        print(f"device index={index} name={name!r} max_input_channels={max_inputs} default_samplerate={samplerate}")
        count += 1
    print(f"input_device_count={count}")
    return True


def _list_pyaudio_devices() -> bool | None:
    pyaudio_module = None
    for module_name in ("pyaudiowpatch", "pyaudio"):
        try:
            pyaudio_module = importlib.import_module(module_name)
            break
        except Exception:
            continue
    if pyaudio_module is None:
        return None
    print(f"audio_backend={pyaudio_module.__name__}")
    audio = pyaudio_module.PyAudio()
    try:
        count = 0
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            max_inputs = int(info.get("maxInputChannels", 0))
            if max_inputs <= 0:
                continue
            print(
                "device "
                f"index={index} "
                f"name={info.get('name', 'unknown')!r} "
                f"max_input_channels={max_inputs} "
                f"default_samplerate={info.get('defaultSampleRate', '-')}"
            )
            count += 1
        print(f"input_device_count={count}")
        return True
    finally:
        audio.terminate()


def _device_value(device: Any, key: str, default: Any) -> Any:
    if isinstance(device, dict):
        return device.get(key, default)
    try:
        return device[key]
    except Exception:
        return getattr(device, key, default)


def _status_by_name(statuses: Sequence[DependencyStatus], name: str) -> DependencyStatus:
    for status in statuses:
        if status.name == name:
            return status
    return DependencyStatus(name, name, False, error="status not collected")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _bool_or_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return _bool_text(value)


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
