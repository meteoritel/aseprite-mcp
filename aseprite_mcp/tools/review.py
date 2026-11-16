"""Read an exact grid and a review image from the same visible frame."""

import json
import uuid
from pathlib import Path
from typing import Literal

from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import AsepriteCommand, lua_escape
from ..core.composite import COMPOSE_FRAME
from ..core.contracts import ContractModel, FrameIndex, Palette, Region, ToolOutput
from ..core.results import SpriteMap
from ..core.sprite_grid import encode_sprite_map, parse_sprite_map
from ..core.state import get_review_directory, prepare_filename

REVIEW_SCALE = 8


class FrameReview(ContractModel):
    filename: str
    frame: int
    map: SpriteMap
    preview_png: str
    preview_scale: int
    preview_lifetime: Literal["session"] = "session"


async def review_frame(*, filename: str = "", frame_index: FrameIndex,
                       region: Region | None = None, palette: Palette | None = None) -> ToolOutput[FrameReview]:
    """Read exact visible RGBA as a character grid and a temporary 8x preview.

    The grid and nearest-neighbor PNG come from one Aseprite composition. Hidden
    layers/groups are excluded. The source project is never saved by this read.

    Args:
        filename: Native project, defaulting to the active file.
        frame_index: Explicit source frame, starting at 1.
        region: Sprite-global pixel rectangle; omitted reads the whole canvas.
        palette: Optional single-character colour mapping to keep characters stable.
    """
    filename = prepare_filename(filename)
    _, error = parse_sprite_map(["."], palette or {}, ".")
    if error:
        raise ToolError(error)
    if region is not None and not isinstance(region, Region):
        region = Region.model_validate(region)
    review_id = uuid.uuid4().hex
    directory = Path(get_review_directory())
    composite = directory / f"{review_id}-source.png"
    preview = directory / f"{review_id}-8x.png"
    selection = "{x=0,y=0,width=spr.width,height=spr.height}"
    if region is not None:
        selection = f"{{x={region.x},y={region.y},width={region.width},height={region.height}}}"
    script = COMPOSE_FRAME + f"""
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    if {frame_index} < 1 or {frame_index} > #spr.frames then error("Frame index out of range (1-based)") end
    local region = {selection}
    local img = compose_frame(spr, {frame_index}, nil)
    local cropped = Image(region.width, region.height, ColorMode.RGB)
    cropped:drawImage(img, Point(-region.x, -region.y))
    cropped:saveAs("{lua_escape(composite.as_posix())}")
    print(json.encode(region))
    """
    try:
        selected = json.loads(await AsepriteCommand.execute_lua_script_checked(script, filename))
        with Image.open(composite) as image:
            rgba = image.convert("RGBA")
            cells = {(x, y): rgba.getpixel((x, y)) for y in range(rgba.height) for x in range(rgba.width)}
            try:
                grid = encode_sprite_map(cells, frame_index=frame_index, palette=palette, **selected)
            except ToolError as exc:
                raise ToolError(f"{exc}. review_frame is exact: shrink region, or use get_sprite_map(max_colors=...) for a quantized read.") from exc
            rgba.resize((rgba.width * REVIEW_SCALE, rgba.height * REVIEW_SCALE), Image.Resampling.NEAREST).save(preview)
        return ToolOutput(summary="Exact frame grid and matching review image", data=FrameReview(
            filename=filename, frame=frame_index, map=grid, preview_png=str(preview), preview_scale=REVIEW_SCALE,
        ))
    except BaseException:
        preview.unlink(missing_ok=True)
        raise
    finally:
        composite.unlink(missing_ok=True)
