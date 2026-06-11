# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
{
    'name': "Codexoo",
    'summary': "Codexoo — chat with your Odoo, safely. An OpenAI Codex-powered assistant "
               "with permission-aware ORM tools and read-only SQL reporting.",
    'description': """
Codexoo — AI Assistant for Odoo
===============================
A chat interface (menu + OWL client action) that drives the OpenAI Codex CLI headless on
the server. The assistant can query Odoo and build reports through a small set of safe
tools exposed over a sandboxed MCP bridge:

* Every ORM action runs with the **current user's** permission level (never superuser).
* Raw SQL reporting is **read-only** (SELECT only) and gated to the *AI SQL Analyst* group.
* Codex runs in a read-only sandbox with approvals disabled; it can only affect Odoo
  through the gated tool endpoints. The authoritative boundary is server-side
  (loopback-only bridge token + per-user Odoo ACLs on every tool call).
* Replies stream into the chat in real time over the Odoo bus.

Authentication is per-user ChatGPT subscription (no API key): each user clicks
**Login with ChatGPT** in the chat, completes the Codex device-code login in their
own browser, and their credentials are stored privately in a per-user CODEX_HOME.
Chatting is gated until the current user has connected.

Requires the OpenAI Codex CLI installed on the server (set its path via the
``codexoo.cli_path`` / ``codexoo.cli_glob`` system parameter).
""",
    'author': "CICDoo",
    'website': "https://cicdoo.com",
    'category': 'Productivity/AI',
    'version': '18.0.1.0.1',
    'license': 'LGPL-3',
    'depends': ['web', 'bus'],
    'data': [
        'security/codexoo_security.xml',
        'security/ir.model.access.csv',
        'data/codexoo_tool_data.xml',
        'data/codexoo_action.xml',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
        'views/codexoo_log_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'codexoo/static/src/scss/codexoo.scss',
            'codexoo/static/src/codexoo_service.js',
            'codexoo/static/src/markdown.js',
            'codexoo/static/src/components/message.js',
            'codexoo/static/src/components/message.xml',
            'codexoo/static/src/components/message_list.js',
            'codexoo/static/src/components/message_list.xml',
            'codexoo/static/src/components/composer.js',
            'codexoo/static/src/components/composer.xml',
            'codexoo/static/src/chat_action.js',
            'codexoo/static/src/chat_action.xml',
        ],
    },
    'application': True,
    'installable': True,
}
