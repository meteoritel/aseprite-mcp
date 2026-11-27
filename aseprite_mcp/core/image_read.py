"""Read-only Pillow fast path for external raster reference images."""

from collections import Counter
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from mcp.server.mcpserver.exceptions import ToolError

from .contracts import Region
from .results import ColorStats, ExtractedPalette

RASTER_IMAGE_EXTENSIONS = frozenset({".png", ".bmp", ".webp"})


def is_raster_image(path: str) -> bool:
    """Return True when `path` points to a supported external raster image."""
    return Path(path).suffix.lower() in RASTER_IMAGE_EXTENSIONS


def _open_rgba(path: str) -> Image.Image:
    try:
        with Image.open(path) as image:
            return image.convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise ToolError(f"Could not read image '{path}': {exc}") from exc


def read_raster_rgba(path: str, region: Region | None = None) -> tuple[Region, bytes]:
    """Read RGBA bytes for a raster image, transparent-padding out-of-bounds regions."""
    rgba = _open_rgba(path)
    if region is None:
        selected = Region(x=0, y=0, width=rgba.width, height=rgba.height)
        return selected, rgba.tobytes()
    cropped = Image.new("RGBA", (region.width, region.height), (0, 0, 0, 0))
    cropped.paste(rgba, (-region.x, -region.y))
    return region, cropped.tobytes()


def raster_color_stats(path: str, *, frame_index: int = 1, top: int = 16) -> ColorStats:
    """Count visible RGB color usage in an external raster image without modifying it."""
    rgba = _open_rgba(path)
    counts: Counter[str] = Counter()
    opaque = 0
    pixel_groups = rgba.getcolors(maxcolors=rgba.width * rgba.height) or []
    for count, (r, g, b, a) in pixel_groups:
        if a > 0:
            opaque += count
            counts[f"#{r:02X}{g:02X}{b:02X}"] += count
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "frame": frame_index,
        "unique_colors": len(counts),
        "opaque_pixels": opaque,
        "top_colors": [{"color": color, "count": count} for color, count in ranked[:top]],
    }


def raster_extract_palette(path: str, *, max_colors: int = 16, with_alpha: bool = False) -> ExtractedPalette:
    """Extract an optimal read-only palette from an external raster image."""
    rgba = _open_rgba(path)
    pixel_groups = rgba.getcolors(maxcolors=rgba.width * rgba.height) or []
    has_transparent = False
    visible_counts: Counter[tuple[int, int, int]] = Counter()
    visible_pixels: list[tuple[int, int, int, int]] = []
    for count, (r, g, b, a) in pixel_groups:
        if a == 0:
            has_transparent = True
            continue
        visible_counts[(r, g, b)] += count
        visible_pixels.extend([(r, g, b, a)] * count)

    transparent_index = 0 if has_transparent else None
    if not visible_counts:
        return {
            "colors": [],
            "count": 0,
            "transparent_index": transparent_index,
            "max_colors": max_colors,
            "palette_size": 1 if has_transparent else 0,
        }

    usable_cap = max(1, max_colors - (1 if has_transparent else 0))
    if len(visible_counts) <= usable_cap:
        ranked = sorted(visible_counts.items(), key=lambda item: (-item[1], item[0]))
        colors = [f"#{r:02X}{g:02X}{b:02X}" for (r, g, b), _ in ranked]
    else:
        strip = Image.new("RGBA" if with_alpha else "RGB", (len(visible_pixels), 1))
        if with_alpha:
            strip.putdata(visible_pixels)
            quantized = strip.quantize(colors=usable_cap, method=Image.Quantize.FASTOCTREE)
        else:
            strip.putdata([(r, g, b) for r, g, b, _ in visible_pixels])
            quantized = strip.quantize(colors=usable_cap, method=Image.Quantize.MEDIANCUT)
        raw_palette = quantized.getpalette() or []
        used_indices = sorted(
            (count, idx)
            for count, idx in (quantized.getcolors(maxcolors=usable_cap) or [])
        )
        used_indices.sort(key=lambda item: (-item[0], item[1]))
        colors = []
        seen: set[str] = set()
        for _, idx in used_indices:
            base = idx * 3
            if base + 2 < len(raw_palette):
                r, g, b = raw_palette[base], raw_palette[base + 1], raw_palette[base + 2]
                code = f"#{r:02X}{g:02X}{b:02X}"
                if code not in seen:
                    seen.add(code)
                    colors.append(code)

    palette_size = len(colors) + (1 if has_transparent else 0)
    return {
        "colors": colors,
        "count": len(colors),
        "transparent_index": transparent_index,
        "max_colors": max_colors,
        "palette_size": palette_size,
    }
