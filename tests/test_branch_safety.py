import pytest

from odysseus_patches.branch_safety import (
    BranchSafetyError,
    check_branch_safety,
    foreign_commits_on_patched,
)
from odysseus_patches.gitops import GitRepo, PATCHED_BRANCH, rebuild_patched
from odysseus_patches.manifest import Patch
from tests.conftest import git


def _tracked(pr, sha, title="a fix"):
    return Patch(pr=pr, title=title, pinned_sha=sha)


def test_on_dev_is_safe(checkout):
    repo = GitRepo(checkout)
    check_branch_safety(repo, "dev")  # does not raise


def test_on_patched_is_safe(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [_tracked(7, sha)])
    assert repo.current_branch() == PATCHED_BRANCH
    check_branch_safety(repo, "dev")  # patched is managed → safe


def test_on_foreign_branch_refuses(checkout):
    repo = GitRepo(checkout)
    repo.run("checkout", "-b", "my-feature")
    with pytest.raises(BranchSafetyError, match="my-feature"):
        check_branch_safety(repo, "dev")


def test_force_bypasses_foreign_branch(checkout):
    repo = GitRepo(checkout)
    repo.run("checkout", "-b", "my-feature")
    check_branch_safety(repo, "dev", force=True)  # no raise


def test_foreign_commit_on_patched_refuses(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [_tracked(7, sha)])
    # user commits their OWN work onto the patched branch
    (checkout / "mywork.txt").write_text("hi\n", encoding="utf-8")
    git("add", "-A", cwd=checkout)
    git("commit", "-m", "my own work", cwd=checkout)

    foreign = foreign_commits_on_patched(repo, "dev")
    assert any("my own work" in f for f in foreign)
    with pytest.raises(BranchSafetyError, match="not managed"):
        check_branch_safety(repo, "dev")


def test_managed_patch_commits_are_not_foreign(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [_tracked(7, sha)])
    assert foreign_commits_on_patched(repo, "dev") == []
    check_branch_safety(repo, "dev")  # only [patch] commits → safe


def test_no_patched_branch_means_no_foreign(checkout):
    repo = GitRepo(checkout)
    assert foreign_commits_on_patched(repo, "dev") == []
