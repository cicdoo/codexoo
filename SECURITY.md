# Security Policy

Codexoo bridges a large-language-model agent to your Odoo database, so we take
security seriously and welcome responsible disclosure.

## Supported versions

| Version  | Supported |
|----------|-----------|
| 17.0.x   | ✅        |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, email **security@cicdoo.com** with:

- a description of the issue and its impact,
- steps to reproduce (a proof-of-concept is ideal),
- the Codexoo version and your Odoo version.

We aim to acknowledge reports within **3 business days** and to provide a
remediation timeline after triage. We will credit reporters in the release notes
unless you prefer to remain anonymous.

## Scope & design notes

Codexoo's threat model assumes the LLM output is **untrusted**. The defenses that
are in scope for security reports include:

- **No superuser execution** — tool endpoints abort if `request.env.su` is true;
  every ORM call runs as the acting user with `ir.model.access` + record rules.
- **Read-only SQL** — `sql_select` is validated (SELECT/WITH only, no stacked
  statements, no row locks, no dangerous functions) *and* executed under
  `SET TRANSACTION READ ONLY` with a statement timeout.
- **Capability tokens** — the MCP bridge holds only a short-lived, session-scoped
  HMAC bearer token (no DB credentials) and is reachable on loopback only via the
  `codexoo_bridge` auth method.
- **Read-only sandbox** — Codex is launched with approvals disabled and no host
  write/network access, so it cannot reach the shell, filesystem, or network on
  its own; it acts only through the `mcp__odoo__*` tools. The authoritative
  boundary is server-side (the loopback bridge token + per-user ACLs).
- **Per-user credential isolation** — ChatGPT login credentials are stored per user
  in a private `CODEX_HOME` with mode `0600` and never exposed on a record.
- **Sandboxed report/chart rendering** — HTML the model emits (charts, reports,
  and `codexoo.session._post_report` output) is rendered in an
  `<iframe sandbox="allow-same-origin">` **without** `allow-scripts`, so its own
  scripts never execute and its styles are isolated from the Odoo UI; the parent
  only reads the frame to size it. `allow-scripts` is deliberately never combined
  with `allow-same-origin` (that pairing lets a frame drop its own sandbox).

If you find a way to (a) escalate beyond the acting user's ACLs, (b) mutate data
through `sql_select`, (c) forge or replay a bridge token, (d) make the model
affect Odoo or the host outside the `mcp__odoo__*` tool surface, or (e) execute
script or escape the iframe sandbox via rendered model HTML, that is a security
bug — please report it.
