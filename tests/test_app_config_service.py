from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

from xiaohuang.app_config_service import (
    AssistantConfig,
    AudioConfig,
    ConversationConfig,
    LlmConfig,
    OverlayConfig,
    RuntimeConfig,
    SttConfig,
    TtsConfig,
    WakeConfig,
    XiaoHuangConfig,
    apply_cli_overrides,
    get_default_config,
    get_default_config_path,
    load_config,
    merge_config_dict,
)


# ---------------------------------------------------------------------------
# 1. default config
# ---------------------------------------------------------------------------

class DefaultConfigTests(unittest.TestCase):
    def test_get_default_config_contains_expected_sections(self):
        config = get_default_config()
        self.assertIsInstance(config, XiaoHuangConfig)
        self.assertIsInstance(config.wake, WakeConfig)
        self.assertIsInstance(config.audio, AudioConfig)
        self.assertIsInstance(config.stt, SttConfig)
        self.assertIsInstance(config.llm, LlmConfig)
        self.assertIsInstance(config.tts, TtsConfig)
        self.assertIsInstance(config.conversation, ConversationConfig)
        self.assertIsInstance(config.overlay, OverlayConfig)
        self.assertIsInstance(config.runtime, RuntimeConfig)
        self.assertIsInstance(config.assistant, AssistantConfig)

    def test_default_wake_config_values(self):
        config = get_default_config()
        self.assertEqual(config.wake.engine, "stt_text")
        self.assertEqual(config.wake.phrases, ["小黄"])
        self.assertEqual(config.wake.aliases, [])
        self.assertEqual(config.wake.wake_window_seconds, 3.0)
        self.assertTrue(config.wake.fallback_enabled)
        self.assertEqual(config.wake.sensitivity, 0.5)
        self.assertEqual(config.wake.cooldown_seconds, 2.5)
        self.assertIsNone(config.wake.device_index)
        self.assertIsNone(config.wake.model_path)
        self.assertIsNone(config.wake.model_name)
        self.assertFalse(config.wake.wake_greeting_enabled)
        self.assertEqual(config.wake.wake_greeting_text, "您好先生，有什么为你服务？")

    def test_default_audio_config_values(self):
        config = get_default_config()
        self.assertEqual(config.audio.device_id, 0)
        self.assertEqual(config.audio.max_seconds, 10.0)
        self.assertEqual(config.audio.silence_seconds, 0.8)

    def test_default_stt_config_values(self):
        config = get_default_config()
        self.assertEqual(config.stt.engine, "funasr")
        self.assertEqual(config.stt.model_name, "iic/SenseVoiceSmall")
        self.assertEqual(config.stt.language, "auto")
        self.assertTrue(config.stt.use_itn)
        self.assertEqual(config.stt.device, "cpu")

    def test_default_llm_config_values(self):
        config = get_default_config()
        self.assertTrue(config.llm.enabled)
        self.assertEqual(config.llm.provider, "deepseek")
        self.assertEqual(config.llm.model, "deepseek-v4-flash")
        self.assertEqual(config.llm.base_url, "https://api.deepseek.com")
        self.assertEqual(config.llm.timeout_seconds, 20.0)
        self.assertEqual(config.llm.max_tokens, 256)
        self.assertEqual(config.llm.temperature, 0.4)
        self.assertEqual(config.llm.api_key_env, "DEEPSEEK_API_KEY")

    def test_default_tts_config_values(self):
        config = get_default_config()
        self.assertTrue(config.tts.enabled)
        self.assertEqual(config.tts.voice, "zh-CN-XiaoxiaoNeural")
        self.assertIsNone(config.tts.output_dir)

    def test_default_conversation_config_values(self):
        config = get_default_config()
        self.assertTrue(config.conversation.enabled)
        self.assertEqual(config.conversation.followup_timeout, 12.0)
        self.assertEqual(config.conversation.max_turns, 12)
        self.assertEqual(config.conversation.max_session_seconds, 300.0)
        self.assertEqual(config.conversation.max_no_speech_retries, 2)
        self.assertEqual(config.conversation.session_timeout, 30.0)

    def test_default_overlay_config_values(self):
        config = get_default_config()
        self.assertTrue(config.overlay.resident_hidden)
        self.assertIsNone(config.overlay.post_response_cooldown)

    def test_default_runtime_config_values(self):
        config = get_default_config()
        self.assertFalse(config.runtime.debug)

    def test_default_assistant_config_values(self):
        config = get_default_config()
        self.assertEqual(config.assistant.name, "小黄")
        self.assertEqual(config.assistant.display_name, "小黄")
        self.assertIn("小黄", config.assistant.persona)
        self.assertIn("Windows", config.assistant.persona)

    def test_get_default_config_path_returns_xiaohuang_dir(self):
        path = get_default_config_path()
        self.assertIn(".xiaohuang", str(path))
        self.assertEqual(path.name, "config.json")


