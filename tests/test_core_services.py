import tempfile
import unittest
import math
from types import SimpleNamespace
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaohuang.audio_capture_service import (
    classify_input_device,
    compute_audio_levels,
    build_recording_path,
)
from xiaohuang.config_service import load_config
from xiaohuang.listen_once_service import (
    TimingStats,
    build_timing_summary,
    build_audio_summary,
    resolve_listen_once_options,
    should_allow_local_fallback,
)
from xiaohuang.stt_client_service import build_health_url, build_transcribe_payload
from xiaohuang.stt_server_service import build_success_response
from xiaohuang.stt_service import MissingDependencyError, SenseVoiceTranscriber, clean_command_text
from xiaohuang.vad_service import FixedDurationVad
from xiaohuang.vad_recording_service import (
    STOP_MAX_SECONDS_REACHED,
    STOP_NO_SPEECH_DETECTED,
    STOP_SILENCE_AFTER_SPEECH,
    VadState,
    block_peak_rms,
    calculate_noise_threshold,
    is_speech_block,
    update_vad_state,
)
from xiaohuang.wake_word_service import is_wake_phrase_detected, normalize_wake_text, parse_wake_phrases


class ConfigServiceTests(unittest.TestCase):
    def test_load_config_reads_nested_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "xiaohuang.yaml"
            config_path.write_text(
                "audio:\n  sample_rate: 16000\n  channels: 1\nrecording:\n  duration_seconds: 5\n",
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config["audio"]["sample_rate"], 16000)
            self.assertEqual(config["audio"]["channels"], 1)
            self.assertEqual(config["recording"]["duration_seconds"], 5)


class AudioCaptureServiceTests(unittest.TestCase):
    def test_build_recording_path_uses_timestamp_and_wav_suffix(self):
        output_dir = Path("data") / "recordings"

        path = build_recording_path(output_dir, timestamp="20260430_120000")

        self.assertEqual(path, output_dir / "test_20260430_120000.wav")

    def test_compute_audio_levels_flags_quiet_audio(self):
        levels = compute_audio_levels([0, 1, -1, 2, -2])

        self.assertEqual(levels.peak_amplitude, 2)
        self.assertTrue(levels.is_too_quiet)
        self.assertFalse(levels.is_clipping)

    def test_compute_audio_levels_flags_clipping_audio(self):
        levels = compute_audio_levels([0, 32767, -32768])

        self.assertEqual(levels.peak_amplitude, 32768)
        self.assertTrue(levels.is_clipping)
        self.assertFalse(levels.is_too_quiet)

    def test_classify_input_device_marks_microphone_as_recommended(self):
        device = classify_input_device("USB Microphone")

        self.assertEqual(device, "recommended")

    def test_classify_input_device_marks_output_loopback_as_not_recommended(self):
        for name in ("Speaker Output", "立体声混音"):
            with self.subTest(name=name):
                self.assertEqual(classify_input_device(name), "not recommended")


class VadServiceTests(unittest.TestCase):
    def test_fixed_duration_vad_reports_configured_seconds(self):
        vad = FixedDurationVad(duration_seconds=5)

        self.assertEqual(vad.get_recording_duration_seconds(), 5)


class VadRecordingServiceTests(unittest.TestCase):
    def test_block_peak_rms_calculates_audio_levels(self):
        peak, rms = block_peak_rms([0, 300, -400])

        self.assertEqual(peak, 400)
        self.assertAlmostEqual(rms, math.sqrt((300 * 300 + 400 * 400) / 3), places=6)

    def test_is_speech_block_uses_energy_threshold(self):
        self.assertFalse(is_speech_block([0, 50, -50], energy_threshold=300))
        self.assertTrue(is_speech_block([0, 600, -600], energy_threshold=300))

    def test_update_vad_state_waits_for_minimum_speech_before_start(self):
        state = VadState()
        state = update_vad_state(
            state,
            speech_detected_in_block=True,
            block_seconds=0.1,
            min_speech_seconds=0.3,
            silence_seconds=0.8,
            max_seconds=10,
        )

        self.assertFalse(state.speech_started)
        self.assertIsNone(state.stop_reason)

        for _index in range(2):
            state = update_vad_state(
                state,
                speech_detected_in_block=True,
                block_seconds=0.1,
                min_speech_seconds=0.3,
                silence_seconds=0.8,
                max_seconds=10,
            )

        self.assertTrue(state.speech_started)

    def test_update_vad_state_stops_after_continuous_silence(self):
        state = VadState(speech_started=True, speech_seconds=0.5)

        for _index in range(4):
            state = update_vad_state(
                state,
                speech_detected_in_block=False,
                block_seconds=0.2,
                min_speech_seconds=0.3,
                silence_seconds=0.8,
                max_seconds=10,
            )

        self.assertEqual(state.stop_reason, STOP_SILENCE_AFTER_SPEECH)

    def test_update_vad_state_reports_no_speech_when_timeout_before_speech(self):
        state = update_vad_state(
            VadState(elapsed_seconds=0.9),
            speech_detected_in_block=False,
            block_seconds=0.1,
            min_speech_seconds=0.3,
            silence_seconds=0.8,
            max_seconds=1.0,
        )

        self.assertEqual(state.stop_reason, STOP_NO_SPEECH_DETECTED)

    def test_update_vad_state_reports_max_seconds_after_speech(self):
        state = update_vad_state(
            VadState(elapsed_seconds=0.9, speech_seconds=0.5, speech_started=True),
            speech_detected_in_block=True,
            block_seconds=0.1,
            min_speech_seconds=0.3,
            silence_seconds=0.8,
            max_seconds=1.0,
        )

        self.assertEqual(state.stop_reason, STOP_MAX_SECONDS_REACHED)

    def test_calculate_noise_threshold_uses_noise_floor_and_default_floor(self):
        self.assertEqual(calculate_noise_threshold([]), 600.0)
        self.assertEqual(calculate_noise_threshold([50.0, 100.0]), 600.0)
        self.assertEqual(calculate_noise_threshold([400.0, 500.0]), 1350.0)


