"""Aseprite MCP - Model Context Protocol implementation for Aseprite."""

import os

from mcp.server.fastmcp import FastMCP

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


mcp = FastMCP("aseprite", instructions=_load_skill_instructions())

__version__ = "0.1.0"
__author__ = "Divyansh Singh"
