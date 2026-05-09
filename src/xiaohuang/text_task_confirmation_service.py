from __future__ import annotations

from uuid import uuid4

from xiaohuang.text_task_models import PendingTextTask, TextTaskIntentResult

_PENDING_STATUS = "pending_confirmation"


def build_pending_text_task(intent: TextTaskIntentResult, original_text: str) -> PendingTextTask:
    return PendingTextTask(
        task_id=f"text-task-{uuid4().hex}",
        title=intent.title,
        task_type=intent.task_type,
        summary=intent.summary,
        risk_level=intent.risk_level,
        status=_PENDING_STATUS,
        allowed=bool(intent.allowed),
        original_text=str(original_text or "").strip(),
        reason=intent.reason,
    )


def format_pending_task_reply(task: PendingTextTask) -> str:
    allowed_note = (
        "这个任务需要你确认后才能执行。"
        if task.allowed
        else "这个任务当前不允许执行，我不会执行。你可以改成只读分析任务。"
    )
    return "\n".join(
        [
            "我理解你想执行一个任务：",
            "",
            f"任务：{task.title}",
            f"类型：{task.task_type}",
            f"风险：{task.risk_level}",
            f"说明：{task.summary}",
            "",
            allowed_note,
        ]
    )
