"""Read native sprite metadata through the Aseprite adapter."""

import json
from mcp.server.mcpserver.exceptions import ToolError
from .commands import AsepriteCommand
from .lua import FIND_LAYER
from .results import SpriteInfo


async def read_sprite_info(filename: str) -> SpriteInfo:
    script = FIND_LAYER + r'''
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    local modes = {[ColorMode.RGB]="rgb", [ColorMode.INDEXED]="indexed", [ColorMode.GRAY]="gray"}
    local info = {width=spr.width, height=spr.height, color_mode=modes[spr.colorMode] or "unknown",
                  frames=#spr.frames, durations_ms={}, layers={}, tags={}}
    for _, frame in ipairs(spr.frames) do
        table.insert(info.durations_ms, math.floor(frame.duration * 1000 + 0.5))
    end
    local function walk(layers, parent)
        for _, layer in ipairs(layers) do
            local entry = {name=layer.name, visible=layer.isVisible, opacity=layer.opacity or 255,
                           is_group=layer.isGroup, path=layer_path(layer),
                           type=layer.isGroup and "group" or (layer.isTilemap and "tilemap" or "image")}
            entry.parent = parent
            table.insert(info.layers, entry)
            if layer.isGroup then walk(layer.layers, layer.name) end
        end
    end
    walk(spr.layers, nil)
    local dirs = {[0]="forward", "reverse", "pingpong", "pingpong_reverse"}
    for _, tag in ipairs(spr.tags) do
        table.insert(info.tags, {name=tag.name, ["from"]=tag.fromFrame.frameNumber,
                                to=tag.toFrame.frameNumber, direction=dirs[tonumber(tag.aniDir)] or tostring(tag.aniDir)})
    end
    print(json.encode(info))
    '''
    output = await AsepriteCommand.execute_lua_script_checked(script, filename)
    try:
        info = json.loads(output)
        for layer in info["layers"]:
            layer.setdefault("parent", None)
        return info
    except (ValueError, TypeError, KeyError) as exc:
        raise ToolError("Aseprite returned invalid sprite metadata") from exc
