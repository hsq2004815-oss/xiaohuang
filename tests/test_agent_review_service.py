from __future__ import annotations

import unittest

from xiaohuang.agent_review.service import review_agent_completion_report


SAMPLE_REPORT = """完成：V1.5-C1.3 Agent Handoff Copy UX

一、改了哪些文件
- src/xiaohuang/control_panel_web_service.py
- frontend/control_panel/assets/app.js
- tests/test_control_panel_web_service.py

二、实现了什么
- 增加复制完整提示词能力。

三、安全边界
- 不启动 Agent：是
- 不执行 shell：是

五、人工验收
- 真实窗口点击通过。

六、验证结果
- compileall：exit 0
- unittest discover：1076 tests OK
- git diff --check：通过

七、最新提交
- 5dfce798f2e37e91ba7316004e72d4ccdfb8c485
- feat: add agent handoff copy ux
"""


class AgentReviewServiceTests(unittest.TestCase):
    def test_full_report_returns_safe_review(self):
        review = review_agent_completion_report(SAMPLE_REPORT)

        self.assertTrue(review.ok)
        self.assertIn(review.verdict, {"keep", "needs_review"})
        self.assertIn("建议保留", review.summary)
        self.assertIn("commit：5dfce798f2e37e91ba7316004e72d4ccdfb8c485", review.safe_details_excerpt)
        self.assertIn("风险点", review.safe_details_excerpt)
        self.assertNotIn("完成：V1.5-C1.3", review.safe_details_excerpt)

    def test_empty_report_is_insufficient_failure(self):
        review = review_agent_completion_report("")

        self.assertFalse(review.ok)
        self.assertEqual(review.verdict, "insufficient")
        self.assertEqual(review.error_message, "empty_report")

    def test_dangerous_report_is_reject(self):
        review = review_agent_completion_report(
            SAMPLE_REPORT + "\n补充：我打开终端执行 powershell 修改 PATH。"
        )

        self.assertTrue(review.ok)
        self.assertEqual(review.verdict, "reject")
        self.assertIn("不建议保留", review.summary)


if __name__ == "__main__":
    unittest.main()
