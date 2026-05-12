from __future__ import annotations

import unittest

from xiaohuang.multica_integration.safety import (
    ALLOWED_ASSIGN_AGENTS,
    BLOCKED_COMMAND_KEYS,
    CONFIRMED_ISSUE_ASSIGN_KEY,
    CONFIRMED_ISSUE_CREATE_KEY,
    CONFIRMED_ISSUE_RUNS_KEY,
    CONFIRMED_RUN_MESSAGES_KEY,
    ISSUE_CREATE_CONFIRMATION_TEXT,
    build_issue_assign_argv,
    build_issue_create_argv,
    build_issue_runs_argv,
    build_run_messages_argv,
    can_assign_issue,
    can_create_issue,
    expected_issue_assign_confirmation,
    get_command_argv,
    is_allowed_confirmed_argv,
    is_allowed_command,
    is_blocked_command,
    is_safe_issue_id,
    is_safe_task_id,
    is_supported_assign_agent,
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

    def test_confirmed_issue_create_uses_separate_gate(self):
        self.assertFalse(is_allowed_command("issue_create"))
        self.assertFalse(can_create_issue(confirmed=False, confirmation_text=ISSUE_CREATE_CONFIRMATION_TEXT))
        self.assertFalse(can_create_issue(confirmed=True, confirmation_text="CREATE"))
        self.assertTrue(can_create_issue(confirmed=True, confirmation_text=ISSUE_CREATE_CONFIRMATION_TEXT))

    def test_build_issue_create_argv_requires_confirmation_and_omits_assignee(self):
        with self.assertRaises(ValueError):
            build_issue_create_argv(
                title="C5E test",
                description="desc",
                confirmed=False,
                confirmation_text=ISSUE_CREATE_CONFIRMATION_TEXT,
            )

        argv = build_issue_create_argv(
            title="C5E test",
            description="desc",
            confirmed=True,
            confirmation_text=ISSUE_CREATE_CONFIRMATION_TEXT,
            priority="normal",
            project="sample",
        )

        self.assertEqual(argv[:3], ("multica", "issue", "create"))
        self.assertIn("--title", argv)
        self.assertIn("--description", argv)
        self.assertIn("--priority", argv)
        self.assertIn("--project", argv)
        self.assertIn("--output", argv)
        self.assertNotIn("--assignee", argv)
        self.assertTrue(is_allowed_confirmed_argv(CONFIRMED_ISSUE_CREATE_KEY, argv))

    def test_confirmed_argv_rejects_unknown_or_dangerous_commands(self):
        self.assertFalse(is_allowed_confirmed_argv("unknown", ("multica", "issue", "create")))
        self.assertFalse(is_allowed_confirmed_argv(CONFIRMED_ISSUE_CREATE_KEY, ("multica", "issue", "assign", "123")))
        self.assertFalse(is_allowed_confirmed_argv(
            CONFIRMED_ISSUE_CREATE_KEY,
            ("multica", "issue", "create", "--title", "t", "--description", "d", "--assignee", "claude", "--output", "json"),
        ))

    def test_confirmed_issue_assign_uses_separate_gate_and_agent_whitelist(self):
        self.assertFalse(is_allowed_command("issue_assign"))
        self.assertEqual(ALLOWED_ASSIGN_AGENTS, ("claude", "codex", "opencode", "openclaw"))
        for agent in ALLOWED_ASSIGN_AGENTS:
            self.assertTrue(is_supported_assign_agent(agent))
        for agent in ("shell", "powershell", "cmd", "python", "node", "agent:f73a741e", "claude;whoami"):
            self.assertFalse(is_supported_assign_agent(agent))
        self.assertEqual(expected_issue_assign_confirmation("4e344c98", "claude"), "ASSIGN 4e344c98 TO claude")
        self.assertFalse(can_assign_issue(issue_id="4e344c98", agent="claude", confirmed=False, confirmation_text="ASSIGN 4e344c98 TO claude"))
        self.assertFalse(can_assign_issue(issue_id="4e344c98", agent="claude", confirmed=True, confirmation_text="ASSIGN HHH-18 TO claude"))
        self.assertTrue(can_assign_issue(issue_id="4e344c98", agent="claude", confirmed=True, confirmation_text="ASSIGN 4e344c98 TO claude"))

    def test_build_issue_assign_argv_rejects_dangerous_values(self):
        for issue_id in (
            "",
            "78480e61;rm",
            "4e344c98;whoami",
            "HHH-19 && cmd",
            "E:\\Projects\\xiaohuang",
            "http://example.com",
            "https://example.com",
            "HHH 18",
            "带空格",
        ):
            self.assertFalse(is_safe_issue_id(issue_id), issue_id)
        for issue_id in ("4e344c98", "78480e61", "HHH-18", "HHH-19"):
            self.assertTrue(is_safe_issue_id(issue_id), issue_id)
        with self.assertRaises(ValueError):
            build_issue_assign_argv(
                issue_id="4e344c98",
                agent="powershell",
                confirmed=True,
                confirmation_text="ASSIGN 4e344c98 TO powershell",
            )
        with self.assertRaises(ValueError):
            build_issue_assign_argv(
                issue_id="4e344c98",
                agent="claude",
                confirmed=True,
                confirmation_text="ASSIGN HHH-18 TO claude",
            )

    def test_build_issue_assign_argv_allows_only_confirmed_assign_shape(self):
        argv = build_issue_assign_argv(
            issue_id="4e344c98",
            agent="claude",
            confirmed=True,
            confirmation_text="ASSIGN 4e344c98 TO claude",
        )

        self.assertEqual(argv, ("multica", "issue", "assign", "4e344c98", "--to", "claude", "--output", "json"))
        self.assertTrue(is_allowed_confirmed_argv(CONFIRMED_ISSUE_ASSIGN_KEY, argv))
        self.assertFalse(is_allowed_confirmed_argv(CONFIRMED_ISSUE_ASSIGN_KEY, ("multica", "issue", "runs", "4e344c98")))
        self.assertFalse(is_allowed_confirmed_argv(CONFIRMED_ISSUE_ASSIGN_KEY, ("multica", "issue", "assign", "4e344c98", "--to", "shell", "--output", "json")))

    def test_issue_runs_not_in_blocked_keys(self):
        self.assertNotIn("issue_runs", BLOCKED_COMMAND_KEYS)
        self.assertNotIn("issue_run_messages", BLOCKED_COMMAND_KEYS)

    def test_build_issue_runs_argv_rejects_dangerous_issue_id(self):
        for issue_id in ("", "78480e61;rm", "HHH-19 && cmd", "http://example.com"):
            with self.subTest(issue_id=issue_id):
                with self.assertRaises(ValueError):
                    build_issue_runs_argv(issue_id=issue_id)

    def test_build_issue_runs_argv_allows_safe_issue_id(self):
        argv = build_issue_runs_argv(issue_id="HHH-19")
        self.assertEqual(argv, ("multica", "issue", "runs", "HHH-19", "--output", "json"))
        self.assertTrue(is_allowed_confirmed_argv(CONFIRMED_ISSUE_RUNS_KEY, argv))

    def test_build_issue_runs_argv_allows_hex_issue_id(self):
        argv = build_issue_runs_argv(issue_id="78480e61")
        self.assertTrue(is_allowed_confirmed_argv(CONFIRMED_ISSUE_RUNS_KEY, argv))

    def test_build_run_messages_argv_rejects_dangerous_task_id(self):
        for task_id in ("", "t1;rm", "t1 && cmd", "t 1"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(ValueError):
                    build_run_messages_argv(task_id=task_id)

    def test_build_run_messages_argv_allows_safe_task_id(self):
        argv = build_run_messages_argv(task_id="t1")
        self.assertEqual(argv, ("multica", "issue", "run-messages", "t1", "--output", "json"))
        self.assertTrue(is_allowed_confirmed_argv(CONFIRMED_RUN_MESSAGES_KEY, argv))

    def test_runs_argv_not_allowed_as_assign(self):
        runs_argv = build_issue_runs_argv(issue_id="4e344c98")
        self.assertFalse(is_allowed_confirmed_argv(CONFIRMED_ISSUE_ASSIGN_KEY, runs_argv))

    def test_safe_task_id_same_as_safe_issue_id_for_hex(self):
        self.assertTrue(is_safe_task_id("78480e61"))
        self.assertTrue(is_safe_task_id("HHH-19"))
        self.assertTrue(is_safe_task_id("t1-a2b3c4d5"))
        self.assertFalse(is_safe_task_id(""))
        self.assertFalse(is_safe_task_id("t1;whoami"))

    def test_runs_argv_not_shell_true(self):
        argv = build_issue_runs_argv(issue_id="HHH-19")
        self.assertIsInstance(argv, tuple)
        self.assertNotIn("shell", argv)

    def test_run_messages_argv_not_rerun(self):
        argv = build_run_messages_argv(task_id="t1")
        self.assertNotIn("rerun", argv)
        self.assertNotIn("assign", argv)
        self.assertNotIn("create", argv)


if __name__ == "__main__":
    unittest.main()
