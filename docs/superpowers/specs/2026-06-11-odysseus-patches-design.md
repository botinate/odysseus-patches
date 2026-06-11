# odysseus-patches — Design Spec

**Date:** 2026-06-11
**Status:** Approved design, pre-implementation
**Repo:** standalone community project (not part of upstream Odysseus); target home `botinate/odysseus-patches`
**License:** AGPL-3.0 (matches upstream Odysseus, so code can migrate into core with no relicensing)

## Purpose

Odysseus's community produces fixes faster than upstream merges them. Users who hit a bug
often find an open PR that fixes it — and then wait weeks. `odysseus-patches` lets a
self-hosting operator apply open upstream PRs to their own install as tracked, pinned
patches, and keeps those patches healthy across updates: re-applied while the PR is open,
retired automatically once it merges, flagged when it conflicts.

This is an external companion tool by design. It uses only stable public contracts —
the git checkout layout, the `data/` directory, GitHub's `refs/pull/*` namespace, and the
MCP protocol — and never imports Odysseus code. That keeps it working across upstream
refactors and keeps a later migration into core cheap (see "Migration plan").

## Goals

- Add an open upstream PR to a local install by number, pinned to a reviewed commit SHA.
- Survive `git pull --ff-only`-based updates (the upstream-documented update flow).
- Auto-retire patches whose PR merged upstream; flag closed-unmerged and conflicted ones.
- Give the Odysseus agent read-only visibility via an optional MCP server.
- Work on every install type that is a git checkout (manual, macOS, Windows, Docker —
  `update_windows.bat` builds images from the working tree, so a patched tree reaches
  Docker on rebuild).

## Non-goals

- Applying arbitrary diffs/files that are not upstream PRs (no upstream identity → no
  lifecycle automation). May be revisited later.
- Mutating a running server from inside the app. All mutation is CLI-side, app stopped.
- An in-app settings card / startup banner — cut from the standalone variant; returns if
  the tool migrates into core.
- Patch distribution/curation ("store"). The unit is an upstream PR; GitHub is the store.

## Architecture

Three components in one Python package:

```
odysseus-patches/
├── odysseus_patches/          # the library — all logic lives here
│   ├── manifest.py            # manifest load/save/validate
│   ├── github.py              # PR metadata + refs/pull fetch (gh CLI, REST fallback)
│   ├── gitops.py              # branch build, cherry-pick, patch-id scan
│   ├── planner.py             # pure function: manifest + PR states -> action plan
│   ├── update.py              # the update orchestration
│   └── mcp_server.py          # optional read-only stdio MCP server
├── bin/odysseus-patches       # thin CLI; follows upstream scripts/odysseus-* conventions
│                              # (shebang + first docstring line = dispatcher help text)
├── tests/                     # pytest, upstream-style
├── LICENSE                    # AGPL-3.0
└── README.md                  # includes "community project, not official" disclaimer
```

The CLI file is deliberately shaped so that migrating into upstream means copying
`bin/odysseus-patches` into `scripts/` and vendoring the lib into `scripts/_lib/` —
their `odysseus` dispatcher discovers `odysseus-*` siblings by filename and parses the
docstring for help text.

## Patch model

A patch **is** an upstream PR, identified by number, pinned to a commit SHA.

`data/patches/manifest.json` (inside the Odysseus checkout's persistent `data/` dir,
which is bind-mounted in Docker and survives updates):

```json
{
  "version": 1,
  "upstream": "pewdiepie-archdaemon/odysseus",
  "patches": [
    {
      "pr": 3055,
      "title": "fix(mcp): bust prompt cache on server connect",
      "pinned_sha": "a1b2c3d4...",
      "status": "active",
      "added_at": "2026-06-11T12:00:00Z",
      "last_result": "applied-clean"
    }
  ]
}
```

`status` ∈ `active | conflicted | retired | closed-upstream`. The manifest is the
**source of truth**; the git branch is a disposable build artifact rebuilt from it.

## Git model: integration branch

- The checkout's tracked branch (`dev`) never carries local commits, so upstream's
  `git pull --ff-only` always succeeds.
- A generated branch `patched` = `dev` HEAD + one commit per active patch (each PR's
  commits squashed into a single `[patch] PR#N <title>` commit, cherry-picked 3-way).
- The checkout sits on `patched` when ≥1 patch is active, on `dev` when none.
- Rebuilding is idempotent: delete + recreate from `dev` + manifest. A failed
  cherry-pick is `--abort`ed, the patch marked `conflicted`, and the rebuild continues
  with the remaining patches — one bad patch never blocks the others or the update.
- PR content is fetched from `git fetch origin refs/pull/N/head` — these refs live on
  the **base** repo for every PR regardless of fork, so no third-party remotes are ever
  added.

## CLI commands

