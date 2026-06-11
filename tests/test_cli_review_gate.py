from odysseus_patches import cli, github
from odysseus_patches import review as review_mod
from odysseus_patches.github import PRInfo
from odysseus_patches.manifest import Manifest
from odysseus_patches.review import (
    Finding,
    ReviewResult,
    ReviewUnavailable,
    VERDICT_CLEAR,
    VERDICT_FINDINGS,
)


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def open_pr(upstream, monkeypatch, pr=7):
    sha = upstream.open_pr(pr, "src/fix.py", "FIX = True\n", f"fix: pr {pr}")
    fake_info(monkeypatch, {pr: PRInfo(pr, f"fix: pr {pr}", "open", False, sha)})
    return sha


def fake_review(monkeypatch, result):
    calls = []

    def runner(diff, config, **kw):
        calls.append(diff)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(review_mod, "run_review", runner)
    return calls


def test_yes_alone_skips_review(upstream, checkout, monkeypatch):
    open_pr(upstream, monkeypatch)
    calls = fake_review(monkeypatch, ReviewResult(VERDICT_CLEAR, []))
    assert cli.main(["-C", str(checkout), "add", "7", "--yes"]) == 0
    assert calls == []  # --yes alone implies --no-review


def test_yes_review_clear_proceeds_and_caches(upstream, checkout, monkeypatch, capsys):
    sha = open_pr(upstream, monkeypatch)
    calls = fake_review(monkeypatch, ReviewResult(VERDICT_CLEAR, []))
    assert cli.main(["-C", str(checkout), "add", "7", "--yes", "--review"]) == 0
    assert len(calls) == 1
    cached = manifest_of(checkout).get(7).review
    assert cached["verdict"] == VERDICT_CLEAR and cached["reviewed_sha"] == sha
    assert "evidence, not proof" in capsys.readouterr().out


def test_yes_review_findings_fails_closed(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    fake_review(
        monkeypatch,
        ReviewResult(VERDICT_FINDINGS, [Finding("high", "src/fix.py", "exfiltrates tokens")]),
    )
    code = cli.main(["-C", str(checkout), "add", "7", "--yes", "--review"])
    out = capsys.readouterr().out
    assert code == 1
    assert "exfiltrates tokens" in out and "report it on the PR thread" in out
    assert manifest_of(checkout).get(7) is None  # not applied, not tracked


def test_interactive_review_findings_install_anyway(upstream, checkout, monkeypatch):
    open_pr(upstream, monkeypatch)
    fake_review(monkeypatch, ReviewResult(VERDICT_FINDINGS, [Finding("low", "f", "odd")]))
    answers = iter(["r", "y", "y"])  # review -> install anyway -> apply confirm
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.main(["-C", str(checkout), "add", "7"]) == 0
    assert manifest_of(checkout).get(7).status == "active"


def test_interactive_abort_at_gate(upstream, checkout, monkeypatch):
    open_pr(upstream, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "a")
    assert cli.main(["-C", str(checkout), "add", "7"]) == 0
    assert manifest_of(checkout).get(7) is None


def test_review_unavailable_offers_install_without(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    fake_review(monkeypatch, ReviewUnavailable("no api_token configured"))
    answers = iter(["r", "y", "y"])  # try review -> install without -> apply confirm
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert cli.main(["-C", str(checkout), "add", "7"]) == 0
    assert "no api_token" in capsys.readouterr().out
    assert manifest_of(checkout).get(7).review is None


def test_upgrade_reviews_incremental_diff(upstream, checkout, monkeypatch, capsys):
    open_pr(upstream, monkeypatch)
    assert cli.main(["-C", str(checkout), "add", "7", "--yes"]) == 0
    new_sha = upstream.open_pr(7, "src/fix.py", "FIX = 2\n", "fix: pr 7 v2")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, new_sha)})
    calls = fake_review(monkeypatch, ReviewResult(VERDICT_CLEAR, []))

    assert cli.main(["-C", str(checkout), "upgrade", "7", "--yes", "--review"]) == 0

    assert len(calls) == 1
    assert "FIX = 2" in calls[0]          # incremental diff reviewed
    assert "FIX = True" not in calls[0].split("FIX = 2")[0].split("---")[0]
    cached = manifest_of(checkout).get(7).review
    assert cached["reviewed_sha"] == new_sha
