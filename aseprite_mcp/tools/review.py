"""Read an exact grid and a review image from the same visible frame."""

from base64 import b64encode
import json
from os.path import normcase
import uuid
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent

from ..core.commands import AsepriteCommand, lua_escape
from ..core.composite import COMPOSE_FRAME
from ..core.contracts import ContractModel, FrameIndex, LayerPath, LayerRef, Palette, Region, SpriteMapEdit, ToolOutput
from ..core.lua import lua_layer_ref
from ..core.region_read import EMIT_REGION_PIXELS, FIND_REGION_CEL, lua_region, read_region_pixels
from ..core.results import PixelChanges, SpriteMap
from ..core.sprite_grid import (
    SpriteMapCapacityError, compare_region_pixels, decode_sprite_map, encode_sprite_map, parse_sprite_map,
)
from ..core.state import get_review_directory, prepare_filename

REVIEW_SCALE = 8


class ReviewedCel(ContractModel):
    layer_name: LayerPath
    status: Literal["exact", "missing_cel", "palette_capacity"]
    edit: SpriteMapEdit | None


class FrameReviewSnapshot(ContractModel):
    filename: str
    frame: FrameIndex
    region: Region
    map: SpriteMap | None
    cel: ReviewedCel | None = None


class FrameReviewChanges(ContractModel):
    composite: PixelChanges | None
    cel: PixelChanges | None


class FrameReview(FrameReviewSnapshot):
    map_unavailable: Literal["palette_capacity"] | None = None
    changes: FrameReviewChanges | None = None
    preview_png: str
    preview_scale: int
    preview_lifetime: Literal["session"] = "session"


async def review_frame(
    *,
    filename: str = "",
    frame_index: FrameIndex,
    region: Region | None = None,
    palette: Palette | None = None,
    layer_name: LayerRef | None = None,
    before: FrameReviewSnapshot | None = None,
) -> Annotated[CallToolResult, ToolOutput[FrameReview]]:
    """Review a frame as an inline 8x PNG and, when colors fit, an exact grid.

    The grid and nearest-neighbor PNG come from one Aseprite composition. Hidden
    layers/groups are excluded. The source project is never saved by this read.

    Args:
        filename: Native project, defaulting to the active file.
        frame_index: Explicit source frame, starting at 1.
        region: Sprite-global pixel rectangle; omitted reads the whole canvas.
        palette: Optional single-character colour mapping to keep characters stable.
        layer_name: Optional image layer to read as an editable cel in the same region.
        before: Previous filename, frame, region, map and cel from review_frame, for exact RGBA comparison.
    """
    filename = prepare_filename(filename)
    _, error = parse_sprite_map(["."], palette or {}, ".")
    if error:
        raise ToolError(error)
    if region is not None and not isinstance(region, Region):
        region = Region.model_validate(region)
    if before is not None and not isinstance(before, FrameReviewSnapshot):
        before = FrameReviewSnapshot.model_validate(before)
    if before is not None and (normcase(before.filename) != normcase(filename) or before.frame != frame_index):
        raise ToolError("Before snapshot must use the same absolute filename and frame as this review")
    review_id = uuid.uuid4().hex
    directory = Path(get_review_directory())
    composite = directory / f"{review_id}-source.png"
    preview = directory / f"{review_id}-8x.png"
    selection = lua_region(region) if region else "{x=0,y=0,width=spr.width,height=spr.height}"
    script = COMPOSE_FRAME
    cel_read = ""
    if layer_name is not None:
        script += FIND_REGION_CEL + EMIT_REGION_PIXELS
        cel_read = f"""
        local path, cel = find_region_cel(spr, {lua_layer_ref(layer_name)}, spr.frames[{frame_index}])
        meta.layer = path
        meta.has_cel = cel ~= nil
        if cel then emit_region_pixels(cel.image, cel.position, region) end
        """
    script += f"""
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    if {frame_index} < 1 or {frame_index} > #spr.frames then error("Frame index out of range (1-based)") end
    local region = {selection}
    local meta = {{region=region}}
    {cel_read}
    local img = compose_frame(spr, {frame_index}, nil)
    local cropped = Image(region.width, region.height, ColorMode.RGB)
    cropped:drawImage(img, Point(-region.x, -region.y))
    cropped:saveAs("{lua_escape(composite.as_posix())}")
    print("REVIEW:" .. json.encode(meta))
    """
    try:
        stdout = await AsepriteCommand.execute_lua_script_checked(script, filename)
        meta = next(json.loads(line.removeprefix("REVIEW:")) for line in stdout.splitlines()
                    if line.startswith("REVIEW:"))
        selected = Region.model_validate(meta["region"])
        layer_path = meta.get("layer")
        cel_pixels = {}
        cel = None
        if layer_path is not None:
            cel = ReviewedCel(layer_name=layer_path, status="missing_cel", edit=None)
            if meta["has_cel"]:
                cel_pixels = read_region_pixels(stdout, selected)
                cel = _editable_cel(cel_pixels, layer_path, frame_index, selected, palette)
        with Image.open(composite) as image:
            rgba = image.convert("RGBA")
            cells = {(x, y): rgba.getpixel((x, y)) for y in range(rgba.height) for x in range(rgba.width)}
            try:
                grid = encode_sprite_map(cells, frame_index=frame_index, palette=palette, **selected.model_dump())
            except SpriteMapCapacityError:
                grid = None
            changes = None
            if before is not None:
                old_composite, old_cel = _read_baseline(before, selected, layer_path)
                changes = FrameReviewChanges(
                    composite=compare_region_pixels(old_composite, cells, selected) if old_composite is not None else None,
                    cel=compare_region_pixels(old_cel, cel_pixels, selected) if old_cel is not None else None,
                )
            rgba.resize((rgba.width * REVIEW_SCALE, rgba.height * REVIEW_SCALE), Image.Resampling.NEAREST).save(preview)
        output = ToolOutput(summary="Frame review", data=FrameReview(
            filename=filename, frame=frame_index, region=selected, map=grid,
            map_unavailable="palette_capacity" if grid is None else None, cel=cel, changes=changes,
            preview_png=str(preview), preview_scale=REVIEW_SCALE,
        ))
        return CallToolResult(
            content=[
                TextContent(type="text", text=output.model_dump_json()),
                ImageContent(type="image", mime_type="image/png", data=b64encode(preview.read_bytes()).decode("ascii")),
            ],
            structured_content=output.model_dump(mode="json"),
        )
    except BaseException:
        preview.unlink(missing_ok=True)
        raise
    finally:
        composite.unlink(missing_ok=True)


def _read_baseline(before: FrameReviewSnapshot, region: Region, layer_path: list[str] | None):
    if before.region != region:
        raise ToolError("Before snapshot must use the same region as this review")
    baseline_path = before.cel.layer_name if before.cel else None
    if baseline_path != layer_path:
        raise ToolError("Before snapshot must use the same layer path as this review")

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
            cel = {}
        elif before.cel.status == "exact":
            edit = before.cel.edit
            if edit is None:
                raise ToolError("Before exact cel must include its edit grid")
            if (edit.layer_name, edit.frame_index, edit.x, edit.y) != (layer_path, before.frame, region.x, region.y):
                raise ToolError("Before cel grid must match the snapshot layer, frame and region")
            cel = decode_sprite_map(edit.rows, edit.palette, edit.transparent, region)
    return composite, cel


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