# ---------------------------------------------------------------------------
# 2. load_config
# ---------------------------------------------------------------------------

class LoadConfigTests(unittest.TestCase):
    def test_load_config_missing_file_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.json"
            config = load_config(path)
            self.assertIsInstance(config, XiaoHuangConfig)
            self.assertEqual(config.wake.phrases, ["小黄"])

    def test_load_config_invalid_json_warns_and_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("not json {{{", encoding="utf-8")
            warnings: list[str] = []
            config = load_config(path, warn=warnings.append)
            self.assertIsInstance(config, XiaoHuangConfig)
            self.assertTrue(warnings)
            self.assertTrue(any("Invalid JSON" in w for w in warnings),
                            f"Expected 'Invalid JSON' in warnings: {warnings}")

    def test_load_config_non_object_root_warns_and_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arr.json"
            path.write_text(json.dumps(["bad"]), encoding="utf-8")
            warnings: list[str] = []
            config = load_config(path, warn=warnings.append)
            self.assertIsInstance(config, XiaoHuangConfig)
            self.assertTrue(warnings)
            self.assertTrue(any("must be a JSON object" in w for w in warnings),
                            f"Expected 'must be a JSON object' in warnings: {warnings}")

    def test_load_config_from_valid_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            data = {
                "wake": {"engine": "openwakeword", "phrases": ["贾维斯"]},
                "audio": {"device_id": 3, "max_seconds": 8.0},
                "llm": {"enabled": False, "model": "custom-model"},
                "tts": {"voice": "zh-CN-YunxiNeural"},
                "conversation": {"enabled": False, "max_turns": 5},
                "overlay": {"resident_hidden": False},
                "runtime": {"debug": True},
                "assistant": {"display_name": "贾维斯助手"},
            }
            path.write_text(json.dumps(data), encoding="utf-8")

            config = load_config(path)

            self.assertEqual(config.wake.engine, "openwakeword")
            self.assertEqual(config.wake.phrases, ["贾维斯"])
            self.assertEqual(config.audio.device_id, 3)
            self.assertEqual(config.audio.max_seconds, 8.0)
            self.assertFalse(config.llm.enabled)
            self.assertEqual(config.llm.model, "custom-model")
            self.assertEqual(config.tts.voice, "zh-CN-YunxiNeural")
            self.assertFalse(config.conversation.enabled)
            self.assertEqual(config.conversation.max_turns, 5)
            self.assertFalse(config.overlay.resident_hidden)
            self.assertTrue(config.runtime.debug)
            self.assertEqual(config.assistant.display_name, "贾维斯助手")

    def test_load_config_none_path_uses_default_path(self):
        config = load_config(None)
        self.assertIsInstance(config, XiaoHuangConfig)


# ---------------------------------------------------------------------------
# 3. merge_config_dict — non-object section
# ---------------------------------------------------------------------------

class MergeConfigDictTests(unittest.TestCase):
    def test_merge_config_skips_non_object_section(self):
        warnings: list[str] = []
        data = {
            "wake": "bad",
            "audio": {"device_id": 3},
        }
        config = merge_config_dict(get_default_config(), data, warn=warnings.append)

        self.assertEqual(config.wake.phrases, ["小黄"])  # default preserved
        self.assertEqual(config.wake.engine, "stt_text")
        self.assertEqual(config.audio.device_id, 3)

        self.assertTrue(any("wake" in w and "must be an object" in w for w in warnings),
                        f"Expected section warning for 'wake': {warnings}")


