## What does this PR do?

<!-- A short summary of the change and the motivation. Link any issue: Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / chore

## Checklist

- [ ] Targets Odoo 17.0 and follows the existing code style
- [ ] Added/updated tests under `tests/` (tagged `codexoo`); CI is green
- [ ] Updated `CHANGELOG.md`
- [ ] Tool endpoints still run **as the user, never superuser**
- [ ] Did not alter Codex engine references (ChatGPT/device-code login, `CODEX_HOME`,
      CLI glob, `codex_thread_id` / `codex_item_id`)
- [ ] For security-sensitive changes: invariants in `SECURITY.md` are preserved
