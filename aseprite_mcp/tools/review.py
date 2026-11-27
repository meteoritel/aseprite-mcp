"""Review visible composites, editable cels, and side-by-side contact sheets."""

from base64 import b64encode
from contextlib import nullcontext
import json
import os
from os.path import normcase
from pathlib import Path
import shutil
import tempfile
from typing import Annotated, Literal
import uuid

from PIL import Image
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import Field

from ..core.colors import parse_hex_color
from ..core.commands import AsepriteCommand, lua_escape
from ..core.composite import COMPOSE_FRAME
from ..core.contracts import ContractModel, FrameIndex, LayerPath, LayerRef, Palette, Region, SpriteMapEdit, ToolOutput
from ..core.image_read import is_raster_image, read_raster_rgba
from ..core.lua import lua_layer_refs
from ..core.preview_render import ContactSheetItem, parse_backgrounds, render_contact_sheet, render_review_image
from ..core.region_read import EMIT_REGION_PIXELS, FIND_REGION_CEL, lua_region, read_region_rgba, region_pixels
from ..core.results import PixelChanges, SpriteMap
from ..core.review_snapshots import ReviewBaseline, ReviewSnapshots
from ..core.sprite_grid import (
    SpriteMapCapacityError, compare_region_pixels, decode_sprite_map, encode_sprite_map, parse_sprite_map,
)
from ..core.state import get_review_directory, prepare_filename

REVIEW_SCALE = 8
MAX_REVIEW_LAYERS = 8
MAX_LAYER_REVIEW_PIXELS = 65_536


class ReviewedCel(ContractModel):
    layer_name: LayerPath
    status: Literal["exact", "missing_cel", "palette_capacity", "omitted"]
    edit: SpriteMapEdit | None = Field(description="For an exact grid, pass a copy to draw_sprite_map with the original filename. Transparent cells erase pixels in this rectangle.")


class FrameReviewSnapshot(ContractModel):
    filename: str
    frame: FrameIndex
    region: Region
    map: SpriteMap | None = Field(description="Exact visible composite grid. Null when omitted or when the composite exceeds character capacity.")
    cel: ReviewedCel | None = Field(default=None, description="Original pixels for the selected image layer, independent of layer visibility. Null when no layer was selected.")

    @property
    def layer_paths(self) -> tuple[tuple[str, ...], ...]:
        return (tuple(self.cel.layer_name),) if self.cel is not None else ()


class FrameReviewChanges(ContractModel):
    composite: PixelChanges | None
    cel: PixelChanges | None


class LayerReviewChange(ContractModel):
    layer_name: LayerPath
    change: PixelChanges


class BatchFrameReviewChanges(FrameReviewChanges):
    cel: None = None
    cels: list[LayerReviewChange]


class ReviewPreview(ContractModel):
    kind: Literal["composite", "layer"]
    layer_name: LayerPath | None
    png: str


class FrameReview(FrameReviewSnapshot):
    map_unavailable: Literal["palette_capacity", "omitted"] | None = None
    snapshot_id: str | None = Field(description="Session-local comparison baseline. Null when the snapshot exceeds the cache budget.")
    changes: FrameReviewChanges | BatchFrameReviewChanges | None = Field(default=None, description="RGBA differences against before_id or before, separately for the composite and cels. An entry is null when its exact baseline is unavailable.")
    cels: list[ReviewedCel] = Field(description="Cels in layer_names order. Empty without a batch selection.")
    previews: list[ReviewPreview] = Field(description="Session-local PNGs in the same order as the inline images.")
    preview_png: str = Field(description="Session-local path to the first inline PNG.")
    saved_preview_png: str | None = Field(default=None, description="Persistent path written when save_preview_to is provided.")
    preview_scale: int
    preview_lifetime: Literal["session"] = "session"


class ContactSheetEntry(ContractModel):
    label: str
    source: str
    frame: int
    slice_name: str | None = None
    width: int
    height: int


class ContactSheetReview(ContractModel):
    entries: list[ContactSheetEntry]
    backgrounds: list[str]
    preview_png: str
    saved_preview_png: str | None = None
    preview_scale: int
    preview_lifetime: Literal["session"] = "session"


class _LayerSample(ContractModel):
    layer_name: LayerPath
    has_cel: bool


