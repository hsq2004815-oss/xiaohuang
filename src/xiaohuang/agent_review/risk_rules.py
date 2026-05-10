from __future__ import annotations

import re

from xiaohuang.agent_review.models import AgentCompletionReport, AgentCompletionReview

_VERDICT_SUMMARY = {
    "keep": "建议保留",
    "needs_review": "建议保留，但需要补充复查",
    "reject": "不建议保留，需要修复或回退",
    "insufficient": "信息不足，暂不建议直接保留",
}


def evaluate_completion_report(report: AgentCompletionReport) -> AgentCompletionReview:
    text = report.raw_text or ""
    risk_points: list[str] = []
    next_steps: list[str] = []
    positive = _positive_verification_signals(report.test_claims)
    negative = _negative_signals(text)
    dangerous = _dangerous_signals(report)

    if dangerous:
        risk_points.extend(dangerous)
    if negative:
        risk_points.extend(negative)

    if len(text.strip()) < 40:
        risk_points.append("报告内容过短，无法判断执行范围和验证结果。")
    if not report.commit_hash:
        risk_points.append("报告没有提供 commit hash。")
    if not report.changed_files:
        risk_points.append("报告没有列出明确的改动文件。")
    if not report.test_claims and not positive:
        risk_points.append("报告没有提供明确的验证结果。")

    missing_core = _missing_core_verifications(positive)
    for item in missing_core:
        risk_points.append(item)

    manual_risks = _manual_acceptance_risks(report)
    risk_points.extend(manual_risks)

    scope_risks = _scope_risks(report)
    risk_points.extend(scope_risks)

    verdict = _choose_verdict(
        report=report,
        dangerous=bool(dangerous),
        negative=bool(negative),
        positive=positive,
        risk_points=risk_points,
    )
    confidence = _confidence_for(verdict, positive, risk_points)
    next_steps = _next_steps(verdict, risk_points, missing_core, manual_risks)

    return AgentCompletionReview(
        ok=True,
        verdict=verdict,
        confidence=confidence,
        title="Agent 完成报告审查",
        summary=_VERDICT_SUMMARY[verdict],
        task_title=report.task_title,
        commit_hash=report.commit_hash,
        changed_files=list(report.changed_files),
        verification_summary=_format_verification_summary(positive, report.test_claims),
        safety_summary=_format_safety_summary(report, dangerous),
        risk_points=_dedupe(risk_points),
        next_steps=_dedupe(next_steps),
        safe_details_excerpt="",
        tags=["agent", "review", verdict],
    )


def _choose_verdict(
    *,
    report: AgentCompletionReport,
    dangerous: bool,
    negative: bool,
    positive: set[str],
    risk_points: list[str],
) -> str:
    if dangerous or negative:
        return "reject"
    if (
        not report.commit_hash
        or not report.changed_files
        or not positive
        or len((report.raw_text or "").strip()) < 40
    ):
        return "insufficient"
    if risk_points:
        return "needs_review"
    return "keep"


def _confidence_for(verdict: str, positive: set[str], risk_points: list[str]) -> str:
    if verdict == "reject":
        return "high"
    if verdict == "insufficient":
        return "low"
    if verdict == "keep" and {"compileall", "unittest", "diff_check"}.issubset(positive):
        return "high"
    if verdict == "needs_review" and len(risk_points) <= 3:
        return "medium"
    return "medium"


def _positive_verification_signals(claims: list[str]) -> set[str]:
    text = "\n".join(claims).lower()
    signals: set[str] = set()
    if "compileall" in text and _has_pass_signal(text):
        signals.add("compileall")
    if ("unittest" in text or "tests ok" in text or " test" in text) and _has_pass_signal(text):
        signals.add("unittest")
    if "diff --check" in text and ("通过" in text or "ok" in text or "exit 0" in text):
        signals.add("diff_check")
    if "--help" in text and ("exit 0" in text or "ok" in text or "通过" in text):
        signals.add("help")
    if "git status" in text and ("干净" in text or "clean" in text):
        signals.add("git_status_clean")
    return signals


def _has_pass_signal(text: str) -> bool:
    return bool(re.search(r"\b(exit\s*0|ok|passed|pass)\b", text)) or "通过" in text or "干净" in text


def _negative_signals(text: str) -> list[str]:
    risks: list[str] = []
    lines = str(text or "").splitlines()
    for line in lines:
        lower = line.lower()
        compact = "".join(lower.split())
        if re.search(r"\bexit\s*1\b", lower) or "未通过" in line or "测试失败" in line:
            risks.append("报告中出现验证失败信号。")
        if "failed" in lower and not re.search(r"failed\s*0\b", lower):
            risks.append("报告中出现 failed 信号。")
        if "error" in lower and not re.search(r"error\s*0\b", lower) and "0 error" not in lower:
            if any(token in lower for token in ("test", "unittest", "compile", "verify", "验证")):
                risks.append("报告中出现 error 验证信号。")
        if "gitstatus不干净" in compact or "dirty" in lower:
            risks.append("报告声明 git status 不干净。")
    return _dedupe(risks)


