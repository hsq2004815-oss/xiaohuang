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
