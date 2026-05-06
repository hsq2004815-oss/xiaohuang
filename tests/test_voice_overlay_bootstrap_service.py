"""test_voice_overlay_bootstrap_service.py

Tests for voice_overlay_bootstrap_service — config loading, option assembly,
CLI override behavior. No Qt, no microphone, no network.
"""

from __future__ import annotations

import argparse
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from xiaohuang.app_config_service import (
    XiaoHuangConfig,
    WakeConfig,
)
from xiaohuang.voice_overlay_bootstrap_service import (
    VoiceOverlayBootstrapResult,
    VoiceOverlayResolvedPaths,
    bootstrap_voice_overlay,
)
from xiaohuang.wake_runtime_service import (
    WAKE_ENGINE_STT_TEXT,
    WAKE_ENGINE_OPENWAKEWORD,
)

_DEFAULT_LEGACY = {
    "audio": {"sample_rate": 16000, "channels": 1, "dtype": "int16", "device_id": None},
    "recording": {"duration_seconds": 5, "output_dir": "data/recordings"},
    "stt": {"engine": "funasr", "model_name": "iic/SenseVoiceSmall", "language": "zh", "use_itn": True, "device": "cpu"},
    "logging": {"directory": "logs", "level": "INFO"},
}


def _default_user_config(*args, **kwargs) -> XiaoHuangConfig:
    return XiaoHuangConfig()


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "device": None, "server_url": "http://127.0.0.1:8766",
        "wake_window_seconds": 3.0, "wake_phrases": None, "wake_aliases": None,
        "max_seconds": 10.0, "silence_seconds": 0.8, "debug": False,
        "enable_tts": False, "tts_voice": "zh-CN-XiaoxiaoNeural",
        "tts_output_dir": "data/tts", "enable_llm": False,
        "llm_timeout": 15.0, "llm_model": None, "llm_base_url": None,
        "llm_max_tokens": None, "post_response_cooldown": None,
        "resident_hidden": False, "conversation_session": False,
        "session_timeout": 30.0, "max_session_turns": 12,
        "followup_timeout": 12.0, "max_session_seconds": 300.0,
        "max_no_speech_retries": 2, "config": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _bootstrap(args=None, **kw):
    """Shorthand: bootstrap with default config isolation."""
    a = _args() if args is None else args
    call_kwargs = dict(
        project_root=Path("/fake/project"),
        legacy_config_loader=lambda: copy.deepcopy(_DEFAULT_LEGACY),
        user_config_loader=_default_user_config,
    )
    call_kwargs.update(kw)
    return bootstrap_voice_overlay(a, **call_kwargs)


class BootstrapDefaultTests(unittest.TestCase):
    """Default CLI args — validate BootstrapResult structure."""

    def test_result_is_valid(self):
        result = _bootstrap()
        self.assertIsInstance(result, VoiceOverlayBootstrapResult)
        self.assertIsInstance(result.legacy_config, dict)
        self.assertIsInstance(result.app_config, XiaoHuangConfig)
        self.assertIsInstance(result.paths, VoiceOverlayResolvedPaths)
        self.assertFalse(result.debug)
        # Default XiaoHuangConfig has llm.enabled=True, tts.enabled=True,
        # overlay.resident_hidden=True. With no CLI flags, config values survive.
        self.assertTrue(result.enable_llm)
        self.assertTrue(result.enable_tts)
        self.assertTrue(result.resident_hidden)
        self.assertEqual(result.device_id, 0)

    def test_default_wake_engine_stt_text(self):
        self.assertEqual(_bootstrap().wake_engine_plan.engine, WAKE_ENGINE_STT_TEXT)

    def test_default_wake_phrases_from_config(self):
        self.assertIn("小黄", _bootstrap().wake_phrases)

    def test_wake_phrases_cli_overrides(self):
        result = _bootstrap(_args(wake_phrases="贾维斯,星期五"))
        self.assertEqual(result.wake_phrases, ["贾维斯", "星期五"])

    def test_wake_aliases_cli(self):
        result = _bootstrap(_args(wake_aliases="小凰"))
        self.assertEqual(result.wake_aliases, ["小凰"])


class BootstrapOptionsTests(unittest.TestCase):
    """WakeLoopOptions construction."""

    def test_options_built(self):
        opts = _bootstrap().options
        self.assertEqual(opts.device_id, 0)
        self.assertEqual(opts.server_url, "http://127.0.0.1:8766")
        self.assertEqual(opts.max_seconds, 10.0)
        self.assertEqual(opts.silence_seconds, 0.8)
        self.assertEqual(opts.sample_rate, 16000)
        self.assertEqual(opts.channels, 1)
        self.assertFalse(opts.keep_wake_recordings)

    def test_device_from_args(self):
        result = _bootstrap(_args(device=3))
        self.assertEqual(result.device_id, 3)

    def test_device_from_legacy_config(self):
        legacy = copy.deepcopy(_DEFAULT_LEGACY)
        legacy["audio"]["device_id"] = 5
        result = _bootstrap(legacy_config_loader=lambda: legacy)
        self.assertEqual(result.device_id, 5)

    def test_device_args_overrides_legacy(self):
        legacy = copy.deepcopy(_DEFAULT_LEGACY)
        legacy["audio"]["device_id"] = 5
        result = _bootstrap(_args(device=7), legacy_config_loader=lambda: legacy)
        self.assertEqual(result.device_id, 7)


