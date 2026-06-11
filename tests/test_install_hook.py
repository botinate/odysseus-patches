import pytest

from odysseus_patches.hooks import HookError, install_hook

BAT = (
    'pushd "%~dp0"\r\n'
    "where git\r\n"
    "git pull --ff-only\r\n"
    "docker compose up -d --build\r\n"
)


def test_install_replaces_pull_line(tmp_path):
    script = tmp_path / "update_windows.bat"
    script.write_text(BAT, encoding="utf-8")

    changed = install_hook(script)

    text = script.read_text(encoding="utf-8")
    assert changed is True
    assert "odysseus-patches update" in text
    assert "git pull --ff-only" not in text.replace(":: odysseus-patches hook (was: git pull --ff-only)", "")
    assert (tmp_path / "update_windows.bat.bak").read_bytes() == BAT.encode("utf-8")


def test_install_is_idempotent(tmp_path):
    script = tmp_path / "update_windows.bat"
    script.write_text(BAT, encoding="utf-8")
    install_hook(script)
    once = script.read_text(encoding="utf-8")

    changed = install_hook(script)

    assert changed is False
    assert script.read_text(encoding="utf-8") == once


def test_no_pull_line_raises(tmp_path):
    script = tmp_path / "update.sh"
    script.write_text("echo no pull here\n", encoding="utf-8")
    with pytest.raises(HookError):
        install_hook(script)
