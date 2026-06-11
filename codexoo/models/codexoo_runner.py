# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time

from odoo import api, models
from odoo.modules.registry import Registry

from .codexoo_session import WEB_TOOLS

_logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI assistant embedded inside an Odoo 18 ERP system. "
    "You help the current Odoo user query data and build reports. "
    "You act through the Odoo tools provided by the `odoo` MCP server (model_introspect, "
    "orm_search_read, orm_read, orm_call, sql_select, and — when granted — orm_create/"
    "orm_write/orm_unlink/orm_action/run_wizard/run_server_action). "
    "Do NOT run shell commands, edit files, or use the network: the ONLY way to read or "
    "change Odoo data is through the `odoo` MCP tools. (You may read files the user attached "
    "under your working directory when they ask about an attachment.) "
    "Web search is available only when the tool grant in the ODOO USER CONTEXT block below "
    "lists it; otherwise assume you cannot reach the web. "
    "All Odoo actions run with the user's own permissions, so respect AccessError results and "
    "never try to work around them. "
    "Use `model_introspect` to discover models/fields before querying — consult its "
    "`effective_access` map to see which actions (read/write/create/unlink) are actually "
    "available to you here before attempting them. "
    "Use `orm_search_read`/`orm_read`/`orm_call` for normal data access (these honor "
    "record rules). Use `sql_select` only for read-only reporting when available. "
    "Write tools may be available; only some users are granted them. When you change data, "
    "confirm what you did concisely. "
    "Action tools may also be available (check `model_introspect`'s `ai_tools_allowed`): "
    "use `orm_action` to call business methods like `action_confirm`/`action_post`/"
    "`button_validate` on records (method names are allowlisted), `run_wizard` to create "
    "and run a wizard in one step, and `run_server_action` to run an admin-allowlisted "
    "server action. Prefer these over raw `orm_write` when an Odoo business action exists, "
    "so state machines and validations run correctly. "
    "Be concise. When you present data, format it as a clear Markdown table when useful. "
    "IDENTITY: You are acting on behalf of a specific Odoo user, whose identity, company, "
    "locale and roles are given in the 'ODOO USER CONTEXT' block below. You are THAT Odoo "
    "user's assistant — never identify yourself as a ChatGPT/OpenAI subscription account, "
    "and address the user by their Odoo name. Any account email shown elsewhere in your "
    "environment is the underlying ChatGPT subscription used to run you — it is NOT the user; "
    "the authoritative identity is the one in the ODOO USER CONTEXT block. Assume ONLY the "
    "roles and privileges listed in that block; never assume administrator rights you have "
    "not been shown. Every tool runs with this user's own Odoo permissions, so an AccessError "
    "is authoritative: report it plainly and never try to work around it. "
    "CRITICAL: Only ever call tools through the real tool-calling mechanism. NEVER write "
    "tool calls or fabricated tool results as text in your reply, and NEVER invent data. If "
    "the Odoo MCP tools are not visible to you, reply exactly 'AI tools are not available "
    "right now, please retry.' and nothing else — do not guess."
)


def _toml_str(value):
    """Quote a Python string as a TOML basic string for a -c override."""
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\t", "\\t")
    return '"%s"' % s


def _toml_inline_table(mapping):
    """Render a flat {str: str} mapping as a TOML inline table."""
    items = ", ".join(
        "%s = %s" % (k, _toml_str(v)) for k, v in mapping.items())
    return "{ %s }" % items


