# Security Policy

## Reporting a vulnerability

Please report security issues **privately** via a GitHub Security Advisory:
https://github.com/botinate/odysseus-patches/security/advisories/new

Do not open a public issue for a vulnerability.

## Scope worth flagging

This tool applies third-party code (upstream PRs) to a self-hosted install, and
ships a panel that runs inside Odysseus. Reports especially welcome for:

- ways the agent (or a non-admin user) could apply/approve a patch it shouldn't,
- the `install-ui` injection or its routes bypassing Odysseus's admin gate,
- the AI-review path being trickable into a false "clean" verdict,
- any path where a patch's content reaches execution without the pinned-SHA
  review step.

A clean AI review is evidence, not proof — applying a patch is always running
someone else's code. That's an inherent property, not a vulnerability.
