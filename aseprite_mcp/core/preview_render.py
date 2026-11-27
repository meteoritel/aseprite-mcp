"""Pure-Pillow preview compositing, pixel coordinate grids, and contact sheets."""

from __future__ import annotations

from dataclasses import dataclass
import math
from PIL import Image, ImageDraw
from mcp.server.mcpserver.exceptions import ToolError

from .colors import parse_hex_color

BACKGROUND_PRESETS: dict[str, tuple[int, int, int, int]] = {
    "mc_hud": (0x30, 0x30, 0x34, 255),
    "mc_slot": (0x8B, 0x8B, 0x8B, 255),
    "mc_dark": (0x0E, 0x16, 0x1C, 255),
    "dark": (0x18, 0x18, 0x1B, 255),
    "light": (0xF0, 0xF0, 0xF0, 255),
    "white": (0xFF, 0xFF, 0xFF, 255),
    "black": (0x00, 0x00, 0x00, 255),
}

_CHROME_BG = (24, 26, 30, 255)
_CHROME_HEADER = (34, 37, 43, 255)
_CHROME_BORDER = (62, 67, 76, 255)
_CHROME_TEXT = (224, 228, 234, 255)
_CHROME_MUTED = (168, 174, 184, 255)

# Compact 3x5 bitmap glyphs for dependency-free crisp labels and pixel rulers.
_GLYPHS_3X5: dict[str, tuple[str, ...]] = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("111", "101", "101", "101", "101"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "#": ("101", "111", "101", "111", "101"),
    "-": ("000", "000", "111", "000", "000"),
    "_": ("000", "000", "000", "000", "111"),
    ".": ("000", "000", "000", "000", "010"),
    ":": ("000", "010", "000", "010", "000"),
    "/": ("001", "001", "010", "100", "100"),
    "+": ("000", "010", "111", "010", "000"),
    "(": ("010", "100", "100", "100", "010"),
    ")": ("010", "001", "001", "001", "010"),
    " ": ("000", "000", "000", "000", "000"),
    "?": ("110", "001", "010", "000", "010"),
}


@dataclass(frozen=True, slots=True)
class ParsedBackground:
    label: str
    kind: str  # "transparent" | "checker" | "solid"
    rgba: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class ContactSheetItem:
    label: str
    size: tuple[int, int]
    rgba: bytes


def parse_background(spec: str) -> ParsedBackground:
    key = spec.strip().lower()
    if key == "transparent":
        return ParsedBackground(label="transparent", kind="transparent")
    if key == "checker":
        return ParsedBackground(label="checker", kind="checker")
    if key in BACKGROUND_PRESETS:
        return ParsedBackground(label=key, kind="solid", rgba=BACKGROUND_PRESETS[key])
    rgba = parse_hex_color(spec)
    if rgba is not None:
        r, g, b, a = rgba
        label = f"#{r:02X}{g:02X}{b:02X}" if a == 255 else f"#{r:02X}{g:02X}{b:02X}{a:02X}"
        return ParsedBackground(label=label, kind="solid", rgba=rgba)
    presets = ", ".join(sorted(BACKGROUND_PRESETS))
    raise ToolError(
        f"Invalid background {spec!r}. Use 'transparent', 'checker', a preset ({presets}), "
        "or a hex color like '#303034'."
    )


def parse_backgrounds(specs: list[str] | None) -> list[ParsedBackground]:
    if not specs:
        return [ParsedBackground(label="transparent", kind="transparent")]
    return [parse_background(item) for item in specs]


def _measure_bitmap_text(text: str) -> int:
    return max(0, len(text) * 4 - 1)


def _draw_bitmap_text(image: Image.Image, x: int, y: int, text: str, color: tuple[int, int, int, int], max_width: int | None = None) -> None:
    pixels = image.load()
    width, height = image.size
    upper = text.upper()
    if max_width is not None and max_width >= 3:
        max_chars = (max_width + 1) // 4
        if len(upper) > max_chars:
            upper = upper[: max(1, max_chars - 1)] + "." if max_chars >= 2 else upper[:1]
    cursor = x
    for ch in upper:
        glyph = _GLYPHS_3X5.get(ch, _GLYPHS_3X5["?"])
        for row_idx, row in enumerate(glyph):
            py = y + row_idx
            if not 0 <= py < height:
                continue
            for col_idx, bit in enumerate(row):
                if bit == "1":
                    px = cursor + col_idx
                    if 0 <= px < width:
                        pixels[px, py] = color
        cursor += 4


