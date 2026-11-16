"""Structural layer/cel checks and explicit animation repairs."""

import json
import re
from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..core.commands import AsepriteCommand, lua_escape
from ..core.contracts import ContractModel, FrameIndex, LayerRef, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.lua import FIND_LAYER, LAYER_NAMES, lua_layer_refs
from ..core.results import AnimationAudit, EditReceipt, SanitizeReport, SceneValidation
from ..core.state import prepare_filename


class LayerFrameRange(ContractModel):
    layer: LayerRef
    ranges: Annotated[list[tuple[FrameIndex, FrameIndex]], Field(min_length=1)]


class OverlapPair(ContractModel):
    a: LayerRef
    b: LayerRef


def _ranges(entries):
    result = []
    for entry in entries or []:
        if isinstance(entry, str):
            name, separator, spans = entry.rpartition(":")
            if not separator or not name.strip():
                raise ToolError(f"Invalid layer_frame_ranges entry {entry!r}; expected layer:1-8,17-24")
            parsed = []
            for span in spans.split(","):
                match = re.fullmatch(r"\s*([1-9][0-9]*)-([1-9][0-9]*)\s*", span)
                if not match or int(match[1]) > int(match[2]):
                    raise ToolError(f"Invalid frame span {span!r} in {entry!r}")
                parsed.append([int(match[1]), int(match[2])])
            entry = {"layer": name.strip(), "ranges": parsed}
        elif isinstance(entry, LayerFrameRange):
            entry = entry.model_dump()
        else:
            entry = LayerFrameRange.model_validate(entry).model_dump()
        if any(start > end for start, end in entry["ranges"]):
            raise ToolError("A layer frame range must end at or after its start")
        result.append(entry)
    return result


def _pairs(entries):
    result = []
    for entry in entries or []:
        if isinstance(entry, str):
            separator = "," if "," in entry else ":"
            names = entry.split(separator)
            if len(names) != 2 or any(not name.strip() for name in names):
                raise ToolError(f"Invalid overlap_pairs entry {entry!r}; expected layerA,layerB")
            entry = {"a": names[0].strip(), "b": names[1].strip()}
        elif isinstance(entry, OverlapPair):
            entry = entry.model_dump()
        else:
            entry = OverlapPair.model_validate(entry).model_dump()
        result.append(entry)
    return result


_QUALITY_TARGETS = FIND_LAYER + LAYER_NAMES + r'''
local spr = app.activeSprite
if not spr then error("No active sprite") end
local function quality_layer(ref)
    local layer = find_layer(spr, ref)
    if not layer then error("Requested layer " .. layer_ref_text(ref) .. " not found. Existing layers: [" .. layer_names(spr) .. "]") end
    if layer.isGroup then error("Select a leaf layer: " .. layer_ref_text(ref)) end
    return layer
end
local function select_layers(refs)
    local result, seen = {}, {}
    local function append(layer)
        if not seen[layer.id] then table.insert(result, layer); seen[layer.id] = true end
    end
    local function walk(layers)
        for _, layer in ipairs(layers) do
            if layer.isGroup then walk(layer.layers) else append(layer) end
        end
    end
    if refs == nil then walk(spr.layers)
    else for _, ref in ipairs(refs) do append(quality_layer(ref)) end end
    return result
end
'''


def _options_script(options):
    return _QUALITY_TARGETS + '\nlocal opts = json.decode("' + lua_escape(json.dumps(options, ensure_ascii=False)) + '")\n' + r'''
local first, last = opts.start_frame, opts.end_frame or #spr.frames
if first < 1 or last > #spr.frames or last < first then error("Frame range out of bounds (1-based)") end
local targets = select_layers(opts.layer_names)
local ranges, pairs = {}, {}
for _, entry in ipairs(opts.ranges) do
    local layer = quality_layer(entry.layer)
    if ranges[layer.id] then error("Repeated layer in layer_frame_ranges") end
    for _, span in ipairs(entry.ranges) do
        if span[2] > #spr.frames then error("Layer frame range exceeds sprite frames") end
    end
    ranges[layer.id] = entry.ranges
end
for _, pair in ipairs(opts.pairs) do
    table.insert(pairs, {quality_layer(pair.a), quality_layer(pair.b)})
end
local function in_ranges(layer, fi)
    if not ranges[layer.id] then return true end
    for _, span in ipairs(ranges[layer.id]) do
        if fi >= span[1] and fi <= span[2] then return true end
    end
    return false
end
local function bounds(cel)
    return {cel.position.x, cel.position.y, cel.image.width, cel.image.height}
end
local function overlaps_for_frame(fi, skip_full)
    local result = {}
    for _, pair in ipairs(pairs) do
        local a, b = pair[1]:cel(spr.frames[fi]), pair[2]:cel(spr.frames[fi])
        if a and b then
            local skip = skip_full and ((a.image.width == spr.width and a.image.height == spr.height)
                                    or (b.image.width == spr.width and b.image.height == spr.height))
            local ra, rb = bounds(a), bounds(b)
            if not skip and ra[1] < rb[1]+rb[3] and ra[1]+ra[3] > rb[1]
                        and ra[2] < rb[2]+rb[4] and ra[2]+ra[4] > rb[2] then
                local entry = {frame=fi, a=layer_path(pair[1]), b=layer_path(pair[2])}
                if opts.report_bounds then entry.a_bounds=ra; entry.b_bounds=rb end
                table.insert(result, entry)
            end
        end
    end
    return result
end
'''


