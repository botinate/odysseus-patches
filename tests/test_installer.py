import pytest

from odysseus_patches.installer import (
    InstallError,
    LOADER_BEGIN,
    install_ui,
    uninstall_ui,
)


def fake_odysseus(tmp_path):
    root = tmp_path / "odyssey"
    (root / "routes").mkdir(parents=True)
    (root / "static" / "js").mkdir(parents=True)
    (root / "app.py").write_text("app = FastAPI()\n# end\n", encoding="utf-8")
    return root


def test_install_copies_assets_and_appends_loader(tmp_path):
    root = fake_odysseus(tmp_path)
    changed = install_ui(root)
    assert (root / "routes" / "patches_ui.py").exists()
    assert (root / "static" / "js" / "patches.js").exists()
    app = (root / "app.py").read_text(encoding="utf-8")
    assert LOADER_BEGIN in app
    assert "routes.patches_ui" in app
    assert changed


def test_install_is_idempotent(tmp_path):
    root = fake_odysseus(tmp_path)
    install_ui(root)
    app_once = (root / "app.py").read_text(encoding="utf-8")
    install_ui(root)
    app_twice = (root / "app.py").read_text(encoding="utf-8")
    assert app_once == app_twice
    assert app_twice.count(LOADER_BEGIN) == 1


def test_uninstall_reverses(tmp_path):
    root = fake_odysseus(tmp_path)
    install_ui(root)
    uninstall_ui(root)
    assert not (root / "routes" / "patches_ui.py").exists()
    assert not (root / "static" / "js" / "patches.js").exists()
    app = (root / "app.py").read_text(encoding="utf-8")
    assert LOADER_BEGIN not in app
    assert "routes.patches_ui" not in app
    assert "app = FastAPI()" in app


def test_install_rejects_non_odysseus_dir(tmp_path):
    bare = tmp_path / "nope"
    bare.mkdir()
    with pytest.raises(InstallError):
        install_ui(bare)


def test_uninstall_without_install_is_clean(tmp_path):
    root = fake_odysseus(tmp_path)
    uninstall_ui(root)
    assert "app = FastAPI()" in (root / "app.py").read_text(encoding="utf-8")
