"""Native Aseprite filters with explicit layer/frame targeting."""

from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import lua_escape
from ..core.contracts import FrameIndex, LayerRef, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.image_read import is_raster_image, raster_extract_palette
from ..core.native import build_native_command_script
from ..core.results import EditReceipt, ExtractedPalette
from ..core.state import prepare_filename
from .fx import _parse_hex_color

# Built-in convolution-matrix resource names (Aseprite data/convmatr.def).
CONVOLUTION_MATRICES = frozenset({
    "brightness", "contrast", "negative",
    "blur-3x3", "blur-3x3-hard", "blur-5x5", "blur-7x7", "blur-9x9", "blur-17x17",
    "blur-5x3-left", "blur-17x3-left", "blur-3x17-top",
    "blur-5x5-diagonal(\\)", "blur-5x5-diagonal(/)",
    "sharpen-3x3", "sharpen-5x5", "sharpen-7x7",
    "edges-find", "edges-find-horizontal", "edges-find-vertical",
    "misc-contour", "misc-texturize", "misc-emboss", "misc-marmolize",
    "misc-rock", "misc-rock-edges",
    "drunk-3x3_x", "drunk-3x3_+", "drunk-5x5_x", "drunk-5x5_+",
    "drunk-7x7_x", "drunk-7x7_+", "drunk-9x9_x", "drunk-9x9_+",
    "drunk-17x17_x", "drunk-17x17_+", "drunk-17x17_o",
    "outline-transparent-layer-(cross)", "outline-transparent-layer-(square)",
})


def _region(x: int, y: int, width: int, height: int):
    return (x, y, width, height) if width > 0 and height > 0 else None


async def outline_native(filename: str='', *, layer_name: LayerRef, frame_index: FrameIndex, color: str='#000000', place: str='outside', matrix: str='circle') -> ToolOutput[EditReceipt]:
    """Native Aseprite Outline around opaque pixels (app.command.Outline).

    Higher quality than the 1px hand-rolled outline_cel: inside/outside
    placement + a circle/square brush. Works best on a full-canvas cel.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: layer to outline (empty = active layer)
        frame_index: 1-based frame
        color: outline colour as #RRGGBB
        place: "outside" or "inside"
        matrix: "circle" or "square"
    """
    filename = prepare_filename(filename)
    rgb = _parse_hex_color(color)
    if not rgb:
        raise ToolError("Invalid color (expected #RRGGBB)")
    if place not in ("outside", "inside"):
        raise ToolError("place must be 'outside' or 'inside'")
    if matrix not in ("circle", "square"):
        raise ToolError("matrix must be 'circle' or 'square'")
    r, g, b = rgb
    cmd = (f'        app.command.Outline{{ui=false, color=Color{{r={r}, g={g}, '
           f'b={b}, a=255}}, place="{place}", matrix="{matrix}"}}')
    script = build_native_command_script(cmd, layer_name, frame_index)
    execution = await execute_edit_script(script, filename)
    return edit_output(f"Outlined ({place}, {matrix}) {layer_name or 'active layer'} in {filename}", filename, execution, frame_index)


async def adjust_hsl_native(filename: str='', *, layer_name: LayerRef, frame_index: FrameIndex, hue: int=0, saturation: int=0, lightness: int=0, x: int=0, y: int=0, width: int=0, height: int=0) -> ToolOutput[EditReceipt]:
    """Native Hue/Saturation/Lightness filter (engine-quality vs adjust_hsl).

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: layer to adjust (empty = active layer)
        frame_index: 1-based frame
        hue: -180..180 (degrees)
        saturation: -100..100
        lightness: -100..100
        x, y, width, height: optional region (width>0 & height>0 to scope)
    """
    filename = prepare_filename(filename)
    if not (-180 <= hue <= 180):
        raise ToolError("hue must be -180..180")
    if not (-100 <= saturation <= 100) or not (-100 <= lightness <= 100):
        raise ToolError("saturation and lightness must be -100..100")
    cmd = (f'        app.command.HueSaturation{{ui=false, hue={hue}, '
           f'saturation={saturation}, lightness={lightness}, alpha=0}}')
    script = build_native_command_script(cmd, layer_name, frame_index,
                                         _region(x, y, width, height))
    execution = await execute_edit_script(script, filename)
    return edit_output(f"Adjusted HSL on {layer_name or 'active layer'} in {filename}", filename, execution, frame_index)


async def adjust_brightness_contrast(filename: str='', *, layer_name: LayerRef, frame_index: FrameIndex, brightness: int=0, contrast: int=0, x: int=0, y: int=0, width: int=0, height: int=0) -> ToolOutput[EditReceipt]:
    """Native Brightness/Contrast filter (app.command.BrightnessContrast).

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: layer to adjust (empty = active layer)
        frame_index: 1-based frame
        brightness: -100..100
        contrast: -100..100
        x, y, width, height: optional region (width>0 & height>0 to scope)
    """
    filename = prepare_filename(filename)
    if not (-100 <= brightness <= 100) or not (-100 <= contrast <= 100):
        raise ToolError("brightness and contrast must be -100..100")
    cmd = (f'        app.command.BrightnessContrast{{ui=false, '
           f'brightness={brightness}, contrast={contrast}}}')
    script = build_native_command_script(cmd, layer_name, frame_index,
                                         _region(x, y, width, height))
    execution = await execute_edit_script(script, filename)
    return edit_output(f"Adjusted brightness/contrast on {layer_name or 'active layer'} in {filename}", filename, execution, frame_index)


