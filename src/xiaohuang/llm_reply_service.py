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
DEFAULT_MAX_REPLY_CHARS = 180
DEFAULT_LLM_MAX_TOKENS = 768

_DEFAULT_VOICE_PERSONA = (
    "你是小黄，一个可靠的 Windows 桌面语音助手。"
    "回答要自然、清楚，默认用 2-3 句说明重点；"
    "涉及事实、步骤、原因时可以稍微展开，但避免长篇。"
    "不要声称你已经执行了没有真实执行的操作。"
)

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-turbo",
        "api_key_env": "QWEN_API_KEY",
    },
    "doubao": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-lite-32k",
        "api_key_env": "DOUBAO_API_KEY",
    },
    "openai_compatible": {
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "default",
        "api_key_env": "OPENAI_API_KEY",
    },
}

def _read_int_env(
    name: str,
    default: int,
    lo: int,
    hi: int,
    *,
    env: Mapping[str, str] | None = None,
) -> int:
    source = os.environ if env is None else env
    raw = source.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        if lo <= value <= hi:
            return value
    except (ValueError, TypeError):
        pass
    return default


def _get_default_max_reply_chars(env: Mapping[str, str] | None = None) -> int:
    return _read_int_env("XIAOHUANG_MAX_REPLY_CHARS", DEFAULT_MAX_REPLY_CHARS, 40, 500, env=env)


