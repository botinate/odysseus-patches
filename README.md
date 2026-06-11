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

*(Not yet on PyPI — until then: `pipx install git+https://github.com/botinate/odysseus-patches` or `pip install -e .` from a clone.)*

Requirements: a git-checkout install of Odysseus (any platform — the Docker
flow builds from the working tree, so patches reach containers on rebuild).
Zip-download installs cannot be patched.

## Use

```bash
cd /path/to/odysseus
odysseus-patches add 3681        # review diffstat, confirm, apply pinned
odysseus-patches add 3681 --review  # ...or have your Odysseus AI security-review the diff first
odysseus-patches list
odysseus-patches update          # instead of `git pull --ff-only`
odysseus-patches upgrade 3681    # PR got new commits: review + re-pin
odysseus-patches remove 3681
odysseus-patches propose 3681    # stage only; approve/reject later
odysseus-patches approve 3681    # apply a staged proposal
odysseus-patches config set api_token <odysseus-api-token>   # one-time, enables AI review
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

Tools: `list_patches`, `patch_status`, `propose_patch`. The agent can report
patch state and *propose* patches (optionally pre-reviewed by AI) — but
applying always requires a human `approve`. The agent cannot apply, upgrade,
or remove anything by design.

## AI security review (optional)

`add`/`upgrade`/`approve` can ask your own Odysseus instance to review the
diff for vulnerabilities and sketchy code before anything is applied (uses
your default model — one-time setup: an Odysseus API token with chat scope,
`odysseus-patches config set api_token <token>`). Findings urge you to report
the PR and require an explicit "install anyway". A clean review is evidence,
not proof — review sensitive diffs yourself.

## Security model

Applying a patch is running someone else's code. Mitigations: you review the
diff(stat) at `add`/`upgrade` time; the SHA you reviewed is what keeps being
applied; updates never adopt new PR content without an explicit `upgrade`.

## License

AGPL-3.0 — same as upstream Odysseus, so this code can migrate into core
without relicensing.
