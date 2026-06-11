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


def main() -> int:
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

    from .cli import MANIFEST_RELPATH, find_checkout
    from .gitops import GitRepo
    from .manifest import Manifest
    from .status import build_status

    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", default=".")
    args = parser.parse_args()
    checkout = find_checkout(Path(args.checkout))

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
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        repo = GitRepo(checkout)
        manifest = Manifest.load(checkout / MANIFEST_RELPATH)
        status = build_status(repo, manifest)
        if name == "list_patches":
            payload = status["patches"]
        elif name == "patch_status":
            payload = {k: v for k, v in status.items() if k != "patches"}
        else:
            return [TextContent(type="text", text=f"unknown tool: {name}")]
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
