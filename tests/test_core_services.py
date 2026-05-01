import tempfile
import unittest
import math
from types import SimpleNamespace
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from xiaohuang.audio_capture_service import (
    classify_input_device,
    compute_audio_levels,
    build_recording_path,
    load_sounddevice,
    load_soundfile,
)
from xiaohuang.config_service import load_config
from xiaohuang.listen_once_service import (
    TimingStats,
    build_timing_summary,
    build_audio_summary,
    resolve_listen_once_options,
    should_allow_local_fallback,
)
from xiaohuang.llm_reply_service import (
    LlmReplyConfig,
    ReplyGenerationResult,
    build_deepseek_request,
    build_deepseek_response_debug_summary,
    generate_llm_reply,
    generate_llm_reply_result,
    load_deepseek_config,
    TOOL_UNAVAILABLE_REPLY,
)
from xiaohuang.overlay_state_service import build_reply_result_text, build_server_unavailable_status, get_overlay_status_text
from xiaohuang.overlay_runtime_service import resolve_post_response_cooldown
from xiaohuang.reply_service import generate_reply
from xiaohuang.stt_client_service import build_health_url, build_transcribe_payload
from xiaohuang.stt_server_service import PathGuardError, build_success_response, resolve_recording_wav_path
from xiaohuang.stt_service import MissingDependencyError, SenseVoiceTranscriber, clean_command_text
from xiaohuang.tts_service import build_tts_output_path, clean_tts_text
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
from xiaohuang.wake_word_service import detect_wake_phrase, is_wake_phrase_detected, normalize_wake_text, parse_wake_phrases
from xiaohuang.wake_loop_service import WakeLoopOptions, run_wake_loop_once


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

    def test_public_audio_dependency_loaders_are_available(self):
        self.assertTrue(callable(load_sounddevice))
        self.assertTrue(callable(load_soundfile))


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

    def test_resolve_recording_wav_path_allows_recordings_wav(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            wav_path = project_root / "data" / "recordings" / "test.wav"
            wav_path.parent.mkdir(parents=True)
            wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

            resolved = resolve_recording_wav_path("data/recordings/test.wav", project_root)

            self.assertEqual(resolved, wav_path.resolve())

    def test_resolve_recording_wav_path_allows_wake_recordings_wav(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            wav_path = project_root / "data" / "recordings" / "wake" / "test.wav"
            wav_path.parent.mkdir(parents=True)
            wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

            resolved = resolve_recording_wav_path(wav_path, project_root)

            self.assertEqual(resolved, wav_path.resolve())

    def test_resolve_recording_wav_path_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            secret_path = project_root / "secret.wav"
            secret_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

            with self.assertRaises(PathGuardError):
                resolve_recording_wav_path("data/recordings/../secret.wav", project_root)

    def test_resolve_recording_wav_path_rejects_absolute_path_outside_recordings(self):
        windows_path = Path("C:/Windows/xxx.wav")

        with self.assertRaises(PathGuardError):
            resolve_recording_wav_path(windows_path, Path("E:/Projects/xiaohuang"))

    def test_resolve_recording_wav_path_rejects_non_wav_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            text_path = project_root / "data" / "recordings" / "test.txt"
            text_path.parent.mkdir(parents=True)
            text_path.write_text("not audio", encoding="utf-8")

            with self.assertRaises(PathGuardError):
                resolve_recording_wav_path(text_path, project_root)

    def test_resolve_recording_wav_path_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)

            with self.assertRaises(PathGuardError):
                resolve_recording_wav_path("data/recordings/missing.wav", project_root)


class SttClientServiceTests(unittest.TestCase):
    def test_build_transcribe_payload_uses_wav_path(self):
        payload = build_transcribe_payload(Path("data/recordings/test.wav"))

        self.assertEqual(payload, {"wav_path": "data\\recordings\\test.wav"})

    def test_build_health_url_targets_health_endpoint(self):
        self.assertEqual(build_health_url("http://127.0.0.1:8766/"), "http://127.0.0.1:8766/health")


class ReplyServiceTests(unittest.TestCase):
    def test_generate_reply_handles_greeting(self):
        self.assertEqual(generate_reply("你好小黄"), "你好，我在。")

    def test_generate_reply_handles_status_question(self):
        self.assertEqual(generate_reply("你在干嘛？"), "我在听你说话，准备帮你处理任务。")

    def test_generate_reply_handles_model_identity_question(self):
        self.assertEqual(generate_reply("你现在不是deep seek吗？"), "我是小黄，当前可接 DeepSeek 单句回复。")

    def test_generate_reply_tolerates_stt_prefix_noise_for_status_question(self):
        for text in ("이在干嘛.", "而在干嘛呢？", "你猜我在干嘛？"):
            with self.subTest(text=text):
                self.assertEqual(generate_reply(text), "我在听你说话，准备帮你处理任务。")

    def test_generate_reply_handles_test_text(self):
        self.assertEqual(generate_reply("帮我测试一下"), "测试收到，语音链路正常。")

    def test_generate_reply_echoes_other_text_shortly(self):
        reply = generate_reply("随便一句话")

        self.assertEqual(reply, "我听到了：随便一句话")
        self.assertLessEqual(len(reply), 30)


class LlmReplyServiceTests(unittest.TestCase):
    def test_load_deepseek_config_reads_environment_without_leaking_key(self):
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret-key",
                "DEEPSEEK_BASE_URL": "https://example.invalid",
                "DEEPSEEK_MODEL": "deepseek-v4-flash",
            },
            timeout_seconds=9,
        )

        self.assertEqual(config.api_key, "secret-key")
        self.assertEqual(config.base_url, "https://example.invalid")
        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertEqual(config.timeout_seconds, 9)

    def test_build_deepseek_request_constructs_single_turn_payload(self):
        payload = build_deepseek_request("你在干嘛？", model="deepseek-v4-flash")

        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["messages"][-1]["role"], "user")
        self.assertEqual(payload["messages"][-1]["content"], "你在干嘛？")
        self.assertGreaterEqual(payload["max_tokens"], 64)
        self.assertLessEqual(payload["max_tokens"], 512)

    def test_generate_llm_reply_uses_api_when_key_is_configured(self):
        calls: list[dict] = []
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        def fake_post_json(url, payload, headers, timeout):
            calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
            return {"choices": [{"message": {"content": "我在等你叫我，有事你直接说。"}}]}

        reply = generate_llm_reply("你在干嘛？", config=config, post_json_func=fake_post_json)

        self.assertEqual(reply, "我在等你叫我，有事你直接说。")
        self.assertEqual(calls[0]["url"], "https://api.example/chat/completions")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer secret")

    def test_generate_llm_reply_result_reports_llm_source(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        result = generate_llm_reply_result(
            "你在干嘛？",
            config=config,
            post_json_func=lambda *_args: {"choices": [{"message": {"content": "我在等你。"}}]},
        )

        self.assertEqual(result, ReplyGenerationResult(text="我在等你。", source="llm"))

    def test_generate_llm_reply_falls_back_without_api_key(self):
        config = LlmReplyConfig(api_key=None, base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        result = generate_llm_reply_result("你在干嘛？", config=config)

        self.assertEqual(result.text, "我在听你说话，准备帮你处理任务。")
        self.assertEqual(result.source, "rule_fallback_no_key")

    def test_generate_llm_reply_falls_back_on_exception(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        def failing_post_json(_url, _payload, _headers, _timeout):
            raise TimeoutError("timeout")

        result = generate_llm_reply_result("测试", config=config, post_json_func=failing_post_json)

        self.assertEqual(result.text, "测试收到，语音链路正常。")
        self.assertEqual(result.source, "rule_fallback_error")

    def test_generate_llm_reply_keeps_reply_short(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        def fake_post_json(_url, _payload, _headers, _timeout):
            return {"choices": [{"message": {"content": "这是一段非常非常非常非常非常非常长的回复，应该被截断。"}}]}

        reply = generate_llm_reply("随便说一句", config=config, post_json_func=fake_post_json)

        self.assertLessEqual(len(reply), 30)

    def test_generate_llm_reply_does_not_claim_tool_execution(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        reply = generate_llm_reply("帮我打开浏览器", config=config, post_json_func=lambda *_args: {})

        self.assertEqual(reply, TOOL_UNAVAILABLE_REPLY)

    def test_generate_llm_reply_result_rejects_execution_claim_from_llm(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        fake_post = lambda *_args: {"choices": [{"message": {"content": "我已经帮你打开浏览器了。"}}]}
        result = generate_llm_reply_result("打开浏览器", config=config, post_json_func=fake_post)

        self.assertEqual(result.text, TOOL_UNAVAILABLE_REPLY)
        self.assertEqual(result.source, "tool_unavailable")

    def test_generate_llm_reply_filters_multiple_execution_claim_phrases(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        claims = [
            "我已经下载好了。",
            "已发送消息。",
            "已经帮你打开了。",
            "已修改代码完成。",
            "已删除文件。",
            "我已经执行完毕。",
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                fake_post = lambda *_args, c=claim: {"choices": [{"message": {"content": c}}]}
                result = generate_llm_reply_result("测试", config=config, post_json_func=fake_post)
                self.assertEqual(result.source, "tool_unavailable", f"Should block: {claim}")

    def test_generate_llm_reply_blocks_all_required_tool_keywords(self):
        tool_requests = [
            "打开浏览器", "打开网页",
            "下载文件", "下载一个东西",
            "发消息给张三", "发送消息",
            "回微信", "回复微信",
            "回qq", "回复qq",
            "改代码", "修改代码",
            "删除文件", "删掉那个",
            "上传资料", "上传文件",
            "登录账号", "登录我的账号",
            "支付", "付款",
            "爬取网页", "爬虫",
            "调用opencode", "opencode",
            "调用opencli", "opencli",
        ]
        for request_text in tool_requests:
            with self.subTest(request_text=request_text):
                reply = generate_llm_reply(request_text)
                self.assertEqual(reply, TOOL_UNAVAILABLE_REPLY, f"Should block: {request_text}")

    def test_generate_llm_reply_falls_back_on_http_error(self):
        from urllib.error import HTTPError
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        def http_error_post(_url, _payload, _headers, _timeout):
            raise HTTPError("https://api.example", 500, "Internal Error", {}, None)

        result = generate_llm_reply_result("测试", config=config, post_json_func=http_error_post)

        self.assertEqual(result.source, "rule_fallback_error")

    def test_generate_llm_reply_falls_back_on_url_error(self):
        from urllib.error import URLError
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        def url_error_post(_url, _payload, _headers, _timeout):
            raise URLError("connection refused")

        result = generate_llm_reply_result("测试", config=config, post_json_func=url_error_post)

        self.assertEqual(result.source, "rule_fallback_error")

    def test_generate_llm_reply_does_not_leak_api_key_in_result(self):
        config = LlmReplyConfig(api_key="sk-secret-12345", base_url="https://api.example", model="deepseek-v4-flash", timeout_seconds=15)

        def fake_post_json(_url, _payload, _headers, _timeout):
            return {"choices": [{"message": {"content": "我在。"}}]}

        result = generate_llm_reply_result("你好", config=config, post_json_func=fake_post_json)

        self.assertNotIn("sk-secret-12345", result.text)
        self.assertNotIn("sk-secret", result.text)

    def test_load_deepseek_config_returns_not_configured_when_key_empty_string(self):
        config = load_deepseek_config(env={"DEEPSEEK_API_KEY": "  "})

        self.assertFalse(config.is_configured)

    def test_normal_openai_compatible_response_parsed_correctly(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "你在干嘛？",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": "我在听你说话。"}, "finish_reason": "stop"}]
            },
        )

        self.assertEqual(result.text, "我在听你说话。")
        self.assertEqual(result.source, "llm")

    def test_empty_content_in_choices_falls_back_to_empty(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": ""}, "finish_reason": "stop"}]
            },
        )

        self.assertEqual(result.source, "rule_fallback_empty")

    def test_response_with_error_field_falls_back_to_error(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "error": {"type": "invalid_request_error", "message": "Model not found"}
            },
        )

        self.assertEqual(result.source, "rule_fallback_error")

    def test_missing_choices_falls_back_without_exception(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {"id": "chatcmpl-123", "object": "chat.completion"},
        )

        self.assertEqual(result.source, "rule_fallback_empty")

    def test_missing_message_in_choice_falls_back_without_exception(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {"choices": [{"finish_reason": "stop"}]},
        )

        self.assertIn(result.source, ("rule_fallback_empty", "rule_fallback_error"))

    def test_content_filter_with_empty_content_falls_back(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]
            },
        )

        self.assertEqual(result.source, "rule_fallback_empty")

    def test_debug_summary_never_contains_api_key(self):
        summary = build_deepseek_response_debug_summary({
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "model": "deepseek-chat",
            "usage": {"total_tokens": 10},
        })

        self.assertNotIn("Bearer", summary)
        self.assertNotIn("sk-", summary)
        self.assertNotIn("Authorization", summary)

    def test_debug_summary_includes_safe_fields_for_error_response(self):
        summary = build_deepseek_response_debug_summary({
            "error": {"type": "rate_limit_exceeded", "message": "Too many requests"}
        })

        self.assertIn("has_error=True", summary)
        self.assertIn("rate_limit_exceeded", summary)
        self.assertIn("Too many requests", summary)
        self.assertIn("choices_count=0", summary)

    def test_debug_summary_includes_finish_reason_and_model(self):
        summary = build_deepseek_response_debug_summary({
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "model": "deepseek-chat",
            "usage": {"total_tokens": 10},
        })

        self.assertIn("finish_reason=stop", summary)
        self.assertIn("model=deepseek-chat", summary)
        self.assertIn("has_usage=True", summary)

    def test_on_debug_callback_invoked_on_error_response(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)
        calls: list[str] = []

        generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "error": {"type": "server_error", "message": "internal error"}
            },
            on_debug=calls.append,
        )

        self.assertEqual(len(calls), 1)
        self.assertIn("has_error=True", calls[0])

    def test_on_debug_callback_invoked_on_empty_reply(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)
        calls: list[str] = []

        generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {"choices": [{"message": {"content": ""}}]},
            on_debug=calls.append,
        )

        self.assertEqual(len(calls), 1)

    def test_on_debug_not_called_on_successful_llm_reply(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)
        calls: list[str] = []

        result = generate_llm_reply_result(
            "你好",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": "你好！"}, "finish_reason": "stop"}]
            },
            on_debug=calls.append,
        )

        self.assertEqual(result.source, "llm")
        self.assertEqual(len(calls), 0)

    def test_on_debug_called_on_content_filter_finish_reason(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)
        calls: list[str] = []

        generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "content_filter"}]
            },
            on_debug=calls.append,
        )

        self.assertEqual(len(calls), 1)
        self.assertIn("finish_reason=content_filter", calls[0])

    def test_finish_reason_length_with_empty_content(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}]
            },
        )

        self.assertEqual(result.source, "rule_fallback_length")

    def test_finish_reason_length_with_nonempty_content(self):
        config = LlmReplyConfig(api_key="secret", base_url="https://api.example", model="deepseek-chat", timeout_seconds=15)

        result = generate_llm_reply_result(
            "测试",
            config=config,
            post_json_func=lambda *_args: {
                "choices": [{"message": {"content": "短回复"}, "finish_reason": "length"}]
            },
        )

        self.assertEqual(result.source, "llm")
        self.assertEqual(result.text, "短回复")

    def test_default_max_tokens_is_at_least_64(self):
        payload = build_deepseek_request("测试", model="deepseek-chat")
        self.assertGreaterEqual(payload["max_tokens"], 64)

    def test_max_tokens_respected_in_request(self):
        payload = build_deepseek_request("测试", model="deepseek-chat", max_tokens=128)
        self.assertEqual(payload["max_tokens"], 128)


