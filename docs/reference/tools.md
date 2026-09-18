# 工具清单（自动生成）

> ⚠️ 本文件由 `scripts/gen_tool_reference.py` 解析源码 AST 生成，**请勿手改**。
> 新增或修改工具后重新生成：`uv run python scripts/gen_tool_reference.py`
> 生成基线：`586420f`

共 **116** 个 `@mcp.tool()` 工具，分布在 **20** 个模块。

参数列中 `*` 之后的是 keyword-only 参数；`filename` 通常可省略（回退到会话的活跃文件）。

## 模块索引

| 模块 | 工具数 | 说明 | 开发者文档 |
|---|---:|---|---|
| [`canvas.py`](#canvaspy) | 7 | 画布创建、图层/帧的增删与活跃状态设置 | [04-layers-and-canvas.md](../04-layers-and-canvas.md) |
| [`drawing.py`](#drawingpy) | 14 | 像素、线、矩形、圆、椭圆、多边形、路径、填充、渐变 | [03-painting.md](../03-painting.md) |
| [`export.py`](#exportpy) | 7 | PNG/GIF/精灵表/分层/按 tag 导出与图片导入 | [07-output.md](../07-output.md) |
| [`animation.py`](#animationpy) | 24 | 帧、cel、tag、带缓动的补间与传播 | [05-animation.md](../05-animation.md) |
| [`preview.py`](#previewpy) | 2 | 本地 HTTP 预览服务器 | [07-output.md](../07-output.md) |
| [`palette.py`](#palettepy) | 8 | 调色板读写、复古预设、色阶生成、量化、色彩模式 | [03-painting.md](../03-painting.md) |
| [`scene.py`](#scenepy) | 1 | 在两个精灵文件之间复制图层 | [04-layers-and-canvas.md](../04-layers-and-canvas.md) |
| [`guide.py`](#guidepy) | 1 | 返回面向 LLM 的动画工作流指南文本 | [05-animation.md](../05-animation.md) |
| [`quality.py`](#qualitypy) | 4 | 动画一致性校验与归一化（结构校验器，非评分器） | [08-inspection-and-quality.md](../08-inspection-and-quality.md) |
| [`pixel_read.py`](#pixel_readpy) | 4 | 单 cel 与合成后的像素读取 | [08-inspection-and-quality.md](../08-inspection-and-quality.md) |
| [`transform.py`](#transformpy) | 4 | 翻转、旋转、缩放、裁剪 | [03-painting.md](../03-painting.md) |
| [`layers.py`](#layerspy) | 7 | 图层删除、重命名、复制、排序、混合模式、合并、展平 | [04-layers-and-canvas.md](../04-layers-and-canvas.md) |
| [`selection.py`](#selectionpy) | 4 | 矩形区域的移动/复制/擦除，以及按颜色擦除 | [03-painting.md](../03-painting.md) |
| [`fx.py`](#fxpy) | 5 | 手写逐像素特效：描边、换色、HSL 调整、有序抖动 | [06-effects-and-tilemap.md](../06-effects-and-tilemap.md) |
| [`analysis.py`](#analysispy) | 3 | 洋葱皮渲染、帧差异、颜色统计 | [08-inspection-and-quality.md](../08-inspection-and-quality.md) |
| [`slices.py`](#slicespy) | 5 | 命名区域、九宫格中心、轴心点 | [06-effects-and-tilemap.md](../06-effects-and-tilemap.md) |
| [`tilemap.py`](#tilemappy) | 5 | tilemap 图层、tileset 编辑、瓦片摆放与读取 | [06-effects-and-tilemap.md](../06-effects-and-tilemap.md) |
| [`script.py`](#scriptpy) | 1 | 任意 Aseprite Lua 的逃生舱 | [01-lua-bridge.md](../01-lua-bridge.md) |
| [`text.py`](#textpy) | 3 | 用 bitmap 或 TrueType 字体绘制与测量文本 | [03-painting.md](../03-painting.md) |
| [`native_fx.py`](#native_fxpy) | 7 | Aseprite 原生滤镜包装（app.command.*） | [06-effects-and-tilemap.md](../06-effects-and-tilemap.md) |

## `canvas.py`

画布创建、图层/帧的增删与活跃状态设置

**7 个工具**

### `create_canvas`

```text
create_canvas(width: int, height: int, *, filename: str) -> str
```

源码：[`aseprite_mcp/tools/canvas.py:9`](../../aseprite_mcp/tools/canvas.py#L9)

Create a new Aseprite canvas with specified dimensions.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `width` | `int` | **必填** | Width of the canvas in pixels |
| `height` | `int` | **必填** | Height of the canvas in pixels |
| `filename` | `str` | **必填** | REQUIRED. Absolute path for the output file, e.g. "D:/art/sprites/coin.aseprite". Relative paths are rejected, so the canvas can never silently land in the server's own folder. |

### `add_layer`

```text
add_layer(filename: str = '', *, layer_name: str, group: str = '') -> str
```

源码：[`aseprite_mcp/tools/canvas.py:51`](../../aseprite_mcp/tools/canvas.py#L51)

Add a new layer to the Aseprite file.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Name of the new layer |
| `group` | `str` | `''` | Optional group to place the new layer inside, by name or "group/subgroup" path (default: top level) |

### `add_group`

```text
add_group(filename: str = '', *, group_name: str, parent_group: str = '') -> str
```

源码：[`aseprite_mcp/tools/canvas.py:98`](../../aseprite_mcp/tools/canvas.py#L98)

Add a new, empty group layer. Combine with add_layer(group=...) / duplicate_layer(group=...) to build a grouped layer structure.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `group_name` | `str` | **必填** | Name of the new group |
| `parent_group` | `str` | `''` | Optional existing group to nest the new group inside, by name or "group/subgroup" path (default: top level) |

### `add_frame`

```text
add_frame(filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/canvas.py:147`](../../aseprite_mcp/tools/canvas.py#L147)

Add a new frame to the Aseprite file.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |

### `set_frame`

```text
set_frame(filename: str = '', *, frame_index: int) -> str
```

源码：[`aseprite_mcp/tools/canvas.py:177`](../../aseprite_mcp/tools/canvas.py#L177)

Set the active frame by index (1-based).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |

### `set_frame_duration`

```text
set_frame_duration(filename: str = '', *, frame_index: int, duration_ms: int) -> str
```

源码：[`aseprite_mcp/tools/canvas.py:213`](../../aseprite_mcp/tools/canvas.py#L213)

Set the duration of a frame in milliseconds.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `duration_ms` | `int` | **必填** | Duration in milliseconds |

### `set_layer`

```text
set_layer(filename: str = '', *, layer_name: str, create_if_missing: bool = False) -> str
```

源码：[`aseprite_mcp/tools/canvas.py:252`](../../aseprite_mcp/tools/canvas.py#L252)

Set the active layer by name.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to activate |
| `create_if_missing` | `bool` | `False` | Create layer if it does not exist |

## `drawing.py`

像素、线、矩形、圆、椭圆、多边形、路径、填充、渐变

**14 个工具**

### `draw_pixels`

```text
draw_pixels(*, filename: str = '', pixels: List[Dict[str, Any]]) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:16`](../../aseprite_mcp/tools/drawing.py#L16)

Draw pixels on the canvas with specified colors.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Name of the Aseprite file to modify (optional; defaults to the session's active file) |
| `pixels` | `List[Dict[str, Any]]` | **必填** | List of pixel data, each containing: {"x": int, "y": int, "color": str} where color is a hex code like "#FF0000" |

### `draw_line`

```text
draw_line(x1: int, y1: int, x2: int, y2: int, color: str = '#000000', thickness: int = 1, filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/drawing.py:85`](../../aseprite_mcp/tools/drawing.py#L85)

Draw a line on the canvas.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `x1` | `int` | **必填** | Starting x coordinate |
| `y1` | `int` | **必填** | Starting y coordinate |
| `x2` | `int` | **必填** | Ending x coordinate |
| `y2` | `int` | **必填** | Ending y coordinate |
| `color` | `str` | `'#000000'` | Hex color code (default: "#000000") |
| `thickness` | `int` | `1` | Line thickness in pixels (default: 1) |
| `filename` | `str` | `''` | Name of the Aseprite file to modify (optional; defaults to the session's active file) |

### `draw_rectangle`

```text
draw_rectangle(x: int, y: int, width: int, height: int, color: str = '#000000', fill: bool = False, filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/drawing.py:170`](../../aseprite_mcp/tools/drawing.py#L170)

Draw a rectangle on the canvas.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `x` | `int` | **必填** | Top-left x coordinate |
| `y` | `int` | **必填** | Top-left y coordinate |
| `width` | `int` | **必填** | Width of the rectangle in pixels (must be > 0) |
| `height` | `int` | **必填** | Height of the rectangle in pixels (must be > 0) |
| `color` | `str` | `'#000000'` | Hex color code (default: "#000000") |
| `fill` | `bool` | `False` | Whether to fill the rectangle (default: False) |
| `filename` | `str` | `''` | Name of the Aseprite file to modify (optional; defaults to the session's active file) |

### `fill_area`

```text
fill_area(x: int, y: int, color: str = '#000000', filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/drawing.py:234`](../../aseprite_mcp/tools/drawing.py#L234)

Fill an area with color using the paint bucket tool.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `x` | `int` | **必填** | X coordinate to fill from |
| `y` | `int` | **必填** | Y coordinate to fill from |
| `color` | `str` | `'#000000'` | Hex color code (default: "#000000") |
| `filename` | `str` | `''` | Name of the Aseprite file to modify (optional; defaults to the session's active file) |

### `draw_circle`

```text
draw_circle(center_x: int, center_y: int, radius: int, color: str = '#000000', fill: bool = False, filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/drawing.py:287`](../../aseprite_mcp/tools/drawing.py#L287)

Draw a circle on the canvas.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `center_x` | `int` | **必填** | X coordinate of circle center |
| `center_y` | `int` | **必填** | Y coordinate of circle center |
| `radius` | `int` | **必填** | Radius of the circle in pixels |
| `color` | `str` | `'#000000'` | Hex color code (default: "#000000") |
| `fill` | `bool` | `False` | Whether to fill the circle (default: False) |
| `filename` | `str` | `''` | Name of the Aseprite file to modify (optional; defaults to the session's active file) |

### `draw_pixels_at`

```text
draw_pixels_at(*, filename: str = '', layer_name: str, frame_index: int, pixels: List[Dict[str, Any]], create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:346`](../../aseprite_mcp/tools/drawing.py#L346)

Draw pixels on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Name of the Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `pixels` | `List[Dict[str, Any]]` | **必填** | List of pixel data with x/y/color |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only) and cel if they don't exist |

### `draw_line_at`

```text
draw_line_at(*, filename: str = '', layer_name: str, frame_index: int, x1: int, y1: int, x2: int, y2: int, color: str = '#000000', thickness: int = 1, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:423`](../../aseprite_mcp/tools/drawing.py#L423)

Draw a line on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `x1` | `int` | **必填** | The x coordinate of the first point of the line. |
| `y1` | `int` | **必填** | The y coordinate of the first point of the line. |
| `x2` | `int` | **必填** | The x coordinate of the second point of the line. |
| `y2` | `int` | **必填** | The y coordinate of the second point of the line. |
| `color` | `str` | `'#000000'` | The color to draw the line with. Defaults to "#000000". |
| `thickness` | `int` | `1` | The thickness of the line. Defaults to 1. |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `draw_rectangle_at`

```text
draw_rectangle_at(*, filename: str = '', layer_name: str, frame_index: int, x: int, y: int, width: int, height: int, color: str = '#000000', fill: bool = False, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:527`](../../aseprite_mcp/tools/drawing.py#L527)

Draw a rectangle on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `x` | `int` | **必填** | The x coordinate of the top-left corner of the rectangle. |
| `y` | `int` | **必填** | The y coordinate of the top-left corner of the rectangle. |
| `width` | `int` | **必填** | The width of the rectangle. |
| `height` | `int` | **必填** | The height of the rectangle. |
| `color` | `str` | `'#000000'` | The color to draw the rectangle with. Defaults to "#000000". |
| `fill` | `bool` | `False` | Whether to fill the rectangle. Defaults to False. |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `draw_circle_at`

```text
draw_circle_at(*, filename: str = '', layer_name: str, frame_index: int, center_x: int, center_y: int, radius: int, color: str = '#000000', fill: bool = False, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:609`](../../aseprite_mcp/tools/drawing.py#L609)

Draw a circle on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `center_x` | `int` | **必填** | The x coordinate of the center of the circle. |
| `center_y` | `int` | **必填** | The y coordinate of the center of the circle. |
| `radius` | `int` | **必填** | The radius of the circle. |
| `color` | `str` | `'#000000'` | The color to draw the circle with. Defaults to "#000000". |
| `fill` | `bool` | `False` | Whether to fill the circle. Defaults to False. |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `fill_area_at`

```text
fill_area_at(*, filename: str = '', layer_name: str, frame_index: int, x: int, y: int, color: str = '#000000', create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:688`](../../aseprite_mcp/tools/drawing.py#L688)

Fill an area on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `x` | `int` | **必填** | The x coordinate of the point to start filling from. |
| `y` | `int` | **必填** | The y coordinate of the point to start filling from. |
| `color` | `str` | `'#000000'` | The color to fill the area with. Defaults to "#000000". |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `draw_polygon`

```text
draw_polygon(*, filename: str = '', layer_name: str, frame_index: int, points: List[Dict[str, int]], color: str = '#000000', fill: bool = False, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:759`](../../aseprite_mcp/tools/drawing.py#L759)

Draw a polygon on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `points` | `List[Dict[str, int]]` | **必填** | The list of points to draw the polygon. |
| `color` | `str` | `'#000000'` | The color to draw the polygon with. Defaults to "#000000". |
| `fill` | `bool` | `False` | Whether to fill the polygon. Defaults to False. |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `draw_path`

```text
draw_path(*, filename: str = '', layer_name: str, frame_index: int, points: List[Dict[str, int]], color: str = '#000000', thickness: int = 1, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:886`](../../aseprite_mcp/tools/drawing.py#L886)

Draw a path using a polyline on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `points` | `List[Dict[str, int]]` | **必填** | The points to draw the path with. |
| `color` | `str` | `'#000000'` | The color to draw the path with. Defaults to "#000000". |
| `thickness` | `int` | `1` | The thickness of the path. Defaults to 1. |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `apply_gradient_rect`

```text
apply_gradient_rect(*, filename: str = '', layer_name: str, frame_index: int, x: int, y: int, width: int, height: int, color_start: str, color_end: str, horizontal: bool = True, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:986`](../../aseprite_mcp/tools/drawing.py#L986)

Apply a linear gradient fill to a rectangle.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to draw on. |
| `frame_index` | `int` | **必填** | The index of the frame to draw on. |
| `x` | `int` | **必填** | The x coordinate of the rectangle to draw on. |
| `y` | `int` | **必填** | The y coordinate of the rectangle to draw on. |
| `width` | `int` | **必填** | The width of the rectangle to draw on. |
| `height` | `int` | **必填** | The height of the rectangle to draw on. |
| `color_start` | `str` | **必填** | The start color of the gradient. |
| `color_end` | `str` | **必填** | The end color of the gradient. |
| `horizontal` | `bool` | `True` | Whether to draw the gradient horizontally. Defaults to True. |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist. Defaults to True. |

### `draw_ellipse_at`

```text
draw_ellipse_at(*, filename: str = '', layer_name: str, frame_index: int, center_x: int, center_y: int, radius_x: int, radius_y: int, color: str = '#000000', fill: bool = False, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/drawing.py:1084`](../../aseprite_mcp/tools/drawing.py#L1084)

Draw an ellipse on a specific layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to draw on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `center_x` | `int` | **必填** | Ellipse center x |
| `center_y` | `int` | **必填** | Ellipse center y |
| `radius_x` | `int` | **必填** | Horizontal radius in pixels |
| `radius_y` | `int` | **必填** | Vertical radius in pixels |
| `color` | `str` | `'#000000'` | Hex color code (default "#000000") |
| `fill` | `bool` | `False` | Fill the ellipse instead of outlining it |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only) and cel if they don't exist |

## `export.py`

PNG/GIF/精灵表/分层/按 tag 导出与图片导入

**7 个工具**

### `export_sprite`

```text
export_sprite(*, filename: str = '', output_filename: str, format: str = 'png') -> str
```

源码：[`aseprite_mcp/tools/export.py:9`](../../aseprite_mcp/tools/export.py#L9)

Export the Aseprite file to another format.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Name of the Aseprite file to export (optional; defaults to the session's active file) |
| `output_filename` | `str` | **必填** | Name of the output file |
| `format` | `str` | `'png'` | Output format (default: "png", can be "png", "gif", "jpg", etc.) |

### `copy_sprite`

```text
copy_sprite(*, filename: str = '', output_filename: str, overwrite: bool = False) -> str
```

源码：[`aseprite_mcp/tools/export.py:58`](../../aseprite_mcp/tools/export.py#L58)

Copy a sprite to a new Aseprite file.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Name of the Aseprite file to copy (optional; defaults to the session's active file) |
| `output_filename` | `str` | **必填** | Name of the output .aseprite file |
| `overwrite` | `bool` | `False` | Whether to overwrite if output exists |

### `export_frame`

```text
export_frame(*, filename: str = '', frame_index: int, output_filename: str, scale: int = 1) -> str
```

源码：[`aseprite_mcp/tools/export.py:99`](../../aseprite_mcp/tools/export.py#L99)

Export a single frame as a PNG, optionally scaled up. Use this for visual feedback while drawing: export at scale 8-10 and open the PNG to inspect the result, then keep iterating.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to export (optional; defaults to the session's active file) |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `output_filename` | `str` | **必填** | Output PNG path |
| `scale` | `int` | `1` | Integer nearest-neighbor scale factor (default 1) |

### `export_spritesheet`

```text
export_spritesheet(*, filename: str = '', output_filename: str, sheet_type: str = 'horizontal', data_filename: str = '', scale: int = 1, padding: int = 0, tag_name: str = '', data_format: str = 'json-array', list_tags: bool = False) -> str
```

源码：[`aseprite_mcp/tools/export.py:152`](../../aseprite_mcp/tools/export.py#L152)

Export frames as a sprite sheet, optionally with a JSON data file.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to export (optional; defaults to the session's active file) |
| `output_filename` | `str` | **必填** | Output sheet image path (PNG) |
| `sheet_type` | `str` | `'horizontal'` | Layout: "horizontal", "vertical", "rows", "columns", or "packed" |
| `data_filename` | `str` | `''` | Optional path for a JSON metadata file |
| `scale` | `int` | `1` | Integer scale factor applied before packing (default 1) |
| `padding` | `int` | `0` | Padding in pixels between frames (default 0) |
| `tag_name` | `str` | `''` | Only include frames of this animation tag (default: all frames) |
| `data_format` | `str` | `'json-array'` | JSON format for the data file: "json-array" (default) or "json-hash" |
| `list_tags` | `bool` | `False` | Include animation tag metadata in the JSON data file (default: False) |

### `export_layers`

```text
export_layers(*, filename: str = '', output_directory: str, include_hidden: bool = False) -> str
```

源码：[`aseprite_mcp/tools/export.py:252`](../../aseprite_mcp/tools/export.py#L252)

Export each layer as its own PNG file named <layer>.png.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to export (optional; defaults to the session's active file) |
| `output_directory` | `str` | **必填** | Directory for the per-layer PNGs (created if missing) |
| `include_hidden` | `bool` | `False` | Also export hidden layers (default False) |

### `export_tag`

```text
export_tag(*, filename: str = '', tag_name: str, output_filename: str, scale: int = 1) -> str
```

源码：[`aseprite_mcp/tools/export.py:292`](../../aseprite_mcp/tools/export.py#L292)

Export the frames of an animation tag as a GIF or PNG sequence.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to export (optional; defaults to the session's active file) |
| `tag_name` | `str` | **必填** | Animation tag to export |
| `output_filename` | `str` | **必填** | Output path; .gif gives an animation, .png a sequence |
| `scale` | `int` | `1` | Integer scale factor (default 1) |

### `import_image_as_layer`

```text
import_image_as_layer(*, filename: str = '', image_path: str, layer_name: str, frame_index: int = 1, x: int = 0, y: int = 0) -> str
```

源码：[`aseprite_mcp/tools/export.py:351`](../../aseprite_mcp/tools/export.py#L351)

Import an image file (PNG, etc.) into a layer of the sprite. Useful for bringing in reference images or composing pre-made parts. The layer is created if it does not exist. Works best when the sprite is in RGB color mode.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `image_path` | `str` | **必填** | Image file to import |
| `layer_name` | `str` | **必填** | Layer to place the image on |
| `frame_index` | `int` | `1` | Frame index starting at 1 (default 1) |
| `x` | `int` | `0` | X position for the image's top-left corner (default 0) |
| `y` | `int` | `0` | Y position for the image's top-left corner (default 0) |

## `animation.py`

帧、cel、tag、带缓动的补间与传播

**24 个工具**

### `add_frames`

```text
add_frames(filename: str = '', *, count: int, duration_ms: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:8`](../../aseprite_mcp/tools/animation.py#L8)

Add multiple frames to a sprite and optionally set their duration.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `count` | `int` | **必填** | Number of frames to add |
| `duration_ms` | `int \| None` | `None` | Optional duration for each new frame in milliseconds |

### `set_frame_duration_all`

```text
set_frame_duration_all(filename: str = '', *, duration_ms: int) -> str
```

源码：[`aseprite_mcp/tools/animation.py:48`](../../aseprite_mcp/tools/animation.py#L48)

Set the duration of all frames in milliseconds.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `duration_ms` | `int` | **必填** | Duration in milliseconds |

### `set_layer_visibility`

```text
set_layer_visibility(filename: str = '', *, layer_name: str, visible: bool = True) -> str
```

源码：[`aseprite_mcp/tools/animation.py:81`](../../aseprite_mcp/tools/animation.py#L81)

Set layer visibility by name.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `visible` | `bool` | `True` | Whether the layer should be visible |

### `set_layer_opacity`

```text
set_layer_opacity(filename: str = '', *, layer_name: str, opacity: int) -> str
```

源码：[`aseprite_mcp/tools/animation.py:118`](../../aseprite_mcp/tools/animation.py#L118)

Set layer opacity by name (0-255).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `opacity` | `int` | **必填** | Opacity value 0-255 |

### `get_sprite_info`

```text
get_sprite_info(filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/animation.py:156`](../../aseprite_mcp/tools/animation.py#L156)

Return sprite info as JSON string (size, color mode, frame durations, layers, tags).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to inspect (optional; defaults to the session's active file) |

### `duplicate_frame_range`

```text
duplicate_frame_range(filename: str = '', *, start_frame: int, end_frame: int, times: int = 1) -> str
```

源码：[`aseprite_mcp/tools/animation.py:222`](../../aseprite_mcp/tools/animation.py#L222)

Duplicate a frame range and append copies to the end.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `start_frame` | `int` | **必填** | Starting frame index (1-based) |
| `end_frame` | `int` | **必填** | Ending frame index (1-based, inclusive) |
| `times` | `int` | `1` | Number of times to append the range (default: 1) |

### `set_cel_position`

```text
set_cel_position(filename: str = '', *, layer_name: str, frame_index: int, x: int, y: int, create_if_missing: bool = False, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:277`](../../aseprite_mcp/tools/animation.py#L277)

Set a cel's position in a specific layer and frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `x` | `int` | **必填** | X position in pixels |
| `y` | `int` | **必填** | Y position in pixels |
| `create_if_missing` | `bool` | `False` | Create the cel if it does not exist |
| `source_frame_index` | `int \| None` | `None` | Optional frame to copy the cel image from |

### `tween_cel_positions`

```text
tween_cel_positions(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, start_x: int, start_y: int, end_x: int, end_y: int, create_missing_cels: bool = False, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:345`](../../aseprite_mcp/tools/animation.py#L345)

Tween cel positions linearly across a frame range.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `start_frame` | `int` | **必填** | Starting frame index (1-based) |
| `end_frame` | `int` | **必填** | Ending frame index (1-based, inclusive) |
| `start_x` | `int` | **必填** | Starting X position in pixels |
| `start_y` | `int` | **必填** | Starting Y position in pixels |
| `end_x` | `int` | **必填** | Ending X position in pixels |
| `end_y` | `int` | **必填** | Ending Y position in pixels |
| `create_missing_cels` | `bool` | `False` | Create missing cels during tween |
| `source_frame_index` | `int \| None` | `None` | Optional frame to copy the cel image from |

### `offset_cel_positions`

```text
offset_cel_positions(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, dx: int, dy: int) -> str
```

源码：[`aseprite_mcp/tools/animation.py:424`](../../aseprite_mcp/tools/animation.py#L424)

Offset cel positions by a delta across a frame range.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `start_frame` | `int` | **必填** | Starting frame index (1-based) |
| `end_frame` | `int` | **必填** | Ending frame index (1-based, inclusive) |
| `dx` | `int` | **必填** | X delta in pixels |
| `dy` | `int` | **必填** | Y delta in pixels |

### `create_cel`

```text
create_cel(filename: str = '', *, layer_name: str, frame_index: int, x: int = 0, y: int = 0) -> str
```

源码：[`aseprite_mcp/tools/animation.py:476`](../../aseprite_mcp/tools/animation.py#L476)

Create an empty cel on a layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `x` | `int` | `0` | X position in pixels |
| `y` | `int` | `0` | Y position in pixels |

### `clear_cel`

```text
clear_cel(filename: str = '', *, layer_name: str, frame_index: int) -> str
```

源码：[`aseprite_mcp/tools/animation.py:521`](../../aseprite_mcp/tools/animation.py#L521)

Delete a cel on a layer/frame.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `layer_name` | `str` | **必填** |  |
| `frame_index` | `int` | **必填** |  |

### `copy_cel`

```text
copy_cel(filename: str = '', *, layer_name: str, source_frame: int, target_frame: int, replace: bool = True, create_target_frame: bool = True) -> str
```

源码：[`aseprite_mcp/tools/animation.py:558`](../../aseprite_mcp/tools/animation.py#L558)

Copy a cel from one frame to another.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to target |
| `source_frame` | `int` | **必填** | Frame index to copy from (1-based) |
| `target_frame` | `int` | **必填** | Frame index to copy to (1-based) |
| `replace` | `bool` | `True` | Overwrite the existing cel at the target frame (default True) |
| `create_target_frame` | `bool` | `True` | Extend the sprite with new frames when target_frame is beyond the current frame count (default True) |

### `copy_frame`

```text
copy_frame(filename: str = '', *, source_frame: int, target_frame: int | None = None, overwrite: bool = True) -> str
```

源码：[`aseprite_mcp/tools/animation.py:625`](../../aseprite_mcp/tools/animation.py#L625)

Copy all cels from a source frame to a target frame (or append).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `source_frame` | `int` | **必填** |  |
| `target_frame` | `int \| None` | `None` |  |
| `overwrite` | `bool` | `True` |  |

### `propagate_frame_to_range`

```text
propagate_frame_to_range(filename: str = '', *, source_frame: int, start_frame: int, end_frame: int, overwrite: bool = True) -> str
```

源码：[`aseprite_mcp/tools/animation.py:682`](../../aseprite_mcp/tools/animation.py#L682)

Copy all layers from a source frame to a range of frames.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `source_frame` | `int` | **必填** | Frame index to copy from (1-based) |
| `start_frame` | `int` | **必填** | Start frame index (1-based) |
| `end_frame` | `int` | **必填** | End frame index (1-based, inclusive) |
| `overwrite` | `bool` | `True` | Whether to overwrite existing cels (default: True) |

### `set_tag`

```text
set_tag(filename: str = '', *, name: str, from_frame: int, to_frame: int, direction: str = 'forward') -> str
```

源码：[`aseprite_mcp/tools/animation.py:748`](../../aseprite_mcp/tools/animation.py#L748)

Create or update an animation tag on the sprite. direction: forward | reverse | pingpong | pingpong_reverse

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `name` | `str` | **必填** |  |
| `from_frame` | `int` | **必填** |  |
| `to_frame` | `int` | **必填** |  |
| `direction` | `str` | `'forward'` |  |

### `set_onion_skin`

```text
set_onion_skin(filename: str = '', enabled: bool = True, before: int = 2, after: int = 2, opacity: int = 128) -> str
```

源码：[`aseprite_mcp/tools/animation.py:800`](../../aseprite_mcp/tools/animation.py#L800)

Configure onion skin settings for Aseprite.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `enabled` | `bool` | `True` |  |
| `before` | `int` | `2` |  |
| `after` | `int` | `2` |  |
| `opacity` | `int` | `128` |  |

### `propagate_cels`

```text
propagate_cels(filename: str = '', *, layer_names: list[str], source_frame: int, start_frame: int, end_frame: int, replace: bool = True) -> str
```

源码：[`aseprite_mcp/tools/animation.py:822`](../../aseprite_mcp/tools/animation.py#L822)

Copy cels from a source frame to a range of frames for specific layers.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_names` | `list[str]` | **必填** | List of layer names to copy |
| `source_frame` | `int` | **必填** | Frame index to copy from (1-based) |
| `start_frame` | `int` | **必填** | Start frame index (1-based) |
| `end_frame` | `int` | **必填** | End frame index (1-based, inclusive) |
| `replace` | `bool` | `True` | Whether to overwrite existing cels (default: True) |

### `tween_cel_positions_eased`

```text
tween_cel_positions_eased(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, start_x: int, start_y: int, end_x: int, end_y: int, easing: str = 'smoothstep', create_missing_cels: bool = False, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:898`](../../aseprite_mcp/tools/animation.py#L898)

Tween cel positions with easing across a frame range.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `layer_name` | `str` | **必填** |  |
| `start_frame` | `int` | **必填** |  |
| `end_frame` | `int` | **必填** |  |
| `start_x` | `int` | **必填** |  |
| `start_y` | `int` | **必填** |  |
| `end_x` | `int` | **必填** |  |
| `end_y` | `int` | **必填** |  |
| `easing` | `str` | `'smoothstep'` |  |
| `create_missing_cels` | `bool` | `False` |  |
| `source_frame_index` | `int \| None` | `None` |  |

### `oscillate_cel_positions`

```text
oscillate_cel_positions(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, amplitude_x: int = 0, amplitude_y: int = 0, cycles: float = 1.0, phase_deg: float = 0.0, create_missing_cels: bool = False, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:985`](../../aseprite_mcp/tools/animation.py#L985)

Oscillate cel positions across a frame range using a sine wave.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `layer_name` | `str` | **必填** |  |
| `start_frame` | `int` | **必填** |  |
| `end_frame` | `int` | **必填** |  |
| `amplitude_x` | `int` | `0` |  |
| `amplitude_y` | `int` | `0` |  |
| `cycles` | `float` | `1.0` |  |
| `phase_deg` | `float` | `0.0` |  |
| `create_missing_cels` | `bool` | `False` |  |
| `source_frame_index` | `int \| None` | `None` |  |

### `tween_cel_opacity_eased`

```text
tween_cel_opacity_eased(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, start_opacity: int, end_opacity: int, easing: str = 'smoothstep', create_missing_cels: bool = False, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:1062`](../../aseprite_mcp/tools/animation.py#L1062)

Tween cel opacity with easing across a frame range.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `layer_name` | `str` | **必填** |  |
| `start_frame` | `int` | **必填** |  |
| `end_frame` | `int` | **必填** |  |
| `start_opacity` | `int` | **必填** |  |
| `end_opacity` | `int` | **必填** |  |
| `easing` | `str` | `'smoothstep'` |  |
| `create_missing_cels` | `bool` | `False` |  |
| `source_frame_index` | `int \| None` | `None` |  |

### `tween_cel_scale_eased`

```text
tween_cel_scale_eased(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, start_scale: float, end_scale: float, easing: str = 'smoothstep', anchor: str = 'center', replace: bool = True, create_missing_cels: bool = True, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/animation.py:1152`](../../aseprite_mcp/tools/animation.py#L1152)

Tween cel scale with easing across a frame range.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `layer_name` | `str` | **必填** |  |
| `start_frame` | `int` | **必填** |  |
| `end_frame` | `int` | **必填** |  |
| `start_scale` | `float` | **必填** |  |
| `end_scale` | `float` | **必填** |  |
| `easing` | `str` | `'smoothstep'` |  |
| `anchor` | `str` | `'center'` |  |
| `replace` | `bool` | `True` |  |
| `create_missing_cels` | `bool` | `True` |  |
| `source_frame_index` | `int \| None` | `None` |  |

### `delete_frame`

```text
delete_frame(filename: str = '', *, frame_index: int) -> str
```

源码：[`aseprite_mcp/tools/animation.py:1267`](../../aseprite_mcp/tools/animation.py#L1267)

Delete a frame by index.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |

### `delete_tag`

```text
delete_tag(filename: str = '', *, name: str) -> str
```

源码：[`aseprite_mcp/tools/animation.py:1301`](../../aseprite_mcp/tools/animation.py#L1301)

Delete an animation tag by name.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `name` | `str` | **必填** | Tag name to delete |

### `set_cel_opacity`

```text
set_cel_opacity(filename: str = '', *, layer_name: str, frame_index: int, opacity: int) -> str
```

源码：[`aseprite_mcp/tools/animation.py:1338`](../../aseprite_mcp/tools/animation.py#L1338)

Set the opacity of a single cel (0-255).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer containing the cel |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `opacity` | `int` | **必填** | Opacity 0 (transparent) to 255 (opaque) |

## `preview.py`

本地 HTTP 预览服务器

**2 个工具**

### `start_preview_server`

```text
start_preview_server(directory: str = '', port: int = 8000) -> str
```

源码：[`aseprite_mcp/tools/preview.py:28`](../../aseprite_mcp/tools/preview.py#L28)

Start a simple HTTP server to preview exported sprites.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `directory` | `str` | `''` | Directory to serve (optional; defaults to the workspace directory) |
| `port` | `int` | `8000` | Port to bind (default 8000) |

### `stop_preview_server`

```text
stop_preview_server(port: int = 8000) -> str
```

源码：[`aseprite_mcp/tools/preview.py:63`](../../aseprite_mcp/tools/preview.py#L63)

Stop the preview HTTP server for a given port.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `port` | `int` | `8000` | Port to stop (default 8000) |

## `palette.py`

调色板读写、复古预设、色阶生成、量化、色彩模式

**8 个工具**

### `get_palette`

```text
get_palette(filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/palette.py:52`](../../aseprite_mcp/tools/palette.py#L52)

Get the active sprite palette as a JSON array of hex colors.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |

### `set_palette`

```text
set_palette(filename: str = '', *, colors: List[str]) -> str
```

源码：[`aseprite_mcp/tools/palette.py:91`](../../aseprite_mcp/tools/palette.py#L91)

Set the active sprite palette using a list of hex colors.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `colors` | `List[str]` | **必填** | List of #RRGGBB hex colors |

### `remap_colors_in_cel_range`

```text
remap_colors_in_cel_range(filename: str = '', *, layer_name: str, start_frame: int, end_frame: int, mappings: List[dict], create_missing_cels: bool = False, source_frame_index: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/palette.py:133`](../../aseprite_mcp/tools/palette.py#L133)

Remap colors in a layer across a frame range using explicit mappings.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | The path to the Aseprite file (optional; defaults to the session's active file). |
| `layer_name` | `str` | **必填** | The name of the layer to remap colors in. |
| `start_frame` | `int` | **必填** | The start frame index to remap colors in. |
| `end_frame` | `int` | **必填** | The end frame index to remap colors in. |
| `mappings` | `List[dict]` | **必填** | The color mappings to use. |
| `create_missing_cels` | `bool` | `False` | Whether to create missing cels. Defaults to False. |
| `source_frame_index` | `int \| None` | `None` | The source frame index to use for remapping. Defaults to None. |

### `list_palette_presets`

```text
list_palette_presets() -> str
```

源码：[`aseprite_mcp/tools/palette.py:245`](../../aseprite_mcp/tools/palette.py#L245)

List the built-in retro palette presets with their colors. Returns: JSON object mapping preset name to its list of hex colors.

### `apply_palette_preset`

```text
apply_palette_preset(filename: str = '', *, preset: str) -> str
```

源码：[`aseprite_mcp/tools/palette.py:255`](../../aseprite_mcp/tools/palette.py#L255)

Set the sprite palette to a built-in retro preset. This only sets the palette; existing pixels keep their colors. Use quantize_to_palette afterwards to snap pixels to the new palette.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `preset` | `str` | **必填** | One of: gameboy, monochrome, grayscale_4, cga, pico8, c64, dawnbringer16, dawnbringer32 |

### `generate_color_ramp`

```text
generate_color_ramp(base_color: str, steps: int = 5, hue_shift_degrees: float = 20, lightness_range: float = 0.5) -> str
```

源码：[`aseprite_mcp/tools/palette.py:281`](../../aseprite_mcp/tools/palette.py#L281)

Generate a shading ramp (dark to light) from a base color. Produces the standard pixel-art shading technique of hue-shifting: shadows lean cooler (hue shifted one way), highlights lean warmer. Use the returned colors for shading instead of plain darker/lighter versions of the same hue.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `base_color` | `str` | **必填** | Hex color the ramp is built around, e.g. "#D04648" |
| `steps` | `int` | `5` | Number of colors in the ramp, 2-16 (default 5) |
| `hue_shift_degrees` | `float` | `20` | Total hue rotation across the ramp (default 20) |
| `lightness_range` | `float` | `0.5` | Total lightness span across the ramp, 0-1 (default 0.5) |

### `quantize_to_palette`

```text
quantize_to_palette(filename: str = '', layer_name: str = '', start_frame: int = 1, end_frame: int = 0) -> str
```

源码：[`aseprite_mcp/tools/palette.py:330`](../../aseprite_mcp/tools/palette.py#L330)

Snap every pixel to the nearest color in the sprite's palette. Walks the chosen cels and replaces each opaque pixel with the closest palette color (RGB distance). Run after apply_palette_preset or set_palette to make existing art conform to the palette.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | `''` | Layer to quantize (empty = all top-level layers) |
| `start_frame` | `int` | `1` | First frame to process (default 1) |
| `end_frame` | `int` | `0` | Last frame to process (default 0 = last frame) |

### `set_color_mode`

```text
set_color_mode(filename: str = '', *, mode: str) -> str
```

源码：[`aseprite_mcp/tools/palette.py:446`](../../aseprite_mcp/tools/palette.py#L446)

Convert the sprite's color mode.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `mode` | `str` | **必填** | "rgb", "grayscale", or "indexed" |

## `scene.py`

在两个精灵文件之间复制图层

**1 个工具**

### `copy_layers_between_sprites`

```text
copy_layers_between_sprites(*, source_filename: str = '', target_filename: str, layer_names: List[str], replace: bool = True, create_missing_frames: bool = True) -> str
```

源码：[`aseprite_mcp/tools/scene.py:8`](../../aseprite_mcp/tools/scene.py#L8)

Copy layers by name from a source sprite to a target sprite.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `source_filename` | `str` | `''` | Source .aseprite file (optional; defaults to the session's active file) |
| `target_filename` | `str` | **必填** | Target .aseprite file (must already exist) |
| `layer_names` | `List[str]` | **必填** | List of layer names to copy |
| `replace` | `bool` | `True` | Overwrite existing cels in target layers |
| `create_missing_frames` | `bool` | `True` | Add frames to target if needed |

## `guide.py`

返回面向 LLM 的动画工作流指南文本

**1 个工具**

### `animation_workflow_guide`

```text
animation_workflow_guide(use_case: str = 'character') -> str
```

源码：[`aseprite_mcp/tools/guide.py:4`](../../aseprite_mcp/tools/guide.py#L4)

Return a concise English guide for optimized animation workflows.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `use_case` | `str` | `'character'` |  |

## `quality.py`

动画一致性校验与归一化（结构校验器，非评分器）

**4 个工具**

### `ensure_layers_present`

```text
ensure_layers_present(filename: str = '', *, layer_names: List[str], start_frame: int = 1, end_frame: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/quality.py:57`](../../aseprite_mcp/tools/quality.py#L57)

Ensure cels exist for layers across a frame range.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `layer_names` | `List[str]` | **必填** |  |
| `start_frame` | `int` | `1` |  |
| `end_frame` | `int \| None` | `None` |  |

### `validate_scene`

```text
validate_scene(filename: str = '', *, required_layers: List[str], start_frame: int = 1, end_frame: int | None = None) -> str
```

源码：[`aseprite_mcp/tools/quality.py:124`](../../aseprite_mcp/tools/quality.py#L124)

Validate presence of layers and cels across a frame range. Returns JSON with missing layers and missing cels.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `required_layers` | `List[str]` | **必填** |  |
| `start_frame` | `int` | `1` |  |
| `end_frame` | `int \| None` | `None` |  |

### `audit_animation`

```text
audit_animation(filename: str = '', start_frame: int = 1, end_frame: int | None = None, layer_names: List[str] | None = None, overlap_pairs: List[str] | None = None, layer_frame_ranges: List[str] | None = None, report_cels: bool = False, report_bounds: bool = False, max_overlaps: int = 200, max_out_of_range: int = 200) -> str
```

源码：[`aseprite_mcp/tools/quality.py:206`](../../aseprite_mcp/tools/quality.py#L206)

Audit animation frames for overlaps and out-of-range layer activity. overlap_pairs format: ["layerA,layerB", "layerC:layerD"] layer_frame_ranges format: ["layer:1-8,17-24", "clouds:1-12"] Returns JSON for AI consumption (summary, overlaps, out_of_range, optional cels).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `start_frame` | `int` | `1` |  |
| `end_frame` | `int \| None` | `None` |  |
| `layer_names` | `List[str] \| None` | `None` |  |
| `overlap_pairs` | `List[str] \| None` | `None` |  |
| `layer_frame_ranges` | `List[str] \| None` | `None` |  |
| `report_cels` | `bool` | `False` |  |
| `report_bounds` | `bool` | `False` |  |
| `max_overlaps` | `int` | `200` |  |
| `max_out_of_range` | `int` | `200` |  |

### `animation_sanitize`

```text
animation_sanitize(filename: str = '', start_frame: int = 1, end_frame: int | None = None, layer_names: List[str] | None = None, layer_order: List[str] | None = None, layer_frame_ranges: List[str] | None = None, ensure_layers: List[str] | None = None, overlap_pairs: List[str] | None = None, report_bounds: bool = False, max_overlaps: int = 200, ignore_full_canvas_overlaps: bool = True, out_of_range_action: str = 'set_opacity_zero', out_of_range_opacity: int = 0, report_only: bool = False, include_stats: bool = True) -> str
```

源码：[`aseprite_mcp/tools/quality.py:443`](../../aseprite_mcp/tools/quality.py#L443)

Normalize animation consistency and optionally apply fixes. layer_frame_ranges format: ["layer:1-8,17-24", "clouds:1-12"] out_of_range_action: "set_opacity_zero", "delete_cels", "none" ignore_full_canvas_overlaps: skip overlap checks when a cel is full canvas Returns JSON for AI consumption (summary, layer_stats, alerts, overlaps).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` |  |
| `start_frame` | `int` | `1` |  |
| `end_frame` | `int \| None` | `None` |  |
| `layer_names` | `List[str] \| None` | `None` |  |
| `layer_order` | `List[str] \| None` | `None` |  |
| `layer_frame_ranges` | `List[str] \| None` | `None` |  |
| `ensure_layers` | `List[str] \| None` | `None` |  |
| `overlap_pairs` | `List[str] \| None` | `None` |  |
| `report_bounds` | `bool` | `False` |  |
| `max_overlaps` | `int` | `200` |  |
| `ignore_full_canvas_overlaps` | `bool` | `True` |  |
| `out_of_range_action` | `str` | `'set_opacity_zero'` |  |
| `out_of_range_opacity` | `int` | `0` |  |
| `report_only` | `bool` | `False` |  |
| `include_stats` | `bool` | `True` |  |

## `pixel_read.py`

单 cel 与合成后的像素读取

**4 个工具**

### `get_pixel_color`

```text
get_pixel_color(filename: str = '', *, x: int, y: int, layer_name: str = '', frame_index: int = 1) -> str
```

源码：[`aseprite_mcp/tools/pixel_read.py:10`](../../aseprite_mcp/tools/pixel_read.py#L10)

Read the RGBA color of a single pixel from one layer's cel. This is a single-cel read: it ignores layer visibility and everything drawn above or below. For "what the player sees", use get_composite_pixel instead. Tilemap layers cannot be read this way — their cel stores tile indexes, so the call is refused with a hint.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `x` | `int` | **必填** | X coordinate (sprite-global) |
| `y` | `int` | **必填** | Y coordinate (sprite-global) |
| `layer_name` | `str` | `''` | Layer to read from (uses active layer when empty) |
| `frame_index` | `int` | `1` | Frame index starting at 1 |

### `get_pixels_rect`

```text
get_pixels_rect(filename: str = '', *, x: int, y: int, width: int, height: int, layer_name: str = '', frame_index: int = 1) -> str
```

源码：[`aseprite_mcp/tools/pixel_read.py:83`](../../aseprite_mcp/tools/pixel_read.py#L83)

Read all pixel colors in a rectangular region from one layer's cel. Single-cel read: layer visibility is ignored and nothing above or below is composited in. For "what the player sees", use get_composite_rect. Tilemap layers are refused — their cel stores tile indexes, not pixels.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `x` | `int` | **必填** | Top-left x coordinate (sprite-global) |
| `y` | `int` | **必填** | Top-left y coordinate (sprite-global) |
| `width` | `int` | **必填** | Width of the region |
| `height` | `int` | **必填** | Height of the region |
| `layer_name` | `str` | `''` | Layer to read from (uses active layer when empty) |
| `frame_index` | `int` | `1` | Frame index starting at 1 |

### `get_composite_pixel`

```text
get_composite_pixel(filename: str = '', *, x: int, y: int, frame_index: int = 1) -> str
```

源码：[`aseprite_mcp/tools/pixel_read.py:180`](../../aseprite_mcp/tools/pixel_read.py#L180)

Read the RGBA colour VISIBLE at a pixel (flattened composite of all layers). Unlike get_pixel_color (which reads a single cel), this composites every visible layer — "what the player actually sees" — by flattening a throwaway clone. Essential for value/CVD QA on grouped/multi-layer scenes.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `x` | `int` | **必填** | X coordinate (sprite-global) |
| `y` | `int` | **必填** | Y coordinate (sprite-global) |
| `frame_index` | `int` | `1` | Frame index starting at 1 |

### `get_composite_rect`

```text
get_composite_rect(filename: str = '', *, x: int, y: int, width: int, height: int, frame_index: int = 1) -> str
```

源码：[`aseprite_mcp/tools/pixel_read.py:228`](../../aseprite_mcp/tools/pixel_read.py#L228)

Read VISIBLE RGBA over a rectangle (flattened composite of all layers). The rectangular counterpart of get_composite_pixel — reads the composited pixels every visible layer produces, not a single cel.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `x` | `int` | **必填** | Top-left x (sprite-global) |
| `y` | `int` | **必填** | Top-left y (sprite-global) |
| `width` | `int` | **必填** | Region width |
| `height` | `int` | **必填** | Region height |
| `frame_index` | `int` | `1` | Frame index starting at 1 |

## `transform.py`

翻转、旋转、缩放、裁剪

**4 个工具**

### `flip_layer`

```text
flip_layer(filename: str = '', *, layer_name: str, frame_index: int, direction: str = 'horizontal') -> str
```

源码：[`aseprite_mcp/tools/transform.py:8`](../../aseprite_mcp/tools/transform.py#L8)

Flip a layer's image horizontally or vertically.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to flip |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `direction` | `str` | `'horizontal'` | "horizontal" or "vertical" |

### `rotate_layer`

```text
rotate_layer(filename: str = '', *, layer_name: str, frame_index: int, angle: int = 90) -> str
```

源码：[`aseprite_mcp/tools/transform.py:77`](../../aseprite_mcp/tools/transform.py#L77)

Rotate a layer's image 90, 180, or 270 degrees clockwise.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer name to rotate |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `angle` | `int` | `90` | Rotation angle: 90, 180, or 270 (clockwise) |

### `resize_canvas`

```text
resize_canvas(filename: str = '', *, width: int, height: int) -> str
```

源码：[`aseprite_mcp/tools/transform.py:169`](../../aseprite_mcp/tools/transform.py#L169)

Scale the canvas and all its content to new dimensions.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `width` | `int` | **必填** | New canvas width in pixels |
| `height` | `int` | **必填** | New canvas height in pixels |

### `crop_canvas`

```text
crop_canvas(filename: str = '', *, x: int, y: int, width: int, height: int) -> str
```

源码：[`aseprite_mcp/tools/transform.py:202`](../../aseprite_mcp/tools/transform.py#L202)

Crop the canvas to the given rectangle, discarding content outside it.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `x` | `int` | **必填** | Left edge of the crop area |
| `y` | `int` | **必填** | Top edge of the crop area |
| `width` | `int` | **必填** | Width of the crop area |
| `height` | `int` | **必填** | Height of the crop area |

## `layers.py`

图层删除、重命名、复制、排序、混合模式、合并、展平

**7 个工具**

### `delete_layer`

```text
delete_layer(filename: str = '', *, layer_name: str) -> str
```

源码：[`aseprite_mcp/tools/layers.py:30`](../../aseprite_mcp/tools/layers.py#L30)

Delete a layer by name.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Name of the layer to delete |

### `rename_layer`

```text
rename_layer(filename: str = '', *, layer_name: str, new_name: str) -> str
```

源码：[`aseprite_mcp/tools/layers.py:68`](../../aseprite_mcp/tools/layers.py#L68)

Rename a layer.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Current layer name |
| `new_name` | `str` | **必填** | New layer name |

### `duplicate_layer`

```text
duplicate_layer(filename: str = '', *, layer_name: str, new_name: str = '', group: str = '') -> str
```

源码：[`aseprite_mcp/tools/layers.py:109`](../../aseprite_mcp/tools/layers.py#L109)

Duplicate a layer with all its cels across every frame. The copy inherits the source's opacity and blend mode. By default it is placed directly above the source layer; pass `group` to place it inside a group instead.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to duplicate, by name or "group/subgroup/layer" path |
| `new_name` | `str` | `''` | Name for the copy (default: "<layer_name> copy") |
| `group` | `str` | `''` | Optional group to place the copy inside, by name or "group/subgroup" path (default: directly above the source) |

### `reorder_layer`

```text
reorder_layer(filename: str = '', *, layer_name: str, position: int) -> str
```

源码：[`aseprite_mcp/tools/layers.py:179`](../../aseprite_mcp/tools/layers.py#L179)

Move a layer to a new position in the layer stack.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to move |
| `position` | `int` | **必填** | Target stack position, 1-based where 1 is the bottom layer |

### `set_layer_blend_mode`

```text
set_layer_blend_mode(filename: str = '', *, layer_name: str, mode: str) -> str
```

源码：[`aseprite_mcp/tools/layers.py:220`](../../aseprite_mcp/tools/layers.py#L220)

Set a layer's blend mode.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to modify |
| `mode` | `str` | **必填** | One of: normal, darken, multiply, color_burn, lighten, screen, color_dodge, addition, overlay, soft_light, hard_light, difference, exclusion, subtract, divide, hue, saturation, color, luminosity |

### `merge_layer_down`

```text
merge_layer_down(filename: str = '', *, layer_name: str) -> str
```

源码：[`aseprite_mcp/tools/layers.py:265`](../../aseprite_mcp/tools/layers.py#L265)

Merge a layer into the layer directly below it.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to merge down (must not be the bottom layer) |

### `flatten_sprite`

```text
flatten_sprite(filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/layers.py:302`](../../aseprite_mcp/tools/layers.py#L302)

Flatten all layers into a single layer.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |

## `selection.py`

矩形区域的移动/复制/擦除，以及按颜色擦除

**4 个工具**

### `move_region`

```text
move_region(filename: str = '', *, layer_name: str, frame_index: int, x: int, y: int, width: int, height: int, dest_x: int, dest_y: int) -> str
```

源码：[`aseprite_mcp/tools/selection.py:15`](../../aseprite_mcp/tools/selection.py#L15)

Cut a rectangular region of pixels and paste it at a new position. Coordinates are sprite-global. The source area is left transparent. Pixels moved outside the canvas are discarded. Fully transparent source pixels do not overwrite destination pixels.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to operate on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `x` | `int` | **必填** | Left edge of the source region |
| `y` | `int` | **必填** | Top edge of the source region |
| `width` | `int` | **必填** | Region width |
| `height` | `int` | **必填** | Region height |
| `dest_x` | `int` | **必填** | New left edge for the region |
| `dest_y` | `int` | **必填** | New top edge for the region |

### `copy_region`

```text
copy_region(filename: str = '', *, layer_name: str, frame_index: int, x: int, y: int, width: int, height: int, dest_x: int, dest_y: int, target_layer_name: str = '', target_frame_index: int = 0) -> str
```

源码：[`aseprite_mcp/tools/selection.py:98`](../../aseprite_mcp/tools/selection.py#L98)

Copy a rectangular region of pixels to another position, layer, or frame. Coordinates are sprite-global. Fully transparent source pixels do not overwrite destination pixels. The destination cel is created when missing.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Source layer |
| `frame_index` | `int` | **必填** | Source frame index starting at 1 |
| `x` | `int` | **必填** | Left edge of the source region |
| `y` | `int` | **必填** | Top edge of the source region |
| `width` | `int` | **必填** | Region width |
| `height` | `int` | **必填** | Region height |
| `dest_x` | `int` | **必填** | Left edge of the destination |
| `dest_y` | `int` | **必填** | Top edge of the destination |
| `target_layer_name` | `str` | `''` | Destination layer (default: same as source) |
| `target_frame_index` | `int` | `0` | Destination frame (default: same as source) |

### `erase_region`

```text
erase_region(filename: str = '', *, layer_name: str, frame_index: int, x: int, y: int, width: int, height: int) -> str
```

源码：[`aseprite_mcp/tools/selection.py:190`](../../aseprite_mcp/tools/selection.py#L190)

Erase (make transparent) a rectangular region of pixels. Coordinates are sprite-global.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to operate on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `x` | `int` | **必填** | Left edge of the region |
| `y` | `int` | **必填** | Top edge of the region |
| `width` | `int` | **必填** | Region width |
| `height` | `int` | **必填** | Region height |

### `erase_color`

```text
erase_color(filename: str = '', *, layer_name: str, frame_index: int, color: str, tolerance: int = 0) -> str
```

源码：[`aseprite_mcp/tools/selection.py:249`](../../aseprite_mcp/tools/selection.py#L249)

Make all pixels of a given color transparent (like a magic eraser).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to operate on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `color` | `str` | **必填** | Hex color to erase, e.g. "#FF00FF" |
| `tolerance` | `int` | `0` | Per-channel tolerance 0-255 (default 0 = exact match) |

## `fx.py`

手写逐像素特效：描边、换色、HSL 调整、有序抖动

**5 个工具**

### `outline_cel`

```text
outline_cel(filename: str = '', *, layer_name: str, frame_index: int, color: str = '#000000', include_diagonals: bool = False) -> str
```

源码：[`aseprite_mcp/tools/fx.py:15`](../../aseprite_mcp/tools/fx.py#L15)

Add a 1px outline around all opaque pixels of a cel. Transparent pixels adjacent to opaque pixels are filled with the outline color. Great for making sprites read clearly against any background.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to outline |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `color` | `str` | `'#000000'` | Outline hex color (default black) |
| `include_diagonals` | `bool` | `False` | Also outline diagonal neighbors for a thicker, rounded outline (default False) |

### `replace_color`

```text
replace_color(filename: str = '', *, layer_name: str, frame_index: int, from_color: str, to_color: str, tolerance: int = 0) -> str
```

源码：[`aseprite_mcp/tools/fx.py:95`](../../aseprite_mcp/tools/fx.py#L95)

Replace one color with another in a cel, preserving alpha.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to operate on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `from_color` | `str` | **必填** | Hex color to replace, e.g. "#FF0000" |
| `to_color` | `str` | **必填** | Replacement hex color |
| `tolerance` | `int` | `0` | Per-channel tolerance 0-255 (default 0 = exact match) |

### `adjust_hsl`

```text
adjust_hsl(filename: str = '', *, layer_name: str, frame_index: int, hue_shift: float = 0, saturation_shift: float = 0, lightness_shift: float = 0) -> str
```

源码：[`aseprite_mcp/tools/fx.py:175`](../../aseprite_mcp/tools/fx.py#L175)

Shift hue, saturation, and lightness of all opaque pixels in a cel. Useful for creating palette-swapped variants and shading: e.g. darken a duplicated layer for shadows or hue-shift toward blue for night scenes.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to adjust |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `hue_shift` | `float` | `0` | Degrees to rotate hue, -360 to 360 |
| `saturation_shift` | `float` | `0` | Saturation delta, -100 to 100 |
| `lightness_shift` | `float` | `0` | Lightness delta, -100 to 100 |

### `apply_dither_gradient`

```text
apply_dither_gradient(filename: str = '', *, layer_name: str, frame_index: int, x: int, y: int, width: int, height: int, color_start: str, color_end: str, horizontal: bool = False, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/fx.py:253`](../../aseprite_mcp/tools/fx.py#L253)

Fill a rectangle with a two-color gradient using Bayer 4x4 ordered dithering. This is the classic pixel-art way to blend two colors without introducing new intermediate colors. The gradient runs from color_start (top/left) to color_end (bottom/right).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to draw on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `x` | `int` | **必填** | Left edge of the rectangle |
| `y` | `int` | **必填** | Top edge of the rectangle |
| `width` | `int` | **必填** | Rectangle width |
| `height` | `int` | **必填** | Rectangle height |
| `color_start` | `str` | **必填** | Hex color at the start of the gradient |
| `color_end` | `str` | **必填** | Hex color at the end of the gradient |
| `horizontal` | `bool` | `False` | Run the gradient left-to-right instead of top-to-bottom |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist |

### `apply_dither_pattern`

```text
apply_dither_pattern(filename: str = '', *, layer_name: str, frame_index: int, x: int, y: int, width: int, height: int, color_a: str, color_b: str, density: float = 0.5, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/fx.py:347`](../../aseprite_mcp/tools/fx.py#L347)

Fill a rectangle with a uniform Bayer-dithered mix of two colors. density controls the ratio: 0.0 = all color_a, 0.5 = checkerboard, 1.0 = all color_b. Useful for textures (stone, grass) and flat mid-tones between two palette colors.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Layer to draw on |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `x` | `int` | **必填** | Left edge of the rectangle |
| `y` | `int` | **必填** | Top edge of the rectangle |
| `width` | `int` | **必填** | Rectangle width |
| `height` | `int` | **必填** | Rectangle height |
| `color_a` | `str` | **必填** | Base hex color |
| `color_b` | `str` | **必填** | Mixed-in hex color |
| `density` | `float` | `0.5` | Fraction of color_b, 0.0-1.0 (default 0.5) |
| `create_if_missing` | `bool` | `True` | Create the layer (top-level names only; never group paths) and cel if they don't exist |

## `analysis.py`

洋葱皮渲染、帧差异、颜色统计

**3 个工具**

### `render_onion_skin`

```text
render_onion_skin(filename: str = '', *, frame_index: int, output_filename: str, before: int = 1, after: int = 1, scale: int = 4, ghost_opacity: int = 100) -> str
```

源码：[`aseprite_mcp/tools/analysis.py:67`](../../aseprite_mcp/tools/analysis.py#L67)

Render a frame with neighboring frames as translucent onion-skin ghosts. Produces a PNG of the given frame composited over ghosted copies of the surrounding frames — the batch-mode equivalent of Aseprite's onion skinning. Essential for checking motion continuity while animating: export it, open the PNG, and verify the in-between positions line up.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `frame_index` | `int` | **必填** | Frame to render, starting at 1 |
| `output_filename` | `str` | **必填** | Output PNG path |
| `before` | `int` | `1` | Number of previous frames to ghost (default 1) |
| `after` | `int` | `1` | Number of following frames to ghost (default 1) |
| `scale` | `int` | `4` | Integer nearest-neighbor scale factor (default 4) |
| `ghost_opacity` | `int` | `100` | Opacity of ghost frames, 0-255 (default 100) |

### `compare_frames`

```text
compare_frames(filename: str = '', *, frame_a: int, frame_b: int) -> str
```

源码：[`aseprite_mcp/tools/analysis.py:161`](../../aseprite_mcp/tools/analysis.py#L161)

Compare two frames and report how much they differ. Composites the *visible* layers (non-destructively) and diffs the two frames pixel by pixel. Use while animating to confirm a frame actually changed, or that it did not change too much. Hidden layers do not count as a change.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `frame_a` | `int` | **必填** | First frame index, starting at 1 |
| `frame_b` | `int` | **必填** | Second frame index, starting at 1 |

### `get_color_stats`

```text
get_color_stats(filename: str = '', frame_index: int = 1, top: int = 16) -> str
```

源码：[`aseprite_mcp/tools/analysis.py:257`](../../aseprite_mcp/tools/analysis.py#L257)

Report the colors used in a frame and how often each appears. Composites the *visible* layers (non-destructively) and histograms the frame — hidden layers are excluded, so the counts match what a player sees. Use to check palette discipline: too many near-duplicate colors is a common pixel-art mistake.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `frame_index` | `int` | `1` | Frame to analyze, starting at 1 (default 1) |
| `top` | `int` | `16` | How many of the most-used colors to list (default 16) |

## `slices.py`

命名区域、九宫格中心、轴心点

**5 个工具**

### `create_slice`

```text
create_slice(filename: str = '', *, name: str, x: int, y: int, width: int, height: int) -> str
```

源码：[`aseprite_mcp/tools/slices.py:17`](../../aseprite_mcp/tools/slices.py#L17)

Create a named slice (a rectangular region usable by game engines).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `name` | `str` | **必填** | Slice name |
| `x` | `int` | **必填** | Left edge of the slice |
| `y` | `int` | **必填** | Top edge of the slice |
| `width` | `int` | **必填** | Slice width |
| `height` | `int` | **必填** | Slice height |

### `set_slice_center`

```text
set_slice_center(filename: str = '', *, name: str, x: int, y: int, width: int, height: int) -> str
```

源码：[`aseprite_mcp/tools/slices.py:61`](../../aseprite_mcp/tools/slices.py#L61)

Set a slice's 9-patch center rectangle (relative to the slice origin). The center defines the stretchable region for 9-patch scaling in game engines.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `name` | `str` | **必填** | Slice name |
| `x` | `int` | **必填** | Center-rect left edge, relative to the slice |
| `y` | `int` | **必填** | Center-rect top edge, relative to the slice |
| `width` | `int` | **必填** | Center-rect width |
| `height` | `int` | **必填** | Center-rect height |

### `set_slice_pivot`

```text
set_slice_pivot(filename: str = '', *, name: str, x: int, y: int) -> str
```

源码：[`aseprite_mcp/tools/slices.py:106`](../../aseprite_mcp/tools/slices.py#L106)

Set a slice's pivot point (relative to the slice origin).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `name` | `str` | **必填** | Slice name |
| `x` | `int` | **必填** | Pivot x, relative to the slice |
| `y` | `int` | **必填** | Pivot y, relative to the slice |

### `list_slices`

```text
list_slices(filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/slices.py:144`](../../aseprite_mcp/tools/slices.py#L144)

List all slices with their bounds, 9-patch centers, and pivots.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |

### `delete_slice`

```text
delete_slice(filename: str = '', *, name: str) -> str
```

源码：[`aseprite_mcp/tools/slices.py:195`](../../aseprite_mcp/tools/slices.py#L195)

Delete a slice by name.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `name` | `str` | **必填** | Slice name to delete |

## `tilemap.py`

tilemap 图层、tileset 编辑、瓦片摆放与读取

**5 个工具**

### `create_tilemap_layer`

```text
create_tilemap_layer(filename: str = '', *, layer_name: str, tile_width: int, tile_height: int) -> str
```

源码：[`aseprite_mcp/tools/tilemap.py:25`](../../aseprite_mcp/tools/tilemap.py#L25)

Create a tilemap layer with its own tileset. Sets the sprite grid to the tile size and adds a tilemap layer. Tile index 0 is always the empty tile; add real tiles with draw_on_tile (which creates tiles on demand).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Name for the new tilemap layer |
| `tile_width` | `int` | **必填** | Tile width in pixels |
| `tile_height` | `int` | **必填** | Tile height in pixels |

### `draw_on_tile`

```text
draw_on_tile(filename: str = '', *, layer_name: str, tile_index: int, pixels: List[Dict[str, Any]]) -> str
```

源码：[`aseprite_mcp/tools/tilemap.py:81`](../../aseprite_mcp/tools/tilemap.py#L81)

Draw pixels onto a tile in a tilemap layer's tileset. Coordinates are tile-local (0,0 = tile top-left). When tile_index equals the current tile count, a new tile is appended automatically.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Tilemap layer whose tileset to edit |
| `tile_index` | `int` | **必填** | Tile to draw on (1 = first real tile; 0 is reserved for the empty tile and cannot be drawn on) |
| `pixels` | `List[Dict[str, Any]]` | **必填** | List of {"x": int, "y": int, "color": "#RRGGBB"} |

### `set_tiles`

```text
set_tiles(filename: str = '', *, layer_name: str, frame_index: int, tiles: List[Dict[str, Any]]) -> str
```

源码：[`aseprite_mcp/tools/tilemap.py:167`](../../aseprite_mcp/tools/tilemap.py#L167)

Place tiles on a tilemap layer by grid position.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Tilemap layer to edit |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `tiles` | `List[Dict[str, Any]]` | **必填** | List of {"col": int, "row": int, "tile_index": int} (col/row are grid coordinates; tile_index 0 clears the cell) |

### `get_tile_at`

```text
get_tile_at(filename: str = '', *, layer_name: str, frame_index: int, col: int, row: int) -> str
```

源码：[`aseprite_mcp/tools/tilemap.py:267`](../../aseprite_mcp/tools/tilemap.py#L267)

Read which tile is placed at a grid position.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Tilemap layer to read |
| `frame_index` | `int` | **必填** | Frame index starting at 1 |
| `col` | `int` | **必填** | Grid column (0-based) |
| `row` | `int` | **必填** | Grid row (0-based) |

### `get_tilemap_info`

```text
get_tilemap_info(filename: str = '', *, layer_name: str) -> str
```

源码：[`aseprite_mcp/tools/tilemap.py:325`](../../aseprite_mcp/tools/tilemap.py#L325)

Get tilemap layer info: tile size, tile count, and map dimensions.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to read (optional; defaults to the session's active file) |
| `layer_name` | `str` | **必填** | Tilemap layer to inspect |

## `script.py`

任意 Aseprite Lua 的逃生舱

**1 个工具**

### `run_lua_script`

```text
run_lua_script(script: str, filename: str = '') -> str
```

源码：[`aseprite_mcp/tools/script.py:7`](../../aseprite_mcp/tools/script.py#L7)

Execute arbitrary Aseprite Lua code in batch mode (escape hatch). Use this when no dedicated tool covers what you need. The full API is documented at https://www.aseprite.org/api/. Anything the curated tools do can also be done here — they are Lua underneath. Essentials for batch-mode scripts: - When filename is given, it is opened first and available as app.activeSprite. - Changes are NOT saved automatically; call spr:saveAs(spr.filename) at the end if you modified the sprite. - print() is the only way to return data; a clean exit does not mean your logic succeeded, so print what you need to verify. - Coordinates on cel images are cel-local: offset sprite-global coordinates by cel.position before getPixel/putPixel. WARNING: this executes unrestricted code (including io/os access) on the host running Aseprite. Only pass scripts you trust.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `script` | `str` | **必填** | Lua source code to execute |
| `filename` | `str` | `''` | Aseprite file to open before running (optional; defaults to the session's active file, or no file when nothing is anchored) |

## `text.py`

用 bitmap 或 TrueType 字体绘制与测量文本

**3 个工具**

### `list_text_fonts`

```text
list_text_fonts() -> str
```

源码：[`aseprite_mcp/tools/text.py:53`](../../aseprite_mcp/tools/text.py#L53)

List fonts that draw_text can use. Covers bitmap sprite-sheet fonts and .ttf/.otf files installed under ~/.aseprite-mcp/fonts, plus TrueType fonts found in the system font directories. Bitmap fonts are the right choice for pixel art: their glyphs are already pixels and `size` scales them by whole numbers.

### `measure_text`

```text
measure_text(text: str, font: str, size: int = 1, letter_spacing: int = 0, bold: int = 0, antialias: bool = False) -> str
```

源码：[`aseprite_mcp/tools/text.py:81`](../../aseprite_mcp/tools/text.py#L81)

Measure text without drawing it. Use this to size a panel or centre a label in one shot instead of guessing and re-rendering.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `text` | `str` | **必填** | The string to measure |
| `font` | `str` | **必填** | Font name from list_text_fonts, or a path to a .ttf/.otf or bitmap font directory |
| `size` | `int` | `1` | Pixel size for TrueType fonts; integer scale factor for bitmap fonts (default 1) |
| `letter_spacing` | `int` | `0` | Extra pixels between glyphs (default 0) |
| `bold` | `int` | `0` | Faux-bold passes; each grows strokes by 1px (default 0) |
| `antialias` | `bool` | `False` | Keep greyscale edges instead of hard pixels (default False) |

### `draw_text`

```text
draw_text(filename: str = '', *, text: str, x: int, y: int, font: str, size: int = 1, color: str = '#FFFFFF', layer_name: Optional[str] = None, frame_index: int = 1, anchor: str = 'topleft', letter_spacing: int = 0, bold: int = 0, outline_color: Optional[str] = None, outline_width: int = 1, outline_diagonal: bool = True, shadow_color: Optional[str] = None, shadow_dx: int = 1, shadow_dy: int = 1, antialias: bool = False, create_if_missing: bool = True) -> str
```

源码：[`aseprite_mcp/tools/text.py:121`](../../aseprite_mcp/tools/text.py#L121)

Draw text onto a sprite. Glyphs are rasterised outside Aseprite and composited in, because the Lua API has no text drawing of its own.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `text` | `str` | **必填** | String to draw |
| `x` | `int` | **必填** | X coordinate of the anchor point |
| `y` | `int` | **必填** | Y coordinate of the anchor point |
| `font` | `str` | **必填** | Font name from list_text_fonts, or a path to a .ttf/.otf or a bitmap font directory |
| `size` | `int` | `1` | Pixel size for TrueType fonts; integer scale factor for bitmap fonts (default 1) |
| `color` | `str` | `'#FFFFFF'` | Text colour, #RRGGBB or #RRGGBBAA (default white) |
| `layer_name` | `Optional[str]` | `None` | Layer to draw on; the active/first layer if omitted |
| `frame_index` | `int` | `1` | Frame index starting at 1 (default 1) |
| `anchor` | `str` | `'topleft'` | Which point of the text (x, y) refers to - one of topleft, top, topright, left, center, right, bottomleft, bottom, bottomright, baselineleft, baseline, baselineright (default topleft) |
| `letter_spacing` | `int` | `0` | Extra pixels between glyphs (default 0) |
| `bold` | `int` | `0` | Faux-bold passes; each grows strokes by 1px (default 0) |
| `outline_color` | `Optional[str]` | `None` | If set, draw a 1px outline in this colour |
| `outline_width` | `int` | `1` | Outline thickness in pixels (default 1) |
| `outline_diagonal` | `bool` | `True` | Include diagonal neighbours in the outline, giving a rounded corner; False gives a boxier 4-way outline (default True) |
| `shadow_color` | `Optional[str]` | `None` | If set, draw a drop shadow in this colour |
| `shadow_dx` | `int` | `1` | Shadow X offset (default 1) |
| `shadow_dy` | `int` | `1` | Shadow Y offset (default 1) |
| `antialias` | `bool` | `False` | Keep greyscale edges instead of hard pixels (default False) |
| `create_if_missing` | `bool` | `True` | Create the layer/cel if absent (default True) |

## `native_fx.py`

Aseprite 原生滤镜包装（app.command.*）

**7 个工具**

### `outline_native`

```text
outline_native(filename: str = '', layer_name: str = '', frame_index: int = 1, color: str = '#000000', place: str = 'outside', matrix: str = 'circle') -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:41`](../../aseprite_mcp/tools/native_fx.py#L41)

Native Aseprite Outline around opaque pixels (app.command.Outline). Higher quality than the 1px hand-rolled outline_cel: inside/outside placement + a circle/square brush. Works best on a full-canvas cel.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | `''` | layer to outline (empty = active layer) |
| `frame_index` | `int` | `1` | 1-based frame |
| `color` | `str` | `'#000000'` | outline colour as #RRGGBB |
| `place` | `str` | `'outside'` | "outside" or "inside" |
| `matrix` | `str` | `'circle'` | "circle" or "square" |

### `adjust_hsl_native`

```text
adjust_hsl_native(filename: str = '', layer_name: str = '', frame_index: int = 1, hue: int = 0, saturation: int = 0, lightness: int = 0, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:84`](../../aseprite_mcp/tools/native_fx.py#L84)

Native Hue/Saturation/Lightness filter (engine-quality vs adjust_hsl).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | `''` | layer to adjust (empty = active layer) |
| `frame_index` | `int` | `1` | 1-based frame |
| `hue` | `int` | `0` | -180..180 (degrees) |
| `saturation` | `int` | `0` | -100..100 |
| `lightness` | `int` | `0` | -100..100 x, y, width, height: optional region (width>0 & height>0 to scope) |
| `x` | `int` | `0` |  |
| `y` | `int` | `0` |  |
| `width` | `int` | `0` |  |
| `height` | `int` | `0` |  |

### `adjust_brightness_contrast`

```text
adjust_brightness_contrast(filename: str = '', layer_name: str = '', frame_index: int = 1, brightness: int = 0, contrast: int = 0, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:126`](../../aseprite_mcp/tools/native_fx.py#L126)

Native Brightness/Contrast filter (app.command.BrightnessContrast).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | `''` | layer to adjust (empty = active layer) |
| `frame_index` | `int` | `1` | 1-based frame |
| `brightness` | `int` | `0` | -100..100 |
| `contrast` | `int` | `0` | -100..100 x, y, width, height: optional region (width>0 & height>0 to scope) |
| `x` | `int` | `0` |  |
| `y` | `int` | `0` |  |
| `width` | `int` | `0` |  |
| `height` | `int` | `0` |  |

### `invert_colors`

```text
invert_colors(filename: str = '', layer_name: str = '', frame_index: int = 1, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:164`](../../aseprite_mcp/tools/native_fx.py#L164)

Native colour inversion (app.command.InvertColor).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `layer_name` | `str` | `''` | layer to invert (empty = active layer) |
| `frame_index` | `int` | `1` | 1-based frame x, y, width, height: optional region (width>0 & height>0 to scope) |
| `x` | `int` | `0` |  |
| `y` | `int` | `0` |  |
| `width` | `int` | `0` |  |
| `height` | `int` | `0` |  |

### `apply_convolution`

```text
apply_convolution(filename: str = '', *, matrix: str, layer_name: str = '', frame_index: int = 1, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:195`](../../aseprite_mcp/tools/native_fx.py#L195)

Native convolution filter (blur / sharpen / edge / emboss …).

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `matrix` | `str` | **必填** | a built-in matrix name (see list_convolution_matrices), e.g. "blur-3x3", "sharpen-3x3", "edges-find", "misc-emboss" |
| `layer_name` | `str` | `''` | layer to filter (empty = active layer) |
| `frame_index` | `int` | `1` | 1-based frame x, y, width, height: optional region (width>0 & height>0 to scope) |
| `x` | `int` | `0` |  |
| `y` | `int` | `0` |  |
| `width` | `int` | `0` |  |
| `height` | `int` | `0` |  |

### `list_convolution_matrices`

```text
list_convolution_matrices() -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:223`](../../aseprite_mcp/tools/native_fx.py#L223)

List the built-in convolution-matrix names usable with apply_convolution. Returns: JSON array of matrix resource names.

### `extract_palette`

```text
extract_palette(filename: str = '', max_colors: int = 16, with_alpha: bool = False) -> str
```

源码：[`aseprite_mcp/tools/native_fx.py:233`](../../aseprite_mcp/tools/native_fx.py#L233)

Build an OPTIMAL palette from the sprite via native ColorQuantization. True palette extraction (vs the nearest-snap quantize_to_palette): writes the resulting palette to the sprite and returns it. NOTE: mutates the sprite's palette. Sprite must be in RGB mode. `max_colors` is a slot budget, not a promise of that many colours: Aseprite always reserves palette slot 0 for the sprite's transparent colour, and the quantiser's median cut can also come up short. Expect at most max_colors - 1 usable colours, sometimes fewer — and asking for max_colors + 1 does not reliably recover the difference. The returned `palette_size` and `max_colors` make the shortfall visible.

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `filename` | `str` | `''` | Aseprite file to modify (optional; defaults to the session's active file) |
| `max_colors` | `int` | `16` | palette slot cap, 1..256 (fewer if the art has fewer) |
| `with_alpha` | `bool` | `False` | include alpha when quantizing |
