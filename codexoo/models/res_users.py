# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import json
import logging
import os
import queue
import re
import signal
import subprocess
import threading

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools import str2bool

from .codexoo_session import READ_TOOLS, ALL_TOOLS, READONLY_TOOL_SET, WEB_TOOLS

_logger = logging.getLogger(__name__)

# Per-user, in-flight `codex login --device-auth` process id (so a new login can
# reap a stale one). Stored in ir.config_parameter, cleared on logout/complete.
_LOGIN_PID = "codexoo.login_pid.%s"

# How long the start route waits to capture the device URL + code from the
# codex login subprocess before returning to the UI.
_LOGIN_CAPTURE_S = 15

# Patterns to lift the verification URL and one-time code out of the codex login
# stdout. The exact wording is Codex-version dependent (plan item C3); these are
# deliberately loose and we also return the raw text as a fallback.
_URL_RE = re.compile(r"https://\S*device\S*", re.IGNORECASE)
# Codex device codes vary in length (e.g. the 4-then-5 "IL70-LNADU"); accept any
# reasonable XXXX-XXXX grouping rather than a fixed 4-4 so the code is extracted
# (which also lets the capture loop exit early instead of stalling the full 15s).
_CODE_RE = re.compile(r"\b([A-Z0-9]{3,8}-[A-Z0-9]{3,8})\b")
# Strip ANSI color/format escapes the CLI emits, so the captured URL/code regexes
# match cleanly and any raw fallback shown in the UI is plain text.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class ResUsers(models.Model):
    _inherit = "res.users"

    # Pure status indicator computed from the presence of valid per-user
    # credentials on disk. No token material is ever exposed on the record.
    codexoo_oauth_set = fields.Boolean(
        compute="_compute_codexoo_oauth_set", string="ChatGPT Account Linked")

    # --- Per-user AI tool permissions (manager-managed) ---
    codexoo_tool_ids = fields.Many2many(
        "codexoo.tool", "codexoo_user_tool_rel", "user_id", "tool_id",
        string="AI Tools Allowed",
        help="Tools this user may invoke through the AI Assistant. "
             "Leave empty to allow all read-only tools.")
    codexoo_zero_trust_mode = fields.Selection(
        [("inherit", "Inherit global default"),
         ("on", "Zero-trust (read-only)"),
         ("off", "Allow writes")],
        default="inherit", string="AI Zero-Trust Mode",
        help="When zero-trust is active, only read-only tools are available to "
             "this user — write tools are stripped regardless of the selection "
             "above. 'Inherit' follows the global default in Settings.")

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["codexoo_oauth_set"]

    def _compute_codexoo_oauth_set(self):
        for user in self:
            user.codexoo_oauth_set = bool(user.id) and user._codexoo_is_authenticated()

    # ------------------------------------------------------------------
    # Effective AI tool set (single source of truth, see codexoo.session)
    # ------------------------------------------------------------------
    def _codexoo_allowed_tool_names(self):
        """Per-user tool selection, independent of zero-trust.

        Empty selection falls back to all read tools (write tools require an
        explicit grant)."""
        self.ensure_one()
        sel = self.codexoo_tool_ids
        return set(sel.mapped("name")) if sel else set(READ_TOOLS)

    def _codexoo_zero_trust(self):
        """Whether zero-trust (read-only) mode is active for this user."""
        self.ensure_one()
        if self.codexoo_zero_trust_mode != "inherit":
            return self.codexoo_zero_trust_mode == "on"
        raw = self.env["codexoo.session"]._config("zero_trust_default")
        return str2bool(raw, False) if raw is not None else False

    def _codexoo_effective_tools(self):
        """THE source of truth: tool names this user may actually invoke."""
        self.ensure_one()
        names = self._codexoo_allowed_tool_names() & set(ALL_TOOLS)
        if self._codexoo_zero_trust():
            names = {n for n in names if n in READONLY_TOOL_SET}
        return names

    def _codexoo_account_email(self):
        """The email the assistant should treat as the user's."""
        self.ensure_one()
        return self.email or self.partner_id.email or self.login or ""

    # ------------------------------------------------------------------
    # Identity / role context injected into the assistant's system prompt
    # ------------------------------------------------------------------
    def _codexoo_identity_prompt(self, effective_tools=None):
        """A concise, authoritative text block telling the model WHO the Odoo
        user is and what roles/permissions they hold.

        Called from the request env as the user (see codexoo.runner._launch),
        so it reflects exactly what this user can see. It carries no secrets — only
        identity, company, locale, privilege flags, application roles and the AI
        tool grant — so the model stops self-identifying as the ChatGPT account
        and instead acts for, and within the rights of, this Odoo user."""
        self.ensure_one()
        if effective_tools is None:
            effective_tools = self._codexoo_effective_tools()

        email = self._codexoo_account_email() or "—"
        lines = [
            "--- ODOO USER CONTEXT (authoritative — this is who you are acting for) ---",
            "Name: %s" % (self.name or "—"),
            "Login: %s" % (self.login or "—"),
            "Email: %s" % email,
            "Odoo user id: %s" % self.id,
            "Company: %s" % (self.company_id.name or "—"),
        ]
        if len(self.company_ids) > 1:
            lines.append(
                "Allowed companies: %s"
                % ", ".join(self.company_ids.mapped("name")))
        lines.append("Language: %s" % (self.lang or "—"))
        lines.append("Timezone: %s" % (self.tz or "—"))

        # Privilege flags — stated plainly so the model never over-assumes rights.
        if self._is_admin():
            priv = "Administrator (full access)"
        elif self._is_system():
            priv = "Settings/System access"
        elif self.has_group("base.group_user"):
            priv = "Internal user (not an administrator)"
        else:
            priv = "Portal/public user (limited access)"
        lines.append("Privilege level: %s" % priv)

        # Curated roles: only groups that belong to an application category.
        roles = sorted(
            "%s / %s" % (g.category_id.name, g.name)
            for g in self.groups_id if g.category_id
        )
        if roles:
            lines.append("Roles:")
            lines.extend("  - %s" % r for r in roles)
        else:
            lines.append("Roles: (none beyond base access)")

        # What the assistant may actually do on this user's behalf.
        if not effective_tools:
            lines.append("AI tools available to you: none.")
        else:
            writeable = sorted(set(effective_tools) - READONLY_TOOL_SET)
            if writeable:
                lines.append(
                    "AI tool grant: read-only data access PLUS write/action tools "
                    "(%s). Use Odoo business actions when available." % ", ".join(writeable))
            else:
                lines.append(
                    "AI tool grant: READ-ONLY. You cannot create, modify or delete "
                    "data for this user — only query and report.")
        if set(effective_tools) & set(WEB_TOOLS):
            lines.append(
                "Web access: you may use web search to retrieve and search "
                "public web content.")
        lines.append("--- END ODOO USER CONTEXT ---")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Per-user Codex home (CODEX_HOME) and credentials file (auth.json)
    # ------------------------------------------------------------------
    def _codexoo_home_root(self):
        """Root under which each user gets `<root>/<uid>/.codex`."""
        return self.env["ir.config_parameter"].sudo().get_param(
            "codexoo.home_root") or "/var/lib/odoo/codexoo_home"

    def _codexoo_home_dir(self):
        """The HOME directory for this user's CLI runs."""
        self.ensure_one()
        return os.path.join(self._codexoo_home_root(), str(self.id))

    def _codexoo_codex_home(self, create=False):
        """This user's private CODEX_HOME (holds auth.json + config)."""
        self.ensure_one()
        path = os.path.join(self._codexoo_home_dir(), ".codex")
        if create:
            try:
                os.makedirs(path, mode=0o700, exist_ok=True)
            except OSError as e:
                raise UserError(_("Cannot create Codex home %s: %s") % (path, e))
        return path

    def _codexoo_auth_path(self):
        self.ensure_one()
        return os.path.join(self._codexoo_codex_home(), "auth.json")

    def _codexoo_is_authenticated(self):
        """True if this user has stored, non-empty Codex credentials.

        Codex writes ``$CODEX_HOME/auth.json`` after a successful login. The
        exact schema is version-dependent (plan item C3); accept any of the
        known token locations (ChatGPT login nests under ``tokens``)."""
        self.ensure_one()
        try:
            with open(self._codexoo_auth_path(), "r") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        tokens = data.get("tokens") or {}
        return bool(
            (isinstance(tokens, dict) and tokens.get("access_token"))
            or data.get("access_token")
            or data.get("OPENAI_API_KEY"))

    def _codexoo_login_env(self):
        """Minimal env for spawning the codex CLI for THIS user."""
        self.ensure_one()
        return {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "HOME": self._codexoo_home_dir(),
            "CODEX_HOME": self._codexoo_codex_home(create=True),
            "CODEX_API_KEY": "",  # subscription only, never an API key
        }

    # ------------------------------------------------------------------
    # Device-auth login flow (ChatGPT subscription)
    # ------------------------------------------------------------------
    def _codexoo_login_start(self):
        """Begin a device-code login: spawn `codex login --device-auth`, capture
        the verification URL + one-time code, and leave the process running so
        Codex completes the exchange and writes auth.json.

        Returns ``{"url", "code", "raw"}`` for the chat gate to display."""
        self.ensure_one()
        if self._codexoo_is_authenticated():
            return {"url": "", "code": "", "raw": "", "authenticated": True}

        self._codexoo_reap_login()  # kill any previous in-flight attempt
        cli = self.env["codexoo.session"]._resolve_cli_path()
        try:
            proc = subprocess.Popen(
                [cli, "login", "--device-auth"],
                cwd=self._codexoo_home_dir(), env=self._codexoo_login_env(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as e:
            raise UserError(_("Could not start codex login: %s") % e)

        self.env["ir.config_parameter"].sudo().set_param(
            _LOGIN_PID % self.id, str(proc.pid))

        raw = self._codexoo_capture_login(proc, _LOGIN_CAPTURE_S)
        raw = _ANSI_RE.sub("", raw)
        url_m = _URL_RE.search(raw)
        url = url_m.group(0) if url_m else ""
        m = _CODE_RE.search(raw)
        code = m.group(1) if m else ""
        if proc.poll() not in (None, 0) and not url:
            raise UserError(_(
                "codex login failed to start the device flow. Make sure device-"
                "code login is enabled for your ChatGPT account/workspace.\n%s"
            ) % (raw[:500] or "(no output)"))
        return {"url": url, "code": code, "raw": raw[:2000],
                "authenticated": self._codexoo_is_authenticated()}

    @staticmethod
    def _codexoo_capture_login(proc, wait_s):
        """Read the login process's stdout for up to ``wait_s`` seconds (without
        blocking on the long-lived process), returning the captured text."""
        import time
        q = queue.Queue()

        def _pump(pipe, out_q):
            try:
                for ln in pipe:
                    out_q.put(ln)
            finally:
                out_q.put(None)

        threading.Thread(target=_pump, args=(proc.stdout, q), daemon=True,
                         name="codexoo_login_read").start()
        deadline = time.time() + wait_s
        buf = []
        while time.time() < deadline:
            try:
                ln = q.get(timeout=min(1.0, max(0.05, deadline - time.time())))
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if ln is None:
                break
            buf.append(ln)
            # Strip ANSI before matching: the CLI wraps the code in color escapes
            # (e.g. "\x1b[94mIL70-LNADU\x1b[0m") whose trailing "m" would otherwise
            # defeat the \b boundary and prevent the early exit, stalling the run.
            text = _ANSI_RE.sub("", "".join(buf))
            # Stop early once we have both a device URL and a code.
            if _URL_RE.search(text) and _CODE_RE.search(text):
                break
        return "".join(buf)

    def _codexoo_login_status(self):
        """Poll target for the chat gate: are this user's credentials present?"""
        self.ensure_one()
        ok = self._codexoo_is_authenticated()
        if ok:
            self._codexoo_reap_login()  # login done; drop the (now-exited) process ref
        return {"authenticated": ok}

    def _codexoo_reap_login(self):
        """Kill any in-flight login subprocess for this user and clear the pid."""
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        raw = ICP.get_param(_LOGIN_PID % self.id)
        if raw and raw.isdigit():
            try:
                os.kill(int(raw), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        ICP.set_param(_LOGIN_PID % self.id, "")

    def _codexoo_logout(self):
        """Remove this user's stored credentials (forces re-authentication)."""
        self.ensure_one()
        self._codexoo_reap_login()
        cli = None
        try:
            cli = self.env["codexoo.session"]._resolve_cli_path()
        except UserError:
            cli = None
        if cli:
            try:
                subprocess.run(
                    [cli, "logout"], cwd=self._codexoo_home_dir(),
                    env=self._codexoo_login_env(), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            os.remove(self._codexoo_auth_path())
        except OSError:
            pass
        return True

    def action_codexoo_logout(self):
        """Button: disconnect this user's ChatGPT account from preferences."""
        for user in self:
            user._codexoo_logout()
        return True
