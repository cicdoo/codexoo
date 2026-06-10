# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import json

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


class AiAssistantChat(http.Controller):

    def _session(self, session_id):
        """Fetch a session owned by the current user (record rule enforced)."""
        session = request.env["codexoo.session"].browse(int(session_id))
        if not session.exists() or session.user_id != request.env.user:
            raise UserError("Session not found.")
        return session

    # ------------------------------------------------------------------
    # Per-user ChatGPT authentication (Codex device-code login gate)
    # ------------------------------------------------------------------
    @http.route("/codexoo/auth/status", type="json", auth="user")
    def auth_status(self):
        return request.env.user._codexoo_login_status()

    @http.route("/codexoo/auth/start", type="json", auth="user")
    def auth_start(self):
        """Start the Codex device-code login and return the URL + one-time code
        for the user to enter in their own browser. The frontend then polls
        /codexoo/auth/status until the login completes."""
        return request.env.user._codexoo_login_start()

    @http.route("/codexoo/auth/logout", type="json", auth="user")
    def auth_logout(self):
        request.env.user._codexoo_logout()
        return {"authenticated": False}

    @http.route("/codexoo/sessions", type="json", auth="user")
    def sessions(self):
        recs = request.env["codexoo.session"].search(
            [("user_id", "=", request.env.uid)], limit=50)
        return [{"id": s.id, "name": s.name, "state": s.state} for s in recs]

    @http.route("/codexoo/new", type="json", auth="user")
    def new(self):
        session = request.env["codexoo.session"].create({
            "user_id": request.env.uid})
        return {"id": session.id, "name": session.name, "state": session.state}

    @http.route("/codexoo/messages", type="json", auth="user")
    def messages(self, session_id=None):
        session = self._session(session_id)
        return {
            "id": session.id,
            "name": session.name,
            "state": session.state,
            "messages": session.message_ids._to_frontend(),
        }

    @http.route("/codexoo/upload", type="http", auth="user", methods=["POST"])
    def upload(self, session_id=None, ufile=None, **kw):
        """Accept one or more uploaded files for a session (multipart form).

        Stores each as an ir.attachment linked to the session and returns their
        descriptors as JSON. type="http" (not json) so the browser can post the
        raw file via FormData."""
        headers = [("Content-Type", "application/json")]
        try:
            session = self._session(session_id)
            files = request.httprequest.files.getlist("ufile")
            if not files:
                raise UserError("No file received.")
            out = [session._store_upload(f.filename, f.read()) for f in files]
            return request.make_response(json.dumps({"attachments": out}), headers)
        except UserError as e:
            return request.make_response(
                json.dumps({"error": str(e)}), headers, status=400)

    @http.route("/codexoo/send", type="json", auth="user")
    def send(self, session_id=None, body=None, attachment_ids=None):
        session = self._session(session_id)
        return session.send_message(body, attachment_ids=attachment_ids)

    @http.route("/codexoo/stop", type="json", auth="user")
    def stop(self, session_id=None):
        session = self._session(session_id)
        session.action_stop()
        return {"state": session.state}
