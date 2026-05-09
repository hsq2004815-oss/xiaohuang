from __future__ import annotations

from dataclasses import dataclass, field

from xiaohuang.conversation_memory_service import ConversationMemory


@dataclass
class TextInteractionSession:
    session_id: str
    memory: ConversationMemory = field(default_factory=ConversationMemory)


class TextInteractionSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, TextInteractionSession] = {}

    def get_or_create(self, session_id: str = "default") -> TextInteractionSession:
        sid = _normalize_session_id(session_id)
        if sid not in self._sessions:
            self._sessions[sid] = TextInteractionSession(session_id=sid)
        return self._sessions[sid]

    def clear(self, session_id: str = "default") -> None:
        sid = _normalize_session_id(session_id)
        if sid in self._sessions:
            self._sessions[sid].memory.clear()

    def build_context_text(self, session_id: str = "default") -> str:
        return self.get_or_create(session_id).memory.build_context_text()


def _normalize_session_id(session_id: str = "default") -> str:
    return str(session_id or "default").strip() or "default"
