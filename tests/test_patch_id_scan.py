from odysseus_patches.gitops import GitRepo, merged_upstream_prs
from odysseus_patches.manifest import Patch
from tests.conftest import git


def test_exact_squash_is_detected(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    old_dev = repo.rev_parse("dev")
    upstream.squash_merge_pr(sha, "fix: something (#7)")
    repo.run("checkout", "dev")
    repo.run("pull", "--ff-only")
    new_dev = repo.rev_parse("dev")

    patch = Patch(pr=7, title="fix: something", pinned_sha=sha)
    assert merged_upstream_prs(repo, old_dev, new_dev, [patch]) == {7}


def test_unmerged_pr_is_not_detected(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    old_dev = repo.rev_parse("dev")
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "unrelated")
    repo.run("pull", "--ff-only")
    new_dev = repo.rev_parse("dev")

    patch = Patch(pr=7, title="fix: something", pinned_sha=sha)
    assert merged_upstream_prs(repo, old_dev, new_dev, [patch]) == set()


def test_no_upstream_movement_short_circuits(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    dev = repo.rev_parse("dev")
    patch = Patch(pr=7, title="fix: something", pinned_sha=sha)
    assert merged_upstream_prs(repo, dev, dev, [patch]) == set()
