from __future__ import annotations

import unittest

from xiaohuang.agent_review.models import AgentCompletionReport
from xiaohuang.agent_review.risk_rules import evaluate_completion_report


def _report(**kwargs) -> AgentCompletionReport:
    defaults = {
        "raw_text": "完成：Demo\n验证结果 compileall exit 0 unittest OK git diff --check 通过",
        "task_title": "Demo",
        "changed_files": ["src/xiaohuang/demo.py", "tests/test_demo.py"],
        "implemented_items": ["实现 Demo"],
        "safety_claims": ["不启动 Agent", "不执行 shell"],
        "test_claims": ["compileall exit 0", "unittest OK", "git diff --check 通过"],
        "manual_acceptance": ["控制面板真实窗口点击通过"],
        "commit_hash": "abc1234",
        "commit_message": "fix: demo",
        "agent_name": "Codex",
    }
    defaults.update(kwargs)
    return AgentCompletionReport(**defaults)


class AgentReviewRiskRulesTests(unittest.TestCase):
    def test_complete_report_can_keep(self):
        review = evaluate_completion_report(_report())

        self.assertEqual(review.verdict, "keep")
        self.assertEqual(review.confidence, "high")
        self.assertIn("compileall", review.verification_summary)

    def test_missing_commit_is_insufficient(self):
        review = evaluate_completion_report(_report(commit_hash=""))

        self.assertEqual(review.verdict, "insufficient")
        self.assertTrue(any("commit hash" in item for item in review.risk_points))

    def test_test_failure_rejects(self):
        review = evaluate_completion_report(_report(
            raw_text="完成：Demo\n验证结果\n- unittest FAILED\n- git diff --check 通过",
            test_claims=["unittest FAILED", "git diff --check 通过"],
        ))

        self.assertEqual(review.verdict, "reject")
        self.assertTrue(any("failed" in item.lower() or "失败" in item for item in review.risk_points))

    def test_shell_or_agent_launch_rejects(self):
        review = evaluate_completion_report(_report(
            raw_text="完成：Demo\n我打开终端执行 powershell，并启动 Agent 完成任务。",
        ))

        self.assertEqual(review.verdict, "reject")
        self.assertTrue(any("shell" in item or "Agent" in item for item in review.risk_points))

    def test_missing_manual_acceptance_needs_review(self):
        review = evaluate_completion_report(_report(manual_acceptance=[]))

        self.assertEqual(review.verdict, "needs_review")
        self.assertTrue(any("人工验收" in item for item in review.risk_points))

    def test_negative_safety_claim_does_not_reject(self):
        review = evaluate_completion_report(_report(
            raw_text="完成：Demo\n安全边界：不执行 shell，不启动 Agent。\n验证结果 compileall exit 0 unittest OK git diff --check 通过",
            safety_claims=["不执行 shell", "不启动 Agent"],
        ))

        self.assertNotEqual(review.verdict, "reject")


if __name__ == "__main__":
    unittest.main()