class _ReviewSample(ContractModel):
    region: Region
    layers: list[_LayerSample] = Field(default_factory=list)


def _resolve_save_preview_path(save_preview_to: str) -> Path | None:
    if not save_preview_to:
        return None
    path = Path(prepare_filename(save_preview_to, must_exist=False, anchor=False))
    if path.suffix.lower() != ".png":
        path = Path(str(path) + ".png")
    return path


def _publish_preview(source: Path, destination: Path) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".aseprite-preview-", dir=destination.parent) as staging:
            staged = Path(staging) / destination.name
            shutil.copyfile(source, staged)
            os.replace(staged, destination)
    except OSError as exc:
        raise ToolError(f"Could not save preview to '{destination}': {exc}") from exc


def _seed_palette_for_cells(previous: dict[str, str] | None, cells: dict[tuple[int, int], tuple[int, int, int, int]]) -> dict[str, str] | None:
    if not previous:
        return None
    present = {rgba for rgba in cells.values() if rgba[3] >= 1}
    if not present:
        return None
    retained: dict[str, str] = {}
    for char, hex_value in previous.items():
        rgba = parse_hex_color(hex_value)
        if rgba is not None and rgba in present:
            retained[char] = hex_value
    return retained or None


async def review_frame(
    *,
    filename: str = "",
    frame_index: FrameIndex,
    region: Region | None = None,
    palette: Palette | None = None,
    layer_name: LayerRef | None = None,
    layer_names: Annotated[list[LayerRef], Field(min_length=1, max_length=MAX_REVIEW_LAYERS)] | None = None,
    preview_mode: Literal["composite", "layer", "both"] = "composite",
    backgrounds: Annotated[list[str], Field(min_length=1, max_length=6)] | None = None,
    show_grid: bool = False,
    grid_mode: Literal["full", "composite", "none"] = "full",
    save_preview_to: str = "",
    before: FrameReviewSnapshot | None = None,
    before_id: str | None = None,
    ctx: Context[ReviewSnapshots] | None = None,
) -> Annotated[CallToolResult, ToolOutput[FrameReview]]:
    """Review a frame as inline 8x PNGs and, when requested, exact grids.

    Supports multi-background compositing (`backgrounds`, e.g. `["#303034", "#8B8B8B", "checker"]`
    or presets `mc_hud`, `mc_slot`, `mc_dark`) and pixel coordinate grids (`show_grid=True`).
    Use `grid_mode="none"` for lightweight visual/diff re-checks, and `save_preview_to` to keep
    a persistent PNG for reports. Also supports read-only inspection of external `.png` reference
    images without changing the active project. For side-by-side comparison across multiple files,
    frames, slices, or reference PNGs, call `review_contact_sheet`.

    Args:
        filename: Native project (defaulting to the active file) or external raster image (.png/.bmp/.webp, read-only).
        frame_index: Explicit source frame, starting at 1.
        region: Sprite-global pixel rectangle; omitted reads the whole canvas.
        palette: Optional single-character colour mapping to keep characters stable. When omitted with before_id, existing colors keep their baseline characters.
        layer_name: Optional RGB image layer to read as an editable cel in the same region. Use an exact layer path when names are ambiguous.
        layer_names: RGB image layers to read in request order as cels for draw_sprite_maps. Use either layer_name or layer_names.
        preview_mode: Composite shows the visible frame. Layer shows the selected raw cels. Both starts with the composite followed by the selected cels. Layer previews require a layer selection.
        backgrounds: Optional list of 1-6 preview backgrounds ('transparent', 'checker', presets mc_hud/mc_slot/mc_dark/dark/light, or #RRGGBB). Multiple values render as one labeled horizontal strip.
        show_grid: Overlay a 1px pixel grid with 0-based coordinate rulers (default False).
        grid_mode: 'full' returns composite and cel edit grids (default), 'composite' omits cel edit grids, 'none' omits all grids for minimal payload visual/diff checks.
        save_preview_to: Optional persistent PNG path to also save the primary rendered preview.
        before: Inline baseline for a composite or single layer_name. Pass only filename, frame, region, map and cel from the previous data.
        before_id: Snapshot ID from this session for the same project, frame and region. Supports composite-only, subset, or reordered reviews of recorded layers.
    """
    if layer_names is not None and layer_name is not None:
        raise ToolError("Choose either layer_name or layer_names")
    if layer_names is not None and not 1 <= len(layer_names) <= MAX_REVIEW_LAYERS:
        raise ToolError(f"Select between 1 and {MAX_REVIEW_LAYERS} layer_names")
    if before is not None and before_id is not None:
        raise ToolError("Choose either before or before_id")
    if before is not None and layer_names is not None:
        raise ToolError("Use before_id with layer_names")
    refs = layer_names if layer_names is not None else [layer_name] if layer_name is not None else []
    if preview_mode != "composite" and not refs:
        raise ToolError("Layer previews require layer_name or layer_names")
    parsed_bgs = parse_backgrounds(backgrounds)
    save_target = _resolve_save_preview_path(save_preview_to)

    external_raster = bool(filename) and is_raster_image(filename)
    filename = prepare_filename(filename, anchor=not external_raster)
    if is_raster_image(filename):
        external_raster = True
    if external_raster and (refs or preview_mode != "composite"):
        raise ToolError("External raster images have a single composite layer; omit layer_name/layer_names and use preview_mode='composite'.")
    if external_raster and frame_index != 1:
        raise ToolError("External raster images only support frame_index=1")

    _, error = parse_sprite_map(["."], palette or {}, ".")
    if error:
        raise ToolError(error)
    if region is not None and not isinstance(region, Region):
        region = Region.model_validate(region)
    if before is not None and not isinstance(before, FrameReviewSnapshot):
        before = FrameReviewSnapshot.model_validate(before)
    cache = ctx.request_context.lifespan_context if ctx is not None else None
    baseline: FrameReviewSnapshot | ReviewBaseline | None = before
    if before_id is not None:
        if cache is None:
            raise ToolError("Use before_id within an MCP session")
        baseline = cache.get(before_id)
    if baseline is not None and (normcase(baseline.filename) != normcase(filename) or baseline.frame != frame_index):
        raise ToolError(
            "Before snapshot must use the same absolute filename and frame as this review "
            f"(baseline={baseline.filename!r} frame={baseline.frame}, requested={filename!r} frame={frame_index})"
        )

    review_id = uuid.uuid4().hex
    directory = Path(get_review_directory())
    if external_raster:
        selected_region, rgba = read_raster_rgba(filename, region)
        sample = _ReviewSample(region=selected_region, layers=[])
        cel_rgba: list[bytes | None] = []
    else:
        composite = directory / f"{review_id}-source.png"
        try:
            sample, rgba, cel_rgba = await _sample_frame(
                filename, frame_index, region, refs, composite,
                bounded=layer_names is not None or preview_mode != "composite",
            )
        finally:
            composite.unlink(missing_ok=True)

    previews: list[ReviewPreview] = []
    try:
        selected = sample.region
        size = selected.width, selected.height
        baseline_comp_palette = baseline.composite_palette if isinstance(baseline, ReviewBaseline) else None
        baseline_cel_palettes = baseline.cel_palettes if isinstance(baseline, ReviewBaseline) else {}

        cels: list[ReviewedCel] = []
        recorded_cel_palettes: dict[tuple[str, ...], dict[str, str]] = {}
        for layer, raw in zip(sample.layers, cel_rgba, strict=True):
            path_key = tuple(layer.layer_name)
            if raw is None:
                cel = ReviewedCel(layer_name=layer.layer_name, status="missing_cel", edit=None)
            elif grid_mode != "full":
                cel = ReviewedCel(layer_name=layer.layer_name, status="omitted", edit=None)
                if path_key in baseline_cel_palettes:
                    recorded_cel_palettes[path_key] = dict(baseline_cel_palettes[path_key])
            else:
                cells = region_pixels(raw, selected.width)
                effective_palette = palette if palette is not None else _seed_palette_for_cells(baseline_cel_palettes.get(path_key), cells)
                cel = _editable_cel(cells, layer.layer_name, frame_index, selected, effective_palette)
                if cel.edit is not None:
                    recorded_cel_palettes[path_key] = dict(cel.edit.palette)
            cels.append(cel)

        map_unavailable: Literal["palette_capacity", "omitted"] | None = None
        if grid_mode == "none":
            grid = None
            map_unavailable = "omitted"
            recorded_comp_palette = dict(baseline_comp_palette) if baseline_comp_palette else {}
        else:
            composite_cells = region_pixels(rgba, selected.width)
            effective_comp_palette = palette if palette is not None else _seed_palette_for_cells(baseline_comp_palette, composite_cells)
            try:
                grid = encode_sprite_map(composite_cells, frame_index=frame_index,
                                         palette=effective_comp_palette, **selected.model_dump())
                recorded_comp_palette = dict(grid["palette"])
            except SpriteMapCapacityError:
                grid = None
                map_unavailable = "palette_capacity"
                recorded_comp_palette = dict(baseline_comp_palette) if baseline_comp_palette else {}

        single_cel = cels[0] if layer_name is not None else None
        layer_paths = tuple(tuple(layer.layer_name) for layer in sample.layers)
        current_cels = tuple(b"" if raw is None else raw for raw in cel_rgba)
        changes = None
        if baseline is not None:
            changes = _review_changes(baseline, selected, layer_paths, rgba, current_cels, batch=layer_names is not None)

        preview_targets: list[tuple[LayerPath | None, bytes | None]] = []
        if preview_mode != "layer":
            preview_targets.append((None, rgba))
        if preview_mode != "composite":
            preview_targets.extend((layer.layer_name, raw) for layer, raw in zip(sample.layers, cel_rgba, strict=True))

        images: list[ImageContent] = []
        for index, (layer_path, raw) in enumerate(preview_targets):
            preview = directory / f"{review_id}-{index}-8x.png"
            previews.append(ReviewPreview(kind="composite" if layer_path is None else "layer",
                                          layer_name=layer_path, png=str(preview)))
            rendered = render_review_image(
                raw,
                size,
                scale=REVIEW_SCALE,
                backgrounds=parsed_bgs,
                show_grid=show_grid,
                origin=(selected.x, selected.y),
            )
            rendered.save(preview)
            images.append(ImageContent(type="image", mime_type="image/png", data=b64encode(preview.read_bytes()).decode("ascii")))

        saved_preview: str | None = None
        if save_target is not None:
            _publish_preview(Path(previews[0].png), save_target)
            saved_preview = str(save_target)

        snapshot = ReviewBaseline(
            filename,
            frame_index,
            selected,
            layer_paths,
            rgba,
            current_cels,
            composite_palette=recorded_comp_palette,
            cel_palettes=recorded_cel_palettes,
        )
        with (cache.record(snapshot) if cache is not None else nullcontext()) as snapshot_id:
            output = ToolOutput(summary="Frame review", data=FrameReview(
                filename=filename, frame=frame_index, region=selected, map=grid,
                map_unavailable=map_unavailable,
                cel=single_cel, cels=cels if layer_names is not None else [], changes=changes,
                previews=previews, preview_png=previews[0].png, saved_preview_png=saved_preview,
                preview_scale=REVIEW_SCALE, snapshot_id=snapshot_id,
            ))
            return CallToolResult(
                content=[TextContent(type="text", text=output.model_dump_json()), *images],
                structured_content=output.model_dump(mode="json"),
            )
    except BaseException:
        for preview in previews:
            Path(preview.png).unlink(missing_ok=True)
        raise


