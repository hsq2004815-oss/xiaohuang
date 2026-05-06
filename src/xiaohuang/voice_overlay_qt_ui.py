from __future__ import annotations

import math
import time
import threading
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QEasingCurve, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

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
    get_overlay_status_text,
)


@dataclass(frozen=True)
class WaveStateStyle:
    color: str
    amp: float
    speed: float
    layers: int
    style: str


STATE_STYLES: dict[str, WaveStateStyle] = {
    STATE_IDLE: WaveStateStyle("#4a9eff", 3.2, 0.65, 3, "breathe"),
    STATE_WAKE_CHECKING: WaveStateStyle("#3d8bfd", 5.5, 1.1, 4, "scan"),
    STATE_WAKE_DETECTED: WaveStateStyle("#00e5a0", 13.0, 1.5, 5, "active"),
    STATE_LISTENING: WaveStateStyle("#00e5a0", 15.0, 1.65, 5, "active"),
    STATE_TRANSCRIBING: WaveStateStyle("#7c6fff", 8.0, 1.2, 4, "mid"),
    STATE_REPLYING: WaveStateStyle("#00b4ff", 9.0, 1.15, 4, "mid"),
    STATE_SPEAKING: WaveStateStyle("#9b6dff", 20.0, 1.9, 6, "heavy"),
    STATE_RESULT: WaveStateStyle("#00d68f", 4.5, 0.75, 3, "soft"),
    STATE_ERROR: WaveStateStyle("#ff4757", 12.0, 3.5, 3, "alert"),
}

VISIBLE_WHEN_RESIDENT_HIDDEN = {
    STATE_WAKE_DETECTED,
    STATE_LISTENING,
    STATE_TRANSCRIBING,
    STATE_REPLYING,
    STATE_SPEAKING,
    STATE_RESULT,
    STATE_ERROR,
}


class OverlaySignalBridge(QObject):
    set_state_requested = Signal(str, object)
    show_status_requested = Signal(object)
    schedule_idle_requested = Signal(int)
    show_requested = Signal()
    hide_requested = Signal()
    close_requested = Signal()


