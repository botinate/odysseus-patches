from odysseus_patches.gitops import GitRepo
from odysseus_patches.installer import LOADER_BEGIN, install_ui
from odysseus_patches.manifest import Manifest
from odysseus_patches.update import run_update
from tests.conftest import git


def test_update_succeeds_with_ui_installed(upstream, checkout):
    (checkout / "app.py").write_text("app = 1\n", encoding="utf-8")
    (checkout / "static" / "js").mkdir(parents=True)
    (checkout / "routes").mkdir(parents=True)
    git("add", "-A", cwd=checkout)
    git("commit", "-m", "add app.py", cwd=checkout)
    git("push", "origin", "dev", cwd=checkout)

    install_ui(checkout)  # dirties app.py with the loader line + drops asset files
    repo = GitRepo(checkout)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")

    upstream.commit_on_dev("src/new.py", "X = 1\n", "upstream work")

    report, code = run_update(repo, manifest, fetch_info=lambda u, p: None)

    assert (checkout / "src" / "new.py").exists()
    assert LOADER_BEGIN in (checkout / "app.py").read_text(encoding="utf-8")
