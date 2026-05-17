"""test_tool_runtime.py — C5H-B readonly tool protocol tests.

Covers: ToolSpec/ToolRegistry, JSON Protocol, Permission, Readonly tools,
Transcript, Turn Loop, Cleanup, and regression for C5G.3-B / Multica.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase

from xiaohuang.text_interaction_service import run_text_interaction_turn
from xiaohuang.tool_runtime.tool_types import (
    ToolSpec,
    ToolCall,
    ToolResult,
    ToolPermissionDecision,
    ToolTurnRecord,
    _is_valid_tool_name,
    ALLOW_DECISION,
)
from xiaohuang.tool_runtime.tool_registry import ToolRegistry, build_default_registry
from xiaohuang.tool_runtime.tool_permission_service import ToolPermissionService
from xiaohuang.tool_runtime.json_tool_protocol import (
    JsonToolProtocol,
    ToolProtocolResult,
    parse_tool_protocol_response,
)
from xiaohuang.tool_runtime.readonly_tools import (
    READONLY_TOOL_SPECS,
    resolve_project_path,
    is_path_allowed,
    is_sensitive_path,
    is_allowed_text_file,
    execute_readonly_tool,
    get_current_conversation_context,
    list_project_files_readonly,
    read_project_file_readonly,
    search_project_text_readonly,
)
from xiaohuang.tool_runtime.tool_execution_service import ToolExecutionService
from xiaohuang.tool_runtime.tool_transcript_service import ToolTranscriptService
from xiaohuang.tool_runtime.agent_turn_loop import (
    ReadonlyToolTurnConfig,
    ReadonlyToolTurnResult,
    run_readonly_tool_turn,
)

# ---------------------------------------------------------------------------
# ToolSpec / ToolRegistry
# ---------------------------------------------------------------------------


class TestToolSpec(TestCase):
    def test_valid_tool_name(self):
        spec = ToolSpec(
            name="test_tool",
            description="test",
            input_schema={},
        )
        self.assertEqual(spec.name, "test_tool")

    def test_invalid_tool_name_raises(self):
        with self.assertRaises(ValueError):
            ToolSpec(name="Test-Tool", description="", input_schema={})
        with self.assertRaises(ValueError):
            ToolSpec(name="", description="", input_schema={})

    def test_default_values(self):
        spec = ToolSpec(name="test", description="desc", input_schema={"type": "object"})
        self.assertEqual(spec.risk_level, "readonly")
        self.assertTrue(spec.readonly)
        self.assertFalse(spec.requires_confirmation)
        self.assertEqual(spec.timeout_seconds, 30)
        self.assertEqual(spec.max_output_chars, 6000)


class TestToolRegistry(TestCase):
    def test_register_and_get(self):
        registry = ToolRegistry()
        spec = ToolSpec(name="tool_a", description="A", input_schema={})
        registry.register_tool(spec)
        self.assertEqual(registry.get_tool("tool_a"), spec)

    def test_duplicate_name_raises(self):
        registry = ToolRegistry()
        spec = ToolSpec(name="tool_a", description="A", input_schema={})
        registry.register_tool(spec)
        with self.assertRaises(ValueError):
            registry.register_tool(ToolSpec(name="tool_a", description="B", input_schema={}))

    def test_invalid_name_raises(self):
        registry = ToolRegistry()
        with self.assertRaises(ValueError):
            registry.register_tool(ToolSpec(name="bad name", description="x", input_schema={}))

    def test_list_tools(self):
        registry = ToolRegistry()
        for name in ("tool_a", "tool_b"):
            registry.register_tool(ToolSpec(name=name, description=name, input_schema={}))
        names = [t.name for t in registry.list_tools()]
        self.assertEqual(set(names), {"tool_a", "tool_b"})

    def test_get_missing_returns_none(self):
        registry = ToolRegistry()
        self.assertIsNone(registry.get_tool("nonexistent"))

    def test_schema_export(self):
        registry = ToolRegistry()
        registry.register_tool(ToolSpec(
            name="test_tool", description="test desc",
            input_schema={"type": "object", "properties": {}},
        ))
        schema = registry.get_tool_schema_for_prompt()
        self.assertIn("test_tool", schema)
        self.assertIn("test desc", schema)

    def test_build_default_registry_has_6_tools(self):
        registry = build_default_registry()
        names = {t.name for t in registry.list_tools()}
        expected = {
            "get_current_conversation_context",
            "list_project_files_readonly",
            "read_project_file_readonly",
            "search_project_text_readonly",
            "get_multica_bound_tasks_readonly",
            "search_database_brief_readonly",
        }
        self.assertEqual(names, expected)

    def test_len_and_contains(self):
        registry = build_default_registry()
        self.assertEqual(len(registry), 6)
        self.assertIn("read_project_file_readonly", registry)
        self.assertNotIn("shell", registry)


class TestToolNameValidation(TestCase):
    def test_valid_names(self):
        for name in ("a", "abc", "tool_1", "get_current_conversation_context", "list_project_files_readonly"):
            self.assertTrue(_is_valid_tool_name(name), f"should be valid: {name}")

    def test_invalid_names(self):
        for name in ("", "A", "Tool-Name", "tool name", "tool.name", "tool/name"):
            self.assertFalse(_is_valid_tool_name(name), f"should be invalid: {name}")


# ---------------------------------------------------------------------------
# JSON Protocol
# ---------------------------------------------------------------------------


class TestJsonProtocol(TestCase):
    def setUp(self):
        self.protocol = JsonToolProtocol()

    def test_plain_text_passthrough(self):
        result = self.protocol.parse("你好，今天天气不错")
        self.assertEqual(result.kind, "plain_text")
        self.assertEqual(result.content, "你好，今天天气不错")

    def test_legal_final(self):
        result = self.protocol.parse(json.dumps({"type": "final", "content": "你好"}))
        self.assertEqual(result.kind, "final")
        self.assertEqual(result.content, "你好")

    def test_legal_tool_call(self):
        result = self.protocol.parse(
            json.dumps({
                "type": "tool_call",
                "tool_name": "read_project_file_readonly",
                "arguments": {"path": "src/test.py", "max_chars": 4000},
            })
        )
        self.assertEqual(result.kind, "tool_call")
        self.assertEqual(result.tool_name, "read_project_file_readonly")
        self.assertEqual(result.arguments, {"path": "src/test.py", "max_chars": 4000})

    def test_non_json_falls_back(self):
        result = self.protocol.parse("这不是JSON")
        self.assertEqual(result.kind, "plain_text")

    def test_array_rejected(self):
        result = self.protocol.parse(json.dumps([{"type": "final", "content": "x"}]))
        self.assertEqual(result.kind, "plain_text")

    def test_multiple_objects_rejected(self):
        # Two JSON objects concatenated
        text = json.dumps({"type": "final", "content": "a"}) + "\n" + json.dumps({"type": "final", "content": "b"})
        result = self.protocol.parse(text)
        self.assertNotEqual(result.kind, "tool_call")

    def test_code_fence_with_single_object_accepted(self):
        text = '```json\n{"type":"final","content":"hello"}\n```'
        result = self.protocol.parse(text)
        self.assertEqual(result.kind, "final")
        self.assertEqual(result.content, "hello")

    def test_code_fence_with_multiple_objects_rejected(self):
        text = '```json\n{"a":1}\n{"b":2}\n```'
        result = self.protocol.parse(text)
        # Should fall back since inner isn't a single dict
        self.assertEqual(result.kind, "plain_text")

    def test_unknown_type_falls_back(self):
        result = self.protocol.parse(json.dumps({"type": "unknown_thing"}))
        self.assertEqual(result.kind, "plain_text")

    def test_final_missing_content_becomes_error(self):
        result = self.protocol.parse(json.dumps({"type": "final"}))
        self.assertEqual(result.kind, "error")

    def test_tool_call_missing_tool_name(self):
        result = self.protocol.parse(json.dumps({"type": "tool_call", "arguments": {}}))
        self.assertEqual(result.kind, "error")

    def test_tool_call_arguments_not_dict(self):
        result = self.protocol.parse(json.dumps({
            "type": "tool_call",
            "tool_name": "x",
            "arguments": [1, 2, 3],
        }))
        self.assertEqual(result.kind, "error")

    def test_empty_text(self):
        result = self.protocol.parse("")
        self.assertEqual(result.kind, "plain_text")
        self.assertEqual(result.content, "")

    def test_parse_tool_protocol_response_convenience(self):
        result = parse_tool_protocol_response("普通文本")
        self.assertEqual(result.kind, "plain_text")

    def test_build_tool_result_message(self):
        msg = self.protocol.build_tool_result_message("call_id_1", "read_file", "file contents here", is_error=False)
        self.assertIn("成功", msg)
        self.assertIn("file contents here", msg)
        self.assertIn("不要要求用户重复指令", msg)

        err_msg = self.protocol.build_tool_result_message("call_id_2", "read_file", "error happened", is_error=True)
        self.assertIn("错误", err_msg)
        self.assertIn("error happened", err_msg)


# ---------------------------------------------------------------------------
# Permission Service
# ---------------------------------------------------------------------------


class TestToolPermissionService(TestCase):
    def setUp(self):
        self.service = ToolPermissionService()

    def test_readonly_tool_allowed(self):
        spec = ToolSpec(name="read_project_file_readonly", description="", input_schema={})
        call = ToolCall(id="1", tool_name="read_project_file_readonly", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertTrue(decision.allowed)

    def test_unregistered_tool_rejected(self):
        call = ToolCall(id="1", tool_name="nonexistent", arguments={})
        decision = self.service.evaluate(call, None)
        self.assertFalse(decision.allowed)
        self.assertIn("not registered", decision.reason)

    def test_non_readonly_tool_rejected(self):
        spec = ToolSpec(name="write_file", description="", input_schema={}, readonly=False, risk_level="write")
        call = ToolCall(id="1", tool_name="write_file", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)
        self.assertIn("only readonly tools allowed", decision.reason)

    def test_shell_prefix_rejected(self):
        spec = ToolSpec(name="shell", description="", input_schema={}, risk_level="readonly")
        call = ToolCall(id="1", tool_name="shell", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)

    def test_write_prefix_rejected(self):
        spec = ToolSpec(name="write_file_thing", description="", input_schema={}, risk_level="readonly")
        call = ToolCall(id="1", tool_name="write_file_thing", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)

    def test_git_prefix_rejected(self):
        spec = ToolSpec(name="git_status_readonly", description="", input_schema={}, risk_level="readonly")
        call = ToolCall(id="1", tool_name="git_status_readonly", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)

    def test_delete_prefix_rejected(self):
        spec = ToolSpec(name="delete_temp", description="", input_schema={}, risk_level="readonly")
        call = ToolCall(id="1", tool_name="delete_temp", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)

    def test_dangerous_risk_level_rejected(self):
        spec = ToolSpec(name="some_tool", description="", input_schema={}, risk_level="dangerous")
        call = ToolCall(id="1", tool_name="some_tool", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)

    def test_missing_required_argument_rejected(self):
        spec = ToolSpec(
            name="read_project_file_readonly",
            description="",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        call = ToolCall(id="1", tool_name="read_project_file_readonly", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)
        self.assertIn("arguments", decision.reason)

    def test_argument_type_mismatch_rejected(self):
        spec = ToolSpec(
            name="read_project_file_readonly",
            description="",
            input_schema={
                "type": "object",
                "properties": {"max_chars": {"type": "integer"}},
            },
        )
        call = ToolCall(id="1", tool_name="read_project_file_readonly", arguments={"max_chars": "not_a_number"})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)
        self.assertIn("arguments", decision.reason)

    def test_requires_confirmation_not_auto_approved(self):
        spec = ToolSpec(
            name="confirm_tool", description="", input_schema={},
            requires_confirmation=True,
        )
        call = ToolCall(id="1", tool_name="confirm_tool", arguments={})
        decision = self.service.evaluate(call, spec)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_confirmation)


# ---------------------------------------------------------------------------
# Readonly Tools — Path Safety
# ---------------------------------------------------------------------------


class TestPathSafety(TestCase):
    def setUp(self):
        self.project_root = Path(r"E:\Projects\xiaohuang")

    def test_resolve_relative_path(self):
        path = resolve_project_path("src/xiaohuang", project_root=self.project_root)
        self.assertIn("src", str(path))
        self.assertIn("xiaohuang", str(path))

    def test_reject_absolute_path(self):
        with self.assertRaises(ValueError):
            resolve_project_path("C:\\Windows\\System32", project_root=self.project_root)

    def test_reject_empty_path(self):
        with self.assertRaises(ValueError):
            resolve_project_path("", project_root=self.project_root)

    def test_reject_parent_traversal(self):
        with self.assertRaises(ValueError):
            resolve_project_path("../etc/passwd", project_root=self.project_root)

    def test_reject_unc_path(self):
        with self.assertRaises(ValueError):
            resolve_project_path("\\\\server\\share\\file", project_root=self.project_root)

    def test_reject_windows_drive_letter(self):
        with self.assertRaises(ValueError):
            resolve_project_path("D:/something", project_root=self.project_root)

    def test_is_sensitive_path_dotenv(self):
        path = self.project_root / ".env"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_secrets_ps1(self):
        path = self.project_root / "secrets.ps1"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_git(self):
        path = self.project_root / ".git" / "config"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_venv(self):
        path = self.project_root / ".venv" / "lib" / "site-packages"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_node_modules(self):
        path = self.project_root / "node_modules" / "lodash"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_pycache(self):
        path = self.project_root / "__pycache__" / "module.pyc"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_key_file(self):
        path = self.project_root / "data" / "key.txt"
        self.assertTrue(is_sensitive_path(path))

    def test_is_sensitive_path_token(self):
        path = self.project_root / "token.json"
        self.assertTrue(is_sensitive_path(path))

    def test_normal_py_file_not_sensitive(self):
        path = self.project_root / "src" / "test.py"
        self.assertFalse(is_sensitive_path(path))

    def test_is_allowed_text_file_py(self):
        self.assertTrue(is_allowed_text_file(Path("test.py")))

    def test_is_allowed_text_file_secrets_ps1(self):
        # .ps1 with 'secret' in name should be rejected
        self.assertFalse(is_allowed_text_file(Path("secrets.ps1")))

    def test_is_allowed_text_file_normal_ps1(self):
        self.assertTrue(is_allowed_text_file(Path("run_env.ps1")))

    def test_is_allowed_text_file_binary_disallowed(self):
        self.assertFalse(is_allowed_text_file(Path("image.png")))
        self.assertFalse(is_allowed_text_file(Path("audio.mp3")))


# ---------------------------------------------------------------------------
# Readonly Tools — Tool Functions
# ---------------------------------------------------------------------------


class TestReadonlyToolFunctions(TestCase):
    def setUp(self):
        self.project_root = Path(r"E:\Projects\xiaohuang")

    def test_get_current_conversation_context(self):
        result = get_current_conversation_context(
            {},
            context={
                "conversation_id": "test123",
                "current_goal": "test goal",
                "current_status": "active",
                "next_step": "review",
                "important_constraints": ["no write"],
                "compact_summary": "summary text",
            },
        )
        self.assertIn("test123", result)
        self.assertIn("test goal", result)
        self.assertIn("active", result)
        self.assertIn("review", result)
        self.assertIn("no write", result)
        self.assertIn("summary text", result)

    def test_get_current_conversation_context_empty(self):
        result = get_current_conversation_context({}, context={})
        self.assertIn("当前会话 ID", result)

    def test_list_project_files_readonly_valid_dir(self):
        result = list_project_files_readonly(
            {"relative_dir": "src/xiaohuang", "max_results": 20},
            project_root=self.project_root,
        )
        self.assertIn("src/xiaohuang", result)
        # Should find at least some .py files
        self.assertIn("[文件]", result)

    def test_list_project_files_readonly_max_results(self):
        result = list_project_files_readonly(
            {"relative_dir": "src/xiaohuang", "max_results": 3},
            project_root=self.project_root,
        )
        lines = result.splitlines()
        file_lines = [l for l in lines if "[文件]" in l]
        self.assertLessEqual(len(file_lines), 3)

    def test_list_project_files_readonly_sensitive_dir(self):
        with self.assertRaises(ValueError):
            list_project_files_readonly(
                {"relative_dir": ".git"},
                project_root=self.project_root,
            )

    def test_read_project_file_readonly_valid(self):
        result = read_project_file_readonly(
            {"path": "src/xiaohuang/tool_runtime/tool_types.py", "max_chars": 2000},
            project_root=self.project_root,
        )
        self.assertIn("tool_types.py", result)
        self.assertIn("dataclass", result)

    def test_read_project_file_readonly_sensitive(self):
        with self.assertRaises(ValueError):
            read_project_file_readonly(
                {"path": ".env"},
                project_root=self.project_root,
            )

    def test_read_project_file_readonly_secrets_ps1(self):
        output, is_error = execute_readonly_tool(
            "read_project_file_readonly",
            {"path": "secrets.ps1"},
            project_root=self.project_root,
        )
        self.assertTrue(is_error)

    def test_read_project_file_readonly_path_traversal(self):
        output, is_error = execute_readonly_tool(
            "read_project_file_readonly",
            {"path": "../Windows/System32/drivers/etc/hosts"},
            project_root=self.project_root,
        )
        self.assertTrue(is_error)

    def test_read_project_file_readonly_nonexistent(self):
        output, is_error = execute_readonly_tool(
            "read_project_file_readonly",
            {"path": "nonexistent_file_xyz.py"},
            project_root=self.project_root,
        )
        self.assertTrue(is_error)

    def test_read_project_file_readonly_disallowed_extension(self):
        output, is_error = execute_readonly_tool(
            "read_project_file_readonly",
            {"path": "data/something.db"},
            project_root=self.project_root,
        )
        self.assertTrue(is_error)

    def test_search_project_text_readonly(self):
        result = search_project_text_readonly(
            {"query": "ToolSpec", "relative_dir": "src/xiaohuang/tool_runtime", "max_results": 10},
            project_root=self.project_root,
        )
        self.assertIn("ToolSpec", result)
        self.assertIn("匹配:", result)

    def test_search_project_text_readonly_empty_query(self):
        output, is_error = execute_readonly_tool(
            "search_project_text_readonly",
            {"query": "", "relative_dir": "src/xiaohuang"},
            project_root=self.project_root,
        )
        self.assertTrue(is_error)

    def test_search_project_text_readonly_sensitive_dir(self):
        output, is_error = execute_readonly_tool(
            "search_project_text_readonly",
            {"query": "test", "relative_dir": ".git"},
            project_root=self.project_root,
        )
        self.assertTrue(is_error)

    def test_execute_readonly_tool_unknown(self):
        output, is_error = execute_readonly_tool("nonexistent", {}, project_root=self.project_root)
        self.assertTrue(is_error)
        self.assertIn("未注册", output)

    def test_execute_readonly_tool_success(self):
        output, is_error = execute_readonly_tool(
            "list_project_files_readonly",
            {"relative_dir": "src", "max_results": 5},
            project_root=self.project_root,
        )
        self.assertFalse(is_error)
        self.assertIn("src", output)


# ---------------------------------------------------------------------------
# Tool Execution Service
# ---------------------------------------------------------------------------


class TestToolExecutionService(TestCase):
    def setUp(self):
        from xiaohuang.tool_runtime.tool_registry import build_default_registry
        from xiaohuang.tool_runtime.tool_permission_service import ToolPermissionService
        self.registry = build_default_registry()
        self.permission = ToolPermissionService()
        self.service = ToolExecutionService(
            self.registry, self.permission,
            project_root=Path(r"E:\Projects\xiaohuang"),
        )

    def test_execute_valid_tool(self):
        call = ToolCall(
            id="test_1", tool_name="list_project_files_readonly",
            arguments={"relative_dir": "src/xiaohuang", "max_results": 5},
            conversation_id="conv_1",
        )
        result = self.service.execute(call)
        self.assertTrue(result.ok)
        self.assertGreater(result.elapsed_ms, 0)
        self.assertEqual(result.tool_call_id, "test_1")

    def test_execute_unregistered_tool(self):
        call = ToolCall(id="test_2", tool_name="nonexistent", arguments={})
        result = self.service.execute(call)
        self.assertFalse(result.ok)
        self.assertIn("not registered", result.error)

    def test_execute_timing(self):
        call = ToolCall(
            id="test_3", tool_name="read_project_file_readonly",
            arguments={"path": "src/xiaohuang/tool_runtime/tool_types.py"},
            conversation_id="conv_1",
        )
        result = self.service.execute(call)
        self.assertGreaterEqual(result.elapsed_ms, 0)

    def test_output_truncation(self):
        # Set max_output_chars on spec to force truncation
        spec = ToolSpec(
            name="read_project_file_readonly",
            description="",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            max_output_chars=50,
        )
        registry = ToolRegistry()
        registry.register_tool(spec)
        service = ToolExecutionService(registry, self.permission, project_root=Path(r"E:\Projects\xiaohuang"))
        call = ToolCall(
            id="test_4", tool_name="read_project_file_readonly",
            arguments={"path": "src/xiaohuang/tool_runtime/tool_types.py"},
            conversation_id="conv_1",
        )
        result = service.execute(call)
        self.assertTrue(result.truncated)
        self.assertIn("截断", result.output)


# ---------------------------------------------------------------------------
# Tool Transcript Service
# ---------------------------------------------------------------------------


class TestToolTranscriptService(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_transcript.db"
        self.service = ToolTranscriptService(self.db_path)

    def tearDown(self):
        try:
            import shutil
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_turn_record(self):
        record = ToolTurnRecord(
            id="turn_1",
            conversation_id="conv_1",
            status="completed",
            tool_rounds=1,
            max_tool_rounds=2,
            created_at="2026-01-01T00:00:00",
            completed_at="2026-01-01T00:00:01",
        )
        self.service.record_turn(record)
        turns = self.service.get_turns("conv_1")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["id"], "turn_1")
        self.assertEqual(turns[0]["tool_rounds"], 1)

    def test_tool_call_and_result_pairing(self):
        call = ToolCall(
            id="call_1",
            tool_name="test_tool",
            arguments={"key": "value"},
            conversation_id="conv_1",
            turn_id="turn_1",
            created_at="2026-01-01T00:00:00",
        )
        self.service.record_tool_call(call, spec_risk_level="readonly")

        result = ToolResult(
            tool_call_id="call_1",
            tool_name="test_tool",
            ok=True,
            output="test output",
            truncated=False,
            elapsed_ms=100,
            created_at="2026-01-01T00:00:01",
        )
        self.service.record_tool_result(result)

        results = self.service.get_results_for_call("call_1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["ok"], 1)
        self.assertEqual(results[0]["output"], "test output")

    def test_permission_record(self):
        decision = ToolPermissionDecision(allowed=True, reason="test")
        self.service.record_permission("call_1", "conv_1", decision)
        # Test doesn't crash — records are written

    def test_error_result_recorded(self):
        call = ToolCall(
            id="call_err",
            tool_name="test_tool",
            arguments={},
            conversation_id="conv_1",
            turn_id="turn_1",
        )
        self.service.record_tool_call(call)

        result = ToolResult(
            tool_call_id="call_err",
            tool_name="test_tool",
            ok=False,
            error="something went wrong",
            elapsed_ms=50,
            created_at="2026-01-01T00:00:01",
        )
        self.service.record_tool_result(result)

        results = self.service.get_results_for_call("call_err")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["ok"], 0)
        self.assertEqual(results[0]["error"], "something went wrong")

    def test_truncated_saved(self):
        call = ToolCall(id="call_trunc", tool_name="test", arguments={}, conversation_id="conv_1", turn_id="turn_1")
        self.service.record_tool_call(call)

        result = ToolResult(
            tool_call_id="call_trunc", tool_name="test", ok=True,
            output="short", truncated=True, elapsed_ms=10, created_at="2026-01-01T00:00:01",
        )
        self.service.record_tool_result(result)

        results = self.service.get_results_for_call("call_trunc")
        self.assertEqual(results[0]["truncated"], 1)

    def test_delete_for_conversation(self):
        record = ToolTurnRecord(id="turn_del", conversation_id="conv_del", status="ok", created_at="now")
        self.service.record_turn(record)
        self.service.record_tool_call(
            ToolCall(id="call_del", tool_name="t", arguments={}, conversation_id="conv_del", turn_id="turn_del")
        )
        self.service.record_tool_result(
            ToolResult(tool_call_id="call_del", tool_name="t", ok=True, created_at="now")
        )

        self.service.delete_for_conversation("conv_del")
        turns = self.service.get_turns("conv_del")
        self.assertEqual(len(turns), 0)

    def test_delete_all(self):
        self.service.record_turn(ToolTurnRecord(id="t1", conversation_id="c1", status="ok", created_at="now"))
        self.service.record_turn(ToolTurnRecord(id="t2", conversation_id="c2", status="ok", created_at="now"))

        self.service.delete_all()
        self.assertEqual(len(self.service.get_turns("c1")), 0)
        self.assertEqual(len(self.service.get_turns("c2")), 0)


# ---------------------------------------------------------------------------
# Agent Turn Loop
# ---------------------------------------------------------------------------


class TestAgentTurnLoop(TestCase):
    def setUp(self):
        self.registry = build_default_registry()
        self.config = ReadonlyToolTurnConfig(max_tool_rounds=2, enable_readonly_tools=True)

    def test_plain_text_no_tools(self):
        """Model returns plain text — should pass through without tool execution."""

        def dummy_llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": "这是一个普通回答，不需要工具。"}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="你好",
            context_pack_render="",
            llm_call_func=dummy_llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertIn("普通回答", result.reply_text)
        self.assertEqual(result.tool_rounds, 0)
        self.assertEqual(len(result.tool_calls), 0)

    def test_json_final(self):
        """Model returns JSON final directive."""

        def dummy_llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": json.dumps({"type": "final", "content": "JSON回复内容"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=dummy_llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.reply_text, "JSON回复内容")
        self.assertEqual(result.tool_rounds, 0)
        self.assertEqual(len(result.tool_calls), 0)

    def test_tool_call_with_valid_tool(self):
        """Model requests a valid readonly tool — should execute and re-call."""

        call_count = [0]

        def tool_llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "list_project_files_readonly",
                    "arguments": {"relative_dir": "src/xiaohuang/tool_runtime", "max_results": 3},
                })}
            return {"text": json.dumps({"type": "final", "content": "已读取目录，结果如上"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="列出目录",
            context_pack_render="",
            llm_call_func=tool_llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertIn("已读取目录", result.reply_text)
        self.assertEqual(result.tool_rounds, 1)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]["tool_name"], "list_project_files_readonly")
        self.assertTrue(result.tool_calls[0]["ok"])

    def test_max_tool_rounds(self):
        """Model keeps requesting tools — should stop at max_tool_rounds."""
        config = ReadonlyToolTurnConfig(max_tool_rounds=2, enable_readonly_tools=True)

        def looping_llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": json.dumps({
                "type": "tool_call",
                "tool_name": "get_current_conversation_context",
                "arguments": {},
            })}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=looping_llm,
            registry=self.registry,
            config=config,
        )
        self.assertLessEqual(result.tool_rounds, 2)
        self.assertLessEqual(len(result.tool_calls), 2)

    def test_tool_error_handled(self):
        """Model requests a tool that errors — should get safe reply."""
        call_count = [0]

        def error_llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "read_project_file_readonly",
                    "arguments": {"path": "nonexistent_xyz.py"},
                })}
            return {"text": json.dumps({"type": "final", "content": "文件不存在，我无法读取"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=error_llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.tool_rounds, 1)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertFalse(result.tool_calls[0]["ok"])
        self.assertIn("文件不存在", result.tool_calls[0]["output"])

    def test_empty_model_response(self):
        def empty_llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": ""}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=empty_llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.error, "模型返回为空")

    def test_tool_call_with_transcript(self):
        """Tool call with transcript recording."""
        tmpdir = tempfile.mkdtemp()
        try:
            db_path = Path(tmpdir) / "test.db"
            transcript = ToolTranscriptService(db_path)

            call_count = [0]

            def tool_llm(text: str, *, context: str = "") -> dict[str, Any]:
                call_count[0] += 1
                if call_count[0] == 1:
                    return {"text": json.dumps({
                        "type": "tool_call",
                        "tool_name": "get_current_conversation_context",
                        "arguments": {},
                    })}
                return {"text": json.dumps({"type": "final", "content": "done"})}

            result = run_readonly_tool_turn(
                conversation_id="test_conv_t",
                user_text="help",
                context_pack_render="",
                llm_call_func=tool_llm,
                registry=self.registry,
                config=self.config,
                transcript_service=transcript,
                context={"conversation_id": "test_conv_t", "current_goal": "test"},
            )

            turns = transcript.get_turns("test_conv_t")
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]["tool_rounds"], 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_llm_exception_handled(self):
        def crash_llm(text: str, *, context: str = "") -> dict[str, Any]:
            raise RuntimeError("API connection failed")

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=crash_llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.tool_rounds, 0)

    # --- C5H-B.1: final JSON must be unwrapped ---

    def test_first_call_final_json_unwrapped(self):
        """First call returns final JSON — reply_text must be content only."""

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": json.dumps({"type": "final", "content": "你好，我是小黄"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="你好",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.reply_text, "你好，我是小黄")
        self.assertNotIn('"type"', result.reply_text)
        self.assertNotIn('"final"', result.reply_text)
        self.assertNotIn('"content"', result.reply_text)

    def test_tool_then_final_json_unwrapped(self):
        """Tool call → tool execution → final JSON — reply must be content only."""
        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "list_project_files_readonly",
                    "arguments": {"relative_dir": "src/xiaohuang/tool_runtime", "max_results": 5},
                })}
            # Second call: final JSON — the key scenario from the bug report
            return {"text": json.dumps({
                "type": "final",
                "content": "src/xiaohuang/tool_runtime 目录下共有 9 个文件包括 agent_turn_loop.py 等",
            })}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="列出目录",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        # Must NOT contain raw JSON
        self.assertNotIn('"type"', result.reply_text)
        self.assertNotIn('"final"', result.reply_text)
        self.assertNotIn('"content"', result.reply_text)
        self.assertIn("agent_turn_loop", result.reply_text)
        self.assertEqual(result.tool_rounds, 1)
        self.assertEqual(len(result.tool_calls), 1)

    def test_max_rounds_final_json_still_unwrapped(self):
        """When max_tool_rounds hit and last parsed is final, must still unwrap."""
        config = ReadonlyToolTurnConfig(max_tool_rounds=1, enable_readonly_tools=True)

        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "get_current_conversation_context",
                    "arguments": {},
                })}
            # Second call returns final, but loop already at max (1 >= 1)
            return {"text": json.dumps({
                "type": "final",
                "content": "上下文信息如上",
            })}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="查看上下文",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=config,
        )
        self.assertNotIn('"type"', result.reply_text)
        self.assertNotIn('"final"', result.reply_text)
        self.assertIn("上下文信息如上", result.reply_text)

    def test_plain_text_not_mistakenly_unwrapped(self):
        """Plain text response without JSON must pass through unchanged."""

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": "你好，今天天气不错。"}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="你好",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.reply_text, "你好，今天天气不错。")

    def test_empty_content_final_handled(self):
        """Final JSON with empty content must fall back to safe message."""

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": json.dumps({"type": "final", "content": ""})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertNotIn('"type"', result.reply_text)
        self.assertNotIn('"final"', result.reply_text)
        # Empty content should produce a safe fallback, not crash
        self.assertTrue(len(result.reply_text) > 0, f"reply_text should not be empty: {result!r}")


# ---------------------------------------------------------------------------
# C5H-B.2: Mixed text + tool_call JSON & tool-result fallback
# ---------------------------------------------------------------------------


class TestMixedTextJsonExtraction(TestCase):
    def setUp(self):
        from xiaohuang.tool_runtime.tool_registry import build_default_registry
        self.registry = build_default_registry()
        self.config = ReadonlyToolTurnConfig(max_tool_rounds=2, enable_readonly_tools=True)

    def test_mixed_text_with_tool_call_extracted(self):
        """Mixed text + tool_call JSON: extract and execute the tool_call."""
        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                # Mixed text: natural language + tool_call JSON
                return {"text": (
                    '好的，我来读取文件。'
                    '{"type":"tool_call","tool_name":"read_project_file_readonly",'
                    '"arguments":{"path":"src/xiaohuang/tool_runtime/tool_types.py"}}'
                )}
            return {"text": json.dumps({"type": "final", "content": "文件内容如上"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="读取文件",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertNotIn('"type":"tool_call"', result.reply_text)
        self.assertNotIn('tool_call', result.reply_text)
        self.assertGreater(len(result.tool_calls), 0, "Should have executed tool_call")
        self.assertEqual(result.tool_calls[0]["tool_name"], "read_project_file_readonly")

    def test_multiple_json_objects_rejected(self):
        """Two JSON objects in one response: reject and don't leak raw JSON."""
        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": (
                    '{"type":"tool_call","tool_name":"list_project_files_readonly","arguments":{}}'
                    '{"type":"tool_call","tool_name":"read_project_file_readonly","arguments":{"path":"x"}}'
                )}
            return {"text": json.dumps({"type": "final", "content": "done"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        # Must not display raw tool_call JSON to user
        self.assertNotIn('"type":"tool_call"', result.reply_text)
        # Should not have executed tools (ambiguous multi-object)
        self.assertEqual(len(result.tool_calls), 0)

    def test_unknown_tool_embedded_rejected(self):
        """Embedded unknown tool_call: reject safely, no raw JSON leak."""

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": (
                '让我执行。{"type":"tool_call","tool_name":"delete_all_files",'
                '"arguments":{"target":"everything"}}'
            )}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="test",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertNotIn('"type":"tool_call"', result.reply_text)
        self.assertNotIn('delete_all_files', result.reply_text)

    def test_tool_success_empty_final_uses_tool_output(self):
        """Tool succeeds but model returns empty final: fallback to tool output."""
        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "list_project_files_readonly",
                    "arguments": {"relative_dir": "src/xiaohuang/tool_runtime", "max_results": 5},
                })}
            # Second call returns empty final
            return {"text": json.dumps({"type": "final", "content": ""})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="列出目录",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        # Must not be the generic "我暂时没有生成有效回复。"
        self.assertNotEqual(result.reply_text, "我暂时没有生成有效回复。")
        # Should contain tool output (directory listing)
        self.assertIn("我已读取目录", result.reply_text)
        self.assertEqual(result.tool_rounds, 1)
        self.assertGreater(len(result.tool_calls), 0)

    def test_tool_failure_still_safe_reply(self):
        """Tool fails: still return safe error, no raw JSON."""
        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "read_project_file_readonly",
                    "arguments": {"path": "nonexistent_xyz_file.py"},
                })}
            return {"text": json.dumps({"type": "final", "content": "文件不存在"})}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="读取不存在文件",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertNotIn('"type":"tool_call"', result.reply_text)
        self.assertNotEqual(result.reply_text, "我暂时没有生成有效回复。")

    def test_plain_text_still_passes_through(self):
        """Plain text without JSON still works normally."""

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            return {"text": "你好，今天天气不错。"}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="你好",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertEqual(result.reply_text, "你好，今天天气不错。")

    def test_mixed_text_with_final_extracted(self):
        """Mixed text with embedded final JSON: extract the content."""
        call_count = [0]

        def llm(text: str, *, context: str = "") -> dict[str, Any]:
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "get_current_conversation_context",
                    "arguments": {},
                })}
            # Mixed text with final JSON
            return {"text": (
                '好的。{"type":"final","content":"上下文如上，没有特殊信息。"}'
            )}

        result = run_readonly_tool_turn(
            conversation_id="test_conv",
            user_text="查看上下文",
            context_pack_render="",
            llm_call_func=llm,
            registry=self.registry,
            config=self.config,
        )
        self.assertNotIn('"type":"final"', result.reply_text)
        self.assertIn("上下文如上", result.reply_text)


