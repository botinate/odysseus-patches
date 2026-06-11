import pytest

from tests.conftest import git
from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo, PATCHED_BRANCH
from odysseus_patches.manifest import (
    Manifest,
    Patch,
    STATUS_ACTIVE,
    STATUS_CONFLICTED,
    STATUS_RETIRED,
)
from odysseus_patches.update import (
    EXIT_ATTENTION,
    EXIT_OK,
    EXIT_REBUILD,
    UpdateError,
    run_update,
)


def setup_tracked_pr(upstream, checkout, pr=7, path="src/fix.py"):
    sha = upstream.open_pr(pr, path, "FIX = True\n", f"fix: pr {pr}")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(pr)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=pr, title=f"fix: pr {pr}", pinned_sha=sha))
    manifest.save()
    return repo, manifest, sha


def online(infos):
    return lambda upstream, pr: infos.get(pr)


def test_open_pr_survives_update(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout)
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "unrelated upstream work")
    fetch = online({7: PRInfo(7, "fix: pr 7", "open", False, sha)})

    report, code = run_update(repo, manifest, fetch_info=fetch)

    assert code == EXIT_REBUILD
    assert repo.current_branch() == PATCHED_BRANCH
    assert (checkout / "src" / "other.py").exists()  # upstream work arrived
    assert (checkout / "src" / "fix.py").exists()    # patch still applied
    assert manifest.get(7).status == STATUS_ACTIVE


def test_merged_pr_is_retired(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout)
    upstream.squash_merge_pr(sha, "fix: pr 7 (#7)")
    fetch = online({7: PRInfo(7, "fix: pr 7", "closed", True, sha)})

    report, code = run_update(repo, manifest, fetch_info=fetch)

    assert code == EXIT_REBUILD
    assert manifest.get(7).status == STATUS_RETIRED
    assert repo.current_branch() == "dev"  # no active patches left
    assert (checkout / "src" / "fix.py").exists()  # via upstream now
    reloaded = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    assert reloaded.get(7).status == STATUS_RETIRED
    assert reloaded.get(7).last_result == "merged upstream"


def test_offline_squash_merge_still_retires(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout)
    upstream.squash_merge_pr(sha, "fix: pr 7 (#7)")

    report, code = run_update(repo, manifest, fetch_info=lambda u, p: None)

    assert manifest.get(7).status == STATUS_RETIRED


def test_conflict_marks_and_continues(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout, pr=8, path="src/app.py")
    upstream.commit_on_dev("src/app.py", "VERSION = 2\nGREETING = 'hi'\n", "bump")
    fetch = online({8: PRInfo(8, "fix: pr 8", "open", False, sha)})

    report, code = run_update(repo, manifest, fetch_info=fetch)

    assert code == EXIT_ATTENTION
    assert manifest.get(8).status == STATUS_CONFLICTED


def test_dirty_tree_refuses(upstream, checkout):
    repo, manifest, _ = setup_tracked_pr(upstream, checkout)
    (checkout / "src" / "app.py").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(UpdateError):
        run_update(repo, manifest, fetch_info=lambda u, p: None)


def test_no_patches_plain_update(upstream, checkout):
    repo = GitRepo(checkout)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "work")

    report, code = run_update(repo, manifest, fetch_info=lambda u, p: None)

    assert code == EXIT_OK
    assert repo.current_branch() == "dev"
    assert (checkout / "src" / "other.py").exists()


def test_undetected_merged_patch_retires_via_empty_pick(upstream, checkout):
    # PR content lands upstream split across two commits: GitHub is offline,
    # patch-id can't match (different split), only the empty cherry-pick
    # detects it. The patch must retire and the artifact branch must be
    # cleaned up by the post-empty re-rebuild.
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\nEXTRA = 2\n", "fix: pr 7")
    upstream.commit_on_dev("src/fix.py", "FIX = True\n", "land part 1")
    upstream.commit_on_dev("src/fix.py", "FIX = True\nEXTRA = 2\n", "land part 2")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="fix: pr 7", pinned_sha=sha))
    manifest.save()

    report, code = run_update(repo, manifest, fetch_info=lambda u, p: None)

    assert manifest.get(7).status == STATUS_RETIRED
    assert manifest.get(7).last_result == "already-upstream"
    assert code == EXIT_REBUILD
    assert repo.current_branch() == "dev"
    branches = git("branch", "--list", PATCHED_BRANCH, cwd=checkout)
    assert branches == ""
