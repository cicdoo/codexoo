# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
"""Pre-migration: remove stale res.users inherited views from the previous
release whose stored arch references pre-rename field names (ai_codex_oauth_set,
ai_zero_trust_mode).

These views are recreated from the current XML later in this same upgrade. We
must delete them FIRST because the data phase loads security before views, and
writing the security groups regenerates the combined res.users "user groups"
view — which would validate the obsolete field reference and abort the upgrade.

NB: we do NOT drop the old ai_zero_trust_mode column — claudoo (a sibling
module) also defines that exact field on res.users and shares the column, so
dropping it here would corrupt claudoo. The orphan column is harmless.
"""
import logging

_logger = logging.getLogger(__name__)

# xmlids (module 'codexoo') of the inherited res.users views to drop.
STALE_VIEWS = ("view_users_form_ai_oauth", "view_users_form_simple_ai_oauth")


def migrate(cr, version):
    if not version:
        return  # fresh install: nothing to migrate
    cr.execute("""
        DELETE FROM ir_ui_view WHERE id IN (
            SELECT res_id FROM ir_model_data
            WHERE module = 'codexoo' AND model = 'ir.ui.view' AND name IN %s
        )
    """, (STALE_VIEWS,))
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = 'codexoo' AND model = 'ir.ui.view' AND name IN %s
    """, (STALE_VIEWS,))
    _logger.info(
        "codexoo pre-migration: removed stale res.users views %s", STALE_VIEWS)
