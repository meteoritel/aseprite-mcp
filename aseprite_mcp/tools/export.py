"""Native-project exports, exact artifact publication and Java textures."""

import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from ntpath import isreserved
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..core.commands import AsepriteCommand, lua_escape
from ..core.contracts import FrameIndex, LayerRef, ToolOutput
from ..core.editing import edit_output, execute_edit_script, native_project_path, validate_native_project
from ..core.inspection import read_sprite_info
from ..core.lua import EDIT_TARGET, NORMALIZE_CEL, lua_layer_ref
from ..core.results import EditReceipt, ExportReceipt, SliceTextureDelivery, TextureDelivery
from ..core.state import get_review_directory, prepare_filename

REVIEW_SCALE = 8
MILLISECONDS_PER_TICK = 50


def _output_path(filename: str, extension: str = "") -> Path:
    if not filename:
        raise ToolError("Specify an explicit output path")
    path = Path(prepare_filename(filename, must_exist=False, anchor=False))
    if extension and path.suffix.lower() != extension:
        path = Path(str(path) + extension)
    return path


@contextmanager
def _export_directory(target: Path):
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".aseprite-export-", dir=target.parent) as directory:
            yield Path(directory)
    except OSError as exc:
        raise ToolError(f"Could not export '{target}': {exc}") from exc


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        image.load()
        return image.size


def _generated_images(directory: Path, requested: Path) -> list[Path]:
    pattern = re.compile(re.escape(requested.stem) + r"(\d*)" + re.escape(requested.suffix), re.IGNORECASE)
    produced = [path for path in directory.iterdir() if path.is_file() and pattern.fullmatch(path.name)]
    if not produced:
        raise ToolError("Aseprite exited successfully but wrote no output file")
    for path in produced:
        if path.suffix.lower() in (".ase", ".aseprite"):
            validate_native_project(str(path))
        else:
            _image_size(path)
    return sorted(produced, key=lambda path: int(pattern.fullmatch(path.name).group(1) or 0))


def _require_distinct_paths(paths: list[Path]) -> None:
    canonical = {os.path.normcase(str(path.resolve())) for path in paths}
    if len(canonical) != len(paths):
        raise ToolError("Export outputs must have distinct paths")


def _publish_files(files: list[tuple[Path, Path]]) -> None:
    """Prepare each file beside its target and restore ordinary failed publishes."""
    _require_distinct_paths([target for _, target in files])
    prepared, applied, retained = [], [], set()
    try:
        for source, target in files:
            target.parent.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix=".aseprite-publish-", dir=target.parent))
            replacement = directory / "new"
            backup = directory / "previous"
            record = (directory, replacement, backup, target, target.exists())
            prepared.append(record)
            shutil.copyfile(source, replacement)
            if record[4]:
                shutil.copyfile(target, backup)
        for record in prepared:
            os.replace(record[1], record[3])
            applied.append(record)
    except OSError as exc:
        recovery = []
        for directory, replacement, backup, target, existed in reversed(applied):
            try:
                if existed:
                    os.replace(backup, target)
                else:
                    target.unlink()
            except OSError as restore_error:
                retained.add(directory)
                recovery.append(f"'{target}': {restore_error}; backup: {backup}")
        detail = " Recovery needed: " + "; ".join(recovery) if recovery else ""
        raise ToolError(f"Could not publish export: {exc}.{detail}") from exc
    finally:
        for directory, *_ in prepared:
            if directory not in retained:
                shutil.rmtree(directory)


def _select_frames(info: dict, frame_index: int | None = None, tag_name: str = "") -> tuple[list[int], str]:
    if frame_index is not None and tag_name:
        raise ToolError("Select either frame_index or tag_name")
    if frame_index is not None:
        if not 1 <= frame_index <= info["frames"]:
            raise ToolError(f"Frame index {frame_index} out of range (sprite has {info['frames']} frames, 1-based)")
        return [frame_index], "forward"
    if tag_name:
        tag = next((tag for tag in info["tags"] if tag["name"] == tag_name), None)
        if tag is None:
            raise ToolError(f"Tag not found: {tag_name}")
        return list(range(tag["from"], tag["to"] + 1)), tag["direction"]
    return list(range(1, info["frames"] + 1)), "forward"


