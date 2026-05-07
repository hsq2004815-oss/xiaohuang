"""test_capability_router.py — tests for the V1.4-A capability router."""

from __future__ import annotations

import unittest
from pathlib import Path

from xiaohuang.capabilities.local_commands.models import (
    CapabilityDefinition,
    LocalCommandIntent,
    LocalCommandResult,
    RouteDecision,
)
from xiaohuang.capabilities.local_commands.registry import get_capability, get_registry
from xiaohuang.capabilities.local_commands.service import (
    execute_capability,
    route_capability,
)


class RouteCapabilityWhitelistTests(unittest.TestCase):
    """Whitelisted capabilities should be matched and executable."""

    def test_open_logs_folder_routes(self):
        for text in ["打开日志目录", "打开日志", "日志目录", "打开logs"]:
            with self.subTest(text=text):
                d = route_capability(text)
                self.assertTrue(d.is_task_request)
                self.assertTrue(d.can_execute)
                self.assertEqual(d.command, "open_logs_folder")

    def test_run_preflight_check_routes(self):
        for text in ["运行启动前检查", "启动前检查", "检查环境", "系统检查"]:
            with self.subTest(text=text):
                d = route_capability(text)
                self.assertTrue(d.is_task_request)
                self.assertTrue(d.can_execute)
                self.assertEqual(d.command, "run_preflight_check")

    def test_get_status_routes(self):
        for text in ["查看当前状态", "小黄状态", "查看状态", "运行状态"]:
            with self.subTest(text=text):
                d = route_capability(text)
                self.assertTrue(d.is_task_request)
                self.assertTrue(d.can_execute)
                self.assertEqual(d.command, "get_status")

    def test_export_diagnostics_routes(self):
        for text in ["导出诊断", "生成诊断", "诊断报告", "导出报告"]:
            with self.subTest(text=text):
                d = route_capability(text)
                self.assertTrue(d.is_task_request)
                self.assertTrue(d.can_execute)
                self.assertEqual(d.command, "export_diagnostics")

    def test_open_control_panel_routes(self):
        for text in ["打开控制面板", "显示控制面板", "控制中心", "打开控制中心"]:
            with self.subTest(text=text):
                d = route_capability(text)
                self.assertTrue(d.is_task_request)
                self.assertTrue(d.can_execute)
                self.assertEqual(d.command, "open_control_panel")


class RouteCapabilityDenyTests(unittest.TestCase):
    """High-risk or non-whitelisted tool requests must be denied."""

    def test_browser_denied(self):
        d = route_capability("帮我打开浏览器")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)
        self.assertEqual(d.reason, "not_allowed")

    def test_download_denied(self):
        d = route_capability("帮我下载资料")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_wechat_denied(self):
        d = route_capability("帮我发微信给张三")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_powershell_denied(self):
        d = route_capability("帮我执行 powershell 命令")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_delete_file_denied(self):
        d = route_capability("删除文件 C:\\temp.txt")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_shell_command_denied(self):
        d = route_capability("帮我执行 cmd 命令")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_opencode_denied(self):
        d = route_capability("帮我用 opencode 写代码")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_arbitrary_shell_denied(self):
        d = route_capability("用 shell 运行 rm -rf /")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_taskkill_denied(self):
        d = route_capability("taskkill python")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)

    def test_shutdown_denied(self):
        d = route_capability("shutdown 电脑")
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)


class RouteCapabilityNotTaskTests(unittest.TestCase):
    """Normal chat should not be classified as task requests."""

    def test_greeting_not_task(self):
        d = route_capability("你好")
        self.assertFalse(d.is_task_request)
        self.assertEqual(d.reason, "not_task")

    def test_question_not_task(self):
        d = route_capability("今天天气怎么样")
        self.assertFalse(d.is_task_request)

    def test_empty_not_task(self):
        d = route_capability("")
        self.assertFalse(d.is_task_request)

    def test_chat_not_task(self):
        d = route_capability("你是谁")
        self.assertFalse(d.is_task_request)


class CapabilityExecutionTests(unittest.TestCase):
    """Execute capability via decision."""

    def test_execute_valid_decision(self):
        intent = LocalCommandIntent(
            command="open_logs_folder",
            original_text="打开日志目录",
            matched_phrase="打开日志",
        )
        decision = RouteDecision(
            is_task_request=True,
            can_execute=True,
            command="open_logs_folder",
            reason="capability_matched",
            message="匹配到能力",
            intent=intent,
        )
        result = execute_capability(decision, project_root=Path(__file__).parents[1])
        self.assertTrue(result.ok)
        self.assertTrue(result.executed)
        self.assertEqual(result.command, "open_logs_folder")

    def test_execute_cannot_execute_decision(self):
        decision = RouteDecision(
            is_task_request=True,
            can_execute=False,
            reason="not_allowed",
            message="不能执行该操作",
        )
        result = execute_capability(decision)
        self.assertFalse(result.ok)
        self.assertFalse(result.executed)
        self.assertEqual(result.error_code, "cannot_execute")

    def test_execute_unknown_command(self):
        decision = RouteDecision(
            is_task_request=True,
            can_execute=True,
            command="nonexistent_capability",
            reason="capability_matched",
        )
        result = execute_capability(decision)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "capability_unavailable")


