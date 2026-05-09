"""Readonly execution for confirmed text tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xiaohuang.launch_control_service import get_project_root
from xiaohuang.text_task_execution_models import TextTaskExecutionResult

ALLOWED_READONLY_TASK_TYPES = {
    "readonly_log_analysis",
    "readonly_status_check",
    "readonly_diagnostic_review",
    "readonly_recent_errors_review",
    "readonly_runtime_events_review",
    "readonly_config_summary",
}

_LOG_EXTENSIONS = {".log", ".txt"}
_MAX_LOG_FILES = 5
_MAX_BYTES_PER_FILE = 100 * 1024
_MAX_DETAIL_LINES = 20
_KEYWORDS = ("error", "traceback", "exception", "warning", "failed")


def execute_confirmed_text_task(
    pending_task: dict[str, Any] | None,
    *,
    project_root: Path | str | None = None,
) -> TextTaskExecutionResult:
    root = Path(project_root) if project_root is not None else get_project_root()
    task = pending_task if isinstance(pending_task, dict) else {}
    task_id = str(task.get("task_id") or "")
    task_type = str(task.get("task_type") or "")
    title = str(task.get("title") or "文本任务")
    risk_level = str(task.get("risk_level") or task.get("risk") or "low").lower()

    if not task:
        return _blocked_result(task_id, task_type, title, "缺少待确认任务。", risk_level=risk_level)
    if task.get("allowed") is False:
        return _blocked_result(task_id, task_type, title, "该任务已被标记为不允许执行。", risk_level=risk_level)
    if risk_level == "high":
        return _blocked_result(task_id, task_type, title, "高风险文本任务不允许执行。", risk_level=risk_level)
    if task_type not in ALLOWED_READONLY_TASK_TYPES:
        return _blocked_result(task_id, task_type, title, "文本任务执行器只允许白名单只读任务。", risk_level=risk_level)

    try:
        if task_type == "readonly_log_analysis":
            return _execute_readonly_log_analysis(task, root)
        if task_type == "readonly_status_check":
            return _execute_readonly_status_check(task, root)
        if task_type == "readonly_diagnostic_review":
            return _execute_readonly_diagnostic_review(task, root)
        if task_type == "readonly_recent_errors_review":
            return _execute_readonly_errors_review(task, root)
        if task_type == "readonly_runtime_events_review":
            return _execute_readonly_events_review(task, root)
        if task_type == "readonly_config_summary":
            return _execute_readonly_config_summary(task, root)
    except Exception as exc:  # Defensive boundary: UI should receive a structured failure.
        return _failed_result(task_id, task_type, title, f"只读任务执行失败: {exc}", risk_level=risk_level)

    return _blocked_result(task_id, task_type, title, "未知只读任务类型。", risk_level=risk_level)


def _execute_readonly_log_analysis(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    analysis = _analyze_recent_logs(project_root)
    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_log_analysis",
        status="completed",
        title=str(task.get("title") or "分析最近日志"),
        summary=analysis["summary"],
        details=analysis["details"],
        risk_level=_safe_risk(task),
        read_files=tuple(analysis["read_files"]),
    )


def _execute_readonly_status_check(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    root = project_root.resolve()
    logs_dir = root / "logs"
    log_count = len(_recent_log_files(logs_dir)) if logs_dir.is_dir() else 0
    checks = [
        f"项目根目录：{'存在' if root.exists() else '未发现'}",
        f"src 目录：{'存在' if (root / 'src').is_dir() else '未发现'}",
        f"scripts 目录：{'存在' if (root / 'scripts').is_dir() else '未发现'}",
        f"frontend 目录：{'存在' if (root / 'frontend').is_dir() else '未发现'}",
        f"logs 目录：{'存在' if logs_dir.is_dir() else '未发现'}",
        f"最近日志文件数量：{log_count}",
        f"control_panel_web.py：{'可定位' if (root / 'scripts' / 'control_panel_web.py').is_file() else '未发现'}",
    ]
    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_status_check",
        status="completed",
        title=str(task.get("title") or "检查基础状态"),
        summary="已完成只读基础状态检查。",
        details="\n".join(checks),
        risk_level=_safe_risk(task),
        read_files=(),
    )


def _execute_readonly_diagnostic_review(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    analysis = _analyze_recent_logs(project_root)
    diagnostic_note = "未发现已有诊断文件；已基于最近日志做只读检查。"
    suggestions = [
        diagnostic_note,
        "建议优先查看 error/traceback/exception 命中行。",
        "如 warning 数量较多，建议结合最近启动时间逐条排查。",
    ]
    details_parts = suggestions
    if analysis["details"]:
        details_parts.extend(["", "最近日志命中：", analysis["details"]])
    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_diagnostic_review",
        status="completed",
        title=str(task.get("title") or "复核诊断信息"),
        summary=analysis["summary"] if analysis["read_files"] else diagnostic_note,
        details="\n".join(details_parts),
        risk_level=_safe_risk(task),
        read_files=tuple(analysis["read_files"]),
    )


def _analyze_recent_logs(project_root: Path) -> dict[str, Any]:
    logs_dir = project_root.resolve() / "logs"
    if not logs_dir.is_dir():
        return {
            "summary": "未发现 logs 目录；没有可读取的最近日志。",
            "details": "",
            "read_files": [],
        }

    files = _recent_log_files(logs_dir)[:_MAX_LOG_FILES]
    if not files:
        return {
            "summary": "logs 目录存在，但未发现 .log 或 .txt 日志文件。",
            "details": "",
            "read_files": [],
        }

    counts = {keyword: 0 for keyword in _KEYWORDS}
    detail_lines: list[str] = []
    read_files: list[str] = []
    failures: list[str] = []

    for path in files:
        rel = _relative_log_path(path, project_root)
        try:
            content = _read_text_prefix(path)
            read_files.append(rel)
        except OSError as exc:
            failures.append(f"{rel}: 读取失败: {exc}")
            continue
        for line_no, line in enumerate(content.splitlines(), start=1):
            lower = line.lower()
            matched = [keyword for keyword in _KEYWORDS if keyword in lower]
            if not matched:
                continue
            for keyword in matched:
                counts[keyword] += 1
            if len(detail_lines) < _MAX_DETAIL_LINES:
                detail_lines.append(f"{rel}:{line_no}: {line.strip()[:220]}")

    summary = (
        f"已读取最近 {len(read_files)} 个日志文件，发现 "
        f"error {counts['error']} 条、traceback {counts['traceback']} 条、"
        f"exception {counts['exception']} 条、warning {counts['warning']} 条、"
        f"failed {counts['failed']} 条。"
    )
    details: list[str] = []
    if detail_lines:
        details.extend(detail_lines)
    else:
        details.append("未发现关键错误命中行。")
    if failures:
        details.extend(["", "读取失败：", *failures])

    return {
        "summary": summary,
        "details": "\n".join(details),
        "read_files": read_files,
    }


def _recent_log_files(logs_dir: Path) -> list[Path]:
    if not logs_dir.is_dir():
        return []
    candidates: list[Path] = []
    for path in logs_dir.iterdir():
        try:
            if _is_safe_log_file(path, logs_dir):
                candidates.append(path)
        except OSError:
            continue
    return sorted(candidates, key=_safe_mtime, reverse=True)


def _is_safe_log_file(path: Path, logs_dir: Path) -> bool:
    if path.is_symlink():
        return False
    if not path.is_file():
        return False
    if path.suffix.lower() not in _LOG_EXTENSIONS:
        return False
    return _is_within_directory(path, logs_dir)


def _is_within_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except (OSError, ValueError):
        return False


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read_text_prefix(path: Path) -> str:
    data = path.read_bytes()[:_MAX_BYTES_PER_FILE]
    return data.decode("utf-8", errors="replace")


def _relative_log_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _execute_readonly_errors_review(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    analysis = _analyze_recent_logs(project_root)
    if not analysis["read_files"]:
        return TextTaskExecutionResult(
            ok=True,
            task_id=str(task.get("task_id") or ""),
            task_type="readonly_recent_errors_review",
            status="completed",
            title=str(task.get("title") or "查看最近错误"),
            summary="未发现可读取的日志文件，或日志目录不存在。",
            details="logs 目录不存在或未发现 .log/.txt 文件。",
            risk_level=_safe_risk(task),
            read_files=(),
        )
    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_recent_errors_review",
        status="completed",
        title=str(task.get("title") or "查看最近错误"),
        summary=analysis["summary"],
        details=analysis["details"],
        risk_level=_safe_risk(task),
        read_files=tuple(analysis["read_files"]),
    )


def _execute_readonly_events_review(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    try:
        from xiaohuang.capabilities.runtime_events.service import get_recent_events
    except Exception:
        return TextTaskExecutionResult(
            ok=True,
            task_id=str(task.get("task_id") or ""),
            task_type="readonly_runtime_events_review",
            status="completed",
            title=str(task.get("title") or "总结最近运行事件"),
            summary="无法读取运行事件。",
            details="运行事件模块当前不可用。",
            risk_level=_safe_risk(task),
            read_files=(),
        )

    events = get_recent_events(100)
    if not events:
        return TextTaskExecutionResult(
            ok=True,
            task_id=str(task.get("task_id") or ""),
            task_type="readonly_runtime_events_review",
            status="completed",
            title=str(task.get("title") or "总结最近运行事件"),
            summary="当前没有可用运行事件。",
            details="runtime events 是内存态，程序重启后可能为空。可以在小黄运行一段时间后再查看。",
            risk_level=_safe_risk(task),
            read_files=(),
        )

    source_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    error_count = 0
    warning_count = 0
    for e in events:
        src = str(e.get("source") or "")
        et = str(e.get("event_type") or "")
        source_counts[src] = source_counts.get(src, 0) + 1
        type_counts[et] = type_counts.get(et, 0) + 1
        lv = str(e.get("level") or "info")
        if lv == "error":
            error_count += 1
        elif lv == "warning":
            warning_count += 1

    detail_lines: list[str] = [
        f"共 {len(events)} 条事件",
        f"error: {error_count} 条, warning: {warning_count} 条",
        "",
        "来源分布：",
    ]
    for src in sorted(source_counts, key=source_counts.get, reverse=True):
        detail_lines.append(f"  {src}: {source_counts[src]} 条")
    detail_lines.append("")
    detail_lines.append("类型分布：")
    for et in sorted(type_counts, key=type_counts.get, reverse=True):
        detail_lines.append(f"  {et}: {type_counts[et]} 条")
    detail_lines.append("")
    detail_lines.append("最近事件：")
    for e in events[-10:]:
        ts = str(e.get("timestamp") or "")[-8:]
        src = str(e.get("source") or "")
        et = str(e.get("event_type") or "")
        msg = str(e.get("message") or "")[:80]
        lv = str(e.get("level") or "info")
        marker = " [ERROR]" if lv == "error" else " [WARN]" if lv == "warning" else ""
        detail_lines.append(f"  {ts} {src}/{et}{marker}: {msg}")

    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_runtime_events_review",
        status="completed",
        title=str(task.get("title") or "总结最近运行事件"),
        summary=(
            f"最近运行事件摘要：共 {len(events)} 条，"
            f"error {error_count} 条、warning {warning_count} 条"
        ),
        details="\n".join(detail_lines),
        risk_level=_safe_risk(task),
        read_files=(),
    )


_CONFIG_REDACT_KEYS = {"api_key", "secret", "password", "token", "authorization"}


def _execute_readonly_config_summary(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    from xiaohuang.app_config_service import load_config

    cfg = load_config()
    awake = cfg.wake
    stt = cfg.stt
    llm = cfg.llm
    tts = cfg.tts
    conv = cfg.conversation
    overlay = cfg.overlay
    runtime = cfg.runtime
    assistant = cfg.assistant

    detail_lines = [
        f"助手名称: {assistant.display_name}",
        f"唤醒引擎: {awake.engine}",
        f"唤醒词数量: {len(awake.phrases)}",
        f"唤醒回退: {'开启' if awake.fallback_enabled else '关闭'}",
        f"唤醒冷却: {awake.cooldown_seconds}s",
        f"唤醒灵敏度: {awake.sensitivity}",
        "",
        f"STT 引擎: {stt.engine}",
        f"STT 模型: {stt.model_name}",
        f"STT 设备: {stt.device}",
        "",
        f"LLM 启用: {'是' if llm.enabled else '否'}",
        f"LLM 提供方: {llm.provider}",
        f"LLM 模型: {llm.model}",
        f"LLM Key 环境变量: {llm.api_key_env}",
        f"LLM 超时: {llm.timeout_seconds}s",
        "",
        f"TTS 启用: {'是' if tts.enabled else '否'}",
        f"TTS 语音: {tts.voice}",
        "",
        f"会话启用: {'是' if conv.enabled else '否'}",
        f"会话最大轮次: {conv.max_turns}",
        f"跟进超时: {conv.followup_timeout}s",
        "",
        f"悬浮窗常驻隐藏: {'是' if overlay.resident_hidden else '否'}",
        f"调试模式: {'是' if runtime.debug else '否'}",
    ]

    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_config_summary",
        status="completed",
        title=str(task.get("title") or "查看当前配置摘要"),
        summary=f"当前配置摘要：LLM {'开启' if llm.enabled else '关闭'} / TTS {'开启' if tts.enabled else '关闭'} / 唤醒引擎 {awake.engine}",
        details="\n".join(detail_lines),
        risk_level=_safe_risk(task),
        read_files=(),
    )


def _blocked_result(
    task_id: str,
    task_type: str,
    title: str,
    details: str,
    *,
    risk_level: str = "low",
) -> TextTaskExecutionResult:
    return TextTaskExecutionResult(
        ok=False,
        task_id=task_id,
        task_type=task_type,
        status="blocked",
        title=title or "受限文本任务",
        summary="该任务不允许执行。",
        details=details,
        risk_level=risk_level if risk_level in {"low", "medium", "high"} else "medium",
        read_files=(),
        error="blocked_task",
    )


def _failed_result(
    task_id: str,
    task_type: str,
    title: str,
    details: str,
    *,
    risk_level: str = "low",
) -> TextTaskExecutionResult:
    return TextTaskExecutionResult(
        ok=False,
        task_id=task_id,
        task_type=task_type,
        status="failed",
        title=title or "文本任务执行失败",
        summary="只读任务执行失败。",
        details=details,
        risk_level=risk_level if risk_level in {"low", "medium", "high"} else "medium",
        read_files=(),
        error="execution_failed",
    )


def _safe_risk(task: dict[str, Any]) -> str:
    risk = str(task.get("risk_level") or task.get("risk") or "low").lower()
    return risk if risk in {"low", "medium", "high"} else "medium"