async def ensure_layers_present(filename: str = "", *, layer_names: Annotated[list[LayerRef], Field(min_length=1)], start_frame: FrameIndex = 1, end_frame: FrameIndex | None = None) -> ToolOutput[EditReceipt]:
    """Create missing cels on existing image layers; every requested layer must resolve.

    Args:
        filename: Project, defaulting to the active file.
        layer_names: Existing leaf image layer names or exact path arrays. No layers are created.
        start_frame: First frame, 1-based.
        end_frame: Last frame, inclusive; omitted means the final frame.
    """
    filename = prepare_filename(filename)
    if not layer_names:
        raise ToolError("Layer names list cannot be empty")
    script = _QUALITY_TARGETS + f'''
    local first, last = {start_frame}, {end_frame if end_frame is not None else '#spr.frames'}
    if first < 1 or last > #spr.frames or first > last then error("Frame range out of bounds (1-based)") end
    local targets = select_layers({lua_layer_refs(layer_names)})
    for _, layer in ipairs(targets) do
        if layer.isTilemap then error("ensure_layers_present requires image layers") end
    end
    app.transaction(function()
        for _, layer in ipairs(targets) do
            for fi = first, last do
                if not layer:cel(spr.frames[fi]) then
                    spr:newCel(layer, spr.frames[fi], Image(spr.width, spr.height, spr.colorMode), Point(0, 0))
                end
            end
        end
    end)
    save_project(spr)
    '''
    execution = await execute_edit_script(script, filename)
    return edit_output("Ensured cels on every requested layer", filename, execution)


async def validate_scene(filename: str = "", *, required_layers: Annotated[list[LayerRef], Field(min_length=1)], start_frame: FrameIndex = 1, end_frame: FrameIndex | None = None) -> ToolOutput[SceneValidation]:
    """Check requested layers and cels, including exact nested paths.

    Args:
        filename: Project, defaulting to the active file.
        required_layers: Explicit layer requirements; this checks structure, not artistic quality.
        start_frame: First frame, 1-based.
        end_frame: Last inclusive frame, or the end of the timeline.
    """
    filename = prepare_filename(filename)
    if not required_layers:
        raise ToolError("Required layers list cannot be empty")
    script = _QUALITY_TARGETS + f'''
    local first, last = {start_frame}, {end_frame if end_frame is not None else '#spr.frames'}
    if first < 1 or last > #spr.frames or first > last then error("Frame range out of bounds (1-based)") end
    local result = {{frames=#spr.frames, range={{start=first, ["end"]=last}}, missing_layers={{}}, missing_cels={{}}}}
    for _, ref in ipairs({lua_layer_refs(required_layers)}) do
        local layer = find_layer(spr, ref)
        if not layer then table.insert(result.missing_layers, ref)
        elseif layer.isGroup then error("Select a leaf layer: " .. layer_ref_text(ref))
        else
            for fi = first, last do
                if not layer:cel(spr.frames[fi]) then
                    table.insert(result.missing_cels, {{layer=layer_path(layer), frame=fi}})
                end
            end
        end
    end
    print(json.encode(result))
    '''
    result = json.loads(await AsepriteCommand.execute_lua_script_checked(script, filename))
    return ToolOutput(summary="Scene layer and cel requirements checked", data=result)


