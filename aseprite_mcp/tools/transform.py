from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import lua_escape
from ..core.contracts import FrameIndex, LayerRef, PositiveInt, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.lua import FIND_LAYER, LAYER_NAMES, lua_layer_ref
from ..core.results import EditReceipt
from ..core.state import prepare_filename


async def flip_layer(filename: str='', *, layer_name: LayerRef, frame_index: FrameIndex, direction: Literal['horizontal', 'vertical']='horizontal') -> ToolOutput[EditReceipt]:
    """Flip a layer's image horizontally or vertically.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to flip
        frame_index: Frame index starting at 1
        direction: "horizontal" or "vertical"
    """
    filename = prepare_filename(filename)
    if direction not in ("horizontal", "vertical"):
        raise ToolError("direction must be 'horizontal' or 'vertical'")

    safe_layer = lua_escape(layer_name)
    flip_h = "true" if direction == "horizontal" else "false"

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end

    local cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel at that layer/frame") return end

    app.transaction(function()
        local img = cel.image
        local w = img.width
        local h = img.height
        local flip_horizontal = {flip_h}

        local pixels = {{}}
        for py = 0, h - 1 do
            pixels[py] = {{}}
            for px = 0, w - 1 do
                pixels[py][px] = img:getPixel(px, py)
            end
        end

        for py = 0, h - 1 do
            for px = 0, w - 1 do
                if flip_horizontal then
                    img:putPixel(px, py, pixels[py][w - 1 - px])
                else
                    img:putPixel(px, py, pixels[h - 1 - py][px])
                end
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' flipped {direction}ly in {filename}", filename, execution, frame_index)


async def rotate_layer(filename: str='', *, layer_name: LayerRef, frame_index: FrameIndex, angle: Literal[90, 180, 270]=90) -> ToolOutput[EditReceipt]:
    """Rotate a layer's image 90, 180, or 270 degrees clockwise.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to rotate
        frame_index: Frame index starting at 1
        angle: Rotation angle: 90, 180, or 270 (clockwise)
    """
    filename = prepare_filename(filename)
    if angle not in (90, 180, 270):
        raise ToolError("angle must be 90, 180, or 270")

    safe_layer = lua_escape(layer_name)

    if angle == 180:
        rotate_lua = """
        local w = img.width
        local h = img.height
        local pixels = {}
        for py = 0, h - 1 do
            pixels[py] = {}
            for px = 0, w - 1 do
                pixels[py][px] = img:getPixel(px, py)
            end
        end
        for py = 0, h - 1 do
            for px = 0, w - 1 do
                img:putPixel(px, py, pixels[h - 1 - py][w - 1 - px])
            end
        end
        """
    elif angle == 90:
        # 90° clockwise: (px, py) → (old_h-1-py, px) in new image (new_w=old_h, new_h=old_w)
        rotate_lua = """
        local old_w = img.width
        local old_h = img.height
        local new_img = Image(old_h, old_w, img.colorMode)
        for py = 0, old_h - 1 do
            for px = 0, old_w - 1 do
                new_img:putPixel(old_h - 1 - py, px, img:getPixel(px, py))
            end
        end
        cel.image = new_img
        """
    else:
        # 270° clockwise (= 90° CCW): (px, py) → (py, old_w-1-px) in new image (new_w=old_h, new_h=old_w)
        rotate_lua = """
        local old_w = img.width
        local old_h = img.height
        local new_img = Image(old_h, old_w, img.colorMode)
        for py = 0, old_h - 1 do
            for px = 0, old_w - 1 do
                new_img:putPixel(py, old_w - 1 - px, img:getPixel(px, py))
            end
        end
        cel.image = new_img
        """

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end

    local cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel at that layer/frame") return end

    app.transaction(function()
        local img = cel.image
        {rotate_lua}
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' rotated {angle}° clockwise in {filename}"
, filename, execution, frame_index)

async def resize_canvas(filename: str = "", *, width: PositiveInt, height: PositiveInt) -> ToolOutput[EditReceipt]:
    """Scale the canvas and all its content to new dimensions.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        width: New canvas width in pixels
        height: New canvas height in pixels
    """
    filename = prepare_filename(filename)
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        spr:resize({width}, {height})
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Canvas resized to {width}x{height} in {filename}", filename, execution, None)


async def crop_canvas(filename: str = "", *, x: int, y: int, width: PositiveInt, height: PositiveInt) -> ToolOutput[EditReceipt]:
    """Crop the canvas to the given rectangle, discarding content outside it.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        x: Left edge of the crop area
        y: Top edge of the crop area
        width: Width of the crop area
        height: Height of the crop area
    """
    filename = prepare_filename(filename)
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    if {x} >= spr.width or {y} >= spr.height or {x} + {width} <= 0 or {y} + {height} <= 0 then
        print("ERROR:Crop rect is fully outside the canvas") return
    end

    app.transaction(function()
        spr:crop({x}, {y}, {width}, {height})
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Canvas cropped to ({x},{y}) {width}x{height} in {filename}", filename, execution, None)
