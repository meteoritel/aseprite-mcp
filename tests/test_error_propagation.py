"""Invalid tool inputs raise ToolError and retain actionable context."""

from conftest import failure
from conftest import BASE, run

from aseprite_mcp.tools import (
    animation,
    canvas,
    drawing,
    export,
    palette,
    pixel_read,
    quality,
    scene,
    transform,
)




# --- issue #15 reproduction table: each must now fail loudly ---

def test_set_layer_visibility_missing_layer(sprite):
    failure(animation.set_layer_visibility(filename=sprite, layer_name="NOT_A_LAYER", visible=False))


def test_set_frame_duration_out_of_range(sprite):
    failure(canvas.set_frame_duration(filename=sprite, frame_index=99, duration_ms=50))


def test_set_tag_range_out_of_bounds(sprite):
    failure(animation.set_tag(filename=sprite, name="bad_tag", from_frame=5, to_frame=99))


def test_remap_colors_missing_layer(sprite):
    failure(palette.remap_colors_in_cel_range(filename=sprite, layer_name="NOSUCHLAYER", start_frame=1, end_frame=1, mappings=[{"from": "#D04648", "to": "#000000"}]))


def test_ensure_layers_present_all_missing(sprite):
    failure(quality.ensure_layers_present(filename=sprite, layer_names=["MISSING"]))


def test_export_sprite_unwritable_format(sprite):
    # Aseprite exits 0 but writes nothing for format="json".
    failure(export.export_sprite(filename=sprite, output_filename=f"{BASE}/err_out", format="json"))


def test_export_tag_missing_tag(sprite):
    # --tag silently exports *all* frames (exit 0) for an unknown tag, so the
    # tool must validate the tag rather than report a fabricated tag export.
    failure(export.export_tag(filename=sprite, tag_name="NO_SUCH_TAG", output_filename=f"{BASE}/err_tag.gif"))


def test_export_spritesheet_missing_tag(sprite):
    failure(export.export_spritesheet(filename=sprite, output_filename=f"{BASE}/err_sheet.png", sheet_type="horizontal", data_filename="", scale=1, padding=0, tag_name="NO_SUCH_TAG"))


# --- readers surfaced a hard error as data (read as success); now fail loudly ---

def test_get_pixel_color_missing_layer(sprite):
    failure(pixel_read.get_pixel_color(filename=sprite, x=0, y=0, layer_name="NO_SUCH_LAYER", frame_index=1))


def test_get_pixels_rect_missing_layer(sprite):
    failure(pixel_read.get_pixels_rect(filename=sprite, x=0, y=0, width=4, height=4, layer_name="NO_SUCH_LAYER", frame_index=1))


# --- copy_layers_between_sprites: all-missing fails; partial surfaces skips ---

def test_copy_layers_all_missing_fails(sprite, base_dir):
    target = f"{base_dir}/copy_target.aseprite"
    run(canvas.create_canvas(width=16, height=16, filename=target))
    failure(scene.copy_layers_between_sprites(source_filename=sprite, target_filename=target, layer_names=["BOGUS"]))


def test_copy_layers_partial_surfaces_skipped(sprite, base_dir):
    target = f"{base_dir}/copy_target2.aseprite"
    run(canvas.create_canvas(width=16, height=16, filename=target))
    result = run(scene.copy_layers_between_sprites(source_filename=sprite, target_filename=target, layer_names=["body", "BOGUS"]))
    assert "skipped missing layers" in result and "BOGUS" in result, result


# --- new guards added alongside the conversion ---

def test_crop_fully_outside_canvas_rejected(sprite):
    failure(transform.crop_canvas(filename=sprite, x=999, y=999, width=10, height=10))


def test_flip_missing_layer(sprite):
    failure(transform.flip_layer(filename=sprite, layer_name="NO_SUCH_LAYER", frame_index=1))


def test_draw_line_missing_layer(sprite):
    # create_if_missing is off here: the drawing tools now *create* a missing
    # top-level layer by default, so the strict path has to be requested to
    # keep testing that a missing layer fails loudly.
    failure(drawing.draw_line_at(filename=sprite, layer_name="NO_SUCH_LAYER", frame_index=1, x1=0, y1=0, x2=5, y2=5, color="#ffffff", thickness=1, create_if_missing=False))
