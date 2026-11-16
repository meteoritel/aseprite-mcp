"""Aseprite MCP - Model Context Protocol implementation for Aseprite."""

import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

from mcp.server import MCPServer
from .core.contracts import ContractTool

from .tool_catalog import CORE_TOOLS, DISCOVERY_TOOLS, EXTENSION_TOOLS
from .tool_discovery import create_discovery_tools

def _load_skill_instructions() -> str:
    """Load the required checkout instructions for MCP initialization."""
    skill_path = Path(__file__).resolve().parent.parent / "SKILL.md"
    recovery = f"Restore a readable, nonempty UTF-8 SKILL.md at '{skill_path}' from the source checkout."
    try:
        content = skill_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Cannot read MCP instructions. {recovery}") from exc
    if not content:
        raise RuntimeError(f"MCP instructions are blank. {recovery}")
    return content


@asynccontextmanager
async def _lifespan(server):
    from .core.state import cleanup_review_directory
    try:
        yield None
    finally:
        cleanup_review_directory()


def _load_tools(catalog):
    for category, names in catalog.items():
        module = import_module(f".tools.{category}", __name__)
        for name in names:
            yield category, ContractTool.from_function(getattr(module, name))


def create_server() -> MCPServer:
    """Assemble a stable core tool list and the extension discovery interface."""
    instructions = _load_skill_instructions()
    core_entries = list(_load_tools(CORE_TOOLS))
    core = [tool for _, tool in core_entries]
    extensions = list(_load_tools(EXTENSION_TOOLS))
    names = [tool.name for tool in core] + [tool.name for _, tool in extensions] + list(DISCOVERY_TOOLS)
    if len(set(names)) != len(names):
        raise ValueError("Duplicate names in the tool catalog")
    discovery = create_discovery_tools({tool.name: (category, tool) for category, tool in extensions},
                                       {tool.name: (category, tool) for category, tool in core_entries})
    tool_lock = asyncio.Lock()

    async def serialize_tools(context, call_next):
        if context.method == "tools/call":
            async with tool_lock:
                return await call_next(context)
        return await call_next(context)

    return MCPServer("aseprite", instructions=instructions, tools=core + discovery,
                     lifespan=_lifespan, middleware=[serialize_tools])

__version__ = "0.1.0"
__author__ = "Divyansh Singh"