class AiAssistantRunner(models.AbstractModel):
    _name = "codexoo.runner"
    _description = "Codexoo AI Assistant CLI Runner"

    # ------------------------------------------------------------------
    # Launch (runs in the request env, as the user)
    # ------------------------------------------------------------------
    def _launch(self, session, prompt, is_first, token):
        """Resolve config in the request env, then spawn a background thread."""
        cli_path = session._resolve_cli_path()
        scratch = session._get_scratch_dir()
        # Empty = let Codex use the account's default model. Forcing a model the
        # ChatGPT subscription can't use (e.g. gpt-5-codex) makes the turn 400.
        model = session._config("model", "")
        timeout_s = int(session._config("timeout_s", 900))
        base_url = session._config("base_url", "http://127.0.0.1:8069")
        # Interpreter used to run the bundled bridge script. Defaults to the
        # Python currently running Odoo; override via `codexoo.python_bin`.
        python_bin = session._config("python_bin", "") or sys.executable
        target_db = session._target_db()
        routing_sid = session._mint_routing_sid(target_db)
        bridge_script = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "bridge", "mcp_server.py")
        codex_env = session._codex_env()
        # Effective tool set + model denylist for THIS user (computed once here,
        # in the request env, as the user). The controller re-derives them
        # authoritatively; these only shape the bridge's advertised tools.
        allowed_tools = sorted(session._effective_tools())
        web_enabled = bool(set(allowed_tools) & set(WEB_TOOLS))
        excluded_models = sorted(session._ai_excluded_models())
        # Per-user identity/role block prepended to the prompt so the model acts
        # AS this Odoo user (built here, in the request env, as the user).
        identity = session.user_id._codexoo_identity_prompt(set(allowed_tools))

        ctx = {
            "dbname": self.env.cr.dbname,
            "uid": session.user_id.id,
            "session_id": session.id,
            "codex_thread_id": session.codex_thread_id or "",
            "prompt": prompt,
            "is_first": is_first,
            "cli_path": cli_path,
            "scratch": scratch,
            "model": model,
            "timeout_s": timeout_s,
            "base_url": base_url,
            "python_bin": python_bin,
            "target_db": target_db,
            "routing_sid": routing_sid,
            "bridge_script": bridge_script,
            "token": token,
            "codex_env": codex_env,
            "allowed_tools": allowed_tools,
            "web_enabled": web_enabled,
            "excluded_models": excluded_models,
            "identity": identity,
        }
        thread = threading.Thread(
            target=self._run_worker, args=(ctx,), daemon=True,
            name="codexoo_run_%s" % session.id)
        # Start only AFTER the request transaction commits, so the worker's own
        # cursor sees the committed session state (state=running) and bridge
        # token (bridge_jti). Starting inline races the request transaction.
        self.env.cr.postcommit.add(thread.start)

    # ------------------------------------------------------------------
    # Background worker (own cursor)
    # ------------------------------------------------------------------
    def _run_worker(self, ctx):
        dbname = ctx["dbname"]
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, ctx["uid"], {})
            session = env["codexoo.session"].browse(ctx["session_id"])
            runner = env["codexoo.runner"]
            try:
                runner._execute(env, session, ctx)
            except Exception as e:
                _logger.exception("AI assistant run failed")
                session.write({"state": "error", "last_error": str(e)})
                runner._emit(session, {"kind": "error", "error": str(e)})
                cr.commit()

    def _execute(self, env, session, ctx):
        last_msg_path = os.path.join(ctx["scratch"], "last_message.txt")
        argv = self._build_argv(ctx, last_msg_path)
        run_env = self._build_env(ctx)
        # The prompt is fed via STDIN (argv ends with "-"), never as an argv
        # token: it begins with the "--- ODOO USER CONTEXT" block, which codex's
        # parser would otherwise mistake for a CLI flag ("unexpected argument").
        prompt_text = self._compose_prompt(ctx)

        _logger.info("AI assistant: spawning %s (session %s)",
                     ctx["cli_path"], ctx["session_id"])
        proc = subprocess.Popen(
            argv, cwd=ctx["scratch"], env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.PIPE, text=True, bufsize=1)
        # Write the prompt, then close stdin so codex sees EOF and proceeds.
        try:
            proc.stdin.write(prompt_text)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        session.write({"last_run_pid": proc.pid})
        self._emit(session, {"kind": "started"})
        env.cr.commit()

        deadline = time.time() + ctx["timeout_s"]
        # Per-turn streaming state: the single assistant message record for this
        # turn (lazily created) plus a {codex_item_id -> tool_calls index} map.
        st = {"msg_id": None, "tool_idx": {}}
        # Read stdout via a helper thread feeding a queue, so the deadline is
        # enforced even when the CLI goes silent (no output, no exit).
        line_q = queue.Queue()

        def _pump(pipe, q):
            try:
                for ln in pipe:
                    q.put(ln)
            finally:
                q.put(None)  # sentinel: stdout closed (process exiting)

        reader = threading.Thread(
            target=_pump, args=(proc.stdout, line_q), daemon=True,
            name="codexoo_read_%s" % ctx["session_id"])
        reader.start()
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    proc.kill()
                    raise TimeoutError("Run exceeded timeout")
                try:
                    line = line_q.get(timeout=min(remaining, 5))
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                if line is None:  # stdout closed -> process is exiting
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except ValueError:
                    # codex --json should emit pure JSONL; ignore stray lines.
                    continue
                self._handle_event(env, session, evt, st)
                env.cr.commit()
            try:
                rc = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
        finally:
            env["codexoo.session"]._delete_routing_sid(ctx.get("routing_sid"))

        stderr = proc.stderr.read() if proc.stderr else ""
        # Fallback: if no assistant text was streamed, use the final-message file.
        if st["msg_id"] is None and session.state == "running":
            final = self._read_last_message(last_msg_path)
            if final:
                rec = self._ensure_assistant(env, session, st)
                rec.body = final
                self._emit_message(session, rec)
        try:
            os.remove(last_msg_path)
        except OSError:
            pass

        session.write({
            "last_run_pid": False,
            "turn_count": session.turn_count + 1,
        })
        if session.state == "running":
            # No explicit turn.completed event; treat as done unless rc failed.
            if rc != 0:
                session.write({"state": "error", "last_error": stderr[:2000]})
                self._emit(session, {"kind": "error",
                                     "error": stderr[:500] or "CLI exited %s" % rc})
            else:
                session.write({"state": "done"})
                self._emit(session, {"kind": "done"})
        env.cr.commit()

    # ------------------------------------------------------------------
    # Event handling: codex stream-json (JSONL) -> DB + bus
    # ------------------------------------------------------------------
    def _handle_event(self, env, session, evt, st):
        etype = evt.get("type") or ""

        # thread.started carries the codex thread/session id used to resume.
        if etype == "thread.started":
            tid = evt.get("thread_id") or (evt.get("thread") or {}).get("id")
            if tid and session.codex_thread_id != tid:
                session.codex_thread_id = tid
            return

        # item.* events carry the actual content (agent text, tool calls, …).
        if etype.startswith("item."):
            self._handle_item(env, session, evt.get("item") or {}, st)
            return

        if etype == "turn.completed":
            session.write({"state": "done"})
            self._emit(session, {"kind": "done"})
            return

        if etype in ("turn.failed", "error"):
            # Codex emits either {"type":"error","message":"…"} (top-level) or a
            # nested {"error":{"message":"…"}} — accept both.
            err = evt.get("error")
            if isinstance(err, dict):
                text = err.get("message")
            else:
                text = err if isinstance(err, str) else None
            text = text or evt.get("message") or "Codex run failed."
            session.write({"state": "error", "last_error": text[:2000]})
            self._emit(session, {"kind": "error", "error": text[:500]})
            return

    def _handle_item(self, env, session, item, st):
        # Codex labels the kind under "type" (within the item) or "item_type".
        itype = item.get("item_type") or item.get("type") or ""
        item_id = item.get("id") or item.get("item_id")

        if itype in ("agent_message", "assistant_message", "message"):
            text = (item.get("text") or item.get("message")
                    or self._content_text(item.get("content")) or "")
            if not text:
                return
            rec = self._ensure_assistant(env, session, st)
            # Item events may arrive as started/updated/completed for one id;
            # take the latest full text rather than appending fragments.
            rec.body = text
            self._emit_message(session, rec)
            return

        if itype in ("mcp_tool_call", "tool_call", "function_call",
                     "command_execution", "web_search"):
            self._upsert_tool_call(env, session, item, itype, item_id, st)
            return

        # reasoning / plan_update / file_change / others: not surfaced.
        return

    def _upsert_tool_call(self, env, session, item, itype, item_id, st):
        rec = self._ensure_assistant(env, session, st)
        calls = list(rec.tool_calls or [])
        name = (item.get("tool") or item.get("name")
                or item.get("command") or itype)
        # Strip a leading MCP server namespace ("odoo." / "odoo__") for display.
        for sep in ("__", "."):
            if isinstance(name, str) and (itype.startswith("mcp") and sep in name):
                name = name.split(sep, 1)[1]
                break
        status = self._map_status(item.get("status"))
        result = (item.get("result") or item.get("output")
                  or item.get("aggregated_output") or "")
        if isinstance(result, (dict, list)):
            result = json.dumps(result, default=str)
        entry = {
            "id": item_id or ("%s-%s" % (itype, len(calls))),
            "name": name,
            "input": item.get("arguments") or item.get("args") or item.get("input") or {},
            "result": (str(result) or None) and str(result)[:4000],
            "status": status,
        }
        idx = st["tool_idx"].get(entry["id"])
        if idx is None:
            st["tool_idx"][entry["id"]] = len(calls)
            calls.append(entry)
        else:
            calls[idx] = entry
        rec.tool_calls = calls
        self._emit_message(session, rec)

    @staticmethod
    def _map_status(status):
        s = (status or "").lower()
        if s in ("completed", "success", "succeeded", "done", "ok"):
            return "done"
        if s in ("failed", "error", "denied", "aborted"):
            return "error"
        return "running"

    @staticmethod
    def _content_text(content):
        """Flatten a list-of-blocks content payload into plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                b.get("text", "") for b in content if isinstance(b, dict))
        return ""

    def _ensure_assistant(self, env, session, st):
        """Lazily create (once per turn) the assistant message record."""
        if st["msg_id"]:
            return env["codexoo.message"].browse(st["msg_id"])
        rec = env["codexoo.message"].create({
            "session_id": session.id,
            "role": "assistant",
            "body": "",
        })
        st["msg_id"] = rec.id
        return rec

    @staticmethod
    def _read_last_message(path):
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except OSError:
            return ""

    # ------------------------------------------------------------------
    # Bus
    # ------------------------------------------------------------------
    def _emit(self, session, payload):
        payload = dict(payload, session_id=session.id)
        # Push to the user's partner channel via the record-level _bus_send
        # (bus.listener.mixin); the frontend filters by the "codexoo" type.
        session.user_id.partner_id._bus_send("codexoo", payload)

    def _emit_message(self, session, rec):
        self._emit(session, {
            "kind": "message",
            "message": rec._to_frontend()[0],
        })

    # ------------------------------------------------------------------
    # Command / env construction
    # ------------------------------------------------------------------
    def _build_argv(self, ctx, last_msg_path):
        """Build the `codex exec` argv for this turn.

        Verified against codex-cli 0.139.0:
          first turn:  codex exec [OPTIONS] <prompt>
          later turns: codex exec [OPTIONS] resume <thread_id> <prompt>

        The exec OPTIONS (--json, -C, -o, -c, …) belong to `exec` and MUST come
        BEFORE the `resume` subcommand — `resume` itself only accepts `-c` plus
        the [SESSION_ID] [PROMPT] positionals, so passing e.g. `-C` after
        `resume` errors with "unexpected argument '-C'".

        Two flags work together for safe unattended operation:

        * --dangerously-bypass-approvals-and-sandbox: in `codex exec` (non-
          interactive) MCP tool calls are otherwise auto-cancelled ("user
          cancelled MCP tool call") — there is no TTY to approve them and no
          per-server auto-approve is honored on this CLI version
          (openai/codex#24135, #16685). This flag lets the Odoo MCP tools run.
        * --disable shell_tool: turns OFF Codex's built-in shell/command tool, so
          the agent has NO local execution at all — it CANNOT run psql, read
          odoo.conf, write files, or otherwise bypass the gated tools. The only
          capabilities left are the loopback-only, token-gated Odoo MCP tools,
          which run under the acting user's own ACLs (see controllers/tools.py).

        Without --disable shell_tool, bypassing the sandbox would let the agent
        reach the DB/secrets directly (codex runs as the odoo OS user). With it,
        the sandbox bypass only re-enables the (now absent) shell, so the
        effective surface is just the Odoo tools. --skip-git-repo-check is
        required because the scratch cwd is not a git repository.
        """
        resume = (not ctx["is_first"]) and ctx["codex_thread_id"]
        argv = [ctx["cli_path"], "exec"]
        # exec-level options FIRST (apply to both fresh and resumed turns).
        argv += [
            "--json",
            "-C", ctx["scratch"],
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "--disable", "shell_tool",
            "--output-last-message", last_msg_path,
        ]
        # Only pin the model if explicitly configured; otherwise let Codex use
        # the account default (forcing an unsupported model 400s the turn).
        if ctx["model"]:
            argv += ["-m", ctx["model"]]
        # MCP server is injected per-invocation via -c overrides (race-free: the
        # per-session bridge token never touches a shared config file). The -c
        # value is parsed as TOML, so an inline table for `.env` is accepted.
        argv += self._mcp_overrides(ctx)
        # Then the resume subcommand + session id, and finally "-" so codex reads
        # the PROMPT from stdin (see _execute) instead of from argv.
        if resume:
            argv += ["resume", ctx["codex_thread_id"]]
        argv.append("-")
        return argv

    def _mcp_overrides(self, ctx):
        bridge_env = {
            "AI_ODOO_BASE": ctx["base_url"],
            "AI_ODOO_DB": ctx["target_db"],
            "AI_ODOO_SID": ctx["routing_sid"],
            "AI_BRIDGE_TOKEN": ctx["token"],
            "AI_SESSION_ID": str(ctx["session_id"]),
            "AI_ALLOWED_TOOLS": ",".join(
                t for t in ctx["allowed_tools"] if t not in WEB_TOOLS),
            "AI_EXCLUDED_MODELS": ",".join(ctx["excluded_models"]),
        }
        return [
            "-c", "mcp_servers.odoo.command=%s" % _toml_str(ctx["python_bin"]),
            "-c", "mcp_servers.odoo.args=[%s]" % _toml_str(ctx["bridge_script"]),
            "-c", "mcp_servers.odoo.env=%s" % _toml_inline_table(bridge_env),
        ]

    def _compose_prompt(self, ctx):
        """Codex `exec` has no --append-system-prompt; fold the system prompt and
        the per-user identity block into the prompt text instead. The full system
        prompt is included on the first turn; the identity block (which reflects
        the current tool grant) is included every turn."""
        parts = []
        if ctx["is_first"]:
            parts.append(SYSTEM_PROMPT)
        parts.append(ctx["identity"])
        parts.append("--- USER MESSAGE ---\n" + ctx["prompt"])
        return "\n\n".join(parts)

    def _build_env(self, ctx):
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            # Subscription-only: force ChatGPT auth, never an API key.
            "CODEX_API_KEY": "",
        }
        env.update(ctx["codex_env"])
        return env
