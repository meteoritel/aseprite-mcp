"""Shared input contracts and the successful MCP result envelope."""

import inspect
import re
from typing import Annotated, Generic, TypedDict, TypeVar

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, ConfigDict, Field, StrictInt, with_config

T = TypeVar("T")


class ToolOutput(BaseModel, Generic[T]):
    summary: str
    data: T


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Character = Annotated[str, Field(min_length=1, max_length=1)]
HexColor = Annotated[str, Field(pattern=r"^\s*#*(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\s*$")]
Palette = dict[Character, HexColor]
PositiveInt = Annotated[int, Field(ge=1)]
NonnegativeInt = Annotated[int, Field(ge=0)]
Byte = Annotated[int, Field(ge=0, le=255)]
FrameIndex = Annotated[int, Field(ge=1, description="External frame number, starting at 1.")]
LayerPath = Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]
LayerRef = Annotated[str | LayerPath, Field(description="A name or group path, or exact path segments from get_sprite_info. Use an array to distinguish a nested layer from a name containing '/'.")]


@with_config(ConfigDict(extra="forbid"))
class Point(TypedDict):
    x: Annotated[StrictInt, Field(description="Pixel x; sprite-global except for draw_on_tile, where it is tile-local.")]
    y: Annotated[StrictInt, Field(description="Pixel y; sprite-global except for draw_on_tile, where it is tile-local.")]


@with_config(ConfigDict(extra="forbid"))
class Pixel(Point):
    color: HexColor


@with_config(ConfigDict(extra="forbid"))
class TilePlacement(TypedDict):
    col: Annotated[StrictInt, Field(description="Tile grid column, starting at 0; not a pixel coordinate.")]
    row: Annotated[StrictInt, Field(description="Tile grid row, starting at 0; not a pixel coordinate.")]
    tile_index: Annotated[int, Field(ge=0)]


ColorMapping = with_config(ConfigDict(extra="forbid"))(
    TypedDict("ColorMapping", {"from": HexColor, "to": HexColor})
)


class Region(ContractModel):
    x: int = 0
    y: int = 0
    width: PositiveInt
    height: PositiveInt


class SpriteMapEdit(ContractModel):
    layer_name: LayerRef
    frame_index: FrameIndex
    rows: Annotated[list[str], Field(min_length=1, description="Equal-width pixel rows, top to bottom.")]
    palette: Annotated[Palette, Field(description="Single-character keys mapped to #RGB, #RGBA, #RRGGBB or #RRGGBBAA. The transparent character is reserved.")]
    x: int = Field(default=0, description="Sprite-global x of the grid origin; may be negative for clipping.")
    y: int = Field(default=0, description="Sprite-global y of the grid origin; may be negative for clipping.")
    transparent: Character = Field(default=".", description="Character for cells to skip or erase.")
    mirror_x: bool = Field(default=False, description="Reflect within the grid width. Different colors at the same reflected position are an error.")
    mirror_y: bool = Field(default=False, description="Reflect within the grid height. Different colors at the same reflected position are an error.")
    erase_transparent: bool = Field(default=False, description="Erase transparent cells. By default they leave the current pixels in place.")
    create_if_missing: bool = Field(default=True, description="Create a missing top-level image layer or cel. Nested layers and target frames must already exist.")


class ContractTool(Tool):
    """Keep SDK execution while rejecting fields the published schema does not accept."""

    @classmethod
    def from_function(cls, fn, **kwargs):
        tool = super().from_function(fn, **kwargs)
        tool.parameters["additionalProperties"] = False
        _, _, arguments = (inspect.getdoc(fn) or "").partition("\nArgs:")
        arguments = re.split(r"\n(?=\S)", arguments)[0]
        for entry in re.split(r"\n(?=    \w+(?:\([^)]*\))?:)", arguments.strip("\n")):
            name, separator, description = entry.strip().partition(":")
            name = name.split("(")[0].strip()
            field = tool.parameters.get("properties", {}).get(name)
            if separator and field is not None:
                existing = field.get("description", "")
                description = " ".join(description.split())
                field["description"] = description + (" " + existing if existing and existing != description else "")
        return tool

    def validate_example(self, arguments):
        unknown = arguments.keys() - self.parameters.get("properties", {}).keys()
        if unknown:
            raise ValueError(f"{self.name} example has unknown fields: {sorted(unknown)}")
        self.fn_metadata.arg_model.model_validate(arguments)

    async def run(self, arguments, context, convert_result=False):
        unknown = sorted(arguments.keys() - self.parameters.get("properties", {}).keys())
        if unknown:
            fields = ", ".join(self.parameters.get("properties", {}))
            raise ToolError(f"Error executing tool {self.name}: Unknown argument(s): {', '.join(unknown)}. Accepted fields: {fields}")
        return await super().run(arguments, context, convert_result=convert_result)
