"""Region edits preserve source, destination and pixels outside the region."""
from conftest import run
from aseprite_mcp.tools import selection
from test_project_editing import frame_image


def test_copy_move_and_erase_regions(sprite, tmp_path):
    run(selection.copy_region(filename=sprite, layer_name="body", frame_index=1,
        x=8, y=8, width=4, height=4, dest_x=0, dest_y=0))
    image = frame_image(sprite, 1, tmp_path)
    red = (208, 70, 72, 255)
    clear = (0, 0, 0, 0)
    assert image.getpixel((0, 0)) == red
    assert image.getpixel((8, 8)) == red
    assert image.getpixel((4, 0)) == clear
    run(selection.move_region(filename=sprite, layer_name="body", frame_index=1,
        x=0, y=0, width=4, height=4, dest_x=24, dest_y=24))
    image = frame_image(sprite, 1, tmp_path)
    assert image.getpixel((0, 0)) == clear
    assert image.getpixel((24, 24)) == red
    assert image.getpixel((8, 8)) == red
    run(selection.erase_region(filename=sprite, layer_name="body", frame_index=1,
        x=24, y=24, width=4, height=4))
    image = frame_image(sprite, 1, tmp_path)
    assert image.getpixel((24, 24)) == clear
    assert image.getpixel((8, 8)) == red
    result = run(selection.erase_color(filename=sprite, layer_name="body", frame_index=1,
        color="#D04648", tolerance=0))
    assert "Erased 256" in result
    assert frame_image(sprite, 1, tmp_path).getbbox() is None
