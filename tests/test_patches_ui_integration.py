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


def _load_asset():
    spec = importlib.util.spec_from_file_location("patches_ui_integ", ASSET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(monkeypatch):
    # stub core.middleware.require_admin (Odysseus-only) so the routes mount here
    fake_core = types.ModuleType("core")
    fake_cm = types.ModuleType("core.middleware")
    fake_cm.require_admin = lambda request: None
    monkeypatch.setitem(sys.modules, "core", fake_core)
    monkeypatch.setitem(sys.modules, "core.middleware", fake_cm)

    mod = _load_asset()
    monkeypatch.setattr(mod, "_run_cli", lambda checkout, args: (0, '{"patches": [], "patch_count": 0}', ""))
    monkeypatch.setattr(mod, "_cli_path", lambda: "/bin/odysseus-patches")

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
    r = client.post("/api/patches/approve", json={"pr": 7})
    assert r.status_code == 200, r.text
    assert "ok" in r.json()


def test_diff_route_typed_pr(client):
    assert client.get("/api/patches/diff?pr=7").status_code == 200
    assert client.get("/api/patches/diff?pr=abc").status_code == 422  # pr really is validated