class BootstrapPathsTests(unittest.TestCase):
    """Resolved directory paths."""

    def test_recording_dir(self):
        self.assertEqual(
            _bootstrap().paths.recording_dir,
            Path("/fake/project/data/recordings"),
        )

    def test_tts_output_dir(self):
        result = _bootstrap(_args(tts_output_dir="data/tts"))
        self.assertEqual(result.paths.tts_output_dir, Path("/fake/project/data/tts"))

    def test_config_types_distinct(self):
        r = _bootstrap()
        self.assertIsInstance(r.legacy_config, dict)
        self.assertIsInstance(r.app_config, XiaoHuangConfig)


class BootstrapPipelineConfigTests(unittest.TestCase):
    """ReplyPipelineConfig / OverlayLoopRuntimeConfig carry expected values."""

    def test_persona_present(self):
        self.assertIn("小黄", _bootstrap().pipeline_config.persona)

    def test_enable_flags(self):
        result = _bootstrap(_args(enable_llm=True, enable_tts=True))
        self.assertTrue(result.pipeline_config.enable_llm)
        self.assertTrue(result.pipeline_config.enable_tts)

    def test_assistant_name(self):
        self.assertEqual(_bootstrap().runtime_config.assistant_name, "小黄")


class BootstrapCliOverrideTests(unittest.TestCase):
    """CLI flags override config values correctly."""

    def test_debug_true(self):
        self.assertTrue(_bootstrap(_args(debug=True)).debug)

    def test_resident_hidden(self):
        self.assertTrue(_bootstrap(_args(resident_hidden=True)).resident_hidden)

    def test_conversation_session(self):
        self.assertTrue(_bootstrap(_args(conversation_session=True)).session_config.enabled)

    def test_session_params(self):
        sc = _bootstrap(_args(
            session_timeout=45.0, max_session_turns=5,
            followup_timeout=20.0, max_session_seconds=180.0,
            max_no_speech_retries=3,
        )).session_config
        self.assertEqual(sc.timeout_seconds, 45.0)
        self.assertEqual(sc.max_turns, 5)
        self.assertEqual(sc.followup_timeout_seconds, 20.0)
        self.assertEqual(sc.max_session_seconds, 180.0)
        self.assertEqual(sc.max_no_speech_retries, 3)

class BootstrapOpenWakeWordTests(unittest.TestCase):
    """openwakeword feature flag behavior."""

    def _oww_config(self) -> XiaoHuangConfig:
        return XiaoHuangConfig(wake=WakeConfig(
            engine="openwakeword", phrases=["贾维斯"],
            fallback_enabled=True, sensitivity=0.5, cooldown_seconds=2.5,
            device_index=0, model_name="hey_jarvis",
        ))

    @patch("xiaohuang.voice_overlay_bootstrap_service.select_wake_engine_runtime")
    @patch("xiaohuang.voice_overlay_bootstrap_service.build_wake_engine_runtime_config")
    def test_oww_flows_to_plan(self, mock_build, mock_select):
        from xiaohuang.wake_runtime_service import WakeEngineRuntimeConfig, WakeEngineRuntimePlan
        mock_build.return_value = WakeEngineRuntimeConfig(
            engine="openwakeword", wake_phrase="贾维斯",
            fallback_enabled=True, device=0, sample_rate=16000,
            sensitivity=0.5, cooldown_seconds=2.5,
            model_path=None, model_name="hey_jarvis",
        )
        mock_select.return_value = WakeEngineRuntimePlan(engine=WAKE_ENGINE_OPENWAKEWORD)
        result = _bootstrap(user_config_loader=lambda *a, **kw: self._oww_config())
        self.assertEqual(result.wake_engine_plan.engine, WAKE_ENGINE_OPENWAKEWORD)
        mock_build.assert_called_once()
        mock_select.assert_called_once()

    @patch("xiaohuang.voice_overlay_bootstrap_service.select_wake_engine_runtime")
    @patch("xiaohuang.voice_overlay_bootstrap_service.build_wake_engine_runtime_config")
    def test_stt_text_default(self, mock_build, mock_select):
        from xiaohuang.wake_runtime_service import WakeEngineRuntimeConfig, WakeEngineRuntimePlan
        mock_build.return_value = WakeEngineRuntimeConfig(
            engine="stt_text", wake_phrase="小黄", fallback_enabled=True,
            device=0, sample_rate=16000, sensitivity=0.5, cooldown_seconds=2.5,
            model_path=None, model_name=None,
        )
        mock_select.return_value = WakeEngineRuntimePlan(engine=WAKE_ENGINE_STT_TEXT)
        self.assertEqual(_bootstrap().wake_engine_plan.engine, WAKE_ENGINE_STT_TEXT)


class BootstrapResultFrozenTests(unittest.TestCase):
    """Result dataclasses are frozen."""

    def test_result_frozen(self):
        r = _bootstrap()
        with self.assertRaises(Exception):
            r.debug = True  # type: ignore[misc]

    def test_paths_frozen(self):
        p = VoiceOverlayResolvedPaths(Path("."), Path("."), Path("."))
        with self.assertRaises(Exception):
            p.project_root = Path("/o")  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
