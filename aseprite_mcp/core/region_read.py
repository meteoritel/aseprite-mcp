"""Read a rectangle of raw RGBA from an Aseprite image."""

from collections.abc import Iterable

from mcp.server.mcpserver.exceptions import ToolError

from .contracts import Region
from .lua import FIND_LAYER, LAYER_NAMES


EMIT_REGION_PIXELS = """
local function emit_region_pixels(img, origin, region, prefix)
    local rgba = app.pixelColor
    for y = region.y, region.y + region.height - 1 do
        local row = {}
        local cy = y - origin.y
        for x = region.x, region.x + region.width - 1 do
            local cx = x - origin.x
            local value = 0
            if cx >= 0 and cy >= 0 and cx < img.width and cy < img.height then
                value = img:getPixel(cx, cy)
            end
            row[#row + 1] = string.format("%02x%02x%02x%02x",
                rgba.rgbaR(value), rgba.rgbaG(value), rgba.rgbaB(value), rgba.rgbaA(value))
        end
        print((prefix or "RGBA:") .. table.concat(row))
    end
end
"""

FIND_REGION_CEL = FIND_LAYER + LAYER_NAMES + """
local function find_region_cel(spr, ref, frame)
    if spr.colorMode ~= ColorMode.RGB then
        error("Sprite maps require RGB mode. Tip: use set_color_mode(mode='rgb') first.")
    end
    local target = find_layer(spr, ref)
    local name = layer_ref_text(ref)
    if not target then
        error("Layer '" .. name .. "' not found. Existing layers: [" .. layer_names(spr)
            .. "]. Tip: call add_layer first or check get_sprite_info.")
    end
    if target.isGroup then error("Layer '" .. name .. "' is a group; select a leaf layer") end
    if target.isTilemap then
        error("Layer '" .. name .. "' is a tilemap layer: its cel stores tile indexes, not pixels."
            .. " Tip: use get_composite_rect for the rendered colour.")
    end
    return layer_path(target), target:cel(frame)
end
"""


def lua_region(region: Region) -> str:
    return f"{{x={region.x},y={region.y},width={region.width},height={region.height}}}"


def read_region_rgba(hex_rows: Iterable[str], region: Region) -> bytes:
    try:
        rows = [bytes.fromhex(row) for row in hex_rows]
    except ValueError as exc:
        raise ToolError("Failed to read sprite map: invalid RGBA data returned") from exc
    if len(rows) != region.height or any(len(row) != region.width * 4 for row in rows):
        raise ToolError("Failed to read sprite map: incomplete pixel data returned")
    return b"".join(rows)


def region_pixels(rgba: bytes, width: int):
    return {
        (pixel % width, pixel // width): tuple(rgba[start:start + 4])
        for pixel, start in enumerate(range(0, len(rgba), 4))
    }


def read_region_pixels(output: str, region: Region):
    rows = (line.removeprefix("RGBA:") for line in output.splitlines() if line.startswith("RGBA:"))
    return region_pixels(read_region_rgba(rows, region), region.width)
