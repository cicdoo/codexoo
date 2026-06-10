# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
"""Pin how the Codex runner wires a turn: `codex exec --json` with a read-only
sandbox, the per-session bridge token injected via -c MCP overrides (never the
web tools, which the bridge does not serve), and resume on later turns."""
import sys
import tempfile

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "codexoo")
class TestRunnerArgv(TransactionCase):

    def setUp(self):
        super().setUp()
        self.runner = self.env["codexoo.runner"]
        self.scratch = tempfile.mkdtemp(prefix="codexoo_test_")

    def _ctx(self, allowed_tools, is_first=True, thread_id=""):
        return {
            "scratch": self.scratch,
            "python_bin": sys.executable,
            "cli_path": "/usr/local/bin/codex",
            "model": "gpt-5-codex",
            "allowed_tools": allowed_tools,
            "web_enabled": bool(set(allowed_tools) & {"web_fetch", "web_search"}),
            "identity": "--- ODOO USER CONTEXT ---",
            "is_first": is_first,
            "codex_thread_id": thread_id,
            "prompt": "hi",
            "base_url": "http://127.0.0.1:8069",
            "target_db": "testdb",
            "routing_sid": "sid",
            "token": "tok-123",
            "session_id": 1,
            "bridge_script": "/tmp/bridge.py",
            "excluded_models": [],
        }

    def test_first_turn_argv_is_read_only_sandbox_exec(self):
        argv = self.runner._build_argv(self._ctx(["orm_read"]), "/tmp/last.txt")
        self.assertEqual(argv[:2], ["/usr/local/bin/codex", "exec"])
        self.assertNotIn("resume", argv)
        self.assertIn("--json", argv)
        self.assertIn("--skip-git-repo-check", argv)
        # MCP tool calls are auto-cancelled in exec mode unless approvals+sandbox
        # are bypassed (the process is container-isolated; see _build_argv).
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
        # Shell tool is disabled so the agent has no local execution (no psql /
        # file access) — only the gated Odoo MCP tools remain.
        self.assertEqual(argv[argv.index("--disable") + 1], "shell_tool")
        self.assertNotIn("--ask-for-approval", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5-codex")
        # The prompt is fed via stdin, so argv ends with the "-" sentinel.
        self.assertEqual(argv[-1], "-")

    def test_resume_turn_passes_thread_id(self):
        argv = self.runner._build_argv(
            self._ctx(["orm_read"], is_first=False, thread_id="th_42"),
            "/tmp/last.txt")
        self.assertEqual(argv[1], "exec")
        # exec OPTIONS must precede the resume subcommand; -C/-m etc. before it.
        self.assertLess(argv.index("-C"), argv.index("resume"))
        # resume is followed by <thread_id>, then the "-" stdin sentinel.
        self.assertEqual(argv[argv.index("resume") + 1], "th_42")
        self.assertEqual(argv[-2], "th_42")
        self.assertEqual(argv[-1], "-")

    def test_mcp_overrides_carry_bridge_token_not_web(self):
        ctx = self._ctx(["orm_read", "web_fetch"])
        overrides = " ".join(self.runner._mcp_overrides(ctx))
        self.assertIn("mcp_servers.odoo.command", overrides)
        self.assertIn("AI_BRIDGE_TOKEN", overrides)
        self.assertIn("tok-123", overrides)
        # The bridge advertises ORM tools, never the CLI's own web tools.
        self.assertIn("orm_read", overrides)
        self.assertNotIn("web_fetch", overrides)

    def test_system_prompt_only_on_first_turn(self):
        first = self.runner._compose_prompt(self._ctx(["orm_read"]))
        later = self.runner._compose_prompt(
            self._ctx(["orm_read"], is_first=False, thread_id="th_1"))
        self.assertIn("embedded inside an Odoo", first)
        self.assertNotIn("embedded inside an Odoo", later)
        self.assertIn("ODOO USER CONTEXT", later)
