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
from xiaohuang.api_error_service import STT_ENGINE_ERROR, STT_SERVER_ERROR, build_error
from xiaohuang.api_schemas import build_error_response, build_ok_response
from xiaohuang.config_service import load_config
from xiaohuang.request_context_service import generate_request_id
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
from xiaohuang.stt_client_service import _extract_error_message, build_health_url, build_transcribe_payload
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


class V114BTrayAppTests(unittest.TestCase):
    def test_tray_app_help_runs(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/tray_app.py", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--config", result.stdout)

    def test_default_config_path_uses_userprofile(self):
        import tray_app
        config_path = tray_app.get_default_config_path(env={"USERPROFILE": r"C:\Users\tester"})
        self.assertEqual(config_path, Path(r"C:\Users\tester") / ".xiaohuang" / "config.json")

    def test_ensure_log_dir_creates_project_logs_dir(self):
        import tray_app
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = tray_app.ensure_log_dir(Path(temp_dir))
            self.assertTrue(log_dir.exists())
            self.assertEqual(log_dir, Path(temp_dir) / "logs")

    def test_build_settings_command_does_not_include_api_key(self):
        import tray_app
        command = tray_app.build_settings_command(
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            python_executable="python.exe",
            project_root=Path(r"E:\Projects\xiaohuang"),
        )
        joined = " ".join(str(part) for part in command)
        self.assertIn("settings_ui.py", joined)
        self.assertIn("--config", command)
        self.assertNotIn("sk-", joined)
        self.assertNotIn("secrets.ps1", joined)
        self.assertNotIn("DEEPSEEK_API_KEY=", joined)

    def test_build_control_panel_command_uses_current_config(self):
        import tray_app
        command = tray_app.build_control_panel_command(
            Path(r"C:\Users\tester\.xiaohuang\config_settings_ui_test.json"),
            python_executable="python.exe",
            project_root=Path(r"E:\Projects\xiaohuang"),
        )
        joined = " ".join(str(part) for part in command)
        self.assertIn("control_panel.py", joined)
        self.assertIn("--config", command)
        self.assertIn(r"C:\Users\tester\.xiaohuang\config_settings_ui_test.json", command)
        self.assertNotIn("sk-", joined)

    def test_exit_tray_only_stops_tray_icon(self):
        import tray_app

        class FakeIcon:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        fake_icon = FakeIcon()
        tray_app.exit_tray(fake_icon)
        self.assertTrue(fake_icon.stopped)

    def test_tray_process_output_redacts_api_key(self):
        import tray_app

        text = tray_app._sanitize_process_output("DEEPSEEK_API_KEY = sk-abcdefghijklmnopqrstuvwxyz")

        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", text)
        self.assertIn("***", text)


class V12CWakeEngineServiceTests(unittest.TestCase):
    def test_wake_event_dataclass_fields(self):
        from xiaohuang.wake_engine_service import WakeEvent

        event = WakeEvent(
            engine_type="openwakeword",
            wake_phrase="贾维斯",
            label="hey_jarvis",
            score=0.98,
            detected_at=10.0,
            raw_event_count=3,
            suppressed_event_count=2,
        )

        self.assertEqual(event.engine_type, "openwakeword")
        self.assertEqual(event.wake_phrase, "贾维斯")
        self.assertEqual(event.label, "hey_jarvis")
        self.assertEqual(event.score, 0.98)
        self.assertEqual(event.detected_at, 10.0)
        self.assertEqual(event.raw_event_count, 3)
        self.assertEqual(event.suppressed_event_count, 2)

    def test_wake_engine_status_dataclass_fields(self):
        from xiaohuang.wake_engine_service import WakeEngineStatus

        status = WakeEngineStatus(
            engine_type="fake",
            running=True,
            ready=True,
            model_loaded=True,
            wake_phrase="贾维斯",
            sensitivity=0.5,
            last_wake_time=12.0,
            last_score=0.9,
            error=None,
        )

        self.assertEqual(status.engine_type, "fake")
        self.assertTrue(status.running)
        self.assertTrue(status.ready)
        self.assertTrue(status.model_loaded)
        self.assertEqual(status.wake_phrase, "贾维斯")
        self.assertEqual(status.sensitivity, 0.5)
        self.assertEqual(status.last_wake_time, 12.0)
        self.assertEqual(status.last_score, 0.9)
        self.assertIsNone(status.error)

    def test_wake_event_stats_dataclass_fields(self):
        from xiaohuang.wake_engine_service import WakeEventStats

        stats = WakeEventStats(
            raw_detections=44,
            coalesced_events=7,
            suppressed_detections=37,
            cooldown_seconds=2.5,
        )

        self.assertEqual(stats.raw_detections, 44)
        self.assertEqual(stats.coalesced_events, 7)
        self.assertEqual(stats.suppressed_detections, 37)
        self.assertEqual(stats.cooldown_seconds, 2.5)

    def test_wake_event_coalescer_accepts_first_label_event(self):
        from xiaohuang.wake_engine_service import WakeEventCoalescer

        coalescer = WakeEventCoalescer(cooldown_seconds=2.5)

        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0, score=0.9))

    def test_wake_event_coalescer_suppresses_same_label_inside_cooldown(self):
        from xiaohuang.wake_engine_service import WakeEventCoalescer

        coalescer = WakeEventCoalescer(cooldown_seconds=2.5)
        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0, score=0.9))

        self.assertFalse(coalescer.accept("hey_jarvis", now=11.0, score=0.95))
        self.assertAlmostEqual(coalescer.remaining_seconds("hey_jarvis", now=11.0), 1.5)

    def test_wake_event_coalescer_accepts_same_label_after_cooldown(self):
        from xiaohuang.wake_engine_service import WakeEventCoalescer

        coalescer = WakeEventCoalescer(cooldown_seconds=2.5)
        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0, score=0.9))

        self.assertTrue(coalescer.accept("hey_jarvis", now=12.6, score=0.95))

    def test_wake_event_coalescer_uses_per_label_cooldown(self):
        from xiaohuang.wake_engine_service import WakeEventCoalescer

        coalescer = WakeEventCoalescer(cooldown_seconds=2.5)
        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0, score=0.9))

        self.assertTrue(coalescer.accept("alexa", now=11.0, score=0.8))

    def test_wake_event_coalescer_stats_counts_raw_coalesced_and_suppressed(self):
        from xiaohuang.wake_engine_service import WakeEventCoalescer

        coalescer = WakeEventCoalescer(cooldown_seconds=2.5)
        coalescer.accept("hey_jarvis", now=10.0, score=0.9)
        coalescer.accept("hey_jarvis", now=10.5, score=0.96)
        coalescer.accept("alexa", now=10.6, score=0.7)
        stats = coalescer.stats()

        self.assertEqual(stats.raw_detections, 3)
        self.assertEqual(stats.coalesced_events, 2)
        self.assertEqual(stats.suppressed_detections, 1)
        self.assertEqual(stats.cooldown_seconds, 2.5)
        self.assertEqual(coalescer.event_counts("hey_jarvis"), (2, 1))

    def test_wake_event_coalescer_reset_clears_state_and_stats(self):
        from xiaohuang.wake_engine_service import WakeEventCoalescer

        coalescer = WakeEventCoalescer(cooldown_seconds=2.5)
        coalescer.accept("hey_jarvis", now=10.0, score=0.9)
        coalescer.accept("hey_jarvis", now=10.5, score=0.96)

        coalescer.reset()
        stats = coalescer.stats()

        self.assertEqual(stats.raw_detections, 0)
        self.assertEqual(stats.coalesced_events, 0)
        self.assertEqual(stats.suppressed_detections, 0)
        self.assertEqual(coalescer.remaining_seconds("hey_jarvis", now=11.0), 0.0)

    def test_fake_wake_engine_start_stop_status(self):
        from xiaohuang.wake_engine_service import FakeWakeEngine

        engine = FakeWakeEngine(wake_phrase="贾维斯", sensitivity=0.5)
        self.assertFalse(engine.status().running)
        self.assertFalse(engine.status().ready)

        engine.start()
        self.assertTrue(engine.status().running)
        self.assertTrue(engine.status().ready)
        self.assertTrue(engine.status().model_loaded)

        engine.stop()
        self.assertFalse(engine.status().running)
        self.assertFalse(engine.status().ready)

    def test_fake_wake_engine_emit_fake_event_uses_coalescer(self):
        from xiaohuang.wake_engine_service import FakeWakeEngine

        engine = FakeWakeEngine(wake_phrase="贾维斯", label="hey_jarvis", cooldown_seconds=2.5)
        engine.start()

        event = engine.emit_fake_event(score=0.9, now=10.0)
        suppressed = engine.emit_fake_event(score=0.95, now=11.0)
        stats = engine.coalescer.stats()

        self.assertIsNotNone(event)
        self.assertEqual(event.engine_type, "fake")
        self.assertEqual(event.wake_phrase, "贾维斯")
        self.assertEqual(event.label, "hey_jarvis")
        self.assertIsNone(suppressed)
        self.assertEqual(stats.raw_detections, 2)
        self.assertEqual(stats.coalesced_events, 1)
        self.assertEqual(stats.suppressed_detections, 1)

    def test_fake_wake_engine_can_simulate_error(self):
        from xiaohuang.wake_engine_service import FakeWakeEngine

        engine = FakeWakeEngine()
        engine.start()
        engine.set_error("simulated")

        self.assertFalse(engine.status().ready)
        self.assertEqual(engine.status().error, "simulated")
        self.assertIsNone(engine.emit_fake_event(score=1.0, now=10.0))


