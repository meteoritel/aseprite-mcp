"""Compact character-grid ("sprite map") authoring and readback.

A sprite map is a rectangular grid of single characters plus a
character -> hex-colour palette. It is the compact counterpart to the
{x, y, color} pixel lists that draw_pixels_at / get_pixels_rect use: a
16x16 sprite drops from ~256 JSON objects to 16 short strings, and the
rows themselves carry the coordinate grid, so neither side has to do
index arithmetic on a 256-cell mental bitmap.

The two tools are inverses. get_sprite_map returns ``rows``,
``palette`` and ``transparent`` shaped exactly like draw_sprite_map's
arguments, so a read -> edit -> write loop needs no reformatting.
"""

from mcp.server.mcpserver.exceptions import ToolError
from ..core.editing import execute_edit_script

import json
from typing import Any, Dict, List, Optional

from ..core.colors import parse_hex_color
from ..core.commands import AsepriteCommand, lua_escape
from ..core.lua import EDIT_TARGET, FIND_LAYER, LAYER_NAMES, NORMALIZE_CEL, PSET
from ..core.state import prepare_filename
from .analysis import _COMPOSE_FRAME


# Characters used for auto-assigned palette entries. "." is reserved for
# transparent cells and never appears here, so a map read back with an
# auto-derived palette is always valid input for draw_sprite_map.
_AUTO_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

_TILEMAP_REFUSAL = (
    "is a tilemap layer: its cel stores tile indexes, not pixels, so a "
    "per-pixel read would return an index in the red channel instead of a "
    "colour"
)


