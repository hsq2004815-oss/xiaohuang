from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable, Mapping
from urllib import request

from xiaohuang.reply_service import generate_reply


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
TOOL_UNAVAILABLE_REPLY = "我可以先帮你整理任务，但当前版本还不能执行工具。"

PostJsonFunc = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


@dataclass(frozen=True)
class LlmReplyConfig:
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class ReplyGenerationResult:
    text: str
    source: str


def load_deepseek_config(
    *,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 15,
    model_override: str | None = None,
    base_url_override: str | None = None,
) -> LlmReplyConfig:
    source = os.environ if env is None else env
    return LlmReplyConfig(
        api_key=_empty_to_none(source.get("DEEPSEEK_API_KEY")),
        base_url=(base_url_override or source.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/"),
        model=model_override or source.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL,
        timeout_seconds=float(timeout_seconds),
    )


def build_deepseek_request(user_text: str, *, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 Windows 桌面语音助手小黄。只做单句自然回复，30 个汉字以内。"
                    "不要编造已经执行了任务；如果用户要求实际操作，只说明当前版本不能执行工具。"
                ),
            },
            {"role": "user", "content": str(user_text or "").strip()},
        ],
        "temperature": 0.4,
        "max_tokens": 80,
        "stream": False,
    }


def generate_llm_reply(
    user_text: str,
    *,
    config: LlmReplyConfig | None = None,
    fallback_func: Callable[[str], str] = generate_reply,
    post_json_func: PostJsonFunc | None = None,
) -> str:
    return generate_llm_reply_result(
        user_text,
        config=config,
        fallback_func=fallback_func,
        post_json_func=post_json_func,
    ).text


def generate_llm_reply_result(
    user_text: str,
    *,
    config: LlmReplyConfig | None = None,
    fallback_func: Callable[[str], str] = generate_reply,
    post_json_func: PostJsonFunc | None = None,
) -> ReplyGenerationResult:
    if _looks_like_tool_request(user_text):
        return ReplyGenerationResult(TOOL_UNAVAILABLE_REPLY, "tool_unavailable")

    resolved_config = config or load_deepseek_config()
    if not resolved_config.is_configured:
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_no_key")

    try:
        response = (post_json_func or _post_json)(
            _chat_completions_url(resolved_config.base_url),
            build_deepseek_request(user_text, model=resolved_config.model),
            {
                "Authorization": f"Bearer {resolved_config.api_key}",
                "Content-Type": "application/json",
            },
            resolved_config.timeout_seconds,
        )
        reply = _shorten_reply(_extract_reply_text(response))
        if reply:
            return ReplyGenerationResult(reply, "llm")
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_empty")
    except Exception:
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_error")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=encoded, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _chat_completions_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/chat/completions"):
        return stripped
    return f"{stripped}/chat/completions"


def _extract_reply_text(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, Mapping):
        return ""
    message = first.get("message")
    if isinstance(message, Mapping):
        return str(message.get("content") or "").strip()
    return str(first.get("text") or "").strip()


def _shorten_reply(text: str, max_length: int = 30) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rstrip("，。！？、,.!? ") + "。"


def _looks_like_tool_request(text: str) -> bool:
    normalized = str(text or "").replace(" ", "")
    tool_keywords = (
        "打开",
        "运行",
        "搜索",
        "下载",
        "发给",
        "发送",
        "回复微信",
        "回复qq",
        "写代码",
        "提交",
        "浏览器",
        "爬",
    )
    return any(keyword in normalized.lower() for keyword in tool_keywords)


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
