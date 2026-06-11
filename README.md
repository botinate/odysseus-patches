# odysseus-patches

Apply open upstream [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
PRs to your own install as tracked, SHA-pinned patches — re-applied across
updates while the PR is open, retired automatically once it merges, flagged
when it conflicts.

> **Community project — not affiliated with or endorsed by the Odysseus
> maintainers.** If they ever want this in core, the migration offer stands:
> AGPL-3.0 license and upstream CLI conventions are deliberate.

## Why

The Odysseus community ships fixes faster than upstream merges them. When the
bug you're hitting has an open PR, you shouldn't have to choose between
waiting weeks and hand-maintaining a fork.

## Install

```bash
pipx install odysseus-patches            # CLI only
pipx install 'odysseus-patches[mcp]'     # + MCP status server for the agent
```

Requirements: a git-checkout install of Odysseus (any platform — the Docker
flow builds from the working tree, so patches reach containers on rebuild).
Zip-download installs cannot be patched.

## Use

```bash
cd /path/to/odysseus
odysseus-patches add 3681        # review diffstat, confirm, apply pinned
odysseus-patches list
odysseus-patches update          # instead of `git pull --ff-only`
odysseus-patches upgrade 3681    # PR got new commits: review + re-pin
odysseus-patches remove 3681
odysseus-patches install-hook update_windows.bat   # wire into your updater
```

`update` exit codes: `0` nothing changed · `10` updated, rebuild/restart
Odysseus · `20` a patch needs attention · `1` error.

## How it works

Your tracked branch (`dev`) never carries local commits, so upstream's
`git pull --ff-only` always works. Patches live as squashed commits on a
generated `patched` branch, rebuilt from `data/patches/manifest.json` on
every update. PR content is fetched only from the upstream repo's own
`refs/pull/N/head` namespace and pinned to the commit SHA you reviewed —
a force-pushed PR can never silently change what your install runs.

## Agent visibility (optional)

Add the read-only MCP server in Odysseus → integrations (stdio):

- command: `odysseus-patches-mcp`
- args: `["--checkout", "/path/to/odysseus"]`

Tools: `list_patches`, `patch_status`. The agent can report patch state;
it cannot apply, upgrade, or remove anything by design.

## Security model

Applying a patch is running someone else's code. Mitigations: you review the
diff(stat) at `add`/`upgrade` time; the SHA you reviewed is what keeps being
applied; updates never adopt new PR content without an explicit `upgrade`.

## License

AGPL-3.0 — same as upstream Odysseus, so this code can migrate into core
without relicensing.
