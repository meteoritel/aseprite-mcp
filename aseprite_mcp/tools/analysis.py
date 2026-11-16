from mcp.server.mcpserver.exceptions import ToolError
import json
import os
from ..core.commands import AsepriteCommand, lua_escape
from ..core.state import prepare_filename
from .. import mcp

# Composite the *visible* layers of one frame into a canvas-sized RGB
# image. Used by the analysis tools so layer offsets and trimmed cels do
# not skew results.
#
# Sprite:flatten() (Aseprite 1.3.x) merges hidden layers too, so a flattened
# clone reports colours the player never sees. Rather than re-implementing the
# renderer — blend modes, group opacity and tilemap rasterisation are all easy
# to get subtly wrong — drop every invisible layer from a throwaway clone and
# only then flatten. The merge stays Aseprite's own code, so the result agrees
# with export_frame pixel for pixel (tests/test_visibility.py asserts that).
_COMPOSE_FRAME = """
local function visible_clone(spr)
    local clone = Sprite(spr)

    -- flatten() needs a layer to produce, and this also keeps the sprite from
    -- reaching zero layers while the hidden ones are being deleted.
    local keep = clone:newLayer()
    keep.name = "__visible_only__"

    local doomed = {}
    local function scan(layers)
        for _, layer in ipairs(layers) do
            if not layer.isVisible then
                doomed[#doomed + 1] = layer
            elseif layer.isGroup then
                -- A hidden group takes its children with it, so do not descend
                -- into it: they would be collected twice and the second delete
                -- would fail.
                scan(layer.layers)
            end
        end
    end
    scan(clone.layers)
    for _, layer in ipairs(doomed) do clone:deleteLayer(layer) end

    clone:flatten()
    return clone
end

local function compose_frame(spr, frame_idx, bg)
    local clone = visible_clone(spr)
    local img = Image(spr.width, spr.height, ColorMode.RGB)
    if bg then
        for py = 0, img.height - 1 do
            for px = 0, img.width - 1 do
                img:putPixel(px, py, bg)
            end
        end
    end
    local layer = clone.layers[#clone.layers]
    local cel = layer:cel(clone.frames[frame_idx])
    if cel then
        img:drawImage(cel.image, cel.position)
    end
    return img
end
"""


@mcp.tool()
async def render_onion_skin(filename: str = "", *, frame_index: int, output_filename: str, before: int = 1, after: int = 1, scale: int = 4, ghost_opacity: int = 100) -> str:
    """Render a frame with neighboring frames as translucent onion-skin ghosts.

    Produces a PNG of the given frame composited over ghosted copies of
    the surrounding frames — the batch-mode equivalent of Aseprite's
    onion skinning. Essential for checking motion continuity while
    animating: export it, open the PNG, and verify the in-between
    positions line up.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        frame_index: Frame to render, starting at 1
        output_filename: Output PNG path
        before: Number of previous frames to ghost (default 1)
        after: Number of following frames to ghost (default 1)
        scale: Integer nearest-neighbor scale factor (default 4)
        ghost_opacity: Opacity of ghost frames, 0-255 (default 100)
    """
    filename = prepare_filename(filename)
    if not output_filename:
        raise ToolError("output_filename is required")
    output_filename = prepare_filename(output_filename, must_exist=False, anchor=False)
    if scale < 1 or scale > 64:
        raise ToolError("scale must be between 1 and 64")
    if not (0 <= ghost_opacity <= 255):
        raise ToolError("ghost_opacity must be between 0 and 255")
    if before < 0 or after < 0:
        raise ToolError("before and after must be >= 0")
    if not output_filename.lower().endswith(".png"):
        output_filename = f"{output_filename}.png"

    safe_out = lua_escape(os.path.abspath(output_filename).replace("\\", "/"))
    script = f"""
    {_COMPOSE_FRAME}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    local white = app.pixelColor.rgba(255, 255, 255, 255)
    local comp = Image(spr.width, spr.height, ColorMode.RGB)
    for py = 0, comp.height - 1 do
        for px = 0, comp.width - 1 do
            comp:putPixel(px, py, white)
        end
    end

    -- Ghosts: oldest first so closer frames draw on top
    for offset = {before}, 1, -1 do
        local fi = idx - offset
        if fi >= 1 then
            comp:drawImage(compose_frame(spr, fi, nil), Point(0, 0), {ghost_opacity}, BlendMode.NORMAL)
        end
    end
    for offset = {after}, 1, -1 do
        local fi = idx + offset
        if fi <= #spr.frames then
            comp:drawImage(compose_frame(spr, fi, nil), Point(0, 0), {ghost_opacity}, BlendMode.NORMAL)
        end
    end
    comp:drawImage(compose_frame(spr, idx, nil), Point(0, 0), 255, BlendMode.NORMAL)

    local s = {scale}
    local big = Image(comp.width * s, comp.height * s, ColorMode.RGB)
    for py = 0, comp.height - 1 do
        for px = 0, comp.width - 1 do
            local v = comp:getPixel(px, py)
            for oy = 0, s - 1 do
                for ox = 0, s - 1 do
                    big:putPixel(px * s + ox, py * s + oy, v)
                end
            end
        end
    end

    big:saveAs("{safe_out}")
    print("OK")
    """

    await AsepriteCommand.execute_lua_script_checked(script, filename)
    return (
        f"Onion-skin render of frame {frame_index} "
        f"(-{before}/+{after} ghosts) saved to {output_filename} at {scale}x"
    )


