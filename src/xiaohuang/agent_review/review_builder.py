from __future__ import annotations

import re

from xiaohuang.agent_review.models import AgentCompletionReport, AgentCompletionReview

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|apikey|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(bearer\s+)?([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+([^\s,;]+)"),
)


def build_review_details(review: AgentCompletionReview, report: AgentCompletionReport) -> str:
    lines: list[str] = [
        "【Agent 完成报告审查】",
        "",
        f"验收结论：{review.summary}",
        f"置信度：{review.confidence}",
        f"verdict：{review.verdict}",
        f"任务：{review.task_title or '未识别'}",
        f"commit：{review.commit_hash or '未提供'}",
    ]
    if report.commit_message:
        lines.append(f"提交信息：{_safe_line(report.commit_message)}")

    lines.extend(["", "一、改动范围"])
    lines.extend(_bullet_lines(review.changed_files, empty="未列出明确改动文件"))

    lines.extend(["", "二、验证结果"])
    lines.append(f"- {_safe_line(review.verification_summary)}")
    for claim in report.test_claims[:4]:
        lines.append(f"- {_safe_line(claim)}")

    lines.extend(["", "三、安全边界"])
    lines.append(f"- {_safe_line(review.safety_summary)}")
    for claim in report.safety_claims[:3]:
        lines.append(f"- {_safe_line(claim)}")

    lines.extend(["", "四、风险点"])
    lines.extend(_bullet_lines(review.risk_points, empty="未发现明显风险点"))

    lines.extend(["", "五、下一步建议"])
    lines.extend(_bullet_lines(review.next_steps, empty="继续按原计划推进"))

    return _redact_sensitive_text("\n".join(lines))


def _bullet_lines(items: list[str], *, empty: str) -> list[str]:
    values = [_safe_line(item) for item in items if str(item or "").strip()]
    if not values:
        return [f"- {empty}"]
    return [f"- {value}" for value in values[:8]]


def _safe_line(text: str, limit: int = 140) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[:limit].rstrip() + "..."
    return value


def _redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    value = _SENSITIVE_VALUE_PATTERNS[0].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_VALUE_PATTERNS[1].sub(r"\g<1>=<redacted>", value)
    value = _SENSITIVE_VALUE_PATTERNS[2].sub(r"Bearer <redacted>", value)
    return value
