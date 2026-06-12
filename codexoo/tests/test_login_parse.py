# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
"""The device-code login gate scrapes the verification URL and one-time code out
of the ``codex login --device-auth`` stdout. The CLI colorises that output and
its code length is version-dependent (e.g. the 4-then-5 ``IL70-LNADU``). These
tests pin the extraction so a stricter pattern can't silently break login again:
a missed code both stalls the capture for the full timeout and leaks raw ANSI to
the UI."""
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.codexoo.models.res_users import _URL_RE, _CODE_RE, _ANSI_RE

# A faithful sample of the codex CLI device-auth output, with real ANSI escapes.
_SAMPLE = (
    "Welcome to Codex [v\x1b[90m0.139.0\x1b[0m]\n"
    "\x1b[90mOpenAI's command-line coding agent\x1b[0m\n\n"
    "1. Open this link in your browser and sign in to your account\n"
    "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n\n"
    "2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
    "   \x1b[94mIL70-LNADU\x1b[0m\n"
)


@tagged("post_install", "-at_install", "codexoo")
class TestLoginParse(TransactionCase):

    # --- ANSI stripping -----------------------------------------------------
    def test_ansi_stripped(self):
        clean = _ANSI_RE.sub("", _SAMPLE)
        self.assertNotIn("\x1b", clean)
        self.assertNotIn("[94m", clean)
        self.assertNotIn("[0m", clean)

    # --- code extraction ----------------------------------------------------
    def test_new_code_format_extracted(self):
        # 4-then-5 is the format current Codex emits; the old pattern missed it.
        clean = _ANSI_RE.sub("", _SAMPLE)
        m = _CODE_RE.search(clean)
        self.assertTrue(m)
        self.assertEqual(m.group(1), "IL70-LNADU")

    def test_legacy_code_format_still_extracted(self):
        self.assertEqual(
            _CODE_RE.search("code ABCD-1234 expires").group(1), "ABCD-1234")

    def test_code_not_matched_through_ansi(self):
        # Regression guard: the colour escape ("\x1b[94m") ends in a word char,
        # which defeats the \b boundary — so the code is only found AFTER the
        # ANSI strip. Matching on raw output is what stalled the capture loop.
        self.assertIsNone(_CODE_RE.search(_SAMPLE))

    # --- url extraction -----------------------------------------------------
    def test_url_extracted_without_trailing_escape(self):
        clean = _ANSI_RE.sub("", _SAMPLE)
        self.assertEqual(
            _URL_RE.search(clean).group(0),
            "https://auth.openai.com/codex/device")