def _frame_filter(frames: list[int]) -> list[str]:
    return ["--frame-range", f"{frames[0] - 1},{frames[-1] - 1}"]


def _read_sheet_data(path: Path, expected_frames: int) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        frames = data["frames"]
        if not isinstance(frames, (list, dict)) or len(frames) != expected_frames:
            raise ValueError("wrong frame collection")
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError(f"Aseprite returned invalid sheet metadata: {exc}") from exc


async def export_sprite(*, filename: str = "", output_filename: str, format: str = "png") -> ToolOutput[ExportReceipt]:
    """Export to an image or image sequence; report the exact published files.

    Args:
        filename: Native project (defaults to the active file)
        output_filename: Output path; numbered siblings are used for still sequences
        format: Aseprite-writable image format, such as png or gif
    """
    filename = prepare_filename(filename)
    target = _output_path(output_filename, "." + format.lower())
    with _export_directory(target) as directory:
        staged = directory / target.name
        await AsepriteCommand.run_command(["--batch", filename, "--save-as", str(staged)])
        produced = _generated_images(directory, staged)
        files = [(path, target.parent / path.name) for path in produced]
        _publish_files(files)
    return ToolOutput(summary="Sprite exported to " + ", ".join(str(target) for _, target in files), data=ExportReceipt(files=[str(path) for _, path in files]))


async def copy_sprite(*, filename: str = "", output_filename: str, overwrite: bool = False) -> ToolOutput[ExportReceipt]:
    """Copy a native project, preserving layers, frames and tags.

    Args:
        filename: Source project (defaults to the active file)
        output_filename: New native project path
        overwrite: Replace an existing destination (default False)
    """
    filename = prepare_filename(filename)
    target = native_project_path(str(_output_path(output_filename)))
    if os.path.exists(target) and not overwrite:
        raise ToolError(f"Output file already exists: {target}")
    if os.path.exists(target) and os.path.samefile(filename, target):
        return ToolOutput(summary=f"Sprite already at {target}", data=ExportReceipt(files=[str(target)]))
    execution = await execute_edit_script("save_project(app.activeSprite)", filename, output_filename=target)
    return ToolOutput(summary=f"Sprite copied to {target}", data=ExportReceipt(files=[str(target)]))


async def export_frame(*, filename: str = "", frame_index: FrameIndex, output_filename: str, scale: int = 1) -> ToolOutput[ExportReceipt]:
    """Export one validated frame to an exact PNG path.

    Args:
        filename: Source project (defaults to the active file)
        frame_index: Explicit source frame, 1-based
        output_filename: Output PNG path
        scale: Nearest-neighbor scale factor, 1..64 (default 1)
    """
    filename = prepare_filename(filename)
    if not 1 <= scale <= 64:
        raise ToolError("scale must be between 1 and 64")
    info = await read_sprite_info(filename)
    frames, _ = _select_frames(info, frame_index)
    target = _output_path(output_filename, ".png")
    with _export_directory(target) as directory:
        staged = directory / target.name
        await AsepriteCommand.run_command(["--batch", *_frame_filter(frames), filename,
                                           "--scale", str(scale), "--save-as", str(staged)])
        produced = _generated_images(directory, staged)
        if len(produced) != 1 or _image_size(produced[0]) != (info["width"] * scale, info["height"] * scale):
            raise ToolError("Aseprite returned an invalid single-frame image")
        _publish_files([(produced[0], target)])
    return ToolOutput(summary=f"Frame {frame_index} exported to {target} at {scale}x", data=ExportReceipt(files=[str(target)]))


