from tests.conftest import git


def test_checkout_tracks_dev(checkout):
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=checkout) == "dev"
    assert (checkout / "src" / "app.py").exists()


def test_pr_ref_is_fetchable(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    git("fetch", "origin", "refs/pull/7/head", cwd=checkout)
    assert git("rev-parse", "FETCH_HEAD", cwd=checkout) == sha


def test_squash_merge_lands_on_dev(upstream, checkout):
    sha = upstream.open_pr(8, "src/fix.py", "FIX = True\n", "fix: something")
    upstream.squash_merge_pr(sha, "fix: something (#8)")
    git("pull", "--ff-only", cwd=checkout)
    assert (checkout / "src" / "fix.py").exists()
