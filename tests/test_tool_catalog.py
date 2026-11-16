"""The tool catalog drives runtime registration and deterministic documentation."""

import asyncio
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools import Tool
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel

from aseprite_mcp import create_server
from aseprite_mcp.tool_catalog import CORE_TOOLS, DISCOVERY_TOOLS, EXTENSION_TOOLS
from aseprite_mcp.tool_discovery import create_discovery_tools


def test_imports_do_not_change_public_tools():
    async def check():
        server = create_server()
        before = await server.list_tools()
        for category in EXTENSION_TOOLS:
            importlib.reload(importlib.import_module(f"aseprite_mcp.tools.{category}"))
        assert await server.list_tools() == before
        assert [tool.name for tool in before] == [name for names in CORE_TOOLS.values() for name in names] + list(DISCOVERY_TOOLS)
        assert await create_server().list_tools() == before
    asyncio.run(check())


class NestedArguments(BaseModel):
    value: int = 7


def test_discovery_retains_nested_schema_context_and_result_semantics():
    contexts = []

    async def extension(sample: NestedArguments, ctx: Context) -> CallToolResult:
        contexts.append(ctx)
        return CallToolResult(content=[TextContent(type="text", text="target content")],
                              structured_content={"value": sample.value}, is_error=sample.value < 0)

    target = Tool.from_function(extension, annotations=ToolAnnotations(read_only_hint=True))
    server = MCPServer("discovery-test", tools=create_discovery_tools({"extension": ("test", target)}))

    async def check():
        result = await server.call_tool("search_tools", {"query": "extension"})
        definition = json.loads(result.content[0].text)["tools"][0]
        assert definition["inputSchema"] == target.parameters
        assert "$defs" in definition["inputSchema"]
        assert definition["annotations"]["readOnlyHint"] is True
        context = Context(mcp_server=server)
        for arguments, value, is_error in (({"sample": {}}, 7, False), ({"sample": {"value": -1}}, -1, True)):
            result = await server.call_tool("call_tool", {"name": "extension", "arguments": arguments}, context)
            assert result.content == [TextContent(type="text", text="target content")]
            assert result.structured_content == {"value": value}
            assert result.is_error is is_error
            assert contexts[-1] is context
    asyncio.run(check())


def test_reference_generation_without_git_and_stale_interface_detection(tmp_path):
    root = Path(__file__).resolve().parent.parent
    shutil.copytree(root / "aseprite_mcp", tmp_path / "aseprite_mcp", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "scripts").mkdir()
    shutil.copy2(root / "scripts/gen_tool_reference.py", tmp_path / "scripts/gen_tool_reference.py")
    command = [sys.executable, "-S", str(tmp_path / "scripts/gen_tool_reference.py")]
    subprocess.run(command, check=True, capture_output=True)
    generated = tmp_path / "docs/reference/tools.md"
    assert generated.read_bytes() == (root / "docs/reference/tools.md").read_bytes()
    subprocess.run(command + ["--check"], check=True, capture_output=True)

    catalog = tmp_path / "aseprite_mcp/tool_catalog.py"
    core, extensions = dict(CORE_TOOLS), dict(EXTENSION_TOOLS)
    core["text"] = ("measure_text",)
    extensions["text"] = tuple(name for name in extensions["text"] if name != "measure_text")
    catalog.write_text(f"CORE_TOOLS = {core!r}\nEXTENSION_TOOLS = {extensions!r}\nDISCOVERY_TOOLS = {DISCOVERY_TOOLS!r}\n", encoding="utf-8")
    assert subprocess.run(command + ["--check"], capture_output=True).returncode == 1
    subprocess.run(command, check=True, capture_output=True)
    text = tmp_path / "aseprite_mcp/tools/text.py"
    text.write_text(text.read_text(encoding="utf-8").replace("size: int = 1,", "size: int = 2,"), encoding="utf-8")
    assert subprocess.run(command + ["--check"], capture_output=True).returncode == 1


@pytest.mark.parametrize("resource", ["missing", "blank", "unreadable", "invalid-utf8"])
def test_startup_requires_readable_nonempty_instructions(tmp_path, resource):
    root = Path(__file__).resolve().parent.parent
    shutil.copytree(root / "aseprite_mcp", tmp_path / "aseprite_mcp", ignore=shutil.ignore_patterns("__pycache__"))
    skill = tmp_path / "SKILL.md"
    if resource == "blank":
        skill.write_text(" \n\t", encoding="utf-8")
    elif resource == "unreadable":
        skill.mkdir()
    elif resource == "invalid-utf8":
        skill.write_bytes(b"\xff")
    result = subprocess.run([sys.executable, "-B", "-m", "aseprite_mcp"], cwd=tmp_path,
                            input="", capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode != 0
    assert not result.stdout
    assert str(skill) in result.stderr
    assert "Restore a readable, nonempty UTF-8 SKILL.md" in result.stderr
