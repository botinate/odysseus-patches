from odysseus_patches import cli, github
from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo
from odysseus_patches.manifest import Manifest


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def test_add_refuses_on_foreign_branch(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr7", "open", False, sha)})
    GitRepo(checkout).run("checkout", "-b", "my-feature")
    code = cli.main(["-C", str(checkout), "add", "7", "--yes"])
    assert code == 1
    assert "my-feature" in capsys.readouterr().err
    # nothing applied; still on the user's branch
    assert GitRepo(checkout).current_branch() == "my-feature"
    assert Manifest.load(checkout / "data" / "patches" / "manifest.json").get(7) is None


def test_add_force_overrides(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX=1\n", "fix: pr7")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr7", "open", False, sha)})
    GitRepo(checkout).run("checkout", "-b", "my-feature")
    code = cli.main(["-C", str(checkout), "add", "7", "--yes", "--force"])
    assert code == 0
    assert Manifest.load(checkout / "data" / "patches" / "manifest.json").get(7).status == "active"


def test_update_refuses_on_foreign_branch(upstream, checkout, monkeypatch, capsys):
    GitRepo(checkout).run("checkout", "-b", "my-feature")
    code = cli.main(["-C", str(checkout), "update"])
    assert code == 1
    assert "my-feature" in capsys.readouterr().err
    # update must NOT have switched the checkout to dev
    assert GitRepo(checkout).current_branch() == "my-feature"
