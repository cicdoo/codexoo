## What does this PR do?

<!-- A short summary of the change and the motivation. Link any issue: Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / chore

## Checklist

- [ ] Targets Odoo 18.0 and follows the existing code style
- [ ] Added/updated tests under `tests/` (tagged `codexoo`) and they pass locally
- [ ] Updated `CHANGELOG.md` (bullet under `## [Unreleased]`)
- [ ] Updated `SECURITY.md` if this touches a safety-critical path (else N/A)
- [ ] All commits are signed off (`git commit -s` → DCO)
- [ ] I am the author and have reviewed/understand **all** code here, including any AI-assisted parts, and it is mine to license
- [ ] Tool endpoints still run **as the user, never superuser**
- [ ] Did not alter Codex engine references (ChatGPT/device-code login, `CODEX_HOME`,
      CLI glob, `codex_thread_id` / `codex_item_id`)
- [ ] For security-sensitive changes: invariants in `SECURITY.md` are preserved
