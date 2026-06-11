# Changelog

All notable changes to **Codexoo** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
Odoo-style versioning (`<odoo-series>.MAJOR.MINOR.PATCH`, e.g. `18.0.1.0.0`). Add new
entries under `## [Unreleased]`; a maintainer assigns the version at release time.

## [Unreleased]

### Added
- **Contribution gates** — a `pr-checks` CI workflow (CHANGELOG, DCO sign-off,
  SECURITY.md-when-relevant, flake8) plus branch protection, and `CONTRIBUTING.md`
  guidance covering AI-assisted contributions and the Developer Certificate of
  Origin (`DCO`).

## [18.0.1.0.1] — 2026-06-11

### Changed
- **App icon** now uses the OpenAI logomark, reflecting the OpenAI Codex engine
  that powers Codexoo.

[18.0.1.0.1]: https://github.com/cicdoo/codexoo/releases/tag/18.0.1.0.1

## [18.0.1.0.0] — 2026-06-11

### Changed
- **Ported to Odoo 18.0.** Functionally identical to `17.0.1.0.2`; only the
  framework APIs that changed between Odoo 17 and 18 were updated:
  - Controllers use the unified `check_access()` / `has_access()` instead of the
    split `check_access_rights()` + `check_access_rule()`.
  - Bus streaming uses the record-level `partner._bus_send()` instead of
    `bus.bus._sendone()`.
  - The chat client action imports `rpc` from `@web/core/network/rpc` (the `rpc`
    service was removed in 18) instead of `useService("rpc")`.
  - The audit-log view uses `<list>` / `view_mode="list,form"` instead of
    `<tree>` / `view_mode="tree,form"`.

[18.0.1.0.0]: https://github.com/cicdoo/codexoo/releases/tag/18.0.1.0.0

## [17.0.1.0.2] — 2026-06-11

### Added
- **Max Concurrent Runs** setting (`codexoo.max_concurrent_runs`, under
  *Settings → Codexoo AI Assistant*) — a soft global cap on how many CLI
  subprocesses may run at once across all users, to bound peak memory and
  protect the host from OOM. `0` = unlimited.

### Changed
- **Dropped the unused `mail` dependency** — the addon drives `web` and `bus`
  directly and never used any `mail` feature; `depends` is now `['web', 'bus']`.

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
