from odysseus_patches.gitops import GitRepo, PATCHED_BRANCH, rebuild_patched
from odysseus_patches.manifest import Manifest, Patch
from odysseus_patches.status import build_status
from tests.conftest import git



def test_on_patched_adds_dev_guidance_without_unhealthy(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    m = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    m.add(Patch(pr=7, title="fix: pr7", pinned_sha=sha))
    rebuild_patched(repo, "dev", m.appliable_patches())
    m.save()

    st = build_status(repo, m)
    # informational guidance present, but a normal patched install stays healthy
    assert any("don't develop" in line.lower() or "branch from" in line.lower()
               for line in st["attention"])
    assert st["healthy"] is True
    assert st["pending_action"] is False  # a clean patched install needs no action


def test_foreign_commit_on_patched_is_unhealthy(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    m = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    m.add(Patch(pr=7, title="fix: pr7", pinned_sha=sha))
    rebuild_patched(repo, "dev", m.appliable_patches())
    m.save()
    (checkout / "w.txt").write_text("x\n", encoding="utf-8")
    git("add", "-A", cwd=checkout); git("commit", "-m", "my work", cwd=checkout)

    st = build_status(repo, m)
    assert st["healthy"] is False
    assert any("not managed" in line.lower() for line in st["attention"])


def test_proposal_still_flips_pending_action(upstream, checkout):
    from odysseus_patches.manifest import STATUS_PROPOSED
    m = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    m.add(Patch(pr=9, title="t", pinned_sha="a" * 40, status=STATUS_PROPOSED, proposer="agent"))
    st = build_status(GitRepo(checkout), m)
    assert st["pending_action"] is True