async def invert_colors(filename: str='', *, layer_name: LayerRef, frame_index: FrameIndex, x: int=0, y: int=0, width: int=0, height: int=0) -> ToolOutput[EditReceipt]:
    """Native colour inversion (app.command.InvertColor).

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: layer to invert (empty = active layer)
        frame_index: 1-based frame
        x, y, width, height: optional region (width>0 & height>0 to scope)
    """
    filename = prepare_filename(filename)
    cmd = "        app.command.InvertColor{ui=false}"
    script = build_native_command_script(cmd, layer_name, frame_index,
                                         _region(x, y, width, height))
    execution = await execute_edit_script(script, filename)
    return edit_output(f"Inverted colours on {layer_name or 'active layer'} in {filename}", filename, execution, frame_index)


async def apply_convolution(filename: str='', *, matrix: str, layer_name: LayerRef, frame_index: FrameIndex, x: int=0, y: int=0, width: int=0, height: int=0) -> ToolOutput[EditReceipt]:
    """Native convolution filter (blur / sharpen / edge / emboss …).

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        matrix: a built-in matrix name (see list_convolution_matrices),
            e.g. "blur-3x3", "sharpen-3x3", "edges-find", "misc-emboss"
        layer_name: layer to filter (empty = active layer)
        frame_index: 1-based frame
        x, y, width, height: optional region (width>0 & height>0 to scope)
    """
    filename = prepare_filename(filename)
    if matrix not in CONVOLUTION_MATRICES:
        raise ToolError(f"Unknown matrix {matrix!r}; call list_convolution_matrices for "
                f"the {len(CONVOLUTION_MATRICES)} valid names")
    cmd = f'        app.command.ConvolutionMatrix{{ui=false, fromResource="{lua_escape(matrix)}"}}'
    script = build_native_command_script(cmd, layer_name, frame_index,
                                         _region(x, y, width, height))
    execution = await execute_edit_script(script, filename)
    return edit_output(f"Applied convolution '{matrix}' on {layer_name or 'active layer'} in {filename}", filename, execution, frame_index)


async def list_convolution_matrices() -> ToolOutput[list[str]]:
    """List the built-in convolution-matrix names usable with apply_convolution.

    Returns:
        JSON array of matrix resource names.
    """
    return ToolOutput(summary='List convolution matrices completed', data=sorted(CONVOLUTION_MATRICES))


async def extract_palette(
    filename: str = "",
    max_colors: int = 16,
    with_alpha: bool = False,
) -> ToolOutput[ExtractedPalette]:
    """Build an OPTIMAL palette from a sprite or read-only external image.

    For native `.aseprite`/`.ase` projects, runs Aseprite ColorQuantization and
    writes the resulting palette back to the sprite (requires RGB mode). For
    external `.png`/`.bmp`/`.webp` reference images, extracts the optimal
    palette in read-only mode without modifying the file or active project.

    `max_colors` is a slot budget, not a promise of that many colours:
    slot 0 is reserved for transparency when present, so expect at most
    `max_colors - 1` usable colours.

    Args:
        filename: Native project (defaults to active file) or external raster image (.png/.bmp/.webp, read-only)
        max_colors: palette slot cap, 1..256 (fewer if the art has fewer)
        with_alpha: include alpha when quantizing

    Returns:
        JSON {colors: [#RRGGBB, ...], count, transparent_index, max_colors,
        palette_size}.
    """
    external_raster = bool(filename) and is_raster_image(filename)
    filename = prepare_filename(filename, anchor=not external_raster)
    if not (1 <= max_colors <= 256):
        raise ToolError("max_colors must be 1..256")
    if is_raster_image(filename):
        return ToolOutput(
            summary="Read-only palette extracted from external image (file untouched)",
            data=raster_extract_palette(filename, max_colors=max_colors, with_alpha=with_alpha),
        )
    wa = "true" if with_alpha else "false"
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end
    app.transaction(function()
        app.command.ColorQuantization{{ui=false, maxColors={max_colors}, withAlpha={wa}}}
    end)
    save_project(spr)
    local pal = spr.palettes[1]
    -- Slot 0 of an Aseprite palette is conventionally the transparent colour
    -- (alpha 0). It paints nothing, so listing it as a colour invents a
    -- duplicate "#000000" whenever the art really contains black; report it
    -- apart from the colours instead.
    print("PALETTE_SIZE:" .. #pal)
    local transparent_index = -1
    for i = 0, #pal - 1 do
        local c = pal:getColor(i)
        if c.alpha == 0 then
            if transparent_index < 0 then transparent_index = i end
        else
            print(string.format("PALETTE:#%02X%02X%02X", c.red, c.green, c.blue))
        end
    end
    print("TRANSPARENT:" .. transparent_index)
    print("OK")
    """
    execution = await execute_edit_script(script, filename)
    output = execution.stdout
    colors = [ln[len("PALETTE:"):] for ln in output.splitlines() if ln.startswith("PALETTE:")]
    transparent_index = None
    palette_size = None
    for line in output.splitlines():
        if line.startswith("TRANSPARENT:"):
            value = int(line[len("TRANSPARENT:"):])
            transparent_index = value if value >= 0 else None
        elif line.startswith("PALETTE_SIZE:"):
            palette_size = int(line[len("PALETTE_SIZE:"):])
    if palette_size is None:
        # Reconstruct rather than under-report: the transparent slot is a
        # real slot even though it never shows up in `colors`.
        palette_size = len(colors) + (1 if transparent_index is not None else 0)
    return ToolOutput(summary='Extract palette completed', data={'colors': colors, 'count': len(colors), 'transparent_index': transparent_index, 'max_colors': max_colors, 'palette_size': palette_size})