class TtsServiceTests(unittest.TestCase):
    def test_clean_tts_text_removes_extra_whitespace(self):
        self.assertEqual(clean_tts_text("  你好\n小黄  "), "你好 小黄")

    def test_build_tts_output_path_uses_timestamp_and_mp3_suffix(self):
        path = build_tts_output_path(Path("data") / "tts", timestamp="20260501_010203")

        self.assertEqual(path, Path("data") / "tts" / "tts_20260501_010203.mp3")


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

    def test_detect_wake_phrase_exact_match(self):
        result = detect_wake_phrase("小黄。", ["小黄", "小黄小黄"])

        self.assertTrue(result.detected)
        self.assertEqual(result.reason, "exact_match")
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.matched_phrase, "小黄")

    def test_detect_wake_phrase_repeated_exact_match(self):
        result = detect_wake_phrase("小黄小黄。", ["小黄", "小黄小黄"])

        self.assertTrue(result.detected)
        self.assertEqual(result.reason, "exact_match")
        self.assertEqual(result.matched_phrase, "小黄小黄")

    def test_detect_wake_phrase_contained_match(self):
        result = detect_wake_phrase("你好小黄", ["小黄"])

        self.assertTrue(result.detected)
        self.assertEqual(result.reason, "contains_match")

    def test_detect_wake_phrase_suffix_noise_match(self):
        result = detect_wake_phrase("小黄ang", ["小黄"])

        self.assertTrue(result.detected)
        self.assertEqual(result.reason, "suffix_noise_match")

    def test_detect_wake_phrase_default_alias_match(self):
        result = detect_wake_phrase("小皇", ["小黄"])

        self.assertTrue(result.detected)
        self.assertEqual(result.reason, "alias_match")
        self.assertEqual(result.score, 0.75)

    def test_detect_wake_phrase_rejects_unrelated_and_empty_text(self):
        self.assertFalse(detect_wake_phrase("哦", ["小黄"]).detected)
        self.assertFalse(detect_wake_phrase("", ["小黄"]).detected)

    def test_detect_wake_phrase_manual_alias_is_opt_in(self):
        self.assertFalse(detect_wake_phrase("小王", ["小黄"]).detected)
        self.assertTrue(detect_wake_phrase("小王", ["小黄"], alias_phrases=["小王"]).detected)


