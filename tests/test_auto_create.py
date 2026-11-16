"""Drawing creates top-level targets and reports invalid layers or frames."""
import json

from conftest import failure, run

from aseprite_mcp.tools import animation, drawing, pixel_read




def sprite_info(path: str) -> dict:
    return json.loads(run(animation.get_sprite_info(filename=path)))


def layer_names(info: dict) -> list[str]:
    return [layer["name"] for layer in info["layers"]]


def rgba(pixel_result: str) -> tuple[int, int, int, int]:
    s = str(pixel_result)
    return (int(s.split("r=")[1].split(",")[0]),
            int(s.split("g=")[1].split(",")[0]),
            int(s.split("b=")[1].split(",")[0]),
            int(s.split("a=")[1].split(")")[0]))


def test_drawing_auto_creates_missing_layer(sprite):
    # "coin" does not exist yet: create_if_missing (default) must build the
    # layer *and* the cel, and the pixels must really land on it.
    assert "coin" not in layer_names(sprite_info(sprite))
    run(drawing.draw_circle_at(
        filename=sprite, layer_name="coin", frame_index=1,
        center_x=16, center_y=16, radius=6, color="#FFCC00", fill=True,
    ))
    assert "coin" in layer_names(sprite_info(sprite))
    assert rgba(run(pixel_read.get_pixel_color(
        filename=sprite, x=16, y=16, layer_name="coin", frame_index=1,
    ))) == (255, 204, 0, 255)


def test_group_path_is_never_auto_created(sprite):
    # A "/" name is a group path, not a new top-level layer: auto-create must
    # refuse rather than fabricate a layer literally called "grp/inner".
    result = failure(drawing.draw_circle_at(
        filename=sprite, layer_name="grp/inner", frame_index=1,
        center_x=8, center_y=8, radius=3,
    ))
    assert "not found" in result, result
    assert "grp/inner" not in layer_names(sprite_info(sprite))


def test_missing_layer_error_lists_existing_layers(sprite):
    # create_if_missing=False keeps the old strict behaviour, but the message
    # must carry the sprite's state so the caller can fix it in one step.
    result = failure(drawing.draw_line_at(
        filename=sprite, layer_name="NO_SUCH_LAYER", frame_index=1,
        x1=0, y1=0, x2=5, y2=5, create_if_missing=False,
    ))
    assert "Existing layers:" in result, result
    assert "body" in result, result


def test_out_of_range_frame_error_reports_frame_count(sprite):
    result = failure(drawing.draw_circle_at(
        filename=sprite, layer_name="body", frame_index=99,
        center_x=8, center_y=8, radius=3,
    ))
    assert "frame" in result.lower() and "1-based" in result, result


def test_copy_cel_auto_creates_target_frame(sprite):
    before = sprite_info(sprite)
    assert before["frames"] == 1, before["frames"]  # single-frame sprite
    result = run(animation.copy_cel(
        filename=sprite, layer_name="body", source_frame=1, target_frame=3,
    ))
    after = sprite_info(sprite)
    assert after["frames"] == 3, after["frames"]
    assert "2 frame(s) auto-created" in result, result


def test_copy_cel_can_refuse_frame_growth(sprite):
    # The sprite now has 3 frames; asking for frame 5 with the feature off
    # must fail loudly and point at add_frame.
    result = failure(animation.copy_cel(
        filename=sprite, layer_name="body", source_frame=1, target_frame=5,
        create_target_frame=False,
    ))
    assert "add_frame" in result, result
    assert sprite_info(sprite)["frames"] == 1
