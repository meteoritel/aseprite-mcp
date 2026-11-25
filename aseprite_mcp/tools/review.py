"""Review the visible composite and editable cels from one native frame."""

from base64 import b64encode
from contextlib import nullcontext
from os.path import normcase
import uuid
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import Field

from ..core.commands import AsepriteCommand, lua_escape
from ..core.composite import COMPOSE_FRAME
from ..core.contracts import ContractModel, FrameIndex, LayerPath, LayerRef, Palette, Region, SpriteMapEdit, ToolOutput
from ..core.lua import lua_layer_refs
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
    status: Literal["exact", "missing_cel", "palette_capacity"]
    edit: SpriteMapEdit | None = Field(description="For an exact grid, pass a copy to draw_sprite_map with the original filename. Transparent cells erase pixels in this rectangle.")


class FrameReviewSnapshot(ContractModel):
    filename: str
    frame: FrameIndex
    region: Region
    map: SpriteMap | None = Field(description="Exact visible composite grid. Null when the composite exceeds character capacity.")
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
    map_unavailable: Literal["palette_capacity"] | None = None
    snapshot_id: str | None = Field(description="Session-local comparison baseline. Null when the snapshot exceeds the cache budget.")
    changes: FrameReviewChanges | BatchFrameReviewChanges | None = Field(default=None, description="RGBA differences against before_id or before, separately for the composite and cels. An entry is null when its exact baseline is unavailable.")
    cels: list[ReviewedCel] = Field(description="Cels in layer_names order. Empty without a batch selection.")
    previews: list[ReviewPreview] = Field(description="Session-local PNGs in the same order as the inline images.")
    preview_png: str = Field(description="Session-local path to the first inline PNG.")
    preview_scale: int
    preview_lifetime: Literal["session"] = "session"


class _LayerSample(ContractModel):
    layer_name: LayerPath
    has_cel: bool


class _ReviewSample(ContractModel):
    region: Region
    layers: list[_LayerSample] = Field(default_factory=list)