async def export_spritesheet(*, filename: str = "", output_filename: str,
                            sheet_type: Literal["horizontal", "vertical", "rows", "columns", "packed"] = "horizontal", data_filename: str = "",
                            scale: int = 1, padding: int = 0, tag_name: str = "",
                            data_format: Literal["json-array", "json-hash"] = "json-array", list_tags: bool = False) -> ToolOutput[ExportReceipt]:
    """Export a sheet and optional Aseprite JSON from this invocation's artifacts.

    Args:
        filename: Source project (defaults to the active file)
        output_filename: Output PNG path
        sheet_type: horizontal, vertical, rows, columns or packed
        data_filename: Optional Aseprite JSON output path
        scale: Nearest-neighbor scale factor, 1..64
        padding: Spacing between frames (default 0)
        tag_name: Restrict the export to an existing tag
        data_format: json-array or json-hash
        list_tags: Include tag metadata in the JSON (default False)
    """
    filename = prepare_filename(filename)
    if sheet_type not in ("horizontal", "vertical", "rows", "columns", "packed"):
        raise ToolError("Unsupported sheet_type")
    if not 1 <= scale <= 64 or padding < 0:
        raise ToolError("scale must be 1..64 and padding must be >= 0")
    if data_format not in ("json-array", "json-hash"):
        raise ToolError("data_format must be json-array or json-hash")
    info = await read_sprite_info(filename)
    frames, _ = _select_frames(info, tag_name=tag_name)
    target = _output_path(output_filename, ".png")
    data_target = _output_path(data_filename) if data_filename else None
    with _export_directory(target) as directory:
        staged, staged_data = directory / target.name, directory / "sheet-data.json"
        args = ["--batch", *_frame_filter(frames), filename, "--scale", str(scale),
                "--sheet-type", sheet_type, "--shape-padding", str(padding)]
        if data_target:
            args += ["--data", str(staged_data), "--format", data_format]
            if list_tags:
                args.append("--list-tags")
        args += ["--sheet", str(staged)]
        await AsepriteCommand.run_command(args)
        _image_size(staged)
        files = [(staged, target)]
        if data_target:
            _read_sheet_data(staged_data, len(frames))
            files.append((staged_data, data_target))
        _publish_files(files)
    return ToolOutput(summary="Sprite sheet exported to " + ", ".join(str(path) for _, path in files), data=ExportReceipt(files=[str(path) for _, path in files]))


async def export_layers(*, filename: str = "", output_directory: str, include_hidden: bool = False) -> ToolOutput[ExportReceipt]:
    """Export layers into an exact set of newly generated PNG files.

    Args:
        filename: Source project (defaults to the active file)
        output_directory: Destination directory
        include_hidden: Include hidden layers (default False)
    """
    filename = prepare_filename(filename)
    target = _output_path(output_directory)
    with _export_directory(target / "layers.png") as directory:
        args = ["--batch"] + (["--all-layers"] if include_hidden else [])
        await AsepriteCommand.run_command([*args, "--split-layers", filename,
                                           "--save-as", str(directory / "{layer}.png")])
        produced = sorted(directory.rglob("*.png"))
        if not produced:
            raise ToolError("Aseprite exited successfully but wrote no layer PNG files")
        for path in produced:
            _image_size(path)
        files = [(path, target / path.relative_to(directory)) for path in produced]
        _publish_files(files)
    return ToolOutput(summary="Layers exported to " + ", ".join(str(path) for _, path in files), data=ExportReceipt(files=[str(path) for _, path in files]))


async def export_tag(*, filename: str = "", tag_name: str, output_filename: str, scale: int = 1) -> ToolOutput[ExportReceipt]:
    """Export an existing tag as GIF or PNG sequence.

    Args:
        filename: Source project (defaults to the active file)
        tag_name: Existing animation tag
        output_filename: Output GIF or PNG path
        scale: Nearest-neighbor scale factor, 1..64
    """
    filename = prepare_filename(filename)
    if not 1 <= scale <= 64:
        raise ToolError("scale must be between 1 and 64")
    info = await read_sprite_info(filename)
    _select_frames(info, tag_name=tag_name)
    target = _output_path(output_filename)
    with _export_directory(target) as directory:
        staged = directory / target.name
        await AsepriteCommand.run_command(["--batch", filename, "--tag", tag_name,
                                           "--scale", str(scale), "--save-as", str(staged)])
        produced = _generated_images(directory, staged)
        files = [(path, target.parent / path.name) for path in produced]
        _publish_files(files)
    return ToolOutput(summary=f"Tag '{tag_name}' exported to " + ", ".join(str(path) for _, path in files), data=ExportReceipt(files=[str(path) for _, path in files]))


