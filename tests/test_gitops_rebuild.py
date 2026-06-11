from odysseus_patches.gitops import (
    APPLY_CONFLICT,
    APPLY_EMPTY,
    APPLY_OK,
    GitRepo,
    PATCHED_BRANCH,
    rebuild_patched,
)
from odysseus_patches.manifest import Patch
from tests.conftest import git


def tracked(pr, sha, title="a fix"):
    return Patch(pr=pr, title=title, pinned_sha=sha)


def test_clean_apply_creates_branch_with_patch_commit(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)

    results = rebuild_patched(repo, "dev", [tracked(7, sha)])

    assert results == {7: APPLY_OK}
    assert repo.current_branch() == PATCHED_BRANCH
    assert (checkout / "src" / "fix.py").exists()
    log = git("log", "--oneline", "-1", cwd=checkout)
    assert "[patch] PR#7" in log


def test_conflict_is_skipped_and_others_apply(upstream, checkout):
    good = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: good")
    bad = upstream.open_pr(8, "src/app.py", "CONFLICT = 'pr'\n", "fix: bad")
    # upstream dev moves over the same file the bad PR touches
    upstream.commit_on_dev("src/app.py", "VERSION = 2\nGREETING = 'hi'\n", "bump")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    repo.fetch_pr_head(7)
    repo.fetch_pr_head(8)

    results = rebuild_patched(repo, "dev", [tracked(7, good), tracked(8, bad)])

    assert results[7] == APPLY_OK
    assert results[8] == APPLY_CONFLICT
    assert (checkout / "src" / "fix.py").exists()
    assert repo.is_dirty() is False  # aborted pick leaves nothing behind


def test_already_merged_content_reports_empty(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    upstream.squash_merge_pr(sha, "fix: something (#7)")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    repo.fetch_pr_head(7)

    results = rebuild_patched(repo, "dev", [tracked(7, sha)])

    assert results == {7: APPLY_EMPTY}


def test_no_patches_returns_to_base_and_drops_branch(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [tracked(7, sha)])

    results = rebuild_patched(repo, "dev", [])

    assert results == {}
    assert repo.current_branch() == "dev"
    branches = git("branch", "--list", PATCHED_BRANCH, cwd=checkout)
    assert branches == ""


def test_rebuild_is_idempotent(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [tracked(7, sha)])
    first = repo.rev_parse("HEAD^{tree}")
    rebuild_patched(repo, "dev", [tracked(7, sha)])
    assert repo.rev_parse("HEAD^{tree}") == first