class TestExtractEmbeddedProtocolJson(TestCase):
    def test_extract_single_tool_call(self):
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json
        text = '好的，我来读取。{"type":"tool_call","tool_name":"read_project_file_readonly","arguments":{"path":"x.py"}}'
        result = extract_embedded_protocol_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "tool_call")
        self.assertEqual(result.tool_name, "read_project_file_readonly")

    def test_extract_single_final(self):
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json
        text = '回答如下。{"type":"final","content":"这是答案"}'
        result = extract_embedded_protocol_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "final")
        self.assertEqual(result.content, "这是答案")

    def test_extract_multiple_objects_is_error(self):
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json
        text = '{"type":"final","content":"a"}{"type":"final","content":"b"}'
        result = extract_embedded_protocol_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "error")
        self.assertIn("多个", result.error)

    def test_extract_unknown_type_is_none(self):
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json
        text = '这是一段话。{"key":"value"}'
        result = extract_embedded_protocol_json(text)
        self.assertIsNone(result)

    def test_extract_no_json_is_none(self):
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json
        result = extract_embedded_protocol_json("你好，没有JSON。")
        self.assertIsNone(result)

    def test_extract_already_clean_json_is_none(self):
        from xiaohuang.tool_runtime.json_tool_protocol import extract_embedded_protocol_json
        text = '{"type":"final","content":"hello"}'
        result = extract_embedded_protocol_json(text)
        # Already clean JSON — let .parse() handle it
        self.assertIsNone(result)


