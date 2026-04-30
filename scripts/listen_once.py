from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.audio_capture_service import AudioDependencyError, AudioLevels, analyze_wav, build_recording_path, record_wav
from xiaohuang.config_service import load_config
from xiaohuang.listen_once_service import (
    TimingStats,
    build_audio_summary,
    build_timing_summary,
    resolve_listen_once_options,
    should_allow_local_fallback,
)
from xiaohuang.logging_service import configure_logging
from xiaohuang.stt_client_service import SttServerError, SttServerUnavailable, request_transcription
from xiaohuang.stt_service import MissingDependencyError, ModelInitializationError, SenseVoiceTranscriber, TranscriptionError
from xiaohuang.vad_recording_service import record_until_silence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record once, transcribe once, and print timing diagnostics.")
    parser.add_argument("--device", type=int, default=None, help="Input device ID. Defaults to config audio.device_id.")
    parser.add_argument("--seconds", type=int, default=None, help="Recording duration. Defaults to config value.")
    parser.add_argument("--countdown", type=int, default=None, help="Countdown seconds before recording. Defaults to 3.")
    parser.add_argument("--channels", type=int, default=None, help="Audio channel count. Defaults to 1.")
    parser.add_argument("--samplerate", type=int, default=None, help="Audio sample rate. Defaults to 16000.")
    parser.add_argument("--use-server", action="store_true", help="Use the local STT server after recording.")
    parser.add_argument("--server-url", default="http://127.0.0.1:8766", help="Local STT server URL.")
    parser.add_argument("--allow-local-fallback", action="store_true", help="Allow direct local STT fallback if the server is unavailable.")
    parser.add_argument("--vad", action="store_true", help="Use energy-threshold VAD to stop after speech and silence.")
    parser.add_argument("--max-seconds", type=float, default=10.0, help="Maximum VAD recording duration. Defaults to 10.")
    parser.add_argument("--silence-seconds", type=float, default=0.8, help="Silence duration after speech before VAD stops. Defaults to 0.8.")
    parser.add_argument("--energy-threshold", type=float, default=None, help="RMS energy threshold for VAD speech detection.")
    parser.add_argument("--calibrate-noise", action="store_true", help="Estimate VAD threshold from 0.5 seconds of ambient noise.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    options = resolve_listen_once_options(args, config)
    logger = configure_logging(
        PROJECT_ROOT / config["logging"]["directory"],
        "listen_once",
        config["logging"]["level"],
    )

    output_dir = PROJECT_ROOT / config["recording"]["output_dir"]
    output_path = build_recording_path(output_dir)

    total_start = time.perf_counter()
    if options.countdown > 0:
        print(f"Recording starts in {options.countdown} second(s).")
        for remaining in range(options.countdown, 0, -1):
            print(f"{remaining}...")
            time.sleep(1)

    record_start = time.perf_counter()
    try:
        if args.vad:
            print(
                f"Recording with VAD max_seconds={args.max_seconds:g} silence_seconds={args.silence_seconds:g} "
                f"device={options.device_id} channels={options.channels} samplerate={options.samplerate}..."
            )
            if args.calibrate_noise:
                print("Calibrating ambient noise for 0.5 second(s). Keep quiet...")
            vad_result = record_until_silence(
                output_path,
                device_id=options.device_id,
                sample_rate=options.samplerate,
                channels=options.channels,
                max_seconds=args.max_seconds,
                silence_seconds=args.silence_seconds,
                energy_threshold=args.energy_threshold,
                calibrate_noise=args.calibrate_noise,
            )
            saved_path = vad_result.path
            levels = AudioLevels(
                peak_amplitude=vad_result.peak_amplitude,
                rms_amplitude=vad_result.rms_amplitude,
                is_too_quiet=not vad_result.speech_detected or vad_result.rms_amplitude < 300,
                is_clipping=vad_result.peak_amplitude >= 32000,
            )
            print(f"actual_recording_seconds={vad_result.duration_seconds:.2f}")
            print(f"stop_reason={vad_result.stop_reason}")
            print(f"speech_detected={str(vad_result.speech_detected).lower()}")
            print(f"energy_threshold={vad_result.energy_threshold:.2f}")
        else:
            print(
                f"Recording {options.seconds} second(s) "
                f"device={options.device_id} channels={options.channels} samplerate={options.samplerate}..."
            )
            saved_path = record_wav(
                output_path,
                duration_seconds=options.seconds,
                sample_rate=options.samplerate,
                channels=options.channels,
                device_id=options.device_id,
            )
            levels = analyze_wav(saved_path)
    except AudioDependencyError as exc:
        logger.error(str(exc))
        print(str(exc))
        return 2
    except Exception as exc:
        logger.exception("Recording failed.")
        print(f"Recording failed: {exc}")
        return 1
    record_seconds = time.perf_counter() - record_start

    audio_summary = build_audio_summary(saved_path, levels)
    print(audio_summary)
    logger.info("\n%s", audio_summary)

    if args.use_server:
        try:
            response = request_transcription(saved_path, args.server_url)
            text = response["text"]
            model_init_seconds = None
            server_model_init_seconds = float(response["server_model_init_seconds"])
            transcribe_seconds = float(response["transcribe_seconds"])
            total_seconds = time.perf_counter() - total_start
            print(f"Used STT server: {args.server_url}")
        except (SttServerUnavailable, SttServerError) as exc:
            if not should_allow_local_fallback(args):
                logger.error(str(exc))
                print(f"{exc}\nSTT server is required in --use-server mode. Add --allow-local-fallback to use direct local STT.")
                return 6
            message = f"{exc}\nFalling back to direct local STT because --allow-local-fallback was specified."
            logger.warning(message)
            print(message)
            text, model_init_seconds, transcribe_seconds = _direct_transcribe(saved_path, config, logger)
            server_model_init_seconds = None
            total_seconds = time.perf_counter() - total_start
    else:
        text, model_init_seconds, transcribe_seconds = _direct_transcribe(saved_path, config, logger)
        server_model_init_seconds = None
        total_seconds = time.perf_counter() - total_start

    print("Transcription:")
    print(text)
    stats = TimingStats(
        record_seconds=record_seconds,
        model_init_seconds=model_init_seconds,
        transcribe_seconds=transcribe_seconds,
        total_seconds=total_seconds,
        server_model_init_seconds=server_model_init_seconds,
    )
    timing_summary = build_timing_summary(stats)
    print(timing_summary)
    logger.info("Transcription: %s\n%s", text, timing_summary)
    return 0


def _direct_transcribe(saved_path: Path, config: dict, logger) -> tuple[str, float, float]:
    transcriber = SenseVoiceTranscriber(
        model_name=config["stt"]["model_name"],
        language="auto",
        use_itn=True,
    )
    try:
        model_init_seconds = transcriber.ensure_model_loaded()
    except MissingDependencyError as exc:
        logger.error(str(exc))
        print(str(exc))
        raise SystemExit(3) from exc
    except ModelInitializationError as exc:
        logger.error(str(exc))
        print(str(exc))
        raise SystemExit(4) from exc

    transcribe_start = time.perf_counter()
    try:
        text = transcriber.transcribe(saved_path)
    except (MissingDependencyError, ModelInitializationError, TranscriptionError, FileNotFoundError) as exc:
        logger.error(str(exc))
        print(str(exc))
        raise SystemExit(5) from exc
    except Exception as exc:
        logger.exception("Unexpected listen_once transcription failure.")
        print(f"Unexpected listen_once transcription failure: {exc}")
        raise SystemExit(1) from exc
    transcribe_seconds = time.perf_counter() - transcribe_start
    return text, model_init_seconds, transcribe_seconds


if __name__ == "__main__":
    raise SystemExit(main())
