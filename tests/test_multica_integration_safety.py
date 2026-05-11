from __future__ import annotations

import unittest

from xiaohuang.multica_integration.safety import (
    BLOCKED_COMMAND_KEYS,
    get_command_argv,
    is_allowed_command,
    is_blocked_command,
)


class MulticaIntegrationSafetyTests(unittest.TestCase):
    def test_allows_only_readonly_status_commands(self):
        for key in (
            "version",
            "daemon_status",
            "agent_list_json",
            "workspace_list_json",
            "workspace_list_table",
        ):
            self.assertTrue(is_allowed_command(key), key)
            self.assertGreater(len(get_command_argv(key)), 1)

    def test_rejects_state_changing_command_keys(self):
        for key in (
            "issue_create",
            "issue_assign",
            "issue_runs",
            "issue_run_messages",
            "daemon_restart",
            "daemon_stop",
        ):
            self.assertIn(key, BLOCKED_COMMAND_KEYS)
            self.assertTrue(is_blocked_command(key), key)
            self.assertFalse(is_allowed_command(key), key)
            with self.assertRaises(ValueError):
                get_command_argv(key)

    def test_rejects_unknown_command_key(self):
        self.assertFalse(is_allowed_command("powershell -c whoami"))
        self.assertFalse(is_allowed_command("unknown"))
        with self.assertRaises(ValueError):
            get_command_argv("unknown")


if __name__ == "__main__":
    unittest.main()

