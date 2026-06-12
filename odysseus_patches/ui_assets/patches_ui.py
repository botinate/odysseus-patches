"""Patch-management panel for Odysseus — installed into <odysseus>/routes/ by
`odysseus-patches install-ui`. Owned by the odysseus-patches extension.

Runs inside Odysseus: FastAPI + core.middleware are imported LAZILY (inside
functions) so this module also imports cleanly where they're absent (the
extension's own test env). Stdlib helpers below are unit-tested there.

All operations shell out to the odysseus-patches CLI, so this panel inherits
every tested CLI behavior (review gate, rollback, branch-safety) — nothing is
reimplemented.

NOTE: deliberately NO `from __future__ import annotations`. FastAPI must see the
route handlers' `request: Request` annotation as the real class to inject it;
with stringized annotations it can't resolve `Request` (imported lazily inside
the factory, not in module globals) and 422s every route. The `X | None` hints
below are evaluated natively on Python 3.10+ (Odysseus requires 3.11+).
"""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys

_CLI_TIMEOUT = 600
_SCRIPT_TAG = '<script type="module" src="/static/js/patches.js"></script>'
# A custom request header the panel's own fetches send on every state-changing
# call. A cross-site page cannot set custom headers on a "simple" request, and a
# cross-origin fetch that tries triggers a CORS preflight Odysseus rejects — so
# requiring it blocks CSRF against a logged-in admin's browser.
_CSRF_HEADER = "x-odypatch-csrf"


def _cli_command():
    """Command prefix for the odysseus-patches CLI, or None if unavailable.

    Tried in order so the panel works without any env var once the package is
    simply installed in Odysseus's venv:
      1. ODYSSEUS_PATCHES_BIN (explicit override)
      2. `odysseus-patches` on PATH
      3. a console-script next to the running interpreter (venv/bin)
      4. `python -m odysseus_patches.cli` if the package is importable here
    """
    override = os.environ.get("ODYSSEUS_PATCHES_BIN")
    if override and os.path.exists(override):
        return [override]
    found = shutil.which("odysseus-patches")
    if found:
        return [found]
    sibling = os.path.join(os.path.dirname(sys.executable), "odysseus-patches")
    if os.path.exists(sibling):
        return [sibling]
    if importlib.util.find_spec("odysseus_patches") is not None:
        return [sys.executable, "-m", "odysseus_patches.cli"]
    return None


def _run_cli(checkout: str, args: list, stdin: "str | None" = None) -> tuple:
    """Run the odysseus-patches CLI against `checkout`. Sync (used from a
    thread executor in the async route). Module-level for testability.

    `stdin` feeds the child's stdin — used to pass secrets (the API token) to
    `config set <key> -` so they never appear in the process argument list."""
    prefix = _cli_command()
    if prefix is None:
        return 127, "", "odysseus-patches CLI not installed"
    cmd = [*prefix, "-C", checkout, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_CLI_TIMEOUT, input=stdin)
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


def _decode_body(body: bytes, content_encoding: str) -> str | None:
    """HTML text of a (possibly gzip-compressed) response body. Returns None if
    it can't be decoded — caller must then pass the original body through
    untouched rather than corrupt it."""
    if (content_encoding or "").lower() == "gzip":
        import gzip
        try:
            body = gzip.decompress(body)
        except Exception:
            return None
    return body.decode("utf-8", "replace")


# --- FastAPI/Odysseus glue: imported lazily so this module loads without them ---

def _checkout_root() -> str:
    # routes/ sits directly under the Odysseus install root.
    import pathlib
    return str(pathlib.Path(__file__).resolve().parents[1])