async def audit_animation(filename: str = "", start_frame: FrameIndex = 1, end_frame: FrameIndex | None = None,
                          layer_names: list[LayerRef] | None = None,
                          overlap_pairs: list[str | OverlapPair] | None = None,
                          layer_frame_ranges: list[str | LayerFrameRange] | None = None,
                          report_cels: bool = False, report_bounds: bool = False,
                          max_overlaps: Annotated[int, Field(ge=0)] = 200,
                          max_out_of_range: Annotated[int, Field(ge=0)] = 200) -> ToolOutput[AnimationAudit]:
    """Audit leaf-layer cel bounds and activity across an inclusive frame range.

    Args:
        layer_names: Exact targets; omitted selects all nested leaf layers.
        overlap_pairs: Objects with a/b layer references, or legacy layerA,layerB strings.
        layer_frame_ranges: Objects with layer/ranges, or legacy layer:1-8,17-24 strings.
        report_cels: Include cel entries per frame.
        report_bounds: Include cel bounds; overlaps compare bounding rectangles.
        max_overlaps: Maximum overlap samples.
        max_out_of_range: Maximum out-of-range samples.
    """
    filename = prepare_filename(filename)
    opts = dict(start_frame=start_frame, end_frame=end_frame, layer_names=layer_names,
                ranges=_ranges(layer_frame_ranges), pairs=_pairs(overlap_pairs), report_bounds=report_bounds)
    script = _options_script(opts) + f'''
    local result = {{frames={{start=first, ["end"]=last}}, overlaps={{}}, out_of_range={{}}, cels={{}}}}
    local total, overlaps_total, out_of_range_total = 0, 0, 0
    for fi = first, last do
        local entries = {{}}
        for _, layer in ipairs(targets) do
            local cel = layer:cel(spr.frames[fi])
            if cel then
                total = total + 1
                local entry = {{layer=layer_path(layer)}}
                if opts.report_bounds then
                    entry.x=cel.position.x; entry.y=cel.position.y; entry.w=cel.image.width; entry.h=cel.image.height
                end
                table.insert(entries, entry)
                if not in_ranges(layer, fi) then
                    out_of_range_total = out_of_range_total + 1
                    if #result.out_of_range < {max_out_of_range} then
                        table.insert(result.out_of_range, {{frame=fi, layer=layer_path(layer)}})
                    end
                end
            end
        end
        if {str(report_cels).lower()} then table.insert(result.cels, {{frame=fi, cels=entries}}) end
        for _, entry in ipairs(overlaps_for_frame(fi, false)) do
            overlaps_total = overlaps_total + 1
            if #result.overlaps < {max_overlaps} then table.insert(result.overlaps, entry) end
        end
    end
    result.summary = {{total_layers=#select_layers(nil), layers_checked=#targets, total_cels=total,
                       overlaps=#result.overlaps, overlaps_total=overlaps_total,
                       overlaps_truncated=overlaps_total > #result.overlaps, out_of_range=#result.out_of_range,
                       out_of_range_total=out_of_range_total, out_of_range_truncated=out_of_range_total > #result.out_of_range}}
    print(json.encode(result))
    '''
    result = json.loads(await AsepriteCommand.execute_lua_script_checked(script, filename))
    return ToolOutput(summary="Animation structure audited", data=result)


