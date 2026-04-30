from __future__ import annotations

import re
from typing import Iterable


_PUNCTUATION_PATTERN = re.compile(r"[\s,，.。!！?？;；:：、\-_()[\]{}<>《》「」『』“”‘’\"'`~]+")


def parse_wake_phrases(value: str | Iterable[str]) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,，]", value)
    else:
        parts = list(value)
    return [part.strip() for part in parts if part and part.strip()]


def normalize_wake_text(text: str) -> str:
    return _PUNCTUATION_PATTERN.sub("", text).lower()


def is_wake_phrase_detected(text: str, wake_phrases: str | Iterable[str]) -> bool:
    normalized_text = normalize_wake_text(text)
    if not normalized_text:
        return False

    for phrase in parse_wake_phrases(wake_phrases):
        normalized_phrase = normalize_wake_text(phrase)
        if normalized_phrase and normalized_phrase in normalized_text:
            return True
    return False
