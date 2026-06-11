from odysseus_patches import cli, github
from odysseus_patches import review as review_mod
from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo
from odysseus_patches.manifest import Manifest, STATUS_PROPOSED
from odysseus_patches.review import ReviewResult, VERDICT_CLEAR


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def open_pr(upstream, monkeypatch, pr=7):
    sha = upstream.open_pr(pr, "src/fix.py", "FIX = True\n", f"fix: pr {pr}")
    fake_info(monkeypatch, {pr: PRInfo(pr, f"fix: pr {pr}", "open", False, sha)})
    return sha


def test_propose_stages(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    code = cli.main(["-C", str(checkout), "propose", "7", "--note", "looks useful"])
    assert code == 0
    p = manifest_of(checkout).get(7)
    assert p.status == STATUS_PROPOSED and p.proposer == "cli" and p.note == "looks useful"
    assert "approve" in capsys.readouterr().out
    # proposals are never applied
    assert GitRepo(checkout).current_branch() == "dev"


def test_approve_applies_with_cached_clear_review(upstream, checkout, monkeypatch, capsys):
    sha = open_pr(upstream, monkeypatch)
    calls = []
    monkeypatch.setattr(
        review_mod, "run_review",
        lambda diff, config, **kw: calls.append(1) or ReviewResult(VERDICT_CLEAR, []),
    )
    cli.main(["-C", str(checkout), "propose", "7", "--review"])
    assert calls == [1]

    code = cli.main(["-C", str(checkout), "approve", "7", "--yes", "--review"])

    assert code == 0
    assert calls == [1]  # cached verdict for same sha — no second review
    p = manifest_of(checkout).get(7)
    assert p.status == "active"
    assert (checkout / "src" / "fix.py").exists()


def test_approve_nonproposal_errors(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    cli.main(["-C", str(checkout), "add", "7", "--yes"])
    assert cli.main(["-C", str(checkout), "approve", "7", "--yes"]) == 1
    assert "not a proposal" in capsys.readouterr().err


def test_reject_drops_proposal(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    cli.main(["-C", str(checkout), "propose", "7"])
    assert cli.main(["-C", str(checkout), "reject", "7"]) == 0
    assert manifest_of(checkout).get(7) is None


def test_reject_applied_patch_points_at_remove(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    cli.main(["-C", str(checkout), "add", "7", "--yes"])
    assert cli.main(["-C", str(checkout), "reject", "7"]) == 1
    assert "remove" in capsys.readouterr().err


def test_list_shows_proposal_and_verdict(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    monkeypatch.setattr(
        review_mod, "run_review", lambda diff, config, **kw: ReviewResult(VERDICT_CLEAR, [])
    )
    cli.main(["-C", str(checkout), "propose", "7", "--review"])
    capsys.readouterr()
    cli.main(["-C", str(checkout), "list"])
    out = capsys.readouterr().out
    assert "proposed" in out and "CLEAR" in out