def _checker_image(width: int, height: int, tile: int) -> Image.Image:
    light = (204, 204, 204, 255)
    dark = (153, 153, 153, 255)
    bg = Image.new("RGBA", (width, height), light)
    draw = ImageDraw.Draw(bg)
    for y in range(0, height, tile):
        row_parity = (y // tile) & 1
        for x in range(0, width, tile):
            if ((x // tile) & 1) != row_parity:
                draw.rectangle((x, y, min(width - 1, x + tile - 1), min(height - 1, y + tile - 1)), fill=dark)
    return bg


def _is_dark_background(bg: ParsedBackground) -> bool:
    if bg.kind != "solid" or bg.rgba is None:
        return False
    r, g, b, _ = bg.rgba
    return (0.299 * r + 0.587 * g + 0.114 * b) < 110


def _apply_grid_and_ruler(canvas: Image.Image, size: tuple[int, int], scale: int, bg: ParsedBackground, origin: tuple[int, int]) -> Image.Image:
    art_w, art_h = size
    scaled_w, scaled_h = canvas.size
    overlay = Image.new("RGBA", (scaled_w, scaled_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if _is_dark_background(bg):
        minor, major = (255, 255, 255, 48), (255, 255, 255, 96)
    else:
        minor, major = (0, 0, 0, 48), (0, 0, 0, 96)

    for col in range(1, art_w):
        x = col * scale
        color = major if (origin[0] + col) % 4 == 0 else minor
        draw.line((x, 0, x, scaled_h - 1), fill=color)
    for row in range(1, art_h):
        y = row * scale
        color = major if (origin[1] + row) % 4 == 0 else minor
        draw.line((0, y, scaled_w - 1, y), fill=color)

    gridded = Image.alpha_composite(canvas, overlay)

    max_y_label = max(len(str(origin[1])), len(str(origin[1] + art_h - 1)))
    left_margin = max(12, max_y_label * 4 + 4)
    top_margin = 10
    framed = Image.new("RGBA", (left_margin + scaled_w + 1, top_margin + scaled_h + 1), _CHROME_HEADER)
    framed.paste(gridded, (left_margin, top_margin))
    fdraw = ImageDraw.Draw(framed)
    fdraw.rectangle((left_margin - 1, top_margin - 1, left_margin + scaled_w, top_margin + scaled_h), outline=_CHROME_BORDER)

    max_x_label = max(len(str(origin[0])), len(str(origin[0] + art_w - 1)))
    label_w = max_x_label * 4 + 1
    x_step = max(1, math.ceil(label_w / max(1, scale)))
    if x_step > 1:
        for candidate in (2, 4, 8, 16):
            if candidate >= x_step:
                x_step = candidate
                break
    for col in range(0, art_w, x_step):
        text = str(origin[0] + col)
        tw = _measure_bitmap_text(text)
        tx = left_margin + col * scale + max(0, (scale - tw) // 2)
        _draw_bitmap_text(framed, tx, 2, text, _CHROME_MUTED)

    y_step = 1 if scale >= 7 else max(2, math.ceil(7 / max(1, scale)))
    for row in range(0, art_h, y_step):
        text = str(origin[1] + row)
        tw = _measure_bitmap_text(text)
        tx = max(1, left_margin - tw - 2)
        ty = top_margin + row * scale + max(0, (scale - 5) // 2)
        _draw_bitmap_text(framed, tx, ty, text, _CHROME_MUTED)

    return framed


def render_sprite_panel(
    rgba: bytes | None,
    size: tuple[int, int],
    *,
    scale: int = 8,
    background: ParsedBackground | None = None,
    show_grid: bool = False,
    origin: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Render one scaled RGBA sprite onto a background with optional pixel grid."""
    bg = background or ParsedBackground(label="transparent", kind="transparent")
    sprite = Image.new("RGBA", size) if rgba is None else Image.frombytes("RGBA", size, rgba)
    scaled_size = (size[0] * scale, size[1] * scale)
    scaled = sprite.resize(scaled_size, Image.Resampling.NEAREST)

    if bg.kind == "transparent" and not show_grid:
        return scaled

    if bg.kind == "checker":
        canvas = Image.alpha_composite(_checker_image(scaled_size[0], scaled_size[1], max(4, scale // 2)), scaled)
    elif bg.kind == "solid" and bg.rgba is not None:
        canvas = Image.alpha_composite(Image.new("RGBA", scaled_size, bg.rgba), scaled)
    else:
        canvas = scaled

    if show_grid:
        return _apply_grid_and_ruler(canvas, size, scale, bg, origin)
    return canvas


def render_review_image(
    rgba: bytes | None,
    size: tuple[int, int],
    *,
    scale: int = 8,
    backgrounds: list[ParsedBackground] | None = None,
    show_grid: bool = False,
    origin: tuple[int, int] = (0, 0),
) -> Image.Image:
    """Render a single preview or a labeled horizontal multi-background comparison strip."""
    resolved = backgrounds or [ParsedBackground(label="transparent", kind="transparent")]
    if len(resolved) == 1:
        return render_sprite_panel(rgba, size, scale=scale, background=resolved[0], show_grid=show_grid, origin=origin)

    panels = [
        (bg.label, render_sprite_panel(rgba, size, scale=scale, background=bg, show_grid=show_grid, origin=origin))
        for bg in resolved
    ]
    pad = 8
    header_h = 13
    panel_w = max(panel.width for _, panel in panels)
    panel_h = max(panel.height for _, panel in panels)
    total_w = pad + len(panels) * (panel_w + pad)
    total_h = pad + header_h + panel_h + pad

    strip = Image.new("RGBA", (total_w, total_h), _CHROME_BG)
    draw = ImageDraw.Draw(strip)
    for index, (label, panel) in enumerate(panels):
        x0 = pad + index * (panel_w + pad)
        y0 = pad
        draw.rectangle((x0, y0, x0 + panel_w - 1, y0 + header_h - 1), fill=_CHROME_HEADER)
        _draw_bitmap_text(strip, x0 + 3, y0 + 4, label, _CHROME_TEXT, max_width=panel_w - 6)
        strip.paste(panel, (x0 + (panel_w - panel.width) // 2, y0 + header_h))
        draw.rectangle((x0, y0, x0 + panel_w - 1, y0 + header_h + panel_h - 1), outline=_CHROME_BORDER)
    return strip


def render_contact_sheet(
    items: list[ContactSheetItem],
    *,
    scale: int = 8,
    backgrounds: list[ParsedBackground] | None = None,
    show_grid: bool = False,
    columns: int | None = None,
) -> Image.Image:
    """Stitch multiple sprites side-by-side with aligned baselines and crisp labels."""
    resolved_bgs = backgrounds or [ParsedBackground(label="transparent", kind="transparent")]
    pad = 8
    header_h = 14

    if len(resolved_bgs) > 1:
        # One horizontal row per background so all items stay aligned vertically and horizontally.
        row_label_w = max(_measure_bitmap_text(bg.label) for bg in resolved_bgs) + 10
        rendered_rows = [
            [
                render_sprite_panel(item.rgba, item.size, scale=scale, background=bg, show_grid=show_grid)
                for item in items
            ]
            for bg in resolved_bgs
        ]
        cell_w = max(panel.width for row in rendered_rows for panel in row)
        cell_w = max(cell_w, 40)
        cell_h = max(panel.height for row in rendered_rows for panel in row)
        total_w = pad + row_label_w + len(items) * (cell_w + pad)
        total_h = pad + header_h + len(resolved_bgs) * (cell_h + pad)

        sheet = Image.new("RGBA", (total_w, total_h), _CHROME_BG)
        draw = ImageDraw.Draw(sheet)
        for col_idx, item in enumerate(items):
            x0 = pad + row_label_w + col_idx * (cell_w + pad)
            draw.rectangle((x0, pad, x0 + cell_w - 1, pad + header_h - 1), fill=_CHROME_HEADER)
            _draw_bitmap_text(sheet, x0 + 3, pad + 4, item.label, _CHROME_TEXT, max_width=cell_w - 6)

        for row_idx, (bg, row_panels) in enumerate(zip(resolved_bgs, rendered_rows, strict=True)):
            y0 = pad + header_h + row_idx * (cell_h + pad)
            draw.rectangle((pad, y0, pad + row_label_w - 4, y0 + cell_h - 1), fill=_CHROME_HEADER, outline=_CHROME_BORDER)
            _draw_bitmap_text(sheet, pad + 3, y0 + max(2, (cell_h - 5) // 2), bg.label, _CHROME_MUTED, max_width=row_label_w - 8)
            for col_idx, panel in enumerate(row_panels):
                x0 = pad + row_label_w + col_idx * (cell_w + pad)
                draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + cell_h - 1), fill=bg.rgba if bg.kind == "solid" and bg.rgba else _CHROME_BG)
                px = x0 + (cell_w - panel.width) // 2
                py = y0 + (cell_h - panel.height)  # bottom-align silhouettes for height comparison
                sheet.paste(panel, (px, py))
                draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + cell_h - 1), outline=_CHROME_BORDER)
        return sheet

    bg = resolved_bgs[0]
    panels = [
        (item.label, render_sprite_panel(item.rgba, item.size, scale=scale, background=bg, show_grid=show_grid))
        for item in items
    ]
    col_count = min(len(panels), columns) if columns else min(len(panels), 6)
    row_count = math.ceil(len(panels) / col_count)
    cell_w = max(max(panel.width for _, panel in panels), 40)
    cell_h = max(panel.height for _, panel in panels)
    slot_h = header_h + cell_h
    total_w = pad + col_count * (cell_w + pad)
    total_h = pad + row_count * (slot_h + pad)

    sheet = Image.new("RGBA", (total_w, total_h), _CHROME_BG)
    draw = ImageDraw.Draw(sheet)
    for idx, (label, panel) in enumerate(panels):
        row_idx, col_idx = divmod(idx, col_count)
        x0 = pad + col_idx * (cell_w + pad)
        y0 = pad + row_idx * (slot_h + pad)
        draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + header_h - 1), fill=_CHROME_HEADER)
        _draw_bitmap_text(sheet, x0 + 3, y0 + 4, label, _CHROME_TEXT, max_width=cell_w - 6)
        body_y = y0 + header_h
        if bg.kind == "solid" and bg.rgba is not None:
            draw.rectangle((x0, body_y, x0 + cell_w - 1, body_y + cell_h - 1), fill=bg.rgba)
        px = x0 + (cell_w - panel.width) // 2
        py = body_y + (cell_h - panel.height)
        sheet.paste(panel, (px, py))
        draw.rectangle((x0, y0, x0 + cell_w - 1, body_y + cell_h - 1), outline=_CHROME_BORDER)
    return sheet
