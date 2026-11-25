import colorsys
import json
from typing import List

from mcp.server.mcpserver.exceptions import ToolError

from ..core.colors import parse_hex_color
from ..core.commands import AsepriteCommand, lua_escape
from ..core.contracts import ColorMapping, FrameIndex, LayerRef, NonnegativeInt, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.lua import FIND_LAYER, LAYER_NAMES, lua_layer_ref
from ..core.results import EditReceipt
from ..core.state import prepare_filename

# Well-known retro/pixel-art palettes.
PALETTE_PRESETS = {
    "gameboy": ["#0F380F", "#306230", "#8BAC0F", "#9BBC0F"],
    "monochrome": ["#000000", "#FFFFFF"],
    "grayscale_4": ["#000000", "#555555", "#AAAAAA", "#FFFFFF"],
    "cga": ["#000000", "#55FFFF", "#FF55FF", "#FFFFFF"],
    "pico8": [
        "#000000", "#1D2B53", "#7E2553", "#008751",
        "#AB5236", "#5F574F", "#C2C3C7", "#FFF1E8",
        "#FF004D", "#FFA300", "#FFEC27", "#00E436",
        "#29ADFF", "#83769C", "#FF77A8", "#FFCCAA",
    ],
    "c64": [
        "#000000", "#FFFFFF", "#880000", "#AAFFEE",
        "#CC44CC", "#00CC55", "#0000AA", "#EEEE77",
        "#DD8855", "#664400", "#FF7777", "#333333",
        "#777777", "#AAFF66", "#0088FF", "#BBBBBB",
    ],
    "dawnbringer16": [
        "#140C1C", "#442434", "#30346D", "#4E4A4E",
        "#854C30", "#346524", "#D04648", "#757161",
        "#597DCE", "#D27D2C", "#8595A1", "#6DAA2C",
        "#D2AA99", "#6DC2CA", "#DAD45E", "#DEEED6",
    ],
    "dawnbringer32": [
        "#000000", "#222034", "#45283C", "#663931",
        "#8F563B", "#DF7126", "#D9A066", "#EEC39A",
        "#FBF236", "#99E550", "#6ABE30", "#37946E",
        "#4B692F", "#524B24", "#323C39", "#3F3F74",
        "#306082", "#5B6EE1", "#639BFF", "#5FCDE4",
        "#CBDBFC", "#FFFFFF", "#9BADB7", "#847E87",
        "#696A6A", "#595652", "#76428A", "#AC3232",
        "#D95763", "#D77BBA", "#8F974A", "#8A6F30",
    ],
}

def _parse_hex_color(value: str) -> tuple[int, int, int] | None:
    """RGB-only parse (alpha dropped); unified via core.colors.parse_hex_color."""
    rgba = parse_hex_color(value)
    return rgba[:3] if rgba else None

async def get_palette(filename: str = "") -> ToolOutput[list[str]]:
    """Read the sprite's stored palette in slot order as hex colors.

    For the colors actually used in a visible frame, call get_color_stats.

    Args:
        filename: Aseprite file to read (optional; defaults to the
            session's active file)
    """
    filename = prepare_filename(filename)

    script = """
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local ok, pal = pcall(function() return spr.palettes[1] end)
    if not ok or not pal then print("ERROR:No palette") return end

    local parts = {}
    local size = #pal
    table.insert(parts, "[")
    for i = 0, size - 1 do
        local c = pal:getColor(i)
        local hex = string.format("#%02X%02X%02X", c.red, c.green, c.blue)
        table.insert(parts, "\\"" .. hex .. "\\"")
        if i < size - 1 then
            table.insert(parts, ",")
        end
    end
    table.insert(parts, "]")
    print(table.concat(parts))
    """

    output = await AsepriteCommand.execute_lua_script_checked(script, filename)
    return ToolOutput(summary="Stored sprite palette. Use get_color_stats for colors in the visible frame.",
                      data=json.loads(output))

async def set_palette(filename: str = "", *, colors: List[str]) -> ToolOutput[EditReceipt]:
    """Set the active sprite palette using a list of hex colors.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        colors: List of #RRGGBB hex colors
    """
    filename = prepare_filename(filename)
    if not colors:
        raise ToolError("Colors list cannot be empty")

    rgb_list = []
    for color in colors:
        rgb = _parse_hex_color(color)
        if rgb is None:
            raise ToolError("Colors must use #RRGGBB values")
        rgb_list.append(rgb)

    palette_entries = "\n".join(
        [f"    pal:setColor({i}, Color({r}, {g}, {b}))" for i, (r, g, b) in enumerate(rgb_list)]
    )

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local pal = Palette({len(rgb_list)})
{palette_entries}
    spr:setPalette(pal)
    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Palette set with {len(colors)} colors in {filename}", filename, execution, None)

