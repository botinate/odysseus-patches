import json

from odysseus_patches import cli
from odysseus_patches import review as review_mod
from odysseus_patches.manifest import Manifest, Patch
from odysseus_patches.review import ReviewResult, VERDICT_FINDINGS, Finding


def test_config_set_and_show(checkout, capsys):
    assert cli.main(["-C", str(checkout), "config", "set", "api_token", "sk-abc-1234"]) == 0
    capsys.readouterr()
    assert cli.main(["-C", str(checkout), "config", "show"]) == 0
    out = capsys.readouterr().out
    assert "sk-abc-1234" not in out
    assert "1234" in out


def test_config_set_unknown_key_errors(checkout, capsys):
    assert cli.main(["-C", str(checkout), "config", "set", "nope", "x"]) == 1
    assert "unknown config key" in capsys.readouterr().err


def test_review_command_prints_findings_and_caches(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: pr 7")
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="fix: pr 7", pinned_sha=sha))
    manifest.save()
    monkeypatch.setattr(
        review_mod, "run_review",
        lambda diff, config, **kw: ReviewResult(
            VERDICT_FINDINGS, [Finding("high", "src/fix.py", "downloads remote code")]
        ),
    )

    code = cli.main(["-C", str(checkout), "review", "7"])

    out = capsys.readouterr().out
    assert code == 0
    assert "FINDINGS" in out and "downloads remote code" in out
    assert "report it on the PR thread" in out
    cached = Manifest.load(checkout / "data" / "patches" / "manifest.json").get(7).review
    assert cached["verdict"] == VERDICT_FINDINGS
    assert cached["reviewed_sha"] == sha


def test_review_command_untracked_pr_errors(checkout, capsys):
    assert cli.main(["-C", str(checkout), "review", "99"]) == 1
    assert "not tracked" in capsys.readouterr().err
