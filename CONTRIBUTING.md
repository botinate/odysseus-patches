# Contributing

This is a small, deliberately-focused project. The goal is a steady stream of
high-signal contributions, not volume — so there's a little structure. Please
read this before opening an issue or PR.

## The flow

1. **Bugs** → open a Bug report issue with version + exact repro. Issues without
   those get closed as not-actionable.
2. **Features / changes** → open a Feature request issue **first** and wait for a
   maintainer 👍 before writing code. Unsolicited large PRs (especially bulk or
   AI-generated ones) may be closed without review — open an issue and let's
   agree on the problem first.
3. **Questions / "how do I…"** → GitHub **Discussions**, not the issue tracker.
4. **Security** → report privately via a
   [Security Advisory](https://github.com/botinate/odysseus-patches/security/advisories/new),
   never a public issue.

## Pull requests

- **Scope:** one focused change per PR. No drive-by refactors or unrelated edits.
- **Title — Conventional Commits.** PR titles must be
  `type(scope): subject`, e.g. `fix(cli): handle empty manifest`,
  `feat(ui): add upgrade button`, `docs: …`, `ci: …`, `refactor: …`,
  `test: …`, `chore: …`. A CI check enforces this. We **squash-merge**, so the
  PR title becomes the commit message.
- **Branch name:** mirror the title, e.g. `fix/empty-manifest`, `feat/upgrade-button`.
- **Tests required.** New behavior needs tests; `pytest` must be green. The web
  panel's JS asset is checked with `node --check`.
- **Link an issue** in the PR body (`Closes #NN`).

## Dev setup

```bash
git clone https://github.com/botinate/odysseus-patches
cd odysseus-patches
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest        # all tests
node --check odysseus_patches/ui_assets/patches.js
```

The core is **stdlib-only** by design (no runtime dependencies) — keep it that
way. Test-only deps live in the `dev` extra.

## Design notes

- The CLI is the source of truth; the web panel and MCP server are thin layers
  that shell out to it. Add behavior in the CLI, not in the panel.
- Operations that apply code (anything mutating a patch) must stay human-gated —
  agents can propose, only a human approves.

## License

By contributing you agree your contribution is licensed under the project's
**AGPL-3.0** license.