def _playback_indices(count: int, direction: str) -> list[int]:
    order = list(range(count))
    if direction in ("reverse", "pingpong_reverse"):
        order.reverse()
    if direction in ("pingpong", "pingpong_reverse"):
        order += order[-2:0:-1]
    return order


def _check_static_sidecar(sidecar: Path) -> None:
    advice = "Choose a new output filename, or use emit_mcmeta='always' to replace the metadata."
    try:
        content = sidecar.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if not sidecar.is_symlink():
            return
        raise ToolError(f"Could not read existing metadata '{sidecar}'. {advice}") from exc
    except (OSError, UnicodeError) as exc:
        raise ToolError(f"Could not read existing metadata '{sidecar}': {exc}. {advice}") from exc
    try:
        metadata = json.loads(content)
    except ValueError as exc:
        raise ToolError(f"Invalid JSON metadata in '{sidecar}': {exc}. {advice}") from exc
    if not isinstance(metadata, dict):
        raise ToolError(f"Expected a JSON object in '{sidecar}'. {advice}")
    if "animation" in metadata:
        raise ToolError(f"Static PNG conflicts with existing animation metadata in '{sidecar}'. {advice}")


async def export_minecraft_texture(*, filename: str = "", output_filename: str,
                                   frame_index: FrameIndex | None = None, tag_name: str = "",
                                   emit_mcmeta: Literal["auto", "always"] = "auto") -> ToolOutput[TextureDelivery]:
    """Deliver a Java Edition texture and a temporary 8x review PNG.

    A single frame yields a canvas-sized PNG. Animation uses
    an unpadded vertical strip at the original resolution, with each source
    frame stored once. The mcmeta uses zero-based strip indexes and exact
    game ticks. Animation frame durations must be positive multiples of 50 ms.

    Args:
        filename: Source native project (defaults to the active file)
        output_filename: Original-resolution game PNG path
        frame_index: Optional single frame, 1-based; mutually exclusive with tag_name
        tag_name: Optional animation tag; otherwise exports the complete timeline
        emit_mcmeta: Auto publishes metadata for animations and preserves existing non-animation metadata for a static PNG. Always also writes empty metadata for a single frame.

    Returns:
        JSON with png, the mcmeta path published by this call (or null),
        preview_png, preview_scale and source-frame mapping.
        The review PNG expires when this stdio session ends. Animation durations
        must be positive multiples of 50 ms; no timing is silently rounded.
    """
    filename = prepare_filename(filename)
    info = await read_sprite_info(filename)
    frames, direction = _select_frames(info, frame_index, tag_name)
    durations = [info["durations_ms"][frame - 1] for frame in frames]
    metadata = {}
    if len(frames) > 1:
        for source, duration in zip(frames, durations):
            if duration <= 0 or duration % MILLISECONDS_PER_TICK:
                raise ToolError(f"Frame {source} duration {duration} ms is not an exact game tick; use set_frame_duration with a positive multiple of 50 ms")
        metadata = {"animation": {
            "width": info["width"], "height": info["height"], "interpolate": False,
            "frames": [{"index": index, "time": durations[index] // MILLISECONDS_PER_TICK}
                       for index in _playback_indices(len(frames), direction)],
        }}
    target = _output_path(output_filename, ".png")
    sidecar = Path(str(target) + ".mcmeta")
    publish_mcmeta = len(frames) > 1 or emit_mcmeta == "always"
    if not publish_mcmeta:
        _check_static_sidecar(sidecar)
    preview = None
    try:
        with _export_directory(target) as directory:
            staged, data = directory / "texture.png", directory / "sheet.json"
            await AsepriteCommand.run_command([
                "--batch", *_frame_filter(frames), filename,
                "--sheet-type", "vertical", "--data", str(data), "--format", "json-array",
                "--sheet", str(staged),
            ])
            expected_size = (info["width"], info["height"] * len(frames))
            if _image_size(staged) != expected_size:
                raise ToolError("Invalid Minecraft strip dimensions")
            sheet = _read_sheet_data(data, len(frames))
            if not isinstance(sheet["frames"], list):
                raise ToolError("Aseprite returned invalid Minecraft frame metadata")
            for index, frame in enumerate(sheet["frames"]):
                rect = {"x": 0, "y": index * info["height"], "w": info["width"], "h": info["height"]}
                if (not isinstance(frame, dict) or frame.get("frame") != rect
                        or frame.get("duration") != durations[index]
                        or frame.get("rotated") is not False or frame.get("trimmed") is not False):
                    raise ToolError("Aseprite returned an invalid Minecraft frame layout or duration")
            files = [(staged, target)]
            if publish_mcmeta:
                staged_sidecar = directory / "texture.png.mcmeta"
                staged_sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
                files.append((staged_sidecar, sidecar))
            preview = Path(get_review_directory()) / f"{target.stem}-{uuid.uuid4().hex}-8x.png"
            with Image.open(staged) as image:
                image.convert("RGBA").resize(
                    (expected_size[0] * REVIEW_SCALE, expected_size[1] * REVIEW_SCALE),
                    Image.Resampling.NEAREST,
                ).save(preview)
            _image_size(preview)
            _publish_files(files)
    except BaseException:
        if preview is not None:
            preview.unlink(missing_ok=True)
        raise
    return ToolOutput(summary="Export minecraft texture completed", data=TextureDelivery(
        png=str(target), mcmeta=str(sidecar) if publish_mcmeta else None,
        preview_png=str(preview), preview_scale=REVIEW_SCALE, preview_lifetime="session",
        frames=[{"source_frame": source, "index": index, "duration_ms": duration}
                for index, (source, duration) in enumerate(zip(frames, durations, strict=True))],
    ))


async def _snapshot_slices(filename: str, names: list[str], image: Path):
    requested = lua_escape(json.dumps(names))
    staged = lua_escape(image.as_posix())
    script = f'''
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    if #spr.frames ~= 1 then error("Slice texture export requires a single-frame project") end
    local requested = json.decode("{requested}")
    local slices, duplicate_names = {{}}, {{}}
    for _, slice in ipairs(spr.slices) do
        local name = slice.name
        if slices[name] then duplicate_names[name] = true end
        slices[name] = slice
    end
    local regions = {{}}
    for _, name in ipairs(requested) do
        if duplicate_names[name] then error("Ambiguous slice name: " .. name) end
        local slice = slices[name]
        if not slice then error("Slice not found: " .. name) end
        local bounds = slice.bounds
        if not bounds or bounds.x < 0 or bounds.y < 0
           or bounds.width < 1 or bounds.height < 1
           or bounds.x + bounds.width > spr.width or bounds.y + bounds.height > spr.height then
            error("Slice outside the canvas: " .. name)
        end
        table.insert(regions, {{bounds.x, bounds.y, bounds.x + bounds.width, bounds.y + bounds.height}})
    end
    spr:saveCopyAs("{staged}")
    print(json.encode({{size={{spr.width, spr.height}}, regions=regions}}))
    '''
    result = await AsepriteCommand.execute_lua_script_checked(script, filename)
    try:
        return json.loads(result)
    except ValueError as exc:
        raise ToolError("Aseprite returned invalid slice metadata") from exc


async def export_slices_to_minecraft(
    *,
    filename: str = "",
    output_directory: str,
    slice_names: Annotated[list[str], Field(min_length=1)],
) -> ToolOutput[list[SliceTextureDelivery]]:
    """Deliver static Minecraft Java Edition textures from named native slices.

    Each slice yields an original-size PNG and an empty .png.mcmeta. The
    source must have one frame, and output records follow the requested order.

    Args:
        filename: Source native project, defaulting to the active file.
        output_directory: Destination directory. Relative paths use the workspace.
        slice_names: Unique slice names usable as Java Edition resource file names.
    """
    if not slice_names:
        raise ToolError("Specify at least one slice name")
    if len(set(slice_names)) != len(slice_names):
        raise ToolError("Slice names must be unique")
    output_root = _output_path(output_directory)
    outputs = []
    for name in slice_names:
        if not re.fullmatch(r"[a-z0-9._-]+", name) or name in (".", "..") or isreserved(f"{name}.png"):
            raise ToolError(f"Invalid slice name for a Minecraft texture file: {name!r}")
        outputs.append((output_root / f"{name}.png", output_root / f"{name}.png.mcmeta"))
    filename = prepare_filename(filename)
    _require_distinct_paths([Path(filename), *(path for pair in outputs for path in pair)])

    deliveries = []
    try:
        with tempfile.TemporaryDirectory(prefix="aseprite-slice-export-") as directory:
            staging = Path(directory)
            snapshot = staging / "frame.png"
            metadata = await _snapshot_slices(filename, slice_names, snapshot)
            with Image.open(snapshot) as image:
                frame = image.convert("RGBA")
            regions = metadata["regions"]
            if list(frame.size) != metadata["size"] or len(regions) != len(outputs):
                raise ToolError("Aseprite returned an invalid slice snapshot")
            files = []
            for index, (name, (png, mcmeta), box) in enumerate(zip(slice_names, outputs, regions, strict=True)):
                staged_png = staging / f"slice-{index}.png"
                staged_mcmeta = staged_png.with_suffix(".png.mcmeta")
                cropped = frame.crop(tuple(box))
                cropped.save(staged_png)
                if _image_size(staged_png) != cropped.size:
                    raise ToolError(f"Invalid PNG dimensions for slice {name!r}")
                staged_mcmeta.write_text("{}\n", encoding="utf-8")
                files.extend([(staged_png, png), (staged_mcmeta, mcmeta)])
                deliveries.append({"slice_name": name, "png": str(png), "mcmeta": str(mcmeta)})
            _publish_files(files)
    except OSError as exc:
        raise ToolError(f"Could not export slices to '{output_root}': {exc}") from exc
    return ToolOutput(summary="Exported Minecraft textures from slices", data=deliveries)


async def import_image_as_layer(*, filename: str = "", image_path: str, layer_name: LayerRef,
                                frame_index: FrameIndex, x: int = 0, y: int = 0) -> ToolOutput[EditReceipt]:
    """Import an image into an explicit layer/frame of a native project.

    Args:
        filename: Target project (defaults to the active file)
        image_path: Existing source image
        layer_name: Explicit layer name or group path
        frame_index: Target frame, 1-based
        x: Image left edge, sprite-global
        y: Image top edge, sprite-global
    """
    filename = prepare_filename(filename)
    image_path = prepare_filename(image_path, anchor=False)
    script = f"""
    {EDIT_TARGET}
    {NORMALIZE_CEL}
    local spr = app.activeSprite
    local frame = require_frame(spr, {frame_index})
    local src = Image{{fromFile="{lua_escape(image_path.replace(chr(92), '/'))}"}}
    if not src then print("ERROR:Could not load image") return end
    app.transaction(function()
        local layer = require_layer(spr, {lua_layer_ref(layer_name)}, true)
        require_cel(spr, layer, {frame_index}, true)
        local cel = normalize_cel(spr, layer, frame, false)
        cel.image:drawImage(src, Point({x}, {y}))
    end)
    save_project(spr)
    """
    execution = await execute_edit_script(script, filename)
    return edit_output(f"Image {image_path} imported on '{layer_name}' frame {frame_index} in {filename}", filename, execution, frame_index)
