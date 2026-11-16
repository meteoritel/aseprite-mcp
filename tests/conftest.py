"""Independent native projects and a deterministic bitmap font for workflows."""
import json
from pathlib import Path
import sys
import uuid

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aseprite_mcp.core import state
from aseprite_mcp.tools import canvas, drawing
from support import FIXTURE_GLYPHS, run


@pytest.fixture
def new_sprite(tmp_path):
    def create(width=16, height=16):
        path = str(tmp_path / f"{uuid.uuid4().hex}.aseprite")
        run(canvas.create_canvas(width, height, filename=path))
        assert Path(path).is_file()
        return path
    return create


@pytest.fixture
def sprite(new_sprite):
    path = new_sprite(32, 32)
    run(drawing.draw_rectangle_at(
        filename=path, layer_name="body", frame_index=1,
        x=8, y=8, width=16, height=16, color="#D04648", fill=True,
    ))
    return path


@pytest.fixture(scope="session")
def bitmap_font(tmp_path_factory):
    directory = tmp_path_factory.mktemp("bitmap-font")
    cell_width, cell_height, ascent = 4, 6, 5
    chars = "ABO"
    sheet = Image.new("RGBA", (cell_width * len(chars), cell_height))
    for index, char in enumerate(chars):
        for y, row in enumerate(FIXTURE_GLYPHS[char]):
            for x, cell in enumerate(row):
                if cell == "#":
                    sheet.putpixel((index * cell_width + x, y), (255, 255, 255, 255))
    sheet.save(directory / "sheet.png")
    (directory / "font.json").write_text(json.dumps({
        "name": "fixture", "letter_gap": 1, "space_width": 2,
        "sheets": [{"file": "sheet.png", "cell_w": cell_width,
                    "cell_h": cell_height, "ascent": ascent, "chars": [chars]}],
    }), encoding="utf-8")
    return str(directory)


@pytest.fixture(autouse=True)
def reset_session():
    state._active_file = None
    yield
    state._active_file = None
    state.cleanup_review_directory()