def _get_default_llm_max_tokens(env: Mapping[str, str] | None = None) -> int:
    return _read_int_env("XIAOHUANG_LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS, 64, 4096, env=env)


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
    temperature: float = 0.4
    provider: str = "deepseek"

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
    if max_tokens_override is not None:
        max_tokens = max_tokens_override
    else:
        max_tokens = _get_default_llm_max_tokens(env=source)
    return LlmReplyConfig(
        api_key=_empty_to_none(source.get("DEEPSEEK_API_KEY")),
        base_url=(base_url_override or source.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/"),
        model=model_override or source.get("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL,
        timeout_seconds=float(timeout_seconds),
        max_tokens=max_tokens,
    )


def load_llm_provider_config(
    app_llm_config: Any,
    *,
    env: Mapping[str, str] | None = None,
) -> LlmReplyConfig:
    """Build LlmReplyConfig from app_config_service LlmConfig.

    Reads api_key from the environment variable named in app_llm_config.api_key_env.
    Falls back to provider defaults for model/base_url when config values match built-in defaults.
    """
    source = os.environ if env is None else env
    provider = str(app_llm_config.provider or "deepseek").strip()
    pd = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["deepseek"])

    api_key_env = str(app_llm_config.api_key_env or pd["api_key_env"]).strip()
    api_key = _empty_to_none(source.get(api_key_env))

    model = str(app_llm_config.model or pd["model"]).strip()
    base_url = str(app_llm_config.base_url or pd["base_url"]).strip().rstrip("/")
    timeout = float(app_llm_config.timeout_seconds if app_llm_config.timeout_seconds is not None else 20.0)
    resolved_max_tokens = int(app_llm_config.max_tokens) if app_llm_config.max_tokens is not None else 0
    if resolved_max_tokens <= 0:
        resolved_max_tokens = _get_default_llm_max_tokens(env=source)
    temperature = float(app_llm_config.temperature) if app_llm_config.temperature is not None else 0.4

    return LlmReplyConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout,
        max_tokens=resolved_max_tokens,
        temperature=temperature,
        provider=provider,
    )


def build_openai_compatible_chat_request(
    user_text: str,
    *,
    model: str,
    max_tokens: int = 256,
    temperature: float = 0.4,
    persona: str | None = None,
    provider: str = "deepseek",
    conversation_context: str | None = None,
) -> dict[str, Any]:
    system_content = persona if persona else _DEFAULT_VOICE_PERSONA
    if conversation_context:
        system_content = system_content + "\n\n" + str(conversation_context)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": str(user_text or "").strip()},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if provider == "deepseek":
        payload["thinking"] = {"type": "disabled"}
    return payload


def build_deepseek_request(
    user_text: str,
    *,
    model: str,
    max_tokens: int = 256,
    persona: str | None = None,
) -> dict[str, Any]:
    return build_openai_compatible_chat_request(
        user_text,
        model=model,
        max_tokens=max_tokens,
        persona=persona,
        provider="deepseek",
    )


def generate_llm_reply(
    user_text: str,
    *,
    config: LlmReplyConfig | None = None,
    fallback_func: Callable[[str], str] = generate_reply,
    post_json_func: PostJsonFunc | None = None,
    on_debug: Callable[[str], None] | None = None,
    persona: str | None = None,
    conversation_context: str | None = None,
) -> str:
    return generate_llm_reply_result(
        user_text,
        config=config,
        fallback_func=fallback_func,
        post_json_func=post_json_func,
        on_debug=on_debug,
        persona=persona,
        conversation_context=conversation_context,
    ).text


def generate_llm_reply_result(
    user_text: str,
    *,
    config: LlmReplyConfig | None = None,
    fallback_func: Callable[[str], str] = generate_reply,
    post_json_func: PostJsonFunc | None = None,
    on_debug: Callable[[str], None] | None = None,
    persona: str | None = None,
    conversation_context: str | None = None,
) -> ReplyGenerationResult:
    if _looks_like_tool_request(user_text):
        return ReplyGenerationResult(TOOL_UNAVAILABLE_REPLY, "tool_unavailable")

    resolved_config = config or load_deepseek_config()
    if not resolved_config.is_configured:
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_no_key")

    provider_label = resolved_config.provider or "deepseek"
    try:
        response = (post_json_func or _post_json)(
            _chat_completions_url(resolved_config.base_url),
            build_openai_compatible_chat_request(
                user_text,
                model=resolved_config.model,
                max_tokens=resolved_config.max_tokens,
                temperature=resolved_config.temperature,
                persona=persona,
                provider=provider_label,
                conversation_context=conversation_context,
            ),
            {
                "Authorization": f"Bearer {resolved_config.api_key}",
                "Content-Type": "application/json",
            },
            resolved_config.timeout_seconds,
        )
    except json.JSONDecodeError:
        _emit_debug(on_debug, f"LLM JSONDecodeError ({provider_label}): response body is not valid JSON")
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_error")
    except UnicodeError:
        _emit_debug(on_debug, f"LLM UnicodeError ({provider_label}): response encoding issue")
        return ReplyGenerationResult(fallback_func(user_text), "rule_fallback_error")
    except Exception as exc:
        _emit_debug(on_debug, _format_request_exception(exc, on_debug, provider_label))
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


def _shorten_reply(
    text: str,
    max_length: int | None = None,
    max_sentences: int = 3,
) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return cleaned

    resolved_max = max_length if max_length is not None else _get_default_max_reply_chars()
    if len(cleaned) <= resolved_max:
        return cleaned

    sentence_ends = "。！？；.!?;"
    soft_breaks = "，、, "

    # Find the last sentence-end within resolved_max
    window = cleaned[:resolved_max]
    last_sent = _last_index_of_any(window, sentence_ends)

    if last_sent > 0:
        prefix = cleaned[:last_sent + 1]
        sent_count = sum(1 for ch in prefix if ch in sentence_ends)
        if sent_count > max_sentences:
            count = 0
            for i, ch in enumerate(prefix):
                if ch in sentence_ends:
                    count += 1
                    if count == max_sentences:
                        return prefix[:i + 1].rstrip()
        return prefix.rstrip()

    # No sentence end — try softer boundary
    last_soft = _last_index_of_any(window, soft_breaks)
    if last_soft > 0:
        return window[:last_soft].rstrip(soft_breaks) + "。"

    # Hard truncate
    return window.rstrip("，。！？、,.!?;； ") + "。"


def _last_index_of_any(text: str, chars: str) -> int:
    idx = -1
    for ch in chars:
        pos = text.rfind(ch)
        if pos > idx:
            idx = pos
    return idx


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


def _format_request_exception(exc: Exception, on_debug: object, provider: str = "deepseek") -> str:
    exc_type = type(exc).__name__
    from urllib.error import HTTPError, URLError
    if isinstance(exc, HTTPError):
        body = ""
        try:
            body = exc.read(500).decode("utf-8", errors="replace")
        except Exception:
            pass
        return f"LLM HTTPError ({provider}) status={exc.code} url={_redact_url(str(exc.url))} body_truncated={body}"
    if isinstance(exc, URLError):
        return f"LLM URLError ({provider}) reason={exc.reason}"
    if isinstance(exc, TimeoutError):
        return f"LLM TimeoutError ({provider}): request timed out"
    if isinstance(exc, OSError):
        return f"LLM OSError ({provider}): {exc}"
    return f"LLM {exc_type} ({provider}): {exc}"


def _redact_url(url: str) -> str:
    import re
    return re.sub(r'(api[-_]?key|token|secret)=[^&]+', r'\1=REDACTED', url)


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
