from odysseus_patches.gitops import GitRepo, rebuild_patched
from odysseus_patches.manifest import Manifest, Patch
from odysseus_patches.status import build_status


def test_status_empty(checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    status = build_status(GitRepo(checkout), manifest)
    assert status["patch_count"] == 0
    assert status["on_patched_branch"] is False
    assert status["healthy"] is True


def test_status_with_applied_patch(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="fix: something", pinned_sha=sha, last_result="applied-clean"))
    rebuild_patched(repo, "dev", manifest.appliable_patches())
    manifest.save()

    status = build_status(repo, manifest)

    assert status["patch_count"] == 1
    assert status["on_patched_branch"] is True
    assert status["healthy"] is True
    assert status["patches"][0]["pr"] == 7
    assert status["patches"][0]["status"] == "active"


def test_status_flags_conflicted_as_unhealthy(checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=8, title="bad", pinned_sha="c" * 40, status="conflicted"))
    status = build_status(GitRepo(checkout), manifest)
    assert status["healthy"] is False
    assert "conflicted" in status["attention"][0]


def test_status_flags_active_patches_while_on_base_branch(upstream, checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="t", pinned_sha="a" * 40, status="active"))
    status = build_status(GitRepo(checkout), manifest)  # still on dev
    assert status["healthy"] is False
    assert any("not running" in line for line in status["attention"])


def test_status_flags_stale_patched_branch(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="fix: something", pinned_sha=sha))
    rebuild_patched(repo, "dev", manifest.appliable_patches())

    # upstream moves; user pulls dev manually but stays on patched
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "upstream work")
    repo.run("fetch", "origin", "dev:dev")

    status = build_status(repo, manifest)

    assert status["on_patched_branch"] is True
    assert status["healthy"] is False
    assert any("outdated" in line for line in status["attention"])
