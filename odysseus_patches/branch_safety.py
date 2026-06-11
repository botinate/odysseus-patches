"""Guard the checkout's git state before mutating patch operations.

`patched` is a generated branch rebuilt with `git checkout -B patched dev`, so
(a) running a patch command from a user's own branch would silently switch them
onto `patched`, and (b) any non-`[patch]` commit a user made on `patched` would
be discarded on the next rebuild. Both are hard-refused (with a `--force`
escape hatch) so neither can happen by accident.
"""
from __future__ import annotations

from .gitops import GitRepo, PATCHED_BRANCH

PATCH_COMMIT_PREFIX = "[patch] "


class BranchSafetyError(Exception):
    pass


def foreign_commits_on_patched(repo: GitRepo, base_branch: str) -> list[str]:
    """`"<sha> <subject>"` lines for commits on `patched` that are NOT managed
    `[patch]` commits — i.e. work a user committed onto the generated branch.
    Empty when `patched` doesn't exist."""
    if not repo.run("branch", "--list", PATCHED_BRANCH).strip():
        return []
    from .gitops import GitError
    try:
        out = repo.run("log", "--format=%h %s", f"{base_branch}..{PATCHED_BRANCH}")
    except GitError:
        return []
    foreign = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        _sha, _, subject = line.partition(" ")
        if not subject.startswith(PATCH_COMMIT_PREFIX):
            foreign.append(line)
    return foreign


def check_branch_safety(repo: GitRepo, base_branch: str, *, force: bool = False) -> None:
    """Raise BranchSafetyError unless it's safe to run a mutating patch command:
    the checkout must be on `base_branch` or `patched`, and `patched` must carry
    only managed `[patch]` commits. `force=True` bypasses all checks."""
    if force:
        return
    cur = repo.current_branch()
    if cur not in (base_branch, PATCHED_BRANCH):
        raise BranchSafetyError(
            f"the checkout is on branch '{cur}', but odysseus-patches manages "
            f"'{base_branch}' and '{PATCHED_BRANCH}'. Switch back with "
            f"`git checkout {base_branch}` first, or pass --force to override."
        )
    foreign = foreign_commits_on_patched(repo, base_branch)
    if foreign:
        listed = "\n  ".join(foreign[:5])
        raise BranchSafetyError(
            f"the '{PATCHED_BRANCH}' branch has commits that are not managed "
            f"patches — it looks like work was committed here:\n  {listed}\n"
            f"Move them to a real branch (e.g. `git branch saved-work {PATCHED_BRANCH}`) "
            "before patching, or pass --force to discard them on the next rebuild."
        )
