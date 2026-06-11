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


def test_rebuild_reestablishes_local_pin_ref(upstream, checkout):
    # the pin ref must survive even when fetch never reran (offline updates):
    # delete it, rebuild from the pinned sha (object is already local), and
    # verify rebuild_patched re-established the ref
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    repo.run("update-ref", "-d", "refs/odypatches/pr/7")
    results = rebuild_patched(repo, "dev", [tracked(7, sha)])
    assert results == {7: APPLY_OK}
    assert repo.rev_parse("refs/odypatches/pr/7") == sha


def test_two_clean_patches_both_apply(upstream, checkout):
    first = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: first")
    second = upstream.open_pr(9, "src/feature.py", "FEATURE = 1\n", "feat: second")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    repo.fetch_pr_head(9)

    results = rebuild_patched(repo, "dev", [tracked(7, first), tracked(9, second)])

    assert results == {7: APPLY_OK, 9: APPLY_OK}
    assert (checkout / "src" / "fix.py").exists()
    assert (checkout / "src" / "feature.py").exists()
    log = git("log", "--oneline", "-2", cwd=checkout)
    assert "[patch] PR#9" in log and "[patch] PR#7" in log


def test_apply_pr_with_merge_commit(upstream, checkout):
    # a PR branch that was "updated" by merging dev — its head is a merge commit.
    # cherry-pick chokes on merge commits; merge --squash must handle it.
    work = upstream.work
    git("checkout", "-b", "pr-merge", "dev", cwd=work)
    (work / "src" / "fix.py").write_text("FIX = True\n", encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "-m", "feat: fix", cwd=work)
    # meanwhile dev advances on an unrelated file...
    git("checkout", "dev", cwd=work)
    (work / "src" / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "-m", "unrelated dev work", cwd=work)
    git("push", "origin", "dev", cwd=work)
    # ...and the PR branch merges dev in (creating a MERGE commit at its head)
    git("checkout", "pr-merge", cwd=work)
    git("merge", "--no-edit", "dev", cwd=work)
    head = git("rev-parse", "HEAD", cwd=work)
    git("push", "origin", "pr-merge:refs/pull/77/head", cwd=work)
    # the user's checkout catches up dev and fetches the PR head
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    repo.fetch_pr_head(77)

    results = rebuild_patched(repo, "dev", [tracked(77, head)])

    assert results == {77: APPLY_OK}, results
    assert (checkout / "src" / "fix.py").exists()
    log = git("log", "--oneline", "-1", cwd=checkout)
    assert "[patch] PR#77" in log