async def animation_sanitize(filename: str = "", start_frame: FrameIndex = 1, end_frame: FrameIndex | None = None,
                             layer_names: list[LayerRef] | None = None, layer_order: list[LayerRef] | None = None,
                             layer_frame_ranges: list[str | LayerFrameRange] | None = None,
                             ensure_layers: list[LayerRef] | None = None, overlap_pairs: list[str | OverlapPair] | None = None,
                             report_bounds: bool = False, max_overlaps: Annotated[int, Field(ge=0)] = 200,
                             ignore_full_canvas_overlaps: bool = True,
                             out_of_range_action: Literal["set_opacity_zero", "delete_cels", "none"] = "set_opacity_zero",
                             out_of_range_opacity: Annotated[int, Field(ge=0, le=255)] = 0,
                             report_only: bool = False, include_stats: bool = True) -> ToolOutput[SanitizeReport]:
    """Repair cel activity and optionally reorder sibling layers, or report proposed effects.

    Args:
        layer_names: Targets; omitted selects every nested leaf layer.
        layer_order: Existing sibling leaf layers in bottom-to-top order; mixed parents fail.
        layer_frame_ranges: Structured layer/ranges objects or legacy layer:1-8 strings.
        ensure_layers: Existing image layers whose missing cels should be created.
        overlap_pairs: Structured a/b references or legacy layerA,layerB strings.
        report_only: Report effects without saving or changing the project.
        out_of_range_action: Action for cels outside their allowed activity ranges.
    """
    filename = prepare_filename(filename)
    opts = dict(start_frame=start_frame, end_frame=end_frame, layer_names=layer_names,
                ranges=_ranges(layer_frame_ranges), pairs=_pairs(overlap_pairs), report_bounds=report_bounds,
                layer_order=layer_order, ensure_layers=ensure_layers)
    script = _options_script(opts) + f'''
    local order = opts.layer_order and select_layers(opts.layer_order) or nil
    local ensure = opts.ensure_layers and select_layers(opts.ensure_layers) or {{}}
    if order then
        for _, layer in ipairs(order) do
            if layer.parent ~= order[1].parent then error("layer_order requires sibling layers with the same parent") end
        end
    end
    for _, layer in ipairs(ensure) do
        if layer.isTilemap then error("ensure_layers requires image layers") end
    end
    local report_only = {str(report_only).lower()}
    local result = {{frames={{start=first, ["end"]=last}}, reordered=false, ensured=0, out_of_range=0,
                    opacity_set=0, deleted=0, layer_stats={{}}, alerts={{}}, overlap_samples={{}}}}
    local analysis = {{total_layers=#select_layers(nil), layers_checked=#targets, total_cels=0,
                      empty_frames=0, overlaps=0, overlaps_total=0, overlaps_truncated=false, inactive_layers={{}}}}
    result.analysis = analysis
    local stats, changed = {{}}, false
    for _, layer in ipairs(targets) do
        stats[layer.id] = {{layer=layer_path(layer), frames_active=0, cel_count=0, full_canvas_cels=0}}
    end
    app.transaction(function()
        if order and #order > 0 then
            local siblings, ordered, seen = order[1].parent.layers, {{}}, {{}}
            for _, layer in ipairs(order) do table.insert(ordered, layer); seen[layer.id] = true end
            for _, layer in ipairs(siblings) do if not seen[layer.id] then table.insert(ordered, layer) end end
            for index, layer in ipairs(ordered) do
                if layer.stackIndex ~= index then
                    result.reordered = true
                    if not report_only then layer.stackIndex = index; changed = true end
                end
            end
        end
        for _, layer in ipairs(ensure) do
            for fi = first, last do
                if not layer:cel(spr.frames[fi]) then
                    result.ensured = result.ensured + 1
                    if not report_only then
                        spr:newCel(layer, spr.frames[fi], Image(spr.width, spr.height, spr.colorMode), Point(0, 0))
                        changed = true
                    end
                end
            end
        end
        for fi = first, last do
            local has_cel = false
            for _, layer in ipairs(targets) do
                local cel, stat = layer:cel(spr.frames[fi]), stats[layer.id]
                if cel then
                    has_cel=true; analysis.total_cels=analysis.total_cels+1
                    stat.frames_active=stat.frames_active+1; stat.cel_count=stat.cel_count+1
                    if cel.image.width == spr.width and cel.image.height == spr.height then stat.full_canvas_cels=stat.full_canvas_cels+1 end
                    local x,y,w,h=cel.position.x,cel.position.y,cel.image.width,cel.image.height
                    if not stat.bounds then stat.bounds={{x,y,x+w,y+h}}
                    else
                        stat.bounds={{math.min(stat.bounds[1],x), math.min(stat.bounds[2],y), math.max(stat.bounds[3],x+w), math.max(stat.bounds[4],y+h)}}
                    end
                    if not in_ranges(layer, fi) then
                        result.out_of_range=result.out_of_range+1
                        if not report_only then
                            if "{out_of_range_action}" == "delete_cels" then
                                spr:deleteCel(cel); result.deleted=result.deleted+1; changed=true
                            elseif "{out_of_range_action}" == "set_opacity_zero" and cel.opacity ~= {out_of_range_opacity} then
                                cel.opacity={out_of_range_opacity}; result.opacity_set=result.opacity_set+1; changed=true
                            end
                        end
                    end
                end
            end
            if not has_cel then analysis.empty_frames=analysis.empty_frames+1 end
            for _, overlap in ipairs(overlaps_for_frame(fi, {str(ignore_full_canvas_overlaps).lower()})) do
                analysis.overlaps_total=analysis.overlaps_total+1
                if #result.overlap_samples < {max_overlaps} then table.insert(result.overlap_samples, overlap) end
            end
        end
    end)
    analysis.overlaps=analysis.overlaps_total
    analysis.overlaps_truncated=analysis.overlaps_total > #result.overlap_samples
    for _, layer in ipairs(targets) do
        local stat=stats[layer.id]
        if stat.cel_count == 0 then table.insert(analysis.inactive_layers, layer_path(layer)) end
        if {str(include_stats).lower()} then table.insert(result.layer_stats, stat) end
        if stat.full_canvas_cels > 0 then table.insert(result.alerts, "full_canvas_cels:" .. json.encode(layer_path(layer))) end
    end
    if analysis.empty_frames > 0 then table.insert(result.alerts, "empty_frames_detected") end
    if result.out_of_range > 0 then table.insert(result.alerts, "cels_out_of_range") end
    if changed then save_project(spr) else print("PROJECT_UNCHANGED") end
    print(json.encode(result))
    '''
    execution = await execute_edit_script(script, filename)
    return ToolOutput(summary="Animation repair report" if report_only else "Animation consistency processed", data=json.loads(execution.stdout))
