from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from xiaohuang.app_config_service import get_default_config_path
from xiaohuang.text_interaction_service import run_text_interaction_turn
from xiaohuang.text_interaction_session_service import TextInteractionSessionStore


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "data": data, "message": message}


def _fail(error: str, code: str = "error") -> dict:
    return {"ok": False, "error": error, "code": code}


class TextChatWebApi:
    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is not None and str(config_path).strip():
            self._config_path = Path(config_path)
        else:
            self._config_path = None
        self._sessions = TextInteractionSessionStore()

    def _resolve_config_path(self) -> Path:
        if self._config_path:
            return self._config_path
        return get_default_config_path()

    def send_message(self, payload: dict) -> dict:
        try:
            text = ""
            session_id = "default"
            if isinstance(payload, dict):
                text = str(payload.get("text") or "")
                session_id = str(payload.get("session_id") or "default")

            result = run_text_interaction_turn(
                text,
                session_store=self._sessions,
                session_id=session_id,
                config_path=self._resolve_config_path(),
            )
            return _ok(data=asdict(result), message="消息已回复" if result.ok else "消息处理失败")
        except Exception:
            return _fail("文本消息处理失败", "send_message_error")

    def clear_session(self, payload: dict | None = None) -> dict:
        try:
            session_id = "default"
            if isinstance(payload, dict):
                session_id = str(payload.get("session_id") or "default")
            self._sessions.clear(session_id)
            return _ok(data={"session_id": session_id}, message="会话已清空")
        except Exception:
            return _fail("清空会话失败", "clear_session_error")
