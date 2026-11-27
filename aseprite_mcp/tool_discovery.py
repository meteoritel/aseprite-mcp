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

_STOP_WORDS = frozenset({
    "a", "an", "and", "at", "by", "for", "from", "in", "into", "is", "of",
    "on", "or", "the", "to", "with", "tool", "tools", "aseprite",
})


class ToolMatch(ContractModel):
    name: str
    category: str
    invocation: Literal["direct", "call_tool"]
    description: str


class BriefToolDefinition(ToolMatch):
    required: list[str]


class ToolDefinition(ToolMatch):
    inputSchema: dict[str, Any]
    outputSchema: dict[str, Any] | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)


class SearchResults(ContractModel):
    tools: list[BriefToolDefinition] | list[ToolDefinition]
    available_categories: list[str]
    next_offset: int | None


def _words(text: str) -> set[str]:
    raw = set(re.findall(r"[^\W_]+", text.casefold()))
    expanded = set(raw)
    for token in raw:
        if token.isascii() and len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            expanded.add(token[:-1])
    return expanded


def _ascii_phrase_matches(phrase: str, query: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", query) is not None


def _non_ascii_chunks(text: str) -> list[str]:
    return re.findall(r"[^\x00-\x7f]+", text)


def _cjk_bigrams(chunks: list[str]) -> set[str]:
    bigrams: set[str] = set()
    for chunk in chunks:
        if len(chunk) <= 2:
            bigrams.add(chunk)
        else:
            bigrams.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return bigrams


def create_discovery_tools(extensions: dict[str, tuple[str, Tool]], core: dict[str, tuple[str, Tool]] | None = None) -> list[Tool]:
    catalog = {**(core or {}), **extensions}
    categories = list(dict.fromkeys(category for category, _ in catalog.values()))
    tool_terms = {
        name: tuple(term.casefold() for term in TOOL_SEARCH_TERMS.get(name, ()))
        for name in catalog
    }
    cjk_terms = {term for terms in tool_terms.values() for term in terms if not term.isascii()}
    ascii_terms = {term for terms in tool_terms.values() for term in terms if term.isascii()}
    tool_cjk_bigrams = {
        name: _cjk_bigrams([term for term in terms if not term.isascii()])
        for name, terms in tool_terms.items()
    }

    def ranked(query: str, category: str = ""):
        exact_query = query.casefold().strip()
        if not exact_query:
            return [
                (0, index, name, tool_category, tool)
                for index, (name, (tool_category, tool)) in enumerate(catalog.items())
                if not category or category == tool_category
            ]

        matched_cjk = {term for term in cjk_terms if term in exact_query}
        matched_ascii_phrases = {term for term in ascii_terms if _ascii_phrase_matches(term, exact_query)}
        raw_tokens = _words(exact_query)
        ascii_tokens = {token for token in raw_tokens if token.isascii()}
        if matched_cjk or matched_ascii_phrases:
            phrase_words = set().union(*(_words(p) for p in matched_ascii_phrases)) if matched_ascii_phrases else set()
            required_tokens = ascii_tokens - phrase_words
        else:
            required_tokens = raw_tokens

        exact_matches = []
        partial_matches = []
        meaningful_ascii = ascii_tokens - _STOP_WORDS
        query_cjk_bigrams = _cjk_bigrams(_non_ascii_chunks(exact_query)) if not matched_cjk else set()

        for index, (name, (tool_category, tool)) in enumerate(catalog.items()):
            if category and category != tool_category:
                continue
            terms_for_tool = tool_terms[name]
            name_words = _words(name)
            description = tool.description.split("\n\n", 1)[0]
            category_words = _words(tool_category)
            short_words = _words(description)
            term_words = _words(" ".join(terms_for_tool))
            all_words = _words(" ".join((name, tool_category, tool.description, *tool.parameters.get("properties", {})))) | term_words

            exact = name.casefold() == exact_query
            cjk_hits = matched_cjk.intersection(terms_for_tool)
            ascii_phrase_hits = matched_ascii_phrases.intersection(terms_for_tool)
            phrase_hits = cjk_hits | ascii_phrase_hits

            tokens_satisfied = (not required_tokens) or (required_tokens <= all_words)
            meaningful_required = required_tokens - _STOP_WORDS
            phrase_partial_ok = bool(phrase_hits) and (
                not meaningful_required
                or len(meaningful_required & all_words) * 2 >= len(meaningful_required)
            )
            phrases_satisfied = (not matched_cjk or bool(cjk_hits)) and (not matched_ascii_phrases or bool(ascii_phrase_hits) or (ascii_tokens and ascii_tokens <= all_words))

            if exact or ((tokens_satisfied or phrase_partial_ok) and phrases_satisfied and (phrase_hits or required_tokens)):
                score = (
                    (1000 if exact else 0)
                    + (40 if tokens_satisfied else 0)
                    + 100 * len(ascii_tokens & name_words)
                    + 80 * len(ascii_tokens & category_words)
                    + 20 * len(ascii_tokens & term_words)
                    + 10 * len(ascii_tokens & short_words)
                    + 100 * len(phrase_hits)
                )
                if exact_query in phrase_hits:
                    score += 100
                # Longer specific phrase matches (e.g. "分层绘制" over "绘制") rank higher.
                score += sum(len(hit) * 5 for hit in phrase_hits)
                exact_matches.append((-score, index, name, tool_category, tool))
                continue

            # Soft fallback for multi-word English queries with synonyms or unseen Chinese phrasing.
            overlap_score = 0
            if len(meaningful_ascii) >= 2:
                hits = meaningful_ascii & all_words
                if len(hits) * 2 >= len(meaningful_ascii):
                    overlap_score += (
                        60 * len(hits & name_words)
                        + 40 * len(hits & category_words)
                        + 25 * len(hits & term_words)
                        + 15 * len(hits)
                    )
            if query_cjk_bigrams:
                bigram_hits = query_cjk_bigrams & tool_cjk_bigrams[name]
                if bigram_hits:
                    overlap_score += 40 * len(bigram_hits)
            if overlap_score > 0:
                partial_matches.append((-overlap_score, index, name, tool_category, tool))

        if exact_matches:
            return sorted(exact_matches)
        return sorted(partial_matches)

    def candidates(name):
        words = _words(name)
        scored = []
        for key, (category, tool) in catalog.items():
            semantic = len(words & _words(key + " " + category + " " + " ".join(tool_terms[key])))
            score = semantic + SequenceMatcher(None, name.casefold(), key.casefold()).ratio()
            scored.append((-score, key, category, tool))
        return sorted(scored)[:3]

    def definition(name, category, tool, detail):
        invocation = "call_tool" if name in extensions else "direct"
        if detail == "brief":
            return BriefToolDefinition(
                name=name, category=category, invocation=invocation,
                description=tool.description.partition("\n")[0], required=tool.parameters.get("required", []),
            )
        return ToolDefinition(
            name=name, category=category, invocation=invocation,
            description=tool.description, inputSchema=tool.parameters, outputSchema=tool.output_schema,
            examples=tool.parameters.get("examples", []),
        )

    async def search_tools(
        query: str = "",
        category: str = "",
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        offset: Annotated[int, Field(ge=0)] = 0,
        detail: Literal["brief", "full"] = "brief",
    ) -> ToolOutput[SearchResults]:
        """Discover all core and extension tools (including tools hidden behind call_tool).

        Extension capabilities discovered here and invoked via `call_tool`:
        - fx/native_fx: 1px outlines (outline_native, outline_cel), HSL & brightness/contrast, Bayer dither fills/gradients, blur/sharpen/emboss convolution.
        - scene/sprite_map: copy_layers_between_sprites (cross-file layer reuse), create_layered_sprite (split composite ASCII grid into layers).
        - slices/export: create_slice, 9-patch centers, export_slices_to_minecraft (batch item sets), export_spritesheet, export_layers.
        - animation/quality/text/tilemap/preview: eased tweening & oscillation, scene/animation audit & sanitize, pixel text, tilemaps, local HTTP preview.

        Use `detail="brief"` to browse, then query the exact tool name with `detail="full", limit=1` for its inputSchema and verified examples.

        Args:
            query: Tool names, categories, English/Chinese intent words (e.g. 'outline', '描边', 'brightness', '亮度', 'copy layer', '切片', '拼图'). Empty browses.
            category: Exact category (e.g. fx, native_fx, scene, slices, export, quality, animation, text, tilemap, preview). Empty searches all.
            limit: Page size, from 1 to 20.
            offset: Nonnegative position; use next_offset to continue.
            detail: Brief returns summary, invocation ('direct' or 'call_tool'), and required args. Use detail='full' with limit=1 for complete schema and examples.
        """
        if category and category not in categories:
            raise ToolError(f"Unknown category '{category}'. Available categories: {', '.join(categories)}")
        matches = ranked(query, category)
        selected = matches[offset:offset + limit]
        tools = [definition(name, cat, tool, detail) for _, _, name, cat, tool in selected]
        if not matches and query and offset == 0:
            suggested = [definition(name, cat, tool, detail) for _, name, cat, tool in candidates(query)
                         if not category or cat == category]
            return ToolOutput(summary="No exact capability match; inspect these suggested tools before calling.",
                              data=SearchResults(tools=suggested[:limit], available_categories=categories, next_offset=None))
        next_offset = offset + len(tools)
        return ToolOutput(
            summary="Matching tools (call 'direct' tools by name; call 'call_tool' extensions via call_tool(name=..., arguments=...)).",
            data=SearchResults(
                tools=tools, available_categories=categories,
                next_offset=next_offset if next_offset < len(matches) else None,
            ),
        )

    async def call_tool(name: str, arguments: dict[str, Any], ctx: Context) -> ToolOutput[JsonValue]:
        """Execute an extension tool (invocation='call_tool' from search_tools); core tools are called directly.

        Fetch the exact inputSchema and verified examples first via
        `search_tools(query="<tool_name>", detail="full", limit=1)`.

        Args:
            name: Extension name from search_tools, such as outline_native, adjust_brightness_contrast, copy_layers_between_sprites, create_layered_sprite, or export_slices_to_minecraft.
            arguments: Target tool arguments matching its inputSchema and examples.
        """
        if name not in extensions:
            if name in catalog:
                raise ToolError(f"'{name}' is a core tool; call {name} directly with its arguments.")
            suggestions = "; ".join(
                f"{key} ({'call_tool' if key in extensions else 'direct'}): {tool.description.splitlines()[0]}"
                for _, key, _, tool in candidates(name)
            )
            raise ToolError(
                f"Unknown extension tool '{name}'. Use search_tools(query=..., detail='full', limit=1) to inspect contracts. "
                f"Candidates: {suggestions}"
            )
        return await extensions[name][1].run(arguments, ctx, convert_result=True)

    return [ContractTool.from_function(search_tools), ContractTool.from_function(call_tool)]
