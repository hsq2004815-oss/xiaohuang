from __future__ import annotations

import re


_PUNCTUATION_PATTERN = re.compile(r"[\s，。！？、,.!?]+")


def generate_reply(user_text: str) -> str:
    text = _clean_user_text(user_text)
    normalized = _normalize_for_match(text)

    if normalized in {"你好", "你好小黄", "小黄你好"}:
        return "你好，我在。"
    if _looks_like_status_question(normalized):
        return "我在听你说话，准备帮你处理任务。"
    if _looks_like_model_identity_question(normalized):
        return "我是小黄，当前可接 DeepSeek 单句回复。"
    if "测试" in normalized:
        return "测试收到，语音链路正常。"
    if not text:
        return "我在。"
    return f"我听到了：{_truncate_for_reply(text)}"


def _clean_user_text(user_text: str) -> str:
    return " ".join(str(user_text or "").split()).strip()


def _normalize_for_match(text: str) -> str:
    return _PUNCTUATION_PATTERN.sub("", text).strip()


def _looks_like_status_question(normalized_text: str) -> bool:
    return (
        "你在干嘛" in normalized_text
        or "你想干嘛" in normalized_text
        or "在干嘛" in normalized_text
        or "想干嘛" in normalized_text
        or normalized_text.endswith("干嘛")
        or normalized_text.endswith("干嘛呢")
    )


def _looks_like_model_identity_question(normalized_text: str) -> bool:
    lowered = normalized_text.lower()
    return (
        "deepseek" in lowered
        or "deepseek" in lowered.replace(" ", "")
        or "大模型" in normalized_text
        or "什么模型" in normalized_text
        or "哪个模型" in normalized_text
    )


def _truncate_for_reply(text: str, max_text_length: int = 20) -> str:
    if len(text) <= max_text_length:
        return text
    return text[:max_text_length].rstrip("，。！？、,.!? ") + "..."
