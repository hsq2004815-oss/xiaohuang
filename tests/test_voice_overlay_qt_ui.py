from __future__ import annotations

import threading
import unittest
from pathlib import Path

from xiaohuang.overlay_state_service import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_REPLYING,
    STATE_RESULT,
    STATE_SPEAKING,
    STATE_TRANSCRIBING,
    STATE_WAKE_CHECKING,
    STATE_WAKE_DETECTED,
)


class VoiceOverlayQtUiTests(unittest.TestCase):
    def test_state_styles_cover_runtime_states(self):
        from xiaohuang.voice_overlay_qt_ui import STATE_STYLES

        for state in (
            STATE_IDLE,
            STATE_WAKE_CHECKING,
            STATE_WAKE_DETECTED,
            STATE_LISTENING,
            STATE_TRANSCRIBING,
            STATE_REPLYING,
            STATE_SPEAKING,
            STATE_RESULT,
            STATE_ERROR,
        ):
            self.assertIn(state, STATE_STYLES)

    def test_edge_fade_has_transparent_edges_and_solid_center(self):
        from xiaohuang.voice_overlay_qt_ui import _edge_fade

        self.assertEqual(_edge_fade(0.0), 0.0)
        self.assertEqual(_edge_fade(1.0), 0.0)
        self.assertEqual(_edge_fade(0.5), 1.0)
        self.assertGreater(_edge_fade(0.1), 0.0)
        self.assertLess(_edge_fade(0.08), _edge_fade(0.18))
        self.assertLess(_edge_fade(0.92), _edge_fade(0.82))

    def test_module_does_not_import_tkinter_or_pillow(self):
        from xiaohuang import voice_overlay_qt_ui

        self.assertNotIn("tkinter", voice_overlay_qt_ui.__dict__)
        self.assertNotIn("ImageTk", voice_overlay_qt_ui.__dict__)
        self.assertNotIn("ImageDraw", voice_overlay_qt_ui.__dict__)

    def test_paint_event_does_not_draw_background_frame(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "xiaohuang"
            / "voice_overlay_qt_ui.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "drawRoundedRect",
            "fillRect",
            "fillPath",
            "drawRect",
            "QBrush",
            "setStyleSheet",
            "setAutoFillBackground(True)",
            "autoFillBackground(True)",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("Qt.NoDropShadowWindowHint", source)
        self.assertIn("QLinearGradient", source)
        self.assertIn("_strip_native_window_frame", source)
        self.assertIn("DwmSetWindowAttribute", source)

    def test_voice_overlay_app_exposes_runtime_interface(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not available")
        from xiaohuang.voice_overlay_qt_ui import VoiceOverlayApp

        qt_app = QApplication.instance() or QApplication([])
        stop = threading.Event()
        app = VoiceOverlayApp(qt_app, stop_event=stop, start_hidden=True)
        try:
            for method_name in (
                "set_state",
                "thread_safe_set_state",
                "show_status",
                "thread_safe_show_status",
                "schedule_idle",
                "show_overlay",
                "hide_overlay",
                "close",
            ):
                self.assertTrue(callable(getattr(app, method_name)))
        finally:
            app.close()

    def test_close_sets_stop_event(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not available")
        from xiaohuang.voice_overlay_qt_ui import VoiceOverlayApp

        qt_app = QApplication.instance() or QApplication([])
        stop = threading.Event()
        app = VoiceOverlayApp(qt_app, stop_event=stop, start_hidden=True)

        app.close()

        self.assertTrue(stop.is_set())
