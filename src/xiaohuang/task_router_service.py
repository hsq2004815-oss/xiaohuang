from __future__ import annotations

from dataclasses import dataclass

TASK_ROUTE_NOT_IMPLEMENTED = "not_implemented"
TASK_ROUTE_NOT_TASK = "not_task"

_TOOL_KEYWORDS = (
    "打开", "帮我打开",
    "浏览器",
    "下载",
    "搜索",
    "发消息",
    "发微信",
    "发qq",
    "运行",
    "执行",
    "写代码",
    "opencode",
    "爬取",
    "入库",
    "操作",
)


@dataclass(frozen=True)
class TaskRouteResult:
    is_task_request: bool
    can_execute: bool
    reason: str
    message: str
    suggested_action: str | None = None


def route_task(user_text: str) -> TaskRouteResult:
    normalized = str(user_text or "").replace(" ", "").lower()
    if not normalized:
        return TaskRouteResult(
            is_task_request=False,
            can_execute=False,
            reason=TASK_ROUTE_NOT_TASK,
            message="",
        )
    if any(keyword in normalized for keyword in _TOOL_KEYWORDS):
        return TaskRouteResult(
            is_task_request=True,
            can_execute=False,
            reason=TASK_ROUTE_NOT_IMPLEMENTED,
            message="当前版本还不能执行工具",
        )
    return TaskRouteResult(
        is_task_request=False,
        can_execute=False,
        reason=TASK_ROUTE_NOT_TASK,
        message="",
    )
