from mcp.server.mcpserver.exceptions import ToolError
import json
from ..core.commands import AsepriteCommand, lua_escape
from ..core.lua import FIND_LAYER, LAYER_NAMES
from ..core.state import prepare_filename
from .analysis import _COMPOSE_FRAME
from .. import mcp


@mcp.tool()
async def get_pixel_color(filename: str='', *, x: int, y: int, layer_name: str, frame_index: int) -> str:
    """Read the RGBA color of a single pixel from one layer's cel.

    This is a single-cel read: it ignores layer visibility and everything
    drawn above or below. For "what the player sees", use
    get_composite_pixel instead. Tilemap layers cannot be read this way —
    their cel stores tile indexes, so the call is refused with a hint.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        x: X coordinate (sprite-global)
        y: Y coordinate (sprite-global)
        layer_name: Explicit layer name or group path
        frame_index: Frame index starting at 1
    """
    filename = prepare_filename(filename)

    if not layer_name:
        raise ToolError("Invalid layer_name: specify an explicit layer")
    safe_layer = lua_escape(layer_name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    local cel = nil
    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer}")
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
    if target.isTilemap then print("ERROR:Layer '{safe_layer}' is a tilemap layer: its cel stores tile indexes, not pixels, so a per-pixel read would return an index in the red channel instead of a colour. Existing layers: [" .. layer_names(spr) .. "]. Tip: use get_tile_at for the tile index at a grid cell, or get_composite_pixel / get_composite_rect for the rendered colour.") return end
    cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel on layer '{safe_layer}' at frame {frame_index} (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first, or draw on this layer/frame.") return end

    local img = cel.image
    -- Coordinates are sprite-global; offset into cel-local space.
    local cx = {x} - cel.position.x
    local cy = {y} - cel.position.y
    local r, g, b, a = 0, 0, 0, 0
    if cx >= 0 and cy >= 0 and cx < img.width and cy < img.height then
        local px_val = img:getPixel(cx, cy)
        r = app.pixelColor.rgbaR(px_val)
        g = app.pixelColor.rgbaG(px_val)
        b = app.pixelColor.rgbaB(px_val)
        a = app.pixelColor.rgbaA(px_val)
    end
    print(string.format("PIXEL:%d,%d,%d,%d", r, g, b, a))
    """

    output = await AsepriteCommand.execute_lua_script(script, filename)

    for line in output.splitlines():
        if line.startswith("ERROR:"):
            raise ToolError(f"Failed to read pixel: {line[6:]}")
        if line.startswith("PIXEL:"):
            parts = line[6:].split(",")
            r, g, b, a = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            return f"#{r:02x}{g:02x}{b:02x} (r={r}, g={g}, b={b}, a={a})"

    raise ToolError("No pixel data returned")


@mcp.tool()
async def get_pixels_rect(filename: str='', *, x: int, y: int, width: int, height: int, layer_name: str, frame_index: int) -> str:
    """Read all pixel colors in a rectangular region from one layer's cel.

    Single-cel read: layer visibility is ignored and nothing above or below
    is composited in. For "what the player sees", use get_composite_rect.
    Tilemap layers are refused — their cel stores tile indexes, not pixels.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        x: Top-left x coordinate (sprite-global)
        y: Top-left y coordinate (sprite-global)
        width: Width of the region
        height: Height of the region
        layer_name: Explicit layer name or group path
        frame_index: Frame index starting at 1

    Returns:
        JSON array of {x, y, hex, r, g, b, a} objects
    """
    filename = prepare_filename(filename)
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")

    if not layer_name:
        raise ToolError("Invalid layer_name: specify an explicit layer")
    safe_layer = lua_escape(layer_name)
    x_end = x + width - 1
    y_end = y + height - 1

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    local cel = nil
    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer}")
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
    if target.isTilemap then print("ERROR:Layer '{safe_layer}' is a tilemap layer: its cel stores tile indexes, not pixels, so a per-pixel read would return an index in the red channel instead of a colour. Existing layers: [" .. layer_names(spr) .. "]. Tip: use get_tile_at for the tile index at a grid cell, or get_composite_pixel / get_composite_rect for the rendered colour.") return end
    cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel on layer '{safe_layer}' at frame {frame_index} (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first, or draw on this layer/frame.") return end

    local img = cel.image
    local ox = cel.position.x
    local oy = cel.position.y
    local iw = img.width
    local ih = img.height

    for py = {y}, {y_end} do
        for px = {x}, {x_end} do
            local cx = px - ox
            local cy = py - oy
            local r, g, b, a = 0, 0, 0, 0
            if cx >= 0 and cy >= 0 and cx < iw and cy < ih then
                local px_val = img:getPixel(cx, cy)
                r = app.pixelColor.rgbaR(px_val)
                g = app.pixelColor.rgbaG(px_val)
                b = app.pixelColor.rgbaB(px_val)
                a = app.pixelColor.rgbaA(px_val)
            end
            print(string.format("PIXEL:%d,%d,%d,%d,%d,%d", px, py, r, g, b, a))
        end
    end
    """

    output = await AsepriteCommand.execute_lua_script(script, filename)

    pixels = []
    for line in output.splitlines():
        if line.startswith("ERROR:"):
            raise ToolError(f"Failed to read pixels: {line[6:]}")
        if line.startswith("PIXEL:"):
            parts = line[6:].split(",")
            px, py, r, g, b, a = [int(p) for p in parts]
            pixels.append({
                "x": px, "y": py,
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "r": r, "g": g, "b": b, "a": a,
            })

    if len(pixels) != width * height:
        raise ToolError("Incomplete pixel data returned")
    return json.dumps(pixels)


@mcp.tool()
async def get_composite_pixel(filename: str = "", *, x: int, y: int, frame_index: int = 1) -> str:
    """Read the RGBA colour VISIBLE at a pixel (flattened composite of all layers).

    Unlike get_pixel_color (which reads a single cel), this composites every
    visible layer — "what the player actually sees" — by flattening a throwaway
    clone. Essential for value/CVD QA on grouped/multi-layer scenes.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        x: X coordinate (sprite-global)
        y: Y coordinate (sprite-global)
        frame_index: Frame index starting at 1
    """
    filename = prepare_filename(filename)

    script = f"""
    {_COMPOSE_FRAME}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end
    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end
    local img = compose_frame(spr, idx, nil)
    local r, g, b, a = 0, 0, 0, 0
    if {x} >= 0 and {y} >= 0 and {x} < img.width and {y} < img.height then
        local pv = img:getPixel({x}, {y})
        r = app.pixelColor.rgbaR(pv)
        g = app.pixelColor.rgbaG(pv)
        b = app.pixelColor.rgbaB(pv)
        a = app.pixelColor.rgbaA(pv)
    end
    print(string.format("PIXEL:%d,%d,%d,%d", r, g, b, a))
    """

    output = await AsepriteCommand.execute_lua_script(script, filename)
    for line in output.splitlines():
        if line.startswith("ERROR:"):
            raise ToolError(f"Failed to read composite pixel: {line[6:]}")
        if line.startswith("PIXEL:"):
            r, g, b, a = (int(p) for p in line[6:].split(","))
            return f"#{r:02x}{g:02x}{b:02x} (r={r}, g={g}, b={b}, a={a})"
    raise ToolError("No pixel data returned")


@mcp.tool()
async def get_composite_rect(filename: str = "", *, x: int, y: int, width: int, height: int, frame_index: int = 1) -> str:
    """Read VISIBLE RGBA over a rectangle (flattened composite of all layers).

    The rectangular counterpart of get_composite_pixel — reads the composited
    pixels every visible layer produces, not a single cel.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        x: Top-left x (sprite-global)
        y: Top-left y (sprite-global)
        width: Region width
        height: Region height
        frame_index: Frame index starting at 1

    Returns:
        JSON array of {x, y, hex, r, g, b, a} objects
    """
    filename = prepare_filename(filename)
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")

    x_end, y_end = x + width - 1, y + height - 1
    script = f"""
    {_COMPOSE_FRAME}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end
    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end
    local img = compose_frame(spr, idx, nil)
    local iw, ih = img.width, img.height
    for py = {y}, {y_end} do
        for px = {x}, {x_end} do
            local r, g, b, a = 0, 0, 0, 0
            if px >= 0 and py >= 0 and px < iw and py < ih then
                local pv = img:getPixel(px, py)
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
    pixels = []
    for line in output.splitlines():
        if line.startswith("ERROR:"):
            raise ToolError(f"Failed to read composite pixels: {line[6:]}")
        if line.startswith("PIXEL:"):
            px, py, r, g, b, a = (int(p) for p in line[6:].split(","))
            pixels.append({
                "x": px, "y": py,
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "r": r, "g": g, "b": b, "a": a,
            })
    if len(pixels) != width * height:
        raise ToolError("Incomplete pixel data returned")
    return json.dumps(pixels)