# ---------------------------------------------------------------------------
# 4. wake.phrases — string and list
# ---------------------------------------------------------------------------

class WakePhrasesTests(unittest.TestCase):
    def test_wake_phrases_accepts_string(self):
        warnings: list[str] = []
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"phrases": "小黄小黄"}},
            warn=warnings.append,
        )
        self.assertEqual(config.wake.phrases, ["小黄小黄"])

    def test_wake_phrases_accepts_list(self):
        warnings: list[str] = []
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"phrases": ["小黄", "你好小黄", ""]}},
            warn=warnings.append,
        )
        self.assertEqual(config.wake.phrases, ["小黄", "你好小黄"])

    def test_wake_phrases_empty_string_in_list_filtered(self):
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"phrases": ["   ", ""]}},
        )
        self.assertEqual(config.wake.phrases, ["小黄"])  # default

    def test_wake_phrases_whitespace_only_string_falls_back(self):
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"phrases": "   "}},
        )
        self.assertEqual(config.wake.phrases, ["小黄"])

    def test_wake_phrases_invalid_type_warns(self):
        warnings: list[str] = []
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"phrases": 123}},
            warn=warnings.append,
        )
        self.assertEqual(config.wake.phrases, ["小黄"])
        self.assertTrue(any("must be string or list" in w for w in warnings))


# ---------------------------------------------------------------------------
# 5. wake.aliases — string and list
# ---------------------------------------------------------------------------

class WakeAliasesTests(unittest.TestCase):
    def test_wake_aliases_accepts_string(self):
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"aliases": "小王"}},
        )
        self.assertEqual(config.wake.aliases, ["小王"])

    def test_wake_aliases_accepts_list(self):
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"aliases": ["小王", "小皇", ""]}},
        )
        self.assertEqual(config.wake.aliases, ["小王", "小皇"])

    def test_wake_aliases_empty_string_returns_empty_list(self):
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"aliases": ""}},
        )
        self.assertEqual(config.wake.aliases, [])

    def test_wake_aliases_invalid_type_warns(self):
        warnings: list[str] = []
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"aliases": 456}},
            warn=warnings.append,
        )
        self.assertEqual(config.wake.aliases, [])
        self.assertTrue(any("aliases must be string or list" in w for w in warnings))


# ---------------------------------------------------------------------------
# 6. numeric out-of-range fallback
# ---------------------------------------------------------------------------

class NumericRangeTests(unittest.TestCase):
    def test_numeric_values_out_of_range_fall_back_to_defaults(self):
        warnings: list[str] = []
        data = {
            "wake": {
                "wake_window_seconds": 0.1,
                "sensitivity": 99.0,
                "cooldown_seconds": -1.0,
            },
            "audio": {
                "device_id": 999,
                "max_seconds": 999.0,
                "silence_seconds": 0.01,
            },
            "llm": {
                "max_tokens": 99999,
                "timeout_seconds": 0.1,
                "temperature": 99.0,
            },
            "conversation": {
                "max_turns": 0,
                "followup_timeout": 0.1,
                "max_no_speech_retries": -1,
            },
        }
        config = merge_config_dict(get_default_config(), data, warn=warnings.append)

        self.assertEqual(config.wake.wake_window_seconds, 3.0)
        self.assertEqual(config.wake.sensitivity, 0.5)
        self.assertEqual(config.wake.cooldown_seconds, 2.5)
        self.assertEqual(config.audio.device_id, 0)
        self.assertEqual(config.audio.max_seconds, 10.0)
        self.assertEqual(config.audio.silence_seconds, 0.8)
        self.assertEqual(config.llm.max_tokens, 256)
        self.assertEqual(config.llm.timeout_seconds, 20.0)
        self.assertEqual(config.llm.temperature, 0.4)
        self.assertEqual(config.conversation.max_turns, 12)
        self.assertEqual(config.conversation.followup_timeout, 12.0)
        self.assertEqual(config.conversation.max_no_speech_retries, 2)
        self.assertTrue(len(warnings) > 0)

    def test_numeric_values_in_range_accepted(self):
        config = merge_config_dict(
            get_default_config(),
            {
                "wake": {"wake_window_seconds": 5.0, "sensitivity": 0.8},
                "audio": {"device_id": 2, "max_seconds": 15.0},
                "llm": {"max_tokens": 512, "temperature": 0.9},
                "conversation": {"max_turns": 8, "followup_timeout": 60.0},
            },
        )
        self.assertEqual(config.wake.wake_window_seconds, 5.0)
        self.assertEqual(config.wake.sensitivity, 0.8)
        self.assertEqual(config.audio.device_id, 2)
        self.assertEqual(config.audio.max_seconds, 15.0)
        self.assertEqual(config.llm.max_tokens, 512)
        self.assertEqual(config.llm.temperature, 0.9)
        self.assertEqual(config.conversation.max_turns, 8)
        self.assertEqual(config.conversation.followup_timeout, 60.0)


