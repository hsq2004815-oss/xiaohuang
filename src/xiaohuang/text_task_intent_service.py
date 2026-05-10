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

_RECENT_ERRORS_TERMS = (
    "最近错误",
    "最近报错",
    "最近异常",
    "最近日志错误",
    "最近日志报错",
    "有什么报错",
    "有没有报错",
    "找错误",
    "查错误",
    "看错误",
    "帮我看下最近异常",
    "有什么异常",
)

_RUNTIME_EVENTS_TERMS = (
    "最近事件",
    "运行事件",
    "最近运行记录",
    "事件摘要",
    "总结最近",
    "最近发生了什么",
    "运行记录",
)

_CONFIG_TERMS = (
    "当前配置",
    "配置摘要",
    "检查配置",
    "看配置",
    "查看配置",
    "配置怎么样",
    "唤醒和tts配置",
    "唤醒和 tts 配置",
    "唤醒配置",
    "tts配置",
    "配置信息",
)

_HEALTH_REPORT_TERMS = (
    "健康检查",
    "做个健康检查",
    "检查一下你自己",
    "检查小黄",
    "小黄自检",
    "自检一下",
    "体检一下",
    "你现在状态怎么样",
    "现在状态怎么样",
    "你最近有没有问题",
    "小黄出问题了吗",
    "为什么最近不太正常",
    "全面检查",
    "小黄健康",
    "状况检查",
    "运行健康报告",
    "自我检查",
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

    if _contains_any(normalized, _RECENT_ERRORS_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_recent_errors_review",
            title="查看最近错误",
            summary="读取最近日志中的错误、异常和失败线索并给出摘要。",
            risk_level="low",
            allowed=True,
            reason="只读错误分析任务，需要用户确认后才能执行。",
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

    if _contains_any(normalized, _RUNTIME_EVENTS_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_runtime_events_review",
            title="总结最近运行事件",
            summary="读取内存中的运行事件记录并汇总来源、类型和级别分布。",
            risk_level="low",
            allowed=True,
            reason="只读运行事件摘要，需要用户确认后才能执行。",
        )

    if _contains_any(normalized, _CONFIG_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_config_summary",
            title="查看当前配置摘要",
            summary="读取当前配置文件并输出安全的摘要信息。",
            risk_level="low",
            allowed=True,
            reason="只读配置摘要任务，需要用户确认后才能执行。",
        )

    if _contains_any(normalized, _HEALTH_REPORT_TERMS):
        return TextTaskIntentResult(
            is_task=True,
            task_type="readonly_health_report",
            title="小黄健康检查",
            summary="综合检查小黄的基础路径、配置、运行事件和最近错误，生成一份安全只读健康报告。",
            risk_level="low",
            allowed=True,
            reason="只读健康检查任务，需要用户确认后才能执行。",
        )

    return TextTaskIntentResult(is_task=False)


def _normalize(text: str) -> str:
    return "".join(str(text or "").lower().split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_normalize(term) in text for term in terms)


def _looks_like_status_check(text: str) -> bool:
    return _contains_any(text, _STATUS_ACTION_TERMS) and _contains_any(text, _STATUS_OBJECT_TERMS)
