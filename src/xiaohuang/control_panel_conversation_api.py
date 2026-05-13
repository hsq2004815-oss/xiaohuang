"""Conversation and text-message API helpers for the web control panel."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from xiaohuang.conversation_history_service import ConversationHistoryStore
from xiaohuang.text_interaction_session_service import TextInteractionSessionStore
from xiaohuang.text_task_registry_service import PendingTextTaskRegistry


def _ok(data: Any = None, message: str = "") -> dict:
    return {"ok": True, "data": data, "message": message}


def _fail(error: str, code: str = "error") -> dict:
    return {"ok": False, "error": error, "code": code}


class ControlPanelConversationApi:
    """Handle text conversations while preserving the legacy LLM turn path."""

    def __init__(
        self,
        *,
        history_store: ConversationHistoryStore,
        session_store: TextInteractionSessionStore,
        task_registry: PendingTextTaskRegistry,
        resolve_config_path: Callable[[], Path],
        run_text_turn: Callable[..., Any],
    ) -> None:
        self._history_store = history_store
        self._session_store = session_store
        self._task_registry = task_registry
        self._resolve_config_path = resolve_config_path
        self._run_text_turn = run_text_turn

    def list_text_conversations(self, payload: dict | None = None) -> dict:
        try:
            conversations = self._history_store.list_conversations()
            result = []
            for c in conversations:
                task_counts = self._history_store.get_bound_task_counts(c.id)
                result.append({
                    **c.to_dict(),
                    "task_count": sum(task_counts.values()),
                    "task_counts": task_counts,
                })
            return _ok(data={"conversations": result}, message="会话列表已加载")
        except Exception:
            return _fail("加载会话列表失败", "conversation_list_error")

    def create_text_conversation(self, payload: dict | None = None) -> dict:
        try:
            title = ""
            if isinstance(payload, dict):
                title = str(payload.get("title") or "")
            conv = self._history_store.create_conversation(title=title)
            return _ok(data=conv.to_dict(), message="新对话已创建")
        except Exception:
            return _fail("创建对话失败", "conversation_create_error")

    def get_text_conversation(self, payload: dict | None = None) -> dict:
        try:
            conversation_id = ""
            if isinstance(payload, dict):
                conversation_id = str(payload.get("conversation_id") or "")
            if not conversation_id:
                conv = self._history_store.get_or_create_default()
                conversation_id = conv.id
            conv = self._history_store.get_conversation(conversation_id)
            if conv is None:
                return _fail("会话不存在", "conversation_not_found")
            messages = self._history_store.get_messages(conversation_id)
            tasks = self._history_store.get_bound_tasks(conversation_id)
            task_counts = self._history_store.get_bound_task_counts(conversation_id)
            return _ok(data={
                "conversation": conv.to_dict(),
                "messages": [m.to_dict() for m in messages],
                "bound_tasks": [t.to_dict() for t in tasks],
                "task_counts": task_counts,
            }, message="会话已加载")
        except ValueError:
            return _fail("会话 ID 格式无效", "invalid_conversation_id")
        except Exception:
            return _fail("加载会话失败", "conversation_get_error")

    def clear_text_conversation(self, payload: dict | None = None) -> dict:
        try:
            conversation_id = ""
            if isinstance(payload, dict):
                conversation_id = str(payload.get("session_id") or "")
            if not conversation_id:
                return _fail("会话 ID 不能为空", "missing_conversation_id")
            conv = self._history_store.get_conversation(conversation_id)
            if conv is None:
                return _fail("会话不存在", "conversation_not_found")
            # Only clear messages, preserve bound tasks.
            self._history_store.clear_conversation_messages(conversation_id)
            self._session_store.clear(conversation_id)
            return _ok(data={"conversation_id": conversation_id}, message="会话消息已清空")
        except ValueError:
            return _fail("会话 ID 格式无效", "invalid_conversation_id")
        except Exception:
            return _fail("清空会话失败", "clear_conversation_error")

    def clear_all_text_conversations(self, payload: dict | None = None) -> dict:
        try:
            result = self._history_store.clear_all_conversations()
            self._session_store.clear_all()
            return _ok(data=result, message="所有对话已清除")
        except Exception:
            return _fail("清除所有对话失败", "clear_all_conversations_error")

    def list_conversation_multica_tasks(self, payload: dict | None = None) -> dict:
        try:
            conversation_id = ""
            if isinstance(payload, dict):
                conversation_id = str(payload.get("conversation_id") or "")
            if not conversation_id:
                return _fail("会话 ID 不能为空", "missing_conversation_id")
            tasks = self._history_store.get_bound_tasks(conversation_id)
            task_counts = self._history_store.get_bound_task_counts(conversation_id)
            return _ok(data={
                "tasks": [t.to_dict() for t in tasks],
                "task_counts": task_counts,
            }, message="绑定任务已加载")
        except ValueError:
            return _fail("会话 ID 格式无效", "invalid_conversation_id")
        except Exception:
            return _fail("加载绑定任务失败", "multica_task_list_error")

    def bind_multica_run_to_conversation(self, payload: dict | None = None) -> dict:
        try:
            data = payload if isinstance(payload, dict) else {}
            conversation_id = str(data.get("conversation_id") or "")
            issue_id = str(data.get("issue_id") or "")
            task_id = str(data.get("task_id") or "")
            if not conversation_id:
                return _fail("会话 ID 不能为空", "missing_conversation_id")
            if not issue_id and not task_id:
                return _fail("issue_id 或 task_id 至少提供一个", "missing_issue_task_id")
            binding = self._history_store.bind_multica_task(
                conversation_id=conversation_id,
                issue_id=issue_id,
                task_id=task_id,
                run_status=str(data.get("run_status") or ""),
                review_summary=str(data.get("review_summary") or ""),
                messages_count=int(data.get("messages_count") or 0),
                tool_use_count=int(data.get("tool_use_count") or 0),
                tool_result_count=int(data.get("tool_result_count") or 0),
                target_project_path=str(data.get("target_project_path") or ""),
                agent=str(data.get("agent") or ""),
                title=str(data.get("title") or ""),
            )
            return _ok(data=binding.to_dict(), message="任务已绑定")
        except ValueError as e:
            return _fail(str(e), "binding_conflict")
        except Exception:
            return _fail("绑定任务失败", "multica_bind_error")

    def run_legacy_text_message_turn(self, payload: dict) -> dict:
        """Exact copy of the legacy LLM call path; persistence is separate."""
        try:
            text = ""
            session_id = "control_panel"
            if isinstance(payload, dict):
                text = str(payload.get("text") or "")
                session_id = str(payload.get("session_id") or "control_panel")

            result = self._run_text_turn(
                text,
                session_store=self._session_store,
                session_id=session_id,
                config_path=self._resolve_config_path(),
            )
            data = asdict(result)
            if data.get("requires_confirmation") and isinstance(data.get("pending_task"), dict):
                record = self._task_registry.register(data["pending_task"])
                data["pending_task"] = dict(record.task)
            return _ok(data=data, message="消息已回复" if result.ok else "消息处理失败")
        except Exception:
            return _fail("文本消息处理失败", "send_text_message_error")

    def send_text_message(self, payload: dict) -> dict:
        """Run the legacy LLM turn, then persist messages by conversation_id."""
        response = self.run_legacy_text_message_turn(payload)

        if not response.get("ok"):
            return response

        try:
            data = response.get("data") or {}
            user_text = str((payload or {}).get("text") or "")
            raw_sid = str((payload or {}).get("session_id") or "").strip()
            raw_cid = str((payload or {}).get("conversation_id") or "").strip()
            session_id = raw_sid if raw_sid else "control_panel"
            conversation_id = raw_cid or session_id

            try:
                default_conv = self._history_store.get_or_create_default()
            except Exception:
                default_conv = None

            if not raw_cid and session_id == "control_panel" and default_conv is not None:
                conversation_id = default_conv.id
            data["conversation_id"] = conversation_id

            try:
                self._history_store.save_user_message(conversation_id, user_text)
            except Exception:
                response["persistence_warning"] = "failed to save user message"

            try:
                reply_text = data.get("reply_text", "")
                meta = {
                    "reply_source": data.get("reply_source", ""),
                    "has_llm_key": data.get("has_llm_key", False),
                    "llm_configured": data.get("llm_configured", False),
                    "latency_ms": data.get("latency_ms", 0),
                }
                pending_snapshot = None
                if data.get("requires_confirmation") and isinstance(data.get("pending_task"), dict):
                    pending_snapshot = dict(data["pending_task"])
                self._history_store.save_assistant_message(
                    conversation_id,
                    reply_text or "(空回复)",
                    meta=meta,
                    pending_task_snapshot=pending_snapshot,
                )
            except Exception:
                if response.get("persistence_warning"):
                    response["persistence_warning"] += "; failed to save assistant message"
                else:
                    response["persistence_warning"] = "failed to save assistant message"
        except Exception:
            pass

        return response

    def clear_text_session(self, payload: dict | None = None) -> dict:
        try:
            session_id = "control_panel"
            if isinstance(payload, dict):
                session_id = str(payload.get("session_id") or "control_panel")
            self._session_store.clear(session_id)
            return _ok(data={"session_id": session_id}, message="文本会话已清空")
        except Exception:
            return _fail("清空文本会话失败", "clear_text_session_error")
