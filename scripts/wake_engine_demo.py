from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import time
from typing import Any, Callable, Sequence


DEFAULT_ENGINE = "openwakeword"
DEFAULT_WAKE_PHRASE = "贾维斯"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_MS = 80
DEFAULT_SENSITIVITY = 0.5
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
    debug: bool


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
    parser.add_argument("--debug", action="store_true", help="Print every frame score instead of periodic summaries.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved configuration only; do not load models or open the microphone.")
    parser.add_argument("--check-install", action="store_true", help="Check optional dependencies without opening the microphone.")
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


def print_install_report(statuses: Sequence[DependencyStatus]) -> None:
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

    try:
        np = importlib.import_module("numpy")
    except Exception as exc:
        print(f"Missing optional dependency: numpy. Install in a test env with: pip install numpy ({exc})")
        return 2

    try:
        model = load_openwakeword_model(config)
    except Exception as exc:
        print(f"openwakeword_load_error={exc}")
        print(f"install_hint_openwakeword={OPENWAKEWORD_INSTALL_HINT}")
        return 2

    try:
        return _run_with_sounddevice(config, model, np)
    except MissingAudioBackend:
        pass
    except KeyboardInterrupt:
        print("interrupted=true")
        return 130
    except Exception as exc:
        print(f"sounddevice_runtime_error={exc}")
        return 2

    try:
        return _run_with_pyaudio(config, model, np)
    except MissingAudioBackend:
        print("No optional audio backend is available.")
        print(f"Missing optional dependency: sounddevice. Install in a test env with: {AUDIO_INSTALL_HINT}")
        return 2
    except KeyboardInterrupt:
        print("interrupted=true")
        return 130
    except Exception as exc:
        print(f"pyaudio_runtime_error={exc}")
        return 2


def load_openwakeword_model(config: DemoConfig) -> Any:
    try:
        model_module = importlib.import_module("openwakeword.model")
    except Exception as exc:
        raise RuntimeError(
            f"Missing optional dependency: openwakeword. Install in a test env with: {OPENWAKEWORD_INSTALL_HINT} ({exc})"
        ) from exc

    wakeword_models: list[str] = []
    if config.model_path:
        wakeword_models.append(config.model_path)
    if config.model_name:
        wakeword_models.append(config.model_name)

    kwargs: dict[str, Any] = {"inference_framework": "onnx"}
    if wakeword_models:
        kwargs["wakeword_models"] = wakeword_models
    return model_module.Model(**kwargs)


def _run_with_sounddevice(config: DemoConfig, model: Any, np: Any) -> int:
    try:
        sd = importlib.import_module("sounddevice")
    except Exception as exc:
        raise MissingAudioBackend(str(exc)) from exc

    print("audio_backend=sounddevice")
    print("listening=true")
    deadline = time.monotonic() + config.duration_seconds
    frames = 0
    detections = 0
    last_summary = 0.0
    with sd.InputStream(
        samplerate=DEFAULT_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=config.chunk_samples,
        device=config.device,
    ) as stream:
        while time.monotonic() < deadline:
            data, overflowed = stream.read(config.chunk_samples)
            frame = np.asarray(data).reshape(-1).astype(np.int16)
            prediction = model.predict(frame)
            detected = print_prediction(prediction, config, force=config.debug or overflowed)
            detections += int(detected)
            frames += 1
            now = time.monotonic()
            if not config.debug and now - last_summary >= 1.0:
                print_prediction(prediction, config, force=True, prefix="score")
                last_summary = now
    print("listening=false")
    print(f"frames={frames}")
    print(f"detections={detections}")
    return 0


def _run_with_pyaudio(config: DemoConfig, model: Any, np: Any) -> int:
    pyaudio_module = None
    for module_name in ("pyaudiowpatch", "pyaudio"):
        try:
            pyaudio_module = importlib.import_module(module_name)
            break
        except Exception:
            continue
    if pyaudio_module is None:
        raise MissingAudioBackend("pyaudio is not installed")

    print(f"audio_backend={pyaudio_module.__name__}")
    audio = pyaudio_module.PyAudio()
    stream = None
    try:
        stream = audio.open(
            format=pyaudio_module.paInt16,
            channels=1,
            rate=DEFAULT_SAMPLE_RATE,
            input=True,
            input_device_index=config.device,
            frames_per_buffer=config.chunk_samples,
        )
        print("listening=true")
        deadline = time.monotonic() + config.duration_seconds
        frames = 0
        detections = 0
        last_summary = 0.0
        while time.monotonic() < deadline:
            data = stream.read(config.chunk_samples, exception_on_overflow=False)
            frame = np.frombuffer(data, dtype=np.int16)
            prediction = model.predict(frame)
            detected = print_prediction(prediction, config, force=config.debug)
            detections += int(detected)
            frames += 1
            now = time.monotonic()
            if not config.debug and now - last_summary >= 1.0:
                print_prediction(prediction, config, force=True, prefix="score")
                last_summary = now
        print("listening=false")
        print(f"frames={frames}")
        print(f"detections={detections}")
        return 0
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()


def print_prediction(prediction: Any, config: DemoConfig, *, force: bool, prefix: str = "frame") -> bool:
    scores = _flatten_prediction(prediction)
    if not scores:
        if force:
            print(f"{prefix} score_unavailable=true raw={prediction!r}")
        return False
    label, score = max(scores.items(), key=lambda item: item[1])
    detected = score >= config.sensitivity
    if force or detected:
        print(f"{prefix} label={label} score={score:.3f} detected={_bool_text(detected)} threshold={config.sensitivity:.3f}")
    if detected:
        print(f"wake_event engine={config.engine} wake_phrase={config.wake_phrase} label={label} score={score:.3f}")
    return detected


def install_hint_for(name: str) -> str:
    if name == "openwakeword":
        return OPENWAKEWORD_INSTALL_HINT
    if name == "sounddevice":
        return AUDIO_INSTALL_HINT
    if name in {"pyaudio", "PyAudioWPatch"}:
        return "pip install PyAudioWPatch"
    return f"pip install {name}"


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


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


class MissingAudioBackend(RuntimeError):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    configure_output_encoding()
    args = parse_args(argv)
    config = build_demo_config(args)
    if args.check_install:
        print_install_report(collect_install_statuses())
        return 0
    if args.list_devices:
        return list_devices()
    if args.dry_run:
        print_dry_run(config)
        return 0
    return run_realtime_demo(config)


if __name__ == "__main__":
    raise SystemExit(main())
