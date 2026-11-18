"""Discover the complete tool catalog and execute extension tools."""

from difflib import SequenceMatcher
import re
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import Field, JsonValue

from .core.contracts import ContractModel, ContractTool, ToolOutput
from .tool_catalog import TOOL_SEARCH_TERMS


class ToolDefinition(ContractModel):
    name: str
    category: str
    invocation: Literal["direct", "call_tool"]
    description: str
    inputSchema: dict[str, Any]
    outputSchema: dict[str, Any] | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)


class SearchResults(ContractModel):
    tools: list[ToolDefinition]
    available_categories: list[str]
    next_offset: int | None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold()))


def create_discovery_tools(extensions: dict[str, tuple[str, Tool]], core: dict[str, tuple[str, Tool]] | None = None) -> list[Tool]:
    catalog = {**(core or {}), **extensions}
    categories = list(dict.fromkeys(category for category, _ in catalog.values()))
    workflow_terms = set().union(*TOOL_SEARCH_TERMS.values())

    def ranked(query, category=""):
        tokens = _words(query)
        terms = {term for term in workflow_terms if term in query}
        if terms:
            tokens = {token for token in tokens if token.isascii()}
        matches = []
        for index, (name, (tool_category, tool)) in enumerate(catalog.items()):
            if category and category != tool_category:
                continue
            name_words = _words(name)
            description = tool.description.split("\n\n", 1)[0]
            category_words = _words(tool_category)
            short_words = _words(description)
            all_words = _words(" ".join((name, tool_category, tool.description, *tool.parameters.get("properties", {}))))
            exact = name.casefold() == query.casefold().strip()
            if tokens and not exact and not tokens <= all_words:
                continue
            term_matches = terms.intersection(TOOL_SEARCH_TERMS.get(name, ()))
            if terms and not term_matches:
                continue
            score = (1000 if exact else 0) + 100 * len(tokens & name_words) + 80 * len(tokens & category_words) + 10 * len(tokens & short_words)
            score += 100 * len(term_matches)
            matches.append((-score, index, name, tool_category, tool))
        return sorted(matches)

    def candidates(name):
        words = _words(name)
        scored = []
        for key, (category, tool) in catalog.items():
            semantic = len(words & _words(key + " " + category))
            score = semantic + SequenceMatcher(None, name.casefold(), key.casefold()).ratio()
            scored.append((-score, key, category, tool))
        return sorted(scored)[:3]

    def definition(name, category, tool):
        return ToolDefinition(
            name=name, category=category, invocation="call_tool" if name in extensions else "direct",
            description=tool.description, inputSchema=tool.parameters, outputSchema=tool.output_schema,
            examples=tool.parameters.get("examples", []),
        )

    async def search_tools(
        query: str = "",
        category: str = "",
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> ToolOutput[SearchResults]:
        """Find core and extension tools, schemas, examples and the correct invocation.

        Args:
            query: Tool names, categories, purpose words or Chinese workflow terms such as 审阅 and 复核. Empty browses.
            category: Exact category, such as text, tilemap or quality. Empty searches all.
            limit: Page size, from 1 to 20.
            offset: Nonnegative position; use next_offset to continue.
        """
        if category and category not in categories:
            raise ToolError(f"Unknown category '{category}'. Available categories: {', '.join(categories)}")
        matches = ranked(query, category)
        selected = matches[offset:offset + limit]
        tools = [definition(name, category, tool) for _, _, name, category, tool in selected]
        if not matches and query and offset == 0:
            suggested = [definition(name, cat, tool) for _, name, cat, tool in candidates(query)
                         if not category or cat == category]
            return ToolOutput(summary="No exact capability match; inspect these suggested tools before calling.",
                              data=SearchResults(tools=suggested[:limit], available_categories=categories, next_offset=None))
        next_offset = offset + len(tools)
        return ToolOutput(summary="Matching tools and their invocation contracts", data=SearchResults(
            tools=tools, available_categories=categories,
            next_offset=next_offset if next_offset < len(matches) else None,
        ))

    async def call_tool(name: str, arguments: dict[str, Any], ctx: Context) -> ToolOutput[JsonValue]:
        """Execute an extension using its discovered inputSchema; core tools are called directly.

        Args:
            name: Extension name from search_tools, such as draw_text.
            arguments: Original target arguments. Follow its inputSchema and examples.
        """
        if name not in extensions:
            if name in catalog:
                raise ToolError(f"'{name}' is a core tool; call {name} directly with its arguments.")
            suggestions = "; ".join(
                f"{key} ({'call_tool' if key in extensions else 'direct'}): {tool.description.splitlines()[0]}"
                for _, key, _, tool in candidates(name)
            )
            raise ToolError(f"Unknown extension tool '{name}'. Use search_tools. Candidates: {suggestions}")
        return await extensions[name][1].run(arguments, ctx, convert_result=True)

    return [ContractTool.from_function(search_tools), ContractTool.from_function(call_tool)]
