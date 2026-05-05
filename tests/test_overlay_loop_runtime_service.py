from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xiaohuang.conversation_session_service import ConversationSessionConfig
from xiaohuang.latency_metrics_service import LatencyTracker
from xiaohuang.reply_pipeline_service import ReplyPipelineConfig
from xiaohuang.wake_loop_service import WakeLoopOptions, WakeLoopResult


class FakeApp:
    def __init__(self):
        self.states: list[tuple[str, str | None]] = []
        self.overlay_shown = False
        self.overlay_hidden = False

    def thread_safe_set_state(self, state: str, detail: str | None = None) -> None:
        self.states.append((state, detail))

    def show_overlay(self) -> None:
        self.overlay_shown = True

    def hide_overlay(self) -> None:
        self.overlay_hidden = True

    @property
    def assistant_name(self) -> str:
        return "小黄"


class FakeLogger:
    def __init__(self):
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def info(self, msg, *args):
        self.infos.append(msg % args if args else msg)

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    def error(self, msg, *args):
        self.errors.append(msg % args if args else msg)

    def exception(self, msg, *args):
        self.errors.append(msg % args if args else msg)

    @property
    def text(self) -> str:
        return " ".join(self.infos + self.warnings + self.errors)


def _fake_wake_result(command_text="hello") -> WakeLoopResult:
    return WakeLoopResult(
        wake_text="test_wake",
        command_text=command_text,
        command_path=Path("/tmp/fake.wav"),
        actual_recording_seconds=1.0,
        stop_reason="silence",
    )


def _fake_tracker():
    return LatencyTracker(clock=iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5]).__next__)


def _fake_pipeline_config():
    return ReplyPipelineConfig(enable_llm=False, enable_tts=False)


def _fake_runtime_config(**kw):
    from xiaohuang.overlay_loop_runtime_service import OverlayLoopRuntimeConfig
    from xiaohuang.wake_runtime_service import WAKE_ENGINE_STT_TEXT

    defaults = dict(
        wake_engine_mode=WAKE_ENGINE_STT_TEXT,
        wake_engine_runtime=None,
        session_config=ConversationSessionConfig(enabled=False),
        debug=False,
    )
    defaults.update(kw)
    return OverlayLoopRuntimeConfig(**defaults)


def _fake_options():
    return WakeLoopOptions(
        device_id=0,
        server_url="http://127.0.0.1:8766",
        wake_window_seconds=0.5,
        wake_phrases=["小黄"],
        max_seconds=2.0,
        silence_seconds=0.5,
        sample_rate=16000,
        channels=1,
        recording_dir=Path("/tmp"),
    )