class CapabilityHandlerErrorTests(unittest.TestCase):
    """Capability handler exceptions must not crash the router."""

    def test_handler_exception_returns_structured_error(self):
        def raise_handler(**kw):
            raise RuntimeError("BOOM")

        broken = CapabilityDefinition(
            name="broken_cap",
            description="broken",
            risk="low",
            enabled=True,
            handler=raise_handler,
        )
        try:
            broken.handler()
            self.fail("Expected RuntimeError")
        except RuntimeError:
            pass

    def test_execute_capability_catches_handler_errors(self):
        def raise_handler(**kw):
            raise RuntimeError("BOOM")

        from xiaohuang.capabilities.local_commands.registry import _registry
        # Save and restore
        old_registry = _registry
        try:
            broken = CapabilityDefinition(
                name="test_broken_cap",
                description="broken",
                risk="low",
                enabled=True,
                handler=raise_handler,
            )
            import xiaohuang.capabilities.local_commands.registry as reg_mod
            reg_mod._registry = [broken]
            decision = RouteDecision(
                is_task_request=True,
                can_execute=True,
                command="test_broken_cap",
                reason="capability_matched",
            )
            result = execute_capability(decision)
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "handler_exception")
            self.assertIn("BOOM", result.message)
        finally:
            import xiaohuang.capabilities.local_commands.registry as reg_mod
            reg_mod._registry = old_registry


class RegistryTests(unittest.TestCase):
    def test_registry_has_five_capabilities(self):
        reg = get_registry()
        names = {c.name for c in reg}
        self.assertEqual(len(names), 5)
        self.assertIn("open_logs_folder", names)
        self.assertIn("run_preflight_check", names)
        self.assertIn("get_status", names)
        self.assertIn("export_diagnostics", names)
        self.assertIn("open_control_panel", names)

    def test_get_valid_capability(self):
        cap = get_capability("open_logs_folder")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.risk, "low")
        self.assertTrue(cap.enabled)

    def test_get_nonexistent_capability(self):
        cap = get_capability("do_dangerous_thing")
        self.assertIsNone(cap)


class RouteDecisionModelTests(unittest.TestCase):
    def test_decision_frozen(self):
        d = RouteDecision(
            is_task_request=True,
            can_execute=False,
            reason="not_allowed",
            message="denied",
        )
        self.assertTrue(d.is_task_request)
        self.assertFalse(d.can_execute)
        self.assertTrue(d.requires_confirmation is False)

    def test_decision_with_intent(self):
        intent = LocalCommandIntent(command="test", original_text="hello")
        d = RouteDecision(
            is_task_request=True,
            can_execute=True,
            command="test",
            reason="matched",
            message="ok",
            intent=intent,
        )
        self.assertEqual(d.intent.command, "test")


class BackwardCompatTests(unittest.TestCase):
    """Old task_router_service.route_task must still work."""

    def test_old_route_task_greeting(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("你好")
        self.assertFalse(result.is_task_request)

    def test_old_route_task_browser(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("帮我打开浏览器")
        self.assertTrue(result.is_task_request)
        self.assertFalse(result.can_execute)
        self.assertEqual(result.reason, "not_implemented")

    def test_old_route_task_opencode(self):
        from xiaohuang.task_router_service import route_task
        result = route_task("帮我用 opencode 写代码")
        self.assertTrue(result.is_task_request)


class PipelineIntegrationTests(unittest.TestCase):
    """reply_pipeline_service integrates capability router."""

    def test_pipeline_handles_capability_command(self):
        from xiaohuang.reply_pipeline_service import (
            ReplyPipelineConfig,
            generate_reply_pipeline_result,
        )
        config = ReplyPipelineConfig(
            enable_llm=False,
            enable_tts=False,
        )
        result = generate_reply_pipeline_result("打开日志目录", config)
        self.assertEqual(result.reply_source, "capability")
        self.assertIn("日志目录", result.reply_text)

    def test_pipeline_denies_dangerous_request(self):
        from xiaohuang.reply_pipeline_service import (
            ReplyPipelineConfig,
            generate_reply_pipeline_result,
        )
        config = ReplyPipelineConfig(
            enable_llm=False,
            enable_tts=False,
        )
        result = generate_reply_pipeline_result("帮我删除文件", config)
        self.assertEqual(result.reply_source, "tool_denied")
        self.assertIn("白名单", result.reply_text)

    def test_pipeline_normal_chat_still_uses_rule(self):
        from xiaohuang.reply_pipeline_service import (
            ReplyPipelineConfig,
            generate_reply_pipeline_result,
        )
        config = ReplyPipelineConfig(
            enable_llm=False,
            enable_tts=False,
        )
        result = generate_reply_pipeline_result("你好", config)
        self.assertEqual(result.reply_source, "rule")

    def test_pipeline_llm_still_works(self):
        from xiaohuang.reply_pipeline_service import (
            ReplyPipelineConfig,
            generate_reply_pipeline_result,
        )
        from xiaohuang.llm_reply_service import LlmReplyConfig, ReplyGenerationResult

        config = ReplyPipelineConfig(
            enable_llm=True,
            enable_tts=False,
            llm_config=LlmReplyConfig(
                api_key="sk-test",
                base_url="https://api.test",
                model="test-model",
                timeout_seconds=15,
            ),
        )
        def fake_llm(text, **_kw):
            return ReplyGenerationResult("你好，我是小黄。", "llm")
        result = generate_reply_pipeline_result(
            "你好",
            config,
            llm_reply_func=fake_llm,
        )
        self.assertEqual(result.reply_source, "llm")

    def test_pipeline_capability_no_llm_called(self):
        from xiaohuang.reply_pipeline_service import (
            ReplyPipelineConfig,
            generate_reply_pipeline_result,
        )
        config = ReplyPipelineConfig(
            enable_llm=True,
            enable_tts=False,
            llm_config=None,
        )
        result = generate_reply_pipeline_result("打开日志目录", config)
        self.assertEqual(result.reply_source, "capability")


if __name__ == "__main__":
    unittest.main()
