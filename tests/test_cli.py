import pytest

from odysseus_patches import cli, github
from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo, PATCHED_BRANCH
from odysseus_patches.manifest import Manifest


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def test_add_applies_and_tracks(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "add", "7", "--yes"])

    assert code == 0
    assert manifest_of(checkout).get(7).pinned_sha == sha
    assert GitRepo(checkout).current_branch() == PATCHED_BRANCH
    assert "src/fix.py" in capsys.readouterr().out


def test_add_offline_errors(upstream, checkout, monkeypatch, capsys):
    fake_info(monkeypatch, {})
    code = cli.main(["-C", str(checkout), "add", "7", "--yes"])
    assert code == 1
    assert "GitHub" in capsys.readouterr().err


def test_add_conflict_rolls_back(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(8, "src/app.py", "CONFLICT = 'pr'\n", "fix: bad")
    upstream.commit_on_dev("src/app.py", "VERSION = 2\nGREETING = 'hi'\n", "bump")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    fake_info(monkeypatch, {8: PRInfo(8, "fix: bad", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "add", "8", "--yes"])

    assert code == 1
    assert manifest_of(checkout).get(8) is None
    assert repo.current_branch() == "dev"


def test_list_shows_patches(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    cli.main(["-C", str(checkout), "add", "7", "--yes"])
    capsys.readouterr()

    code = cli.main(["-C", str(checkout), "list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "7" in out and "active" in out and sha[:10] in out


def test_show_prints_diff(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    cli.main(["-C", str(checkout), "add", "7", "--yes"])
    capsys.readouterr()

    code = cli.main(["-C", str(checkout), "show", "7"])

    out = capsys.readouterr().out
    assert code == 0
    assert "FIX = True" in out


def test_remove_untracks_and_rebuilds(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    cli.main(["-C", str(checkout), "add", "7", "--yes"])

    code = cli.main(["-C", str(checkout), "remove", "7"])

    assert code == 0
    assert manifest_of(checkout).get(7) is None
    assert GitRepo(checkout).current_branch() == "dev"
    assert not (checkout / "src" / "fix.py").exists()


def test_not_a_git_checkout_errors(tmp_path, capsys):
    code = cli.main(["-C", str(tmp_path), "list"])
    assert code == 1
    assert "git checkout" in capsys.readouterr().err


def test_add_aborts_when_user_declines(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    monkeypatch.setattr("builtins.input", lambda _: "n")

    code = cli.main(["-C", str(checkout), "add", "7"])

    assert code == 0
    assert "aborted" in capsys.readouterr().out
    assert manifest_of(checkout).get(7) is None


def test_add_already_upstream_suggests_update(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    upstream.squash_merge_pr(sha, "fix: something (#7)")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "add", "7", "--yes"])

    assert code == 1
    assert "already in upstream" in capsys.readouterr().err
    assert manifest_of(checkout).get(7) is None