class OverlayStateServiceTests(unittest.TestCase):
    def test_get_overlay_status_text_maps_idle_state(self):
        status = get_overlay_status_text("idle")

        self.assertEqual(status.title, "小黄待机中")
        self.assertEqual(status.subtitle, "说“小黄”唤醒我")

    def test_get_overlay_status_text_maps_result_state_with_text(self):
        status = get_overlay_status_text("result", "你在干嘛？")

        self.assertEqual(status.title, "你说：")
        self.assertEqual(status.subtitle, "你在干嘛？")

    def test_build_server_unavailable_status_returns_error_text(self):
        status = build_server_unavailable_status("http://127.0.0.1:8766")

        self.assertEqual(status.state, "error")
        self.assertEqual(status.title, "STT server 未启动")
        self.assertIn("scripts\\stt_server.py", status.subtitle)

    def test_get_overlay_status_text_maps_replying_and_speaking_states(self):
        replying = get_overlay_status_text("replying")
        speaking = get_overlay_status_text("speaking")

        self.assertEqual(replying.title, "正在想怎么回复...")
        self.assertEqual(speaking.title, "小黄正在说话")

    def test_build_reply_result_text_without_source_note(self):
        text = build_reply_result_text("你好", "我在。")

        self.assertIn("你说：你好", text)
        self.assertIn("小黄：我在。", text)
        self.assertNotIn("(", text)

    def test_build_reply_result_text_with_source_note(self):
        text = build_reply_result_text("你好", "我在。", source_note="DeepSeek 不可用，已使用本地回复")

        self.assertIn("你说：你好", text)
        self.assertIn("小黄：我在。", text)
        self.assertIn("(DeepSeek 不可用，已使用本地回复)", text)