async def review_frame(
    *,
    filename: str = "",
    frame_index: FrameIndex,
    region: Region | None = None,
    palette: Palette | None = None,
    layer_name: LayerRef | None = None,
    layer_names: Annotated[list[LayerRef], Field(min_length=1, max_length=MAX_REVIEW_LAYERS)] | None = None,
    preview_mode: Literal["composite", "layer", "both"] = "composite",
    before: FrameReviewSnapshot | None = None,
    before_id: str | None = None,
    ctx: Context[ReviewSnapshots] | None = None,
) -> Annotated[CallToolResult, ToolOutput[FrameReview]]:
    """Review a frame as inline 8x PNGs and, when colors fit, exact grids.

    Specify image layers to get editable cels alongside the visible composite.
    Keep snapshot_id and pass it as before_id after editing the same target.
    Previews remain available when colors exceed the grid's character capacity.

    Args:
        filename: Native project, defaulting to the active file.
        frame_index: Explicit source frame, starting at 1.
        region: Sprite-global pixel rectangle; omitted reads the whole canvas.
        palette: Optional single-character colour mapping to keep characters stable.
        layer_name: Optional RGB image layer to read as an editable cel in the same region. Use an exact layer path when names are ambiguous.
        layer_names: RGB image layers to read in request order as cels for draw_sprite_maps. Use either layer_name or layer_names.
        preview_mode: Composite shows the visible frame. Layer shows the selected raw cels. Both starts with the composite followed by the selected cels. Layer previews require a layer selection.
        before: Inline baseline for a composite or single layer_name. Pass only filename, frame, region, map and cel from the previous data.
        before_id: Snapshot ID from this session for the same project, frame, region and ordered layer paths. Use either before or before_id. Review again to refresh an expired ID.
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
    filename = prepare_filename(filename)
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
        raise ToolError("Before snapshot must use the same absolute filename and frame as this review")
    review_id = uuid.uuid4().hex
    directory = Path(get_review_directory())
    composite = directory / f"{review_id}-source.png"
    try:
        sample, rgba, cel_rgba = await _sample_frame(
            filename, frame_index, region, refs, composite,
            bounded=layer_names is not None or preview_mode != "composite",
        )
    finally:
        composite.unlink(missing_ok=True)

    previews = []
    try:
        selected = sample.region
        size = selected.width, selected.height
        cels = []
        for layer, raw in zip(sample.layers, cel_rgba, strict=True):
            if raw is None:
                cel = ReviewedCel(layer_name=layer.layer_name, status="missing_cel", edit=None)
            else:
                cel = _editable_cel(region_pixels(raw, selected.width), layer.layer_name, frame_index, selected, palette)
            cels.append(cel)
        try:
            grid = encode_sprite_map(region_pixels(rgba, selected.width), frame_index=frame_index,
                                     palette=palette, **selected.model_dump())
        except SpriteMapCapacityError:
            grid = None
        single_cel = cels[0] if layer_name is not None else None
        layer_paths = tuple(tuple(layer.layer_name) for layer in sample.layers)
        current_cels = tuple(b"" if raw is None else raw for raw in cel_rgba)
        changes = None
        if baseline is not None:
            changes = _review_changes(baseline, selected, layer_paths, rgba, current_cels, batch=layer_names is not None)

        preview_targets = []
        if preview_mode != "layer":
            preview_targets.append((None, rgba))
        if preview_mode != "composite":
            preview_targets.extend((layer.layer_name, raw) for layer, raw in zip(sample.layers, cel_rgba, strict=True))
        images = []
        for index, (layer_path, raw) in enumerate(preview_targets):
            preview = directory / f"{review_id}-{index}-8x.png"
            previews.append(ReviewPreview(kind="composite" if layer_path is None else "layer",
                                          layer_name=layer_path, png=str(preview)))
            image = Image.new("RGBA", size) if raw is None else Image.frombytes("RGBA", size, raw)
            image.resize((size[0] * REVIEW_SCALE, size[1] * REVIEW_SCALE), Image.Resampling.NEAREST).save(preview)
            images.append(ImageContent(type="image", mime_type="image/png", data=b64encode(preview.read_bytes()).decode("ascii")))

        snapshot = ReviewBaseline(filename, frame_index, selected, layer_paths, rgba, current_cels)
        with (cache.record(snapshot) if cache is not None else nullcontext()) as snapshot_id:
            output = ToolOutput(summary="Frame review", data=FrameReview(
                filename=filename, frame=frame_index, region=selected, map=grid,
                map_unavailable="palette_capacity" if grid is None else None,
                cel=single_cel, cels=cels if layer_names is not None else [], changes=changes,
                previews=previews, preview_png=previews[0].png, preview_scale=REVIEW_SCALE,
                snapshot_id=snapshot_id,
            ))
            return CallToolResult(
                content=[TextContent(type="text", text=output.model_dump_json()), *images],
                structured_content=output.model_dump(mode="json"),
            )
    except BaseException:
        for preview in previews:
            Path(preview.png).unlink(missing_ok=True)
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
    rows = [[] for _ in refs]
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
    cels = []
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
        raise ToolError("Before snapshot must use the same region as this review")
    if before.layer_paths != layer_paths:
        raise ToolError("Before snapshot must use the same layer path as this review")
    if isinstance(before, ReviewBaseline) and batch:
        return BatchFrameReviewChanges(
            composite=compare_region_pixels(before.composite, rgba, region),
            cels=[LayerReviewChange(layer_name=list(path), change=compare_region_pixels(old, current, region))
                  for path, old, current in zip(layer_paths, before.cels, cels, strict=True)],
        )
    if isinstance(before, ReviewBaseline):
        old_composite, old_cels = before.composite, before.cels
    else:
        old_composite, old_cels = _decode_baseline(before)
    composite = compare_region_pixels(old_composite, rgba, region) if old_composite is not None else None
    cel = compare_region_pixels(old_cels[0], cels[0], region) if old_cels and old_cels[0] is not None else None
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