class WaveformDock(QWidget):
    WIDTH = 720
    HEIGHT = 160
    ANIMATION_MS = 33
    BOTTOM_MARGIN = 60

    def __init__(
        self,
        *,
        stop_event: threading.Event,
        title: str = "小黄",
        wake_phrase: str = "小黄",
        resident_hidden: bool = False,
        quit_on_close: bool = False,
    ) -> None:
        super().__init__()
        self.stop_event = stop_event
        self.assistant_name = title or "小黄"
        self.wake_phrase = wake_phrase or "小黄"
        self.resident_hidden = resident_hidden
        self.quit_on_close = quit_on_close
        self.closed = False

        self.state = STATE_IDLE
        self._style = STATE_STYLES[STATE_IDLE]
        r, g, b = _hex_to_rgb(self._style.color)
        self._live_amp = 0.0
        self._live_speed = self._style.speed
        self._live_r = float(r)
        self._live_g = float(g)
        self._live_b = float(b)
        self._target_r = float(r)
        self._target_g = float(g)
        self._target_b = float(b)
        self._target_amp = self._style.amp
        self._target_speed = self._style.speed
        self._time = 0.0
        self._last_ts = 0.0
        self._flash_alpha = 0.0
        self._drag_offset = None
        self._fade_animation: QPropertyAnimation | None = None

        self._configure_window()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self.ANIMATION_MS)

        self.apply_state(STATE_IDLE)
        if self.resident_hidden:
            self.setWindowOpacity(0.0)
            self.hide()
        else:
            self.setWindowOpacity(1.0)
            self.show()

    def _configure_window(self) -> None:
        self.setWindowTitle(self.assistant_name)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._move_bottom_center()

    def _move_bottom_center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        x = rect.x() + (rect.width() - self.WIDTH) // 2
        y = rect.y() + rect.height() - self.HEIGHT - self.BOTTOM_MARGIN
        self.move(max(rect.x(), x), max(rect.y(), y))

    def apply_state(self, state: str, detail: str | None = None) -> None:
        if self.closed:
            return
        status = get_overlay_status_text(
            state,
            detail,
            assistant_name=self.assistant_name,
            wake_phrase=self.wake_phrase,
        )
        style = STATE_STYLES.get(status.state, STATE_STYLES[STATE_ERROR])
        r, g, b = _hex_to_rgb(style.color)
        changed = status.state != self.state
        self.state = status.state
        self._style = style
        self._target_r = float(r)
        self._target_g = float(g)
        self._target_b = float(b)
        self._target_amp = style.amp
        self._target_speed = style.speed
        if changed:
            self._flash_alpha = 0.18
        if self.resident_hidden:
            if status.state in VISIBLE_WHEN_RESIDENT_HIDDEN:
                self.show_overlay()
            elif status.state in {STATE_IDLE, STATE_WAKE_CHECKING}:
                self.hide_overlay()
        self.update()

    def apply_status(self, status: Any) -> None:
        self.apply_state(getattr(status, "state", STATE_ERROR), getattr(status, "subtitle", None))

    def schedule_idle(self, delay_ms: int = 3500) -> None:
        if self.closed:
            return
        QTimer.singleShot(max(0, int(delay_ms)), lambda: self.apply_state(STATE_IDLE))

    def show_overlay(self) -> None:
        if self.closed:
            return
        self._move_bottom_center()
        self.show()
        self.raise_()
        self.activateWindow()
        self._fade_to(1.0, duration_ms=220, hide_when_done=False)

    def hide_overlay(self) -> None:
        if self.closed:
            return
        self._fade_to(0.0, duration_ms=260, hide_when_done=True)

    def _fade_to(self, target_opacity: float, *, duration_ms: int, hide_when_done: bool) -> None:
        if self._fade_animation is not None:
            self._fade_animation.stop()
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(duration_ms)
        animation.setStartValue(float(self.windowOpacity()))
        animation.setEndValue(float(target_opacity))
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if hide_when_done:
            animation.finished.connect(self._hide_if_still_transparent)
        self._fade_animation = animation
        animation.start()

    def _hide_if_still_transparent(self) -> None:
        if not self.closed and self.windowOpacity() <= 0.02:
            self.hide()

    def _tick(self) -> None:
        if self.closed:
            return
        now = time.perf_counter()
        dt = 0.033 if self._last_ts == 0 else min(now - self._last_ts, 0.05)
        self._last_ts = now
        k = 1.0 - math.pow(0.035, dt)
        self._live_amp += (self._target_amp - self._live_amp) * k
        self._live_speed += (self._target_speed - self._live_speed) * k
        self._live_r += (self._target_r - self._live_r) * k
        self._live_g += (self._target_g - self._live_g) * k
        self._live_b += (self._target_b - self._live_b) * k
        self._flash_alpha = max(0.0, self._flash_alpha - dt * 1.6)
        self._time += dt * self._live_speed
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        w = float(self.width())
        h = float(self.height())
        cy = h / 2.0
        r = int(self._live_r)
        g = int(self._live_g)
        b = int(self._live_b)
        amp_ratio = min(1.0, self._live_amp / 18.0)

        layers = max(1, int(self._style.layers))
        for index in range(layers - 1, -1, -1):
            layer_t = index / max(1, layers)
            opacity = 0.035 + (1.0 - layer_t) * 0.16
            width = max(0.55, 1.5 - index * 0.14)
            amp = self._layer_amp(index)
            path = self._wave_path(w, cy, amp, self._time, index * 0.62, 1.0 + index * 0.18)
            self._stroke_path(painter, path, r, g, b, int(opacity * 255), width)

        main_path = self._main_path(w, cy)
        flash_boost = int(self._flash_alpha * 60)
        self._stroke_path(
            painter, main_path, r, g, b,
            int((0.10 + amp_ratio * 0.10) * 255) + flash_boost,
            8.0,
        )
        self._stroke_path(
            painter, main_path, r, g, b,
            int((0.18 + amp_ratio * 0.20) * 255) + flash_boost,
            4.0,
        )
        self._stroke_path(
            painter, main_path, r, g, b,
            min(255, 220 + flash_boost),
            1.35,
        )

        mirror_path = self._main_path(w, cy, mirror=True)
        self._stroke_path(painter, mirror_path, r, g, b, int(amp_ratio * 20), 0.8)

    def _layer_amp(self, index: int) -> float:
        amp = self._live_amp
        t = self._time
        style = self._style.style
        if style == "breathe":
            return amp * (0.42 + 0.58 * math.sin(t * 0.55 + index * 0.32))
        if style == "scan":
            return amp * (0.5 + 0.5 * math.sin(t * 0.8 + index * 0.28))
        if style == "active":
            return amp * (0.62 + 0.38 * math.sin(t * 1.25 + index * 0.48))
        if style == "mid":
            return amp * (0.68 + 0.32 * math.sin(t * 0.95 + index * 0.38))
        if style == "heavy":
            return amp * (0.52 + 0.48 * math.sin(t * 1.55 + index * 0.52)) * 1.18
        if style == "soft":
            return amp * (0.38 + 0.62 * math.sin(t * 0.42 + index * 0.22))
        if style == "alert":
            return amp if abs(math.sin(t * 5.5)) > 0.35 else amp * 0.12
        return amp

    def _wave_path(
        self,
        width: float,
        center_y: float,
        amp: float,
        t: float,
        phase_offset: float,
        freq_multiplier: float,
    ) -> QPainterPath:
        points: list[tuple[float, float]] = []
        step = 6.0
        x = 0.0
        while x <= width:
            nx = x / width if width else 0.0
            env = _edge_fade(nx)
            s1 = math.sin(nx * 6.8 * freq_multiplier + t * 2.05 + phase_offset)
            s2 = math.sin(nx * 10.2 * freq_multiplier + t * 1.62 + phase_offset * 1.35)
            s3 = math.sin(nx * 3.4 * freq_multiplier + t * 2.55 + phase_offset * 0.75)
            s4 = math.sin(nx * 15.0 * freq_multiplier + t * 1.15 + phase_offset * 0.45) * 0.12
            value = (s1 * 0.54 + s2 * 0.24 + s3 * 0.14 + s4) * amp * env
            points.append((x, center_y + value))
            x += step
        points.append((width, center_y))
        return _smooth_path(points)

    def _main_path(self, width: float, center_y: float, *, mirror: bool = False) -> QPainterPath:
        points: list[tuple[float, float]] = []
        step = 5.0
        x = 0.0
        while x <= width:
            nx = x / width if width else 0.0
            env = _edge_fade(nx)
            s1 = math.sin(nx * 7.2 + self._time * 2.2)
            s2 = math.sin(nx * 11.5 + self._time * 1.68)
            value = (s1 * 0.58 + s2 * 0.42) * self._live_amp * 0.82 * env
            points.append((x, center_y - value if mirror else center_y + value))
            x += step
        points.append((width, center_y))
        return _smooth_path(points)

    @staticmethod
    def _stroke_path(
        painter: QPainter,
        path: QPainterPath,
        r: int,
        g: int,
        b: int,
        alpha: int,
        width: float,
    ) -> None:
        if alpha <= 0:
            return
        pen = QPen(QColor(r, g, b, max(0, min(255, alpha))), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.closed = True
        self.stop_event.set()
        self._timer.stop()
        if self.quit_on_close:
            QTimer.singleShot(0, QApplication.instance().quit)
        super().closeEvent(event)


class VoiceOverlayApp:
    def __init__(
        self,
        qt_app: QApplication | None = None,
        *,
        stop_event: threading.Event,
        debug: bool = False,
        start_hidden: bool = False,
        title: str = "小黄",
        wake_phrase: str = "小黄",
        quit_on_close: bool = False,
    ) -> None:
        if qt_app is not None and not isinstance(qt_app, QApplication):
            qt_app = None
        self.qt_app = qt_app or QApplication.instance() or QApplication([])
        self.stop_event = stop_event
        self.debug = debug
        self.assistant_name = title or "小黄"
        self.wake_phrase = wake_phrase or "小黄"
        self.closed = False
        self._bridge = OverlaySignalBridge()
        self._widget = WaveformDock(
            stop_event=stop_event,
            title=self.assistant_name,
            wake_phrase=self.wake_phrase,
            resident_hidden=start_hidden,
            quit_on_close=quit_on_close,
        )
        self._bridge.set_state_requested.connect(self._widget.apply_state)
        self._bridge.show_status_requested.connect(self._widget.apply_status)
        self._bridge.schedule_idle_requested.connect(self._widget.schedule_idle)
        self._bridge.show_requested.connect(self._widget.show_overlay)
        self._bridge.hide_requested.connect(self._widget.hide_overlay)
        self._bridge.close_requested.connect(self._close_widget)

    @property
    def state(self) -> str:
        return self._widget.state

    def set_state(self, state: str, detail: str | None = None) -> None:
        if not self.closed:
            self._bridge.set_state_requested.emit(state, detail)

    def thread_safe_set_state(self, state: str, detail: str | None = None) -> None:
        self.set_state(state, detail)

    def show_status(self, status) -> None:
        if not self.closed:
            self._bridge.show_status_requested.emit(status)

    def thread_safe_show_status(self, status) -> None:
        self.show_status(status)

    def schedule_idle(self, delay_ms: int = 3500) -> None:
        if not self.closed:
            self._bridge.schedule_idle_requested.emit(int(delay_ms))

    def show_overlay(self) -> None:
        if not self.closed:
            self._bridge.show_requested.emit()

    def hide_overlay(self) -> None:
        if not self.closed:
            self._bridge.hide_requested.emit()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        self._bridge.close_requested.emit()

    def _close_widget(self) -> None:
        self._widget.close()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _edge_fade(nx: float) -> float:
    fade_zone = 0.18
    if nx <= 0.0 or nx >= 1.0:
        return 0.0
    if nx < fade_zone:
        t = nx / fade_zone
        return t * t * (3 - 2 * t)
    if nx > 1.0 - fade_zone:
        t = (1.0 - nx) / fade_zone
        return t * t * (3 - 2 * t)
    return 1.0


def _smooth_path(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0][0], points[0][1])
    if len(points) == 1:
        return path
    for index in range(len(points) - 1):
        p0 = points[max(index - 1, 0)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(index + 2, len(points) - 1)]
        c1x = p1[0] + (p2[0] - p0[0]) / 6.0
        c1y = p1[1] + (p2[1] - p0[1]) / 6.0
        c2x = p2[0] - (p3[0] - p1[0]) / 6.0
        c2y = p2[1] - (p3[1] - p1[1]) / 6.0
        path.cubicTo(c1x, c1y, c2x, c2y, p2[0], p2[1])
    return path
