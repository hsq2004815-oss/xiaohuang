from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_PUNCTUATION_PATTERN = re.compile(r"[\s,，.。!！?？;；:：、\-_()[\]{}<>《》「」『』“”‘’\"'`~]+")
DEFAULT_WAKE_ALIASES = ["小皇", "小煌", "小凰"]
SUFFIX_NOISE_TOKENS = ["ang", "啊", "嗯", "呃", "呀", "哎", "诶", "呢", "嘛"]


@dataclass(frozen=True)
class WakeMatchResult:
    detected: bool
    reason: str
    score: float
    normalized_text: str
    matched_phrase: str | None


def parse_wake_phrases(value: str | Iterable[str]) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,，]", value)
    else:
        parts = list(value)
    return [part.strip() for part in parts if part and part.strip()]


def normalize_wake_text(text: str) -> str:
    return _PUNCTUATION_PATTERN.sub("", text).lower()


def detect_wake_phrase(
    text: str,
    wake_phrases: str | Iterable[str],
    alias_phrases: str | Iterable[str] | None = None,
) -> WakeMatchResult:
    normalized_text = normalize_wake_text(text)
    if not normalized_text:
        return WakeMatchResult(
            detected=False,
            reason="empty_text",
            score=0.0,
            normalized_text=normalized_text,
            matched_phrase=None,
        )

    normalized_phrases = _normalized_phrases(wake_phrases)
    for phrase, normalized_phrase in normalized_phrases:
        if normalized_text == normalized_phrase:
            return WakeMatchResult(True, "exact_match", 1.0, normalized_text, phrase)

    for phrase, normalized_phrase in normalized_phrases:
        if _has_suffix_noise(normalized_text, normalized_phrase):
            return WakeMatchResult(True, "suffix_noise_match", 0.9, normalized_text, phrase)

    for phrase, normalized_phrase in normalized_phrases:
        if normalized_phrase in normalized_text:
            return WakeMatchResult(True, "contains_match", 0.95, normalized_text, phrase)

    for alias in _normalized_aliases(alias_phrases):
        if alias and alias in normalized_text:
            return WakeMatchResult(True, "alias_match", 0.75, normalized_text, alias)

    return WakeMatchResult(False, "no_match", 0.0, normalized_text, None)


def is_wake_phrase_detected(text: str, wake_phrases: str | Iterable[str]) -> bool:
    return detect_wake_phrase(text, wake_phrases).detected


def _normalized_phrases(wake_phrases: str | Iterable[str]) -> list[tuple[str, str]]:
    phrases = []
    for phrase in parse_wake_phrases(wake_phrases):
        normalized_phrase = normalize_wake_text(phrase)
        if normalized_phrase:
            phrases.append((phrase, normalized_phrase))
    return sorted(phrases, key=lambda item: len(item[1]), reverse=True)


def _normalized_aliases(alias_phrases: str | Iterable[str] | None) -> list[str]:
    aliases = DEFAULT_WAKE_ALIASES if alias_phrases is None else parse_wake_phrases(alias_phrases)
    return [normalize_wake_text(alias) for alias in aliases if normalize_wake_text(alias)]


def _has_suffix_noise(normalized_text: str, normalized_phrase: str) -> bool:
    if not normalized_text.startswith(normalized_phrase):
        return False
    suffix = normalized_text[len(normalized_phrase) :]
    if not suffix:
        return False
    return suffix in SUFFIX_NOISE_TOKENS
