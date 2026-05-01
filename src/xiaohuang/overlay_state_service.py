from __future__ import annotations

from dataclasses import dataclass


STATE_IDLE = "idle"
STATE_WAKE_CHECKING = "wake_checking"
STATE_WAKE_DETECTED = "wake_detected"
STATE_LISTENING = "listening"
STATE_TRANSCRIBING = "transcribing"
STATE_REPLYING = "replying"
STATE_SPEAKING = "speaking"
STATE_RESULT = "result"
STATE_ERROR = "error"


@dataclass(frozen=True)
class OverlayStatus:
    state: str
    title: str
    subtitle: str


def get_overlay_status_text(state: str, detail: str | None = None) -> OverlayStatus:
    if state == STATE_IDLE:
        return OverlayStatus(state=state, title="小黄待机中", subtitle="说“小黄”唤醒我")
    if state == STATE_WAKE_CHECKING:
        return OverlayStatus(state=state, title="正在等待唤醒词", subtitle="等待唤醒词：小黄")
    if state == STATE_WAKE_DETECTED:
        return OverlayStatus(state=state, title="我在", subtitle="请说你的命令")
    if state == STATE_LISTENING:
        return OverlayStatus(state=state, title="正在听你说话", subtitle="说完后我会自动停止")
    if state == STATE_TRANSCRIBING:
        return OverlayStatus(state=state, title="识别中...", subtitle="正在转写你的语音")
    if state == STATE_REPLYING:
        return OverlayStatus(state=state, title="正在想怎么回复...", subtitle="生成一条简短回复")
    if state == STATE_SPEAKING:
        return OverlayStatus(state=state, title="小黄正在说话", subtitle=detail or "正在播放语音回复")
    if state == STATE_RESULT:
        return OverlayStatus(state=state, title="你说：", subtitle=detail or "")
    if state == STATE_ERROR:
        return OverlayStatus(state=state, title="出错了", subtitle=detail or "请查看控制台输出")
    return OverlayStatus(state=STATE_ERROR, title="出错了", subtitle=f"未知状态：{state}")


def build_server_unavailable_status(server_url: str) -> OverlayStatus:
    return OverlayStatus(
        state=STATE_ERROR,
        title="STT server 未启动",
        subtitle=f"请先运行 python scripts\\stt_server.py --host 127.0.0.1 --port 8766 ({server_url})",
    )


def build_reply_result_text(user_text: str, reply_text: str) -> str:
    return f"你说：{user_text}\n小黄：{reply_text}"