async def remap_colors_in_cel_range(filename: str = "", *, layer_name: LayerRef, start_frame: FrameIndex, end_frame: FrameIndex, mappings: list[ColorMapping], create_missing_cels: bool = False, source_frame_index: FrameIndex | None = None) -> ToolOutput[EditReceipt]:
    """Remap colors in a layer across a frame range using explicit mappings.

    Args:
        filename (str): The path to the Aseprite file (optional; defaults
            to the session's active file).
        layer_name (str): The name of the layer to remap colors in.
        start_frame (int): The start frame index to remap colors in.
        end_frame (int): The end frame index to remap colors in.
        mappings (List[dict]): The color mappings to use.
        create_missing_cels (bool, optional): Whether to create missing cels. Defaults to False.
        source_frame_index (int | None, optional): The source frame index to use for remapping. Defaults to None.
    """
    filename = prepare_filename(filename)
    if not mappings:
        raise ToolError("Mappings list cannot be empty")

    parsed = []
    for m in mappings:
        src = _parse_hex_color(m.get("from") or "")
        dst = _parse_hex_color(m.get("to") or "")
        if src is None or dst is None:
            raise ToolError("Mappings must use #RRGGBB colors")
        sr, sg, sb = src
        dr, dg, db = dst
        parsed.append((sr, sg, sb, dr, dg, db))

    mapping_lua = ", ".join(
        [f"{{{sr},{sg},{sb},{dr},{dg},{db}}}" for sr, sg, sb, dr, dg, db in parsed]
    )
    create_flag = "true" if create_missing_cels else "false"
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)
    safe_layer_name = lua_escape(layer_name)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end

    local source_frame = {source_idx}
    if source_frame == nil then
        source_frame = start_idx
    end
    if source_frame < 1 or source_frame > #spr.frames then
        print("ERROR:Source frame out of range") return
    end

    local map = {{ {mapping_lua} }}

    app.transaction(function()
        for fi = start_idx, end_idx do
            local frame = spr.frames[fi]
            local cel = target:cel(frame)
            if not cel and {create_flag} then
                local source_cel = target:cel(spr.frames[source_frame])
                if source_cel then
                    local img = source_cel.image:clone()
                    cel = spr:newCel(target, frame, img, source_cel.position)
                else
                    local img = Image(spr.width, spr.height, spr.colorMode)
                    cel = spr:newCel(target, frame, img, Point(0, 0))
                end
            end
            if cel then
                local img = cel.image
                for y = 0, img.height - 1 do
                    for x = 0, img.width - 1 do
                        local c = img:getPixel(x, y)
                        local r = app.pixelColor.rgbaR(c)
                        local g = app.pixelColor.rgbaG(c)
                        local b = app.pixelColor.rgbaB(c)
                        local a = app.pixelColor.rgbaA(c)
                        if a > 0 then
                            for _, m in ipairs(map) do
                                if r == m[1] and g == m[2] and b == m[3] then
                                    local nc = app.pixelColor.rgba(m[4], m[5], m[6], a)
                                    img:putPixel(x, y, nc)
                                    break
                                end
                            end
                        end
                    end
                end
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return (
        edit_output(f"Remapped colors on '{layer_name}' frames {start_frame}-{end_frame} in {filename}", filename, execution, None)
    )


async def list_palette_presets() -> ToolOutput[dict[str, list[str]]]:
    """List the built-in retro palette presets with their colors.

    Returns:
        JSON object mapping preset name to its list of hex colors.
    """
    return ToolOutput(summary='List palette presets completed', data=PALETTE_PRESETS)


async def apply_palette_preset(filename: str = "", *, preset: str) -> ToolOutput[EditReceipt]:
    """Set the sprite palette to a built-in retro preset.

    This only sets the palette; existing pixels keep their colors.
    Use quantize_to_palette afterwards to snap pixels to the new palette.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        preset: One of: gameboy, monochrome, grayscale_4, cga, pico8, c64,
            dawnbringer16, dawnbringer32
    """
    filename = prepare_filename(filename)

    colors = PALETTE_PRESETS.get(preset.lower())
    if colors is None:
        raise ToolError(f"Unknown preset '{preset}'. Available: {', '.join(sorted(PALETTE_PRESETS))}")
    await set_palette(filename, colors=colors)
    return edit_output(f"Palette preset '{preset}' ({len(colors)} colors) applied to {filename}", filename, None, None)


async def generate_color_ramp(
    base_color: str,
    steps: int = 5,
    hue_shift_degrees: float = 20,
    lightness_range: float = 0.5,
) -> ToolOutput[list[str]]:
    """Generate a shading ramp (dark to light) from a base color.

    Produces the standard pixel-art shading technique of hue-shifting:
    shadows lean cooler (hue shifted one way), highlights lean warmer.
    Use the returned colors for shading instead of plain darker/lighter
    versions of the same hue.

    Args:
        base_color: Hex color the ramp is built around, e.g. "#D04648"
        steps: Number of colors in the ramp, 2-16 (default 5)
        hue_shift_degrees: Total hue rotation across the ramp (default 20)
        lightness_range: Total lightness span across the ramp, 0-1 (default 0.5)

    Returns:
        JSON array of hex colors ordered darkest to lightest.
    """
    rgb = _parse_hex_color(base_color)
    if rgb is None:
        raise ToolError(f"Invalid color value: {base_color}")
    if not (2 <= steps <= 16):
        raise ToolError("steps must be between 2 and 16")
    if not (0 <= lightness_range <= 1):
        raise ToolError("lightness_range must be between 0 and 1")

    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)

    ramp = []
    mid = (steps - 1) / 2
    for i in range(steps):
        # t in [-0.5, 0.5]: negative = shadow side, positive = highlight side
        t = (i - mid) / (steps - 1) if steps > 1 else 0
        nh = (h - t * (hue_shift_degrees / 360)) % 1.0
        nl = min(1.0, max(0.0, l + t * lightness_range))
        # Shadows slightly more saturated, highlights slightly less
        ns = min(1.0, max(0.0, s - t * 0.15))
        nr, ng, nb = colorsys.hls_to_rgb(nh, nl, ns)
        ramp.append("#{:02X}{:02X}{:02X}".format(
            round(nr * 255), round(ng * 255), round(nb * 255)))
    return ToolOutput(summary='Generate color ramp completed', data=ramp)


