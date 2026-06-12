"""Tests for the stdlib-testable parts of the shipped Odysseus asset.
The FastAPI/Odysseus glue (setup_patches_ui_routes, install) is lazy-imported
and verified in the running app, not here."""
import importlib.util
from pathlib import Path

import pytest

ASSET = Path(__file__).resolve().parents[1] / "odysseus_patches" / "ui_assets" / "patches_ui.py"


def _load():
    spec = importlib.util.spec_from_file_location("patches_ui_under_test", ASSET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_imports_without_fastapi():
    mod = _load()
    assert hasattr(mod, "_run_cli")
    assert hasattr(mod, "inject_script_tag")


def test_first_line_strips_error_prefix():
    mod = _load()
    assert mod._first_line("error: nope\nmore") == "nope"
    assert mod._first_line("\n\n  hi\n") == "hi"
    assert mod._first_line("") == ""


def test_cli_command_prefers_env(monkeypatch, tmp_path):
    mod = _load()
    fake = tmp_path / "odysseus-patches"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ODYSSEUS_PATCHES_BIN", str(fake))
    assert mod._cli_command() == [str(fake)]


def test_cli_command_falls_back_to_python_m(monkeypatch):
    mod = _load()
    # no env override, nothing on PATH, no sibling binary — but the package is
    # importable, so fall back to `python -m odysseus_patches.cli`
    monkeypatch.delenv("ODYSSEUS_PATCHES_BIN", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod.os.path, "exists", lambda p: False)
    monkeypatch.setattr(mod.importlib.util, "find_spec", lambda name: object())
    cmd = mod._cli_command()
    assert cmd[0] == mod.sys.executable
    assert cmd[1:] == ["-m", "odysseus_patches.cli"]


def test_cli_command_none_when_nothing_found(monkeypatch):
    mod = _load()
    monkeypatch.delenv("ODYSSEUS_PATCHES_BIN", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod.os.path, "exists", lambda p: False)
    monkeypatch.setattr(mod.importlib.util, "find_spec", lambda name: None)
    assert mod._cli_command() is None


def test_run_cli_builds_command(monkeypatch):
    mod = _load()
    seen = {}

    class FakeProc:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout, input=None):
        seen["cmd"] = cmd
        seen["input"] = input
        return FakeProc()

    monkeypatch.setattr(mod, "_cli_command", lambda: ["/bin/odysseus-patches"])
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    code, out, err = mod._run_cli("/srv/ody", ["status"])
    assert code == 0 and out == '{"ok": true}'
    assert seen["cmd"] == ["/bin/odysseus-patches", "-C", "/srv/ody", "status"]


def test_run_cli_builds_python_m_command(monkeypatch):
    mod = _load()
    seen = {}

    class FakeProc:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr(mod, "_cli_command", lambda: ["/py", "-m", "odysseus_patches.cli"])
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **k: seen.update(cmd=cmd) or FakeProc())
    mod._run_cli("/srv/ody", ["approve", "7", "--yes"])
    assert seen["cmd"] == ["/py", "-m", "odysseus_patches.cli", "-C", "/srv/ody", "approve", "7", "--yes"]


def test_run_cli_missing_binary(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_cli_command", lambda: None)
    code, out, err = mod._run_cli("/srv/ody", ["status"])
    assert code == 127
    assert "not installed" in err.lower()


def test_inject_script_tag_once_before_body():
    mod = _load()
    html = "<html><body><div>x</div></body></html>"
    out = mod.inject_script_tag(html)
    assert out.count("/static/js/patches.js") == 1
    assert out.index("patches.js") < out.index("</body>")
    assert mod.inject_script_tag(out) == out


def test_inject_script_tag_leaves_non_html_untouched():
    mod = _load()
    assert mod.inject_script_tag("just text, no body") == "just text, no body"


def test_decode_body_plain():
    mod = _load()
    assert mod._decode_body(b"<html></html>", "") == "<html></html>"


def test_decode_body_gzip_roundtrip():
    import gzip
    mod = _load()
    raw = b"<html><body>hi</body></html>"
    assert mod._decode_body(gzip.compress(raw), "gzip") == raw.decode()


def test_decode_body_bad_gzip_returns_none():
    mod = _load()
    assert mod._decode_body(b"not gzip bytes", "gzip") is None
