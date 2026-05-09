from __future__ import annotations

from xiaohuang.text_task_models import TextTaskIntentResult

_BLOCKED_TERMS = (
    "执行命令",
    "powershell",
    "cmd",
    "删除文件",
    "删文件",
    "重启电脑",
    "发微信",
    "发qq",
    "发送微信",
    "发送qq",
    "自动操作浏览器",
)

_LOG_TERMS = (
    "分析日志",
    "检查日志",
    "查看日志",
    "最近日志",
    "日志错误",
    "日志报错",
    "有没有错误",
    "error",
    "traceback",
    "报错",
)

_STATUS_ACTION_TERMS = ("检查", "查看", "查询", "获取")
_STATUS_OBJECT_TERMS = ("状态", "小黄状态", "当前状态")

_DIAGNOSTIC_TERMS = (
    "分析诊断",
    "查看诊断",
    "检查诊断",
    "诊断报告",
    "启动失败原因",
    "启动失败",
)


def detect_text_task_intent(text: str) -> TextTaskIntentResult:
    original = str(text or "").strip()
    if not original:
        return TextTaskIntentResult(is_task=False)

    normalized = _normalize(original)

    if _contains_any(normalized, _BLOCKED_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="blocked_local_execution",
            title="受限本地执行请求",
            summary="用户请求执行本地命令、删除文件、发送消息或自动操作外部应用。",
            risk_level="high",
            allowed=False,
            reason="文本入口当前不允许执行本地命令或操作外部应用。",
        )

    if _contains_any(normalized, _LOG_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_log_analysis",
            title="分析最近日志错误",
            summary="读取项目 logs 目录中的最近日志并总结错误信息。",
            risk_level="low",
            allowed=True,
            reason="只读日志分析任务，需要用户确认后才能执行。",
        )

    if _looks_like_status_check(normalized):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_status_check",
            title="检查小黄当前状态",
            summary="读取小黄运行状态并总结当前服务、唤醒、模型和最近错误。",
            risk_level="low",
            allowed=True,
            reason="只读状态检查任务，需要用户确认后才能执行。",
        )

    if _contains_any(normalized, _DIAGNOSTIC_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_diagnostic_review",
            title="分析诊断信息",
            summary="读取已有诊断信息并总结可能原因和排查建议。",
            risk_level="low",
            allowed=True,
            reason="只读诊断分析任务，需要用户确认后才能执行。",
        )

    return TextTaskIntentResult(is_task=False)


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_normalize(term) in text for term in terms)


def _looks_like_status_check(text: str) -> bool:
    return _contains_any(text, _STATUS_ACTION_TERMS) and _contains_any(text, _STATUS_OBJECT_TERMS)