def _dangerous_signals(report: AgentCompletionReport) -> list[str]:
    risks: list[str] = []
    lines = (report.raw_text or "").splitlines()
    for line in lines:
        lower = line.lower()
        compact = "".join(lower.split())
        if any(token in lower for token in ("rm -rf", "format", "del /s", "修改 path", "install dependency", "安装依赖")):
            risks.append("报告提到危险命令、PATH 修改或依赖安装。")
        if ("e:\\database" in lower or "e:/database" in lower) and not _is_negative_claim(compact):
            risks.append("报告提到修改或访问 E:\\DataBase，超出本次安全边界。")
        if any(token in lower for token in ("powershell", "cmd", "打开终端", "terminal")) and not _is_negative_claim(compact):
            risks.append("报告提到执行 shell/终端操作。")
        if any(token in compact for token in ("启动agent", "启动claude", "启动codex", "launchagent")) and not _is_negative_claim(compact):
            risks.append("报告提到启动外部 Agent。")
    for path in report.changed_files:
        normalized = path.replace("\\", "/").lower()
        if normalized.startswith(("logs/", "data/")) or normalized in {".env", "secrets.ps1"}:
            risks.append("改动范围包含 data/logs/secrets 类路径，建议拒绝并复查。")
        if normalized.startswith("runtime/") and not normalized.startswith("runtime/agent_handoffs/"):
            risks.append("改动范围包含 runtime 输出路径，建议拒绝并复查。")
    return _dedupe(risks)


def _is_negative_claim(compact_line: str) -> bool:
    return any(token in compact_line for token in ("不执行", "未执行", "没有执行", "不启动", "未启动", "没有启动", "不打开", "未打开", "不修改", "未修改", "没有修改", "不读取", "未读取"))


def _missing_core_verifications(positive: set[str]) -> list[str]:
    risks: list[str] = []
    if "compileall" not in positive:
        risks.append("验证结果缺少 compileall 通过信号。")
    if "unittest" not in positive:
        risks.append("验证结果缺少 unittest/tests 通过信号。")
    if "diff_check" not in positive:
        risks.append("验证结果缺少 git diff --check 通过信号。")
    return risks


def _manual_acceptance_risks(report: AgentCompletionReport) -> list[str]:
    if not report.manual_acceptance:
        return ["报告没有提供人工验收结果。"]
    text = "\n".join(report.manual_acceptance)
    if any(token in text.lower() for token in ("skipped", "partial")) or any(token in text for token in ("未做", "没有做", "未进行", "待验收")):
        return ["人工验收未完成或只完成了一部分。"]
    return []


def _scope_risks(report: AgentCompletionReport) -> list[str]:
    files = [path.replace("\\", "/").lower() for path in report.changed_files]
    touches_frontend = any(path.startswith("frontend/") for path in files)
    touches_backend = any(path.startswith("src/") or path.startswith("scripts/") for path in files)
    if touches_frontend and touches_backend:
        manual_text = "\n".join(report.manual_acceptance)
        if not any(token in manual_text for token in ("真实窗口", "点击", "控制面板", "浏览器", "pywebview")):
            return ["同时修改前端和后端，建议补一次真实窗口或控制面板 smoke 验收。"]
    if len(files) >= 12:
        return ["改动文件较多，建议人工复核范围是否符合原任务。"]
    return []


def _format_verification_summary(positive: set[str], claims: list[str]) -> str:
    if not positive and not claims:
        return "未提供明确验证结果"
    labels = {
        "compileall": "compileall：通过",
        "unittest": "unittest/tests：通过",
        "diff_check": "git diff --check：通过",
        "help": "--help：通过",
        "git_status_clean": "git status：干净",
    }
    parts = [labels[key] for key in ("compileall", "unittest", "diff_check", "help", "git_status_clean") if key in positive]
    return "；".join(parts) if parts else "已提供验证描述，但通过信号不完整"


def _format_safety_summary(report: AgentCompletionReport, dangerous: list[str]) -> str:
    if dangerous:
        return "发现安全边界风险"
    if report.safety_claims:
        return "报告包含安全边界声明，未发现明显越界操作"
    return "报告没有单独列出安全边界声明"


def _next_steps(
    verdict: str,
    risk_points: list[str],
    missing_core: list[str],
    manual_risks: list[str],
) -> list[str]:
    if verdict == "reject":
        return ["不要直接保留该提交，先要求执行 Agent 修复报告中的失败或越界项。"]
    if verdict == "insufficient":
        return ["要求补充 commit hash、改动文件、验证结果和人工验收结论后再审查。"]
    steps: list[str] = []
    if manual_risks:
        steps.append("先补一次真实使用路径的人工验收。")
    if missing_core:
        steps.append("补齐 compileall、unittest 和 git diff --check 的明确通过结果。")
    if not steps and risk_points:
        steps.append("按风险点逐项复核后再保留。")
    if not steps:
        steps.append("可以保留该提交，并继续后续任务。")
    return steps


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