class V12DCWakeCommandBridgeTests(unittest.TestCase):
    def _wake_event(self, detected_at: float = 10.0):
        from xiaohuang.wake_engine_service import WakeEvent

        return WakeEvent(
            engine_type="fake",
            wake_phrase="贾维斯",
            label="hey_jarvis",
            score=0.9,
            detected_at=detected_at,
        )

    def _bridge(self, *, cooldown: float = 2.5, enabled: bool = True, raise_on_start: bool = False):
        from xiaohuang.wake_command_bridge_service import (
            FakeCommandStarter,
            WakeCommandBridge,
            WakeCommandBridgeConfig,
        )

        clock = ManualClock(10.0)
        starter = FakeCommandStarter(raise_on_start=raise_on_start)
        bridge = WakeCommandBridge(
            WakeCommandBridgeConfig(enabled=enabled, post_wake_cooldown_seconds=cooldown),
            starter,
            time_fn=clock.now,
        )
        return bridge, starter, clock

    def test_bridge_accepts_first_wake_event(self):
        bridge, starter, _ = self._bridge()

        decision = bridge.handle_wake_event(self._wake_event())

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "accepted")
        self.assertEqual(starter.call_count, 1)
        self.assertEqual(bridge.state().accepted_count, 1)
        self.assertEqual(bridge.state().suppressed_count, 0)

    def test_bridge_rejects_second_event_inside_cooldown(self):
        bridge, starter, clock = self._bridge(cooldown=2.5)
        bridge.handle_wake_event(self._wake_event(detected_at=10.0))
        clock.advance(1.0)

        decision = bridge.handle_wake_event(self._wake_event(detected_at=11.0))

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "cooldown")
        self.assertEqual(starter.call_count, 1)
        self.assertEqual(bridge.state().accepted_count, 1)
        self.assertEqual(bridge.state().suppressed_count, 1)

    def test_bridge_accepts_after_cooldown(self):
        bridge, starter, clock = self._bridge(cooldown=2.5)
        bridge.handle_wake_event(self._wake_event(detected_at=10.0))
        clock.advance(2.6)

        decision = bridge.handle_wake_event(self._wake_event(detected_at=12.6))

        self.assertTrue(decision.accepted)
        self.assertEqual(starter.call_count, 2)
        self.assertEqual(bridge.state().accepted_count, 2)

    def test_bridge_rejects_when_command_active(self):
        bridge, starter, _ = self._bridge()
        bridge.mark_command_started()

        decision = bridge.handle_wake_event(self._wake_event())

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "command_active")
        self.assertEqual(starter.call_count, 0)

    def test_bridge_rejects_when_tts_active(self):
        bridge, starter, _ = self._bridge()
        bridge.mark_tts_started()

        decision = bridge.handle_wake_event(self._wake_event())

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "tts_active")
        self.assertEqual(starter.call_count, 0)

    def test_bridge_rejects_when_disabled(self):
        bridge, starter, _ = self._bridge(enabled=False)

        decision = bridge.handle_wake_event(self._wake_event())

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "disabled")
        self.assertEqual(starter.call_count, 0)

    def test_bridge_recorder_error_releases_busy_state(self):
        bridge, starter, _ = self._bridge(raise_on_start=True)

        decision = bridge.handle_wake_event(self._wake_event())
        state = bridge.state()

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "recorder_error")
        self.assertEqual(starter.call_count, 0)
        self.assertFalse(state.bridge_busy)
        self.assertEqual(state.accepted_count, 0)
        self.assertEqual(state.suppressed_count, 1)

    def test_bridge_reset_clears_state(self):
        bridge, _, _ = self._bridge()
        bridge.handle_wake_event(self._wake_event())
        bridge.mark_command_started()
        bridge.mark_tts_started()

        bridge.reset()
        state = bridge.state()

        self.assertFalse(state.command_active)
        self.assertFalse(state.tts_active)
        self.assertFalse(state.bridge_busy)
        self.assertIsNone(state.last_wake_time)
        self.assertEqual(state.accepted_count, 0)
        self.assertEqual(state.suppressed_count, 0)
        self.assertIsNone(state.last_reason)

    def test_fake_command_starter_only_receives_accepted_events(self):
        bridge, starter, clock = self._bridge(cooldown=2.5)
        first = self._wake_event(detected_at=10.0)
        second = self._wake_event(detected_at=11.0)

        bridge.handle_wake_event(first)
        clock.advance(1.0)
        bridge.handle_wake_event(second)

        self.assertEqual(starter.calls, [first])

    def test_wake_command_bridge_demo_help_runs(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/wake_command_bridge_demo.py", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("--events", result.stdout)
        self.assertIn("--simulate-tts", result.stdout)
        self.assertIn("--simulate-command-active", result.stdout)

    def test_wake_command_bridge_demo_dry_run(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/wake_command_bridge_demo.py", "--dry-run"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("bridge_demo=true", result.stdout)
        self.assertIn("dry_run=true", result.stdout)
        self.assertIn("will_open_microphone=false", result.stdout)

    def test_wake_command_bridge_demo_default_cooldown_starts_once(self):
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "scripts/wake_command_bridge_demo.py",
                "--events",
                "3",
                "--interval-seconds",
                "0.5",
                "--cooldown-seconds",
                "2.5",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("event_index=1 decision=accepted reason=accepted", result.stdout)
        self.assertIn("event_index=2 decision=suppressed reason=cooldown", result.stdout)
        self.assertIn("command_starts=1", result.stdout)
        self.assertIn("accepted_count=1", result.stdout)

    def test_wake_command_bridge_demo_simulated_blocks(self):
        import subprocess

        for flag, reason in [
            ("--simulate-tts", "tts_active"),
            ("--simulate-command-active", "command_active"),
            ("--simulate-error", "recorder_error"),
        ]:
            result = subprocess.run(
                [sys.executable, "scripts/wake_command_bridge_demo.py", flag, "--events", "1"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn(f"reason={reason}", result.stdout)


class V12EOpenWakeWordOverlayIntegrationTests(unittest.TestCase):
    def _runtime_config(self, *, engine: str = "openwakeword", fallback_enabled: bool = True):
        from xiaohuang.wake_runtime_service import WakeEngineRuntimeConfig

        return WakeEngineRuntimeConfig(
            engine=engine,
            wake_phrase="贾维斯",
            fallback_enabled=fallback_enabled,
            device=0,
            sample_rate=16000,
            sensitivity=0.5,
            cooldown_seconds=2.5,
            model_path=None,
            model_name="hey_jarvis",
            poll_seconds=0.1,
        )

    def _dependency_status(self, *, ready: bool):
        from xiaohuang.openwakeword_adapter import OpenWakeWordDependencyStatus

        return OpenWakeWordDependencyStatus(
            openwakeword_installed=ready,
            numpy_installed=ready,
            sounddevice_installed=ready,
            onnxruntime_available=ready,
            ready_for_realtime_demo=ready,
            errors=[] if ready else ["Missing optional dependency: openwakeword"],
        )

    def _wake_event(self):
        from xiaohuang.wake_engine_service import WakeEvent

        return WakeEvent(
            engine_type="openwakeword",
            wake_phrase="贾维斯",
            label="hey_jarvis",
            score=0.92,
            detected_at=10.0,
        )

    def test_default_wake_config_keeps_stt_text_engine(self):
        from xiaohuang.app_config_service import get_default_config

        config = get_default_config()

        self.assertEqual(config.wake.engine, "stt_text")
        self.assertTrue(config.wake.fallback_enabled)

    def test_wake_config_reads_openwakeword_fields(self):
        from xiaohuang.app_config_service import get_default_config, merge_config_dict

        config = merge_config_dict(
            get_default_config(),
            {
                "wake": {
                    "engine": "openwakeword",
                    "fallback_enabled": False,
                    "sensitivity": 0.6,
                    "cooldown_seconds": 3.0,
                    "device_index": 2,
                    "model_name": "hey_jarvis",
                }
            },
        )

        self.assertEqual(config.wake.engine, "openwakeword")
        self.assertFalse(config.wake.fallback_enabled)
        self.assertEqual(config.wake.sensitivity, 0.6)
        self.assertEqual(config.wake.cooldown_seconds, 3.0)
        self.assertEqual(config.wake.device_index, 2)
        self.assertEqual(config.wake.model_name, "hey_jarvis")

    def test_openwakeword_engine_selects_openwakeword_when_dependencies_ready(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_OPENWAKEWORD, select_wake_engine_runtime as _select_wake_engine_runtime

        plan = _select_wake_engine_runtime(
            self._runtime_config(engine="openwakeword"),
            dependency_status=self._dependency_status(ready=True),
        )

        self.assertEqual(plan.engine, WAKE_ENGINE_OPENWAKEWORD)
        self.assertIsNone(plan.error)

    def test_openwakeword_dependency_missing_falls_back_when_enabled(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_STT_TEXT, select_wake_engine_runtime as _select_wake_engine_runtime

        plan = _select_wake_engine_runtime(
            self._runtime_config(engine="openwakeword", fallback_enabled=True),
            dependency_status=self._dependency_status(ready=False),
        )

        self.assertEqual(plan.engine, WAKE_ENGINE_STT_TEXT)
        self.assertIsNone(plan.error)
        self.assertIn("falling back to stt_text", plan.warning)

    def test_openwakeword_dependency_missing_errors_when_fallback_disabled(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_OPENWAKEWORD, select_wake_engine_runtime as _select_wake_engine_runtime

        plan = _select_wake_engine_runtime(
            self._runtime_config(engine="openwakeword", fallback_enabled=False),
            dependency_status=self._dependency_status(ready=False),
        )

        self.assertEqual(plan.engine, WAKE_ENGINE_OPENWAKEWORD)
        self.assertIn("dependency unavailable", plan.error)

    def test_openwakeword_startup_config_logs_required_fields(self):
        from voice_overlay import WAKE_ENGINE_OPENWAKEWORD, _print_wake_engine_runtime_config

        logger = FakeLogger()

        _print_wake_engine_runtime_config(self._runtime_config(), WAKE_ENGINE_OPENWAKEWORD, logger)

        log_text = logger.text
        self.assertIn("wake_engine_selected=openwakeword", log_text)
        self.assertIn("wake_fallback_enabled=true", log_text)
        self.assertIn("wake_device_index=0", log_text)
        self.assertIn("wake_cooldown_seconds=2.5", log_text)
        self.assertIn("wake_sensitivity=0.5", log_text)

    def test_openwakeword_listener_thread_starts_continuous_adapter_once(self):
        import threading
        from xiaohuang.wake_runtime_service import (
            OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime,
            start_openwakeword_listener as _start_openwakeword_listener,
            stop_openwakeword_listener as _stop_openwakeword_listener,
        )

        app = FakeOverlayApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        adapter = LoopingFakeOpenWakeWordAdapter([], stop_event=stop_event)
        bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5)

        handle = _start_openwakeword_listener(
            app=app,
            runtime_config=self._runtime_config(),
            bridge_runtime=bridge,
            logger=logger,
            debug=False,
            stop_event=stop_event,
            adapter_factory=lambda _config: adapter,
        )
        handle.thread.join(timeout=1.0)
        _stop_openwakeword_listener(handle)

        self.assertEqual(adapter.run_until_count, 1)
        self.assertEqual(adapter.run_count, 0)
        self.assertFalse(handle.thread.is_alive())
        self.assertIn("openwakeword_listener_starting", logger.text)
        self.assertIn("openwakeword_listener_running", logger.text)
        self.assertIn("openwakeword_listener_status", logger.text)
        self.assertIn("model_labels=hey_jarvis", logger.text)
        self.assertIn("openwakeword_listener_stopped", logger.text)

    def test_openwakeword_listener_accepted_event_enters_command_entry_once(self):
        import threading
        from xiaohuang.wake_runtime_service import OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime
        from voice_overlay import _record_openwakeword_command
        from xiaohuang.overlay_loop_runtime_service import _run_openwakeword_turn_from_listener
        from xiaohuang.wake_runtime_service import (
            start_openwakeword_listener,
            stop_openwakeword_listener,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            app = FakeOverlayApp()
            logger = FakeLogger()
            stop_event = threading.Event()
            bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5)
            adapter = OneShotFakeOpenWakeWordAdapter([self._wake_event()])
            recording_path = Path(temp_dir) / "command.wav"
            record_calls: list[Path] = []
            options = WakeLoopOptions(
                device_id=0,
                server_url="http://127.0.0.1:8766",
                wake_window_seconds=0.1,
                wake_phrases=["贾维斯"],
                max_seconds=1.0,
                silence_seconds=0.1,
                sample_rate=16000,
                channels=1,
                recording_dir=Path(temp_dir),
            )

            def fake_record(path, **_kwargs):
                record_calls.append(Path(path))
                return SimpleNamespace(path=Path(path), duration_seconds=0.4, stop_reason="silence_after_speech")

            def _build_recording_path(_dir):
                return recording_path

            def record_oww_cmd(**kwargs):
                return _record_openwakeword_command(
                    record_func=fake_record,
                    build_recording_path_func=_build_recording_path,
                    **kwargs,
                )

            handle = start_openwakeword_listener(
                app=app,
                runtime_config=self._runtime_config(),
                bridge_runtime=bridge,
                logger=logger,
                debug=False,
                stop_event=stop_event,
                adapter_factory=lambda _config: adapter,
            )
            result = _run_openwakeword_turn_from_listener(
                app=app,
                options=options,
                listener=handle,
                logger=logger,
                debug=False,
                stop_event=stop_event,
                request_transcription_func=lambda _path, _url, mode=None: {"text": "打开记事本"},
                record_openwakeword_command=record_oww_cmd,
            )
            stop_event.set()
            stop_openwakeword_listener(handle)

        self.assertEqual(result.command_text, "打开记事本")
        self.assertEqual(len(record_calls), 1)
        self.assertEqual(bridge.bridge.state().accepted_count, 1)
        self.assertEqual(adapter.run_until_count, 1)
        self.assertEqual(adapter.run_count, 0)
        self.assertIn("openwakeword_bridge_decision accepted=true reason=accepted", logger.text)
        self.assertIn("command_record_start source=openwakeword", logger.text)

    def test_openwakeword_bridge_rejects_command_and_tts_active_events(self):
        import queue
        from xiaohuang.wake_runtime_service import OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime

        command_queue = queue.Queue()
        command_bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5, command_queue=command_queue)
        command_bridge.mark_command_started()
        command_decision = command_bridge.handle_event(self._wake_event())

        tts_queue = queue.Queue()
        tts_bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5, command_queue=tts_queue)
        tts_bridge.mark_tts_started()
        tts_decision = tts_bridge.handle_event(self._wake_event())

        self.assertFalse(command_decision.accepted)
        self.assertEqual(command_decision.reason, "command_active")
        self.assertTrue(command_queue.empty())
        self.assertFalse(tts_decision.accepted)
        self.assertEqual(tts_decision.reason, "tts_active")
        self.assertTrue(tts_queue.empty())

    def test_openwakeword_listener_error_logs_and_fallbacks_when_enabled(self):
        import threading
        from xiaohuang.wake_runtime_service import (
            OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime,
            start_openwakeword_listener as _start_openwakeword_listener,
        )

        app = FakeOverlayApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5)
        adapter = FailingOpenWakeWordAdapter("fake listener failed")

        handle = _start_openwakeword_listener(
            app=app,
            runtime_config=self._runtime_config(fallback_enabled=True),
            bridge_runtime=bridge,
            logger=logger,
            debug=False,
            stop_event=stop_event,
            adapter_factory=lambda _config: adapter,
        )
        handle.thread.join(timeout=1.0)

        self.assertFalse(handle.thread.is_alive())
        self.assertFalse(stop_event.is_set())
        self.assertEqual(handle.error_queue.get_nowait(), "fake listener failed")
        self.assertIn("openwakeword_listener_error error=fake listener failed", logger.text)
        self.assertIn("fallback_to_stt_text reason=fake listener failed", logger.text)

    def test_openwakeword_listener_error_safely_stops_when_fallback_disabled(self):
        import threading
        from xiaohuang.wake_runtime_service import (
            OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime,
            start_openwakeword_listener as _start_openwakeword_listener,
        )

        app = FakeOverlayApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5)
        adapter = FailingOpenWakeWordAdapter("fake listener failed")

        handle = _start_openwakeword_listener(
            app=app,
            runtime_config=self._runtime_config(fallback_enabled=False),
            bridge_runtime=bridge,
            logger=logger,
            debug=False,
            stop_event=stop_event,
            adapter_factory=lambda _config: adapter,
        )
        handle.thread.join(timeout=1.0)

        self.assertFalse(handle.thread.is_alive())
        self.assertTrue(stop_event.is_set())
        self.assertIn("openwakeword_listener_error error=fake listener failed", logger.text)
        self.assertNotIn("fallback_to_stt_text", logger.text)

    def test_command_recording_error_leaves_bridge_clean(self):
        from xiaohuang.wake_runtime_service import OpenWakeWordBridgeRuntime as _OpenWakeWordBridgeRuntime
        from voice_overlay import _record_openwakeword_command

        with tempfile.TemporaryDirectory() as temp_dir:
            app = FakeOverlayApp()
            bridge = _OpenWakeWordBridgeRuntime(cooldown_seconds=2.5)
            event = self._wake_event()
            options = WakeLoopOptions(
                device_id=0,
                server_url="http://127.0.0.1:8766",
                wake_window_seconds=0.1,
                wake_phrases=["贾维斯"],
                max_seconds=1.0,
                silence_seconds=0.1,
                sample_rate=16000,
                channels=1,
                recording_dir=Path(temp_dir),
            )

            def failing_record(_path, **_kwargs):
                raise RuntimeError("fake recorder failed")

            with self.assertRaises(RuntimeError):
                _record_openwakeword_command(
                    event=event,
                    app=app,
                    options=options,
                    bridge_runtime=bridge,
                    logger=FakeLogger(),
                    debug=False,
                    record_func=failing_record,
                    build_recording_path_func=lambda _dir: Path(temp_dir) / "command.wav",
                    request_transcription_func=lambda _path, _url, mode=None: {"text": "text"},
                )

        self.assertFalse(bridge.bridge.state().command_active)


class FakeOverlayApp:
    def __init__(self):
        self.states: list[tuple[str, str | None]] = []
        self.visible = False

    def thread_safe_set_state(self, state: str, detail: str | None = None) -> None:
        self.states.append((state, detail))

    def show_overlay(self) -> None:
        self.visible = True


class FakeOpenWakeWordAdapter:
    def __init__(self, events):
        self.events = list(events)
        self.stopped = False
        self.run_count = 0
        self.run_until_count = 0
        self.frames_read = 0

    def run_for_duration(self, _duration_seconds, on_event=None, debug=False):
        from xiaohuang.wake_engine_service import WakeEventStats

        self.stopped = False
        self.run_count += 1
        self.frames_read = len(self.events)
        for event in self.events:
            if self.stopped:
                break
            if on_event is not None:
                on_event(event)
        return WakeEventStats(
            raw_detections=len(self.events),
            coalesced_events=1 if self.events else 0,
            suppressed_detections=max(0, len(self.events) - 1),
            cooldown_seconds=2.5,
        )

    def run_until_stopped(
        self,
        stop_event,
        on_event=None,
        debug=False,
        on_status=None,
        status_interval_seconds=5.0,
    ):
        from xiaohuang.openwakeword_adapter import OpenWakeWordRuntimeStatus
        from xiaohuang.wake_engine_service import WakeEventStats

        self.stopped = False
        self.run_until_count += 1
        self.frames_read = len(self.events)
        if on_status is not None:
            on_status(
                OpenWakeWordRuntimeStatus(
                    frames_read=0,
                    max_label=None,
                    max_score=None,
                    raw_detections=0,
                    coalesced_events=0,
                    suppressed_detections=0,
                    model_labels=["hey_jarvis"],
                    device=0,
                    sample_rate=16000,
                    sensitivity=0.5,
                )
            )
        for event in self.events:
            if stop_event.is_set():
                break
            if on_event is not None:
                on_event(event)
        return WakeEventStats(
            raw_detections=len(self.events),
            coalesced_events=1 if self.events else 0,
            suppressed_detections=max(0, len(self.events) - 1),
            cooldown_seconds=2.5,
        )

    def stop(self):
        self.stopped = True

    def status(self):
        return SimpleNamespace(error=None, running=not self.stopped, ready=not self.stopped, model_loaded=True)


class OneShotFakeOpenWakeWordAdapter(FakeOpenWakeWordAdapter):
    def run_until_stopped(
        self,
        stop_event,
        on_event=None,
        debug=False,
        on_status=None,
        status_interval_seconds=5.0,
    ):
        result = super().run_until_stopped(
            stop_event,
            on_event=on_event,
            debug=debug,
            on_status=on_status,
            status_interval_seconds=status_interval_seconds,
        )
        self.events = []
        return result


class LoopingFakeOpenWakeWordAdapter(FakeOpenWakeWordAdapter):
    def __init__(self, events, *, stop_event):
        super().__init__(events)
        self.stop_event = stop_event

    def run_until_stopped(
        self,
        stop_event,
        on_event=None,
        debug=False,
        on_status=None,
        status_interval_seconds=5.0,
    ):
        result = super().run_until_stopped(
            stop_event,
            on_event=on_event,
            debug=debug,
            on_status=on_status,
            status_interval_seconds=status_interval_seconds,
        )
        self.stop_event.set()
        return result


class FailingOpenWakeWordAdapter(FakeOpenWakeWordAdapter):
    def __init__(self, error: str):
        super().__init__([])
        self.error = error

    def run_for_duration(self, _duration_seconds, on_event=None, debug=False):
        self.run_count += 1
        raise RuntimeError(self.error)

    def run_until_stopped(
        self,
        stop_event,
        on_event=None,
        debug=False,
        on_status=None,
        status_interval_seconds=5.0,
    ):
        self.run_until_count += 1
        raise RuntimeError(self.error)

    def status(self):
        return SimpleNamespace(error=self.error, running=False, ready=False, model_loaded=True)


class FakeLogger:
    def __init__(self):
        self.records: list[tuple[str, str]] = []

    @property
    def text(self) -> str:
        return "\n".join(message for _level, message in self.records)

    def info(self, *args, **_kwargs):
        self._record("info", *args)

    def warning(self, *args, **_kwargs):
        self._record("warning", *args)

    def error(self, *args, **_kwargs):
        self._record("error", *args)

    def exception(self, *args, **_kwargs):
        self._record("exception", *args)

    def _record(self, level: str, *args) -> None:
        if not args:
            message = ""
        else:
            message = str(args[0])
            if len(args) > 1:
                try:
                    message = message % args[1:]
                except Exception:
                    message = " ".join(str(arg) for arg in args)
        self.records.append((level, message))


class ManualClock:
    def __init__(self, current: float = 0.0):
        self.current = current

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class V12DOpenWakeWordAdapterTests(unittest.TestCase):
    def test_openwakeword_adapter_import_does_not_require_openwakeword(self):
        from xiaohuang import openwakeword_adapter

        self.assertTrue(hasattr(openwakeword_adapter, "OpenWakeWordAdapter"))

    def test_dependency_check_reports_missing_optional_dependencies(self):
        from xiaohuang.openwakeword_adapter import check_openwakeword_dependencies

        def fake_import(name):
            raise ImportError(f"{name} missing")

        status = check_openwakeword_dependencies(import_module=fake_import)

        self.assertFalse(status.openwakeword_installed)
        self.assertFalse(status.numpy_installed)
        self.assertFalse(status.sounddevice_installed)
        self.assertFalse(status.onnxruntime_available)
        self.assertFalse(status.ready_for_realtime_demo)
        self.assertTrue(any("openwakeword" in error for error in status.errors))

    def test_dependency_check_can_be_simulated_ready(self):
        from xiaohuang.openwakeword_adapter import check_openwakeword_dependencies

        def fake_import(name):
            return SimpleNamespace(__version__="1.0")

        status = check_openwakeword_dependencies(import_module=fake_import)

        self.assertTrue(status.openwakeword_installed)
        self.assertTrue(status.numpy_installed)
        self.assertTrue(status.sounddevice_installed)
        self.assertTrue(status.onnxruntime_available)
        self.assertTrue(status.ready_for_realtime_demo)
        self.assertEqual(status.errors, [])

    def test_adapter_initial_status(self):
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        adapter = OpenWakeWordAdapter(wake_phrase="贾维斯", sensitivity=0.6)
        status = adapter.status()

        self.assertEqual(status.engine_type, "openwakeword")
        self.assertFalse(status.running)
        self.assertFalse(status.ready)
        self.assertFalse(status.model_loaded)
        self.assertEqual(status.wake_phrase, "贾维斯")
        self.assertEqual(status.sensitivity, 0.6)
        self.assertIsNone(status.error)

    def test_adapter_start_stop_are_idempotent_with_injected_runtime(self):
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        load_count = {"model": 0}

        class FakeModel:
            def predict(self, frame):
                return {"hey_jarvis": 0.0}

        def model_factory(adapter):
            load_count["model"] += 1
            return FakeModel()

        adapter = OpenWakeWordAdapter(
            model_factory=model_factory,
            input_stream_factory=FakeInputStream,
            numpy_module=np,
        )

        adapter.stop()
        self.assertFalse(adapter.status().running)

        adapter.start()
        adapter.start()
        self.assertTrue(adapter.status().running)
        self.assertTrue(adapter.status().ready)
        self.assertEqual(load_count["model"], 1)

        adapter.stop()
        adapter.stop()
        self.assertFalse(adapter.status().running)
        self.assertFalse(adapter.status().ready)

    def test_adapter_run_for_duration_uses_coalescer_and_fake_audio(self):
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        FakeInputStream.instances.clear()
        predictions = [
            {"hey_jarvis": 0.90},
            {"hey_jarvis": 0.95},
            {"hey_jarvis": 0.96},
            {"alexa": 0.80},
        ]
        fake_model = FakePredictionModel(predictions)
        now = {"value": 0.0}

        def time_fn():
            now["value"] += 1.0
            return now["value"]

        events = []
        adapter = OpenWakeWordAdapter(
            wake_phrase="贾维斯",
            sensitivity=0.5,
            cooldown_seconds=2.5,
            model_factory=lambda adapter: fake_model,
            input_stream_factory=FakeInputStream,
            numpy_module=np,
            time_fn=time_fn,
        )

        stats = adapter.run_for_duration(8.0, on_event=events.append)

        self.assertEqual(adapter.frames_read, 4)
        self.assertEqual(stats.raw_detections, 4)
        self.assertEqual(stats.coalesced_events, 3)
        self.assertEqual(stats.suppressed_detections, 1)
        self.assertEqual([event.label for event in events], ["hey_jarvis", "hey_jarvis", "alexa"])
        self.assertEqual(len(events), stats.coalesced_events)
        self.assertEqual(events[0].wake_phrase, "贾维斯")
        self.assertEqual(events[0].engine_type, "openwakeword")
        self.assertFalse(adapter.status().running)
        self.assertTrue(FakeInputStream.instances[0].closed)

    def test_adapter_run_for_duration_can_disable_coalescing(self):
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        fake_model = FakePredictionModel([{"hey_jarvis": 0.9}, {"hey_jarvis": 0.95}])
        now = {"value": 0.0}

        def time_fn():
            now["value"] += 1.0
            return now["value"]

        events = []
        adapter = OpenWakeWordAdapter(
            sensitivity=0.5,
            cooldown_seconds=2.5,
            coalesce=False,
            model_factory=lambda adapter: fake_model,
            input_stream_factory=FakeInputStream,
            numpy_module=np,
            time_fn=time_fn,
        )

        stats = adapter.run_for_duration(4.0, on_event=events.append)

        self.assertEqual(stats.raw_detections, 2)
        self.assertEqual(stats.coalesced_events, 2)
        self.assertEqual(stats.suppressed_detections, 0)
        self.assertEqual(len(events), 2)

    def test_adapter_run_until_stopped_uses_one_stream_and_reports_status(self):
        import threading
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        FakeInputStream.instances.clear()
        stop_event = threading.Event()
        predictions = [
            {"hey_jarvis": 0.10},
            {"hey_jarvis": 0.93},
            {"hey_jarvis": 0.20},
        ]

        class StopAfterPredictionModel:
            model_names = ["hey_jarvis"]

            def __init__(self):
                self.calls = 0

            def predict(self, _frame):
                prediction = predictions[min(self.calls, len(predictions) - 1)]
                self.calls += 1
                if self.calls >= len(predictions):
                    stop_event.set()
                return prediction

        now = {"value": 0.0}

        def time_fn():
            now["value"] += 1.0
            return now["value"]

        statuses = []
        events = []
        adapter = OpenWakeWordAdapter(
            wake_phrase="贾维斯",
            sensitivity=0.5,
            cooldown_seconds=2.5,
            model_factory=lambda adapter: StopAfterPredictionModel(),
            input_stream_factory=FakeInputStream,
            numpy_module=np,
            time_fn=time_fn,
        )

        stats = adapter.run_until_stopped(
            stop_event,
            on_event=events.append,
            on_status=statuses.append,
            status_interval_seconds=1.0,
        )

        self.assertEqual(len(FakeInputStream.instances), 1)
        self.assertTrue(FakeInputStream.instances[0].closed)
        self.assertEqual(adapter.frames_read, 3)
        self.assertFalse(adapter.status().running)
        self.assertEqual(stats.raw_detections, 1)
        self.assertEqual([event.label for event in events], ["hey_jarvis"])
        self.assertTrue(any(status.model_labels == ["hey_jarvis"] for status in statuses))
        self.assertTrue(any(status.max_label == "hey_jarvis" for status in statuses))

    def test_adapter_run_for_duration_exception_releases_stream(self):
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        FakeInputStream.instances.clear()
        adapter = OpenWakeWordAdapter(
            model_factory=lambda adapter: FakePredictionModel([{"hey_jarvis": 0.9}]),
            input_stream_factory=lambda **kwargs: RaisingInputStream(RuntimeError("stream failed"), **kwargs),
            numpy_module=np,
        )

        with self.assertRaises(RuntimeError):
            adapter.run_for_duration(2.0)

        status = adapter.status()
        self.assertFalse(status.running)
        self.assertTrue(status.model_loaded)
        self.assertIn("stream failed", status.error)
        self.assertTrue(FakeInputStream.instances[0].closed)

    def test_adapter_run_for_duration_keyboard_interrupt_releases_stream(self):
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        FakeInputStream.instances.clear()
        adapter = OpenWakeWordAdapter(
            model_factory=lambda adapter: FakePredictionModel([{"hey_jarvis": 0.9}]),
            input_stream_factory=lambda **kwargs: RaisingInputStream(KeyboardInterrupt(), **kwargs),
            numpy_module=np,
        )

        with self.assertRaises(KeyboardInterrupt):
            adapter.run_for_duration(2.0)

        status = adapter.status()
        self.assertFalse(status.running)
        self.assertTrue(status.model_loaded)
        self.assertIsNone(status.error)
        self.assertTrue(FakeInputStream.instances[0].closed)

    def test_adapter_two_fake_rounds_do_not_leave_running_true(self):
        import numpy as np
        from xiaohuang.openwakeword_adapter import OpenWakeWordAdapter

        FakeInputStream.instances.clear()
        fake_model = FakePredictionModel([{"hey_jarvis": 0.9}, {"hey_jarvis": 0.9}])
        now = {"value": 0.0}

        def time_fn():
            now["value"] += 1.0
            return now["value"]

        adapter = OpenWakeWordAdapter(
            model_factory=lambda adapter: fake_model,
            input_stream_factory=FakeInputStream,
            numpy_module=np,
            time_fn=time_fn,
        )

        first_stats = adapter.run_for_duration(2.0)
        first_status = adapter.status()
        adapter.stop()
        second_stats = adapter.run_for_duration(2.0)
        second_status = adapter.status()
        adapter.stop()

        self.assertEqual(first_stats.raw_detections, 1)
        self.assertEqual(second_stats.raw_detections, 1)
        self.assertFalse(first_status.running)
        self.assertFalse(second_status.running)
        self.assertFalse(adapter.status().running)
        self.assertEqual(len(FakeInputStream.instances), 2)
        self.assertTrue(all(stream.closed for stream in FakeInputStream.instances))


class FakePredictionModel:
    def __init__(self, predictions):
        self._predictions = list(predictions)

    def predict(self, frame):
        if not self._predictions:
            return {"hey_jarvis": 0.0}
        return self._predictions.pop(0)


class FakeInputStream:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.read_count = 0
        FakeInputStream.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True
        return False

    def read(self, blocksize):
        self.read_count += 1
        return [[0] for _ in range(blocksize)], False


class RaisingInputStream(FakeInputStream):
    def __init__(self, exception, **kwargs):
        self.exception = exception
        super().__init__(**kwargs)

    def read(self, blocksize):
        self.read_count += 1
        raise self.exception


class FakeSafetyAdapter:
    instances = []

    def __init__(self, config):
        self.config = config
        self.frames_read = 0
        self._running = False
        self._error = None
        FakeSafetyAdapter.instances.append(self)

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def status(self):
        return SimpleNamespace(
            running=self._running,
            ready=self._running and self._error is None,
            model_loaded=True,
            error=self._error,
        )

    def run_for_duration(self, duration_seconds, on_event=None, debug=False):
        from xiaohuang.wake_engine_service import WakeEventStats

        self.frames_read = 3
        self._running = False
        return WakeEventStats(
            raw_detections=2,
            coalesced_events=1,
            suppressed_detections=1,
            cooldown_seconds=self.config.cooldown_seconds,
        )


class V12BWakeEngineDemoTests(unittest.TestCase):
    def test_wake_engine_demo_help_runs(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/wake_engine_demo.py", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--check-install", result.stdout)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--cooldown-seconds", result.stdout)
        self.assertIn("--no-coalesce", result.stdout)
        self.assertIn("--safety-check", result.stdout)
        self.assertIn("--repeat", result.stdout)
        self.assertIn("--gap-seconds", result.stdout)

    def test_wake_engine_demo_check_install_command_runs(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/wake_engine_demo.py", "--check-install"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("V1.2B openWakeWord demo install check", result.stdout)
        self.assertIn("ready_for_realtime_demo=", result.stdout)

    def test_wake_engine_demo_check_install_does_not_fail_when_optional_dependency_missing(self):
        import wake_engine_demo

        def fake_import(name):
            if name == "openwakeword":
                raise ImportError("not installed")
            return SimpleNamespace(__version__="1.0")

        statuses = wake_engine_demo.collect_install_statuses(import_module=fake_import)

        openwakeword_status = [status for status in statuses if status.name == "openwakeword"][0]
        self.assertFalse(openwakeword_status.installed)
        self.assertIn("Missing optional dependency: openwakeword", openwakeword_status.error)

    def test_wake_engine_demo_dry_run_does_not_require_openwakeword(self):
        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                "scripts/wake_engine_demo.py",
                "--dry-run",
                "--engine",
                "openwakeword",
                "--wake-phrase",
                "贾维斯",
                "--cooldown-seconds",
                "2.5",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("dry_run=true", result.stdout)
        self.assertIn("will_load_model=false", result.stdout)
        self.assertIn("will_open_microphone=false", result.stdout)
        self.assertIn("cooldown_seconds=2.5", result.stdout)
        self.assertIn("coalesce_events=true", result.stdout)
        self.assertIn("wake_phrase=贾维斯", result.stdout)

    def test_wake_engine_demo_parse_args(self):
        import wake_engine_demo

        args = wake_engine_demo.parse_args(
            [
                "--engine",
                "openwakeword",
                "--model-name",
                "hey jarvis",
                "--device",
                "0",
                "--duration-seconds",
                "3",
                "--chunk-ms",
                "80",
                "--sensitivity",
                "0.6",
                "--cooldown-seconds",
                "1.5",
                "--no-coalesce",
            ]
        )
        config = wake_engine_demo.build_demo_config(args)

        self.assertEqual(config.engine, "openwakeword")
        self.assertEqual(config.model_name, "hey jarvis")
        self.assertEqual(config.device, 0)
        self.assertEqual(config.duration_seconds, 3.0)
        self.assertEqual(config.chunk_samples, 1280)
        self.assertEqual(config.sensitivity, 0.6)
        self.assertEqual(config.cooldown_seconds, 1.5)
        self.assertFalse(config.coalesce_events)

    def test_wake_engine_demo_parse_safety_check_args(self):
        import wake_engine_demo

        args = wake_engine_demo.parse_args(
            [
                "--safety-check",
                "--repeat",
                "3",
                "--gap-seconds",
                "0.25",
            ]
        )

        self.assertTrue(args.safety_check)
        self.assertEqual(args.repeat, 3)
        self.assertEqual(args.gap_seconds, 0.25)

    def test_wake_engine_demo_safety_check_fake_two_rounds(self):
        from contextlib import redirect_stdout
        import io
        import wake_engine_demo

        FakeSafetyAdapter.instances.clear()
        config = wake_engine_demo.build_demo_config(
            wake_engine_demo.parse_args(["--safety-check", "--duration-seconds", "0.1"])
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = wake_engine_demo.collect_safety_check_result(
                config,
                repeat=2,
                gap_seconds=0,
                adapter_factory=FakeSafetyAdapter,
                sleep_func=lambda seconds: None,
            )

        text = output.getvalue()
        self.assertTrue(result.all_rounds_completed)
        self.assertTrue(result.microphone_released)
        self.assertEqual(result.errors, 0)
        self.assertEqual(len(FakeSafetyAdapter.instances), 2)
        self.assertIn("safety_check=true", text)
        self.assertIn("round=1 started=true", text)
        self.assertIn("round=2 stopped=true", text)
        self.assertIn("round=1 frames=3", text)
        self.assertIn("round=2 raw_detections=2", text)
        self.assertIn("round=2 suppressed_detections=1", text)
        self.assertIn("status_after_stop running=false", text)
        self.assertIn("all_rounds_completed=true", text)
        self.assertIn("microphone_released=true", text)
        self.assertIn("errors=0", text)

    def test_wake_event_coalescer_accepts_first_label_event(self):
        import wake_engine_demo

        coalescer = wake_engine_demo.WakeEventCoalescer(cooldown_seconds=2.5)

        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0))

    def test_wake_event_coalescer_suppresses_same_label_inside_cooldown(self):
        import wake_engine_demo

        coalescer = wake_engine_demo.WakeEventCoalescer(cooldown_seconds=2.5)
        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0))

        self.assertFalse(coalescer.accept("hey_jarvis", now=11.0))
        self.assertAlmostEqual(coalescer.remaining_seconds("hey_jarvis", now=11.0), 1.5)

    def test_wake_event_coalescer_accepts_same_label_after_cooldown(self):
        import wake_engine_demo

        coalescer = wake_engine_demo.WakeEventCoalescer(cooldown_seconds=2.5)
        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0))

        self.assertTrue(coalescer.accept("hey_jarvis", now=12.6))

    def test_wake_event_coalescer_uses_per_label_cooldown(self):
        import wake_engine_demo

        coalescer = wake_engine_demo.WakeEventCoalescer(cooldown_seconds=2.5)
        self.assertTrue(coalescer.accept("hey_jarvis", now=10.0))

        self.assertTrue(coalescer.accept("alexa", now=11.0))

    def test_wake_engine_demo_detection_summary_includes_coalesced_counts(self):
        from contextlib import redirect_stdout
        import io
        import wake_engine_demo

        config = wake_engine_demo.build_demo_config(wake_engine_demo.parse_args(["--cooldown-seconds", "2.5"]))
        stats = wake_engine_demo.DetectionStats(
            frames=373,
            raw_detections=29,
            coalesced_events=3,
            suppressed_detections=26,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            wake_engine_demo.print_detection_summary(stats, config)

        text = output.getvalue()
        self.assertIn("frames=373", text)
        self.assertIn("raw_detections=29", text)
        self.assertIn("coalesced_events=3", text)
        self.assertIn("suppressed_detections=26", text)
        self.assertIn("cooldown_seconds=2.5", text)


class V114CLaunchControlTests(unittest.TestCase):
    def setUp(self):
        import tray_app

        self._tray_app_write_log = tray_app.write_tray_log
        tray_app.write_tray_log = lambda *args, **kwargs: None

    def tearDown(self):
        import tray_app

        tray_app.write_tray_log = self._tray_app_write_log

    def test_build_start_command_uses_start_script_and_config_path(self):
        from xiaohuang.launch_control_service import build_start_command

        command = build_start_command(
            Path(r"E:\Projects\xiaohuang"),
            Path(r"C:\Users\tester\.xiaohuang\config_settings_ui_test.json"),
            powershell_executable="pwsh.exe",
        )

        joined = " ".join(command)
        self.assertIsInstance(command, list)
        self.assertEqual(command[0], "pwsh.exe")
        self.assertIn("start_xiaohuang.ps1", joined)
        self.assertIn("-File", command)
        self.assertIn("-ConfigPath", command)
        self.assertIn(r"C:\Users\tester\.xiaohuang\config_settings_ui_test.json", command)
        self.assertNotIn("sk-", joined)
        self.assertNotIn("DEEPSEEK_API_KEY=", joined)

    def test_build_stop_command_uses_stop_script_and_stops_stt(self):
        from xiaohuang.launch_control_service import build_stop_command

        command = build_stop_command(Path(r"E:\Projects\xiaohuang"), powershell_executable="pwsh.exe")

        joined = " ".join(command)
        self.assertIsInstance(command, list)
        self.assertEqual(command[0], "pwsh.exe")
        self.assertIn("stop_xiaohuang.ps1", joined)
        self.assertIn("-File", command)
        self.assertIn("-StopSttServer", command)

    def test_build_restart_commands_stop_before_start(self):
        from xiaohuang.launch_control_service import build_restart_commands

        commands = build_restart_commands(
            Path(r"E:\Projects\xiaohuang"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            powershell_executable="pwsh.exe",
        )

        self.assertEqual(len(commands), 2)
        self.assertIn("stop_xiaohuang.ps1", " ".join(commands[0]))
        self.assertIn("start_xiaohuang.ps1", " ".join(commands[1]))

    def test_status_summary_handles_no_processes(self):
        from xiaohuang.launch_control_service import summarize_process_status

        status = summarize_process_status([])

        self.assertFalse(status.stt_server_running)
        self.assertFalse(status.voice_overlay_running)
        self.assertFalse(status.any_running)
        self.assertEqual(status.process_count, 0)

    def test_fully_running_requires_stt_and_overlay(self):
        from xiaohuang.launch_control_service import ProcessStatus

        status = ProcessStatus(stt_server_running=True, voice_overlay_running=True, process_count=2)

        self.assertTrue(status.is_fully_running)
        self.assertFalse(status.is_partial)

    def test_voice_overlay_only_is_partial_not_fully_running(self):
        from xiaohuang.launch_control_service import ProcessStatus

        status = ProcessStatus(stt_server_running=False, voice_overlay_running=True, process_count=1)

        self.assertFalse(status.is_fully_running)
        self.assertTrue(status.is_partial)

    def test_partial_state_start_sequence_stops_then_starts(self):
        from xiaohuang.launch_control_service import ProcessStatus, build_start_sequence_for_status

        commands = build_start_sequence_for_status(
            ProcessStatus(stt_server_running=False, voice_overlay_running=True, process_count=1),
            Path(r"E:\Projects\xiaohuang"),
            Path(r"C:\Users\tester\.xiaohuang\config_settings_ui_test.json"),
            powershell_executable="pwsh.exe",
        )

        self.assertEqual(len(commands), 2)
        self.assertIn("stop_xiaohuang.ps1", " ".join(commands[0]))
        self.assertIn("-StopSttServer", commands[0])
        self.assertIn("start_xiaohuang.ps1", " ".join(commands[1]))
        self.assertIn("-ConfigPath", commands[1])

    def test_fully_running_start_sequence_skips_start(self):
        from xiaohuang.launch_control_service import ProcessStatus, build_start_sequence_for_status

        commands = build_start_sequence_for_status(
            ProcessStatus(stt_server_running=True, voice_overlay_running=True, process_count=2),
            Path(r"E:\Projects\xiaohuang"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            powershell_executable="pwsh.exe",
        )

        self.assertEqual(commands, [])

    def test_classify_voice_overlay_absolute_path(self):
        from xiaohuang.launch_control_service import classify_process_command_line

        result = classify_process_command_line(
            r'"F:\for_xiaohuang\conda310\python.exe" "E:\Projects\xiaohuang\scripts\voice_overlay.py"',
            Path(r"E:\Projects\xiaohuang"),
        )

        self.assertEqual(result, "voice_overlay")

    def test_classify_voice_overlay_relative_backslash_path(self):
        from xiaohuang.launch_control_service import classify_process_command_line

        result = classify_process_command_line(
            r'python.exe scripts\voice_overlay.py --config C:\Users\tester\.xiaohuang\config.json',
            Path(r"E:\Projects\xiaohuang"),
        )

        self.assertEqual(result, "voice_overlay")

    def test_classify_voice_overlay_forward_slash_path(self):
        from xiaohuang.launch_control_service import classify_process_command_line

        result = classify_process_command_line(
            "python.exe E:/Projects/xiaohuang/scripts/voice_overlay.py --debug",
            Path(r"E:\Projects\xiaohuang"),
        )

        self.assertEqual(result, "voice_overlay")

    def test_classify_voice_overlay_under_pythonw(self):
        from xiaohuang.launch_control_service import classify_process_command_line

        result = classify_process_command_line(
            r'pythonw.exe "E:/Projects/xiaohuang/scripts/voice_overlay.py" --resident-hidden',
            Path(r"E:\Projects\xiaohuang"),
        )

        self.assertEqual(result, "voice_overlay")

    def test_classify_stt_server_uses_same_path_normalization(self):
        from xiaohuang.launch_control_service import classify_process_command_line

        result = classify_process_command_line(
            "python.exe E:/Projects/xiaohuang/scripts/stt_server.py --port 8766",
            Path(r"E:\Projects\xiaohuang"),
        )

        self.assertEqual(result, "stt_server")

    def test_run_command_uses_shell_false(self):
        import tray_app

        calls = []

        class FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return FakeResult()

        original_run = tray_app.subprocess.run
        original_show_message = tray_app.show_message
        try:
            tray_app.subprocess.run = fake_run
            tray_app.show_message = lambda *args, **kwargs: None
            ok = tray_app._run_command(["pwsh.exe", "-File", "x.ps1"], "test", project_root=PROJECT_ROOT)
        finally:
            tray_app.subprocess.run = original_run
            tray_app.show_message = original_show_message

        self.assertTrue(ok)
        self.assertEqual(calls[0][1]["shell"], False)
        self.assertEqual(calls[0][1]["cwd"], str(PROJECT_ROOT))

    def test_wait_until_ready_returns_true_when_processes_and_health_ready(self):
        from xiaohuang.launch_control_service import (
            HealthCheckResult,
            XiaoHuangProcess,
            wait_until_ready,
        )

        polls = []
        result = wait_until_ready(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=1,
            process_detector=lambda root: [
                XiaoHuangProcess(1, "stt_server"),
                XiaoHuangProcess(2, "voice_overlay"),
            ],
            health_checker=lambda url: HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
            on_poll=polls.append,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ready")
        self.assertEqual(polls, ["readiness poll stt=True overlay=True health=ready model_loaded=True"])

    def test_status_control_and_wait_use_same_detected_processes(self):
        from xiaohuang.launch_control_service import (
            HealthCheckResult,
            parse_process_rows,
            summarize_process_status,
            wait_until_ready,
        )
        from xiaohuang.status_control_service import ConfigSummary, READY, compute_status

        project_root = Path(r"E:\Projects\xiaohuang")
        processes = parse_process_rows(
            [
                {"ProcessId": 10, "CommandLine": r'python.exe scripts\stt_server.py --port 8766'},
                {"ProcessId": 11, "CommandLine": r'pythonw.exe "E:/Projects/xiaohuang/scripts/voice_overlay.py"'},
            ],
            project_root,
        )
        health = HealthCheckResult(True, "ok=True status=ready model_loaded=True")

        panel_status = compute_status(
            summarize_process_status(processes),
            health,
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        wait_result = wait_until_ready(
            project_root,
            timeout_seconds=1,
            process_detector=lambda root: processes,
            health_checker=lambda url: health,
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
        )

        self.assertEqual(panel_status.overall_status, READY)
        self.assertTrue(panel_status.overlay_running)
        self.assertTrue(wait_result.ok)
        self.assertTrue(wait_result.status.voice_overlay_running)

    def test_wait_until_ready_eventually_succeeds_after_health_failure(self):
        from xiaohuang.launch_control_service import (
            HealthCheckResult,
            XiaoHuangProcess,
            wait_until_ready,
        )

        now = [0.0]
        health_results = [
            HealthCheckResult(False, "health_unavailable"),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
        ]

        def sleep(seconds):
            now[0] += seconds

        def health_checker(url):
            return health_results.pop(0)

        result = wait_until_ready(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=2,
            poll_interval_seconds=0.5,
            process_detector=lambda root: [
                XiaoHuangProcess(1, "stt_server"),
                XiaoHuangProcess(2, "voice_overlay"),
            ],
            health_checker=health_checker,
            monotonic=lambda: now[0],
            sleeper=sleep,
        )

        self.assertTrue(result.ok)

    def test_wait_until_ready_times_out_with_reason(self):
        from xiaohuang.launch_control_service import HealthCheckResult, wait_until_ready

        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        result = wait_until_ready(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=1,
            poll_interval_seconds=0.5,
            process_detector=lambda root: [],
            health_checker=lambda url: HealthCheckResult(False, "health_unavailable"),
            monotonic=lambda: now[0],
            sleeper=sleep,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "timeout_stt_server_missing")

    def test_wait_until_ready_does_not_treat_command_returncode_as_ready(self):
        from xiaohuang.launch_control_service import HealthCheckResult, wait_until_ready

        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        result = wait_until_ready(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=1,
            poll_interval_seconds=0.5,
            process_detector=lambda root: [],
            health_checker=lambda url: HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            monotonic=lambda: now[0],
            sleeper=sleep,
        )

        self.assertFalse(result.ok)
        self.assertNotEqual(result.reason, "ready")

    def test_wait_until_ready_does_not_timeout_overlay_missing_when_overlay_exists(self):
        from xiaohuang.launch_control_service import (
            HealthCheckResult,
            parse_process_rows,
            wait_until_ready,
        )

        project_root = Path(r"E:\Projects\xiaohuang")
        processes = parse_process_rows(
            [
                {"ProcessId": 20, "CommandLine": "python.exe E:/Projects/xiaohuang/scripts/stt_server.py"},
                {"ProcessId": 21, "CommandLine": "pythonw.exe E:/Projects/xiaohuang/scripts/voice_overlay.py"},
            ],
            project_root,
        )

        result = wait_until_ready(
            project_root,
            timeout_seconds=1,
            process_detector=lambda root: processes,
            health_checker=lambda url: HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertNotEqual(result.reason, "timeout_voice_overlay_missing")

    def test_readiness_poll_callback_does_not_require_real_log_file(self):
        from xiaohuang.launch_control_service import (
            HealthCheckResult,
            XiaoHuangProcess,
            wait_until_ready,
        )

        polls = []
        result = wait_until_ready(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=1,
            process_detector=lambda root: [
                XiaoHuangProcess(1, "stt_server"),
                XiaoHuangProcess(2, "voice_overlay"),
            ],
            health_checker=lambda url: HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
            on_poll=polls.append,
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(polls), 1)

    def test_wait_until_stopped_returns_true_when_processes_gone(self):
        from xiaohuang.launch_control_service import wait_until_stopped

        result = wait_until_stopped(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=1,
            process_detector=lambda root: [],
            monotonic=lambda: 0.0,
            sleeper=lambda seconds: None,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "stopped")

    def test_wait_until_stopped_times_out_when_processes_remain(self):
        from xiaohuang.launch_control_service import XiaoHuangProcess, wait_until_stopped

        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        result = wait_until_stopped(
            Path(r"E:\Projects\xiaohuang"),
            timeout_seconds=1,
            poll_interval_seconds=0.5,
            process_detector=lambda root: [XiaoHuangProcess(1, "voice_overlay")],
            monotonic=lambda: now[0],
            sleeper=sleep,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "timeout_processes_still_running")

    def test_operation_guard_blocks_duplicate_operation(self):
        import tray_app

        guard = tray_app.OperationGuard()
        started, current = guard.begin("启动")
        second_started, second_current = guard.begin("重启")

        self.assertTrue(started)
        self.assertEqual(current, "启动")
        self.assertFalse(second_started)
        self.assertEqual(second_current, "启动")
        guard.finish()
        self.assertIsNone(guard.current_operation)

    def test_guarded_start_success_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message
        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "启动",
                lambda: tray_app.OperationResult("ok", "ready"),
                guard=guard,
            )
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_guarded_start_timeout_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message
        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "启动",
                lambda: tray_app.OperationResult("timeout", "not ready", error=True),
                guard=guard,
            )
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_guarded_start_exception_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message

        def boom():
            raise RuntimeError("boom")

        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation("启动", boom, guard=guard)
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_guarded_stop_success_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message
        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "停止",
                lambda: tray_app.OperationResult("ok", "stopped"),
                guard=guard,
            )
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_guarded_stop_error_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message
        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "停止",
                lambda: tray_app.OperationResult("stop failed", "timeout", error=True),
                guard=guard,
            )
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_guarded_restart_success_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message
        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "重启",
                lambda: tray_app.OperationResult("ok", "ready"),
                guard=guard,
            )
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_guarded_restart_error_releases_busy_flag(self):
        import tray_app

        guard = tray_app.OperationGuard()
        original_show_message = tray_app.show_message
        try:
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "重启",
                lambda: tray_app.OperationResult("restart failed", "timeout", error=True),
                guard=guard,
            )
        finally:
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_start_readiness_success_releases_even_if_process_still_running(self):
        import tray_app
        from xiaohuang.launch_control_service import ProcessStatus

        class FakeProcess:
            pid = 1234

            def poll(self):
                return None

        guard = tray_app.OperationGuard()
        original_get_status = tray_app.get_process_status
        original_launch = tray_app._launch_command_async
        original_wait_ready = tray_app._wait_ready_result
        original_log_async = tray_app._log_async_process_summary
        original_show_message = tray_app.show_message
        try:
            tray_app.get_process_status = lambda **kwargs: ProcessStatus(False, False, 0)
            tray_app._launch_command_async = lambda *args, **kwargs: FakeProcess()
            tray_app._wait_ready_result = lambda *args, **kwargs: tray_app.OperationResult("ready", "ready")
            tray_app._log_async_process_summary = lambda *args, **kwargs: None
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app._execute_guarded_operation(
                "启动",
                tray_app.start_xiaohuang,
                Path(r"C:\Users\tester\.xiaohuang\config.json"),
                guard=guard,
            )
        finally:
            tray_app.get_process_status = original_get_status
            tray_app._launch_command_async = original_launch
            tray_app._wait_ready_result = original_wait_ready
            tray_app._log_async_process_summary = original_log_async
            tray_app.show_message = original_show_message

        self.assertIsNone(guard.current_operation)

    def test_restart_order_is_stop_start_wait_ready(self):
        import tray_app

        events = []

        original_run_command = tray_app._run_command
        original_launch_command = tray_app._launch_command_async
        original_wait_stopped = tray_app._wait_stopped_result
        original_wait_ready = tray_app._wait_ready_result
        original_log_async = tray_app._log_async_process_summary
        original_show_message = tray_app.show_message
        original_sleep = tray_app.time.sleep
        try:
            tray_app._run_command = lambda command, label, **kwargs: events.append(label) or True
            tray_app._launch_command_async = lambda command, label, **kwargs: events.append(label) or object()
            tray_app._wait_stopped_result = lambda message, **kwargs: events.append("wait_stopped") or tray_app.OperationResult("ok", "ok")
            tray_app._wait_ready_result = lambda message, **kwargs: events.append("wait_ready") or tray_app.OperationResult("ok", "ok")
            tray_app._log_async_process_summary = lambda *args, **kwargs: None
            tray_app.show_message = lambda *args, **kwargs: None
            tray_app.time.sleep = lambda seconds: None
            tray_app.restart_xiaohuang(Path(r"C:\Users\tester\.xiaohuang\config.json"), project_root=Path(r"E:\Projects\xiaohuang"))
        finally:
            tray_app._run_command = original_run_command
            tray_app._launch_command_async = original_launch_command
            tray_app._wait_stopped_result = original_wait_stopped
            tray_app._wait_ready_result = original_wait_ready
            tray_app._log_async_process_summary = original_log_async
            tray_app.show_message = original_show_message
            tray_app.time.sleep = original_sleep

        self.assertEqual(events, ["重启小黄：停止", "wait_stopped", "重启小黄：启动", "wait_ready"])

    def test_process_row_parser_detects_stt_and_overlay(self):
        from xiaohuang.launch_control_service import parse_process_rows, summarize_process_status

        rows = [
            {"ProcessId": 1001, "CommandLine": r'python E:\Projects\xiaohuang\scripts\stt_server.py --port 8766'},
            {"ProcessId": 1002, "CommandLine": r'python E:\Projects\xiaohuang\scripts\voice_overlay.py --config x.json'},
            {"ProcessId": 1003, "CommandLine": r'python E:\Projects\other\scripts\voice_overlay.py'},
        ]

        processes = parse_process_rows(rows, Path(r"E:\Projects\xiaohuang"))
        status = summarize_process_status(processes)

        self.assertEqual(len(processes), 2)
        self.assertTrue(status.stt_server_running)
        self.assertTrue(status.voice_overlay_running)

    def test_format_status_message_includes_basic_state_and_config(self):
        from xiaohuang.launch_control_service import ProcessStatus, format_status_message

        message = format_status_message(
            ProcessStatus(stt_server_running=True, voice_overlay_running=False, process_count=1),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
        )

        self.assertIn("V1.1.4C", message)
        self.assertIn("STT server: running", message)
        self.assertIn("Voice overlay: not detected", message)
        self.assertIn(r"C:\Users\tester\.xiaohuang\config.json", message)


