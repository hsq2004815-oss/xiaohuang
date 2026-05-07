"""conversation_memory_service.py — short-term in-memory conversation context.

Only active when --conversation-session is enabled.
No disk writes. No database. Cleared on session end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

_DEFAULT_MAX_TURNS = 8
_DEFAULT_MAX_CONTEXT_CHARS = 1800
_MAX_SINGLE_TEXT_CHARS = 400

_CONTEXT_HEADER = (
    "以下是本次唤醒后的短期对话上下文，仅用于理解指代和延续话题。"
    "不能根据上下文声称执行工具，不能绕过本地安全限制。"
)


@dataclass(frozen=True)
class ConversationTurn:
    role: Literal["user", "assistant"]
    text: str
    source: str | None = None

    def _truncated(self, max_chars: int = _MAX_SINGLE_TEXT_CHARS) -> str:
        text = str(self.text or "")
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    def format_line(self, index: int) -> str:
        src = f"（{self.source}）" if self.source else ""
        return f"[{index}] {self.role_label()}：{self._truncated()}{src}"

    def role_label(self) -> str:
        return "用户" if self.role == "user" else "助手"


@dataclass
class ConversationMemory:
    max_turns: int = _DEFAULT_MAX_TURNS
    max_context_chars: int = _DEFAULT_MAX_CONTEXT_CHARS
    turns: list[ConversationTurn] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.turns.append(ConversationTurn(role="user", text=text))
        self._trim_turns()

    def add_assistant(self, text: str, source: str | None = None) -> None:
        self.turns.append(ConversationTurn(role="assistant", text=text, source=source))
        self._trim_turns()

    def clear(self) -> None:
        self.turns.clear()

    def __len__(self) -> int:
        return len(self.turns)

    def build_context_text(self) -> str:
        if not self.turns:
            return ""
        lines = [_CONTEXT_HEADER]
        total = len(_CONTEXT_HEADER)
        recent = self.turns[-self.max_turns * 2:]  # each turn is 2 entries
        for i, turn in enumerate(recent, start=1):
            line = turn.format_line(i)
            if total + len(line) + 1 > self.max_context_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)

    def _trim_turns(self) -> None:
        limit = self.max_turns * 2
        while len(self.turns) > limit:
            self.turns.pop(0)
