"""startup_diagnostics/service.py — log-based startup failure diagnostics.

Reads tail of log files and identifies common failure patterns.
No STT / LLM / TTS calls. No process launch. No secrets access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaohuang.capabilities.startup_diagnostics.models import StartupDiagnostic

_SENSITIVE_KEYS = {
    "api_key", "api_key_env", "secret", "password", "token",
    "authorization", "access_key", "private_key",
}

_LOG_FILES = [
    "stt_server.err.log",
    "stt_server.out.log",
    "voice_overlay.err.log",
]

_TAIL_LINES = 80
_MAX_TEXT_LENGTH = 2000

_PATTERNS: list[dict] = [
    {
        "kind": "memory_error",
        "severity": "error",
        "keywords": [
            "DefaultCPUAllocator: not enough memory",
            "not enough memory",
        ],
        "summary_zh": "STT 模型加载失败，可能是内存不足。",
        "suggestion_zh": "建议关闭 Chrome / VSCode / Claude Code / 其他大内存程序后重试；如果仍失败，可增加 Windows 虚拟内存。",
    },
    {
        "kind": "memory_error",
        "severity": "error",
        "keywords": [
            "ModelInitializationError",
            "FunASR model initialization failed",
        ],
        "summary_zh": "STT 模型初始化失败，可能是内存或模型文件问题。",
        "suggestion_zh": "检查系统内存是否充足，或模型文件是否完整。若持续失败，可尝试切换 STT 设备为 cpu。",
    },
    {
        "kind": "run_env_parse_error",
        "severity": "error",
        "keywords": ["ParserError", "AmpersandNotAllowed"],
        "context_requires": ["run_env.ps1"],
        "summary_zh": "启动环境脚本解析失败，可能是 run_env.ps1 中的 PowerShell 字符串转义问题。",
        "suggestion_zh": "建议检查 scripts/run_env.ps1，或使用不依赖 run_env.ps1 的启动脚本。",
    },
    {
        "kind": "run_env_parse_error",
        "severity": "error",
        "keywords": ["字符串缺少终止符", "不允许使用与号"],
        "context_requires": ["run_env.ps1"],
        "summary_zh": "启动环境脚本解析失败，可能是 run_env.ps1 中的 PowerShell 字符串转义问题。",
        "suggestion_zh": "建议检查 scripts/run_env.ps1，或使用不依赖 run_env.ps1 的启动脚本。",
    },
    {
        "kind": "port_or_health_error",
        "severity": "error",
        "keywords": [
            "address already in use",
            "Only one usage of each socket address",
        ],
        "summary_zh": "STT 服务端口被占用。",
        "suggestion_zh": "建议检查 8766 端口是否被其他程序占用，或终止占用该端口的进程后重试。",
    },
    {
        "kind": "port_or_health_error",
        "severity": "error",
        "keywords": [
            "actively refused",
            "connection refused",
            "无法连接",
        ],
        "summary_zh": "STT 服务端口不可用或服务未启动。",
        "suggestion_zh": "建议检查 STT server 是否正常运行，或查看 stt_server 日志。",
    },
    {
        "kind": "model_cache_error",
        "severity": "warning",
        "keywords": [
            "model_path_not_found",
            "checksum",
        ],
        "summary_zh": "模型缓存或下载可能异常。",
        "suggestion_zh": "建议检查 MODELSCOPE_CACHE / HF_HOME 路径和网络状态。",
    },
    {
        "kind": "model_cache_error",
        "severity": "warning",
        "keywords": ["No such file"],
        "context_requires": ["model"],
        "summary_zh": "模型文件缺失。",
        "suggestion_zh": "建议检查模型缓存目录是否完整，或重新下载模型。",
    },
    {
        "kind": "model_cache_error",
        "severity": "warning",
        "keywords": [
            "ConnectionError",
            "ReadTimeout",
        ],
        "summary_zh": "模型下载网络异常。",
        "suggestion_zh": "检查网络连接是否正常，或尝试使用代理下载模型。",
    },
]


def diagnose_startup_failure(project_root: Path) -> StartupDiagnostic:
    log_texts = _read_log_files(project_root)
    return diagnose_logs(log_texts)


def diagnose_logs(log_texts: dict[str, str]) -> StartupDiagnostic:
    combined = _combine_log_texts(log_texts)
    return _match_patterns(combined, log_texts)


def _combine_log_texts(log_texts: dict[str, str]) -> str:
    parts = []
    for _path, text in log_texts.items():
        if text:
            parts.append(text)
    return "\n".join(parts)


def _read_log_files(project_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel_path in _LOG_FILES:
        full_path = project_root / "logs" / rel_path
        try:
            if not full_path.is_file():
                continue
            text = _read_tail(full_path, _TAIL_LINES)
            if text:
                result[rel_path] = text[-_MAX_TEXT_LENGTH:] if len(text) > _MAX_TEXT_LENGTH else text
        except Exception:
            pass
    return result


def _read_tail(path: Path, lines: int) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return ""
    if not content:
        return ""
    all_lines = content.splitlines()
    return "\n".join(all_lines[-lines:])


def _match_patterns(combined: str, log_texts: dict[str, str]) -> StartupDiagnostic:
    combined_lower = combined.lower()

    for pattern in _PATTERNS:
        kw_match = _match_keywords(combined, pattern.get("keywords", []))
        if not kw_match:
            continue
        context_req = pattern.get("context_requires", [])
        if context_req:
            has_context = any(req.lower() in combined_lower for req in context_req)
            if not has_context:
                continue
        source_file = _find_source_file(kw_match, log_texts)
        return StartupDiagnostic(
            kind=pattern["kind"],
            severity=pattern["severity"],
            summary=pattern["summary_zh"],
            suggestion=pattern["suggestion_zh"],
            source_file=source_file,
            matched_text=_truncate_text(kw_match),
        )

    if combined.strip():
        return StartupDiagnostic(
            kind="unknown",
            severity="warning",
            summary="启动失败，但未识别出明确原因。",
            suggestion="请查看 logs/stt_server.err.log 和 logs/voice_overlay.err.log。",
        )

    return StartupDiagnostic(
        kind="none",
        severity="info",
        summary="未找到相关日志。",
        suggestion="请确认 STT server 和 voice overlay 日志文件是否存在。",
    )


def _match_keywords(text: str, keywords: list[str]) -> str | None:
    for kw in keywords:
        if kw in text:
            for line in text.splitlines():
                if kw in line:
                    return line.strip()
            return kw
    return None


def _find_source_file(matched_text: str | None, log_texts: dict[str, str]) -> str | None:
    if not matched_text:
        return None
    for path, text in log_texts.items():
        if matched_text in text:
            return f"logs/{path}"
    return None


def _truncate_text(text: str | None, max_len: int = 200) -> str | None:
    if text is None:
        return None
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def sanitize_diagnostic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: sanitize_diagnostic_value(v)
            for k, v in value.items()
            if k.lower() not in _SENSITIVE_KEYS
        }
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "..."
    return value
