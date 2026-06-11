# odysseus-patches

[![PyPI](https://img.shields.io/pypi/v/odysseus-patches)](https://pypi.org/project/odysseus-patches/)
[![Python](https://img.shields.io/pypi/pyversions/odysseus-patches)](https://pypi.org/project/odysseus-patches/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![CI](https://github.com/botinate/odysseus-patches/actions/workflows/ci.yml/badge.svg)](https://github.com/botinate/odysseus-patches/actions/workflows/ci.yml)

Apply open upstream [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
PRs to your own install as tracked, SHA-pinned patches — re-applied across
updates while the PR is open, retired automatically once it merges, flagged
when it conflicts. CLI + a web panel inside Odysseus's own UI.

> **Community project — not affiliated with or endorsed by the Odysseus
> maintainers.** If they ever want this in core, the migration offer stands:
> AGPL-3.0 license and upstream CLI conventions are deliberate.

## Quick start

```bash
pipx install odysseus-patches                    # install (or: brew install botinate/tap/odysseus-patches)
cd /path/to/your/odysseus
odysseus-patches add 3681                         # apply an open upstream PR, pinned to a SHA you review
odysseus-patches install-ui                       # (optional) add a Patches panel to Odysseus's sidebar
```

Then restart Odysseus. Full install options and every command are below.

## Why

The Odysseus community ships fixes faster than upstream merges them. When the
bug you're hitting has an open PR, you shouldn't have to choose between
waiting weeks and hand-maintaining a fork.

## Install

```bash
pipx install odysseus-patches            # PyPI (recommended)
pipx install 'odysseus-patches[mcp]'     # + MCP status server for the agent

brew install botinate/tap/odysseus-patches   # Homebrew (macOS/Linux)
```

No clone needed. If a release hasn't landed on PyPI/Homebrew yet, install
straight from git (works today, still no clone):

```bash
pipx install git+https://github.com/botinate/odysseus-patches
```

It's a single self-contained tool with no runtime dependencies, so any of
these put one `odysseus-patches` command on your PATH (the web panel finds it
automatically). Requirements: a **git-checkout** install of Odysseus (any
platform — the Docker flow builds from the working tree, so patches reach
containers on rebuild). Zip-download installs cannot be patched.

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

`install-ui` **auto-registers** a read-only MCP server in Odysseus (a row in its
`mcp_servers` table, with the absolute interpreter path so there's no PATH
guesswork) — restart Odysseus and the agent gets the tools, no manual
integration setup. `uninstall-ui` removes it.

The MCP server needs the `mcp` package in the Python that runs it, so register
from an environment that has it: run `install-ui` with Odysseus's own venv
(`/path/to/odysseus/venv/bin/odysseus-patches -C /path/to/odysseus install-ui`,
its venv already has `mcp`), or `pipx install 'odysseus-patches[mcp]'`. To run
the server by hand: `odysseus-patches -C /path/to/odysseus mcp`.

Tools: `list_patches`, `patch_status`, `propose_patch`. The agent can report
patch state and *propose* patches (optionally pre-reviewed by AI) — but
applying always requires a human `approve`. The agent cannot apply, upgrade,
or remove anything by design.

## Web UI panel (optional)

Manage patches inside Odysseus's own interface instead of the terminal:

```bash
odysseus-patches install-ui      # injects the panel into your Odysseus install
# ...restart Odysseus, then open Tools -> Patches (admin only)
odysseus-patches uninstall-ui    # remove it
```

It is **not** a separate server and **not** an upstream PR: `install-ui` drops two
files into your Odysseus install and adds one line to its `app.py`, all owned by
this extension and reapplied automatically when you run `odysseus-patches update`.
The panel reuses Odysseus's own admin login and themes (no new auth — it's
admin-only, behind your existing login), and uses Odysseus's own notifications.

From the panel (Tools → Patches, admin only) you can do everything the CLI does
short of git surgery: **add a PR** (with an optional AI review), **upgrade**,
**approve/reject** agent proposals, **remove**, **review**, view **diffs**,
**check for updates**, and set your **API token** under Settings. Applied changes
take effect on the next Odysseus restart.

## AI security review (optional)

`add`/`upgrade`/`approve` can ask your own Odysseus instance to review the
diff for vulnerabilities and sketchy code before anything is applied (uses
your default model — one-time setup: an Odysseus API token with chat scope,
`odysseus-patches config set api_token <token>`). Findings urge you to report
the PR and require an explicit "install anyway". A clean review is evidence,
not proof — review sensitive diffs yourself.

## Branch model & safety

Patches live on a generated **`patched`** branch (= `dev` + one squashed
`[patch] PR#N` commit per patch). Your checkout sits on `patched` when patches
are active and on `dev` when none are. `patched` is a **build artifact** —
every `add`/`approve`/`upgrade`/`remove`/`update` rebuilds it from scratch
(`git checkout -B patched dev`).

Because of that, **don't develop on the `patched` branch** — any commit you make
there that isn't a managed `[patch]` commit gets discarded on the next rebuild.
Branch your own work off `dev` instead. The tool guards both footguns and
**refuses** (rather than silently switching or discarding) when:

- you run a patch command while the checkout is on one of your own branches
  (not `dev`/`patched`), or
- `patched` carries commits that aren't managed patches.

Pass `--force` to override a guard if you really mean it. The web panel's status
and the MCP `patch_status` tool surface the same warnings.

## Security model

Applying a patch is running someone else's code. Mitigations: you review the
diff(stat) at `add`/`upgrade` time; the SHA you reviewed is what keeps being
applied; updates never adopt new PR content without an explicit `upgrade`. The
web panel is admin-only (Odysseus's own login) and is excluded from the agent's
generic API bridge, so the agent can report but never apply.

## License

AGPL-3.0 — same as upstream Odysseus, so this code can migrate into core
without relicensing.