# ---------------------------------------------------------------------------
# 7. bool coercion
# ---------------------------------------------------------------------------

class BoolCoercionTests(unittest.TestCase):
    def test_bool_values_require_boolean(self):
        warnings: list[str] = []
        data = {
            "llm": {"enabled": "yes"},
            "tts": {"enabled": "false"},
            "runtime": {"debug": 1},
        }
        config = merge_config_dict(get_default_config(), data, warn=warnings.append)

        self.assertTrue(config.llm.enabled)
        self.assertTrue(config.tts.enabled)
        self.assertFalse(config.runtime.debug)
        self.assertGreaterEqual(len(warnings), 3,
                                f"Expected at least 3 bool warnings, got {len(warnings)}: {warnings}")

    def test_bool_true_accepted(self):
        config = merge_config_dict(
            get_default_config(),
            {"llm": {"enabled": True}, "tts": {"enabled": False}, "runtime": {"debug": True}},
        )
        self.assertTrue(config.llm.enabled)
        self.assertFalse(config.tts.enabled)
        self.assertTrue(config.runtime.debug)

    def test_bool_wake_fallback_enabled_defaults_on_non_bool(self):
        warnings: list[str] = []
        config = merge_config_dict(
            get_default_config(),
            {"wake": {"fallback_enabled": "yes"}},
            warn=warnings.append,
        )
        self.assertTrue(config.wake.fallback_enabled)
        self.assertTrue(any("Expected boolean" in w for w in warnings))


# ---------------------------------------------------------------------------
# 8. assistant config
# ---------------------------------------------------------------------------

class AssistantConfigTests(unittest.TestCase):
    def test_assistant_config_overrides_name_display_name_persona(self):
        config = merge_config_dict(
            get_default_config(),
            {
                "assistant": {
                    "name": "xiao_huang",
                    "display_name": "小黄助手",
                    "persona": "你是一个简洁助手。",
                }
            },
        )
        self.assertEqual(config.assistant.name, "xiao_huang")
        self.assertEqual(config.assistant.display_name, "小黄助手")
        self.assertEqual(config.assistant.persona, "你是一个简洁助手。")

    def test_assistant_whitespace_only_display_name_falls_back(self):
        config = merge_config_dict(
            get_default_config(),
            {"assistant": {"display_name": "   "}},
        )
        self.assertEqual(config.assistant.display_name, "小黄")

    def test_assistant_empty_name_falls_back(self):
        config = merge_config_dict(
            get_default_config(),
            {"assistant": {"name": ""}},
        )
        self.assertEqual(config.assistant.name, "小黄")


# ---------------------------------------------------------------------------
# 9. LLM / TTS / Overlay fields
# ---------------------------------------------------------------------------