class OverlayRuntimeServiceTests(unittest.TestCase):
    def test_resolve_post_response_cooldown_defaults_longer_when_tts_enabled(self):
        self.assertEqual(resolve_post_response_cooldown(enable_tts=True, requested_seconds=None), 6.0)
        self.assertEqual(resolve_post_response_cooldown(enable_tts=False, requested_seconds=None), 3.5)

    def test_resolve_post_response_cooldown_respects_explicit_value(self):
        self.assertEqual(resolve_post_response_cooldown(enable_tts=True, requested_seconds=8.0), 8.0)


class WakeLoopServiceTests(unittest.TestCase):
    def test_run_wake_loop_once_emits_expected_callback_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            recording_dir = project_root / "data" / "recordings"
            wake_path = recording_dir / "wake" / "wake.wav"
            command_path = recording_dir / "command.wav"
            events: list[str] = []
            transcribe_calls: list[Path] = []

            options = WakeLoopOptions(
                device_id=0,
                server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0,
                wake_phrases=["小黄"],
                max_seconds=10.0,
                silence_seconds=0.8,
                sample_rate=16000,
                channels=1,
                recording_dir=recording_dir,
                keep_wake_recordings=False,
            )

            def fake_build_path(output_dir):
                return wake_path if Path(output_dir).name == "wake" else command_path

            def fake_record_wav(output_path, **_kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
                return Path(output_path)

            def fake_record_until_silence(output_path, **_kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
                return SimpleNamespace(path=Path(output_path), duration_seconds=1.2, stop_reason="silence_after_speech")

            def fake_transcribe(path, _server_url):
                transcribe_calls.append(Path(path))
                return {"text": "小黄" if len(transcribe_calls) == 1 else "帮我测试"}

            result = run_wake_loop_once(
                options,
                on_state_change=lambda state, _payload=None: events.append(state),
                record_wav_func=fake_record_wav,
                record_until_silence_func=fake_record_until_silence,
                request_transcription_func=fake_transcribe,
                build_recording_path_func=fake_build_path,
            )

            self.assertEqual(events, ["wake_checking", "wake_detected", "listening", "transcribing", "result"])
            self.assertEqual(result.wake_text, "小黄")
            self.assertEqual(result.command_text, "帮我测试")
            self.assertFalse(wake_path.exists())

    def test_run_wake_loop_once_calls_text_callbacks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording_dir = Path(temp_dir) / "data" / "recordings"
            seen_wake: list[str] = []
            seen_command: list[str] = []
            calls = {"count": 0}

            options = WakeLoopOptions(
                device_id=0,
                server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0,
                wake_phrases=["小黄"],
                max_seconds=10.0,
                silence_seconds=0.8,
                sample_rate=16000,
                channels=1,
                recording_dir=recording_dir,
            )

            def fake_path(output_dir):
                return Path(output_dir) / f"{Path(output_dir).name}.wav"

            def write_wav(output_path, **_kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
                return Path(output_path)

            def fake_vad(output_path, **_kwargs):
                write_wav(output_path)
                return SimpleNamespace(path=Path(output_path), duration_seconds=1.0, stop_reason="silence_after_speech")

            def fake_transcribe(_path, _server_url):
                calls["count"] += 1
                return {"text": "小黄" if calls["count"] == 1 else "你在干嘛？"}

            run_wake_loop_once(
                options,
                on_wake_text=seen_wake.append,
                on_command_text=seen_command.append,
                record_wav_func=write_wav,
                record_until_silence_func=fake_vad,
                request_transcription_func=fake_transcribe,
                build_recording_path_func=fake_path,
            )

            self.assertEqual(seen_wake, ["小黄"])
            self.assertEqual(seen_command, ["你在干嘛？"])

    def test_run_wake_loop_once_wake_stt_error_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording_dir = Path(temp_dir) / "data" / "recordings"
            events: list[str] = []

            options = WakeLoopOptions(
                device_id=0,
                server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0,
                wake_phrases=["小黄"],
                max_seconds=10.0,
                silence_seconds=0.8,
                sample_rate=16000,
                channels=1,
                recording_dir=recording_dir,
            )

            def fake_path(output_dir):
                return Path(output_dir) / f"{Path(output_dir).name}.wav"

            def write_wav(output_path, **_kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
                return Path(output_path)

            call_count = {"n": 0}

            def safe_stt(_path, _server_url):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return {"text": ""}
                return {"text": "小黄" if call_count["n"] == 2 else "测试"}

            def fake_vad(output_path, **_kwargs):
                write_wav(output_path)
                return SimpleNamespace(path=Path(output_path), duration_seconds=1.0, stop_reason="silence_after_speech")

            result = run_wake_loop_once(
                options,
                on_state_change=lambda state, _payload=None: events.append(state),
                record_wav_func=write_wav,
                record_until_silence_func=fake_vad,
                request_transcription_func=safe_stt,
                build_recording_path_func=fake_path,
            )

            self.assertIn("wake_checking", events)
            self.assertEqual(result.command_text, "测试")


class VoiceOverlayGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
        except ImportError:
            raise unittest.SkipTest("Tkinter not available")
        cls._tk = tk

    def setUp(self):
        import threading
        self._stop_event = threading.Event()
        self._root = self._tk.Tk()
        self._root.withdraw()

    def tearDown(self):
        try:
            self._root.destroy()
        except Exception:
            pass

    def _make_app(self):
        from voice_overlay import VoiceOverlayApp
        return VoiceOverlayApp(self._root, stop_event=self._stop_event, debug=False)

    def test_thread_safe_set_state_after_close_does_not_throw(self):
        app = self._make_app()
        app.close()
        try:
            app.thread_safe_set_state("idle")
        except tk.TclError:
            self.fail("thread_safe_set_state raised TclError after close")

    def test_schedule_idle_after_close_does_not_throw(self):
        app = self._make_app()
        app.close()
        try:
            app.schedule_idle(100)
        except tk.TclError:
            self.fail("schedule_idle raised TclError after close")

    def test_animate_after_close_does_not_throw(self):
        app = self._make_app()
        app.close()
        try:
            app._animate()
        except tk.TclError:
            self.fail("_animate raised TclError after close")

    def test_thread_safe_show_status_after_close_does_not_throw(self):
        from xiaohuang.overlay_state_service import build_server_unavailable_status
        app = self._make_app()
        app.close()
        status = build_server_unavailable_status("http://127.0.0.1:8766")
        try:
            app.thread_safe_show_status(status)
        except tk.TclError:
            self.fail("thread_safe_show_status raised TclError after close")

    def test_close_is_idempotent(self):
        app = self._make_app()
        app.close()
        try:
            app.close()
        except Exception as exc:
            self.fail(f"second close raised unexpected {type(exc).__name__}: {exc}")


class SourceNoteTests(unittest.TestCase):
    def test_source_note_none_for_rule(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIsNone(_source_note_for_overlay("rule"))

    def test_source_note_none_for_llm(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIsNone(_source_note_for_overlay("llm"))

    def test_source_note_no_key(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIn("未配置 key", _source_note_for_overlay("rule_fallback_no_key"))

    def test_source_note_error(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIn("不可用", _source_note_for_overlay("rule_fallback_error"))

    def test_source_note_empty(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIn("返回为空", _source_note_for_overlay("rule_fallback_empty"))

    def test_source_note_length(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIn("被截断", _source_note_for_overlay("rule_fallback_length"))

    def test_source_note_tool_unavailable(self):
        from voice_overlay import _source_note_for_overlay
        self.assertIn("不能执行工具", _source_note_for_overlay("tool_unavailable"))


if __name__ == "__main__":
    unittest.main()
