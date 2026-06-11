"""Optional read-only MCP server: install state for the Odysseus agent.

Add via Odysseus's integrations tab (stdio transport):
  command: odysseus-patches-mcp   (or: python -m odysseus_patches.mcp_server)
  args:    ["--checkout", "/path/to/odysseus"]

Requires the 'mcp' extra: pip install 'odysseus-patches[mcp]'.
Strictly read-only — the agent can report patch state, never change it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def serve(checkout: str) -> int:
    """Run the MCP server with an already-resolved checkout path string."""
    try:
        import asyncio

        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:
        print(
            "the 'mcp' package is required: pip install 'odysseus-patches[mcp]'",
            file=sys.stderr,
        )
        return 1

    from .cli import CONFIG_RELPATH, MANIFEST_RELPATH
    from .config import Config
    from .gitops import GitRepo
    from .manifest import Manifest
    from .proposals import stage_proposal
    from .status import build_status
    from . import review as review_mod

    checkout_path = Path(checkout)

    server = Server("odysseus-patches")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_patches",
                description=(
                    "List the upstream PR patches applied to this Odysseus "
                    "install: PR number, title, pinned commit, and status "
                    "(active/conflicted/retired/closed-upstream)."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="patch_status",
                description=(
                    "Overall patch health for this install: whether the "
                    "patched branch is running and anything needing attention."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="propose_patch",
                description=(
                    "Stage an open upstream Odysseus PR as a patch PROPOSAL on "
                    "this install. Nothing is applied: a human must approve it "
                    "in the patches UI or with `odysseus-patches approve <pr>`. "
                    "Optionally runs an AI security review of the diff first "
                    "and attaches the verdict to the proposal."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pr": {"type": "integer", "description": "upstream PR number"},
                        "run_review": {
                            "type": "boolean",
                            "description": "AI-review the diff and attach the verdict (default true)",
                        },
                        "note": {"type": "string", "description": "why this PR is being proposed"},
                    },
                    "required": ["pr"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        # synchronous git/manifest I/O is fine here: stdio MCP serves one
        # client sequentially — don't "fix" with run_in_executor
        repo = GitRepo(checkout_path)
        manifest = Manifest.load(checkout_path / MANIFEST_RELPATH)
        status = build_status(repo, manifest)
        if name == "list_patches":
            payload = status["patches"]
        elif name == "patch_status":
            payload = {k: v for k, v in status.items() if k != "patches"}
        elif name == "propose_patch":
            pr = int(arguments["pr"])
            run_review = bool(arguments.get("run_review", True))
            note = str(arguments.get("note", ""))
            config = Config.load(checkout_path / CONFIG_RELPATH)
            review_runner = (
                (lambda diff: review_mod.run_review(diff, config)) if run_review else None
            )
            try:
                message = stage_proposal(
                    repo, manifest, pr,
                    run_review=run_review, note=note, proposer="agent",
                    review_runner=review_runner,
                )
            except Exception as exc:
                # never crash the stdio server — the agent gets a readable error
                message = f"could not stage proposal: {exc}"
            return [TextContent(type="text", text=message)]
        else:
            raise ValueError(f"unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", default=".")
    args = parser.parse_args()
    from .cli import find_checkout
    checkout = find_checkout(Path(args.checkout))
    return serve(str(checkout))


if __name__ == "__main__":
    sys.exit(main())