async def quantize_to_palette(
    filename: str = "",
    layer_name: LayerRef = "",
    start_frame: FrameIndex = 1,
    end_frame: NonnegativeInt = 0,
) -> ToolOutput[EditReceipt]:
    """Snap every pixel to the nearest color in the sprite's palette.

    Walks the chosen cels and replaces each opaque pixel with the
    closest palette color (RGB distance). Run after apply_palette_preset
    or set_palette to make existing art conform to the palette.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Layer to quantize (empty = all top-level layers)
        start_frame: First frame to process (default 1)
        end_frame: Last frame to process (default 0 = last frame)
    """
    filename = prepare_filename(filename)

    safe_layer = lua_escape(layer_name)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local ok, pal = pcall(function() return spr.palettes[1] end)
    if not ok or not pal or #pal == 0 then print("ERROR:No palette") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if end_idx < 1 then end_idx = #spr.frames end
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local layers = {{}}
    if "{safe_layer}" ~= "" then
        local target = find_layer(spr, {lua_layer_ref(layer_name)})
        if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
        table.insert(layers, target)
    else
        for _, layer in ipairs(spr.layers) do
            if layer.isImage then table.insert(layers, layer) end
        end
    end

    local colors = {{}}
    for i = 0, #pal - 1 do
        local c = pal:getColor(i)
        table.insert(colors, {{c.red, c.green, c.blue}})
    end

    local cache = {{}}
    local function nearest(r, g, b)
        local key = r * 65536 + g * 256 + b
        local hit = cache[key]
        if hit then return hit end
        local best, best_d = colors[1], math.huge
        for _, c in ipairs(colors) do
            local dr, dg, db = r - c[1], g - c[2], b - c[3]
            local d = dr * dr + dg * dg + db * db
            if d < best_d then best, best_d = c, d end
        end
        cache[key] = best
        return best
    end

    local count = 0
    app.transaction(function()
        for _, layer in ipairs(layers) do
            for fi = start_idx, end_idx do
                local cel = layer:cel(spr.frames[fi])
                if cel then
                    local img = cel.image
                    for py = 0, img.height - 1 do
                        for px = 0, img.width - 1 do
                            local v = img:getPixel(px, py)
                            local a = app.pixelColor.rgbaA(v)
                            if a > 0 then
                                local r = app.pixelColor.rgbaR(v)
                                local g = app.pixelColor.rgbaG(v)
                                local b = app.pixelColor.rgbaB(v)
                                local c = nearest(r, g, b)
                                if c[1] ~= r or c[2] ~= g or c[3] ~= b then
                                    img:putPixel(px, py, app.pixelColor.rgba(c[1], c[2], c[3], a))
                                    count = count + 1
                                end
                            end
                        end
                    end
                end
            end
        end
    end)

    save_project(spr)
    print("COUNT:" .. count)
    """

    execution = await execute_edit_script(script, filename)
    output = execution.stdout

    count = "?"
    for line in output.splitlines():
        if line.startswith("COUNT:"):
            count = line[len("COUNT:"):]
    return edit_output(f"Quantized {count} pixels to the palette in {filename}", filename, execution, None)


async def set_color_mode(filename: str = "", *, mode: str) -> ToolOutput[EditReceipt]:
    """Convert the sprite's color mode.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        mode: "rgb", "grayscale", or "indexed"
    """
    filename = prepare_filename(filename)
    if mode.lower() not in ("rgb", "grayscale", "indexed"):
        raise ToolError("mode must be 'rgb', 'grayscale', or 'indexed'")

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.command.ChangePixelFormat {{ format = "{mode.lower()}" }}

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Color mode set to {mode} in {filename}", filename, execution, None)
