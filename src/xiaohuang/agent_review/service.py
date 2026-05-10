from __future__ import annotations

from dataclasses import replace

from xiaohuang.agent_review.models import AgentCompletionReview
from xiaohuang.agent_review.report_parser import parse_completion_report
from xiaohuang.agent_review.review_builder import build_review_details
from xiaohuang.agent_review.risk_rules import evaluate_completion_report


def review_agent_completion_report(text: str) -> AgentCompletionReview:
    value = str(text or "").strip()
    if not value:
        return AgentCompletionReview(
            ok=False,
            verdict="insufficient",
            confidence="low",
            title="Agent 完成报告审查",
            summary="信息不足，暂不建议直接保留",
            task_title="",
            commit_hash="",
            changed_files=[],
            verification_summary="未提供明确验证结果",
            safety_summary="未提供安全边界声明",
            risk_points=["没有提供完成报告文本。"],
            next_steps=["粘贴 Agent 完成报告后再进行审查。"],
            safe_details_excerpt="【Agent 完成报告审查】\n\n验收结论：信息不足，暂不建议直接保留\n风险点：没有提供完成报告文本。",
            tags=["agent", "review", "insufficient"],
            error_message="empty_report",
        )
    try:
        report = parse_completion_report(value)
        review = evaluate_completion_report(report)
        details = build_review_details(review, report)
        return replace(review, safe_details_excerpt=details)
    except Exception as exc:
        return AgentCompletionReview(
            ok=False,
            verdict="insufficient",
            confidence="low",
            title="Agent 完成报告审查",
            summary="信息不足，暂不建议直接保留",
            task_title="",
            commit_hash="",
            changed_files=[],
            verification_summary="解析失败",
            safety_summary="解析失败",
            risk_points=["完成报告解析失败。"],
            next_steps=["请补充更结构化的完成报告后重试。"],
            safe_details_excerpt=f"【Agent 完成报告审查】\n\n验收结论：信息不足，暂不建议直接保留\n错误：{exc}",
            tags=["agent", "review", "insufficient"],
            error_message=str(exc),
        )
