"""Read-only status snapshot consumed by the CLI and the MCP server."""
from __future__ import annotations

from dataclasses import asdict

from .branch_safety import foreign_commits_on_patched
from .gitops import GitRepo, PATCHED_BRANCH
from .manifest import Manifest, STATUS_CONFLICTED, STATUS_PROPOSED


def build_status(repo: GitRepo, manifest: Manifest) -> dict:
    appliable = manifest.appliable_patches()
    on_patched = repo.current_branch() == PATCHED_BRANCH
    attention: list[str] = []
    for p in manifest.patches:
        if p.status == STATUS_CONFLICTED:
            attention.append(
                f"PR #{p.pr} is conflicted — `odysseus-patches show {p.pr}` for details"
            )
    if appliable and not on_patched:
        attention.append(
            "patches are tracked but the checkout is not running the patched "
            "branch — run `odysseus-patches update`"
        )
    if appliable and on_patched:
        base_sha = repo.rev_parse(manifest.base_branch)
        if repo.merge_base(PATCHED_BRANCH, manifest.base_branch) != base_sha:
            attention.append(
                f"the patched branch is built on an outdated {manifest.base_branch} "
                "— run `odysseus-patches update` to rebase the patches"
            )
    # foreign (non-managed) commits on patched are a data-loss risk → failure
    foreign = foreign_commits_on_patched(repo, manifest.base_branch)
    if foreign:
        attention.append(
            f"the 'patched' branch has {len(foreign)} commit(s) that are not "
            "managed patches — they will be discarded on the next rebuild; "
            "move them to a real branch")
    # failure states determine health
    healthy = not attention
    # informational guidance: warn users not to develop on the generated branch
    if on_patched:
        attention.append(
            "you are on the generated 'patched' branch — don't develop here; "
            "create feature branches from '" + manifest.base_branch + "'")
    proposals = [p for p in manifest.patches if p.status == STATUS_PROPOSED]
    if proposals:
        attention.append(
            f"{len(proposals)} proposal(s) awaiting approval — "
            "`odysseus-patches approve <pr>` or reject"
        )
    return {
        "upstream": manifest.upstream,
        "base_branch": manifest.base_branch,
        "on_patched_branch": on_patched,
        "patch_count": len(manifest.patches),
        "patches": [asdict(p) for p in manifest.patches],
        "attention": attention,
        "healthy": healthy,
        "pending_action": bool(attention),
    }
