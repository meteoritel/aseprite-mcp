"""Pure character-grid parsing, mirrored painting and exact RGBA encoding."""

from typing import Any, Dict, List
from mcp.server.mcpserver.exceptions import ToolError
from .colors import parse_hex_color

_AUTO_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

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
        if len(row) != width:
            return None, (
                f"rows must form a rectangle: rows[0] has {width} character(s) "
                f"but rows[{index}] has {len(row)}"
            )


    cells: List[tuple[int, int, tuple[int, int, int, int]]] = []
    for row_index, row in enumerate(rows):
        for col_index, char in enumerate(row):
            if char == transparent:
                continue
            rgba = colours.get(char)
            if rgba is None:
                return None, (
                    f"Unknown character {char!r} at row {row_index}, column "
                    f"{col_index} — add it to palette, or use {transparent!r} "
                    f"for an empty cell"
                )
            cells.append((col_index, row_index, rgba))

    return (width, len(rows), cells), None

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
        raise ToolError(f"Invalid colour count: the region uses {len(counts)} distinct "
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
