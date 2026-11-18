"""Domain payloads returned by editing, inspection and delivery tools."""

from typing import Literal, NotRequired, TypedDict

from pydantic import Field

from .contracts import ContractModel


class EditReceipt(ContractModel):
    filename: str
    layer_paths: list[list[str]] = Field(default_factory=list)
    frame: int | None = None


class ExportReceipt(ContractModel):
    files: list[str]


class PixelColor(TypedDict):
    x: int
    y: int
    hex: str
    r: int
    g: int
    b: int
    a: int


class SpriteLayer(TypedDict):
    name: str
    visible: bool
    opacity: int
    is_group: bool
    parent: str | None
    path: list[str]
    type: Literal["group", "image", "tilemap"]


AnimationTag = TypedDict("AnimationTag", {"name": str, "from": int, "to": int, "direction": str})


class SpriteInfo(TypedDict):
    width: int
    height: int
    color_mode: str
    frames: int
    durations_ms: list[int]
    layers: list[SpriteLayer]
    tags: list[AnimationTag]


class SpriteMap(TypedDict):
    source: Literal["cel", "composite"]
    layer: list[str] | None
    frame: int
    x: int
    y: int
    width: int
    height: int
    transparent: str
    palette: dict[str, str]
    rows: list[str]
    lossy: bool
    columns: NotRequired[str]


class ChangedBounds(TypedDict):
    x: int
    y: int
    width: int
    height: int


class PixelChanges(TypedDict):
    changed_pixels: int
    changed_bounds: ChangedBounds | None


class FrameDifference(TypedDict):
    frame_a: int
    frame_b: int
    changed_pixels: int
    total_pixels: int
    percent_changed: float
    changed_bounds: NotRequired[ChangedBounds]


class ColorUsage(TypedDict):
    color: str
    count: int


class ColorStats(TypedDict):
    frame: int
    unique_colors: int
    opaque_pixels: int
    top_colors: list[ColorUsage]


class ExtractedPalette(TypedDict):
    colors: list[str]
    count: int
    transparent_index: int
    max_colors: int
    palette_size: int


class TextureFrame(TypedDict):
    source_frame: int
    index: int
    duration_ms: int


class TextureDelivery(TypedDict):
    png: str
    mcmeta: str
    preview_png: str
    preview_scale: int
    preview_lifetime: Literal["session"]
    frames: list[TextureFrame]


class TextMetrics(TypedDict):
    width: int
    height: int
    advance_width: int
    above_baseline: int
    below_baseline: int
    left_bearing: int


class FontDescription(TypedDict):
    name: str
    kind: str
    source: str


class TextReceipt(EditReceipt):
    stamp_bounds: ChangedBounds | None = None


class ScriptOutput(ContractModel):
    stdout: str


class PreviewStatus(ContractModel):
    port: int
    url: str | None = None
    running: bool


class TileAt(TypedDict):
    col: int
    row: int
    tile_index: int


class TilemapInfo(TypedDict):
    tile_width: int
    tile_height: int
    tile_count: int
    map_cols: int
    map_rows: int


class SliceInfo(TypedDict):
    name: str
    x: int
    y: int
    width: int
    height: int
    center: NotRequired[dict[str, int]]
    pivot: NotRequired[dict[str, int]]


class FrameRange(TypedDict):
    start: int
    end: int


class MissingCel(TypedDict):
    layer: list[str]
    frame: int


class SceneValidation(TypedDict):
    frames: int
    range: FrameRange
    missing_layers: list[str | list[str]]
    missing_cels: list[MissingCel]


class LayerCel(ContractModel):
    layer: list[str]
    frame: int | None = None
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None


class LayerOverlap(ContractModel):
    frame: int
    a: list[str]
    b: list[str]
    a_bounds: list[int] | None = None
    b_bounds: list[int] | None = None


class FrameCels(ContractModel):
    frame: int
    cels: list[LayerCel]


class AuditSummary(ContractModel):
    total_layers: int
    layers_checked: int
    total_cels: int
    overlaps: int
    overlaps_total: int
    overlaps_truncated: bool
    out_of_range: int
    out_of_range_total: int
    out_of_range_truncated: bool


class AnimationAudit(ContractModel):
    frames: FrameRange
    summary: AuditSummary
    overlaps: list[LayerOverlap]
    out_of_range: list[LayerCel]
    cels: list[FrameCels] = Field(default_factory=list)


class LayerStats(ContractModel):
    layer: list[str]
    frames_active: int
    cel_count: int
    full_canvas_cels: int
    bounds: list[int] | None = None


class SanitizeAnalysis(ContractModel):
    total_layers: int
    layers_checked: int
    total_cels: int
    empty_frames: int
    overlaps: int
    overlaps_total: int
    overlaps_truncated: bool
    inactive_layers: list[list[str]]


class SanitizeReport(ContractModel):
    frames: FrameRange
    reordered: bool
    ensured: int
    out_of_range: int
    opacity_set: int
    deleted: int
    analysis: SanitizeAnalysis
    layer_stats: list[LayerStats] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    overlap_samples: list[LayerOverlap] = Field(default_factory=list)
