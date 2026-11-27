"""Pure character-grid parsing, mirrored painting and exact RGBA encoding."""

from collections import Counter
import json
from typing import Any, Dict, List
from mcp.server.mcpserver.exceptions import ToolError
from .colors import parse_hex_color
from .contracts import Region, SpriteLayerRule
from .results import PixelChanges

_AUTO_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MAX_GRID_DIAGNOSTICS = 5


class SpriteMapCapacityError(ToolError):
    """Exact colors do not fit the available character slots."""


def decode_sprite_map(rows, palette, transparent, region: Region) -> bytes:
    parsed, error = parse_sprite_map(rows, palette, transparent)
    if error:
        raise ToolError(f"Invalid before grid: {error}")
    width, height, cells = parsed
    if (width, height) != (region.width, region.height):
        raise ToolError("Before grid dimensions must match the review region")
    pixels = bytearray(width * height * 4)
    for x, y, rgba in cells:
        start = (y * width + x) * 4
        pixels[start:start + 4] = bytes(rgba)
    return bytes(pixels)


def compare_region_pixels(before: bytes, after: bytes, region: Region) -> PixelChanges:
    if before == after:
        return {"changed_pixels": 0, "changed_bounds": None}
    count = 0
    left, top, right, bottom = region.width, region.height, -1, -1
    for start in range(0, max(len(before), len(after)), 4):
        old, new = before[start:start + 4], after[start:start + 4]
        # An absent cel and a fully transparent pixel have the same appearance.
        if old == new or not ((old and old[3]) or (new and new[3])):
            continue
        y, x = divmod(start // 4, region.width)
        count += 1
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x), max(bottom, y)
    if not count:
        return {"changed_pixels": 0, "changed_bounds": None}
    return {
        "changed_pixels": count,
        "changed_bounds": {"x": region.x + left, "y": region.y + top,
                           "width": right - left + 1, "height": bottom - top + 1},
    }


def parse_sprite_map(
    rows: List[str], palette: Dict[str, str], transparent: str
) -> tuple[tuple[int, int, List[tuple[int, int, tuple[int, int, int, int]]]] | None, str | None]:
    """Validate a sprite map and flatten it to (width, height, cells).

    Each cell is (col, row, (r, g, b, a)) with col/row relative to the
    grid's top-left. Every character must be either `transparent` or a key
    of `palette`, and all rows must be the same length.

    Returns ((width, height, cells), None) on success, or (None, error).
    """
    if not rows:
        return None, "rows must contain at least one row"
    if not isinstance(transparent, str) or len(transparent) != 1:
        return None, f"transparent must be a single character, got {transparent!r}"
    if not isinstance(rows[0], str):
        return None, f"rows[0] must be a string, got {type(rows[0]).__name__}"

    width = len(rows[0])
    if width == 0:
        return None, "rows must be non-empty strings"

    colours: Dict[str, tuple[int, int, int, int]] = {}
    if not isinstance(palette, dict):
        return None, f"palette must be an object, got {type(palette).__name__}"
    for char, value in palette.items():
        if not isinstance(char, str) or len(char) != 1:
            return None, f"palette keys must be single characters, got {char!r}"
        if char == transparent:
            return None, (
                f"palette must not contain the transparent character "
                f"{transparent!r} — it is reserved for empty cells"
            )
        rgba = parse_hex_color(value)
        if rgba is None:
            return None, f"Invalid colour for palette[{char!r}]: {value!r}"
        colours[char] = rgba

    for index, row in enumerate(rows):
        if not isinstance(row, str):
            return None, f"rows[{index}] must be a string, got {type(row).__name__}"

    # When 3+ rows have a clear majority width, diagnose against that width so a typo on rows[0] blames rows[0].
    expected_width = width
    majority_count = 0
    if len(rows) >= 3:
        counts = Counter(len(row) for row in rows)
        most_common = counts.most_common(2)
        if most_common[0][1] > 1 and (len(most_common) == 1 or most_common[0][1] > most_common[1][1]):
            expected_width, majority_count = most_common[0]

    width_errors: list[str] = []
    for index, row in enumerate(rows):
        if len(row) != expected_width:
            column = min(expected_width, len(row))
            start, stop = max(0, column - 24), min(len(row), column + 24)
            label = f"rows[{index}][{start}:{stop}] = "
            excerpt = json.dumps(row[start:stop])
            caret = " " * (len(label) + len(json.dumps(row[start:column])) - 1)
            position = "first missing cell" if len(row) < expected_width else "grid right boundary"
            if expected_width == width:
                header = (
                    f"rows must form a rectangle: rows[0] has {width} character(s) "
                    f"but rows[{index}] has {len(row)}"
                )
            else:
                header = (
                    f"rows must form a rectangle: {majority_count} of {len(rows)} rows have {expected_width} character(s) "
                    f"but rows[{index}] has {len(row)}"
                )
            width_errors.append(f"{header}\n{label}{excerpt}\n{caret}^ column {column} ({position}, zero-based)")
    if width_errors:
        shown = width_errors[:_MAX_GRID_DIAGNOSTICS]
        extra = f"\n... and {len(width_errors) - len(shown)} more row width mismatch(es)" if len(width_errors) > len(shown) else ""
        return None, "\n".join(shown) + extra

    cells: List[tuple[int, int, tuple[int, int, int, int]]] = []
    unknown_errors: list[str] = []
    for row_index, row in enumerate(rows):
        for col_index, char in enumerate(row):
            if char == transparent:
                continue
            rgba = colours.get(char)
            if rgba is None:
                if len(unknown_errors) < _MAX_GRID_DIAGNOSTICS:
                    unknown_errors.append(
                        f"Unknown character {char!r} at row {row_index}, column {col_index}"
                    )
                continue
            cells.append((col_index, row_index, rgba))
    if unknown_errors:
        keys_hint = (
            f"Available palette keys: {sorted(colours)}"
            if colours
            else "palette is empty"
        )
        return None, (
            "; ".join(unknown_errors)
            + f" — add it to palette, or use {transparent!r} for an empty cell ({keys_hint})"
        )

    return (width, len(rows), cells), None