def _parse_sprite_map(
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

    for index, row in enumerate(rows):
        if not isinstance(row, str):
            return None, f"rows[{index}] must be a string, got {type(row).__name__}"
        if len(row) != width:
            return None, (
                f"rows must form a rectangle: rows[0] has {width} character(s) "
                f"but rows[{index}] has {len(row)}"
            )

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


async def draw_sprite_map(*, filename: str='', layer_name: str, frame_index: int, rows: List[str], palette: Dict[str, str], x: int=0, y: int=0, transparent: str='.', mirror_x: bool=False, mirror_y: bool=False, erase_transparent: bool=False, create_if_missing: bool=True) -> str:
    """Draw a whole region from a compact character-grid map.

    `rows` is a list of equal-length strings, one per pixel row, top to
    bottom; `palette` maps each character to a colour. This is the compact
    alternative to draw_pixels_at's {x, y, color} lists:

        draw_sprite_map(
            layer_name="hero", frame_index=1,
            rows=["..1111..",
                  ".122221.",
                  "12233221"],
            palette={"1": "#3b2a1e", "2": "#8b5a2b", "3": "#f2c48d"},
        )

    Characters equal to `transparent` ("." by default) are skipped, so
    whatever is already on the layer shows through. Pass
    erase_transparent=true to clear them instead — that is what makes a
    map round-trip exactly after pixels are deleted in an edit.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer to draw on
        frame_index: Frame index starting at 1
        rows: Grid rows, top to bottom; every row must be the same length
        palette: Character -> hex colour (#RGB, #RGBA, #RRGGBB or #RRGGBBAA)
        x: Sprite-global x of the grid's top-left cell (default 0)
        y: Sprite-global y of the grid's top-left cell (default 0)
        transparent: Character meaning "no pixel here" (default ".")
        mirror_x: Also draw every cell at its left-right reflection, so a symmetric sprite only has to be authored once. The mirror is in place: the grid keeps its width, so author the full width with the far half left as `transparent`
        mirror_y: Also draw every cell at its top-bottom reflection (in place)
        erase_transparent: Clear transparent cells instead of leaving them
        create_if_missing: Create the layer (top-level names only) and cel if they don't exist
    """
    filename = prepare_filename(filename)

    parsed, map_err = _parse_sprite_map(rows, palette, transparent)
    if map_err:
        raise ToolError(f"Invalid sprite map: {map_err}")
    width, height, cells = parsed

    pixels: Dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for col, row, rgba in cells:
        positions = {(col, row)}
        if mirror_x:
            positions.add((width - 1 - col, row))
        if mirror_y:
            positions.add((col, height - 1 - row))
        if mirror_x and mirror_y:
            positions.add((width - 1 - col, height - 1 - row))
        for position in positions:
            if position in pixels and pixels[position] != rgba:
                raise ToolError(f"Invalid sprite map: conflicting mirrored colours at column {position[0]}, row {position[1]}")
            pixels[position] = rgba

    if erase_transparent:
        for row in range(height):
            for col in range(width):
                pixels.setdefault((col, row), (0, 0, 0, 0))

    if not pixels:
        return (
            f"OK: nothing to draw — every cell of the {width}x{height} map is "
            f"{transparent!r} and erase_transparent is false"
        )

    safe_layer_name = lua_escape(layer_name)
    create_flag = "true" if create_if_missing else "false"

    script = f"""
    {NORMALIZE_CEL}
    {PSET}
    {EDIT_TARGET}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end
    if spr.colorMode ~= ColorMode.RGB then print("ERROR:Sprite maps require RGB mode. Tip: use set_color_mode(mode='rgb') first.") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index {frame_index} out of range (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first.") return end

    local target = require_layer(spr, "{safe_layer_name}", {create_flag})
    if target.isTilemap then print("ERROR:Sprite maps require an image layer, not a tilemap") return end

    app.transaction(function()
        app.activeLayer = target
        app.activeFrame = spr.frames[idx]
        require_cel(spr, target, idx, {create_flag})
        local cel = normalize_cel(spr, target, spr.frames[idx], false)
        local img = cel.image
    """

    for col, row in sorted(pixels):
        r, g, b, a = pixels[(col, row)]
        script += f"""
        pset(img, {x + col}, {y + row}, Color({r}, {g}, {b}, {a}))
        """

    script += """
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return (
        f"Sprite map drawn on '{layer_name}' frame {frame_index} "
        f"({width}x{height} at {x},{y}, {len(pixels)} pixel(s)) in {filename}"
    )


async def get_sprite_map(
    *,
    filename: str = "",
    layer_name: str = "",
    frame_index: int = 1,
    x: int,
    y: int,
    width: int,
    height: int,
    palette: Optional[Dict[str, str]] = None,
    max_colors: int = 0,
    alpha_threshold: int = 1,
    transparent: str = ".",
    composite: bool = False,
) -> str:
    """Read a rectangular region back as a compact character-grid map.

    Returns JSON whose `rows`, `palette` and `transparent` are shaped
    exactly like draw_sprite_map's arguments, so a read/edit/write loop
    needs no reformatting:

        {"layer": "hero", "frame": 1, "x": 0, "y": 0,
         "width": 16, "height": 16, "transparent": ".",
         "columns": "0123456789abcdef",
         "palette": {"0": "#3b2a1e", "1": "#8b5a2b"},
         "rows": ["....0011........", ...]}

    `columns` labels each column's x offset, so a character's position can
    be read off without counting. Against get_pixels_rect's per-pixel JSON
    a 16x16 region goes from ~256 objects to 16 short strings — and unlike
    judging an exported PNG by eye, the hex values are exact.

    Auto-assigned characters follow ascending colour order. Pass `palette`
    (e.g. a previous result's) to pin the assignment: characters then stay
    stable across edits, so two maps can be diffed character by character.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        layer_name: Explicit layer name; may be empty only for composite reads
        frame_index: Frame index starting at 1
        x: Left edge of the region (sprite-global)
        y: Top edge of the region (sprite-global)
        width: Region width
        height: Region height
        palette: Optional character -> hex colour map to reuse for the output
        max_colors: Quantise to at most this many colours (0 = no limit)
        alpha_threshold: Alpha below this becomes `transparent` (default 1)
        transparent: Character emitted for empty cells (default ".")
        composite: Read the visible flattened composite instead of a single layer
    """
    filename = prepare_filename(filename)
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")
    if max_colors < 0:
        raise ToolError("max_colors must be >= 0")
    if not 0 <= alpha_threshold <= 255:
        raise ToolError("alpha_threshold must be between 0 and 255")
    if not composite and not layer_name:
        raise ToolError("Invalid layer_name: specify an explicit layer, or composite=true")
    if not isinstance(transparent, str) or len(transparent) != 1:
        raise ToolError(f"Invalid transparent: must be a single character, got {transparent!r}")

    # Parse the caller's palette up front. It is only an output mapping, so a
    # bad key or colour can be rejected before paying for an Aseprite launch.
    char_to_rgba: Dict[str, tuple[int, int, int, int]] = {}
    rgba_to_char: Dict[tuple[int, int, int, int], str] = {}
    if palette:
        for char, value in palette.items():
            if not isinstance(char, str) or len(char) != 1:
                raise ToolError(f"Invalid palette key {char!r}: keys must be single characters")
            if char == transparent:
                raise ToolError(f"Invalid palette: must not contain the transparent "
                    f"character {transparent!r}")
            rgba = parse_hex_color(value)
            if rgba is None:
                raise ToolError(f"Invalid colour for palette[{char!r}]: {value!r}")
            # Two characters for one colour would make the inverse
            # ambiguous; the lowest character wins deterministically.
            if rgba in rgba_to_char:
                continue
            rgba_to_char[rgba] = char
            char_to_rgba[char] = rgba

    safe_layer = lua_escape(layer_name)

    if composite:
        # Visible layers only — see _COMPOSE_FRAME for why flattening a
        # clone beats Sprite:flatten() directly.
        reader = f"""
        {_COMPOSE_FRAME}
        local img = compose_frame(spr, idx, nil)
        local ox, oy = 0, 0
        """
    else:
        reader = f"""
        if spr.colorMode ~= ColorMode.RGB then print("ERROR:Sprite maps require RGB mode. Tip: use set_color_mode(mode='rgb') first.") return end
        local cel = nil
        {FIND_LAYER}
        {LAYER_NAMES}
        local target = find_layer(spr, "{safe_layer}")
        if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
        if target.isTilemap then print("ERROR:Layer '{safe_layer}' {_TILEMAP_REFUSAL}. Tip: use get_composite_rect for the rendered colour.") return end
        cel = target:cel(spr.frames[idx])
        if not cel then print("ERROR:No cel on layer '{safe_layer}' at frame {frame_index} (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first, or draw on this layer/frame.") return end
        local img = cel.image
        local ox = cel.position.x
        local oy = cel.position.y
        """

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index {frame_index} out of range (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first.") return end
    {reader}

    local iw, ih = img.width, img.height
    for py = {y}, {y + height - 1} do
        for px = {x}, {x + width - 1} do
            local cx = px - ox
            local cy = py - oy
            local r, g, b, a = 0, 0, 0, 0
            if cx >= 0 and cy >= 0 and cx < iw and cy < ih then
                local pv = img:getPixel(cx, cy)
                r = app.pixelColor.rgbaR(pv)
                g = app.pixelColor.rgbaG(pv)
                b = app.pixelColor.rgbaB(pv)
                a = app.pixelColor.rgbaA(pv)
            end
            print(string.format("PIXEL:%d,%d,%d,%d,%d,%d", px, py, r, g, b, a))
        end
    end
    """

    output = await AsepriteCommand.execute_lua_script(script, filename)

    cells: Dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for line in output.splitlines():
        if line.startswith("ERROR:"):
            raise ToolError(f"Failed to read sprite map: {line[6:]}")
        if line.startswith("PIXEL:"):
            px, py, r, g, b, a = (int(value) for value in line[6:].split(","))
            cells[(px - x, py - y)] = (r, g, b, a)

    if len(cells) != width * height:
        raise ToolError("Failed to read sprite map: incomplete pixel data returned")

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
        "layer": layer_name or "(active)",
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

    return json.dumps(result, ensure_ascii=False)
