<!--
Before opening: for anything beyond a small fix, there should be an issue first
that the maintainer has agreed to. PRs that don't follow this template, have no
linked issue, or bundle unrelated changes may be closed without review.
-->

## Summary

<!-- One paragraph: what changes and why. -->

## Linked issue

<!-- Required for features; strongly preferred for fixes. -->
Closes #

## Type of change

- [ ] Bug fix
- [ ] New feature (has an agreed-upon issue)
- [ ] Docs / packaging / CI
- [ ] Refactor (no behavior change)

## Checklist

- [ ] PR **title follows Conventional Commits** (`type(scope): subject`, e.g. `fix(cli): …`).
- [ ] One focused change — no unrelated edits bundled in.
- [ ] `pytest` passes locally (`pip install -e ".[dev]" && pytest`).
- [ ] New behavior has tests.
- [ ] I read CONTRIBUTING.md.

## How to test

<!-- Steps a reviewer can follow. -->