class V12HBOverlayLoopRuntimeTests(unittest.TestCase):
    """Tests for overlay_loop_runtime_service."""

    # ------------------------------------------------------------------
    # stt_text path
    # ------------------------------------------------------------------

    def test_stt_text_path_calls_assistant_turn(self):
        from xiaohuang.overlay_loop_runtime_service import run_overlay_runtime

        app = FakeApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        options = _fake_options()
        rt_config = _fake_runtime_config()
        pipeline_config = _fake_pipeline_config()

        with patch(
            "xiaohuang.overlay_loop_runtime_service.run_wake_loop_once",
            return_value=_fake_wake_result("say hi"),
        ):
            with patch(
                "xiaohuang.overlay_loop_runtime_service.run_assistant_turn_from_command",
                return_value=False,
            ) as mock_turn:
                run_overlay_runtime(
                    app=app,
                    stop_event=stop_event,
                    logger=logger,
                    options=options,
                    runtime_config=rt_config,
                    pipeline_config=pipeline_config,
                    record_openwakeword_command=lambda **kw: _fake_wake_result(),
                    make_llm_debug_handler=lambda logger, debug: None,
                    playback_warning=lambda msg: None,
                    log_warning=lambda msg: None,
                )

        mock_turn.assert_called_once()
        self.assertEqual(mock_turn.call_args[1]["command_text"], "say hi")

    # ------------------------------------------------------------------
    # empty command_text continues loop
    # ------------------------------------------------------------------

    def test_empty_command_continues_loop(self):
        from xiaohuang.overlay_loop_runtime_service import run_overlay_runtime

        app = FakeApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        options = _fake_options()
        rt_config = _fake_runtime_config()
        pipeline_config = _fake_pipeline_config()

        with patch(
            "xiaohuang.overlay_loop_runtime_service.run_wake_loop_once",
        ) as mock_wake:
            mock_wake.side_effect = [
                _fake_wake_result(""),  # first: empty → continue
                _fake_wake_result("ok"),  # second: goes to turn
            ]

            with patch(
                "xiaohuang.overlay_loop_runtime_service.run_assistant_turn_from_command",
                return_value=False,
            ) as mock_turn:
                run_overlay_runtime(
                    app=app,
                    stop_event=stop_event,
                    logger=logger,
                    options=options,
                    runtime_config=rt_config,
                    pipeline_config=pipeline_config,
                    record_openwakeword_command=lambda **kw: _fake_wake_result(),
                    make_llm_debug_handler=lambda logger, debug: None,
                    playback_warning=lambda msg: None,
                    log_warning=lambda msg: None,
                )

        mock_turn.assert_called_once()
        # First call was with empty text, should have been skipped by run_assistant_turn_from_command

    # ------------------------------------------------------------------
    # stop_event
    # ------------------------------------------------------------------

    def test_stop_event_breaks_loop(self):
        from xiaohuang.overlay_loop_runtime_service import run_overlay_runtime

        app = FakeApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        options = _fake_options()
        rt_config = _fake_runtime_config()
        pipeline_config = _fake_pipeline_config()

        call_count = [0]

        with patch(
            "xiaohuang.overlay_loop_runtime_service.run_wake_loop_once",
            return_value=_fake_wake_result("hello"),
        ):
            with patch(
                "xiaohuang.overlay_loop_runtime_service.run_assistant_turn_from_command",
                return_value=False,
            ):
                def wait_then_stop(s):
                    call_count[0] += 1
                    if call_count[0] >= 3:
                        stop_event.set()
                    return False

                run_overlay_runtime(
                    app=app,
                    stop_event=stop_event,
                    logger=logger,
                    options=options,
                    runtime_config=rt_config,
                    pipeline_config=pipeline_config,
                    record_openwakeword_command=lambda **kw: _fake_wake_result(),
                    make_llm_debug_handler=lambda logger, debug: None,
                    playback_warning=lambda msg: None,
                    log_warning=lambda msg: None,
                )

    # ------------------------------------------------------------------
    # SttServerUnavailable error
    # ------------------------------------------------------------------

    def test_stt_unavailable_sets_error_state(self):
        from xiaohuang.overlay_loop_runtime_service import run_overlay_runtime
        from xiaohuang.stt_client_service import SttServerUnavailable

        app = FakeApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        options = _fake_options()
        rt_config = _fake_runtime_config()
        pipeline_config = _fake_pipeline_config()

        side_effects = [
            _fake_wake_result("hello"),
            SttServerUnavailable("server down"),
        ]
        with patch(
            "xiaohuang.overlay_loop_runtime_service.run_wake_loop_once",
            side_effect=side_effects,
        ):
            run_overlay_runtime(
                app=app,
                stop_event=stop_event,
                logger=logger,
                options=options,
                runtime_config=rt_config,
                pipeline_config=pipeline_config,
                record_openwakeword_command=lambda **kw: _fake_wake_result(),
                make_llm_debug_handler=lambda logger, debug: None,
                playback_warning=lambda msg: None,
                log_warning=lambda msg: None,
            )

        # Should have at least one error state
        error_states = [s for s in app.states if s[0] == "error"]
        self.assertGreater(len(error_states), 0)

    # ------------------------------------------------------------------
    # general Exception error
    # ------------------------------------------------------------------

    def test_general_exception_sets_error_state(self):
        from xiaohuang.overlay_loop_runtime_service import run_overlay_runtime

        app = FakeApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        options = _fake_options()
        rt_config = _fake_runtime_config()
        pipeline_config = _fake_pipeline_config()

        side_effects = [
            _fake_wake_result("hello"),
            RuntimeError("unexpected error"),
        ]
        with patch(
            "xiaohuang.overlay_loop_runtime_service.run_wake_loop_once",
            side_effect=side_effects,
        ):
            run_overlay_runtime(
                app=app,
                stop_event=stop_event,
                logger=logger,
                options=options,
                runtime_config=rt_config,
                pipeline_config=pipeline_config,
                record_openwakeword_command=lambda **kw: _fake_wake_result(),
                make_llm_debug_handler=lambda logger, debug: None,
                playback_warning=lambda msg: None,
                log_warning=lambda msg: None,
            )

        error_states = [s for s in app.states if s[0] == "error"]
        self.assertGreater(len(error_states), 0)

    # ------------------------------------------------------------------
    # no tkinter
    # ------------------------------------------------------------------

    def test_no_tkinter_import(self):
        from xiaohuang import overlay_loop_runtime_service
        self.assertNotIn("tkinter", overlay_loop_runtime_service.__dict__)

    # ------------------------------------------------------------------
    # break when turn outcome says stop
    # ------------------------------------------------------------------

    def test_turn_outcome_false_breaks_loop(self):
        from xiaohuang.overlay_loop_runtime_service import run_overlay_runtime

        app = FakeApp()
        logger = FakeLogger()
        stop_event = threading.Event()
        options = _fake_options()
        rt_config = _fake_runtime_config()
        pipeline_config = _fake_pipeline_config()

        with patch(
            "xiaohuang.overlay_loop_runtime_service.run_wake_loop_once",
            return_value=_fake_wake_result("hello"),
        ):
            with patch(
                "xiaohuang.overlay_loop_runtime_service.run_assistant_turn_from_command",
                return_value=False,
            ) as mock_turn:
                run_overlay_runtime(
                    app=app,
                    stop_event=stop_event,
                    logger=logger,
                    options=options,
                    runtime_config=rt_config,
                    pipeline_config=pipeline_config,
                    record_openwakeword_command=lambda **kw: _fake_wake_result(),
                    make_llm_debug_handler=lambda logger, debug: None,
                    playback_warning=lambda msg: None,
                    log_warning=lambda msg: None,
                )

        mock_turn.assert_called_once()


class V12HBImportSmokeTests(unittest.TestCase):
    def test_import_does_not_crash(self):
        from xiaohuang.overlay_loop_runtime_service import (
            OverlayLoopRuntimeConfig,
            run_overlay_runtime,
        )
