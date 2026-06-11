# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    codexoo_cli_path = fields.Char(
        string="Codex CLI Path",
        config_parameter="codexoo.cli_path",
        help="Absolute path to the codex binary. Leave empty to use PATH/auto-detect.")
    codexoo_model = fields.Char(
        string="Model", config_parameter="codexoo.model", default="",
        help="Model passed to `codex -m`. Leave EMPTY to use your ChatGPT "
             "account's default model. Note: 'gpt-5-codex' is not available on "
             "ChatGPT-subscription auth and will make turns fail.")
    codexoo_max_turns = fields.Integer(
        string="Max Turns", config_parameter="codexoo.max_turns", default=30)
    codexoo_timeout_s = fields.Integer(
        string="Run Timeout (s)", config_parameter="codexoo.timeout_s",
        default=900)
    codexoo_max_concurrent_runs = fields.Integer(
        string="Max Concurrent Runs",
        config_parameter="codexoo.max_concurrent_runs", default=0,
        help="Maximum number of AI runs allowed to execute at the same time "
             "across all users. Each run is a separate CLI subprocess, so this "
             "caps peak memory and protects the host from OOM. 0 = unlimited.")
    codexoo_scratch_root = fields.Char(
        string="Scratch Directory", config_parameter="codexoo.scratch_root",
        default="/var/lib/odoo/codexoo_scratch")
    codexoo_home_root = fields.Char(
        string="Per-User Codex Home Root", config_parameter="codexoo.home_root",
        default="/var/lib/odoo/codexoo_home",
        help="Root directory under which each user gets a private "
             "<root>/<uid>/.codex (CODEX_HOME) holding their own credentials.")
    codexoo_base_url = fields.Char(
        string="Odoo Host URL", config_parameter="codexoo.base_url",
        default="http://127.0.0.1:8069",
        help="Host URL the MCP bridge connects back to (loopback by default).")
    codexoo_db_name = fields.Char(
        string="Odoo Database", config_parameter="codexoo.db_name",
        help="Database the assistant connects to. Leave empty to use the current "
             "database. Set this in multi-database deployments so the bridge "
             "always reaches the right database.")
    codexoo_sql_enabled = fields.Boolean(
        string="Enable SQL Reporting Tool",
        config_parameter="codexoo.sql_enabled", default=True,
        help="Allow the read-only SQL tool (members of the AI SQL Analyst group).")
    codexoo_zero_trust_default = fields.Boolean(
        string="Zero-Trust by Default (read-only)",
        config_parameter="codexoo.zero_trust_default", default=False,
        help="Instance-wide default: when on, users left on 'Inherit' may only "
             "use read-only tools. A per-user override can still allow writes.")
    codexoo_action_method_patterns = fields.Char(
        string="AI Action Method Patterns",
        config_parameter="codexoo.action_methods",
        default="action_*,button_*",
        help="Comma-separated fnmatch patterns for methods orm_action/run_wizard "
             "may call (e.g. action_*,button_*). Private/dunder methods are "
             "always blocked.")
    # Non-stored: persisted as a CSV of technical names in the
    # codexoo.excluded_models system parameter (see get/set_values).
    # Explicit relation table/columns (NOT the auto-derived name): res.config.settings
    # ↔ ir.model would otherwise collide with any other module's M2M between the
    # same two models (e.g. claudoo's), since the auto name is identical.
    codexoo_excluded_model_ids = fields.Many2many(
        "ir.model", "codexoo_settings_excluded_model_rel",
        "settings_id", "model_id", string="Models Hidden from AI",
        help="The AI Assistant will refuse to introspect, read, or write these "
             "models for every user.")
    # Non-stored: persisted as a CSV of ids in the codexoo.server_action_ids
    # system parameter (see get/set_values). Only these may be run via
    # run_server_action; an allowlisted server action is trusted-by-admin.
    codexoo_allowed_server_action_ids = fields.Many2many(
        "ir.actions.server", "codexoo_settings_server_action_rel",
        "settings_id", "action_id", string="AI-Runnable Server Actions",
        help="Only these server actions may be run via run_server_action. "
             "Empty = none. A 'code' server action runs arbitrary Python, so "
             "only allowlist actions you trust.")

    def get_values(self):
        res = super().get_values()
        names = self.env["codexoo.session"]._ai_excluded_models()
        models = self.env["ir.model"].search([("model", "in", list(names))])
        res["codexoo_excluded_model_ids"] = [(6, 0, models.ids)]
        sa_ids = self.env["codexoo.session"]._ai_allowed_server_action_ids()
        res["codexoo_allowed_server_action_ids"] = [(6, 0, list(sa_ids))]
        return res

    def set_values(self):
        super().set_values()
        names = ",".join(sorted(self.codexoo_excluded_model_ids.mapped("model")))
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("codexoo.excluded_models", names)
        ICP.set_param("codexoo.server_action_ids",
                      ",".join(map(str, sorted(self.codexoo_allowed_server_action_ids.ids))))