class TestScrubJsonFromText(TestCase):
    def test_scrub_removes_json(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _scrub_json_from_text
        text = '你好。{"type":"tool_call","tool_name":"x","arguments":{}}谢谢。'
        result = _scrub_json_from_text(text)
        self.assertNotIn('"type"', result)
        self.assertIn("你好", result)
        self.assertIn("谢谢", result)

    def test_scrub_only_json_returns_fallback(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _scrub_json_from_text
        text = '{"type":"tool_call","tool_name":"x","arguments":{}}'
        result = _scrub_json_from_text(text)
        self.assertEqual(result, "我暂时没有生成有效回复。")

    def test_scrub_empty_returns_empty(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _scrub_json_from_text
        self.assertEqual(_scrub_json_from_text(""), "")

    def test_scrub_plain_text_passes_through(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _scrub_json_from_text
        self.assertEqual(_scrub_json_from_text("你好"), "你好")


# ---------------------------------------------------------------------------
# C5H-B.1: _unwrap_final_json_reply unit tests
# ---------------------------------------------------------------------------


class TestUnwrapFinalJson(TestCase):
    def test_unwrap_valid_final(self):
        from xiaohuang.text_interaction_service import _unwrap_final_json_reply
        text = '{"type":"final","content":"hello world"}'
        self.assertEqual(_unwrap_final_json_reply(text), "hello world")

    def test_unwrap_pass_through_plain_text(self):
        from xiaohuang.text_interaction_service import _unwrap_final_json_reply
        self.assertEqual(_unwrap_final_json_reply("你好"), "你好")

    def test_unwrap_pass_through_tool_call(self):
        from xiaohuang.text_interaction_service import _unwrap_final_json_reply
        tc = '{"type":"tool_call","tool_name":"x","arguments":{}}'
        self.assertEqual(_unwrap_final_json_reply(tc), tc)

    def test_unwrap_empty_content(self):
        from xiaohuang.text_interaction_service import _unwrap_final_json_reply
        text = '{"type":"final","content":""}'
        # Empty content → return original (don't return empty string)
        self.assertEqual(_unwrap_final_json_reply(text), text)

    def test_unwrap_non_json(self):
        from xiaohuang.text_interaction_service import _unwrap_final_json_reply
        self.assertEqual(_unwrap_final_json_reply(""), "")
        self.assertEqual(_unwrap_final_json_reply("not json"), "not json")


# ---------------------------------------------------------------------------
# Regression: ContextPack not broken
# ---------------------------------------------------------------------------


class TestToolRuntimeRegression(TestCase):
    def test_context_pack_build_still_works(self):
        """Verify that C5G.3-B ContextPack building still works."""
        try:
            from xiaohuang.conversation_context_engine import build_context_pack_for_turn
            result = build_context_pack_for_turn(None, "test", None)
            self.assertIsInstance(result.context_text, str)
        except Exception as exc:
            self.fail(f"build_context_pack_for_turn raised: {exc}")

    def test_tool_runtime_imports_dont_break_conversation_history(self):
        """Verify that importing tool_runtime doesn't break conversation_history_service."""
        try:
            from xiaohuang.conversation_history_service import ConversationHistoryStore
            self.assertTrue(True)
        except Exception as exc:
            self.fail(f"conversation_history_service import failed: {exc}")

    def test_text_interaction_result_has_tool_fields(self):
        """Verify that TextInteractionResult has the new tool_calls/tool_rounds fields."""
        from xiaohuang.text_interaction_models import TextInteractionResult

        result = TextInteractionResult(
            ok=True, session_id="test",
            tool_calls=[{"name": "test_tool"}],
            tool_rounds=1,
        )
        self.assertEqual(result.tool_calls, [{"name": "test_tool"}])
        self.assertEqual(result.tool_rounds, 1)


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------


class TestDataStructures(TestCase):
    def test_tool_call_creation(self):
        call = ToolCall(
            id="id1", tool_name="test", arguments={"k": "v"},
            source="model", created_at="now", conversation_id="c1", turn_id="t1",
        )
        self.assertEqual(call.id, "id1")
        self.assertEqual(call.tool_name, "test")
        self.assertEqual(call.arguments, {"k": "v"})

    def test_tool_result_creation(self):
        result = ToolResult(
            tool_call_id="id1", tool_name="test", ok=True,
            output="hello", error="", truncated=False, elapsed_ms=10, created_at="now",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "hello")

    def test_tool_permission_decision_defaults(self):
        decision = ToolPermissionDecision(allowed=True)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_confirmation)
        self.assertEqual(decision.risk_level, "readonly")

    def test_tool_turn_record_defaults(self):
        record = ToolTurnRecord(id="t1", conversation_id="c1")
        self.assertEqual(record.status, "")
        self.assertEqual(record.tool_rounds, 0)
        self.assertEqual(record.max_tool_rounds, 2)


# ---------------------------------------------------------------------------
# C5H-B integration smoke: control_panel_conversation_api must not crash
# ---------------------------------------------------------------------------


class TestControlPanelApiSmoke(TestCase):
    """Smoke test: sending '你好' through the control panel API path must not
    return 'send_text_message_error' — the C5H-B tool turn integration must
    not break the plain-text chat path.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "smoke.db"

        from xiaohuang.conversation_history_service import ConversationHistoryStore
        from xiaohuang.text_interaction_session_service import TextInteractionSessionStore
        from xiaohuang.text_task_registry_service import PendingTextTaskRegistry
        from xiaohuang.control_panel_conversation_api import ControlPanelConversationApi

        self._history_store = ConversationHistoryStore(db_path)
        self._session_store = TextInteractionSessionStore()
        self._task_registry = PendingTextTaskRegistry()

        # Use a config file without LLM API key so the tool turn path is NOT
        # entered (we need to verify the plain-text fallback path works).
        config_path = Path(self._tmp.name) / "config.json"
        config_path.write_text(
            '{"llm":{"enabled":false},"assistant":{"persona":"你是小黄。"}}',
            encoding="utf-8",
        )

        self._api = ControlPanelConversationApi(
            history_store=self._history_store,
            session_store=self._session_store,
            task_registry=self._task_registry,
            resolve_config_path=lambda: config_path,
            run_text_turn=run_text_interaction_turn,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_send_hello_does_not_fail(self):
        """Sending '你好' must return ok=true, not '文本消息处理失败'."""
        response = self._api.send_text_message({"text": "你好", "session_id": "cp_smoke"})
        self.assertTrue(response.get("ok"), f"Expected ok=true but got: {response}")
        self.assertNotIn("send_text_message_error", response.get("code", ""))
        self.assertNotIn("文本消息处理失败", response.get("error", ""))

    def test_legacy_turn_with_conversation_id_does_not_crash(self):
        """With a conversation_id present but no LLM key, turn must not crash."""
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult
        from unittest.mock import patch

        with patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            return_value=ReplyPipelineResult("test reply", "rule", None),
        ):
            response = self._api.run_legacy_text_message_turn({
                "text": "你好",
                "session_id": "cp_smoke",
                "conversation_id": "test_conv_123",
            })
        self.assertTrue(response.get("ok"), f"Expected ok=true but got: {response}")
        data = response.get("data") or {}
        self.assertIn("test reply", data.get("reply_text", ""))

    def test_result_helper_accepts_tool_args(self):
        """_result() must accept tool_calls and tool_rounds without TypeError."""
        from xiaohuang.text_interaction_service import _result
        import time

        r = _result(
            True, "sid", time.perf_counter(),
            user_text="hello",
            reply_text="hi",
            reply_source="llm",
            tool_calls=[{"tool_name": "read_project_file_readonly", "ok": True}],
            tool_rounds=1,
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.tool_calls, [{"tool_name": "read_project_file_readonly", "ok": True}])
        self.assertEqual(r.tool_rounds, 1)

    def test_send_text_message_with_conversation_id_ok(self):
        """Full send_text_message with conversation_id, no API key — must not crash."""
        from unittest.mock import patch
        from xiaohuang.reply_pipeline_service import ReplyPipelineResult

        with patch(
            "xiaohuang.text_interaction_service.generate_reply_runtime_result",
            return_value=ReplyPipelineResult("hello reply", "rule", None),
        ):
            response = self._api.send_text_message({
                "text": "你好",
                "conversation_id": "conv_smoke_test",
            })
        self.assertTrue(response.get("ok"), f"Expected ok=true but got: {response}")


# ---------------------------------------------------------------------------
# Readonly tool specs validation
# ---------------------------------------------------------------------------


class TestReadonlyToolSpecs(TestCase):
    def test_all_6_specs_valid(self):
        """Verify all 6 readonly tool specs have valid names and schemas."""
        for spec in READONLY_TOOL_SPECS:
            self.assertTrue(_is_valid_tool_name(spec.name))
            self.assertEqual(spec.risk_level, "readonly")
            self.assertTrue(spec.readonly)
            self.assertIsInstance(spec.input_schema, dict)
            self.assertEqual(spec.input_schema.get("type"), "object")

    def test_no_duplicate_names(self):
        names = [spec.name for spec in READONLY_TOOL_SPECS]
        self.assertEqual(len(names), len(set(names)))

    def test_spec_names_are_lowercase_only(self):
        for spec in READONLY_TOOL_SPECS:
            self.assertTrue(_is_valid_tool_name(spec.name))


# ---------------------------------------------------------------------------
# C5H-C: get_multica_bound_tasks_readonly
# ---------------------------------------------------------------------------


class TestMulticaTool(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "test_multica.db"
        from xiaohuang.conversation_history_service import ConversationHistoryStore
        self._store = ConversationHistoryStore(db_path)
        self._store.create_conversation(title="test conv")
        self._conv_id = self._store.get_or_create_default().id

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_bound_tasks_returns_empty(self):
        output, is_error = execute_readonly_tool(
            "get_multica_bound_tasks_readonly",
            {},
            context={"conversation_id": self._conv_id, "history_store": self._store},
        )
        self.assertFalse(is_error)
        data = json.loads(output)
        self.assertEqual(data["conversation_id"], self._conv_id)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["tasks"], [])

    def test_with_bound_tasks_returns_summary(self):
        self._store.bind_multica_task(
            conversation_id=self._conv_id,
            issue_id="issue_1",
            task_id="task_1",
            title="Test Task",
            run_status="completed",
            review_summary="All tests passed",
        )
        output, is_error = execute_readonly_tool(
            "get_multica_bound_tasks_readonly",
            {},
            context={"conversation_id": self._conv_id, "history_store": self._store},
        )
        self.assertFalse(is_error)
        data = json.loads(output)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["tasks"][0]["task_id"], "task_1")
        self.assertEqual(data["tasks"][0]["title"], "Test Task")
        self.assertEqual(data["tasks"][0]["status"], "completed")

    def test_missing_conversation_id_fails(self):
        output, is_error = execute_readonly_tool(
            "get_multica_bound_tasks_readonly",
            {},
            context={"history_store": self._store},
        )
        self.assertTrue(is_error)
        self.assertIn("conversation_id", output)

    def test_missing_history_store_fails(self):
        output, is_error = execute_readonly_tool(
            "get_multica_bound_tasks_readonly",
            {},
            context={"conversation_id": self._conv_id},
        )
        self.assertTrue(is_error)
        self.assertIn("history_store", output)

    def test_tool_is_readonly(self):
        spec = build_default_registry().get_tool("get_multica_bound_tasks_readonly")
        self.assertIsNotNone(spec)
        self.assertTrue(spec.readonly)
        self.assertEqual(spec.risk_level, "readonly")


# ---------------------------------------------------------------------------
# C5H-C: search_database_brief_readonly
# ---------------------------------------------------------------------------


class TestDatabaseBriefTool(TestCase):
    def test_normal_api_response(self):
        from unittest.mock import patch
        from xiaohuang.agent_handoff.database_brief_client import DatabaseBriefResult

        fake_result = DatabaseBriefResult(
            database_used=True,
            database_status="used",
            brief="UI design rules for glass panels: use backdrop-blur, avoid solid backgrounds",
        )
        with patch(
            "xiaohuang.agent_handoff.database_brief_client.fetch_database_brief",
            return_value=fake_result,
        ):
            output, is_error = execute_readonly_tool(
                "search_database_brief_readonly",
                {"query": "glass panel design rules", "domain": "ui_design"},
            )
        self.assertFalse(is_error)
        data = json.loads(output)
        self.assertTrue(data["ok"])
        self.assertIn("glass", data["brief"])

    def test_api_unavailable(self):
        from unittest.mock import patch
        from xiaohuang.agent_handoff.database_brief_client import DatabaseBriefResult

        fake_result = DatabaseBriefResult(
            database_used=False,
            database_status="unavailable",
            error_message="connection refused",
        )
        with patch(
            "xiaohuang.agent_handoff.database_brief_client.fetch_database_brief",
            return_value=fake_result,
        ):
            output, is_error = execute_readonly_tool(
                "search_database_brief_readonly",
                {"query": "test query"},
            )
        self.assertFalse(is_error)
        data = json.loads(output)
        self.assertFalse(data["ok"])
        self.assertIn("unavailable", data["error"])

    def test_non_json_response(self):
        from unittest.mock import patch

        with patch(
            "xiaohuang.agent_handoff.database_brief_client.fetch_database_brief",
            side_effect=ValueError("database brief response was not valid JSON"),
        ):
            output, is_error = execute_readonly_tool(
                "search_database_brief_readonly",
                {"query": "test"},
            )
        self.assertTrue(is_error)
        self.assertIn("JSON", output)

    def test_empty_query_fails(self):
        output, is_error = execute_readonly_tool(
            "search_database_brief_readonly",
            {"query": ""},
        )
        self.assertTrue(is_error)
        self.assertIn("不能为空", output)

    def test_tool_is_readonly(self):
        spec = build_default_registry().get_tool("search_database_brief_readonly")
        self.assertIsNotNone(spec)
        self.assertTrue(spec.readonly)
        self.assertEqual(spec.risk_level, "readonly")

    def test_fetch_exception_handled(self):
        from unittest.mock import patch

        with patch(
            "xiaohuang.agent_handoff.database_brief_client.fetch_database_brief",
            side_effect=TimeoutError("timed out"),
        ):
            output, is_error = execute_readonly_tool(
                "search_database_brief_readonly",
                {"query": "timeout test", "limit": 3},
            )
        self.assertTrue(is_error)
        self.assertTrue("timed" in output.lower() or "timeout" in output.lower())


# ---------------------------------------------------------------------------
# C5H-C: Registry and integration
# ---------------------------------------------------------------------------


class TestC5HCRegression(TestCase):
    def test_6_tools_registry_order(self):
        registry = build_default_registry()
        names = [t.name for t in registry.list_tools()]
        self.assertEqual(len(names), 6)
        # Original 4 must still be present
        for name in ("get_current_conversation_context", "list_project_files_readonly",
                     "read_project_file_readonly", "search_project_text_readonly"):
            self.assertIn(name, names)

    def test_new_tools_in_registry(self):
        registry = build_default_registry()
        self.assertIsNotNone(registry.get_tool("get_multica_bound_tasks_readonly"))
        self.assertIsNotNone(registry.get_tool("search_database_brief_readonly"))

    def test_env_rejection_still_works(self):
        output, is_error = execute_readonly_tool(
            "read_project_file_readonly",
            {"path": ".env"},
            project_root=Path(r"E:\Projects\xiaohuang"),
        )
        self.assertTrue(is_error)

    def test_path_traversal_still_rejected(self):
        output, is_error = execute_readonly_tool(
            "read_project_file_readonly",
            {"path": "../Windows/System32"},
            project_root=Path(r"E:\Projects\xiaohuang"),
        )
        self.assertTrue(is_error)

    def test_plain_text_chat_not_affected(self):
        """Verify TextInteractionResult still works with new tool fields."""
        from xiaohuang.text_interaction_models import TextInteractionResult
        result = TextInteractionResult(ok=True, session_id="test", reply_text="你好")
        self.assertEqual(result.reply_text, "你好")
        self.assertIsNone(result.tool_calls)


# ---------------------------------------------------------------------------
# C5H-C.1: JSON tool output → natural language formatting
# ---------------------------------------------------------------------------


class TestToolOutputFormatting(TestCase):
    def test_multica_tasks_formatted_naturally(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        output = json.dumps({
            "conversation_id": "abc123",
            "tasks": [{
                "task_id": "de4c05f1abc123def456",
                "title": "Fix login bug",
                "status": "in_progress",
                "summary": "Login page returns 500 on invalid input",
                "agent": "claude-code",
                "messages_count": 69,
                "tool_use_count": 29,
                "tool_result_count": 29,
            }],
            "count": 1,
        })
        result = _try_format_tool_json("get_multica_bound_tasks_readonly", output)
        self.assertIsNot(result, "")
        self.assertIn("1 个 Multica 任务", result)
        self.assertIn("de4c05f1", result)
        self.assertIn("in_progress", result)
        self.assertIn("69 条消息", result)
        self.assertIn("29 次", result)
        self.assertIn("Login page returns 500", result)
        # Must NOT contain raw JSON markers
        self.assertNotIn('"conversation_id"', result)
        self.assertNotIn('"tasks"', result)
        self.assertNotIn('"count"', result)

    def test_multica_empty_tasks(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        output = json.dumps({"conversation_id": "abc123", "tasks": [], "count": 0})
        result = _try_format_tool_json("get_multica_bound_tasks_readonly", output)
        self.assertIn("0 个 Multica 任务", result)
        self.assertNotIn('"conversation_id"', result)

    def test_multica_missing_title_uses_summary(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        output = json.dumps({
            "conversation_id": "abc",
            "tasks": [{"task_id": "t1", "status": "completed", "summary": "Everything passed"}],
            "count": 1,
        })
        result = _try_format_tool_json("get_multica_bound_tasks_readonly", output)
        self.assertIn("t1", result)
        self.assertIn("Everything passed", result)
        self.assertNotIn('"summary"', result)

    def test_database_brief_success_formatted(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        output = json.dumps({
            "ok": True,
            "query": "UI design rules",
            "domain": "ui_design",
            "brief": "Use glass panels with backdrop-blur. Avoid solid backgrounds.",
            "source": "http://127.0.0.1:8765/brief",
        })
        result = _try_format_tool_json("search_database_brief_readonly", output)
        self.assertIn("UI design rules", result)
        self.assertIn("ui_design", result)
        self.assertIn("glass panels", result)
        self.assertNotIn('"brief"', result)
        self.assertNotIn('"ok"', result)
        self.assertNotIn('"source"', result)

    def test_database_brief_unavailable_formatted(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        output = json.dumps({
            "ok": False,
            "error": "database_brief_unavailable",
            "message": "API not reachable",
            "source": "http://127.0.0.1:8765/brief",
        })
        result = _try_format_tool_json("search_database_brief_readonly", output)
        self.assertIn("API not reachable", result)
        self.assertNotIn('"message"', result)

    def test_non_json_passes_through(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        result = _try_format_tool_json("get_multica_bound_tasks_readonly", "plain text result")
        self.assertEqual(result, "")

    def test_unknown_tool_json_not_formatted(self):
        from xiaohuang.tool_runtime.agent_turn_loop import _try_format_tool_json
        result = _try_format_tool_json("unknown_tool", '{"key":"value"}')
        self.assertEqual(result, "")


class TestC5HC1Regression(TestCase):
    def setUp(self):
        self.registry = build_default_registry()
        self.config = ReadonlyToolTurnConfig(max_tool_rounds=2, enable_readonly_tools=True)

    def test_final_json_unwrap_still_works(self):
        """C5H-B.1 regression: final JSON still unwrapped."""
        def llm(text, *, context=""):
            return {"text": json.dumps({"type": "final", "content": "这是最终回复"})}

        result = run_readonly_tool_turn(
            conversation_id="test", user_text="hello",
            context_pack_render="", llm_call_func=llm,
            registry=self.registry, config=self.config,
        )
        self.assertEqual(result.reply_text, "这是最终回复")
        self.assertNotIn('"type"', result.reply_text)

    def test_mixed_tool_call_still_handled(self):
        """C5H-B.2 regression: mixed text + tool_call JSON still extracted."""
        call_count = [0]

        def llm(text, *, context=""):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": '好的。{"type":"tool_call","tool_name":"list_project_files_readonly","arguments":{"relative_dir":"src/xiaohuang/tool_runtime","max_results":3}}'}
            return {"text": json.dumps({"type": "final", "content": "目录已列出"})}

        result = run_readonly_tool_turn(
            conversation_id="test", user_text="list dir",
            context_pack_render="", llm_call_func=llm,
            registry=self.registry, config=self.config,
        )
        self.assertNotIn('"type":"tool_call"', result.reply_text)

    def test_tool_success_empty_final_uses_natural_fallback(self):
        """C5H-B.2 + C5H-C.1: tool success + empty final → natural fallback."""
        call_count = [0]

        def llm(text, *, context=""):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"text": json.dumps({
                    "type": "tool_call",
                    "tool_name": "list_project_files_readonly",
                    "arguments": {"relative_dir": "src/xiaohuang/tool_runtime", "max_results": 3},
                })}
            return {"text": json.dumps({"type": "final", "content": ""})}

        result = run_readonly_tool_turn(
            conversation_id="test", user_text="list",
            context_pack_render="", llm_call_func=llm,
            registry=self.registry, config=self.config,
        )
        self.assertNotIn('"type":', result.reply_text)
        self.assertIn("我已读取目录", result.reply_text)
