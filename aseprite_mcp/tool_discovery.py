"""Expose extension schemas and execute them through standard MCP tools."""

from typing import Annotated, Any

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.types import CallToolResult, InputRequiredResult
from pydantic import Field

from .tool_catalog import DISCOVERY_TOOLS


def create_discovery_tools(extensions: dict[str, tuple[str, Tool]]) -> list[Tool]:
    categories = list(dict.fromkeys(category for category, _ in extensions.values()))

    async def search_tools(
        query: str = "",
        category: str = "",
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Find extension tools and their full schemas. Execute them with call_tool.

        Args:
            query: Space-separated words matched in names, descriptions and parameter names; empty browses.
            category: Module category, such as text or tilemap; empty searches all categories.
            limit: Page size, from 1 to 20.
            offset: Nonnegative position in the matching tools; use next_offset for the next page.
        """
        if category and category not in categories:
            raise ToolError(f"Unknown category '{category}'. Available categories: {', '.join(categories)}")
        normalized = query.casefold().strip()
        words = normalized.split()
        matches = []
        for name, (tool_category, tool) in extensions.items():
            if category and category != tool_category:
                continue
            searchable = " ".join((name, tool.description, *tool.parameters.get("properties", {}))).casefold()
            if all(word in searchable for word in words):
                matches.append((tool_category, tool))
        matches.sort(key=lambda entry: entry[1].name.casefold() != normalized)
        tools = []
        for tool_category, tool in matches[offset:offset + limit]:
            definition = {
                "name": tool.name, "category": tool_category,
                "description": tool.description, "inputSchema": tool.parameters,
            }
            if tool.output_schema is not None:
                definition["outputSchema"] = tool.output_schema
            if tool.annotations is not None:
                definition["annotations"] = tool.annotations.model_dump(by_alias=True, exclude_none=True)
            tools.append(definition)
        next_offset = offset + len(tools)
        return {
            "tools": tools, "available_categories": categories,
            "next_offset": next_offset if next_offset < len(matches) else None,
        }

    async def call_tool(name: str, arguments: dict[str, Any], ctx: Context) -> CallToolResult | InputRequiredResult:
        """Execute an extension tool by its original name with its original arguments.

        Use search_tools to discover names and complete input schemas, or call a known
        extension directly. Core tools are called directly, outside this proxy.

        Args:
            name: Extension tool name, such as draw_text.
            arguments: The target tool's parameter object, following its inputSchema.
        """
        if name not in extensions:
            raise ToolError(f"Unknown extension tool '{name}'. Use search_tools to find extensions; call core tools directly.")
        # The outer tools/call owns serialization and cancellation for the whole edit.
        return await extensions[name][1].run(arguments, ctx, convert_result=True)

    return [Tool.from_function(fn, name=name)
            for name, fn in zip(DISCOVERY_TOOLS, (search_tools, call_tool), strict=True)]