| Command | Behavior |
|---|---|
| `add <pr#>` | Fetch PR meta + ref; show title/author/diffstat (full diff with `--show`); confirm; pin current head SHA; rebuild branch |
| `update` | Full update dance (below) |
| `list` | Table: PR, title, pinned SHA, upstream state, last apply result |
| `show <pr#>` | Full diff, status detail, conflict files if any |
| `upgrade <pr#>` | PR head moved: show **incremental** diff (pinned..head), confirm, re-pin |
| `remove <pr#>` | Drop from manifest, rebuild branch |
| `install-hook` | Insert the `update` call into the local update script (documented, reversible) |

### `update` flow

1. Refuse on dirty working tree (same as git itself); explain why.
2. Switch to `dev`, `git pull --ff-only`.
3. For each manifest patch, classify (see planner):
   - **merged upstream** → status `retired`, announce. Detection: GitHub `merged` flag
     (authoritative); offline fallback: `git patch-id` equivalence scan of new upstream
     commits (catches squash-merges without network).
   - **closed unmerged** → status `closed-upstream`, warn; kept and re-applied until the
     user decides (`remove` or keep).
   - **open, head moved** → re-apply the **pinned** SHA, note "upgrade available".
   - **open, unchanged** → re-apply pinned SHA.
4. Rebuild `patched` from surviving patches; conflicted ones are skipped + marked.
5. Switch back to the right branch; print a per-patch report.
6. Exit code distinguishes "done" / "done, container rebuild needed" / "attention needed"
   so wrapper scripts can react.

Offline/rate-limited: skip merge-detection (step 3 classification degrades to
"open, unchanged"), still re-apply pinned SHAs from local refs. Updates never require
network beyond `git pull` itself.

## GitHub interaction

- Metadata (state, merged, head SHA, title): `gh` CLI when available, else
  unauthenticated REST (`GET /repos/{upstream}/pulls/{N}`) — a handful of PRs per update
  is far below anonymous rate limits.
- Content: only via `refs/pull/N/head` on the upstream remote. Never a fork remote,
  never a tarball.

## Security

- **Applying a patch is running someone's code.** Mitigations: SHA pinning at review
  time; `add`/`upgrade` show the diff(stat) and require confirmation; a force-pushed PR
  can never silently change what's applied (`update` keeps applying the pinned SHA).
- The MCP server is **read-only** (list/status). No agent-reachable apply/remove —
  the LLM can report, not mutate. Upstream's non-admin gating blocks all `mcp__` tools
  for non-admin users automatically.
- `install-hook` edits only the local update script, idempotently, with a marker comment.

## Optional MCP status server

`odysseus_patches/mcp_server.py`, stdio transport, added by the user via Odysseus's
integrations tab (same flow as any community MCP server). Tools:

- `list_patches` — manifest + per-patch upstream state (cached from last `update`)
- `patch_status` — overall health: base commit vs manifest expectations, staleness,
  anything conflicted/retired-pending

Both read-only; no filesystem writes, no subprocess git mutation.

## Error handling

| Condition | Behavior |
|---|---|
| Not a git checkout (zip install) | Clear error + docs link; nothing attempted |
| Dirty working tree on `update` | Refuse, list dirty files, explain |
| Cherry-pick conflict | Abort that pick, mark `conflicted`, continue others, report |
| Network down / rate-limited | Degrade to offline mode (reapply pinned, skip detection) |
| `gh` missing | REST fallback, no behavior change |
| Manifest corrupt | Refuse mutation, print recovery hint (manifest is plain JSON) |

## Testing

- **Unit:** manifest round-trip/validation; planner as a pure function — every
  combination of (manifest status × PR state) is table-tested with no git or network.
- **Integration:** pytest fixture builds a sandbox upstream (bare repo with `dev` and
  synthetic `refs/pull/N/head`), clones it, then walks the lifecycle: add → upstream
  merges (squash) → update → assert retired; the conflict path; the offline path;
  `--ff-only` safety (tracked branch never diverges).
- **Conventions:** pytest, same style as upstream's `tests/` (e.g. their
  `test_windows_update_script.py` precedent for asserting script hooks).

## Community placement & migration plan

1. **Now:** standalone repo under `botinate` (transfer to a community org later is free —
   GitHub preserves redirects). README disclaimer: community project, not affiliated.
2. **Announce** in upstream GitHub Discussions, linking the pain threads (#337, #1789)
   whose participants are the target users.
3. **Listing:** once upstream's `docs/community-mcp-servers.md` (PR #3847) lands, submit
   the MCP server for that list, or propose a `community-tools.md` sibling.
4. **Migration trigger** (stated in README): if/when maintainers want it in core —
   their current focus is infrastructure, not features — the offer stands. Migration =
   copy CLI into `scripts/`, vendor lib into `scripts/_lib/`, replace the MCP server
   with a native tool + settings card, upstream the test suite. AGPL + matched
   conventions mean the PR reads like it was always theirs.

## Out of scope for v1 (explicitly deferred)

- Raw `.diff` file patches (no lifecycle automation possible)
- In-app settings card / startup banner (returns on migration into core)
- Patch sets/profiles, dependency ordering between patches
- Auto-`upgrade` policies (always explicit per the pinning decision)
