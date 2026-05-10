from __future__ import annotations

import unittest

from xiaohuang.agent_handoff.database_brief_client import fetch_database_brief


class _FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")
        self.closed = False

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        self.closed = True


class AgentHandoffDatabaseBriefClientTests(unittest.TestCase):
    def test_api_available_returns_used(self):
        calls = []

        def opener(url, timeout):
            calls.append((url, timeout))
            return _FakeResponse('{"brief":"任务历史页面上下文"}')

        result = fetch_database_brief(
            query="任务历史页面",
            domains=["xiaohuang_project"],
            opener=opener,
        )

        self.assertTrue(result.database_used)
        self.assertEqual(result.database_status, "used")
        self.assertIn("任务历史", result.brief)
        self.assertIn("127.0.0.1", calls[0][0])

    def test_api_unavailable_returns_safe_fallback(self):
        def opener(url, timeout):
            raise TimeoutError("timeout")

        result = fetch_database_brief(
            query="任务历史页面",
            domains=["xiaohuang_project"],
            opener=opener,
        )

        self.assertFalse(result.database_used)
        self.assertEqual(result.database_status, "unavailable")

    def test_external_endpoint_is_forbidden(self):
        result = fetch_database_brief(
            query="x",
            domains=[],
            endpoint="https://example.com/brief",
            opener=lambda url, timeout: _FakeResponse("should not call"),
        )

        self.assertFalse(result.database_used)
        self.assertEqual(result.database_status, "forbidden_endpoint")


if __name__ == "__main__":
    unittest.main()
