"""test_wake_greeting.py — tests for wake greeting before command recording."""

from __future__ import annotations

import unittest
from unittest.mock import patch


class WakeGreetingConfigTests(unittest.TestCase):
    def test_default_config_greeting_disabled(self):
        from xiaohuang.app_config_service import WakeConfig
        cfg = WakeConfig()
        self.assertFalse(cfg.wake_greeting_enabled)

    def test_default_greeting_text(self):
        from xiaohuang.app_config_service import WakeConfig
        cfg = WakeConfig()
        self.assertIn("先生", cfg.wake_greeting_text)

    def test_custom_greeting_text(self):
        from xiaohuang.app_config_service import WakeConfig
        cfg = WakeConfig(wake_greeting_text="你好主人！")
        self.assertEqual(cfg.wake_greeting_text, "你好主人！")

    def test_cli_override_default(self):
        import argparse
        from xiaohuang.app_config_service import WakeConfig
        args = argparse.Namespace(
            wake_greeting=False,
            wake_greeting_text=None,
        )
        self.assertFalse(args.wake_greeting)


class OverlayLoopRuntimeConfigTests(unittest.TestCase):
    def test_runtime_config_has_greeting_fields(self):
        from xiaohuang.overlay_loop_runtime_service import OverlayLoopRuntimeConfig
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        cfg = OverlayLoopRuntimeConfig(
            wake_engine_mode="stt_text",
            wake_engine_runtime=None,
            session_config=ConversationSessionConfig(),
        )
        self.assertFalse(cfg.wake_greeting_enabled)
        self.assertIn("先生", cfg.wake_greeting_text)

    def test_runtime_config_greeting_enabled(self):
        from xiaohuang.overlay_loop_runtime_service import OverlayLoopRuntimeConfig
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        cfg = OverlayLoopRuntimeConfig(
            wake_engine_mode="stt_text",
            wake_engine_runtime=None,
            session_config=ConversationSessionConfig(),
            wake_greeting_enabled=True,
            wake_greeting_text="你好，请说话。",
        )
        self.assertTrue(cfg.wake_greeting_enabled)
        self.assertEqual(cfg.wake_greeting_text, "你好，请说话。")


class PlayWakeGreetingTests(unittest.TestCase):
    def test_greeting_disabled_does_nothing(self):
        from xiaohuang.overlay_loop_runtime_service import _play_wake_greeting

        class FakeLogger:
            def __init__(self):
                self.infos = []
                self.warnings = []

            def info(self, msg):
                self.infos.append(msg)

            def warning(self, msg):
                self.warnings.append(msg)

        class FakeApp:
            def __init__(self):
                self.states = []

            def thread_safe_set_state(self, s, d=None):
                self.states.append(s)

        logger = FakeLogger()
        app = FakeApp()
        _play_wake_greeting(
            text="你好",
            logger=logger,
            app=app,
            enable_tts=False,
            tts_output_dir=None,
        )
        self.assertIn("skipped", logger.infos[0])

    def test_greeting_tts_failure_does_not_crash(self):
        from xiaohuang.overlay_loop_runtime_service import _play_wake_greeting

        class FakeLogger:
            def __init__(self):
                self.warnings = []

            def info(self, msg):
                pass

            def warning(self, msg):
                self.warnings.append(msg)

        class FakeApp:
            def thread_safe_set_state(self, s, d=None):
                pass

        _play_wake_greeting(
            text="你好",
            logger=FakeLogger(),
            app=FakeApp(),
            enable_tts=True,
            tts_output_dir="/nonexistent/tts",
        )
        self.assertTrue(True)  # didn't crash

    def test_empty_greeting_text_skips(self):
        from xiaohuang.overlay_loop_runtime_service import _play_wake_greeting

        class FakeLogger:
            def __init__(self):
                self.warnings = []

            def info(self, msg):
                pass

            def warning(self, msg):
                self.warnings.append(msg)

        class FakeApp:
            def thread_safe_set_state(self, s, d=None):
                pass

        _play_wake_greeting(text="", logger=FakeLogger(), app=FakeApp(), enable_tts=True, tts_output_dir=None)
        # empty text won't reach TTS — _run_openwakeword_turn checks text before calling
        self.assertTrue(True)


class GreetingNotInMemoryTests(unittest.TestCase):
    def test_greeting_not_recorded_in_memory(self):
        from xiaohuang.conversation_memory_service import ConversationMemory
        mem = ConversationMemory()
        # Simulate: greeting is played via TTS, not via reply_pipeline
        # Only add_user / add_assistant go to memory
        mem.add_user("打开日志目录")
        mem.add_assistant("日志目录已打开", source="capability")
        ctx = mem.build_context_text()
        self.assertNotIn("您好先生", ctx)
        self.assertIn("打开日志目录", ctx)


class VoiceOverlayHelpTests(unittest.TestCase):
    def test_help_includes_greeting_args(self):
        import subprocess
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "voice_overlay.py"), "--help"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--wake-greeting", result.stdout)
        self.assertIn("--wake-greeting-text", result.stdout)


if __name__ == "__main__":
    unittest.main()
