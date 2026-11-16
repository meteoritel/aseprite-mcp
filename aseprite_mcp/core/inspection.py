"""Read native sprite metadata through the Aseprite adapter."""

import json
from mcp.server.mcpserver.exceptions import ToolError
from .commands import AsepriteCommand


async def read_sprite_info(filename: str) -> dict:
    # NOTE: batch mode discards Lua `return` values — output MUST go through print().
    script = """
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local cm = "unknown"
    if spr.colorMode == ColorMode.RGB then cm = "rgb"
    elseif spr.colorMode == ColorMode.INDEXED then cm = "indexed"
    elseif spr.colorMode == ColorMode.GRAY then cm = "gray" end

    local parts = {}
    table.insert(parts, "{")
    table.insert(parts, "\\"width\\":" .. spr.width .. ",")
    table.insert(parts, "\\"height\\":" .. spr.height .. ",")
    table.insert(parts, "\\"color_mode\\":\\"" .. cm .. "\\",")
    table.insert(parts, "\\"frames\\":" .. #spr.frames .. ",")
    table.insert(parts, "\\"durations_ms\\":[")
    for i, frame in ipairs(spr.frames) do
        table.insert(parts, tostring(math.floor(frame.duration * 1000 + 0.5)))
        if i < #spr.frames then table.insert(parts, ",") end
    end
    table.insert(parts, "],")
    table.insert(parts, "\\"layers\\":[")
    -- Recurse into groups so nested layers are enumerated too; each entry
    -- carries its immediate parent group name (null at top level).
    local first_layer = true
    local function walk_layers(layers, parent)
        for _, layer in ipairs(layers) do
            if not first_layer then table.insert(parts, ",") end
            first_layer = false
            local pj = "null"
            if parent then pj = string.format("%q", parent) end
            local entry = "{\\"name\\":" .. string.format("%q", layer.name) .. ",\\"visible\\":" .. tostring(layer.isVisible) .. ",\\"opacity\\":" .. (layer.opacity or 255) .. ",\\"is_group\\":" .. tostring(layer.isGroup) .. ",\\"parent\\":" .. pj .. "}"
            table.insert(parts, entry)
            if layer.isGroup then walk_layers(layer.layers, layer.name) end
        end
    end
    walk_layers(spr.layers, nil)
    table.insert(parts, "],")
    local dirs = {[0]="forward", "reverse", "pingpong", "pingpong_reverse"}
    table.insert(parts, "\\"tags\\":[")
    for i, t in ipairs(spr.tags) do
        local entry = "{\\"name\\":" .. string.format("%q", t.name) .. ",\\"from\\":" .. t.fromFrame.frameNumber .. ",\\"to\\":" .. t.toFrame.frameNumber .. ",\\"direction\\":\\"" .. (dirs[tonumber(t.aniDir)] or tostring(t.aniDir)) .. "\\"}"
        table.insert(parts, entry)
        if i < #spr.tags then table.insert(parts, ",") end
    end
    table.insert(parts, "]}")
    print(table.concat(parts))
    """

    output = await AsepriteCommand.execute_lua_script_checked(script, filename)
    try:
        return json.loads(output)
    except (ValueError, TypeError) as exc:
        raise ToolError("Aseprite returned invalid sprite metadata") from exc
