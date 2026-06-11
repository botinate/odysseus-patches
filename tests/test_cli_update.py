from odysseus_patches import cli, github
from odysseus_patches.github import PRInfo
from odysseus_patches.manifest import Manifest


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def add_pr(upstream, checkout, monkeypatch, pr=7, path="src/fix.py", content="FIX = True\n"):
    sha = upstream.open_pr(pr, path, content, f"fix: pr {pr}")
    fake_info(monkeypatch, {pr: PRInfo(pr, f"fix: pr {pr}", "open", False, sha)})
    assert cli.main(["-C", str(checkout), "add", str(pr), "--yes"]) == 0
    return sha


def test_update_retires_merged(upstream, checkout, monkeypatch, capsys):
    sha = add_pr(upstream, checkout, monkeypatch)
    upstream.squash_merge_pr(sha, "fix: pr 7 (#7)")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "closed", True, sha)})

    code = cli.main(["-C", str(checkout), "update"])

    out = capsys.readouterr().out
    assert code == 10  # EXIT_REBUILD
    assert "retired" in out
    assert manifest_of(checkout).get(7).status == "retired"


def test_update_reports_upgrade_available(upstream, checkout, monkeypatch, capsys):
    sha = add_pr(upstream, checkout, monkeypatch)
    new_sha = upstream.open_pr(7, "src/fix.py", "FIX = 2\n", "fix: pr 7 v2")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, new_sha)})

    code = cli.main(["-C", str(checkout), "update"])

    out = capsys.readouterr().out
    assert "upgrade available" in out
    assert manifest_of(checkout).get(7).pinned_sha == sha  # still pinned


def test_upgrade_repins_after_confirm(upstream, checkout, monkeypatch, capsys):
    add_pr(upstream, checkout, monkeypatch)
    new_sha = upstream.open_pr(7, "src/fix.py", "FIX = 2\n", "fix: pr 7 v2")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, new_sha)})

    code = cli.main(["-C", str(checkout), "upgrade", "7", "--yes"])

    assert code == 0
    assert manifest_of(checkout).get(7).pinned_sha == new_sha
    assert (checkout / "src" / "fix.py").read_text() == "FIX = 2\n"


def test_upgrade_up_to_date(upstream, checkout, monkeypatch, capsys):
    sha = add_pr(upstream, checkout, monkeypatch)
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "upgrade", "7", "--yes"])

    assert code == 0
    assert "up to date" in capsys.readouterr().out