class LlmTtsOverlayMergeTests(unittest.TestCase):
    def test_llm_tts_overlay_fields_merge(self):
        config = merge_config_dict(
            get_default_config(),
            {
                "llm": {
                    "enabled": False,
                    "model": "deepseek-test",
                    "base_url": "http://127.0.0.1:9999",
                    "timeout_seconds": 30,
                    "temperature": 0.7,
                    "api_key_env": "TEST_KEY",
                },
                "tts": {
                    "enabled": False,
                    "voice": "zh-CN-YunxiNeural",
                    "output_dir": "data/custom_tts",
                },
                "overlay": {
                    "resident_hidden": False,
                    "post_response_cooldown": 2.5,
                },
            },
        )
        self.assertFalse(config.llm.enabled)
        self.assertEqual(config.llm.model, "deepseek-test")
        self.assertEqual(config.llm.base_url, "http://127.0.0.1:9999")
        self.assertEqual(config.llm.timeout_seconds, 30)
        self.assertEqual(config.llm.temperature, 0.7)
        self.assertEqual(config.llm.api_key_env, "TEST_KEY")
        self.assertFalse(config.tts.enabled)
        self.assertEqual(config.tts.voice, "zh-CN-YunxiNeural")
        self.assertEqual(config.tts.output_dir, "data/custom_tts")
        self.assertFalse(config.overlay.resident_hidden)
        self.assertEqual(config.overlay.post_response_cooldown, 2.5)


# ---------------------------------------------------------------------------
# 10. apply_cli_overrides
# ---------------------------------------------------------------------------

