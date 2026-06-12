# Changelog

All notable changes to **Codexoo** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
Odoo-style versioning (`17.0.MAJOR.MINOR.PATCH`). Add new entries under
`## [Unreleased]`; a maintainer assigns the version at release time.

## [Unreleased]

### Fixed
- **ChatGPT device-code login** — extract the current Codex CLI code format
  (4-then-5, e.g. `IL70-LNADU`) and strip ANSI escapes from the captured output.
  The old 4-4 pattern missed the code, which both stalled the verification page
  by the full capture timeout and leaked raw `[90m…` ANSI text into the login
  gate.

### Added
- **Contribution gates** — a `pr-checks` CI workflow (CHANGELOG, DCO sign-off,
  SECURITY.md-when-relevant, flake8) plus branch protection, and `CONTRIBUTING.md`
  guidance covering AI-assisted contributions and the Developer Certificate of
  Origin (`DCO`).

## [17.0.1.0.3] — 2026-06-11

### Changed
- **App icon** now uses the OpenAI logomark, reflecting the OpenAI Codex engine
  that powers Codexoo.

[17.0.1.0.3]: https://github.com/cicdoo/codexoo/releases/tag/17.0.1.0.3

## [17.0.1.0.2] — 2026-06-11

### Added
- **Max Concurrent Runs** setting (`codexoo.max_concurrent_runs`, under
  *Settings → Codexoo AI Assistant*) — a soft global cap on how many CLI
  subprocesses may run at once across all users, to bound peak memory and
  protect the host from OOM. `0` = unlimited.

[17.0.1.0.2]: https://github.com/cicdoo/codexoo/releases/tag/17.0.1.0.2

## [17.0.1.0.1] — First public release

First open-source release of Codexoo, an in-Odoo AI assistant that drives the
OpenAI Codex CLI over a sandboxed, permission-aware bridge.

### Features
- **Chat client action** (OWL) with real-time streaming over the Odoo bus.
- **Permission-aware ORM tools** — every action runs as the *current user*
  (never superuser); `ir.model.access` and record rules are always enforced.
- **Read-only SQL reporting** (`sql_select`) gated to the *AI SQL Analyst* group,
  guarded by a SELECT-only text validator plus Postgres `SET TRANSACTION READ ONLY`
  and a statement timeout.
- **Per-user ChatGPT login** ("Login with ChatGPT", device-code flow) — no shared
  API key; credentials are stored privately per user in a `CODEX_HOME`, mode `0600`,
  never in the database.
- **Read-only sandbox** — Codex runs with approvals disabled and no host
  write/network access; the model can act *only* through the `mcp__odoo__*` tools.
  The authoritative boundary is server-side (loopback `codexoo_bridge` token +
  per-user ACLs).
- **Immutable audit log** (`codexoo.tool_log`) written on a separate committed
  cursor so it survives rollbacks.
- **Zero-trust mode** (global default + per-user override) that strips all write
  tools.
- **Test suite** covering the SQL guard, bridge-token mint/verify, tool-access
  policy, the `codexoo_bridge` auth method, and the audit log.

### Licensing
- **Dual-licensed**: open-source **LGPL-3.0-or-later** *or* a **commercial license**
  from CICDoo (see `COMMERCIAL_LICENSE.md`). Every source file carries an SPDX
  `LGPL-3.0-or-later OR LicenseRef-Codexoo-Commercial` notice.
- Runs on **both Odoo Community and Enterprise** editions (depends only on
  Community modules: `web`, `bus`, `mail`).

[17.0.1.0.1]: https://github.com/cicdoo/codexoo/releases/tag/17.0.1.0.1
