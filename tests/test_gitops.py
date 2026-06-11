import pytest

from odysseus_patches.gitops import GitError, GitRepo
from tests.conftest import git


def test_run_and_rev_parse(checkout):
    repo = GitRepo(checkout)
    assert repo.current_branch() == "dev"
    assert len(repo.rev_parse("HEAD")) == 40


def test_run_raises_giterror(checkout):
    repo = GitRepo(checkout)
    with pytest.raises(GitError):
        repo.run("rev-parse", "no-such-ref-xyz")


def test_is_dirty(checkout):
    repo = GitRepo(checkout)
    assert repo.is_dirty() is False
    (checkout / "src" / "app.py").write_text("VERSION = 99\n", encoding="utf-8")
    assert repo.is_dirty() is True


def test_fetch_pr_head_pins_sha(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    assert repo.fetch_pr_head(7) == sha
    # the ref is stored locally so offline re-applies keep working
    assert repo.rev_parse("refs/odypatches/pr/7") == sha


def test_diffstat_mentions_file(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    base = repo.merge_base("dev", sha)
    assert "src/fix.py" in repo.diffstat(base, sha)