class SttServiceTests(unittest.TestCase):
    def test_sensevoice_transcriber_reports_missing_funasr_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "sample.wav"
            wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            transcriber = SenseVoiceTranscriber(model_name="iic/SenseVoiceSmall", funasr_module=None)

            with self.assertRaises(MissingDependencyError) as context:
                transcriber.transcribe(wav_path)

            self.assertIn("FunASR", str(context.exception))

    def test_sensevoice_transcriber_uses_recommended_model_init_args(self):
        class FakeFunASR:
            captured_kwargs = None

            class AutoModel:
                def __init__(self, **kwargs):
                    FakeFunASR.captured_kwargs = kwargs

        transcriber = SenseVoiceTranscriber(funasr_module=FakeFunASR)

        transcriber._get_model()

        self.assertEqual(FakeFunASR.captured_kwargs["model"], "iic/SenseVoiceSmall")
        self.assertTrue(FakeFunASR.captured_kwargs["trust_remote_code"])
        self.assertEqual(FakeFunASR.captured_kwargs["remote_code"], "./model.py")
        self.assertEqual(FakeFunASR.captured_kwargs["vad_model"], "fsmn-vad")
        self.assertEqual(FakeFunASR.captured_kwargs["vad_kwargs"], {"max_single_segment_time": 30000})
        self.assertEqual(FakeFunASR.captured_kwargs["device"], "cpu")
        self.assertTrue(FakeFunASR.captured_kwargs["disable_update"])

    def test_sensevoice_transcriber_uses_recommended_generate_args_and_postprocess(self):
        class FakeModel:
            captured_kwargs = None

            def generate(self, **kwargs):
                FakeModel.captured_kwargs = kwargs
                return [{"text": "<|zh|><|NEUTRAL|><|Speech|>你好，小黄"}]

        class FakeFunASR:
            class AutoModel:
                def __new__(cls, **kwargs):
                    return FakeModel()

        def postprocess(text):
            return text.replace("<|zh|><|NEUTRAL|><|Speech|>", "").strip()

        with tempfile.TemporaryDirectory() as temp_dir:
            wav_path = Path(temp_dir) / "sample.wav"
            wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            transcriber = SenseVoiceTranscriber(funasr_module=FakeFunASR, postprocess_func=postprocess)

            text = transcriber.transcribe(wav_path)

        self.assertEqual(FakeModel.captured_kwargs["input"], str(wav_path))
        self.assertEqual(FakeModel.captured_kwargs["language"], "auto")
        self.assertTrue(FakeModel.captured_kwargs["use_itn"])
        self.assertEqual(FakeModel.captured_kwargs["batch_size_s"], 60)
        self.assertTrue(FakeModel.captured_kwargs["merge_vad"])
        self.assertEqual(FakeModel.captured_kwargs["merge_length_s"], 15)
        self.assertEqual(text, "你好，小黄")

    def test_clean_command_text_removes_emoji_space_and_extra_punctuation(self):
        text = clean_command_text("  ✅ 小黄，帮我测试一下！！！  ")

        self.assertEqual(text, "小黄，帮我测试一下")


