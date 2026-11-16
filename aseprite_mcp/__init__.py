"""Aseprite MCP - Model Context Protocol implementation for Aseprite."""

import os
import asyncio
from contextlib import asynccontextmanager

from mcp.server import MCPServer

_FALLBACK_INSTRUCTIONS = """\
Aseprite MCP: every tool that touches a sprite file takes an optional
`filename`, except create_canvas which REQUIRES an absolute `filename` and
rejects relative paths. The first call that names a file (create_canvas, or
any explicit filename) anchors it as the session's active file; later calls
may omit `filename` and act on it. Relative paths on other tools resolve
against ASERITE_MCP_WORKSPACE (if set) or the server working directory;
absolute paths are used as-is.
"""


def _load_skill_instructions() -> str:
    """Read SKILL.md from the project root for the MCP `instructions` field.

    Falls back to a short built-in summary when the file is missing (e.g.
    installed as a package or in Docker without the repo root).
    """
    skill_path = os.path.join(os.path.dirname(__file__), "..", "SKILL.md")
    try:
        with open(skill_path, encoding="utf-8") as f:
            content = f.read().strip()
        return content or _FALLBACK_INSTRUCTIONS
    except OSError:
        return _FALLBACK_INSTRUCTIONS


@asynccontextmanager
async def _lifespan(server):
    from .core.state import cleanup_review_directory
    try:
        yield None
    finally:
        cleanup_review_directory()


_tool_lock = asyncio.Lock()


async def _serialize_tools(context, call_next):
    if context.method == "tools/call":
        async with _tool_lock:
            return await call_next(context)
    return await call_next(context)


mcp = MCPServer("aseprite", instructions=_load_skill_instructions(),
                lifespan=_lifespan, middleware=[_serialize_tools])

__version__ = "0.1.0"
__author__ = "Divyansh Singh"
