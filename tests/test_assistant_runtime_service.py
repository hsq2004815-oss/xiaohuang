from __future__ import annotations

import unittest
from typing import Any


class V12FFDAssistantTurnOrchestrationTests(unittest.TestCase):
    """Tests for run_assistant_turn_from_command in assistant_runtime_service."""

    def _turn_callbacks(self):
        from xiaohuang.assistant_runtime_service import AssistantTurnCallbacks
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        states: list[tuple[str, str | None]] = []
        infos: list[str] = []
        warnings: list[str] = []
        waits: list[float] = []
        replies: list[tuple[str, object]] = []

        def generate_reply(text, lt):
            replies.append((text, lt))
            return _next_reply_result.pop(0) if _next_reply_result else ReplyPipelineResult(
                reply_text=f"reply: {text}", reply_source="rule", source_note=None,
            )

        _next_reply_result: list[Any] = []

        cb = AssistantTurnCallbacks(
            set_state=lambda s, d=None: states.append((s, d)),
            log_info=lambda msg: infos.append(msg),
            log_warning=lambda msg: warnings.append(msg),
            wait_seconds=lambda s: (waits.append(s), False)[1],
            generate_reply=generate_reply,
            debug_print=None,
        )
        return cb, states, infos, warnings, waits, replies, _next_reply_result

    def _single_turn_callbacks(self):
        from xiaohuang.assistant_runtime_service import AssistantRuntimeCallbacks

        states: list[tuple[str, str | None]] = []
        warns: list[str] = []
        waits: list[float] = []
        hides: list[bool] = []

        cb = AssistantRuntimeCallbacks(
            set_state=lambda s, d=None: states.append((s, d)),
            log_warn=lambda msg: warns.append(msg),
            wait=lambda s: (waits.append(s), False)[1],
            hide_overlay=lambda: hides.append(True),
        )
        return cb, states, warns, waits, hides

    def _session_callbacks(self):
        from xiaohuang.assistant_runtime_service import AssistantSessionCallbacks
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        states: list[tuple[str, str | None]] = []
        infos: list[str] = []
        waits: list[float] = []
        records: list[tuple[float, object]] = []
        replies: list[tuple[str, object]] = []

        def record_followup(max_s, lt):
            records.append((max_s, lt))
            return _next_record_text.pop(0) if _next_record_text else ""

        def generate_reply(text, lt):
            replies.append((text, lt))
            return _next_reply_result.pop(0) if _next_reply_result else ReplyPipelineResult(
                reply_text=f"reply: {text}", reply_source="rule", source_note=None,
            )

        _next_record_text: list[str] = []
        _next_reply_result: list[Any] = []

        cb = AssistantSessionCallbacks(
            set_state=lambda s, d=None: states.append((s, d)),
            log_info=lambda msg: infos.append(msg),
            wait_seconds=lambda s: (waits.append(s), False)[1],
            record_followup=record_followup,
            generate_reply=generate_reply,
        )
        return cb, states, infos, waits, records, replies, _next_record_text, _next_reply_result

    def _session_config(self, **kw):
        from xiaohuang.conversation_session_service import ConversationSessionConfig
        defaults = dict(enabled=True, max_turns=5, followup_timeout_seconds=8.0,
                        max_session_seconds=300.0, max_no_speech_retries=3)
        defaults.update(kw)
        return ConversationSessionConfig(**defaults)

    # ------------------------------------------------------------------
    # empty command_text
    # ------------------------------------------------------------------

    def test_empty_command_text_returns_true_no_reply(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command

        cb, states, infos, _, _, replies, _ = self._turn_callbacks()
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, _, _, _, _ = self._single_turn_callbacks()

        result = run_assistant_turn_from_command(
            command_text="",
            turn_tracker=None,
            callbacks=cb,
            session_config=self._session_config(enabled=False),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
        )
        self.assertTrue(result)
        self.assertEqual(len(replies), 0)
        self.assertEqual(len(states), 0)

    def test_whitespace_command_text_returns_true_no_reply(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command

        cb, states, infos, _, _, replies, _ = self._turn_callbacks()
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, _, _, _, _ = self._single_turn_callbacks()

        result = run_assistant_turn_from_command(
            command_text="   ",
            turn_tracker=None,
            callbacks=cb,
            session_config=self._session_config(enabled=False),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
        )
        self.assertTrue(result)
        self.assertEqual(len(replies), 0)

    # ------------------------------------------------------------------
    # non-session: normal reply
    # ------------------------------------------------------------------

    def test_non_session_normal_reply_calls_handle_single_turn(self):
        from xiaohuang.assistant_runtime_service import (
            run_assistant_turn_from_command,
        )

        cb, states, infos, _, waits, replies, _ = self._turn_callbacks()
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, st_states, _, _, _ = self._single_turn_callbacks()

        result = run_assistant_turn_from_command(
            command_text="hello",
            turn_tracker=_fake_tracker(),
            callbacks=cb,
            session_config=self._session_config(enabled=False),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
        )
        self.assertTrue(result)
        # turn callbacks: set_state(REPLYING)
        self.assertEqual(states[0][0], "replying")
        # reply generated
        self.assertEqual(len(replies), 1)
        # single_turn handles result/idle
        self.assertTrue(any(s[0] == "result" for s in st_states))

    def test_non_session_stop_event_returns_false(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command

        cb, states, infos, _, waits, replies, _ = self._turn_callbacks()
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, _, _, _, _ = self._single_turn_callbacks()
        st_cb.wait = lambda s: True  # stop during cooldown

        result = run_assistant_turn_from_command(
            command_text="hello",
            turn_tracker=_fake_tracker(),
            callbacks=cb,
            session_config=self._session_config(enabled=False),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
            post_response_cooldown=2.0,
        )
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # tts_error
    # ------------------------------------------------------------------

    def test_tts_error_logs_warning(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        cb, states, infos, warnings, _, replies, next_results = self._turn_callbacks()
        next_results.append(ReplyPipelineResult(
            reply_text="hi", reply_source="llm", source_note=None,
            tts_error="tts failed",
        ))
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, _, _, _, _ = self._single_turn_callbacks()

        run_assistant_turn_from_command(
            command_text="hello",
            turn_tracker=_fake_tracker(),
            callbacks=cb,
            session_config=self._session_config(enabled=False),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
        )
        self.assertTrue(any("tts failed" in w for w in warnings))

    # ------------------------------------------------------------------
    # session enabled
    # ------------------------------------------------------------------

    def test_session_enabled_calls_run_session_followup_loop(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command

        cb, states, _, _, _, replies, _ = self._turn_callbacks()
        sc_cb, sc_states, _, _, records, _, next_texts, _ = self._session_callbacks()
        next_texts.append("退出")
        st_cb, _, _, _, _ = self._single_turn_callbacks()
        _now = [0.0]

        def fake_now():
            _now[0] += 0.5
            return _now[0]

        result = run_assistant_turn_from_command(
            command_text="hello",
            turn_tracker=_fake_tracker(),
            callbacks=cb,
            session_config=self._session_config(max_turns=5),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
        )
        self.assertTrue(result)
        # session followup was entered
        self.assertEqual(len(records), 1)

    def test_session_outcome_false_returns_false(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command

        cb, states, _, _, waits, replies, _ = self._turn_callbacks()
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, _, _, _, _ = self._single_turn_callbacks()

        # make wait return True during session 0.3s wait
        call_count = [0]
        def wait_once(s):
            call_count[0] += 1
            if call_count[0] == 1 and s == 0.3:
                return True
            return False
        cb.wait_seconds = wait_once

        result = run_assistant_turn_from_command(
            command_text="hello",
            turn_tracker=_fake_tracker(),
            callbacks=cb,
            session_config=self._session_config(max_turns=5),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
        )
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # debug callbacks
    # ------------------------------------------------------------------

    def test_debug_callbacks_receive_output(self):
        from xiaohuang.assistant_runtime_service import run_assistant_turn_from_command

        debugs: list[str] = []
        cb, states, _, _, _, replies, _ = self._turn_callbacks()
        cb.debug_print = lambda msg: debugs.append(msg)
        sc_cb, _, _, _, _, _, _, _ = self._session_callbacks()
        st_cb, st_states, _, _, _ = self._single_turn_callbacks()

        run_assistant_turn_from_command(
            command_text="hello",
            turn_tracker=_fake_tracker(),
            callbacks=cb,
            session_config=self._session_config(enabled=False),
            session_callbacks=sc_cb,
            single_turn_callbacks=st_cb,
            debug=True,
        )
        self.assertTrue(any("XiaoHuang reply:" in d for d in debugs))
        self.assertTrue(any("Reply source:" in d for d in debugs))

    # ------------------------------------------------------------------
    # no tkinter
    # ------------------------------------------------------------------

    def test_assistant_runtime_no_tkinter(self):
        import sys
        from xiaohuang import assistant_runtime_service
        self.assertNotIn("tkinter", assistant_runtime_service.__dict__)


def _fake_tracker():
    from xiaohuang.latency_metrics_service import LatencyTracker
    t = LatencyTracker(clock=iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]).__next__)
    return t