class ListenOnceServiceTests(unittest.TestCase):
    def test_resolve_listen_once_options_prefers_args_then_config_then_defaults(self):
        args = SimpleNamespace(device=None, seconds=None, countdown=None, channels=None, samplerate=None)
        config = {
            "audio": {"device_id": 0, "channels": 2, "sample_rate": 44100},
            "recording": {"duration_seconds": 7},
        }

        options = resolve_listen_once_options(args, config)

        self.assertEqual(options.device_id, 0)
        self.assertEqual(options.seconds, 7)
        self.assertEqual(options.countdown, 3)
        self.assertEqual(options.channels, 2)
        self.assertEqual(options.samplerate, 44100)

    def test_resolve_listen_once_options_cli_values_win(self):
        args = SimpleNamespace(device=3, seconds=4, countdown=1, channels=1, samplerate=16000)
        config = {
            "audio": {"device_id": 0, "channels": 2, "sample_rate": 44100},
            "recording": {"duration_seconds": 7},
        }

        options = resolve_listen_once_options(args, config)

        self.assertEqual(options.device_id, 3)
        self.assertEqual(options.seconds, 4)
        self.assertEqual(options.countdown, 1)
        self.assertEqual(options.channels, 1)
        self.assertEqual(options.samplerate, 16000)

    def test_build_timing_summary_contains_required_fields(self):
        summary = build_timing_summary(
            TimingStats(record_seconds=5.1, model_init_seconds=1.2, transcribe_seconds=0.8, total_seconds=7.1)
        )

        self.assertIn("record_seconds=5.10", summary)
        self.assertIn("model_init_seconds=1.20", summary)
        self.assertIn("transcribe_seconds=0.80", summary)
        self.assertIn("total_seconds=7.10", summary)

    def test_build_audio_summary_includes_warning_text(self):
        levels = compute_audio_levels([0, 1, -1])

        summary = build_audio_summary(Path("sample.wav"), levels)

        self.assertIn("Saved recording: sample.wav", summary)
        self.assertIn("Peak amplitude:", summary)
        self.assertIn("RMS amplitude:", summary)
        self.assertIn("may be silence", summary)

    def test_server_mode_does_not_allow_local_fallback_by_default(self):
        args = SimpleNamespace(use_server=True, allow_local_fallback=False)

        self.assertFalse(should_allow_local_fallback(args))

    def test_server_mode_allows_local_fallback_only_when_requested(self):
        args = SimpleNamespace(use_server=True, allow_local_fallback=True)

        self.assertTrue(should_allow_local_fallback(args))

    def test_non_server_mode_never_uses_server_fallback_policy(self):
        args = SimpleNamespace(use_server=False, allow_local_fallback=True)

        self.assertFalse(should_allow_local_fallback(args))


class SttServerServiceTests(unittest.TestCase):
    def test_build_success_response_contains_required_timing_fields(self):
        response = build_success_response(
            text="小黄测试",
            server_model_init_seconds=24.75,
            transcribe_seconds=1.53,
            total_seconds=1.60,
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["text"], "小黄测试")
        self.assertEqual(response["server_model_init_seconds"], 24.75)
        self.assertEqual(response["transcribe_seconds"], 1.53)
        self.assertEqual(response["total_seconds"], 1.60)


class SttClientServiceTests(unittest.TestCase):
    def test_build_transcribe_payload_uses_wav_path(self):
        payload = build_transcribe_payload(Path("data/recordings/test.wav"))

        self.assertEqual(payload, {"wav_path": "data\\recordings\\test.wav"})

    def test_build_health_url_targets_health_endpoint(self):
        self.assertEqual(build_health_url("http://127.0.0.1:8766/"), "http://127.0.0.1:8766/health")


class WakeWordServiceTests(unittest.TestCase):
    def test_parse_wake_phrases_splits_comma_separated_text(self):
        self.assertEqual(parse_wake_phrases("小黄, 小黄小黄， 你好小黄"), ["小黄", "小黄小黄", "你好小黄"])

    def test_normalize_wake_text_removes_spaces_and_common_punctuation(self):
        self.assertEqual(normalize_wake_text(" 你 好，小黄！ "), "你好小黄")

    def test_is_wake_phrase_detected_matches_xiaohuang(self):
        self.assertTrue(is_wake_phrase_detected("小黄", ["小黄"]))

    def test_is_wake_phrase_detected_matches_repeated_xiaohuang(self):
        self.assertTrue(is_wake_phrase_detected("小黄小黄。", ["小黄", "小黄小黄"]))

    def test_is_wake_phrase_detected_matches_contained_phrase(self):
        self.assertTrue(is_wake_phrase_detected("你好，小黄", ["小黄"]))

    def test_is_wake_phrase_detected_ignores_empty_text(self):
        self.assertFalse(is_wake_phrase_detected("  ，。 ", ["小黄"]))


if __name__ == "__main__":
    unittest.main()