class ApplyCliOverridesTests(unittest.TestCase):
    def test_apply_cli_overrides_updates_only_cli_values(self):
        base = merge_config_dict(
            get_default_config(),
            {
                "wake": {"phrases": ["贾维斯"]},
                "llm": {"enabled": True, "model": "original-model"},
                "tts": {"enabled": False},
            },
        )
        args = SimpleNamespace(
            wake_window_seconds=5.0,
            device=2,
            max_seconds=8.0,
            silence_seconds=0.5,
            enable_llm=True,
            llm_model="deepseek-custom",
            llm_base_url="http://localhost",
            llm_timeout=9.0,
            llm_max_tokens=99,
            enable_tts=True,
            tts_voice="voice-test",
            tts_output_dir="data/tts-test",
            conversation_session=True,
            followup_timeout=10.0,
            max_session_turns=5,
            max_session_seconds=100.0,
            max_no_speech_retries=1,
            session_timeout=20.0,
            resident_hidden=True,
            post_response_cooldown=3.0,
            debug=True,
            wake_greeting=True,
            wake_greeting_text="你好",
        )

        updated = apply_cli_overrides(base, args)

        self.assertEqual(updated.wake.wake_window_seconds, 5.0)
        self.assertEqual(updated.audio.device_id, 2)
        self.assertEqual(updated.audio.max_seconds, 8.0)
        self.assertEqual(updated.audio.silence_seconds, 0.5)
        self.assertTrue(updated.llm.enabled)
        self.assertEqual(updated.llm.model, "deepseek-custom")
        self.assertEqual(updated.llm.base_url, "http://localhost")
        self.assertEqual(updated.llm.timeout_seconds, 9.0)
        self.assertEqual(updated.llm.max_tokens, 99)
        self.assertTrue(updated.tts.enabled)
        self.assertEqual(updated.tts.voice, "voice-test")
        self.assertEqual(updated.tts.output_dir, "data/tts-test")
        self.assertTrue(updated.conversation.enabled)
        self.assertEqual(updated.conversation.followup_timeout, 10.0)
        self.assertEqual(updated.conversation.max_turns, 5)
        self.assertEqual(updated.conversation.max_session_seconds, 100.0)
        self.assertEqual(updated.conversation.max_no_speech_retries, 1)
        self.assertEqual(updated.conversation.session_timeout, 20.0)
        self.assertTrue(updated.overlay.resident_hidden)
        self.assertEqual(updated.overlay.post_response_cooldown, 3.0)
        self.assertTrue(updated.runtime.debug)
        self.assertTrue(updated.wake.wake_greeting_enabled)
        self.assertEqual(updated.wake.wake_greeting_text, "你好")
        # Unaffected fields stay
        self.assertEqual(updated.wake.phrases, ["贾维斯"])
        self.assertEqual(updated.assistant.display_name, "小黄")

    def test_apply_cli_overrides_false_store_true_does_not_disable_config(self):
        base = merge_config_dict(
            get_default_config(),
            {
                "llm": {"enabled": True},
                "tts": {"enabled": True},
                "conversation": {"enabled": True},
                "overlay": {"resident_hidden": True},
                "runtime": {"debug": True},
            },
        )
        args = SimpleNamespace(
            enable_llm=False,
            enable_tts=False,
            conversation_session=False,
            resident_hidden=False,
            debug=False,
            wake_window_seconds=None,
            device=None,
            max_seconds=None,
            silence_seconds=None,
            llm_model=None,
            llm_base_url=None,
            llm_timeout=None,
            llm_max_tokens=None,
            tts_voice=None,
            tts_output_dir=None,
            followup_timeout=None,
            max_session_turns=None,
            max_session_seconds=None,
            max_no_speech_retries=None,
            session_timeout=None,
            post_response_cooldown=None,
            wake_greeting=False,
            wake_greeting_text=None,
        )
        updated = apply_cli_overrides(base, args)

        self.assertTrue(updated.llm.enabled)
        self.assertTrue(updated.tts.enabled)
        self.assertTrue(updated.conversation.enabled)
        self.assertTrue(updated.overlay.resident_hidden)
        self.assertTrue(updated.runtime.debug)
        self.assertFalse(updated.wake.wake_greeting_enabled)

    def test_apply_cli_overrides_cli_true_overrides_config_false(self):
        base = merge_config_dict(
            get_default_config(),
            {"llm": {"enabled": False}, "runtime": {"debug": False}},
        )
        args = SimpleNamespace(
            enable_llm=True,
            debug=True,
            wake_window_seconds=None,
            device=None,
            max_seconds=None,
            silence_seconds=None,
            llm_model=None,
            llm_base_url=None,
            llm_timeout=None,
            llm_max_tokens=None,
            enable_tts=False,
            tts_voice=None,
            tts_output_dir=None,
            conversation_session=False,
            followup_timeout=None,
            max_session_turns=None,
            max_session_seconds=None,
            max_no_speech_retries=None,
            session_timeout=None,
            resident_hidden=False,
            post_response_cooldown=None,
            wake_greeting=False,
            wake_greeting_text=None,
        )
        updated = apply_cli_overrides(base, args)

        self.assertTrue(updated.llm.enabled)
        self.assertTrue(updated.runtime.debug)

    def test_apply_cli_overrides_none_scalar_does_not_override(self):
        base = get_default_config()
        args = SimpleNamespace(
            wake_window_seconds=None,
            device=None,
            max_seconds=None,
            silence_seconds=None,
            enable_llm=False,
            llm_model=None,
            llm_base_url=None,
            llm_timeout=None,
            llm_max_tokens=None,
            enable_tts=False,
            tts_voice=None,
            tts_output_dir=None,
            conversation_session=False,
            followup_timeout=None,
            max_session_turns=None,
            max_session_seconds=None,
            max_no_speech_retries=None,
            session_timeout=None,
            resident_hidden=False,
            post_response_cooldown=None,
            debug=False,
            wake_greeting=False,
            wake_greeting_text=None,
        )
        updated = apply_cli_overrides(base, args)

        self.assertEqual(updated.wake.wake_window_seconds, 3.0)
        self.assertEqual(updated.audio.device_id, 0)
        self.assertEqual(updated.audio.max_seconds, 10.0)
        self.assertEqual(updated.llm.model, "deepseek-v4-flash")


# ---------------------------------------------------------------------------
# 11. frozen dataclass
# ---------------------------------------------------------------------------

class FrozenDataclassTests(unittest.TestCase):
    def test_config_dataclasses_are_frozen(self):
        config = get_default_config()
        with self.assertRaises(FrozenInstanceError):
            config.audio.device_id = 1  # type: ignore[misc]

        with self.assertRaises(FrozenInstanceError):
            config.wake.sensitivity = 0.9  # type: ignore[misc]

        with self.assertRaises(FrozenInstanceError):
            config.llm.max_tokens = 100  # type: ignore[misc]

    def test_frozen_list_field_still_mutable_elements(self):
        config = get_default_config()
        config.wake.phrases.append("test")  # list ref mutable, frozen prevents reassignment only
        self.assertIn("test", config.wake.phrases)
