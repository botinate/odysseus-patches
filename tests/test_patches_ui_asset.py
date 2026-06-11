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


def test_cli_path_prefers_env(monkeypatch, tmp_path):
    mod = _load()
    fake = tmp_path / "odysseus-patches"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("ODYSSEUS_PATCHES_BIN", str(fake))
    assert mod._cli_path() == str(fake)


def test_run_cli_builds_command(monkeypatch):
    mod = _load()
    seen = {}

    class FakeProc:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        seen["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(mod, "_cli_path", lambda: "/bin/odysseus-patches")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    code, out, err = mod._run_cli("/srv/ody", ["status"])
    assert code == 0 and out == '{"ok": true}'
    assert seen["cmd"] == ["/bin/odysseus-patches", "-C", "/srv/ody", "status"]


def test_run_cli_missing_binary(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "_cli_path", lambda: None)
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
