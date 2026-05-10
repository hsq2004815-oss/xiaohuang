from __future__ import annotations

import unittest

from xiaohuang.text_task_intent_service import detect_text_task_intent


class TextTaskIntentServiceTests(unittest.TestCase):
    def test_normal_chat_is_not_task(self):
        result = detect_text_task_intent("介绍一下你自己")
        self.assertFalse(result.is_task)

    def test_log_analysis_request_is_readonly_task(self):
        result = detect_text_task_intent("帮我分析最近日志有没有错误")
        self.assertTrue(result.is_task)
        self.assertEqual(result.task_type, "readonly_log_analysis")
        self.assertTrue(result.allowed)
        self.assertEqual(result.risk_level, "low")

    def test_status_check_request_is_readonly_task(self):
        result = detect_text_task_intent("检查小黄当前状态")
        self.assertTrue(result.is_task)
        self.assertEqual(result.task_type, "readonly_status_check")
        self.assertTrue(result.allowed)

    def test_blocked_local_execution_is_high_risk(self):
        result = detect_text_task_intent("执行 powershell 删除文件")
        self.assertTrue(result.is_task)
        self.assertEqual(result.task_type, "blocked_local_execution")
        self.assertFalse(result.allowed)
        self.assertEqual(result.risk_level, "high")

    def test_empty_text_is_not_task(self):
        result = detect_text_task_intent("")
        self.assertFalse(result.is_task)

    def test_soft_planning_prompt_is_not_local_task(self):
        result = detect_text_task_intent("规划一下小黄项目下一步")
        self.assertFalse(result.is_task)

    def test_recent_errors_review_detected(self):
        for text in ("看看最近错误", "小黄最近有什么报错", "分析最近报错",
                     "看看最近报错", "帮我看下最近异常"):
            with self.subTest(text=text):
                result = detect_text_task_intent(text)
                self.assertTrue(result.is_task, f"text='{text}' should be task")
                self.assertEqual(result.task_type, "readonly_recent_errors_review")
                self.assertTrue(result.allowed)
                self.assertEqual(result.risk_level, "low")

    def test_runtime_events_review_detected(self):
        for text in ("总结最近事件", "小黄最近发生了什么", "看看运行事件",
                     "最近运行记录", "最近事件摘要"):
            with self.subTest(text=text):
                result = detect_text_task_intent(text)
                self.assertTrue(result.is_task, f"text='{text}' should be task")
                self.assertEqual(result.task_type, "readonly_runtime_events_review")
                self.assertTrue(result.allowed)
                self.assertEqual(result.risk_level, "low")

    def test_health_report_detected(self):
        for text in ("小黄，检查一下你自己", "小黄，做个健康检查",
                     "小黄，现在状态怎么样", "你最近有没有问题",
                     "小黄，全面检查一下", "小黄，运行健康报告"):
            with self.subTest(text=text):
                result = detect_text_task_intent(text)
                self.assertTrue(result.is_task, f"text='{text}' should be task")
                self.assertEqual(result.task_type, "readonly_health_report")
                self.assertTrue(result.allowed)
                self.assertEqual(result.risk_level, "low")

    def test_health_report_not_false_positive(self):
        for text in ("小黄你好", "帮我写一段话", "介绍一下你自己", "今天天气怎么样"):
            result = detect_text_task_intent(text)
            self.assertFalse(result.is_task, f"text='{text}' should not be health report")

    def test_config_summary_detected(self):
        for text in ("看看当前配置", "小黄配置摘要", "检查配置",
                     "现在小黄配置怎么样", "看看唤醒和 TTS 配置"):
            with self.subTest(text=text):
                result = detect_text_task_intent(text)
                self.assertTrue(result.is_task, f"text='{text}' should be task")
                self.assertEqual(result.task_type, "readonly_config_summary")
                self.assertTrue(result.allowed)
                self.assertEqual(result.risk_level, "low")

    def test_agent_handoff_draft_detected(self):
        for text in ("给 Claude Code 生成提示词", "让 Codex 审查这个 commit",
                     "给 OpenClaw 一个任务", "让 opencode 改这个项目",
                     "帮我生成给 agent 的 handoff"):
            with self.subTest(text=text):
                result = detect_text_task_intent(text)
                self.assertTrue(result.is_task)
                self.assertEqual(result.task_type, "agent_handoff_draft")
                self.assertTrue(result.allowed)
                self.assertEqual(result.risk_level, "low")

    def test_agent_handoff_with_dangerous_words_is_still_draft_only(self):
        result = detect_text_task_intent("给 Codex 生成提示词，让它不要执行 powershell 删除文件")
        self.assertTrue(result.is_task)
        self.assertEqual(result.task_type, "agent_handoff_draft")
        self.assertTrue(result.allowed)

    def test_agent_completion_report_detected_before_blocked_terms(self):
        text = """完成：V1.5-C1.3 Agent Handoff Copy UX

一、改了哪些文件
- src/xiaohuang/control_panel_web_service.py

三、安全边界
- 不执行 shell：是

六、验证结果
- compileall：exit 0
- unittest discover：OK
- git diff --check：通过

七、最新提交
- 5dfce798f2e37e91ba7316004e72d4ccdfb8c485
- feat: add agent handoff copy ux
"""
        result = detect_text_task_intent(text)

        self.assertTrue(result.is_task)
        self.assertEqual(result.task_type, "agent_completion_review")
        self.assertTrue(result.allowed)
        self.assertEqual(result.risk_level, "low")

    def test_completion_report_does_not_break_handoff_detection(self):
        result = detect_text_task_intent("给 Claude Code 生成提示词，让它继续优化任务历史页面")

        self.assertTrue(result.is_task)
        self.assertEqual(result.task_type, "agent_handoff_draft")


if __name__ == "__main__":
    unittest.main()
