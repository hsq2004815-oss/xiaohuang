"""Readonly execution for confirmed text tasks."""

from __future__ import annotations

import re
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
    "readonly_health_report",
}

ALLOWED_AGENT_HANDOFF_TASK_TYPES = {
    "agent_handoff_draft",
}

ALLOWED_AGENT_REVIEW_TASK_TYPES = {
    "agent_completion_review",
}

ALLOWED_TEXT_TASK_TYPES = (
    ALLOWED_READONLY_TASK_TYPES
    | ALLOWED_AGENT_HANDOFF_TASK_TYPES
    | ALLOWED_AGENT_REVIEW_TASK_TYPES
)

_LOG_EXTENSIONS = {".log", ".txt"}
_MAX_LOG_FILES = 5
_MAX_BYTES_PER_FILE = 100 * 1024
_MAX_DETAIL_LINES = 20
_KEYWORDS = ("error", "traceback", "exception", "warning", "failed")


def execute_confirmed_text_task(
    pending_task: dict[str, Any] | None,
    *,
    project_root: Path | str | None = None,
    config_path: Path | str | None = None,
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
    if task_type not in ALLOWED_TEXT_TASK_TYPES:
        return _blocked_result(task_id, task_type, title, "文本任务执行器只允许白名单受控任务。", risk_level=risk_level)

    try:
        if task_type == "agent_completion_review":
            return _execute_agent_completion_review(task)
        if task_type == "agent_handoff_draft":
            return _execute_agent_handoff_draft(task, root)
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
        if task_type == "readonly_health_report":
            return _execute_readonly_health_report(task, root, config_path=config_path)

        if task_type == "readonly_config_summary":
            return _execute_readonly_config_summary(task, root, config_path=config_path)
    except Exception as exc:  # Defensive boundary: UI should receive a structured failure.
        return _failed_result(task_id, task_type, title, f"只读任务执行失败: {exc}", risk_level=risk_level)

    return _blocked_result(task_id, task_type, title, "未知只读任务类型。", risk_level=risk_level)


def _execute_agent_handoff_draft(task: dict[str, Any], project_root: Path) -> TextTaskExecutionResult:
    from xiaohuang.agent_handoff.models import AgentHandoffRequest
    from xiaohuang.agent_handoff.service import create_agent_handoff

    user_request = str(task.get("original_text") or task.get("summary") or "").strip()
    result = create_agent_handoff(
        AgentHandoffRequest(user_request=user_request, source="text"),
        project_root=project_root,
    )
    status = "completed" if result.ok else "failed"
    return TextTaskExecutionResult(
        ok=result.ok,
        task_id=str(task.get("task_id") or ""),
        task_type="agent_handoff_draft",
        status=status,
        title=result.title or str(task.get("title") or "生成 Agent 交接提示词"),
        summary=result.summary,
        details=_format_agent_handoff_details(result),
        risk_level=_safe_risk(task),
        read_files=(),
        error="" if result.ok else (result.error_message or "agent_handoff_failed"),
    )


def _format_agent_handoff_details(result: Any) -> str:
    lines = [
        f"目标 Agent：{result.target_agent}",
        f"相关领域：{', '.join(result.domains) if result.domains else '未指定'}",
        f"数据库：{result.database_status}",
    ]
    if result.handoff_path:
        lines.append(f"文件：{result.handoff_path}")
    if result.handoff_preview:
        lines.extend(["", "预览：", result.handoff_preview])
    if result.error_message and not result.ok:
        lines.extend(["", f"错误：{result.error_message}"])
    return "\n".join(lines)


def _execute_agent_completion_review(task: dict[str, Any]) -> TextTaskExecutionResult:
    from xiaohuang.agent_review.service import review_agent_completion_report

    report_text = str(task.get("original_text") or task.get("summary") or "").strip()
    review = review_agent_completion_report(report_text)
    status = "completed" if review.ok else "failed"
    return TextTaskExecutionResult(
        ok=review.ok,
        task_id=str(task.get("task_id") or ""),
        task_type="agent_completion_review",
        status=status,
        title=review.title or str(task.get("title") or "审查 Agent 完成报告"),
        summary=review.summary,
        details=review.safe_details_excerpt,
        risk_level=_safe_risk(task),
        read_files=(),
        error="" if review.ok else (review.error_message or "agent_completion_review_failed"),
    )


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
                safe_line = _redact_sensitive_text(line.strip())[:220]
                detail_lines.append(f"{rel}:{line_no}: {safe_line}")

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


def _execute_readonly_config_summary(
    task: dict[str, Any],
    project_root: Path,
    *,
    config_path: Path | str | None = None,
) -> TextTaskExecutionResult:
    from xiaohuang.app_config_service import load_config

    cfg = load_config(config_path)
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


def _check_basic_project_paths(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    paths = [
        ("project_root", root),
        ("logs", root / "logs"),
        ("scripts/control_panel_web.py", root / "scripts" / "control_panel_web.py"),
        ("scripts/voice_overlay.py", root / "scripts" / "voice_overlay.py"),
        ("src/xiaohuang", root / "src" / "xiaohuang"),
        ("frontend/control_panel", root / "frontend" / "control_panel"),
    ]
    checked: list[str] = []
    missing: list[str] = []
    for label, path in paths:
        checked.append(label)
        if not path.exists():
            missing.append(label)
    return {"ok": len(missing) == 0, "checked": checked, "missing": missing}


def _compact_health_text(text: str, limit: int = 96) -> str:
    s = str(text or "").replace("\n", " ").replace("\r", " ").strip()
    s = " ".join(s.split())
    idx = s.find("Traceback")
    if idx >= 0:
        s = s[:idx].strip() or "出现异常"
    s = _redact_sensitive_text(s)
    return s[:limit].rstrip() + "…" if len(s) > limit else s


def _summarize_log_signal(line: str) -> str | None:
    s = str(line or "").strip()
    if not s:
        return None
    lower = s.lower()
    if any(kw in lower for kw in ("parsererror", "categoryinfo",
                                     "fullyqualifiederrorid", "ampersandnotallowed",
                                     "parentcontainserrorrecordexception")):
        if "tray_app.log" in lower:
            return "tray_app.log 中发现 PowerShell 解析错误，建议检查托盘启动脚本或命令引用格式。"
        return "日志中发现 PowerShell 解析错误，可能与命令引用或特殊字符有关，建议检查对应脚本。"
    if "get_status" in lower or "获取状态失败" in s:
        return "控制面板状态读取曾失败，建议观察控制面板状态刷新是否正常。"
    if any(kw in lower for kw in ("start_xiaohuang", "restart_xiaohuang",
                                     "启动失败", "重启失败")):
        return "启动/重启流程曾出现失败记录，建议确认当前进程状态和日志。"
    compacted = _compact_health_text(s, 100)
    if compacted:
        return "历史日志中发现错误记录：" + compacted
    return None


def _execute_readonly_health_report(
    task: dict[str, Any],
    project_root: Path,
    *,
    config_path: Path | str | None = None,
) -> TextTaskExecutionResult:
    title = str(task.get("title") or "小黄健康检查报告")
    health_errors: list[str] = []
    health_warnings: list[str] = []
    health_unknowns: list[str] = []
    detail_parts: list[str] = ["【小黄健康检查报告】", ""]

    # ── 1. Path check ──
    paths = _check_basic_project_paths(project_root)
    ok_count = len(paths["checked"]) - len(paths["missing"])
    total_count = len(paths["checked"])
    if paths["missing"]:
        health_errors.append(f"缺失 {len(paths['missing'])} 个关键路径")
        detail_parts.append(f"一、基础状态 — {ok_count}/{total_count} 正常")
        for label in paths["checked"]:
            present = "✓" if label not in paths["missing"] else "✗ 缺失"
            detail_parts.append(f"  - {label}: {present}")
    else:
        detail_parts.append(f"一、基础状态 — {ok_count}/{total_count} 正常")

    # ── 2. Config summary ──
    detail_parts.append("")
    detail_parts.append("二、配置状态")
    config_ok = True
    cfg_warnings: list[str] = []
    try:
        from xiaohuang.app_config_service import load_config
        cfg = load_config(config_path)
        detail_parts.append(f"  - 助手名称: {cfg.assistant.display_name}")
        detail_parts.append(f"  - 唤醒引擎: {cfg.wake.engine}")
        detail_parts.append(f"  - LLM: {'已启用' if cfg.llm.enabled else '未启用'} ({cfg.llm.model})")
        detail_parts.append(f"  - TTS: {'已启用' if cfg.tts.enabled else '未启用'} ({cfg.tts.voice})")
        if not cfg.llm.enabled:
            cfg_warnings.append("LLM 未启用")
        if not cfg.tts.enabled:
            cfg_warnings.append("TTS 未启用")
        if not cfg.wake.engine:
            cfg_warnings.append("唤醒引擎未设置")
        if not cfg.tts.voice:
            cfg_warnings.append("TTS voice 为空")
        if not cfg.assistant.display_name.strip():
            cfg_warnings.append("助手名称为空")
        if cfg_warnings:
            detail_parts.append(f"  - 配置提示: {'; '.join(cfg_warnings)}")
            health_warnings.extend(cfg_warnings)
        else:
            detail_parts.append("  - 配置提示: 未发现明显配置缺口")
    except Exception:
        detail_parts.append("  - 配置读取失败")
        health_warnings.append("配置读取失败")
        config_ok = False

    # ── 3. Runtime events summary ──
    detail_parts.append("")
    detail_parts.append("三、运行事件")
    events_ok = True
    error_count = 0
    warning_count = 0
    total_events = 0
    last_error_text = ""
    last_warning_text = ""
    try:
        from xiaohuang.capabilities.runtime_events.service import get_recent_events
        events = get_recent_events(50)
        total_events = len(events)
        sources: dict[str, int] = {}
        for e in events:
            lv = str(e.get("level") or "info")
            if lv == "error":
                error_count += 1
                if not last_error_text:
                    last_error_text = _compact_health_text(str(e.get("message") or ""))
            elif lv == "warning":
                warning_count += 1
                if not last_warning_text:
                    last_warning_text = _compact_health_text(str(e.get("message") or ""))
            src = str(e.get("source") or "")
            sources[src] = sources.get(src, 0) + 1
        detail_parts.append(f"  - 最近事件: {total_events} 条")
        detail_parts.append(f"  - 当前 error/warning: {error_count}/{warning_count}")
        if sources:
            top_src = sorted(sources, key=sources.get, reverse=True)[:3]
            detail_parts.append(f"  - 活跃模块: {', '.join(top_src)}")
        if last_error_text:
            detail_parts.append(f"  - 当前 error 提示: {last_error_text}")
        if last_warning_text:
            detail_parts.append(f"  - 当前 warning 提示: {last_warning_text}")
        if error_count + warning_count == 0:
            detail_parts.append("  - 当前未发现 error/warning 事件")
    except Exception:
        detail_parts.append("  - 运行事件读取失败")
        health_warnings.append("运行事件读取失败")
        events_ok = False

    # ── 4. Recent errors summary ──
    detail_parts.append("")
    detail_parts.append("四、最近错误（历史日志）")
    log_error = 0
    log_warning = 0
    log_files = 0
    log_signals: list[str] = []
    seen_signals: set[str] = set()
    try:
        analysis = _analyze_recent_logs(project_root)
        log_files = len(analysis["read_files"])
        import re
        analysis_summary = analysis.get("summary", "")
        err_m = re.search(r"error\s+(\d+)", analysis_summary.lower())
        warn_m = re.search(r"warning\s+(\d+)", analysis_summary.lower())
        log_error = int(err_m.group(1)) if err_m else 0
        log_warning = int(warn_m.group(1)) if warn_m else 0
        detail_parts.append(f"  - 读取日志文件: {log_files} 个")
        detail_parts.append(f"  - 历史 ERROR/WARNING: {log_error}/{log_warning}")
        if analysis["details"] and "未发现关键错误" not in analysis["details"]:
            for line in analysis["details"].split("\n"):
                stripped = line.strip()
                if not stripped or stripped.startswith("未发现") or stripped.startswith("读取失败"):
                    continue
                signal = _summarize_log_signal(stripped)
                if signal and signal not in seen_signals:
                    seen_signals.add(signal)
                    log_signals.append(signal)
            for signal in log_signals[:2]:
                detail_parts.append(f"  - 代表性问题：{signal}")
        if log_error > 0:
            detail_parts.append("  - 提醒：历史日志错误不一定代表功能正在失败，可结合当前运行事件判断。")
    except Exception:
        detail_parts.append("  - 日志分析不可用")
        health_unknowns.append("日志分析不可用")

    # ── 5. Overall status (built from health tracking) ──
    if error_count > 0:
        health_errors.append(f"当前运行事件发现 {error_count} 条 error")
    if not paths["ok"]:
        health_errors.append("关键路径缺失")
    if log_error > 0:
        health_warnings.append(f"历史日志中发现 {log_error} 条 ERROR 记录")
    if warning_count > 0 or log_warning > 0:
        health_warnings.append(f"发现 {warning_count + log_warning} 条 warning 记录")

    if health_errors:
        overall = "有错误"
    elif health_warnings:
        overall = "有警告"
    elif health_unknowns:
        overall = "信息不足"
    elif total_events == 0 and log_files == 0:
        overall = "信息不足"
    else:
        overall = "正常"

    # ── Overall status and summary at top ──
    detail_parts.insert(1, f"总体状态: {overall}")
    detail_parts.insert(2, "")

    if health_errors:
        summary = f"总体状态：有错误。{'; '.join(health_errors[:2])}，请优先排查。"
    elif health_warnings:
        summary = "总体状态：有警告。"
        if log_error > 0:
            summary += f" 历史日志中发现 {log_error} 条 ERROR 记录，"
        else:
            summary += f" 发现 {warning_count + log_warning} 条 warning 记录，"
        summary += "建议排查来源。"
    elif health_unknowns:
        summary = "总体状态：信息不足。部分模块无法读取，建议打开控制面板查看更多状态。"
    else:
        summary = "总体状态：正常。基础路径、配置、运行事件和最近错误均未发现明显异常。"

    # ── 6. Suggestions ──
    detail_parts.append("")
    detail_parts.append("六、建议")
    if health_errors:
        if not paths["ok"]:
            detail_parts.append("  - 核心路径缺失，请检查项目安装是否完整")
        if error_count > 0:
            detail_parts.append("  - 当前运行事件中存在 error，建议优先排查最近错误")
        detail_parts.append("  - 优先处理 control_panel / voice_overlay 相关错误")
    elif health_warnings:
        if cfg_warnings:
            detail_parts.append("  - 存在配置缺口，建议检查设置页面补全")
        if log_error > 0:
            detail_parts.append("  - 历史日志中存在错误记录，建议排查是否仍会复现")
        if warning_count > 0 or log_warning > 0:
            detail_parts.append("  - 存在 warning，暂时可继续使用，建议观察来源")
        detail_parts.append("  - 如语音无响应，检查唤醒/STT/TTS 配置")
    elif health_unknowns:
        detail_parts.append("  - 当前信息不足以判断完整状态")
        detail_parts.append("  - 建议打开控制面板 Diagnostics 查看更多详情")
    else:
        detail_parts.append("  - 当前没有发现严重问题")
        detail_parts.append("  - 可以继续进行下一步工作")

    return TextTaskExecutionResult(
        ok=True,
        task_id=str(task.get("task_id") or ""),
        task_type="readonly_health_report",
        status="completed",
        title=title,
        summary=summary,
        details="\n".join(detail_parts),
        risk_level=_safe_risk(task),
        read_files=(),
    )


_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|apikey|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(bearer\s+)?([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+([^\s,;]+)"),
)


def _redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    value = _SENSITIVE_VALUE_PATTERNS[0].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_VALUE_PATTERNS[1].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_VALUE_PATTERNS[2].sub(r"Bearer <redacted>", value)
    return value


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