def _unique_labels(raw_labels: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for label in raw_labels:
        counts[label] = counts.get(label, 0) + 1
    seen: dict[str, int] = {}
    result: list[str] = []
    for label in raw_labels:
        if counts[label] == 1:
            result.append(label)
        else:
            seen[label] = seen.get(label, 0) + 1
            result.append(f"{label}#{seen[label]}")
    return result


async def _render_native_batch(targets: list[tuple[str, int]], staging: Path) -> list[tuple[tuple[int, int], bytes]]:
    """Render multiple (native_project_path, frame_index) entries in one Aseprite process."""
    manifest = []
    out_paths: list[Path] = []
    for index, (src, frame) in enumerate(targets):
        out = staging / f"sheet-item-{index}.png"
        out_paths.append(out)
        manifest.append({"src": Path(src).as_posix(), "frame": frame, "out": out.as_posix()})
    encoded = lua_escape(json.dumps(manifest, ensure_ascii=False))
    script = COMPOSE_FRAME + f'''
    local targets = json.decode("{encoded}")
    local opened = {{}}
    local ok, err = pcall(function()
        for _, entry in ipairs(targets) do
            local spr = opened[entry.src]
            if not spr then
                spr = app.open(entry.src)
                if not spr then error("Could not open sprite: " .. entry.src) end
                opened[entry.src] = spr
            end
            if entry.frame < 1 or entry.frame > #spr.frames then
                error("Frame index " .. entry.frame .. " out of range for " .. entry.src .. " (sprite has " .. #spr.frames .. " frames, 1-based)")
            end
            local img = compose_frame(spr, entry.frame, nil)
            img:saveAs(entry.out)
        end
    end)
    for _, spr in pairs(opened) do spr:close() end
    if not ok then error(err) end
    print("OK")
    '''
    await AsepriteCommand.execute_lua_script_checked(script)
    rendered: list[tuple[tuple[int, int], bytes]] = []
    for out in out_paths:
        if not out.is_file():
            raise ToolError("Aseprite exited successfully but wrote no contact-sheet frame")
        with Image.open(out) as image:
            rgba = image.convert("RGBA")
            rendered.append((rgba.size, rgba.tobytes()))
    return rendered


async def _render_slice_batch(source: str, frame_index: int, slice_names: list[str], staging: Path) -> list[tuple[tuple[int, int], bytes]]:
    requested = lua_escape(json.dumps(slice_names, ensure_ascii=False))
    out = staging / "slice-frame.png"
    script = COMPOSE_FRAME + f'''
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then error("Frame index " .. idx .. " out of range (1-based)") end
    local requested = json.decode("{requested}")
    local slices, dupes = {{}}, {{}}
    for _, slice in ipairs(spr.slices) do
        if slices[slice.name] then dupes[slice.name] = true end
        slices[slice.name] = slice
    end
    local boxes = {{}}
    for _, name in ipairs(requested) do
        if dupes[name] then error("Ambiguous slice name: " .. name) end
        local slice = slices[name]
        if not slice then error("Slice not found: " .. name) end
        local b = slice.bounds
        if not b or b.x < 0 or b.y < 0 or b.width < 1 or b.height < 1 or b.x + b.width > spr.width or b.y + b.height > spr.height then
            error("Slice outside the canvas: " .. name)
        end
        table.insert(boxes, {{b.x, b.y, b.x + b.width, b.y + b.height}})
    end
    local img = compose_frame(spr, idx, nil)
    img:saveAs("{lua_escape(out.as_posix())}")
    print("BOXES:" .. json.encode(boxes))
    '''
    stdout = await AsepriteCommand.execute_lua_script_checked(script, source)
    boxes_line = next((line.removeprefix("BOXES:") for line in stdout.splitlines() if line.startswith("BOXES:")), None)
    if boxes_line is None:
        raise ToolError("Aseprite returned incomplete slice metadata")
    boxes = json.loads(boxes_line)
    with Image.open(out) as image:
        rgba = image.convert("RGBA")
        items: list[tuple[tuple[int, int], bytes]] = []
        for box in boxes:
            cropped = rgba.crop(tuple(box))
            items.append((cropped.size, cropped.tobytes()))
        return items


async def review_contact_sheet(
    *,
    filenames: Annotated[list[str], Field(min_length=1, max_length=12)] | None = None,
    filename: str = "",
    frame_index: FrameIndex = 1,
    frame_indices: Annotated[list[FrameIndex], Field(min_length=1, max_length=16)] | None = None,
    slice_names: Annotated[list[str], Field(min_length=1, max_length=16)] | None = None,
    labels: list[str] | None = None,
    scale: Annotated[int, Field(ge=1, le=16)] = 8,
    backgrounds: Annotated[list[str], Field(min_length=1, max_length=4)] | None = None,
    show_grid: bool = False,
    columns: Annotated[int, Field(ge=1, le=12)] | None = None,
    save_preview_to: str = "",
) -> Annotated[CallToolResult, ToolOutput[ContactSheetReview]]:
    """Render a side-by-side labeled contact sheet for asset sets, frames, or slices.

    Ideal for aligning proportions, palette harmony, and silhouettes across item sets
    (e.g. potion variants, armor sets, crop stages) or comparing native `.aseprite`
    assets directly next to external `.png` reference sprites on dark/light HUD backgrounds
    in one Aseprite process and one inline image. Does not change the active file.

    Args:
        filenames: Compare 1-12 files side-by-side (may mix .aseprite/.ase and external .png/.bmp/.webp reference images). Mutually exclusive with filename/frame_indices/slice_names.
        filename: Single source project for frame_indices or slice_names mode (defaults to active file).
        frame_index: Frame number (1-based, default 1) used in filenames or slice_names mode.
        frame_indices: Compare 1-16 frames of one project side-by-side. Mutually exclusive with filenames and slice_names.
        slice_names: Compare 1-16 named slices of one project side-by-side. Mutually exclusive with filenames and frame_indices.
        labels: Optional custom labels matching the item count.
        scale: Nearest-neighbor integer scale factor, 1..16 (default 8).
        backgrounds: Optional 1-4 backgrounds ('transparent', 'checker', mc_hud/mc_slot/mc_dark/dark/light, or #RRGGBB). Multiple values stack one aligned row per background.
        show_grid: Overlay a 1px pixel grid and coordinate rulers on each panel (default False).
        columns: Maximum panels per row in single-background mode (default up to 6).
        save_preview_to: Optional persistent PNG path to also save the rendered contact sheet.
    """
    modes = sum(x is not None for x in (filenames, frame_indices, slice_names))
    if modes != 1:
        raise ToolError("Specify exactly one of filenames, frame_indices, or slice_names")
    if filenames is not None and filename:
        raise ToolError("Do not pass filename together with filenames")

    parsed_bgs = parse_backgrounds(backgrounds)
    save_target = _resolve_save_preview_path(save_preview_to)

    entries_meta: list[ContactSheetEntry] = []
    sheet_items: list[ContactSheetItem] = []

    with tempfile.TemporaryDirectory(prefix="aseprite-contact-") as staging_dir:
        staging = Path(staging_dir)
        if filenames is not None:
            resolved_paths = [prepare_filename(path, anchor=False) for path in filenames]
            item_labels = labels if labels is not None else _unique_labels([Path(path).stem for path in resolved_paths])
            if len(item_labels) != len(resolved_paths):
                raise ToolError(f"labels count ({len(item_labels)}) must match filenames count ({len(resolved_paths)})")

            native_slots: list[int] = []
            native_targets: list[tuple[str, int]] = []
            sampled: list[tuple[tuple[int, int], bytes] | None] = [None] * len(resolved_paths)
            for idx, path in enumerate(resolved_paths):
                if is_raster_image(path):
                    selected_region, rgba = read_raster_rgba(path)
                    sampled[idx] = ((selected_region.width, selected_region.height), rgba)
                else:
                    native_slots.append(idx)
                    native_targets.append((path, frame_index))
            if native_targets:
                native_results = await _render_native_batch(native_targets, staging)
                for slot, result in zip(native_slots, native_results, strict=True):
                    sampled[slot] = result

            for path, label, item in zip(resolved_paths, item_labels, sampled, strict=True):
                assert item is not None
                (width, height), rgba = item
                entries_meta.append(ContactSheetEntry(
                    label=label, source=path, frame=1 if is_raster_image(path) else frame_index,
                    width=width, height=height,
                ))
                sheet_items.append(ContactSheetItem(label=label, size=(width, height), rgba=rgba))

        elif frame_indices is not None:
            source = prepare_filename(filename, anchor=False)
            item_labels = labels if labels is not None else [f"F{idx}" for idx in frame_indices]
            if len(item_labels) != len(frame_indices):
                raise ToolError(f"labels count ({len(item_labels)}) must match frame_indices count ({len(frame_indices)})")
            if is_raster_image(source):
                if any(idx != 1 for idx in frame_indices):
                    raise ToolError("External raster images only support frame_index=1")
                selected_region, rgba = read_raster_rgba(source)
                rendered_frames = [((selected_region.width, selected_region.height), rgba) for _ in frame_indices]
            else:
                rendered_frames = await _render_native_batch([(source, idx) for idx in frame_indices], staging)
            for idx, label, ((width, height), rgba) in zip(frame_indices, item_labels, rendered_frames, strict=True):
                entries_meta.append(ContactSheetEntry(label=label, source=source, frame=idx, width=width, height=height))
                sheet_items.append(ContactSheetItem(label=label, size=(width, height), rgba=rgba))

        else:
            assert slice_names is not None
            source = prepare_filename(filename, anchor=False)
            if is_raster_image(source):
                raise ToolError("slice_names requires a native .aseprite or .ase project")
            item_labels = labels if labels is not None else list(slice_names)
            if len(item_labels) != len(slice_names):
                raise ToolError(f"labels count ({len(item_labels)}) must match slice_names count ({len(slice_names)})")
            rendered_slices = await _render_slice_batch(source, frame_index, slice_names, staging)
            for name, label, ((width, height), rgba) in zip(slice_names, item_labels, rendered_slices, strict=True):
                entries_meta.append(ContactSheetEntry(
                    label=label, source=source, frame=frame_index, slice_name=name, width=width, height=height,
                ))
                sheet_items.append(ContactSheetItem(label=label, size=(width, height), rgba=rgba))

    preview = Path(get_review_directory()) / f"contact-{uuid.uuid4().hex}-{scale}x.png"
    try:
        sheet = render_contact_sheet(
            sheet_items,
            scale=scale,
            backgrounds=parsed_bgs,
            show_grid=show_grid,
            columns=columns,
        )
        sheet.save(preview)
        saved_preview: str | None = None
        if save_target is not None:
            _publish_preview(preview, save_target)
            saved_preview = str(save_target)
        image_block = ImageContent(type="image", mime_type="image/png", data=b64encode(preview.read_bytes()).decode("ascii"))
        output = ToolOutput(
            summary=f"Contact sheet rendered ({len(entries_meta)} items)",
            data=ContactSheetReview(
                entries=entries_meta,
                backgrounds=[bg.label for bg in parsed_bgs],
                preview_png=str(preview),
                saved_preview_png=saved_preview,
                preview_scale=scale,
            ),
        )
        return CallToolResult(
            content=[TextContent(type="text", text=output.model_dump_json()), image_block],
            structured_content=output.model_dump(mode="json"),
        )
    except BaseException:
        preview.unlink(missing_ok=True)
        raise


async def _sample_frame(filename: str, frame_index: int, region: Region | None, refs: list[LayerRef],
                        composite: Path, *, bounded: bool) -> tuple[_ReviewSample, bytes, list[bytes | None]]:
    selection = lua_region(region) if region else "{x=0,y=0,width=spr.width,height=spr.height}"
    script = COMPOSE_FRAME + FIND_REGION_CEL + EMIT_REGION_PIXELS + f"""
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    if {frame_index} < 1 or {frame_index} > #spr.frames then error("Frame index out of range (1-based)") end
    local region = {selection}
    local refs = {lua_layer_refs(refs)}
    if {str(bounded).lower()} and region.width * region.height * (1 + #refs) > {MAX_LAYER_REVIEW_PIXELS} then
        error("Layer review exceeds the pixel budget. Choose a smaller region or fewer layers.")
    end
    local meta = {{region=region}}
    if #refs > 0 then
        meta.layers = {{}}
        local seen = {{}}
        for index, ref in ipairs(refs) do
            local path, cel = find_region_cel(spr, ref, spr.frames[{frame_index}])
            local key = json.encode(path)
            if seen[key] then error("Duplicate review layer: " .. key) end
            seen[key] = true
            meta.layers[index] = {{layer_name=path, has_cel=cel ~= nil}}
            if cel then emit_region_pixels(cel.image, cel.position, region, "RGBA:" .. index .. ":") end
        end
    end
    local img = compose_frame(spr, {frame_index}, nil)
    local cropped = Image(region.width, region.height, ColorMode.RGB)
    cropped:drawImage(img, Point(-region.x, -region.y))
    cropped:saveAs("{lua_escape(composite.as_posix())}")
    print("REVIEW:" .. json.encode(meta))
    """
    stdout = await AsepriteCommand.execute_lua_script_checked(script, filename)
    sample = None
    rows: list[list[str]] = [[] for _ in refs]
    try:
        for line in stdout.splitlines():
            if line.startswith("RGBA:"):
                _, index, row = line.split(":", 2)
                slot = int(index) - 1
                if not 0 <= slot < len(rows):
                    raise ValueError("unexpected cel index")
                rows[slot].append(row)
            elif line.startswith("REVIEW:"):
                if sample is not None:
                    raise ValueError("duplicate review metadata")
                sample = _ReviewSample.model_validate_json(line.removeprefix("REVIEW:"))
    except ValueError as exc:
        raise ToolError(f"Aseprite returned invalid frame review data: {exc}") from exc
    if sample is None or len(sample.layers) != len(refs):
        raise ToolError("Aseprite returned incomplete frame review metadata")
    cels: list[bytes | None] = []
    for layer, layer_rows in zip(sample.layers, rows, strict=True):
        if not layer.has_cel and layer_rows:
            raise ToolError("Aseprite returned RGBA for a missing cel")
        cels.append(read_region_rgba(layer_rows, sample.region) if layer.has_cel else None)
    with Image.open(composite) as image:
        if image.size != (sample.region.width, sample.region.height):
            raise ToolError("Aseprite returned unexpected composite dimensions")
        return sample, image.convert("RGBA").tobytes(), cels


def _review_changes(before: FrameReviewSnapshot | ReviewBaseline, region: Region,
                    layer_paths: tuple[tuple[str, ...], ...], rgba: bytes, cels: tuple[bytes, ...],
                    *, batch: bool) -> FrameReviewChanges:
    if before.region != region:
        raise ToolError(
            "Before snapshot must use the same region as this review "
            f"(baseline region={before.region.model_dump()}, requested region={region.model_dump()})"
        )

    if isinstance(before, ReviewBaseline):
        old_composite: bytes | None = before.composite
        old_cels: tuple[bytes | None, ...] = before.cels
    else:
        old_composite, old_cels = _decode_baseline(before)

    baseline_layers = dict(zip(before.layer_paths, old_cels, strict=True))
    missing_layers = [list(path) for path in layer_paths if path not in baseline_layers]
    if missing_layers:
        recorded = [list(path) for path in before.layer_paths]
        raise ToolError(
            f"Before snapshot must use the same layer path or a superset of requested layers "
            f"(missing={missing_layers}, baseline layer_paths={recorded}, baseline region={before.region.model_dump()})"
        )

    composite = compare_region_pixels(old_composite, rgba, region) if old_composite is not None else None
    if not layer_paths:
        return FrameReviewChanges(composite=composite, cel=None)
    if batch:
        return BatchFrameReviewChanges(
            composite=composite,
            cels=[
                LayerReviewChange(
                    layer_name=list(path),
                    change=compare_region_pixels(baseline_layers[path] or b"", current, region),
                )
                for path, current in zip(layer_paths, cels, strict=True)
            ],
        )
    old_single = baseline_layers[layer_paths[0]]
    cel = compare_region_pixels(old_single, cels[0], region) if old_single is not None else None
    return FrameReviewChanges(composite=composite, cel=cel)


def _decode_baseline(before: FrameReviewSnapshot) -> tuple[bytes | None, tuple[bytes | None, ...]]:
    region = before.region
    composite = None
    if before.map is not None:
        grid = before.map
        if grid["lossy"] or grid["source"] != "composite" or grid["layer"] is not None:
            raise ToolError("Before map must be an exact composite grid")
        if grid["frame"] != before.frame or any(grid[key] != value for key, value in region.model_dump().items()):
            raise ToolError("Before map must match the snapshot frame and region")
        composite = decode_sprite_map(grid["rows"], grid["palette"], grid["transparent"], region)

    cel = None
    if before.cel is not None:
        if before.cel.status == "missing_cel":
            cel = b""
        elif before.cel.status == "exact":
            edit = before.cel.edit
            if edit is None:
                raise ToolError("Before exact cel must include its edit grid")
            if (edit.layer_name, edit.frame_index, edit.x, edit.y) != (before.cel.layer_name, before.frame, region.x, region.y):
                raise ToolError("Before cel grid must match the snapshot layer, frame and region")
            cel = decode_sprite_map(edit.rows, edit.palette, edit.transparent, region)
    return composite, (cel,) if before.cel is not None else ()


def _editable_cel(cells, layer_path, frame_index, region, palette) -> ReviewedCel:
    try:
        grid = encode_sprite_map(cells, frame_index=frame_index, palette=palette, **region.model_dump())
    except SpriteMapCapacityError:
        return ReviewedCel(layer_name=layer_path, status="palette_capacity", edit=None)
    edit = SpriteMapEdit(
        layer_name=layer_path, frame_index=frame_index, x=region.x, y=region.y,
        rows=grid["rows"], palette=grid["palette"], transparent=grid["transparent"],
        erase_transparent=True, create_if_missing=False,
    )
    return ReviewedCel(layer_name=layer_path, status="exact", edit=edit)