def compile_layered_sprite(rows: list[str], palette: dict[str, str], layers: list[SpriteLayerRule], transparent: str):
    parsed, error = parse_sprite_map(rows, palette, transparent)
    if error:
        raise ToolError(f"Invalid sprite map: {error}")
    width, height, cells = parsed
    stacks = {}
    for index, layer in enumerate(layers):
        for source, target in layer.mapping.items():
            if source not in palette or target not in palette:
                raise ToolError(f"layers[{index}].mapping[{source!r}] = {target!r}: both must be palette characters distinct from {transparent!r}")
            rgba = parse_hex_color(palette[target])
            if rgba[3] != 255:
                raise ToolError(f"layers[{index}].mapping[{source!r}]: palette[{target!r}] must be opaque")
            stacks.setdefault(source, []).append((index, rgba))

    pixels_by_layer = [[] for _ in layers]
    for x, y, rgba in cells:
        symbol = rows[y][x]
        stack = stacks.get(symbol)
        if not stack:
            raise ToolError(f"No layer mapping for {symbol!r} at row {y}, column {x}")
        if rgba[3] != 255:
            raise ToolError(f"palette[{symbol!r}] at row {y}, column {x} must be opaque")
        if stack[-1][1] != rgba:
            raise ToolError(f"Top layer mapping for {symbol!r} at row {y}, column {x} must preserve its palette colour")
        for index, colour in stack:
            pixels_by_layer[index].append([x, y, *colour])
    return width, height, pixels_by_layer


def _hex_of(rgba: tuple[int, int, int, int]) -> str:
    """#RRGGBB for opaque colours, #RRGGBBAA when alpha is partial."""
    r, g, b, a = rgba
    if a == 255:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{r:02x}{g:02x}{b:02x}{a:02x}"

