from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import lua_escape
from ..core.contracts import LayerRef, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.lua import FIND_LAYER, lua_layer_refs
from ..core.results import EditReceipt
from ..core.state import prepare_filename

async def copy_layers_between_sprites(
    *,
    source_filename: str = "",
    target_filename: str,
    layer_names: list[LayerRef],
    replace: bool = True,
    create_missing_frames: bool = True
) -> ToolOutput[EditReceipt]:
    """Copy layers by name from a source sprite to a target sprite.

    Args:
        source_filename: Source .aseprite file (optional; defaults to the session's active file)
        target_filename: Target .aseprite file (must already exist)
        layer_names: Source leaf image layers, by legacy name or exact path array. Exact destination parents must already exist.
        replace: Overwrite existing cels in target layers
        create_missing_frames: Add frames to target if needed
    """
    source_filename = prepare_filename(source_filename)
    target_filename = prepare_filename(target_filename, anchor=False)
    if not layer_names:
        raise ToolError("Layer names list cannot be empty")

    src_path = lua_escape(source_filename.replace("\\", "/"))
    dst_path = lua_escape(target_filename.replace("\\", "/"))
    replace_flag = "true" if replace else "false"
    create_frames_flag = "true" if create_missing_frames else "false"
    layers_lua = lua_layer_refs(layer_names)

    script = f"""
    local src = app.open("{src_path}")
    if not src then print("ERROR:Source sprite not opened") return end
    local dst = app.open("{dst_path}")
    if not dst then print("ERROR:Target sprite not opened") return end

    {FIND_LAYER}

    local names = {layers_lua}
    local missing = {{}}
    local valid = {{}}
    for _, name in ipairs(names) do
        local source = find_layer(src, name)
        if source then
            if source.isGroup or source.isTilemap then error("Copy requires leaf image layers: " .. layer_ref_text(name)) end
            local target = find_layer(dst, name)
            local parent = nil
            local new_name = source.name
            if not target and type(name) ~= "string" and #name > 1 then
                local parent_path = {{}}
                for index = 1, #name-1 do parent_path[index] = name[index] end
                parent = find_layer(dst, parent_path)
                if not parent or not parent.isGroup then error("Destination group not found: " .. layer_ref_text(parent_path)) end
            elseif not target and type(name) == "string" then
                new_name = name
            end
            if target and (target.isGroup or target.isTilemap) then error("Destination must be an image layer: " .. layer_ref_text(name)) end
            table.insert(valid, {{source=source, target=target, parent=parent, name=new_name, ref=name}})
        else
            table.insert(missing, layer_ref_text(name))
        end
    end
    if #valid == 0 then
        print("ERROR:None of the requested layers exist in the source: " .. table.concat(missing, ", ")) return
    end

    app.transaction(function()
        if {create_frames_flag} then
            while #dst.frames < #src.frames do
                dst:newFrame()
            end
        end

        _aseprite_edit_targets = {{}}
        for _, entry in ipairs(valid) do
            local src_layer = entry.source
            local dst_layer = entry.target or find_layer(dst, entry.ref)
            if not dst_layer then
                dst_layer = dst:newLayer()
                dst_layer.name = entry.name
                if entry.parent then dst_layer.parent = entry.parent end
            end
            remember_target(dst_layer)
            if {replace_flag} then
                for i = 1, #dst.frames do
                    local cel = dst_layer:cel(dst.frames[i])
                    if cel then dst:deleteCel(cel) end
                end
            end
            for i = 1, #src.frames do
                if i <= #dst.frames then
                    local src_cel = src_layer:cel(src.frames[i])
                    if src_cel then
                        local dst_cel = dst_layer:cel(dst.frames[i])
                        if dst_cel and {replace_flag} then
                            dst:deleteCel(dst_cel)
                            dst_cel = nil
                        end
                        if not dst_cel then
                            local img = src_cel.image:clone()
                            dst:newCel(dst_layer, dst.frames[i], img, src_cel.position)
                        end
                    end
                end
            end
        end
    end)

    save_project(dst)
    if #missing > 0 then
        print("MISSING:" .. table.concat(missing, ", "))
    end
    print("OK")
    """

    execution = await execute_edit_script(script, source_filename, output_filename=target_filename)
    output = execution.stdout
    missing = next(
        (line[len("MISSING:"):] for line in output.splitlines() if line.startswith("MISSING:")),
        None,
    )
    msg = f"Layers copied from {source_filename} to {target_filename}"
    if missing:
        msg += f" (skipped missing layers: {missing})"
    return edit_output(msg, target_filename, execution, None)