@mcp.tool()
async def compare_frames(filename: str = "", *, frame_a: int, frame_b: int) -> str:
    """Compare two frames and report how much they differ.

    Composites the *visible* layers (non-destructively) and diffs the two
    frames pixel by pixel. Use while animating to confirm a frame actually
    changed, or that it did not change too much. Hidden layers do not
    count as a change.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        frame_a: First frame index, starting at 1
        frame_b: Second frame index, starting at 1

    Returns:
        JSON with changed pixel count, total pixels, percent changed,
        and the bounding box of the changed region.
    """
    filename = prepare_filename(filename)

    script = f"""
    {_COMPOSE_FRAME}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local a = {frame_a}
    local b = {frame_b}
    if a < 1 or a > #spr.frames or b < 1 or b > #spr.frames then
        print("ERROR:Frame index out of range") return
    end

    local img_a = compose_frame(spr, a, nil)
    local img_b = compose_frame(spr, b, nil)

    local changed = 0
    local min_x, min_y = math.huge, math.huge
    local max_x, max_y = -1, -1
    for py = 0, img_a.height - 1 do
        for px = 0, img_a.width - 1 do
            local va = img_a:getPixel(px, py)
            local vb = img_b:getPixel(px, py)
            local aa = app.pixelColor.rgbaA(va)
            local ab = app.pixelColor.rgbaA(vb)
            local diff
            if aa == 0 and ab == 0 then
                diff = false
            else
                diff = va ~= vb
            end
            if diff then
                changed = changed + 1
                if px < min_x then min_x = px end
                if py < min_y then min_y = py end
                if px > max_x then max_x = px end
                if py > max_y then max_y = py end
            end
        end
    end

    if changed == 0 then
        -- math.huge has no integer representation for %d
        min_x, min_y, max_x, max_y = 0, 0, -1, -1
    end
    print(string.format("DIFF:%d,%d,%d,%d,%d,%d,%d",
        changed, img_a.width * img_a.height, min_x, min_y, max_x, max_y,
        (changed > 0) and 1 or 0))
    """

    output = await AsepriteCommand.execute_lua_script_checked(script, filename)

    for line in output.splitlines():
        if line.startswith("DIFF:"):
            parts = [int(p) for p in line[len("DIFF:"):].split(",")]
            changed, total, min_x, min_y, max_x, max_y, any_change = parts
            result = {
                "frame_a": frame_a,
                "frame_b": frame_b,
                "changed_pixels": changed,
                "total_pixels": total,
                "percent_changed": round(changed / total * 100, 2) if total else 0,
            }
            if any_change:
                result["changed_bounds"] = {
                    "x": min_x,
                    "y": min_y,
                    "width": max_x - min_x + 1,
                    "height": max_y - min_y + 1,
                }
            return json.dumps(result)
    raise ToolError("No diff data returned")


@mcp.tool()
async def get_color_stats(filename: str = "", frame_index: int = 1, top: int = 16) -> str:
    """Report the colors used in a frame and how often each appears.

    Composites the *visible* layers (non-destructively) and histograms the
    frame — hidden layers are excluded, so the counts match what a player
    sees. Use to check palette discipline: too many near-duplicate colors
    is a common pixel-art mistake.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        frame_index: Frame to analyze, starting at 1 (default 1)
        top: How many of the most-used colors to list (default 16)

    Returns:
        JSON with unique color count, opaque pixel count, and the top
        colors with usage counts.
    """
    filename = prepare_filename(filename)
    if top < 1:
        raise ToolError("top must be >= 1")

    script = f"""
    {_COMPOSE_FRAME}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    local img = compose_frame(spr, idx, nil)

    local counts = {{}}
    local opaque = 0
    for py = 0, img.height - 1 do
        for px = 0, img.width - 1 do
            local v = img:getPixel(px, py)
            if app.pixelColor.rgbaA(v) > 0 then
                opaque = opaque + 1
                local hex = string.format("#%02X%02X%02X",
                    app.pixelColor.rgbaR(v),
                    app.pixelColor.rgbaG(v),
                    app.pixelColor.rgbaB(v))
                counts[hex] = (counts[hex] or 0) + 1
            end
        end
    end

    local unique = 0
    for hex, count in pairs(counts) do
        unique = unique + 1
        print("COLOR:" .. hex .. "," .. count)
    end
    print("OPAQUE:" .. opaque)
    print("UNIQUE:" .. unique)
    """

    output = await AsepriteCommand.execute_lua_script_checked(script, filename)

    colors = []
    opaque = 0
    unique = 0
    for line in output.splitlines():
        if line.startswith("COLOR:"):
            hex_color, count = line[len("COLOR:"):].split(",")
            colors.append({"color": hex_color, "count": int(count)})
        elif line.startswith("OPAQUE:"):
            opaque = int(line[len("OPAQUE:"):])
        elif line.startswith("UNIQUE:"):
            unique = int(line[len("UNIQUE:"):])

    colors.sort(key=lambda c: c["count"], reverse=True)
    return json.dumps({
        "frame": frame_index,
        "unique_colors": unique,
        "opaque_pixels": opaque,
        "top_colors": colors[:top],
    })