class V114DAStatusControlTests(unittest.TestCase):
    def _control_panel_state(self):
        return {
            "closed": False,
            "active_operation": None,
            "last_operation": None,
            "last_elapsed": None,
            "last_error": None,
            "last_status": None,
            "refresh_in_progress": False,
            "pending_refresh": False,
            "refresh_generation": 0,
            "operation_completion_pending": False,
        }

    def _ready_panel_status(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, compute_status

        return compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

    def _not_running_panel_status(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, compute_status

        return compute_status(
            ProcessStatus(False, False, 0),
            HealthCheckResult(False, "health_unavailable:URLError"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

    def _partial_panel_status(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, compute_status

        return compute_status(
            ProcessStatus(True, False, 1),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

    def test_control_panel_help_runs(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "scripts/control_panel.py", "--help"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--config", result.stdout)
        self.assertIn("--refresh-interval", result.stdout)

    def test_control_panel_start_timeout_uses_ready_final_status_as_success(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, ControlOperationResult, compute_status

        final_status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        result = control_panel.resolve_operation_result_after_final_status("启动", timeout, final_status)

        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual(result.title, "小黄已就绪")
        self.assertNotIn("timeout_voice_overlay_missing", result.message)

    def test_control_panel_restart_timeout_uses_ready_final_status_as_success(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, ControlOperationResult, compute_status

        final_status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        timeout = ControlOperationResult(
            False,
            "重启未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        result = control_panel.resolve_operation_result_after_final_status("重启", timeout, final_status)

        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual(result.title, "重启完成")
        self.assertNotIn("timeout_voice_overlay_missing", result.message)

    def test_control_panel_restart_timeout_uses_rendered_ready_status_as_success(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, ControlOperationResult, compute_status

        summary = ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True)
        stale_final_status = compute_status(
            ProcessStatus(True, False, 1),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            summary,
        )
        rendered_ready_status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            summary,
        )
        timeout = ControlOperationResult(
            False,
            "重启未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        result = control_panel.resolve_operation_result_after_statuses(
            "重启",
            timeout,
            [stale_final_status, rendered_ready_status],
        )

        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual(result.title, "重启完成")

    def test_control_panel_restart_ready_result_does_not_call_showerror(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, ControlOperationResult, compute_status

        final_status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        timeout = ControlOperationResult(
            False,
            "重启未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )
        calls = []
        fake_messagebox = SimpleNamespace(
            showinfo=lambda title, message: calls.append(("info", title, message)),
            showerror=lambda title, message: calls.append(("error", title, message)),
        )

        result = control_panel.resolve_operation_result_after_final_status("重启", timeout, final_status)
        control_panel.show_operation_result(fake_messagebox, result)

        self.assertEqual([call[0] for call in calls], ["info"])
        self.assertNotIn("error", [call[0] for call in calls])

    def test_control_panel_start_timeout_stays_error_when_final_status_partial(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, ControlOperationResult, compute_status

        final_status = compute_status(
            ProcessStatus(True, False, 1),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        result = control_panel.resolve_operation_result_after_final_status("启动", timeout, final_status)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout_voice_overlay_missing")
        self.assertIn("timeout_voice_overlay_missing", result.message)

    def test_control_panel_restart_timeout_stays_error_when_final_status_not_running(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, ControlOperationResult, compute_status

        final_status = compute_status(
            ProcessStatus(False, False, 0),
            HealthCheckResult(False, "health_unavailable:URLError"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        timeout = ControlOperationResult(
            False,
            "重启未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        result = control_panel.resolve_operation_result_after_final_status("重启", timeout, final_status)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout_voice_overlay_missing")
        self.assertIn("timeout_voice_overlay_missing", result.message)

    def test_control_panel_ready_status_clears_stale_timeout_last_error(self):
        import control_panel
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, compute_status

        final_status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        error = control_panel.clear_ready_state_error("timeout_voice_overlay_missing", final_status)

        self.assertIsNone(error)

    def test_control_panel_request_refresh_does_not_start_second_worker_when_busy(self):
        import control_panel

        state = self._control_panel_state()
        state["refresh_in_progress"] = True
        workers = []
        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=lambda **kwargs: self._not_running_panel_status(),
            render=lambda status: None,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: workers.append((target, name)),
        )

        started = controller.request()

        self.assertFalse(started)
        self.assertEqual(workers, [])
        self.assertTrue(state["pending_refresh"])

    def test_control_panel_refresh_completion_releases_in_progress(self):
        import control_panel

        state = self._control_panel_state()
        state["refresh_in_progress"] = True
        rendered = []
        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=lambda **kwargs: self._not_running_panel_status(),
            render=rendered.append,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: target(),
        )

        controller.apply_result(control_panel.StatusRefreshResult(0, self._not_running_panel_status()))

        self.assertFalse(state["refresh_in_progress"])
        self.assertEqual(len(rendered), 1)

    def test_control_panel_closed_refresh_result_does_not_render(self):
        import control_panel

        state = self._control_panel_state()
        state["closed"] = True
        state["refresh_in_progress"] = True
        rendered = []
        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=lambda **kwargs: self._not_running_panel_status(),
            render=rendered.append,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: target(),
        )

        controller.apply_result(control_panel.StatusRefreshResult(0, self._not_running_panel_status()))

        self.assertFalse(state["refresh_in_progress"])
        self.assertEqual(rendered, [])

    def test_control_panel_refresh_exception_becomes_redacted_last_error(self):
        import control_panel

        state = self._control_panel_state()

        def collect_status(**kwargs):
            raise RuntimeError("DEEPSEEK_API_KEY=sk-secret123456 token=abc123")

        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=collect_status,
            render=lambda status: None,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: target(),
        )

        self.assertTrue(controller.request())

        self.assertFalse(state["refresh_in_progress"])
        self.assertIn("RuntimeError", state["last_error"])
        self.assertNotIn("sk-secret123456", state["last_error"])
        self.assertNotIn("token=abc123", state["last_error"])

    def test_control_panel_stale_refresh_result_does_not_overwrite_ready_status(self):
        import control_panel

        ready = self._ready_panel_status()
        state = self._control_panel_state()
        state["last_status"] = ready
        state["refresh_in_progress"] = True
        state["refresh_generation"] = 2
        rendered = []
        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=lambda **kwargs: self._not_running_panel_status(),
            render=rendered.append,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: target(),
        )

        controller.apply_result(control_panel.StatusRefreshResult(1, self._not_running_panel_status()))

        self.assertFalse(state["refresh_in_progress"])
        self.assertEqual(state["last_status"], ready)
        self.assertEqual(rendered, [])

    def test_control_panel_operation_finish_uses_ready_final_status_without_timeout_popup(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        state = self._control_panel_state()
        state["active_operation"] = "重启"
        rendered = []
        buttons_enabled = []
        refresh_requests = []
        shown = []
        timeout = ControlOperationResult(
            False,
            "重启未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        control_panel.apply_operation_ui_result(
            state,
            control_panel.OperationUiResult("重启", timeout, self._ready_panel_status()),
            render=rendered.append,
            set_buttons_enabled=buttons_enabled.append,
            show_result=shown.append,
            request_status_refresh=lambda: refresh_requests.append(True) or True,
        )

        self.assertIsNone(state["active_operation"])
        self.assertIsNone(state["last_error"])
        self.assertEqual(buttons_enabled, [True])
        self.assertEqual(refresh_requests, [True])
        self.assertEqual(len(rendered), 1)
        self.assertTrue(shown[0].ok)
        self.assertIsNone(shown[0].error)
        self.assertNotIn("timeout_voice_overlay_missing", shown[0].message)

    def test_control_panel_start_worker_timeout_ready_final_status_does_not_show_error(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        state = self._control_panel_state()
        state["active_operation"] = "启动"
        shown = []
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        control_panel.apply_operation_ui_result(
            state,
            control_panel.OperationUiResult("启动", timeout, self._ready_panel_status()),
            render=lambda status: None,
            set_buttons_enabled=lambda enabled: None,
            show_result=shown.append,
            request_status_refresh=lambda: True,
        )

        self.assertTrue(shown[0].ok)
        self.assertIsNone(shown[0].error)
        self.assertIsNone(state["last_error"])

    def test_control_panel_start_timeout_partial_final_status_shows_error(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        state = self._control_panel_state()
        state["active_operation"] = "启动"
        shown = []
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        control_panel.apply_operation_ui_result(
            state,
            control_panel.OperationUiResult("启动", timeout, self._partial_panel_status()),
            render=lambda status: None,
            set_buttons_enabled=lambda enabled: None,
            show_result=shown.append,
            request_status_refresh=lambda: True,
        )

        self.assertFalse(shown[0].ok)
        self.assertEqual(shown[0].error, "timeout_voice_overlay_missing")
        self.assertEqual(state["last_error"], "timeout_voice_overlay_missing")

    def test_control_panel_periodic_ready_and_operation_timeout_ready_final_status_no_error(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        state = self._control_panel_state()
        state["active_operation"] = "启动"
        state["refresh_generation"] = 1
        rendered = []
        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=lambda **kwargs: self._ready_panel_status(),
            render=rendered.append,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: target(),
        )
        controller.apply_result(control_panel.StatusRefreshResult(1, self._ready_panel_status()))
        self.assertEqual(len(rendered), 1)

        shown = []
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )
        control_panel.apply_operation_ui_result(
            state,
            control_panel.OperationUiResult("启动", timeout, self._ready_panel_status()),
            render=rendered.append,
            set_buttons_enabled=lambda enabled: None,
            show_result=shown.append,
            request_status_refresh=lambda: True,
        )

        self.assertTrue(shown[0].ok)
        self.assertIsNone(shown[0].error)
        self.assertIsNone(state["last_error"])

    def test_control_panel_operation_completion_priority_skips_periodic_refresh_result(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        state = self._control_panel_state()
        state["active_operation"] = "启动"
        state["operation_completion_pending"] = True
        rendered = []
        controller = control_panel.StatusRefreshController(
            state=state,
            collect_status=lambda **kwargs: self._not_running_panel_status(),
            render=rendered.append,
            schedule_ui=lambda callback: callback(),
            start_worker=lambda target, name: target(),
        )

        controller.apply_result(control_panel.StatusRefreshResult(0, self._not_running_panel_status()))

        self.assertEqual(rendered, [])
        self.assertTrue(state["pending_refresh"])

        shown = []
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )
        control_panel.apply_operation_ui_result(
            state,
            control_panel.OperationUiResult("启动", timeout, self._ready_panel_status()),
            render=rendered.append,
            set_buttons_enabled=lambda enabled: None,
            show_result=shown.append,
            request_status_refresh=lambda: True,
        )

        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0].overall_status, "READY")
        self.assertTrue(shown[0].ok)

    def test_control_panel_closed_operation_result_does_not_update_ui(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        state = self._control_panel_state()
        state["closed"] = True
        state["active_operation"] = "启动"
        calls = []
        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )

        control_panel.apply_operation_ui_result(
            state,
            control_panel.OperationUiResult("启动", timeout, self._ready_panel_status()),
            render=lambda status: calls.append("render"),
            set_buttons_enabled=lambda enabled: calls.append("buttons"),
            show_result=lambda result: calls.append("show"),
            request_status_refresh=lambda: calls.append("refresh") or True,
        )

        self.assertEqual(calls, [])
        self.assertEqual(state["active_operation"], "启动")

    def test_control_panel_worker_collects_ready_final_status_after_timeout_retry(self):
        import control_panel
        from xiaohuang.status_control_service import ControlOperationResult

        timeout = ControlOperationResult(
            False,
            "启动未就绪",
            "启动命令已发出，但服务未就绪：timeout_voice_overlay_missing",
            90.0,
            "timeout_voice_overlay_missing",
        )
        statuses = [self._partial_panel_status(), self._ready_panel_status()]
        now = [0.0]

        def sleeper(seconds):
            now[0] += seconds

        ui_result = control_panel.collect_operation_ui_result(
            "启动",
            lambda: timeout,
            lambda **kwargs: statuses.pop(0),
            monotonic=lambda: now[0],
            sleeper=sleeper,
            final_status_grace_seconds=1.0,
            final_status_poll_seconds=0.5,
        )

        self.assertEqual(ui_result.operation_name, "启动")
        self.assertEqual(ui_result.result.error, "timeout_voice_overlay_missing")
        self.assertTrue(ui_result.final_status.can_wake_now)

    def test_not_running_status(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, NOT_RUNNING, compute_status

        status = compute_status(
            ProcessStatus(False, False, 0),
            HealthCheckResult(False, "health_unavailable:URLError"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        self.assertEqual(status.overall_status, NOT_RUNNING)
        self.assertFalse(status.can_wake_now)

    def test_ready_status_requires_stt_health_and_overlay(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, READY, compute_status

        status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        self.assertEqual(status.overall_status, READY)
        self.assertTrue(status.stt_ready)
        self.assertTrue(status.stt_model_loaded)
        self.assertTrue(status.can_wake_now)

    def test_stt_running_health_not_ready_is_loading_model(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, LOADING_MODEL, STARTING, compute_status

        status = compute_status(
            ProcessStatus(True, False, 1),
            HealthCheckResult(False, "ok=True status=loading model_loaded=False"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        self.assertIn(status.overall_status, (STARTING, LOADING_MODEL))
        self.assertFalse(status.can_wake_now)

    def test_stt_ready_overlay_missing_is_partial(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, PARTIAL, compute_status

        status = compute_status(
            ProcessStatus(True, False, 1),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        self.assertEqual(status.overall_status, PARTIAL)
        self.assertFalse(status.can_wake_now)

    def test_stt_missing_overlay_running_is_partial(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, PARTIAL, compute_status

        status = compute_status(
            ProcessStatus(False, True, 1),
            HealthCheckResult(False, "health_unavailable:URLError"),
            Path(r"C:\Users\tester\.xiaohuang\config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        self.assertEqual(status.overall_status, PARTIAL)
        self.assertFalse(status.can_wake_now)

    def test_can_wake_now_only_ready(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, compute_status

        summary = ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True)
        ready = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            summary,
        )
        partial = compute_status(
            ProcessStatus(True, False, 1),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            summary,
        )

        self.assertTrue(ready.can_wake_now)
        self.assertFalse(partial.can_wake_now)

    def test_can_wake_now_accepts_ready_status_without_model_loaded_flag(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, READY, compute_status

        status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=False"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )

        self.assertEqual(status.overall_status, READY)
        self.assertTrue(status.can_wake_now)

    def test_ready_status_overrides_wait_timeout_operation_result(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus, WaitResult
        from xiaohuang.status_control_service import (
            ConfigSummary,
            compute_status,
            _resolve_ready_operation_result,
        )

        current_status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary("贾维斯测试", ["贾维斯"], "deepseek", True),
        )
        timeout = WaitResult(
            ok=False,
            reason="timeout_voice_overlay_missing",
            status=ProcessStatus(True, False, 1),
            health=HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            elapsed_seconds=90.0,
        )

        result = _resolve_ready_operation_result(
            timeout,
            current_status,
            0.0,
            success_title="重启完成",
            success_message="小黄已重启并就绪。",
            failure_title="重启未就绪",
            failure_prefix="启动命令已发出，但服务未就绪：",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.title, "重启完成")
        self.assertIsNone(result.error)
        self.assertNotIn("timeout_voice_overlay_missing", result.message)

    def test_config_summary_reads_user_config(self):
        from xiaohuang.status_control_service import load_config_summary

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                """
{
  "assistant": {"display_name": "贾维斯测试"},
  "wake": {"phrases": ["贾维斯"]},
  "llm": {"provider": "qwen"},
  "tts": {"enabled": false}
}
""".strip(),
                encoding="utf-8",
            )

            summary = load_config_summary(config_path)

        self.assertEqual(summary.assistant_display_name, "贾维斯测试")
        self.assertEqual(summary.wake_phrases, ["贾维斯"])
        self.assertEqual(summary.llm_provider, "qwen")
        self.assertFalse(summary.tts_enabled)

    def test_health_check_failure_does_not_crash_status_build(self):
        from xiaohuang.launch_control_service import HealthCheckResult, XiaoHuangProcess
        from xiaohuang.status_control_service import build_status

        status = build_status(
            PROJECT_ROOT,
            Path(r"C:\Users\tester\.xiaohuang\missing.json"),
            process_detector=lambda root: [XiaoHuangProcess(1, "stt_server")],
            health_checker=lambda url: HealthCheckResult(False, "health_unavailable:URLError"),
        )

        self.assertFalse(status.can_wake_now)
        self.assertIn(status.overall_status, ("STARTING", "LOADING_MODEL", "ERROR"))
        self.assertEqual(status.stt_health_status, "unavailable")


class V12EBControlPanelWakeEngineTests(unittest.TestCase):
    def _write_json_config(self, data):
        import json

        temp_dir = tempfile.TemporaryDirectory()
        config_path = Path(temp_dir.name) / "config.json"
        config_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return temp_dir, config_path

    def _read_json_config(self, config_path):
        import json

        return json.loads(config_path.read_text(encoding="utf-8"))

    def test_config_summary_reads_openwakeword_engine(self):
        from xiaohuang.status_control_service import load_config_summary

        temp_dir, config_path = self._write_json_config({
            "wake": {
                "engine": "openwakeword",
                "phrases": ["贾维斯"],
                "fallback_enabled": False,
                "device_index": 0,
                "cooldown_seconds": 2.5,
                "sensitivity": 0.7,
                "model_name": "hey_jarvis",
            }
        })
        with temp_dir:
            summary = load_config_summary(config_path)

        self.assertEqual(summary.wake_engine, "openwakeword")
        self.assertFalse(summary.wake_engine_is_default)
        self.assertEqual(summary.wake_model_label, "hey_jarvis")
        self.assertEqual(summary.wake_phrases, ["贾维斯"])

    def test_config_summary_defaults_missing_engine_to_stt_text(self):
        from xiaohuang.status_control_service import load_config_summary

        temp_dir, config_path = self._write_json_config({"wake": {"phrases": ["贾维斯"]}})
        with temp_dir:
            summary = load_config_summary(config_path)

        self.assertEqual(summary.wake_engine, "stt_text")
        self.assertTrue(summary.wake_engine_is_default)

    def test_config_summary_reads_wake_engine_parameters(self):
        from xiaohuang.status_control_service import load_config_summary

        temp_dir, config_path = self._write_json_config({
            "wake": {
                "engine": "openwakeword",
                "fallback_enabled": False,
                "device_index": 3,
                "cooldown_seconds": 4.0,
                "sensitivity": 0.25,
            }
        })
        with temp_dir:
            summary = load_config_summary(config_path)

        self.assertFalse(summary.wake_fallback_enabled)
        self.assertEqual(summary.wake_device_index, 3)
        self.assertEqual(summary.wake_cooldown_seconds, 4.0)
        self.assertEqual(summary.wake_sensitivity, 0.25)

    def test_compute_status_includes_wake_engine_fields(self):
        from xiaohuang.launch_control_service import HealthCheckResult, ProcessStatus
        from xiaohuang.status_control_service import ConfigSummary, compute_status

        status = compute_status(
            ProcessStatus(True, True, 2),
            HealthCheckResult(True, "ok=True status=ready model_loaded=True"),
            Path("config.json"),
            ConfigSummary(
                "贾维斯测试",
                ["贾维斯"],
                "deepseek",
                True,
                wake_engine="openwakeword",
                wake_engine_is_default=False,
                wake_fallback_enabled=False,
                wake_device_index=0,
                wake_cooldown_seconds=2.5,
                wake_sensitivity=0.6,
                wake_model_label="hey_jarvis",
            ),
        )

        self.assertEqual(status.wake_engine, "openwakeword")
        self.assertFalse(status.wake_fallback_enabled)
        self.assertEqual(status.wake_device_index, 0)
        self.assertEqual(status.wake_model_label, "hey_jarvis")

    def test_save_wake_engine_config_creates_missing_wake_object(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({"assistant": {"display_name": "贾维斯测试"}})
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("openwakeword", True, 0, 2.5, 0.5),
            )
            data = self._read_json_config(config_path)

        self.assertTrue(result.ok)
        self.assertEqual(data["wake"]["engine"], "openwakeword")
        self.assertEqual(data["assistant"]["display_name"], "贾维斯测试")

    def test_save_wake_engine_config_writes_openwakeword(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({"wake": {"engine": "stt_text"}})
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("openwakeword", False, 0, 3.0, 0.8),
            )
            data = self._read_json_config(config_path)

        self.assertTrue(result.ok)
        self.assertEqual(data["wake"]["engine"], "openwakeword")
        self.assertFalse(data["wake"]["fallback_enabled"])
        self.assertEqual(data["wake"]["device_index"], 0)
        self.assertEqual(data["wake"]["cooldown_seconds"], 3.0)
        self.assertEqual(data["wake"]["sensitivity"], 0.8)

    def test_save_wake_engine_config_writes_stt_text(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({"wake": {"engine": "openwakeword"}})
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("stt_text", True, 0, 2.5, 0.5),
            )
            data = self._read_json_config(config_path)

        self.assertTrue(result.ok)
        self.assertEqual(data["wake"]["engine"], "stt_text")

    def test_save_wake_engine_config_rejects_invalid_device_index(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({"wake": {}})
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("stt_text", True, "abc", 2.5, 0.5),
            )

        self.assertFalse(result.ok)
        self.assertIn("device_index", result.message)

    def test_save_wake_engine_config_rejects_invalid_cooldown(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({"wake": {}})
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("stt_text", True, 0, 0.0, 0.5),
            )

        self.assertFalse(result.ok)
        self.assertIn("cooldown_seconds", result.message)

    def test_save_wake_engine_config_rejects_invalid_sensitivity(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({"wake": {}})
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("stt_text", True, 0, 2.5, 1.1),
            )

        self.assertFalse(result.ok)
        self.assertIn("sensitivity", result.message)

    def test_save_wake_engine_config_preserves_other_fields(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        temp_dir, config_path = self._write_json_config({
            "wake": {"phrases": ["贾维斯"], "model_name": "hey_jarvis"},
            "llm": {"provider": "qwen"},
            "custom": {"keep": True},
        })
        with temp_dir:
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("openwakeword", True, 0, 2.5, 0.5),
            )
            data = self._read_json_config(config_path)

        self.assertTrue(result.ok)
        self.assertEqual(data["wake"]["phrases"], ["贾维斯"])
        self.assertEqual(data["wake"]["model_name"], "hey_jarvis")
        self.assertEqual(data["llm"]["provider"], "qwen")
        self.assertTrue(data["custom"]["keep"])

    def test_save_wake_engine_config_missing_file_returns_error(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "missing" / "config.json"
            result = save_wake_engine_config(
                config_path,
                WakeEngineConfigUpdate("stt_text", True, 0, 2.5, 0.5),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "config_not_found")
        self.assertFalse(config_path.exists())

    def test_validate_config_path_rejects_empty_string(self):
        from xiaohuang.status_control_service import _validate_config_path

        self.assertIsNotNone(_validate_config_path(Path("")))
        self.assertIn("无效", _validate_config_path(Path("")) or "")

    def test_validate_config_path_rejects_dot(self):
        from xiaohuang.status_control_service import _validate_config_path

        self.assertIsNotNone(_validate_config_path(Path(".")))
        self.assertIn("无效", _validate_config_path(Path(".")) or "")

    def test_validate_config_path_rejects_directory(self):
        from xiaohuang.status_control_service import _validate_config_path

        with tempfile.TemporaryDirectory() as tmp:
            error = _validate_config_path(Path(tmp))
            self.assertIsNotNone(error)
            self.assertIn("目录", error or "")

    def test_validate_config_path_accepts_valid_file_path(self):
        from xiaohuang.status_control_service import _validate_config_path

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            self.assertIsNone(_validate_config_path(config_path))

    def test_save_wake_engine_config_rejects_empty_path(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        result = save_wake_engine_config(
            Path(""),
            WakeEngineConfigUpdate("stt_text", True, 0, 2.5, 0.5),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_path")

    def test_save_wake_engine_config_rejects_dot_path(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        result = save_wake_engine_config(
            Path("."),
            WakeEngineConfigUpdate("stt_text", True, 0, 2.5, 0.5),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_path")

    def test_save_wake_engine_config_rejects_directory(self):
        from xiaohuang.status_control_service import WakeEngineConfigUpdate, save_wake_engine_config

        with tempfile.TemporaryDirectory() as tmp:
            result = save_wake_engine_config(
                Path(tmp),
                WakeEngineConfigUpdate("stt_text", True, 0, 2.5, 0.5),
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_path")

    def test_config_path_display_uses_resolved_absolute_path(self):
        import control_panel

        self.assertFalse(control_panel._is_config_path_valid(Path("")))
        self.assertFalse(control_panel._is_config_path_valid(Path(".")))


class V12FBWakeRuntimeServiceTests(unittest.TestCase):
    """Tests for src/xiaohuang/wake_runtime_service.py — pure config/selection logic."""

    def _config(self, *, engine: str = "openwakeword", fallback_enabled: bool = True):
        from xiaohuang.wake_runtime_service import WakeEngineRuntimeConfig

        return WakeEngineRuntimeConfig(
            engine=engine,
            wake_phrase="贾维斯",
            fallback_enabled=fallback_enabled,
            device=0,
            sample_rate=16000,
            sensitivity=0.5,
            cooldown_seconds=2.5,
            model_path=None,
            model_name="hey_jarvis",
            poll_seconds=1.0,
        )

    def _ready_deps(self):
        from xiaohuang.openwakeword_adapter import OpenWakeWordDependencyStatus

        return OpenWakeWordDependencyStatus(
            openwakeword_installed=True,
            numpy_installed=True,
            sounddevice_installed=True,
            onnxruntime_available=True,
            ready_for_realtime_demo=True,
            errors=[],
        )

    def _missing_deps(self):
        from xiaohuang.openwakeword_adapter import OpenWakeWordDependencyStatus

        return OpenWakeWordDependencyStatus(
            openwakeword_installed=False,
            numpy_installed=True,
            sounddevice_installed=True,
            onnxruntime_available=True,
            ready_for_realtime_demo=False,
            errors=["Missing optional dependency: openwakeword"],
        )

    def test_normalize_wake_engine_none_defaults_to_stt_text(self):
        from xiaohuang.wake_runtime_service import normalize_wake_engine

        self.assertEqual(normalize_wake_engine(None), "stt_text")

    def test_normalize_wake_engine_openwakeword(self):
        from xiaohuang.wake_runtime_service import normalize_wake_engine

        self.assertEqual(normalize_wake_engine("openwakeword"), "openwakeword")

    def test_normalize_wake_engine_dash_normalized_to_underscore(self):
        from xiaohuang.wake_runtime_service import normalize_wake_engine

        self.assertEqual(normalize_wake_engine("open-wakeword"), "open_wakeword")

    def test_normalize_wake_engine_empty_string_defaults_to_stt_text(self):
        from xiaohuang.wake_runtime_service import normalize_wake_engine

        self.assertEqual(normalize_wake_engine(""), "stt_text")

    def test_select_stt_text_returns_stt_text_plan(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_STT_TEXT, select_wake_engine_runtime

        plan = select_wake_engine_runtime(self._config(engine="stt_text"))
        self.assertEqual(plan.engine, WAKE_ENGINE_STT_TEXT)
        self.assertIsNone(plan.warning)
        self.assertIsNone(plan.error)

    def test_select_openwakeword_with_ready_deps_returns_openwakeword(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_OPENWAKEWORD, select_wake_engine_runtime

        plan = select_wake_engine_runtime(
            self._config(engine="openwakeword"),
            dependency_status=self._ready_deps(),
        )
        self.assertEqual(plan.engine, WAKE_ENGINE_OPENWAKEWORD)
        self.assertIsNone(plan.error)

    def test_select_openwakeword_missing_deps_fallback_enabled_returns_stt_text(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_STT_TEXT, select_wake_engine_runtime

        plan = select_wake_engine_runtime(
            self._config(engine="openwakeword", fallback_enabled=True),
            dependency_status=self._missing_deps(),
        )
        self.assertEqual(plan.engine, WAKE_ENGINE_STT_TEXT)
        self.assertIsNotNone(plan.warning)
        self.assertIn("falling back to stt_text", plan.warning or "")

    def test_select_openwakeword_missing_deps_fallback_disabled_returns_error(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_OPENWAKEWORD, select_wake_engine_runtime

        plan = select_wake_engine_runtime(
            self._config(engine="openwakeword", fallback_enabled=False),
            dependency_status=self._missing_deps(),
        )
        self.assertEqual(plan.engine, WAKE_ENGINE_OPENWAKEWORD)
        self.assertIsNotNone(plan.error)

    def test_select_unsupported_engine_fallback_enabled_returns_stt_text_with_warning(self):
        from xiaohuang.wake_runtime_service import WAKE_ENGINE_STT_TEXT, select_wake_engine_runtime

        plan = select_wake_engine_runtime(
            self._config(engine="unknown_engine", fallback_enabled=True),
        )
        self.assertEqual(plan.engine, WAKE_ENGINE_STT_TEXT)
        self.assertIsNotNone(plan.warning)

    def test_select_unsupported_engine_fallback_disabled_returns_error(self):
        from xiaohuang.wake_runtime_service import select_wake_engine_runtime

        plan = select_wake_engine_runtime(
            self._config(engine="unknown_engine", fallback_enabled=False),
        )
        self.assertIsNotNone(plan.error)
        self.assertNotEqual(plan.engine, "stt_text")

    def test_format_openwakeword_dependency_error_includes_errors(self):
        from xiaohuang.wake_runtime_service import format_openwakeword_dependency_error

        message = format_openwakeword_dependency_error(self._missing_deps())
        self.assertIn("openwakeword dependency unavailable", message)
        self.assertIn("Missing optional dependency: openwakeword", message)

    def test_format_openwakeword_dependency_error_no_errors_fallback_message(self):
        from xiaohuang.wake_runtime_service import format_openwakeword_dependency_error
        from xiaohuang.openwakeword_adapter import OpenWakeWordDependencyStatus

        status = OpenWakeWordDependencyStatus(
            openwakeword_installed=True,
            numpy_installed=True,
            sounddevice_installed=True,
            onnxruntime_available=True,
            ready_for_realtime_demo=False,
            errors=[],
        )
        message = format_openwakeword_dependency_error(status)
        self.assertIn("dependency check failed", message)


class V12FEReplyRuntimeServiceTests(unittest.TestCase):
    """Tests for src/xiaohuang/reply_runtime_service.py — reply/TTS runtime."""

    def _config(self):
        from xiaohuang.reply_pipeline_service import ReplyPipelineConfig

        return ReplyPipelineConfig(
            enable_llm=False,
            enable_tts=False,
        )

    def _fake_result(self, text: str = "hello"):
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        return ReplyPipelineResult(
            reply_text=text,
            reply_source="rule",
            source_note=None,
        )

    def _fake_pipeline(self, return_result=None):
        def _pipeline(command_text, *, config, on_debug, on_before_tts, playback_warn, latency_tracker):
            if on_before_tts is not None:
                on_before_tts("fake tts text")
            if return_result is not None:
                return return_result
            return self._fake_result(f"reply: {command_text}")

        return _pipeline

    def _fake_bridge(self):
        class FakeBridge:
            def __init__(self):
                self.tts_started = False
                self.tts_finished = False

            def mark_tts_started(self):
                self.tts_started = True

            def mark_tts_finished(self):
                self.tts_finished = True

        return FakeBridge()

    def test_generate_reply_runtime_calls_tts_callbacks(self):
        from xiaohuang.reply_runtime_service import generate_reply_runtime_result

        bridge = self._fake_bridge()
        tts_text: list[str] = []

        def _before_tts(text):
            tts_text.append(text)
            bridge.mark_tts_started()

        def _after_tts():
            bridge.mark_tts_finished()

        result = generate_reply_runtime_result(
            "test command",
            config=self._config(),
            on_before_tts=_before_tts,
            on_after_tts=_after_tts,
            pipeline_func=self._fake_pipeline(),
        )

        self.assertTrue(bridge.tts_started)
        self.assertTrue(bridge.tts_finished)
        self.assertEqual(len(tts_text), 1)
        self.assertIn("fake tts text", tts_text[0])

    def test_generate_reply_runtime_no_callbacks_no_error(self):
        from xiaohuang.reply_runtime_service import generate_reply_runtime_result

        result = generate_reply_runtime_result(
            "test command",
            config=self._config(),
            pipeline_func=self._fake_pipeline(),
        )
        self.assertIsNotNone(result)
        self.assertIn("test command", result.reply_text)

    def test_generate_reply_runtime_exception_still_calls_after_tts(self):
        from xiaohuang.reply_runtime_service import generate_reply_runtime_result

        bridge = self._fake_bridge()

        def _before_tts(text):
            bridge.mark_tts_started()
            raise RuntimeError("tts failed")

        def _after_tts():
            bridge.mark_tts_finished()

        with self.assertRaises(RuntimeError):
            generate_reply_runtime_result(
                "test",
                config=self._config(),
                on_before_tts=_before_tts,
                on_after_tts=_after_tts,
                pipeline_func=self._fake_pipeline(),
            )

        self.assertTrue(bridge.tts_started)
        self.assertTrue(bridge.tts_finished)

    def test_generate_reply_runtime_no_tts_no_finished_callback(self):
        from xiaohuang.reply_runtime_service import generate_reply_runtime_result

        bridge = self._fake_bridge()

        def _after_tts():
            bridge.mark_tts_finished()

        # Use a pipeline that does NOT call on_before_tts
        def _no_tts_pipeline(command_text, *, config, on_debug, on_before_tts, playback_warn, latency_tracker):
            return self._fake_result(f"reply: {command_text}")

        result = generate_reply_runtime_result(
            "test",
            config=self._config(),
            on_after_tts=_after_tts,
            pipeline_func=_no_tts_pipeline,
        )
        self.assertFalse(bridge.tts_finished)

    def test_generate_reply_runtime_passes_debug_callback(self):
        from xiaohuang.reply_runtime_service import generate_reply_runtime_result

        debug_msgs: list[str] = []

        def _fake_debug_pipeline(command_text, *, config, on_debug, on_before_tts, playback_warn, latency_tracker):
            if on_debug is not None:
                on_debug("debug message")
            return self._fake_result(f"reply: {command_text}")

        generate_reply_runtime_result(
            "what time is it",
            config=self._config(),
            on_debug=lambda msg: debug_msgs.append(msg),
            pipeline_func=_fake_debug_pipeline,
        )
        self.assertEqual(len(debug_msgs), 1)


class V12FFBAssistantRuntimeServiceTests(unittest.TestCase):
    """Tests for src/xiaohuang/assistant_runtime_service.py."""

    def _callbacks(self):
        from xiaohuang.assistant_runtime_service import AssistantRuntimeCallbacks

        states: list[tuple[str, str | None]] = []
        warns: list[str] = []
        debugs: list[str] = []
        waits: list[float] = []
        hides: list[bool] = []

        cb = AssistantRuntimeCallbacks(
            set_state=lambda s, d=None: states.append((s, d)),
            log_warn=lambda msg: warns.append(msg),
            debug_print=lambda msg: debugs.append(msg),
            wait=lambda s: (waits.append(s), False)[1],
            hide_overlay=lambda: hides.append(True),
        )
        return cb, states, warns, debugs, waits, hides

    def _fake_pipeline_result(self, **kw):
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        return ReplyPipelineResult(
            reply_text=kw.get("reply_text", "hello"),
            reply_source=kw.get("reply_source", "rule"),
            source_note=kw.get("source_note", None),
            tts_error=kw.get("tts_error", None),
        )

    def test_handle_single_turn_sets_state_result(self):
        from xiaohuang.assistant_runtime_service import handle_single_turn_reply_result

        cb, states, _, _, _, _ = self._callbacks()
        outcome = handle_single_turn_reply_result(
            callbacks=cb,
            pipeline_result=self._fake_pipeline_result(reply_text="hi"),
            command_text="say hi",
        )
        self.assertTrue(outcome.continue_loop)
        self.assertEqual(states[0][0], "result")
        self.assertEqual(states[1][0], "idle")

    def test_handle_single_turn_tts_error_sets_error_state(self):
        from xiaohuang.assistant_runtime_service import handle_single_turn_reply_result

        cb, states, warns, _, _, _ = self._callbacks()
        handle_single_turn_reply_result(
            callbacks=cb,
            pipeline_result=self._fake_pipeline_result(
                reply_text="hi", tts_error="tts failed",
            ),
            command_text="say hi",
        )
        self.assertIn("error", [s[0] for s in states])
        self.assertIn("tts failed", warns)

    def test_handle_single_turn_cooldown_wait(self):
        from xiaohuang.assistant_runtime_service import handle_single_turn_reply_result

        cb, _, _, _, waits, _ = self._callbacks()
        handle_single_turn_reply_result(
            callbacks=cb,
            pipeline_result=self._fake_pipeline_result(),
            command_text="test",
            post_response_cooldown=3.5,
        )
        self.assertGreater(len(waits), 0)

    def test_handle_single_turn_resident_hidden_hides_overlay(self):
        from xiaohuang.assistant_runtime_service import handle_single_turn_reply_result

        cb, _, _, _, _, hides = self._callbacks()
        handle_single_turn_reply_result(
            callbacks=cb,
            pipeline_result=self._fake_pipeline_result(),
            command_text="test",
            resident_hidden=True,
        )
        self.assertGreater(len(hides), 0)

    def test_handle_single_turn_resident_visible_no_hide(self):
        from xiaohuang.assistant_runtime_service import handle_single_turn_reply_result

        cb, _, _, _, _, hides = self._callbacks()
        cb.hide_overlay = None
        outcome = handle_single_turn_reply_result(
            callbacks=cb,
            pipeline_result=self._fake_pipeline_result(),
            command_text="test",
            resident_hidden=True,
        )
        self.assertTrue(outcome.continue_loop)
        self.assertEqual(len(hides), 0)

    def test_handle_single_turn_stop_event_fires(self):
        from xiaohuang.assistant_runtime_service import handle_single_turn_reply_result

        cb, _, _, _, _, _ = self._callbacks()
        cb.wait = lambda s: True  # stop event fired
        outcome = handle_single_turn_reply_result(
            callbacks=cb,
            pipeline_result=self._fake_pipeline_result(),
            command_text="test",
            post_response_cooldown=2.0,
        )
        self.assertFalse(outcome.continue_loop)

    def test_assistant_runtime_service_no_tkinter_import(self):
        import sys
        from xiaohuang import assistant_runtime_service
        # module imports shouldn't pull in tkinter transitively from us
        self.assertNotIn("tkinter", assistant_runtime_service.__dict__)


class V12FFCSessionFollowupLoopTests(unittest.TestCase):
    """Tests for run_session_followup_loop in assistant_runtime_service."""

    def _session_callbacks(self):
        from xiaohuang.assistant_runtime_service import AssistantSessionCallbacks

        states: list[tuple[str, str | None]] = []
        infos: list[str] = []
        warnings: list[str] = []
        waits: list[float] = []
        hides: list[bool] = []
        records: list[tuple[float, object]] = []
        replies: list[tuple[str, object]] = []

        def record_followup(max_seconds, lt):
            records.append((max_seconds, lt))
            return _next_record_text.pop(0) if _next_record_text else ""

        def generate_reply(text, lt):
            replies.append((text, lt))
            from xiaohuang.reply_pipeline_service import ReplyPipelineResult
            return _next_reply_result.pop(0) if _next_reply_result else ReplyPipelineResult(
                reply_text=f"reply: {text}", reply_source="rule", source_note=None,
            )

        _next_record_text: list[str] = []
        _next_reply_result: list[object] = []

        cb = AssistantSessionCallbacks(
            set_state=lambda s, d=None: states.append((s, d)),
            log_info=lambda msg: infos.append(msg),
            wait_seconds=lambda s: (waits.append(s), False)[1],
            record_followup=record_followup,
            generate_reply=generate_reply,
            debug_print=None,
            log_warning=lambda msg: warnings.append(msg),
            hide_overlay=lambda: hides.append(True),
        )
        return cb, states, infos, warnings, waits, hides, records, replies, _next_record_text, _next_reply_result

    def _session_config(self, **kw):
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        defaults = dict(enabled=True, max_turns=5, followup_timeout_seconds=8.0,
                        max_session_seconds=300.0, max_no_speech_retries=3)
        defaults.update(kw)
        return ConversationSessionConfig(**defaults)

    def test_normal_followup_one_turn_then_exit(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, waits, hides, records, replies, next_texts, next_results = self._session_callbacks()
        next_texts.append("继续说的话")
        next_texts.append("退出")
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_turns=5),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        self.assertEqual(outcome.end_reason, "exit_phrase")
        # initial=1 + followup "继续说的话" + exit "退出" = 3
        self.assertEqual(outcome.completed_turns, 3)
        self.assertTrue(outcome.should_continue_main_loop)
        # States: listening (turn2), listening (turn3/exit), result (exit reply), idle
        self.assertEqual(states[0][0], "listening")
        self.assertEqual(states[1][0], "listening")
        self.assertEqual(states[2][0], "result")
        self.assertEqual(states[3][0], "idle")

    def test_no_speech_increments_retries(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, _, _, _, _, next_texts, _ = self._session_callbacks()
        next_texts.append("")  # no speech
        next_texts.append("")  # no speech
        next_texts.append("")  # no speech
        next_texts.append("")  # no speech (exceeds max)
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_no_speech_retries=2),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        self.assertEqual(outcome.end_reason, "no_speech")
        # max_no_speech_retries=2, exits at 2
        self.assertEqual(outcome.no_speech_retries, 2)
        self.assertTrue(any("no_speech" in msg for msg in infos))

    def test_max_turns_ends_session(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, _, _, _, _, next_texts, _ = self._session_callbacks()
        next_texts.append("turn 2")
        next_texts.append("turn 3")
        next_texts.append("turn 4")
        next_texts.append("turn 5")
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_turns=4),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        self.assertEqual(outcome.end_reason, "max_turns")
        self.assertEqual(outcome.completed_turns, 4)

    def test_stop_requested_during_cooldown_returns_false(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, waits, _, _, _, next_texts, _ = self._session_callbacks()
        next_texts.append("退出")
        cb.wait_seconds = lambda s: True
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_turns=5),
            callbacks=cb,
            session_start_time=0.0,
            post_response_cooldown=2.0,
            debug=False,
            now_func=fake_now,
        )
        self.assertFalse(outcome.should_continue_main_loop)

    def test_session_config_disabled_no_followup(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, _, _, records, _, next_texts, _ = self._session_callbacks()
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(enabled=False),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        # should_continue_session returns False immediately for disabled
        self.assertEqual(outcome.completed_turns, 1)
        self.assertEqual(len(records), 0)

    def test_tts_error_logs_warning(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        cb, states, infos, warnings, _, _, _, replies, next_texts, next_results = self._session_callbacks()
        next_texts.append("hello")
        next_results.append(ReplyPipelineResult(
            reply_text="hi there", reply_source="llm", source_note=None,
            tts_error="tts playback failed",
        ))
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_turns=2),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        self.assertTrue(any("tts playback failed" in w for w in warnings))

    def test_state_transitions_order(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, _, _, _, _, next_texts, _ = self._session_callbacks()
        next_texts.append("followup text")
        next_texts.append("退出")
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_turns=5),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        state_names = [s[0] for s in states]
        # followup 1: listening, followup 2 (exit): listening → result, end: idle
        self.assertEqual(state_names[0], "listening")
        self.assertEqual(state_names[1], "listening")
        self.assertEqual(state_names[2], "result")
        self.assertEqual(state_names[3], "idle")

    def test_session_end_reason_stop_event(self):
        from xiaohuang.assistant_runtime_service import run_session_followup_loop

        cb, states, infos, _, waits, _, _, _, next_texts, _ = self._session_callbacks()
        next_texts.append("hello")
        next_texts.append("stop_event_text")
        # wait_seconds returns True during post-record wait for first followup
        call_count = [0]
        def wait_once(s):
            call_count[0] += 1
            if call_count[0] == 1 and s == 0:
                return True  # stop during post-record wait for turn 2
            return False
        cb.wait_seconds = wait_once
        _now = [0.0]
        def fake_now():
            _now[0] += 0.5
            return _now[0]

        outcome = run_session_followup_loop(
            session_config=self._session_config(max_turns=5),
            callbacks=cb,
            session_start_time=0.0,
            debug=False,
            now_func=fake_now,
        )
        # inner loop breaks, end-reason reports stop_event
        # should_continue_main_loop depends on cooldown wait (which returns False)
        self.assertEqual(outcome.end_reason, "stop_event")

    def test_session_followup_loop_no_tkinter(self):
        import sys
        from xiaohuang import assistant_runtime_service
        self.assertNotIn("tkinter", assistant_runtime_service.__dict__)


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

    def test_get_overlay_status_text_uses_configured_assistant_and_wake_phrase(self):
        idle = get_overlay_status_text("idle", assistant_name="贾维斯测试", wake_phrase="贾维斯")
        speaking = get_overlay_status_text("speaking", assistant_name="贾维斯测试")

        self.assertEqual(idle.title, "贾维斯测试待机中")
        self.assertEqual(idle.subtitle, "说“贾维斯”唤醒我")
        self.assertEqual(speaking.title, "贾维斯测试正在说话")

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

    def test_build_reply_result_text_uses_configured_assistant_name(self):
        text = build_reply_result_text("你好", "我在。", assistant_name="贾维斯测试")

        self.assertIn("你说：你好", text)
        self.assertIn("贾维斯测试：我在。", text)


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

    def test_run_wake_loop_once_passes_wake_check_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording_dir = Path(temp_dir) / "data" / "recordings"
            modes: list[str] = []

            options = WakeLoopOptions(
                device_id=0, server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0, wake_phrases=["小黄"],
                max_seconds=10.0, silence_seconds=0.8,
                sample_rate=16000, channels=1, recording_dir=recording_dir,
            )

            def fake_path(output_dir):
                return Path(output_dir) / f"{Path(output_dir).name}.wav"

            def write_wav(output_path, **_kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
                return Path(output_path)

            call_count = {"n": 0}

            def mode_stt(_path, _server_url, *, mode=None):
                modes.append(mode)
                call_count["n"] += 1
                return {"text": "小黄" if call_count["n"] == 1 else "测试"}

            def fake_vad(output_path, **_kwargs):
                write_wav(output_path)
                return SimpleNamespace(path=Path(output_path), duration_seconds=1.0, stop_reason="silence_after_speech")

            run_wake_loop_once(
                options,
                record_wav_func=write_wav,
                record_until_silence_func=fake_vad,
                request_transcription_func=mode_stt,
                build_recording_path_func=fake_path,
            )

            self.assertEqual(modes, ["wake_check", "command"])

    def test_run_wake_loop_once_mode_compat_with_old_two_arg_signature(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording_dir = Path(temp_dir) / "data" / "recordings"
            call_count = {"n": 0}

            options = WakeLoopOptions(
                device_id=0, server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0, wake_phrases=["小黄"],
                max_seconds=10.0, silence_seconds=0.8,
                sample_rate=16000, channels=1, recording_dir=recording_dir,
            )

            def fake_path(output_dir):
                return Path(output_dir) / f"{Path(output_dir).name}.wav"

            def write_wav(output_path, **_kwargs):
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
                return Path(output_path)

            def old_stt(_path, _server_url):
                call_count["n"] += 1
                return {"text": "小黄" if call_count["n"] == 1 else "测试"}

            def fake_vad(output_path, **_kwargs):
                write_wav(output_path)
                return SimpleNamespace(path=Path(output_path), duration_seconds=1.0, stop_reason="silence_after_speech")

            result = run_wake_loop_once(
                options,
                record_wav_func=write_wav,
                record_until_silence_func=fake_vad,
                request_transcription_func=old_stt,
                build_recording_path_func=fake_path,
            )

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
    @staticmethod
    def _source_note(source):
        from xiaohuang.reply_pipeline_service import _source_note_for_source
        return _source_note_for_source(source)

    def test_source_note_none_for_rule(self):
        self.assertIsNone(self._source_note("rule"))

    def test_source_note_none_for_llm(self):
        self.assertIsNone(self._source_note("llm"))

    def test_source_note_no_key(self):
        self.assertIn("未配置 key", self._source_note("rule_fallback_no_key"))

    def test_source_note_error(self):
        self.assertIn("不可用", self._source_note("rule_fallback_error"))

    def test_source_note_empty(self):
        self.assertIn("返回为空", self._source_note("rule_fallback_empty"))

    def test_source_note_length(self):
        self.assertIn("被截断", self._source_note("rule_fallback_length"))

    def test_source_note_tool_unavailable(self):
        self.assertIn("不能执行工具", self._source_note("tool_unavailable"))


class V101RequestIdTests(unittest.TestCase):
    def test_generate_request_id_returns_non_empty_string(self):
        rid = generate_request_id()
        self.assertIsInstance(rid, str)
        self.assertTrue(len(rid) > 0)
        self.assertTrue(rid.startswith("req_"))

    def test_generate_request_id_returns_unique_values(self):
        ids = {generate_request_id() for _ in range(20)}
        self.assertEqual(len(ids), 20)


class V101ApiErrorServiceTests(unittest.TestCase):
    def test_build_error_contains_required_fields(self):
        error = build_error(STT_ENGINE_ERROR, "Transcription failed.", retryable=True)
        self.assertEqual(error["code"], STT_ENGINE_ERROR)
        self.assertEqual(error["message"], "Transcription failed.")
        self.assertTrue(error["retryable"])

    def test_build_error_detail_excluded_by_default(self):
        error = build_error(STT_SERVER_ERROR, "Internal error.", retryable=False)
        self.assertNotIn("detail", error)


class V101ApiSchemasTests(unittest.TestCase):
    def test_build_ok_response_has_required_fields(self):
        resp = build_ok_response("req_test", type="command", text="识别结果")
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["request_id"], "req_test")
        self.assertEqual(resp["type"], "command")
        self.assertEqual(resp["text"], "识别结果")
        self.assertIsNone(resp["error"])
        self.assertIsInstance(resp["meta"], dict)

    def test_build_ok_response_generates_request_id_when_none(self):
        resp = build_ok_response(None, type="health")
        self.assertTrue(resp["request_id"].startswith("req_"))

    def test_build_error_response_has_required_fields(self):
        resp = build_error_response(
            "req_err", type="command",
            code=STT_ENGINE_ERROR, message="Transcription failed.", retryable=True,
        )
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["request_id"], "req_err")
        self.assertEqual(resp["type"], "command")
        self.assertEqual(resp["text"], "")
        self.assertIsInstance(resp["error"], dict)
        self.assertEqual(resp["error"]["code"], STT_ENGINE_ERROR)
        self.assertEqual(resp["error"]["message"], "Transcription failed.")
        self.assertTrue(resp["error"]["retryable"])
        self.assertIsInstance(resp["meta"], dict)

    def test_build_error_response_generates_request_id_when_none(self):
        resp = build_error_response(None, code=STT_SERVER_ERROR, message="err")
        self.assertTrue(resp["request_id"].startswith("req_"))


class V101SttClientBackwardCompatTests(unittest.TestCase):
    def test_extract_error_message_handles_old_string_format(self):
        msg = _extract_error_message({"ok": False, "error": "Missing wav_path."})
        self.assertEqual(msg, "Missing wav_path.")

    def test_extract_error_message_handles_new_dict_format(self):
        msg = _extract_error_message({
            "ok": False,
            "error": {"code": "STT_ENGINE_ERROR", "message": "Transcription failed.", "retryable": True}
        })
        self.assertIn("STT_ENGINE_ERROR", msg)
        self.assertIn("Transcription failed.", msg)

    def test_extract_error_message_fallback_when_no_error_field(self):
        msg = _extract_error_message({"ok": False})
        self.assertEqual(msg, "STT server returned ok=false.")

    def test_extract_error_message_handles_empty_error_string(self):
        msg = _extract_error_message({"ok": False, "error": ""})
        self.assertEqual(msg, "STT server returned ok=false.")

    def test_health_response_retains_old_fields(self):
        resp = build_ok_response("req_h", type="health")
        resp["status"] = "ready"
        resp["server_model_init_seconds"] = 24.75
        self.assertEqual(resp["status"], "ready")
        self.assertEqual(resp["server_model_init_seconds"], 24.75)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["request_id"], "req_h")


class V102HealthObservabilityTests(unittest.TestCase):
    @staticmethod
    def _build_health_response():
        resp = build_ok_response("req_test", type="health")
        resp["status"] = "ready"
        resp["server_model_init_seconds"] = 22.06
        resp["service"] = "xiaohuang-stt-server"
        resp["version"] = "1.0.2"
        resp["uptime_seconds"] = 123.45
        resp["model_loaded"] = True
        resp["capabilities"] = {
            "transcribe": True,
            "health": True,
            "request_id": True,
            "error_envelope": True,
        }
        resp["last_error"] = None
        return resp

    def test_health_retains_old_fields(self):
        resp = self._build_health_response()
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["status"], "ready")
        self.assertEqual(resp["server_model_init_seconds"], 22.06)

    def test_health_retains_v101_fields(self):
        resp = self._build_health_response()
        self.assertEqual(resp["request_id"], "req_test")
        self.assertEqual(resp["type"], "health")
        self.assertEqual(resp["text"], "")
        self.assertIsNone(resp["error"])
        self.assertIsInstance(resp["meta"], dict)

    def test_health_has_v102_service_and_version(self):
        resp = self._build_health_response()
        self.assertEqual(resp["service"], "xiaohuang-stt-server")
        self.assertEqual(resp["version"], "1.0.2")

    def test_health_has_v102_uptime_and_model_loaded(self):
        resp = self._build_health_response()
        self.assertGreater(resp["uptime_seconds"], 0)
        self.assertTrue(resp["model_loaded"])

    def test_health_capabilities_has_required_keys(self):
        resp = self._build_health_response()
        caps = resp["capabilities"]
        self.assertTrue(caps["transcribe"])
        self.assertTrue(caps["health"])
        self.assertTrue(caps["request_id"])
        self.assertTrue(caps["error_envelope"])

    def test_health_last_error_initial_null(self):
        resp = self._build_health_response()
        self.assertIsNone(resp["last_error"])

    def test_health_last_error_after_recording(self):
        resp = self._build_health_response()
        resp["last_error"] = {
            "code": "STT_ENGINE_ERROR",
            "message": "Transcription failed.",
            "request_id": "req_err",
            "timestamp": "2026-05-01T18:00:00+00:00",
        }
        self.assertIsNotNone(resp["last_error"])
        self.assertEqual(resp["last_error"]["code"], "STT_ENGINE_ERROR")
        self.assertNotIn("traceback", resp["last_error"])

    def test_error_response_still_v101_envelope(self):
        resp = build_error_response(
            "req_err", type="command",
            code=STT_ENGINE_ERROR, message="Transcription failed.", retryable=True,
        )
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["request_id"], "req_err")
        self.assertEqual(resp["error"]["code"], STT_ENGINE_ERROR)
        self.assertIsInstance(resp["meta"], dict)


class V103SttErrorClassificationTests(unittest.TestCase):
    def test_stt_request_error_is_stt_server_error_subclass(self):
        from xiaohuang.stt_client_service import SttRequestError, SttServerError
        self.assertTrue(issubclass(SttRequestError, SttServerError))

    def test_stt_server_internal_error_is_stt_server_error_subclass(self):
        from xiaohuang.stt_client_service import SttServerInternalError, SttServerError
        self.assertTrue(issubclass(SttServerInternalError, SttServerError))

    def test_stt_api_error_is_stt_server_error_subclass(self):
        from xiaohuang.stt_client_service import SttApiError, SttServerError
        self.assertTrue(issubclass(SttApiError, SttServerError))

    def test_stt_invalid_response_is_stt_server_error_subclass(self):
        from xiaohuang.stt_client_service import SttInvalidResponse, SttServerError
        self.assertTrue(issubclass(SttInvalidResponse, SttServerError))

    def test_old_catch_stt_server_error_catches_new_subclass(self):
        from xiaohuang.stt_client_service import SttApiError, SttServerError
        try:
            raise SttApiError("test")
        except SttServerError:
            pass
        else:
            self.fail("SttServerError should catch SttApiError")

    def test_parse_response_body_invalid_json(self):
        from xiaohuang.stt_client_service import SttInvalidResponse, _parse_response_body
        with self.assertRaises(SttInvalidResponse):
            _parse_response_body("not json")

    def test_parse_response_body_non_dict(self):
        from xiaohuang.stt_client_service import SttInvalidResponse, _parse_response_body
        with self.assertRaises(SttInvalidResponse):
            _parse_response_body("[]")

    def test_parse_response_body_ok_true(self):
        from xiaohuang.stt_client_service import _parse_response_body
        data = _parse_response_body('{"ok": true, "text": "hello"}')
        self.assertEqual(data["text"], "hello")

    def test_parse_response_body_ok_false_old_string(self):
        from xiaohuang.stt_client_service import SttApiError, _parse_response_body
        with self.assertRaises(SttApiError) as ctx:
            _parse_response_body('{"ok": false, "error": "Missing wav_path."}')
        self.assertIn("Missing wav_path.", str(ctx.exception))

    def test_parse_response_body_ok_false_new_dict(self):
        from xiaohuang.stt_client_service import SttApiError, _parse_response_body
        with self.assertRaises(SttApiError) as ctx:
            _parse_response_body(
                '{"ok": false, "error": {"code": "STT_ENGINE_ERROR", "message": "Transcription failed."}}'
            )
        self.assertIn("STT_ENGINE_ERROR", str(ctx.exception))
        self.assertIn("Transcription failed.", str(ctx.exception))

    def test_parse_response_body_text_only_backward_compat(self):
        from xiaohuang.stt_client_service import _parse_response_body
        data = _parse_response_body('{"text": "你好"}')
        self.assertEqual(data["text"], "你好")

    def test_parse_response_body_status_only_backward_compat(self):
        from xiaohuang.stt_client_service import _parse_response_body
        data = _parse_response_body('{"status": "ready"}')
        self.assertEqual(data["status"], "ready")

    def test_parse_response_body_missing_all_fails(self):
        from xiaohuang.stt_client_service import SttInvalidResponse, _parse_response_body
        with self.assertRaises(SttInvalidResponse):
            _parse_response_body('{"unrelated": 1}')

    def test_http_error_400_raises_request_error(self):
        import io
        from urllib.error import HTTPError
        from xiaohuang.stt_client_service import SttRequestError, _raise_for_http_error
        fp = io.BytesIO(b'{"ok": false, "error": {"code": "STT_SERVER_ERROR", "message": "Missing wav_path."}}')
        exc = HTTPError("http://127.0.0.1:8766/t", 400, "Bad Request", {}, fp)
        with self.assertRaises(SttRequestError) as ctx:
            _raise_for_http_error(exc, "http://127.0.0.1:8766")
        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertIn("Missing wav_path.", str(ctx.exception))

    def test_http_error_500_raises_internal_error(self):
        import io
        from urllib.error import HTTPError
        from xiaohuang.stt_client_service import SttServerInternalError, _raise_for_http_error
        exc = HTTPError("http://127.0.0.1:8766/t", 500, "Error", {}, io.BytesIO(b"{}"))
        with self.assertRaises(SttServerInternalError) as ctx:
            _raise_for_http_error(exc, "http://127.0.0.1:8766")
        self.assertIn("HTTP 500", str(ctx.exception))


class V104ReplyPipelineTests(unittest.TestCase):
    def _make_config(self, **kw):
        from xiaohuang.reply_pipeline_service import ReplyPipelineConfig
        defaults = dict(enable_llm=False, enable_tts=False)
        defaults.update(kw)
        return ReplyPipelineConfig(**defaults)

    def test_pipeline_rule_reply_when_llm_disabled(self):
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        result = generate_reply_pipeline_result("你好", self._make_config())
        self.assertEqual(result.reply_source, "rule")

    def test_pipeline_fallback_when_llm_not_configured(self):
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_llm=True, llm_config=None)
        result = generate_reply_pipeline_result("你好", config)
        self.assertEqual(result.reply_source, "rule_fallback_no_key")

    def test_pipeline_uses_llm_when_configured(self):
        from xiaohuang.llm_reply_service import LlmReplyConfig, ReplyGenerationResult
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(
            enable_llm=True,
            llm_config=LlmReplyConfig(api_key="sk", base_url="https://x", model="m", timeout_seconds=15),
        )
        def fake_llm(_text, **_kw):
            return ReplyGenerationResult("LLM hello", "llm")
        result = generate_reply_pipeline_result("hi", config, llm_reply_func=fake_llm)
        self.assertEqual(result.reply_text, "LLM hello")
        self.assertEqual(result.reply_source, "llm")
        self.assertIsNone(result.source_note)

    def test_pipeline_tool_unavailable_source_note(self):
        from xiaohuang.llm_reply_service import ReplyGenerationResult, TOOL_UNAVAILABLE_REPLY
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(
            enable_llm=True,
            llm_config=LlmReplyConfig(api_key="sk", base_url="https://x", model="m", timeout_seconds=15),
        )
        def fake_llm(_text, **_kw):
            return ReplyGenerationResult(TOOL_UNAVAILABLE_REPLY, "tool_unavailable")
        result = generate_reply_pipeline_result("打开浏览器", config, llm_reply_func=fake_llm)
        self.assertEqual(result.reply_source, "tool_unavailable")
        self.assertIn("不能执行工具", result.source_note or "")

    def test_pipeline_tts_disabled(self):
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        result = generate_reply_pipeline_result("你好", self._make_config(enable_tts=False))
        self.assertIsNone(result.tts_path)
        self.assertFalse(result.tts_played)
        self.assertIsNone(result.tts_error)

    def test_pipeline_tts_success(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True, tts_output_dir=Path("/tmp"))
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path):
            return True
        result = generate_reply_pipeline_result("你好", config, tts_func=fake_tts, play_audio_func=fake_play)
        self.assertEqual(result.tts_path, Path("/tmp/fake.mp3"))
        self.assertTrue(result.tts_played)
        self.assertIsNone(result.tts_error)

    def test_pipeline_tts_missing_dependency(self):
        from xiaohuang.tts_service import MissingTtsDependencyError
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True)
        def fake_tts(_text, _dir, **_kw):
            raise MissingTtsDependencyError("edge-tts missing")
        result = generate_reply_pipeline_result("你好", config, tts_func=fake_tts)
        self.assertTrue(len(result.reply_text) > 0)
        self.assertIn("edge-tts missing", result.tts_error or "")

    def test_pipeline_tts_playback_false(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True)
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path):
            return False
        result = generate_reply_pipeline_result("你好", config, tts_func=fake_tts, play_audio_func=fake_play)
        self.assertFalse(result.tts_played)
        self.assertIsNotNone(result.tts_error)

    def test_pipeline_source_note_compat(self):
        from xiaohuang.reply_pipeline_service import _source_note_for_source
        self.assertIsNone(_source_note_for_source("rule"))
        self.assertIsNone(_source_note_for_source("llm"))
        self.assertIn("未配置 key", _source_note_for_source("rule_fallback_no_key"))
        self.assertIn("不可用", _source_note_for_source("rule_fallback_error"))
        self.assertIn("返回为空", _source_note_for_source("rule_fallback_empty"))
        self.assertIn("被截断", _source_note_for_source("rule_fallback_length"))
        self.assertIn("不能执行工具", _source_note_for_source("tool_unavailable"))

    def test_pipeline_tts_exception_no_crash(self):
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True)
        def fake_tts(_text, _dir, **_kw):
            raise RuntimeError("boom")
        result = generate_reply_pipeline_result("你好", config, tts_func=fake_tts)
        self.assertTrue(len(result.reply_text) > 0)
        self.assertIn("TTS failed", result.tts_error or "")


    def test_pipeline_on_before_tts_called_with_reply_text(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True, tts_output_dir=Path("/tmp"))
        calls: list[str] = []
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path):
            return True
        generate_reply_pipeline_result(
            "你好", config,
            tts_func=fake_tts, play_audio_func=fake_play,
            on_before_tts=calls.append,
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("你好", calls[0])

    def test_pipeline_on_before_tts_not_called_when_tts_disabled(self):
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        calls: list[str] = []
        generate_reply_pipeline_result("你好", self._make_config(enable_tts=False), on_before_tts=calls.append)
        self.assertEqual(len(calls), 0)

    def test_pipeline_playback_warn_passed_to_play_func(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True, tts_output_dir=Path("/tmp"))
        warn_calls: list[str] = []
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path, warn=None):
            if warn:
                warn("test warning")
            return True
        result = generate_reply_pipeline_result(
            "你好", config,
            tts_func=fake_tts, play_audio_func=fake_play,
            playback_warn=lambda m: warn_calls.append(m),
        )
        self.assertTrue(result.tts_played)
        self.assertEqual(warn_calls, ["test warning"])

    def test_pipeline_old_play_func_without_warn_still_compatible(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True, tts_output_dir=Path("/tmp"))
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path):
            return True
        result = generate_reply_pipeline_result(
            "你好", config,
            tts_func=fake_tts, play_audio_func=fake_play,
            playback_warn=lambda _m: None,
        )
        self.assertTrue(result.tts_played)

    def test_pipeline_on_before_tts_exception_does_not_crash(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import generate_reply_pipeline_result
        config = self._make_config(enable_tts=True, tts_output_dir=Path("/tmp"))
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path):
            return True
        def bad_callback(_text):
            raise RuntimeError("callback boom")
        result = generate_reply_pipeline_result(
            "你好", config,
            tts_func=fake_tts, play_audio_func=fake_play,
            on_before_tts=bad_callback,
        )
        self.assertTrue(result.tts_played)


class V105TaskRouterTests(unittest.TestCase):
    def test_route_task_greeting_is_not_task(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("你好")
        self.assertFalse(result.is_task_request)
        self.assertFalse(result.can_execute)
        self.assertEqual(result.reason, "not_task")

    def test_route_task_open_browser_is_task(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("帮我打开浏览器")
        self.assertTrue(result.is_task_request)
        self.assertFalse(result.can_execute)
        self.assertEqual(result.reason, "not_implemented")

    def test_route_task_download_is_task(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("帮我下载资料")
        self.assertTrue(result.is_task_request)
        self.assertFalse(result.can_execute)

    def test_route_task_opencode_is_task(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("帮我用 opencode 写代码")
        self.assertTrue(result.is_task_request)
        self.assertFalse(result.can_execute)

    def test_route_task_empty_is_not_task(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("")
        self.assertFalse(result.is_task_request)

    def test_pipeline_task_request_skips_llm(self):
        from xiaohuang.llm_reply_service import LlmReplyConfig
        from xiaohuang.reply_pipeline_service import ReplyPipelineConfig, generate_reply_pipeline_result
        config = ReplyPipelineConfig(
            enable_llm=True, enable_tts=False,
            llm_config=LlmReplyConfig(api_key="sk", base_url="https://x", model="m", timeout_seconds=15),
        )
        llm_called = {"n": 0}
        def fake_llm(_text, **_kw):
            llm_called["n"] += 1
            return type("R", (), {"text": "x", "source": "llm"})()
        result = generate_reply_pipeline_result("帮我打开浏览器", config, llm_reply_func=fake_llm)
        self.assertEqual(llm_called["n"], 0)
        self.assertEqual(result.reply_source, "tool_unavailable")
        self.assertIn("不能执行工具", result.source_note or "")

    def test_pipeline_task_request_still_does_tts(self):
        from pathlib import Path
        from xiaohuang.reply_pipeline_service import ReplyPipelineConfig, generate_reply_pipeline_result
        config = ReplyPipelineConfig(enable_llm=False, enable_tts=True, tts_output_dir=Path("/tmp"))
        def fake_tts(_text, _dir, **_kw):
            return Path("/tmp/fake.mp3")
        def fake_play(_path):
            return True
        result = generate_reply_pipeline_result("帮我打开浏览器", config, tts_func=fake_tts, play_audio_func=fake_play)
        self.assertEqual(result.reply_source, "tool_unavailable")
        self.assertTrue(result.tts_played)
        self.assertEqual(result.tts_path, Path("/tmp/fake.mp3"))

    def test_pipeline_normal_chat_unchanged(self):
        from xiaohuang.reply_pipeline_service import ReplyPipelineConfig, generate_reply_pipeline_result
        result = generate_reply_pipeline_result("你好", ReplyPipelineConfig(enable_llm=False, enable_tts=False))
        self.assertEqual(result.reply_source, "rule")


class V111WakeDetectedCallbackTests(unittest.TestCase):
    def test_on_wake_detected_called_on_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording_dir = Path(temp_dir) / "data" / "recordings"
            called = {"n": 0}

            options = WakeLoopOptions(
                device_id=0, server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0, wake_phrases=["小黄"],
                max_seconds=10.0, silence_seconds=0.8,
                sample_rate=16000, channels=1, recording_dir=recording_dir,
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

            call_count = {"n": 0}
            def mode_stt(_path, _server_url, *, mode=None):
                call_count["n"] += 1
                return {"text": "小黄" if call_count["n"] == 1 else "测试"}

            run_wake_loop_once(
                options,
                record_wav_func=write_wav,
                record_until_silence_func=fake_vad,
                request_transcription_func=mode_stt,
                build_recording_path_func=fake_path,
                on_wake_detected=lambda: called.update(n=called["n"] + 1),
            )
            self.assertEqual(called["n"], 1)

    def test_on_wake_detected_not_called_on_no_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_dir = Path(temp_dir)
            recording_dir = tmp_dir / "recordings"
            called = {"on_wake_detected": 0}
            record_calls = []
            wake_path = tmp_dir / "wake.wav"
            wake_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

            options = WakeLoopOptions(
                device_id=0, server_url="http://127.0.0.1:8766",
                wake_window_seconds=0.1, wake_phrases=["小黄"],
                max_seconds=0.1, silence_seconds=0.1,
                sample_rate=16000, channels=1, recording_dir=recording_dir,
            )

            def fake_write_wav(*_args, **_kw):
                record_calls.append("wake_check")
                if len(record_calls) > 1:
                    raise AssertionError("command recording should not be called for no-match")
                return wake_path

            def no_wake_stt(_p, _s, *, mode=None):
                return {"text": "今天天气不错"}

            try:
                run_wake_loop_once(
                    options,
                    record_wav_func=fake_write_wav,
                    request_transcription_func=no_wake_stt,
                    on_wake_detected=lambda: called.update(on_wake_detected=called["on_wake_detected"] + 1),
                )
                self.fail("run_wake_loop_once should loop forever on no-match and be stopped")
            except AssertionError:
                pass

            self.assertEqual(called["on_wake_detected"], 0)

    def test_on_wake_detected_exception_does_not_block(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recording_dir = Path(temp_dir) / "data" / "recordings"
            options = WakeLoopOptions(
                device_id=0, server_url="http://127.0.0.1:8766",
                wake_window_seconds=2.0, wake_phrases=["小黄"],
                max_seconds=10.0, silence_seconds=0.8,
                sample_rate=16000, channels=1, recording_dir=recording_dir,
            )
            def fake_path(d):
                return Path(d) / f"{Path(d).name}.wav"
            def write_wav(o, **_kw):
                Path(o).parent.mkdir(parents=True, exist_ok=True); Path(o).write_bytes(b"RIFF\x00\x00\x00\x00WAVE"); return Path(o)
            def fake_vad(o, **_kw):
                write_wav(o); return SimpleNamespace(path=Path(o), duration_seconds=1.0, stop_reason="silence_after_speech")
            call_count = {"n": 0}
            def mode_stt(_p, _s, *, mode=None):
                call_count["n"] += 1
                return {"text": "小黄" if call_count["n"] == 1 else "测试"}
            def bad_callback():
                raise RuntimeError("boom")
            result = run_wake_loop_once(
                options, record_wav_func=write_wav, record_until_silence_func=fake_vad,
                request_transcription_func=mode_stt, build_recording_path_func=fake_path,
                on_wake_detected=bad_callback,
            )
            self.assertEqual(result.command_text, "测试")


class V111ResidentHiddenTests(unittest.TestCase):
    def test_voice_overlay_app_accepts_start_hidden(self):
        import importlib, threading
        try:
            import tkinter as tk
        except ImportError:
            raise unittest.SkipTest("Tkinter not available")
        root = tk.Tk()
        root.withdraw()
        try:
            from voice_overlay import VoiceOverlayApp
            stop = threading.Event()
            app = VoiceOverlayApp(root, stop_event=stop, debug=False, start_hidden=True)
            self.assertIsNotNone(app)
            app.close()
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def test_resident_hidden_in_help(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "scripts/voice_overlay.py", "--help"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        self.assertIn("--resident-hidden", result.stdout)


class V111SafePrintTests(unittest.TestCase):
    def test_safe_print_does_not_crash_on_emoji(self):
        from voice_overlay import _safe_print
        try:
            _safe_print("test \U0001f614 emoji")
        except UnicodeEncodeError:
            self.fail("_safe_print raised UnicodeEncodeError on emoji")


class V111DeepSeekDiagnosticsTests(unittest.TestCase):
    def test_http_error_debug_includes_status(self):
        import io
        from urllib.error import HTTPError
        from xiaohuang.llm_reply_service import _format_request_exception
        exc = HTTPError("https://api.deepseek.com/v1/chat", 502, "Bad Gateway", {}, io.BytesIO(b'{"error":"upstream"}'))
        msg = _format_request_exception(exc, None)
        self.assertIn("502", msg)

    def test_url_error_debug_includes_reason(self):
        from urllib.error import URLError
        from xiaohuang.llm_reply_service import _format_request_exception
        exc = URLError("connection refused")
        msg = _format_request_exception(exc, None)
        self.assertIn("connection refused", msg)

    def test_timeout_debug_includes_timeout(self):
        from xiaohuang.llm_reply_service import _format_request_exception
        exc = TimeoutError("timed out")
        msg = _format_request_exception(exc, None)
        self.assertIn("Timeout", msg)

    def test_format_exception_does_not_leak_key(self):
        import io
        from urllib.error import HTTPError
        from xiaohuang.llm_reply_service import _format_request_exception
        exc = HTTPError("https://api.example.com?api_key=sk-secret123", 502, "Err", {}, io.BytesIO(b"{}"))
        msg = _format_request_exception(exc, None)
        self.assertNotIn("sk-secret123", msg)
        self.assertIn("REDACTED", msg)

    def test_json_decode_error_debug_clear(self):
        from xiaohuang.llm_reply_service import generate_llm_reply_result, LlmReplyConfig
        calls: list[str] = []
        config = LlmReplyConfig(api_key="secret", base_url="https://x", model="m", timeout_seconds=15)
        def bad_json(_url, _payload, _headers, _timeout):
            import json
            raise json.JSONDecodeError("msg", "doc", 0)
        result = generate_llm_reply_result("测试", config=config, post_json_func=bad_json, on_debug=calls.append)
        self.assertEqual(result.source, "rule_fallback_error")
        self.assertEqual(len(calls), 1)
        self.assertIn("JSONDecodeError", calls[0])


class V111ConversationSessionTests(unittest.TestCase):
    def test_normalize_removes_punctuation_and_spaces(self):
        from xiaohuang.conversation_session_service import normalize_session_text
        self.assertEqual(normalize_session_text(" 好，了。！"), "好了")

    def test_is_exit_text_recognizes_exit_phrases(self):
        from xiaohuang.conversation_session_service import is_session_exit_text
        for phrase in ["好了", "没事了", "退出", "休息吧", "可以了"]:
            with self.subTest(phrase=phrase):
                self.assertTrue(is_session_exit_text(phrase), f"Should be exit: {phrase}")

    def test_is_exit_text_not_false_positive(self):
        from xiaohuang.conversation_session_service import is_session_exit_text
        for phrase in ["你好", "今天天气不错", "毛泽东是谁"]:
            with self.subTest(phrase=phrase):
                self.assertFalse(is_session_exit_text(phrase), f"Should not be exit: {phrase}")

    def test_should_continue_disabled_returns_false(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=False)
        self.assertFalse(should_continue_session(1, config))

    def test_should_continue_over_max_turns_returns_false(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True, max_turns=3)
        self.assertFalse(should_continue_session(3, config))

    def test_should_continue_under_max_turns_returns_true(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True, max_turns=3)
        self.assertTrue(should_continue_session(2, config))


class V111SessionRecordTests(unittest.TestCase):
    def test_record_command_transcribe_uses_command_mode(self):
        import tempfile, logging
        from types import SimpleNamespace
        from pathlib import Path
        from xiaohuang.command_runtime_service import record_command_transcribe as _record_command_transcribe
        from xiaohuang.wake_loop_service import STT_MODE_COMMAND

        modes: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "cmd.wav"
            wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")

            def fake_record(output_path, **kwargs):
                return SimpleNamespace(path=Path(output_path), duration_seconds=0.5, stop_reason="silence")
            def fake_transcribe(path, server_url):
                return {"text": "那邓小平呢？"}

            opts = SimpleNamespace(
                device_id=0, server_url="http://127.0.0.1:8766",
                sample_rate=16000, channels=1, silence_seconds=0.2,
                recording_dir=Path(tmp),
            )
            logger = logging.getLogger("test")
            text = _record_command_transcribe(
                options=opts, max_seconds=1.0,
                debug=False, logger=logger, record_func=fake_record,
                transcribe_func=fake_transcribe,
            )
            self.assertEqual(text, "那邓小平呢？")


class V111ReplyPipelineResultImportTests(unittest.TestCase):
    def test_reply_pipeline_result_importable(self):
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult
        result = ReplyPipelineResult(
            reply_text="好的，我先待命。",
            reply_source="session_exit",
            source_note=None,
        )
        self.assertEqual(result.reply_text, "好的，我先待命。")
        self.assertEqual(result.reply_source, "session_exit")


class V111NoSpeechTests(unittest.TestCase):
    def test_transcribe_returns_empty_string_for_no_speech(self):
        import tempfile
        from pathlib import Path
        from xiaohuang.stt_service import SenseVoiceTranscriber

        class FakeModel:
            def generate(self, **kwargs):
                return [{"key": "test", "text": "", "timestamp": []}]

        class FakeFunASR:
            class AutoModel:
                def __new__(cls, **kwargs):
                    return FakeModel()

        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "s.wav"
            wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            t = SenseVoiceTranscriber(funasr_module=FakeFunASR, postprocess_func=lambda x: x)
            result = t.transcribe(wav)
            self.assertEqual(result, "")

    def test_transcribe_raises_on_model_error(self):
        import tempfile
        from pathlib import Path
        from xiaohuang.stt_service import SenseVoiceTranscriber, TranscriptionError

        class CrashModel:
            def generate(self, **kwargs):
                raise RuntimeError("model crash")

        class FakeFunASR:
            class AutoModel:
                def __new__(cls, **kwargs):
                    return CrashModel()

        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "s.wav"
            wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            t = SenseVoiceTranscriber(funasr_module=FakeFunASR, postprocess_func=lambda x: x)
            with self.assertRaises(TranscriptionError):
                t.transcribe(wav)

    def test_no_speech_does_not_affect_stt_client(self):
        from xiaohuang.stt_client_service import _parse_response_body
        body = '{"ok": true, "request_id": "r", "type": "command", "text": "", "error": null, "meta": {"no_speech": true, "empty_text": true}}'
        data = _parse_response_body(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["text"], "")
        self.assertTrue(data["meta"]["no_speech"])


class V111TtsBackgroundPlaybackTests(unittest.TestCase):
    def test_play_audio_file_missing_returns_false(self):
        import tempfile
        from xiaohuang.audio_playback_service import play_audio_file
        warns: list[str] = []
        result = play_audio_file(Path("nonexistent.mp3"), warn=warns.append)
        self.assertFalse(result)
        self.assertTrue(len(warns) > 0)

    def test_play_audio_file_mci_success(self):
        import tempfile
        from unittest.mock import patch
        from xiaohuang.audio_playback_service import play_audio_file
        with tempfile.TemporaryDirectory() as d:
            mp3 = Path(d) / "test.mp3"
            mp3.write_bytes(b"fake mp3")
            with patch("xiaohuang.audio_playback_service._mci_send") as mock_mci:
                result = play_audio_file(mp3)
                self.assertTrue(result)
                commands = [c[0][0] for c in mock_mci.call_args_list]
                self.assertTrue(any("open" in c for c in commands))
                self.assertTrue(any("play" in c for c in commands))
                self.assertTrue(any("close" in c for c in commands))

    def test_play_audio_file_mci_failure_returns_false(self):
        import tempfile
        from unittest.mock import patch
        from xiaohuang.audio_playback_service import play_audio_file
        warns: list[str] = []
        with tempfile.TemporaryDirectory() as d:
            mp3 = Path(d) / "test.mp3"
            mp3.write_bytes(b"fake mp3")
            with patch("xiaohuang.audio_playback_service._mci_send", side_effect=OSError("MCI error: device not ready")):
                result = play_audio_file(mp3, warn=warns.append)
                self.assertFalse(result)
                self.assertTrue(any("playback failed" in w for w in warns))


class V112LatencyMetricsTests(unittest.TestCase):
    def test_tracker_start_end_produces_ms(self):
        from xiaohuang.latency_metrics_service import LatencyTracker
        t = LatencyTracker(clock=iter([0.0, 0.25]).__next__)
        t.start("test")
        t.end("test")
        self.assertEqual(t.summary_ms(), {"test": 250.0})

    def test_tracker_end_without_start_no_crash(self):
        from xiaohuang.latency_metrics_service import LatencyTracker
        t = LatencyTracker()
        t.end("nonexistent")
        self.assertEqual(t.summary_ms(), {})

    def test_tracker_double_end_no_change(self):
        from xiaohuang.latency_metrics_service import LatencyTracker
        clock = iter([0.0, 0.1, 0.3]).__next__
        t = LatencyTracker(clock=clock)
        t.start("x")
        t.end("x")
        t.end("x")
        self.assertEqual(t.summary_ms(), {"x": 100.0})

    def test_format_latency_summary_output(self):
        from xiaohuang.latency_metrics_service import format_latency_summary
        s = format_latency_summary({"llm_ms": 820.5, "turn_total_ms": 9820.4}, turn=1, source="llm")
        self.assertIn("turn=1", s)
        self.assertIn("source=llm", s)
        self.assertIn("llm_ms=820.5", s)
        self.assertIn("Overlay latency:", s)

    def test_format_latency_summary_no_none(self):
        from xiaohuang.latency_metrics_service import format_latency_summary
        s = format_latency_summary({}, turn=1)
        self.assertNotIn("None", s)


class V112AdaptiveFollowupTests(unittest.TestCase):
    def test_followup_timeout_default(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, get_followup_timeout_seconds
        config = ConversationSessionConfig()
        self.assertEqual(get_followup_timeout_seconds(config), 12.0)

    def test_followup_timeout_fallback_to_timeout(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, get_followup_timeout_seconds
        config = ConversationSessionConfig(followup_timeout_seconds=0, timeout_seconds=30)
        self.assertEqual(get_followup_timeout_seconds(config), 30.0)

    def test_should_continue_max_session_seconds(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True, max_turns=10, max_session_seconds=60)
        self.assertFalse(should_continue_session(1, config, elapsed_seconds=61))

    def test_should_continue_no_speech_retries(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True, max_no_speech_retries=1)
        self.assertFalse(should_continue_session(1, config, no_speech_retries=2))

    def test_should_exit_for_no_speech(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_exit_for_no_speech
        config = ConversationSessionConfig(max_no_speech_retries=1)
        self.assertTrue(should_exit_for_no_speech(1, config))
        self.assertFalse(should_exit_for_no_speech(0, config))
        config2 = ConversationSessionConfig(max_no_speech_retries=2)
        self.assertFalse(should_exit_for_no_speech(1, config2))
        self.assertTrue(should_exit_for_no_speech(2, config2))

    def test_old_should_continue_signature_still_works(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True, max_turns=3)
        self.assertTrue(should_continue_session(2, config))


class V112DirectListeningTests(unittest.TestCase):
    def test_single_turn_cooldown_unchanged_without_session(self):
        from xiaohuang.overlay_runtime_service import resolve_post_response_cooldown
        self.assertGreater(resolve_post_response_cooldown(enable_tts=True, requested_seconds=None), 0)
        self.assertGreater(resolve_post_response_cooldown(enable_tts=False, requested_seconds=None), 0)

    def test_session_skip_result_hold_still_passes_pipeline(self):
        from xiaohuang.reply_pipeline_service import ReplyPipelineConfig, generate_reply_pipeline_result
        result = generate_reply_pipeline_result("你好", ReplyPipelineConfig(enable_llm=False, enable_tts=False))
        self.assertIsNotNone(result.reply_text)


class V112SessionDefaultsTests(unittest.TestCase):
    def test_default_followup_timeout_is_12(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, get_followup_timeout_seconds
        self.assertEqual(get_followup_timeout_seconds(ConversationSessionConfig()), 12.0)

    def test_default_max_turns_is_12(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        self.assertEqual(ConversationSessionConfig().max_turns, 12)

    def test_default_max_session_seconds_is_300(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        self.assertEqual(ConversationSessionConfig().max_session_seconds, 300.0)

    def test_default_max_no_speech_retries_is_2(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        self.assertEqual(ConversationSessionConfig().max_no_speech_retries, 2)

    def test_should_continue_at_turn_11(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True)
        self.assertTrue(should_continue_session(11, config))

    def test_should_continue_stops_at_turn_12(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, should_continue_session
        config = ConversationSessionConfig(enabled=True)
        self.assertFalse(should_continue_session(12, config))

    def test_end_reason_max_turns(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, get_session_end_reason
        config = ConversationSessionConfig(max_turns=12)
        self.assertEqual(get_session_end_reason(turn_count=12, config=config, elapsed_seconds=0, no_speech_retries=0), "max_turns")

    def test_end_reason_exit_phrase(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, get_session_end_reason
        config = ConversationSessionConfig()
        self.assertEqual(get_session_end_reason(turn_count=1, config=config, elapsed_seconds=0, no_speech_retries=0, exit_phrase_detected=True), "exit_phrase")

    def test_end_reason_no_speech(self):
        from xiaohuang.conversation_session_service import ConversationSessionConfig, get_session_end_reason
        config = ConversationSessionConfig(max_no_speech_retries=2)
        self.assertEqual(get_session_end_reason(turn_count=1, config=config, elapsed_seconds=0, no_speech_retries=3), "no_speech")


class V113AppConfigTests(unittest.TestCase):
    def test_load_config_no_file_returns_default(self):
        from xiaohuang.app_config_service import load_config
        cfg = load_config(Path("/nonexistent/config.json"))
        self.assertEqual(cfg.wake.phrases, ["小黄"])

    def test_load_config_valid_json_overrides_wake_phrase(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text(json.dumps({"wake": {"phrases": ["贾维斯"]}}), encoding="utf-8")
            cfg = load_config(fp)
            self.assertEqual(cfg.wake.phrases, ["贾维斯"])

    def test_load_config_invalid_json_warns_and_returns_default(self):
        import tempfile
        from xiaohuang.app_config_service import load_config
        warns: list[str] = []
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text("{invalid", encoding="utf-8")
            cfg = load_config(fp, warn=warns.append)
            self.assertEqual(cfg.wake.phrases, ["小黄"])
            self.assertTrue(len(warns) > 0)

    def test_phrase_string_converted_to_list(self):
        from xiaohuang.app_config_service import _coerce_phrases
        self.assertEqual(_coerce_phrases("贾维斯"), ["贾维斯"])

    def test_phrase_empty_list_fallback(self):
        from xiaohuang.app_config_service import _coerce_phrases
        self.assertIsNone(_coerce_phrases([]))

    def test_tts_voice_overridden(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text(json.dumps({"tts": {"voice": "zh-CN-YunxiNeural"}}), encoding="utf-8")
            cfg = load_config(fp)
            self.assertEqual(cfg.tts.voice, "zh-CN-YunxiNeural")


class V113WakeConfigOverrideTests(unittest.TestCase):
    def test_config_wake_phrases_replace_default(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config as load_user_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "c.json"
            fp.write_text(json.dumps({"wake": {"phrases": ["贾维斯"]}}), encoding="utf-8")
            cfg = load_user_config(fp)
            self.assertEqual(cfg.wake.phrases, ["贾维斯"])
            self.assertNotIn("小黄", cfg.wake.phrases)

    def test_config_wake_aliases_replace_default(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config as load_user_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "c.json"
            fp.write_text(json.dumps({"wake": {"aliases": ["嘉维斯"]}}), encoding="utf-8")
            cfg = load_user_config(fp)
            self.assertEqual(cfg.wake.aliases, ["嘉维斯"])

    def test_cli_none_preserves_config_wake_phrases(self):
        import argparse
        from xiaohuang.app_config_service import apply_cli_overrides, get_default_config
        parser = argparse.ArgumentParser()
        for a in ['wake-phrases','wake-aliases','wake-window-seconds','device','max-seconds','silence-seconds','enable-llm','enable-tts','debug','resident-hidden','conversation-session','llm-model','llm-base-url','llm-timeout','llm-max-tokens','tts-voice','tts-output-dir','post-response-cooldown','session-timeout','max-session-turns','followup-timeout','max-session-seconds','max-no-speech-retries']:
            parser.add_argument(f'--{a}', default=None)
        args = parser.parse_args([])
        cfg = apply_cli_overrides(get_default_config(), args)
        self.assertEqual(cfg.wake.phrases, ["小黄"])


class V113AssistantConfigTests(unittest.TestCase):
    def test_default_assistant_name_is_xiaohuang(self):
        from xiaohuang.app_config_service import get_default_config
        cfg = get_default_config()
        self.assertEqual(cfg.assistant.name, "小黄")
        self.assertEqual(cfg.assistant.display_name, "小黄")

    def test_config_assistant_name_can_be_jarvis(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text(json.dumps({"assistant": {"name": "贾维斯", "display_name": "贾维斯"}}), encoding="utf-8")
            cfg = load_config(fp)
            self.assertEqual(cfg.assistant.name, "贾维斯")
            self.assertEqual(cfg.assistant.display_name, "贾维斯")

    def test_config_assistant_persona_can_override_default(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config
        persona_text = "你是贾维斯，一个简洁可靠的 Windows 桌面语音助手。"
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text(json.dumps({"assistant": {"persona": persona_text}}), encoding="utf-8")
            cfg = load_config(fp)
            self.assertEqual(cfg.assistant.persona, persona_text)

    def test_invalid_assistant_name_falls_back_default(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config
        warns: list[str] = []
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text(json.dumps({"assistant": {"name": "", "display_name": ""}}), encoding="utf-8")
            cfg = load_config(fp, warn=warns.append)
            self.assertEqual(cfg.assistant.name, "小黄")
            self.assertEqual(cfg.assistant.display_name, "小黄")

    def test_reply_prompt_uses_assistant_persona(self):
        from xiaohuang.llm_reply_service import build_deepseek_request
        persona = "你是贾维斯，一个简洁可靠的 Windows 桌面语音助手。"
        req = build_deepseek_request("你是谁", model="test-model", persona=persona)
        sys_msg = req["messages"][0]
        self.assertEqual(sys_msg["role"], "system")
        self.assertEqual(sys_msg["content"], persona)
        self.assertNotIn("小黄", sys_msg["content"])

    def test_wake_phrase_and_assistant_name_are_independent(self):
        import tempfile, json
        from xiaohuang.app_config_service import load_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "config.json"
            fp.write_text(json.dumps({
                "wake": {"phrases": ["贾维斯"]},
                "assistant": {"name": "小黄", "display_name": "小黄"},
            }), encoding="utf-8")
            cfg = load_config(fp)
            self.assertEqual(cfg.wake.phrases, ["贾维斯"])
            self.assertEqual(cfg.assistant.name, "小黄")
            self.assertNotIn("小黄", cfg.wake.phrases)


class V113BLlmProviderRouterTests(unittest.TestCase):
    def test_provider_deepseek_loads_api_key_from_env(self):
        from xiaohuang.llm_reply_service import load_llm_provider_config
        from types import SimpleNamespace
        app_cfg = SimpleNamespace(
            provider="deepseek", model="deepseek-v4-flash",
            base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY",
            timeout_seconds=20, max_tokens=256, temperature=0.4,
        )
        cfg = load_llm_provider_config(app_cfg, env={"DEEPSEEK_API_KEY": "sk-test"})
        self.assertTrue(cfg.is_configured)
        self.assertEqual(cfg.provider, "deepseek")
        self.assertEqual(cfg.model, "deepseek-v4-flash")

    def test_provider_qwen_uses_qwen_defaults(self):
        from xiaohuang.llm_reply_service import load_llm_provider_config
        from types import SimpleNamespace
        app_cfg = SimpleNamespace(
            provider="qwen", model="qwen-turbo",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="QWEN_API_KEY", timeout_seconds=20, max_tokens=256, temperature=0.4,
        )
        cfg = load_llm_provider_config(app_cfg, env={"QWEN_API_KEY": "sk-qwen"})
        self.assertTrue(cfg.is_configured)
        self.assertEqual(cfg.provider, "qwen")
        self.assertEqual(cfg.base_url.rstrip("/"), "https://dashscope.aliyuncs.com/compatible-mode/v1")

    def test_provider_doubao_uses_doubao_defaults(self):
        from xiaohuang.llm_reply_service import load_llm_provider_config
        from types import SimpleNamespace
        app_cfg = SimpleNamespace(
            provider="doubao", model="doubao-lite-32k",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key_env="DOUBAO_API_KEY", timeout_seconds=20, max_tokens=256, temperature=0.4,
        )
        cfg = load_llm_provider_config(app_cfg, env={"DOUBAO_API_KEY": "sk-doubao"})
        self.assertTrue(cfg.is_configured)
        self.assertEqual(cfg.provider, "doubao")

    def test_provider_openai_compatible_works(self):
        from xiaohuang.llm_reply_service import load_llm_provider_config
        from types import SimpleNamespace
        app_cfg = SimpleNamespace(
            provider="openai_compatible", model="default",
            base_url="http://127.0.0.1:8080/v1", api_key_env="OPENAI_API_KEY",
            timeout_seconds=20, max_tokens=256, temperature=0.4,
        )
        cfg = load_llm_provider_config(app_cfg, env={"OPENAI_API_KEY": "sk-openai"})
        self.assertTrue(cfg.is_configured)
        self.assertEqual(cfg.provider, "openai_compatible")

    def test_missing_api_key_env_falls_back_gracefully(self):
        from xiaohuang.llm_reply_service import load_llm_provider_config
        from types import SimpleNamespace
        app_cfg = SimpleNamespace(
            provider="qwen", model="qwen-turbo",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="QWEN_API_KEY", timeout_seconds=20, max_tokens=256, temperature=0.4,
        )
        cfg = load_llm_provider_config(app_cfg, env={})
        self.assertFalse(cfg.is_configured)
        self.assertIsNone(cfg.api_key)

    def test_config_temperature_flows_to_llm_request(self):
        from xiaohuang.llm_reply_service import build_openai_compatible_chat_request
        req = build_openai_compatible_chat_request(
            "你好", model="test", temperature=0.9, provider="qwen",
        )
        self.assertEqual(req["temperature"], 0.9)
        self.assertNotIn("thinking", req)

    def test_deepseek_request_includes_thinking_disabled(self):
        from xiaohuang.llm_reply_service import build_openai_compatible_chat_request
        req = build_openai_compatible_chat_request(
            "你好", model="deepseek-v4-flash", provider="deepseek",
        )
        self.assertIn("thinking", req)
        self.assertEqual(req["thinking"], {"type": "disabled"})

    def test_build_deepseek_request_backward_compat(self):
        from xiaohuang.llm_reply_service import build_deepseek_request
        req = build_deepseek_request("测试", model="deepseek-chat")
        self.assertEqual(req["model"], "deepseek-chat")
        self.assertIn("thinking", req)

    def test_persona_flows_to_openai_compatible_request(self):
        from xiaohuang.llm_reply_service import build_openai_compatible_chat_request
        persona = "你是贾维斯。"
        req = build_openai_compatible_chat_request(
            "你是谁", model="test", persona=persona, provider="qwen",
        )
        self.assertEqual(req["messages"][0]["content"], persona)

    def test_api_key_not_leaked_in_config(self):
        from xiaohuang.llm_reply_service import load_llm_provider_config
        from types import SimpleNamespace
        app_cfg = SimpleNamespace(
            provider="deepseek", model="deepseek-v4-flash",
            base_url="https://api.deepseek.com", api_key_env="DEEPSEEK_API_KEY",
            timeout_seconds=20, max_tokens=256, temperature=0.4,
        )
        cfg = load_llm_provider_config(app_cfg, env={"DEEPSEEK_API_KEY": "sk-secret-abc"})
        self.assertEqual(cfg.api_key, "sk-secret-abc")
        # api_key is in the config object but never logged to output
        self.assertNotIn("sk-secret-abc", str(cfg.base_url))
        self.assertNotIn("sk-secret-abc", str(cfg.model))

    def test_cli_args_dont_override_config_when_not_passed(self):
        import argparse
        from xiaohuang.app_config_service import get_default_config, apply_cli_overrides
        parser = argparse.ArgumentParser()
        for a in ['wake-phrases','wake-aliases','wake-window-seconds','device','max-seconds','silence-seconds','enable-llm','enable-tts','debug','resident-hidden','conversation-session','llm-model','llm-base-url','llm-timeout','llm-max-tokens','tts-voice','tts-output-dir','post-response-cooldown','session-timeout','max-session-turns','followup-timeout','max-session-seconds','max-no-speech-retries']:
            parser.add_argument(f'--{a}', default=None)
        args = parser.parse_args([])
        cfg = apply_cli_overrides(get_default_config(), args)
        self.assertEqual(cfg.llm.model, "deepseek-v4-flash")
        self.assertEqual(cfg.llm.base_url, "https://api.deepseek.com")


class V113CSettingsConfigFileServiceTests(unittest.TestCase):
    def test_load_missing_config_returns_defaults(self):
        from xiaohuang.settings_config_file_service import load_config_with_unknown
        data, err = load_config_with_unknown(Path("/nonexistent/xyz.json"))
        self.assertIsNone(err)
        self.assertIn("wake", data)
        self.assertIn("assistant", data)

    def test_save_and_preserve_unknown_fields(self):
        import tempfile, json
        from xiaohuang.settings_config_file_service import save_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "orig.json"
            orig = {"wake": {"phrases": ["小黄"]}, "custom_section": {"foo": "bar"}}
            fp.write_text(json.dumps(orig, ensure_ascii=False), encoding="utf-8")

            new_data = {"wake": {"phrases": ["贾维斯"]}}
            err = save_config(fp, new_data, original_data=orig)
            self.assertIsNone(err)

            loaded = json.loads(fp.read_text(encoding="utf-8"))
            self.assertEqual(loaded["wake"]["phrases"], ["贾维斯"])
            self.assertEqual(loaded["custom_section"]["foo"], "bar")

    def test_parse_list_from_comma_string(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"wake": {"phrases": "贾维斯, 小黄", "aliases": "贾"}}
        result, errs = normalize_ui_inputs(data)
        self.assertEqual(result["wake"]["phrases"], ["贾维斯", "小黄"])
        self.assertEqual(result["wake"]["aliases"], ["贾"])
        self.assertEqual(len(errs), 0)

    def test_parse_list_from_chinese_comma(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"wake": {"phrases": "贾维斯，小黄"}}
        result, errs = normalize_ui_inputs(data)
        self.assertEqual(result["wake"]["phrases"], ["贾维斯", "小黄"])

    def test_empty_wake_phrases_rejected(self):
        from xiaohuang.settings_config_file_service import validate_config
        v = validate_config({"wake": {"phrases": []}})
        self.assertFalse(v.valid)
        self.assertTrue(any("不能为空" in e for e in v.errors))

    def test_api_key_env_rejects_sk_prefix(self):
        from xiaohuang.settings_config_file_service import validate_config
        v = validate_config({"llm": {"api_key_env": "sk-abc123def456"}})
        self.assertFalse(v.valid)
        self.assertTrue(any("疑似真实 API key" in e for e in v.errors))

    def test_api_key_env_rejects_long_secret(self):
        from xiaohuang.settings_config_file_service import validate_config
        v = validate_config({"llm": {"api_key_env": "a" * 60}})
        self.assertFalse(v.valid)

    def test_api_key_env_allows_valid_env_name(self):
        from xiaohuang.settings_config_file_service import validate_config
        v = validate_config({"llm": {"api_key_env": "DEEPSEEK_API_KEY"}})
        self.assertTrue(v.valid)

    def test_provider_must_be_valid(self):
        from xiaohuang.settings_config_file_service import validate_config
        v = validate_config({"llm": {"provider": "anthropic"}})
        self.assertFalse(v.valid)
        self.assertTrue(any("无效" in e for e in v.errors))

    def test_number_range_validated(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"llm": {"temperature": "5.0"}}
        _, errs = normalize_ui_inputs(data)
        self.assertTrue(any("应在" in e for e in errs))

    def test_bool_fields_normalized(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"llm": {"enabled": False}, "tts": {"enabled": True}}
        result, errs = normalize_ui_inputs(data)
        self.assertEqual(result["llm"]["enabled"], False)
        self.assertEqual(result["tts"]["enabled"], True)

    def test_overlay_post_response_cooldown_none_string_normalized(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"overlay": {"post_response_cooldown": "None"}}
        result, errs = normalize_ui_inputs(data)
        self.assertEqual(errs, [])
        self.assertIsNone(result["overlay"]["post_response_cooldown"])

    def test_overlay_post_response_cooldown_blank_normalized(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"overlay": {"post_response_cooldown": ""}}
        result, errs = normalize_ui_inputs(data)
        self.assertEqual(errs, [])
        self.assertIsNone(result["overlay"]["post_response_cooldown"])

    def test_overlay_post_response_cooldown_number_normalized(self):
        from xiaohuang.settings_config_file_service import normalize_ui_inputs
        data = {"overlay": {"post_response_cooldown": "8.5"}}
        result, errs = normalize_ui_inputs(data)
        self.assertEqual(errs, [])
        self.assertEqual(result["overlay"]["post_response_cooldown"], 8.5)

    def test_save_creates_parent_dir(self):
        import tempfile
        from xiaohuang.settings_config_file_service import save_config
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "sub" / "deep" / "config.json"
            err = save_config(fp, {"wake": {"phrases": ["test"]}})
            self.assertIsNone(err)
            self.assertTrue(fp.exists())


if __name__ == "__main__":
    unittest.main()