def setup_patches_ui_routes():
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel
    from core.middleware import require_admin
    try:
        from core.middleware import INTERNAL_TOOL_HEADER
    except Exception:
        INTERNAL_TOOL_HEADER = "X-Odysseus-Internal-Token"

    root = _checkout_root()
    router = APIRouter(tags=["patches-ui"])

    def require_human_admin(request):
        """Gate for state-changing routes. Beyond `require_admin` it:

        (a) Refuses the in-process agent loopback. `require_admin` deliberately
            grants any request carrying Odysseus's internal-tool token, which the
            agent's `app_api` bridge sends — so admin-gating alone does NOT keep
            the agent out. Rejecting that token here means a prompt-injected
            agent can never apply/upgrade/remove/configure patches over HTTP; its
            only mutating path stays the propose-only MCP server (human-gated).
            This holds even if Odysseus's `app_api` blocklist patch silently
            fails — it no longer depends on an upstream private symbol.

        (b) Requires a custom header the panel sends, blocking browser CSRF.
        """
        require_admin(request)
        state_user = getattr(getattr(request, "state", None), "current_user", None)
        if request.headers.get(INTERNAL_TOOL_HEADER) or state_user == "internal-tool":
            raise HTTPException(
                403, "patches cannot be changed via the agent API bridge — "
                     "use the propose-only MCP path; a human approves in the UI/CLI")
        if not request.headers.get(_CSRF_HEADER):
            raise HTTPException(403, "missing X-Odypatch-CSRF header")

    class PrBody(BaseModel):
        pr: int

    class AddBody(BaseModel):
        pr: int
        review: bool = False

    class ConfigBody(BaseModel):
        api_token: str

    async def run(args, stdin=None):
        return await asyncio.to_thread(_run_cli, root, args, stdin)

    @router.get("/api/patches/status")
    async def status(request: Request):
        require_admin(request)
        code, out, err = await run(["status"])
        available = _cli_command() is not None
        try:
            return {"cli_available": available, "status": json.loads(out)}
        except (ValueError, TypeError):
            if not available:
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
        require_human_admin(request)
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
        require_human_admin(request)
        code, out, err = await run(["update"])
        return {"exit_code": code, "report": out, "ok": code in (0, 10), "message": _first_line(err)}

    @router.post("/api/patches/add")
    async def add(request: Request, body: AddBody):
        require_human_admin(request)
        args = ["add", str(body.pr), "--yes"]
        if body.review:
            args.append("--review")
        code, out, err = await run(args)
        return {"ok": code == 0, "message": _first_line(err) or _first_line(out), "exit_code": code}

    @router.post("/api/patches/upgrade")
    async def upgrade(request: Request, body: PrBody):
        require_human_admin(request)
        code, out, err = await run(["upgrade", str(body.pr), "--yes"])
        return {"ok": code == 0, "message": _first_line(err) or _first_line(out), "exit_code": code}

    @router.get("/api/patches/config")
    async def config_show(request: Request):
        require_admin(request)
        import json as _json
        code, out, err = await run(["config", "show"])
        try:
            return {"ok": True, "config": _json.loads(out)}
        except (ValueError, TypeError):
            return {"ok": code == 0, "config": None, "message": _first_line(err)}

    @router.post("/api/patches/config")
    async def config_set(request: Request, body: ConfigBody):
        require_human_admin(request)
        token = body.api_token.strip()
        if not token:
            raise HTTPException(422, "api_token is required")
        # Pass the token on stdin (`config set api_token -`) so it never lands
        # in the process argument list (visible via `ps` to other local users).
        code, out, err = await run(["config", "set", "api_token", "-"], stdin=token)
        return {"ok": code == 0, "message": _first_line(out) or _first_line(err), "exit_code": code}

    return router


def _install_middleware(app):
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class _PanelInject(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            if "text/html" not in resp.headers.get("content-type", ""):
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode("utf-8")
            text = _decode_body(body, resp.headers.get("content-encoding", ""))
            if text is None:
                # couldn't decode (unexpected encoding) — re-serve the original
                # body + headers unchanged so we never corrupt the response
                return Response(content=body, status_code=resp.status_code,
                                headers=dict(resp.headers))
            data = inject_script_tag(text).encode("utf-8")
            headers = dict(resp.headers)
            headers.pop("content-encoding", None)
            headers.pop("transfer-encoding", None)
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
