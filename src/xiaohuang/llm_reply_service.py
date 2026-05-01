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

_EXECUTION_CLAIM_KEYWORDS = (
    "我已经打开", "我已经下载", "我已经发送", "我已经执行",
    "我已经修改", "我已经删除", "我已经上传", "我已经登录",
    "我已经支付", "我已经爬取", "已经帮你打开", "已经帮你下载",
    "已打开", "已下载", "已发送", "已执行",
    "已修改", "已删除", "已上传", "已登录",
    "已支付", "已爬取", "已完成",
)

PostJsonFunc = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


@dataclass(frozen=True)
class LlmReplyConfig:
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float
    max_tokens: int = 256

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
    max_tokens_override: int | None = None,
) -> LlmReplyConfig:
    source = os.environ if env is None else env
    max_tokens = max_tokens_override
    if max_tokens is None:
        env_value = source.get("DEEPSEEK_MAX_TOKENS")
        max_tokens = int(env_value) if env_value else None
    return LlmReplyConfig(
        api_key=_empty_to_none(source.get("DEEPSEEK_API_KEY")),
        base_url=(base_url_override or source.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/"),
        model=model_override or source.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL,
        timeout_seconds=float(timeout_seconds),
        max_tokens=max_tokens if max_tokens is not None else 256,
    )


def build_deepseek_request(user_text: str, *, model: str, max_tokens: int = 256) -> dict[str, Any]:
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
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "disabled"},
    }


def generate_llm_reply(
    user_text: str,
    *,
    config: LlmReplyConfig | None = None,
    fallback_func: Callable[[str], str] = generate_reply,
    post_json_func: PostJsonFunc | None = None,
    on_debug: Callable[[str], None] | None = None,
) -> str:
    return generate_llm_reply_result(
        user_text,
        config=config,
        fallback_func=fallback_func,
        post_json_func=post_json_func,
        on_debug=on_debug,
    ).text


def generate_llm_reply_result(
    user_text: str,
    *,
    config: LlmReplyConfig | None = None,
    fallback_func: Callable[[str], str] = generate_reply,
    post_json_func: PostJsonFunc | None = None,
    on_debug: Callable[[str], None] | None = None,
) -> ReplyGenerationResult:
    if _looks_like_tool_request(user_text):
        return ReplyGenerationResult(TOOL_UNAVAILABLE_REPLY, "tool_unavailable")

    resolved_config = config or load_deepseek_config()
    if not resolved_config.is_configured:
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_no_key")

    try:
        response = (post_json_func or _post_json)(
            _chat_completions_url(resolved_config.base_url),
            build_deepseek_request(user_text, model=resolved_config.model, max_tokens=resolved_config.max_tokens),
            {
                "Authorization": f"Bearer {resolved_config.api_key}",
                "Content-Type": "application/json",
            },
            resolved_config.timeout_seconds,
        )
    except Exception:
        _emit_debug(on_debug, "DeepSeek request raised exception (network/timeout/http error)")
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_error")

    if isinstance(response.get("error"), dict):
        _emit_debug(on_debug, build_deepseek_response_debug_summary(response))
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_error")

    raw_text = _extract_reply_text(response)
    finish_reason = _get_finish_reason(response)
    reply = _shorten_reply(raw_text)

    if reply:
        if _looks_like_execution_claim(reply):
            return ReplyGenerationResult(TOOL_UNAVAILABLE_REPLY, "tool_unavailable")
        if finish_reason in ("content_filter", "insufficient_system_resource", "length"):
            _emit_debug(on_debug, build_deepseek_response_debug_summary(response))
        return ReplyGenerationResult(reply, "llm")

    # empty reply — classify by finish_reason
    _emit_debug(on_debug, build_deepseek_response_debug_summary(response))
    if finish_reason == "length":
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_length")
    return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_empty")


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
    normalized = str(text or "").replace(" ", "").lower()
    tool_keywords = (
        "打开浏览器", "打开网页", "打开网站",
        "下载", "下载文件",
        "发消息", "发送消息", "发给", "发送",
        "回微信", "回复微信",
        "回qq", "回复qq",
        "改代码", "修改代码", "写代码",
        "删除文件", "删掉",
        "上传", "上传资料",
        "登录", "登录账号",
        "支付", "付款",
        "爬取", "爬虫", "爬网页",
        "调用opencode", "opencode",
        "调用opencli", "opencli",
        "打开", "运行", "浏览器",
    )
    return any(keyword in normalized for keyword in tool_keywords)


def _looks_like_execution_claim(text: str) -> bool:
    return any(keyword in str(text) for keyword in _EXECUTION_CLAIM_KEYWORDS)


def build_deepseek_response_debug_summary(response: Mapping[str, Any]) -> str:
    parts: list[str] = []
    error = response.get("error")
    if isinstance(error, dict):
        error_type = str(error.get("type", ""))[:50]
        error_msg = str(error.get("message", ""))[:100]
        parts.append(f"has_error=True error_type={error_type} error_message={error_msg}")
    else:
        parts.append("has_error=False")
    choices = response.get("choices")
    if isinstance(choices, list):
        parts.append(f"choices_count={len(choices)}")
        if choices and isinstance(choices[0], dict):
            first = choices[0]
            finish_reason = first.get("finish_reason")
            parts.append(f"finish_reason={finish_reason}")
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                parts.append(f"has_message=True content_length={len(str(content or ''))}")
            else:
                parts.append("has_message=False")
    else:
        parts.append("choices_count=0")
    model = response.get("model")
    if model:
        parts.append(f"model={model}")
    parts.append("has_usage=True" if isinstance(response.get("usage"), dict) else "has_usage=False")
    return " | ".join(parts)


def _emit_debug(on_debug: Callable[[str], None] | None, message: str) -> None:
    if on_debug is not None:
        on_debug(message)


def _get_finish_reason(response: Mapping[str, Any]) -> str | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    finish_reason = choices[0].get("finish_reason")
    if finish_reason is None:
        return None
    return str(finish_reason)


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
