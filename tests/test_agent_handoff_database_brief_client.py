from __future__ import annotations

import json
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
    def test_post_json_request_returns_used(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return _FakeResponse('{"brief":"任务历史页面上下文"}')

        result = fetch_database_brief(
            query="任务历史页面",
            domains=["xiaohuang_project", "ui_design", "agent_workflow"],
            opener=opener,
        )

        self.assertTrue(result.database_used)
        self.assertEqual(result.database_status, "used")
        self.assertIn("任务历史", result.brief)
        request = calls[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:8765/brief")
        self.assertIn("application/json", request.get_header("Content-type"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["task"], "任务历史页面")
        self.assertNotIn("query", body)
        self.assertNotIn("domain", body)
        self.assertEqual(body["ui_limit"], 8)
        self.assertEqual(body["workflow_limit"], 5)
        self.assertEqual(body["automation_limit"], 0)
        self.assertEqual(body["backend_limit"], 0)
        self.assertEqual(body["asset_limit"], 0)

    def test_backend_domain_limit_mapping(self):
        captured = {}

        def opener(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _FakeResponse('{"brief":"backend"}')

        fetch_database_brief(query="后端 API registry", domains=["backend"], opener=opener)

        self.assertEqual(captured["ui_limit"], 0)
        self.assertEqual(captured["workflow_limit"], 0)
        self.assertEqual(captured["automation_limit"], 0)
        self.assertEqual(captured["backend_limit"], 6)
        self.assertEqual(captured["asset_limit"], 0)

    def test_browser_automation_domain_limit_mapping(self):
        captured = {}

        def opener(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _FakeResponse('{"brief":"automation"}')

        fetch_database_brief(query="浏览器自动化", domains=["browser_automation"], opener=opener)

        self.assertEqual(captured["automation_limit"], 5)
        self.assertEqual(captured["workflow_limit"], 0)

    def test_empty_domains_default_to_workflow_limit(self):
        captured = {}

        def opener(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _FakeResponse('{"brief":"workflow"}')

        fetch_database_brief(query="整理需求", domains=[], opener=opener)

        self.assertEqual(captured["ui_limit"], 0)
        self.assertEqual(captured["workflow_limit"], 5)
        self.assertEqual(captured["asset_limit"], 0)

    def test_api_unavailable_returns_safe_fallback(self):
        def opener(request, timeout):
            raise TimeoutError("timeout")

        result = fetch_database_brief(
            query="任务历史页面",
            domains=["xiaohuang_project"],
            opener=opener,
        )

        self.assertFalse(result.database_used)
        self.assertEqual(result.database_status, "unavailable")

    def test_external_endpoint_is_forbidden(self):
        calls = []

        result = fetch_database_brief(
            query="x",
            domains=[],
            endpoint="https://example.com/brief",
            opener=lambda request, timeout: calls.append(request) or _FakeResponse("should not call"),
        )

        self.assertFalse(result.database_used)
        self.assertEqual(result.database_status, "forbidden_endpoint")
        self.assertEqual(calls, [])

    def test_lan_endpoint_is_forbidden(self):
        calls = []

        result = fetch_database_brief(
            query="x",
            domains=[],
            endpoint="http://192.168.1.10:8765/brief",
            opener=lambda request, timeout: calls.append(request) or _FakeResponse("should not call"),
        )

        self.assertFalse(result.database_used)
        self.assertEqual(result.database_status, "forbidden_endpoint")
        self.assertEqual(calls, [])

    def test_response_extraction_includes_guidance_and_chunks(self):
        payload = {
            "brief": "这是数据库返回的 brief",
            "guidance": ["先读文件", "不要乱改"],
            "ui_chunks": [
                {
                    "source_name": "premium ui rule",
                    "section": "layout",
                    "content": "界面需要更有层次",
                }
            ],
        }

        result = fetch_database_brief(
            query="UI",
            domains=["ui_design"],
            opener=lambda request, timeout: _FakeResponse(json.dumps(payload, ensure_ascii=False)),
        )

        self.assertTrue(result.database_used)
        self.assertIn("这是数据库返回的 brief", result.brief)
        self.assertIn("先读文件", result.brief)
        self.assertIn("premium ui rule", result.brief)
        self.assertIn("界面需要更有层次", result.brief)

    def test_invalid_json_is_unavailable(self):
        result = fetch_database_brief(
            query="x",
            domains=[],
            opener=lambda request, timeout: _FakeResponse("not json"),
        )

        self.assertFalse(result.database_used)
        self.assertEqual(result.database_status, "unavailable")


if __name__ == "__main__":
    unittest.main()