def _quantise(
    colours: List[tuple[int, int, int, int]],
    counts: Dict[tuple[int, int, int, int], int],
    max_colors: int,
) -> Dict[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Map every colour to one of the `max_colors` most frequent colours.

    Keeps the most-used colours and snaps the rest to the nearest kept one
    by squared RGB distance, so an antialiased sprite reads back as a valid
    map instead of failing on colour-count overflow.
    """
    keep = sorted(colours, key=lambda c: (-counts[c], c))[:max_colors]
    mapping: Dict[tuple[int, int, int, int], tuple[int, int, int, int]] = {}
    for colour in colours:
        if colour in keep:
            mapping[colour] = colour
            continue
        nearest = min(
            keep,
            key=lambda k: (k[0] - colour[0]) ** 2
            + (k[1] - colour[1]) ** 2
            + (k[2] - colour[2]) ** 2,
        )
        mapping[colour] = nearest
    return mapping


def compile_sprite_map(rows, palette, transparent=".", mirror_x=False, mirror_y=False, erase_transparent=False):
    parsed, error = parse_sprite_map(rows, palette, transparent)
    if error:
        raise ToolError(f"Invalid sprite map: {error}")
    width, height, cells = parsed
    pixels = {}
    for col, row, rgba in cells:
        positions = {(col, row)}
        if mirror_x: positions.add((width - 1 - col, row))
        if mirror_y: positions.add((col, height - 1 - row))
        if mirror_x and mirror_y: positions.add((width - 1 - col, height - 1 - row))
        for position in positions:
            if position in pixels and pixels[position] != rgba:
                raise ToolError(f"Invalid sprite map: conflicting mirrored colours at column {position[0]}, row {position[1]}")
            pixels[position] = rgba
    if erase_transparent:
        for row in range(height):
            for col in range(width): pixels.setdefault((col, row), (0, 0, 0, 0))
    return width, height, pixels


def encode_sprite_map(cells, *, frame_index, x, y, width, height, palette=None,
                      alpha_threshold=1, max_colors=0, transparent=".", source="composite", layer=None):
    char_to_rgba, rgba_to_char = {}, {}
    for char, value in (palette or {}).items():
        if len(char) != 1 or char == transparent:
            raise ToolError("Palette keys must be single characters distinct from transparent")
        rgba = parse_hex_color(value)
        if rgba is None: raise ToolError(f"Invalid colour for palette[{char!r}]: {value!r}")
        if rgba not in rgba_to_char:
            rgba_to_char[rgba]=char; char_to_rgba[char]=rgba
    is_lossy = any(0 < rgba[3] < alpha_threshold for rgba in cells.values())

    counts: Dict[tuple[int, int, int, int], int] = {}
    for rgba in cells.values():
        if rgba[3] >= alpha_threshold:
            counts[rgba] = counts.get(rgba, 0) + 1

    if max_colors > 0 and len(counts) > max_colors:
        remap = _quantise(list(counts), counts, max_colors)
        is_lossy = is_lossy or any(colour != mapped for colour, mapped in remap.items())
        cells = {
            pos: remap.get(rgba, rgba) for pos, rgba in cells.items()
        }
        counts = {}
        for rgba in cells.values():
            if rgba[3] >= alpha_threshold:
                counts[rgba] = counts.get(rgba, 0) + 1

    # Anything the caller's palette did not cover is auto-assigned from the
    # alphabet that is still free.
    free = [c for c in _AUTO_ALPHABET if c != transparent and c not in char_to_rgba]
    extra = sorted(colour for colour in counts if colour not in rgba_to_char)
    if len(extra) > len(free):
        raise SpriteMapCapacityError(f"Invalid colour count: the region uses {len(counts)} distinct "
            f"colour(s) but only {len(char_to_rgba) + len(free)} "
            f"single-character slot(s) are available — pass max_colors to "
            f"quantise, or a palette covering the colours you care about")
    for rgba, char in zip(extra, free):
        rgba_to_char[rgba] = char
        char_to_rgba[char] = rgba

    rows_out = []
    for row in range(height):
        line = []
        for col in range(width):
            rgba = cells.get((col, row), (0, 0, 0, 0))
            if rgba[3] < alpha_threshold:
                line.append(transparent)
            else:
                line.append(rgba_to_char[rgba])
        rows_out.append("".join(line))

    result: Dict[str, Any] = {
        "source": source,
        "layer": layer,
        "frame": frame_index,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "transparent": transparent,
        "palette": {char: _hex_of(char_to_rgba[char]) for char in sorted(char_to_rgba)},
        "rows": rows_out,
        "lossy": is_lossy,
    }
    # A single-character-per-column ruler only exists while the alphabet
    # lasts; past that the region is wide enough that rows are self-describing.
    if width <= len(_AUTO_ALPHABET):
        result["columns"] = _AUTO_ALPHABET[:width]

    return result
