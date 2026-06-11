"""Git plumbing: a thin subprocess wrapper plus the patched-branch builder.

All patch content enters through `git fetch origin refs/pull/N/head` — these
refs live on the base repo for every PR regardless of fork, so no third-party
remote is ever added. Fetched heads are stored under refs/odypatches/pr/N so
re-applying pinned SHAs works offline.
Commits created on the patched branch are authored as odysseus-patches <odysseus-patches@local.invalid> regardless of the user's git identity, so artifact commits are recognizable and hermetic on CI.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .manifest import Patch

PATCHED_BRANCH = "patched"
PR_REF = "refs/odypatches/pr/{pr}"

APPLY_OK = "applied"
APPLY_CONFLICT = "conflict"
APPLY_EMPTY = "empty"  # changes already present upstream -> retire


class GitError(Exception):
    pass


class GitRepo:
    def __init__(self, root: Path):
        self.root = Path(root)

    def run(self, *args: str, check: bool = True) -> str:
        # For commit invocations, inject an identity so tests pass on CI machines
        # that have no global git config (the sandbox GIT_CONFIG_GLOBAL=/dev/null
        # suppresses identity in fixture-driven git() calls, but GitRepo inherits
        # the process env; adding identity here is the pre-approved deviation).
        extra_config: list[str] = []
        if args and args[0] == "commit":
            extra_config = [
                "-c", "user.name=odysseus-patches",
                "-c", "user.email=odysseus-patches@local.invalid",
            ]
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *extra_config, *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise GitError(
                f"git {shlex.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout.strip()

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def rev_parse(self, ref: str) -> str:
        return self.run("rev-parse", ref)

    def is_dirty(self) -> bool:
        return bool(self.run("status", "--porcelain"))

    def fetch_pr_head(self, pr: int) -> str:
        """Fetch refs/pull/N/head into a local ref; return its SHA."""
        local = PR_REF.format(pr=pr)
        self.run("fetch", "origin", f"refs/pull/{pr}/head:{local}", "--force")
        return self.rev_parse(local)

    def merge_base(self, a: str, b: str) -> str:
        return self.run("merge-base", a, b)

    def diffstat(self, base: str, head: str) -> str:
        return self.run("diff", "--stat", f"{base}..{head}")


def rebuild_patched(repo: GitRepo, base_branch: str, patches: list[Patch]) -> dict[int, str]:
    """Rebuild the patched branch from base + the given patches.

    Idempotent: the branch is recreated from scratch every time; the manifest
    is the source of truth and this branch is a build artifact. One failing
    patch never blocks the others. With no patches, the checkout returns to
    the base branch and the artifact branch is deleted.

    Returns {pr: APPLY_OK | APPLY_CONFLICT | APPLY_EMPTY}.
    """
    if not patches:
        if repo.current_branch() == PATCHED_BRANCH:
            repo.run("checkout", base_branch)
        repo.run("branch", "-D", PATCHED_BRANCH, check=False)
        return {}

    # a previous run may have died mid-cherry-pick, leaving CHERRY_PICK_HEAD
    # behind; --quit forgets it without touching the working tree (a genuinely
    # dirty tree still fails loudly at the checkout below — fail closed)
    repo.run("cherry-pick", "--quit", check=False)

    repo.run("checkout", "-B", PATCHED_BRANCH, base_branch)
    results: dict[int, str] = {}
    for patch in patches:
        local_ref = PR_REF.format(pr=patch.pr)
        base = repo.merge_base(PATCHED_BRANCH, patch.pinned_sha)
        proc = subprocess.run(
            [
                "git", "-c", "commit.gpgsign=false",
                "cherry-pick", "--no-commit", f"{base}..{patch.pinned_sha}",
            ],
            cwd=repo.root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            subprocess.run(
                ["git", "cherry-pick", "--abort"],
                cwd=repo.root, capture_output=True, text=True,
            )
            repo.run("reset", "--hard", "HEAD")
            results[patch.pr] = APPLY_CONFLICT
            continue
        staged = repo.run("diff", "--cached", "--name-only")
        if not staged:
            repo.run("reset", "--hard", "HEAD")
            results[patch.pr] = APPLY_EMPTY
            continue
        repo.run("commit", "-m", f"[patch] PR#{patch.pr} {patch.title}")
        results[patch.pr] = APPLY_OK
        # keep the local pin ref alive even if fetch never reran
        repo.run("update-ref", local_ref, patch.pinned_sha)
    return results


def _patch_id_of_diff(repo: GitRepo, diff_text: str) -> str:
    """Stable patch-id for a diff, '' when the diff is empty."""
    if not diff_text.strip():
        return ""
    proc = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=repo.root,
        input=diff_text,
        capture_output=True,
        text=True,
    )
    out = proc.stdout.strip()
    return out.split()[0] if out else ""


def merged_upstream_prs(
    repo: GitRepo, old_base: str, new_base: str, patches: list[Patch]
) -> set[int]:
    """Offline fallback for 'did this PR merge?': patch-id equivalence.

    Compares each patch's squashed diff against every commit that arrived on
    the base branch between old_base and new_base. Exact squash-merges match;
    merges with review tweaks won't (the empty-cherry-pick detector covers
    most of those at apply time). Best-effort by design.
    """
    if old_base == new_base or not patches:
        return set()
    upstream_ids = set()
    for sha in repo.run("rev-list", f"{old_base}..{new_base}").splitlines():
        diff = repo.run("diff-tree", "-p", "--no-commit-id", sha)
        pid = _patch_id_of_diff(repo, diff)
        if pid:
            upstream_ids.add(pid)
    merged = set()
    for patch in patches:
        base = repo.merge_base(old_base, patch.pinned_sha)
        diff = repo.run("diff", f"{base}..{patch.pinned_sha}")
        pid = _patch_id_of_diff(repo, diff)
        if pid and pid in upstream_ids:
            merged.add(patch.pr)
    return merged
