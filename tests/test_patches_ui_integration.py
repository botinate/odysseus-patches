"""Integration test for the shipped Odysseus asset's FastAPI routes.

Runs only where fastapi is available (the `dev` extra installs it). This catches
the class of bug the stdlib-only unit tests cannot: e.g. `from __future__ import
annotations` stringizing the handlers' `request: Request` annotation so FastAPI
treats it as a query field and 422s every route. Mounts the real router with a
stubbed require_admin and a faked CLI.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from starlette.testclient import TestClient

ASSET = Path(__file__).resolve().parents[1] / "odysseus_patches" / "ui_assets" / "patches_ui.py"

# the panel's own state-changing fetches carry this header; the server requires it
CSRF = {"X-Odypatch-CSRF": "1"}
# Odysseus's loopback admin-bypass token header (mirrors core.middleware)
INTERNAL_HEADER = "X-Odysseus-Internal-Token"


def _load_asset():
    spec = importlib.util.spec_from_file_location("patches_ui_integ", ASSET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_core(monkeypatch):
    """Install a stub core.middleware: admin always passes, but expose the
    internal-token header name so the human-admin guard's real import path runs."""
    fake_core = types.ModuleType("core")
    fake_cm = types.ModuleType("core.middleware")
    fake_cm.require_admin = lambda request: None
    fake_cm.INTERNAL_TOOL_HEADER = INTERNAL_HEADER
    monkeypatch.setitem(sys.modules, "core", fake_core)
    monkeypatch.setitem(sys.modules, "core.middleware", fake_cm)


@pytest.fixture
def client(monkeypatch):
    _fake_core(monkeypatch)
    mod = _load_asset()
    monkeypatch.setattr(mod, "_run_cli",
                        lambda checkout, args, stdin=None: (0, '{"patches": [], "patch_count": 0}', ""))
    monkeypatch.setattr(mod, "_cli_command", lambda: ["/bin/odysseus-patches"])

    app = FastAPI()
    app.include_router(mod.setup_patches_ui_routes())
    return TestClient(app, raise_server_exceptions=False)


def test_status_route_injects_request_not_422(client):
    # The future-annotations bug made FastAPI treat `request: Request` as a
    # required query param -> 422. This must be 200 with the CLI's JSON.
    r = client.get("/api/patches/status")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["patch_count"] == 0


def test_approve_route_maps_args(client):
    r = client.post("/api/patches/approve", json={"pr": 7}, headers=CSRF)
    assert r.status_code == 200, r.text
    assert "ok" in r.json()


def test_diff_route_typed_pr(client):
    assert client.get("/api/patches/diff?pr=7").status_code == 200
    assert client.get("/api/patches/diff?pr=abc").status_code == 422  # pr really is validated


@pytest.fixture
def recording_client(monkeypatch):
    _fake_core(monkeypatch)
    mod = _load_asset()
    calls, stdins = [], []

    def fake_run(checkout, args, stdin=None):
        calls.append(args)
        stdins.append(stdin)
        return 0, '{"patches": []}', ""

    monkeypatch.setattr(mod, "_run_cli", fake_run)
    monkeypatch.setattr(mod, "_cli_command", lambda: ["/bin/odysseus-patches"])
    app = FastAPI(); app.include_router(mod.setup_patches_ui_routes())
    c = TestClient(app, raise_server_exceptions=False)
    c._calls = calls
    c._stdins = stdins
    return c


def test_add_route_maps_args(recording_client):
    r = recording_client.post("/api/patches/add", json={"pr": 7}, headers=CSRF)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert recording_client._calls[-1] == ["add", "7", "--yes"]


def test_add_route_with_review(recording_client):
    recording_client.post("/api/patches/add", json={"pr": 7, "review": True}, headers=CSRF)
    assert recording_client._calls[-1] == ["add", "7", "--yes", "--review"]


def test_add_route_requires_int_pr(recording_client):
    assert recording_client.post("/api/patches/add", json={"pr": "x"}, headers=CSRF).status_code == 422


def test_upgrade_route_maps_args(recording_client):
    recording_client.post("/api/patches/upgrade", json={"pr": 9}, headers=CSRF)
    assert recording_client._calls[-1] == ["upgrade", "9", "--yes"]


def test_config_set_passes_token_via_stdin_not_argv(recording_client):
    r = recording_client.post("/api/patches/config", json={"api_token": "sk-abc"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["ok"] is True
    # the token goes on stdin (`api_token -`), never in the argument list
    assert recording_client._calls[-1] == ["config", "set", "api_token", "-"]
    assert recording_client._stdins[-1] == "sk-abc"


def test_config_get_runs_config_show(recording_client):
    r = recording_client.get("/api/patches/config")
    assert r.status_code == 200
    assert recording_client._calls[-1] == ["config", "show"]


def test_config_set_rejects_empty_token(recording_client):
    assert recording_client.post("/api/patches/config", json={"api_token": ""}, headers=CSRF).status_code == 422
    assert recording_client.post("/api/patches/config", json={"api_token": "   "}, headers=CSRF).status_code == 422


# --- the human-admin guard on state-changing routes ---------------------------

def test_mutating_route_requires_csrf_header(recording_client):
    # without the panel's custom header a state-changing call is refused (CSRF)
    r = recording_client.post("/api/patches/add", json={"pr": 7})  # no CSRF header
    assert r.status_code == 403
    assert recording_client._calls == []  # CLI never ran


def test_mutating_route_refuses_agent_loopback_token(recording_client):
    # require_admin GRANTS the internal-tool token (that's how the agent's
    # app_api bridge authenticates) — so admin-gating alone is not enough.
    # The guard must independently refuse it on mutating routes.
    r = recording_client.post("/api/patches/add", json={"pr": 7},
                              headers={**CSRF, INTERNAL_HEADER: "loopback-secret"})
    assert r.status_code == 403, r.text
    assert recording_client._calls == []  # the agent never applied anything


def test_read_route_allows_agent_loopback(recording_client):
    # reads are fine for the agent (it can report state) — only writes are gated
    r = recording_client.get("/api/patches/status", headers={INTERNAL_HEADER: "loopback-secret"})
    assert r.status_code == 200, r.text
