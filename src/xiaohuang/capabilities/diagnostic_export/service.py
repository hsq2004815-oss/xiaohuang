"""diagnostic_export/service.py — format and write diagnostic TXT exports.

No STT / LLM / TTS calls. No process launch. No voice overlay access.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from xiaohuang.capabilities.diagnostic_export.models import (
    DiagnosticExportInput,
    DiagnosticExportResult,
)

_SENSITIVE_KEYS = {
    "api_key", "api_key_env", "secret", "password", "token",
    "authorization", "access_key", "private_key",
}
_EXPORT_SUBDIR = "diagnostic_exports"
_MAX_HISTORY_ENTRIES = 30
_BOOL_YES = "是"
_BOOL_NO = "否"
_HTML_ESCAPE_TABLE = str.maketrans({
    "<": "&lt;",
    ">": "&gt;",
    "&": "&amp;",
})


def format_diagnostics_text(input_data: dict) -> str:
    """Format diagnostic data as a human-readable TXT report (Chinese)."""
    inp = _parse_input(input_data)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s = _safe_dict(inp.status)
    lp = _safe_dict(inp.log_paths)
    dr = _safe_dict(inp.drawer)

    def _v(key, default="--"):
        """Get a safe, HTML-escaped value from status or drawer."""
        val = s.get(key)
        if val is None or val == "":
            val = dr.get(key, default)
        return _fmt_val(val)

    lines: list[str] = []
    _a = lines.append

    _a("小黄诊断信息导出")
    _a(f"导出时间：{ts}")
    _a(f"来源：{_esc(str(inp.exported_from))}")
    _a(f"项目路径：{_esc(str(lp.get('project_root', '--')))}")
    _a("")

    # ── 一、运行状态 ──
    _a("一、运行状态")
    _a(f"- 整体状态：{_v('overall_message', s.get('overall_status', '--'))}")
    _a(f"- 桌面桥接：{'已连接' if inp.bridge_ready else '未连接'}")
    _a(f"- STT 服务：{'运行中' if s.get('stt_running') else '未检测到'}")
    _a(f"- STT Ready：{_v('stt_ready')}")
    _a(f"- 模型已加载：{_v('stt_model_loaded')}")
    _a(f"- Voice Overlay：{'运行中' if s.get('overlay_running') else '未检测到'}")
    _a(f"- 可唤醒：{_v('can_wake_now')}")
    _a(f"- 最近错误：{_v('last_error', '无')}")
    _a("")

    # ── 二、唤醒与语音 ──
    _a("二、唤醒与语音")
    _a(f"- Wake Engine：{_v('wake_engine')}")
    _a(f"- Wake Device：{_v('wake_device_index')}")
    _a(f"- Wake Cooldown：{_v('wake_cooldown_seconds')}s")
    _a(f"- Wake Sensitivity：{_v('wake_sensitivity')}")
    _a(f"- Wake Fallback：{_v('wake_fallback_enabled')}")
    phrases = s.get("wake_phrases", [])
    _a(f"- Wake Phrases：{', '.join(phrases) if phrases else '--'}")
    _a("")

    # ── 三、模型与回复 ──
    _a("三、模型与回复")
    _a(f"- Assistant：{_v('assistant_display_name')}")
    _a(f"- LLM Provider：{_v('llm_provider')}")
    _a(f"- TTS Enabled：{_v('tts_enabled')}")
    _a("")

    # ── 四、路径 ──
    _a("四、路径")
    _a(f"- 配置文件：{_esc(str(dr.get('config_path') or lp.get('config_path') or '--'))}")
    _a(f"- 日志目录：{_esc(str(dr.get('logs_path') or lp.get('logs_directory') or '--'))}")
    _a("")

    # ── 五、最近操作 ──
    _a("五、最近操作")
    _a(f"- 最近操作：{_v('last_operation', '--')}")
    elapsed = s.get("last_operation_elapsed_seconds")
    _a(f"- 操作耗时：{_fmt_seconds(elapsed)}")
    _a("")

    # ── 六、操作历史 ──
    _a("六、操作历史")
    history = inp.history if inp.history else []
    if history:
        for entry in history[: _MAX_HISTORY_ENTRIES]:
            time_str = entry.get("time", "")
            op = entry.get("op", "")
            ok = entry.get("ok")
            detail = entry.get("detail", "")
            ok_str = "完成" if ok else ("失败" if ok is False else "")
            parts = [time_str, _esc(op)]
            if ok_str:
                parts.append(ok_str)
            if detail:
                parts.append(_esc(detail))
            _a("  ".join(parts))
    else:
        _a("（无操作历史）")
    _a("")

    return "\n".join(lines)


def export_diagnostics_to_file(
    text: str,
    logs_dir: str | Path,
) -> DiagnosticExportResult:
    """Write the diagnostic text to logs/diagnostic_exports/ and return the result."""
    base = Path(logs_dir)
    if not base.is_absolute():
        return DiagnosticExportResult(ok=False, message="logs_dir 必须是绝对路径")

    safe_base = base.resolve()
    out_dir = safe_base / _EXPORT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"xiaohuang_diagnostics_{ts}.txt"
    filepath = out_dir / filename

    resolved = filepath.resolve()
    if not str(resolved).startswith(str(safe_base) + os.sep) and str(resolved) != str(safe_base):
        return DiagnosticExportResult(ok=False, message="导出路径超出安全目录")

    resolved.write_text(text, encoding="utf-8")
    return DiagnosticExportResult(
        ok=True,
        path=str(resolved),
        content=text,
        message="诊断信息已导出",
    )


# ── internal helpers ──

def _parse_input(data: dict) -> DiagnosticExportInput:
    return DiagnosticExportInput(
        exported_from=str(data.get("exported_from", "control_panel_web")),
        bridge_ready=bool(data.get("bridge_ready", False)),
        status=_safe_dict(data.get("status", {})),
        log_paths=_safe_dict(data.get("log_paths", {})),
        drawer=_safe_dict(data.get("drawer", {})),
        history=_sanitize_history(data.get("history", [])),
    )


def _safe_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return _sanitize_dict(value)
    return {}


def _sanitize_dict(d: dict) -> dict:
    return {k: v for k, v in d.items() if k.lower() not in _SENSITIVE_KEYS}


def _sanitize_history(entries: list) -> list[dict]:
    result: list[dict] = []
    for e in entries[: _MAX_HISTORY_ENTRIES]:
        if not isinstance(e, dict):
            continue
        result.append({
            "time": str(e.get("time", "")),
            "op": str(e.get("op", "")),
            "ok": e.get("ok") if "ok" in e else None,
            "detail": str(e.get("detail", "")) if e.get("detail") else "",
        })
    return result


def _esc(value: str) -> str:
    return str(value).translate(_HTML_ESCAPE_TABLE)


def _fmt_val(value: Any) -> str:
    """Format a value for diagnostic output, escaping HTML chars."""
    if value is None or value == "":
        return "--"
    if isinstance(value, bool):
        return _BOOL_YES if value else _BOOL_NO
    if isinstance(value, (int, float)):
        return str(value)
    return _esc(str(value))


def _fmt_bool(value: Any) -> str:
    if value is True:
        return _BOOL_YES
    if value is False:
        return _BOOL_NO
    return "--"


def _fmt_seconds(value: Any) -> str:
    if value is None:
        return "--"
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return str(value)
