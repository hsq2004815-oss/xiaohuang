from __future__ import annotations

import json
import unittest

from xiaohuang.multica_integration.models import MulticaCommandResult
from xiaohuang.multica_integration.status_service import get_multica_status


class MulticaIntegrationStatusServiceTests(unittest.TestCase):
    def test_full_success_parses_status(self):
        result = get_multica_status(_runner({
            "version": _ok("version", "multica 0.2.16\n"),
            "daemon_status": _ok("daemon_status", "Daemon:      running (pid 123)\nAgents:      claude, codex, opencode, openclaw\nWorkspaces:  1\n"),
            "agent_list_json": _ok("agent_list_json", json.dumps([{"name": "Codex", "status": "idle"}])),
            "workspace_list_json": _ok("workspace_list_json", json.dumps([{"id": "ws1", "name": "hhh-ai-lab"}])),
        }))

        self.assertTrue(result.ok)
        self.assertTrue(result.installed)
        self.assertEqual(result.version, "multica 0.2.16")
        self.assertTrue(result.daemon_running)
        self.assertIn("running", result.daemon_summary)
        self.assertEqual(result.agents, ("claude", "codex", "opencode", "openclaw"))
        self.assertEqual(result.workspace_summary, "hhh-ai-lab")
        self.assertEqual(result.agent_details[0].name, "Codex")

    def test_workspace_json_unknown_flag_falls_back_to_table(self):
        calls = []

        def runner(key):
            calls.append(key)
            values = {
                "version": _ok("version", "multica 0.2.16\n"),
                "daemon_status": _ok("daemon_status", "Daemon:      running\nAgents:      claude\n"),
                "agent_list_json": _ok("agent_list_json", "[]"),
                "workspace_list_json": _fail("workspace_list_json", "unknown flag: --output"),
                "workspace_list_table": _ok("workspace_list_table", "ID  NAME\nabc hhh-ai-lab\n"),
            }
            return values[key]

        result = get_multica_status(runner)

        self.assertIn("workspace_list_table", calls)
        self.assertIn("fallback", " ".join(result.warnings))
        self.assertIn("1 workspace", result.workspace_summary)

    def test_daemon_stopped_is_not_running(self):
        result = get_multica_status(_runner({
            "version": _ok("version", "multica 0.2.16\n"),
            "daemon_status": _ok("daemon_status", "Daemon:      stopped\nAgents:      claude\n"),
            "agent_list_json": _ok("agent_list_json", "[]"),
            "workspace_list_json": _ok("workspace_list_json", "[]"),
        }))

        self.assertTrue(result.ok)
        self.assertFalse(result.daemon_running)
        self.assertEqual(result.daemon_summary, "stopped")

    def test_agent_json_parse_failure_warns_without_crashing(self):
        result = get_multica_status(_runner({
            "version": _ok("version", "multica 0.2.16\n"),
            "daemon_status": _ok("daemon_status", "Daemon:      running\nAgents:      claude\n"),
            "agent_list_json": _ok("agent_list_json", "{bad json"),
            "workspace_list_json": _ok("workspace_list_json", "[]"),
        }))

        self.assertTrue(result.ok)
        self.assertIn("agent list json parse failed", result.warnings)

    def test_multica_not_found_returns_installed_false(self):
        result = get_multica_status(_runner({
            "version": MulticaCommandResult(False, "version", error_code="multica_not_found", message="missing"),
        }))

        self.assertFalse(result.ok)
        self.assertFalse(result.installed)
        self.assertEqual(result.error_code, "multica_not_found")

    def test_single_command_failure_becomes_warning(self):
        result = get_multica_status(_runner({
            "version": _ok("version", "multica 0.2.16\n"),
            "daemon_status": _fail("daemon_status", "daemon down"),
            "agent_list_json": _ok("agent_list_json", '[{"name":"Codex"}]'),
            "workspace_list_json": _ok("workspace_list_json", "[]"),
        }))

        self.assertTrue(result.ok)
        self.assertFalse(result.daemon_running)
        self.assertIn("daemon_status", " ".join(result.warnings))
        self.assertEqual(result.agents, ("Codex",))


def _runner(results):
    def run(key):
        return results.get(key, _fail(key, "not configured"))
    return run


def _ok(key, stdout):
    return MulticaCommandResult(True, key, returncode=0, stdout=stdout, message="ok")


def _fail(key, stderr):
    return MulticaCommandResult(False, key, returncode=2, stderr=stderr, error_code="multica_nonzero_exit", message=stderr)


if __name__ == "__main__":
    unittest.main()
