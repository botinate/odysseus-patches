"""Patch-management panel for Odysseus — installed into <odysseus>/routes/ by
`odysseus-patches install-ui`. Owned by the odysseus-patches extension.

Runs inside Odysseus: FastAPI + core.middleware are imported LAZILY (inside
functions) so this module also imports cleanly where they're absent (the
extension's own test env). Stdlib helpers below are unit-tested there.

All operations shell out to the odysseus-patches CLI, so this panel inherits
every tested CLI behavior (review gate, rollback, branch-safety) — nothing is
reimplemented.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess

_CLI_TIMEOUT = 600
_SCRIPT_TAG = '<script type="module" src="/static/js/patches.js"></script>'


def _cli_path():
    override = os.environ.get("ODYSSEUS_PATCHES_BIN")
    if override and os.path.exists(override):
        return override
    return shutil.which("odysseus-patches")


def _run_cli(checkout: str, args: list) -> tuple:
    """Run the odysseus-patches CLI against `checkout`. Sync (used from a
    thread executor in the async route). Module-level for testability."""
    binary = _cli_path()
    if binary is None:
        return 127, "", "odysseus-patches CLI not installed"
    cmd = [binary, "-C", checkout, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_CLI_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", "patches CLI timed out"
    return proc.returncode, proc.stdout, proc.stderr


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line.removeprefix("error: ")
    return ""


def inject_script_tag(html: str) -> str:
    """Add the panel <script> before </body>, once. Leaves non-HTML untouched."""
    if _SCRIPT_TAG in html or "</body>" not in html:
        return html
    return html.replace("</body>", _SCRIPT_TAG + "</body>", 1)


# --- FastAPI/Odysseus glue: imported lazily so this module loads without them ---

def _checkout_root() -> str:
    # routes/ sits directly under the Odysseus install root.
    import pathlib
    return str(pathlib.Path(__file__).resolve().parents[1])


def setup_patches_ui_routes():
    from fastapi import APIRouter, Request
    from pydantic import BaseModel
    from core.middleware import require_admin

    root = _checkout_root()
    router = APIRouter(tags=["patches-ui"])

    class PrBody(BaseModel):
        pr: int

    async def run(args):
        return await asyncio.to_thread(_run_cli, root, args)

    @router.get("/api/patches/status")
    async def status(request: Request):
        require_admin(request)
        code, out, err = await run(["status"])
        try:
            return {"cli_available": _cli_path() is not None, "status": json.loads(out)}
        except (ValueError, TypeError):
            if _cli_path() is None:
                return {"cli_available": False,
                        "hint": "Install odysseus-patches in this environment."}
            return {"cli_available": True, "status": None,
                    "message": f"could not parse CLI output: {_first_line(err) or _first_line(out)}"}

    @router.get("/api/patches/diff")
    async def diff(request: Request, pr: int):
        require_admin(request)
        code, out, err = await run(["show", str(pr)])
        return {"diff": out, "ok": code == 0, "message": _first_line(err)}

    async def _action(request, args):
        require_admin(request)
        code, out, err = await run(args)
        return {"ok": code == 0, "message": _first_line(err) or _first_line(out), "exit_code": code}

    @router.post("/api/patches/approve")
    async def approve(request: Request, body: PrBody):
        return await _action(request, ["approve", str(body.pr), "--yes"])

    @router.post("/api/patches/reject")
    async def reject(request: Request, body: PrBody):
        return await _action(request, ["reject", str(body.pr)])

    @router.post("/api/patches/remove")
    async def remove(request: Request, body: PrBody):
        return await _action(request, ["remove", str(body.pr)])

    @router.post("/api/patches/review")
    async def review(request: Request, body: PrBody):
        return await _action(request, ["review", str(body.pr)])

    @router.post("/api/patches/update")
    async def update(request: Request):
        require_admin(request)
        code, out, err = await run(["update"])
        return {"exit_code": code, "report": out, "ok": code in (0, 10), "message": _first_line(err)}

    return router


def _install_middleware(app):
    from starlette.middleware.base import BaseHTTPMiddleware

    class _PanelInject(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            ctype = resp.headers.get("content-type", "")
            if "text/html" not in ctype:
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            html = inject_script_tag(body.decode("utf-8", "replace"))
            from starlette.responses import Response
            data = html.encode("utf-8")
            headers = dict(resp.headers)
            headers["content-length"] = str(len(data))
            return Response(content=data, status_code=resp.status_code,
                            headers=headers, media_type="text/html")

    app.add_middleware(_PanelInject)


def _block_from_app_api():
    """Best-effort: keep the agent from driving /api/patches via app_api."""
    try:
        import src.tool_implementations as ti
        prefixes = getattr(ti, "_APP_API_BLOCKLIST_PREFIXES", None)
        if prefixes is not None and "/api/patches" not in prefixes:
            ti._APP_API_BLOCKLIST_PREFIXES = tuple(prefixes) + ("/api/patches",)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "odysseus-patches: could not extend app_api blocklist; "
            "relying on route-level require_admin")


def install(app):
    """Entry point called by the loader line appended to Odysseus's app.py."""
    app.include_router(setup_patches_ui_routes())
    _install_middleware(app)
    _block_from_app_api()
