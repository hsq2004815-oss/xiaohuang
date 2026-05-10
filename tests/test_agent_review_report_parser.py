from __future__ import annotations

import unittest

from xiaohuang.agent_review.report_parser import is_completion_report, parse_completion_report


SAMPLE_CN_REPORT = """完成：V1.5-C1.3 Agent Handoff Copy UX

一、改了哪些文件
- src/xiaohuang/agent_handoff/handoff_file_service.py
- src/xiaohuang/control_panel_web_service.py
- frontend/control_panel/assets/app.js
- frontend/control_panel/assets/app.js
- TASK_MEMORY.md

二、实现了什么
- 后端读取接口：增加安全读取。
- 前端复制完整提示词。

三、安全边界
- 不启动 Agent：是
- 不执行 shell：是

四、测试覆盖
- handoff_file_service 单元测试。

五、人工验收
- 未做真实窗口点击验收。

六、验证结果
- compileall：exit 0
- unittest discover：1076 tests OK，skipped 1
- control_panel_web.py --help：exit 0
- voice_overlay.py --help：exit 0
- git diff --check：通过
- git status --short：干净

七、最新提交
- 5dfce798f2e37e91ba7316004e72d4ccdfb8c485
- feat: add agent handoff copy ux
"""


class AgentReviewReportParserTests(unittest.TestCase):
    def test_chinese_report_extracts_core_fields(self):
        report = parse_completion_report(SAMPLE_CN_REPORT)

        self.assertTrue(is_completion_report(SAMPLE_CN_REPORT))
        self.assertEqual(report.task_title, "V1.5-C1.3 Agent Handoff Copy UX")
        self.assertEqual(report.commit_hash, "5dfce798f2e37e91ba7316004e72d4ccdfb8c485")
        self.assertEqual(report.commit_message, "feat: add agent handoff copy ux")
        self.assertIn("frontend/control_panel/assets/app.js", report.changed_files)
        self.assertEqual(report.changed_files.count("frontend/control_panel/assets/app.js"), 1)
        self.assertTrue(any("unittest discover" in item for item in report.test_claims))

    def test_english_semistructured_report_is_supported(self):
        text = """Done: Fix task card

Changed files:
- src/xiaohuang/text_task_execution_service.py
- tests/test_text_task_execution_service.py

Implemented:
- Added a readonly review branch.

Safety:
- No shell execution.

Tests:
- compileall exit 0
- unittest OK
- git diff --check OK

Manual acceptance:
- Control panel click path passed.

Commit:
- abc1234 fix: add readonly completion review
"""
        report = parse_completion_report(text)

        self.assertTrue(is_completion_report(text))
        self.assertEqual(report.task_title, "Fix task card")
        self.assertEqual(report.commit_hash, "abc1234")
        self.assertEqual(report.commit_message, "fix: add readonly completion review")
        self.assertIn("tests/test_text_task_execution_service.py", report.changed_files)

    def test_missing_commit_hash_stays_empty(self):
        text = """完成：没有提交的报告

一、改了哪些文件
- src/xiaohuang/example.py

五、验证结果
- compileall：exit 0
- unittest discover：OK
"""
        report = parse_completion_report(text)

        self.assertEqual(report.commit_hash, "")
        self.assertEqual(report.commit_message, "")

    def test_normal_health_chat_is_not_completion_report(self):
        self.assertFalse(is_completion_report("小黄，做个健康检查"))


if __name__ == "__main__":
    unittest.main()
