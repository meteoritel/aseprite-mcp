# 06 · 特效与网格结构

> 本文档覆盖两个相互独立、但都属于"对已有结构做批量处理"的主题：**特效**（对像素做滤镜）与**网格/区域抽象**（tilemap 与 slice）。
> 覆盖源文件：[`tools/fx.py`](../aseprite_mcp/tools/fx.py) · [`tools/native_fx.py`](../aseprite_mcp/tools/native_fx.py) · [`tools/tilemap.py`](../aseprite_mcp/tools/tilemap.py) · [`tools/slices.py`](../aseprite_mcp/tools/slices.py)

## 职责边界

**负责**：描边、换色、HSL 调整、有序抖动、原生滤镜调用、色彩量化；tilemap 图层与 tileset 的读写、命名 slice（含九宫格中心与轴心点）的增删查。

**不负责**：

- 基础绘图图元 → [03 · 绘图与像素编辑](03-painting.md)
- 调色板的读写与色阶生成（`quantize_to_palette` 用**已有**调色板吸附） → [03 §7](03-painting.md#七调色板)。本文档的 `extract_palette` 是**从画面推导**调色板，两者互补
- 逐像素读取与合成分析 → [08 · 读取、分析与质量校验](08-inspection-and-quality.md)
- 原生命令包装的通用机制 → [01 §6](01-lua-bridge.md#六corenativepy原生命令为什么要包装)

---

## 第一部分：特效

## 一、两套实现的分工

`fx.py` 和 `native_fx.py` 做的是**同类事情**，但走完全不同的路径：

| | [`fx.py`](../aseprite_mcp/tools/fx.py) | [`native_fx.py`](../aseprite_mcp/tools/native_fx.py) |
|---|---|---|
| 实现者 | 本项目手写的逐像素 Lua 循环 | Aseprite 自己编译进去的滤镜 |
| 调用 | `img:getPixel` / `putPixel` 双循环 | `app.command.*{ui=false, ...}` |
| 作用对象 | 明确的 `cel.image` | **当前激活**的图层/帧，可用选区限定区域 |
| 包装 | 直接用 `execute_lua_script_checked` | 必须经 [`core/native.py`](../aseprite_mcp/core/native.py) 先激活目标 |
| 质量 | 简单、可读、可魔改 | 更好（引擎级算法，如正确的卷积与中值切分） |
| 速度 | 慢（Lua 逐像素） | 快（C++ 实现） |

`native_fx.py` 的模块 docstring 说明了它的定位（[`native_fx.py:1-9`](../aseprite_mcp/tools/native_fx.py#L1)）：

> These delegate to Aseprite's own engine filters instead of hand-rolling pixel math in Lua — higher quality and faster than the equivalents in fx.py. All verified to run headless under `--batch`. They are added ALONGSIDE the hand-rolled tools (outline_cel / adjust_hsl / quantize_to_palette stay) per the "deprecate, don't break" policy.

这就是**"deprecate, don't break"**：新工具与旧工具并存，旧工具保留不动，不删除也不改变行为。所以文档里会看到三对功能重叠的工具：

| 手写版（旧） | 原生版（新） |
|---|---|
| `outline_cel` | `outline_native` |
| `adjust_hsl` | `adjust_hsl_native` |
| `quantize_to_palette`（吸附到已有调色板） | `extract_palette`（从画面推导调色板） |

**选择建议**：能用原生版就用原生版。手写版的价值在于可读、可改，以及在不支持某些 `app.command` 的 Aseprite 版本上仍能工作。

---

## 二、`fx.py` 的五个工具

| 工具 | 作用范围 | 关键参数 |
|---|---|---|
| `outline_cel` | 单个 cel | `color`、`include_diagonals` |
| `replace_color` | 单个 cel | `from_color`、`to_color`、`tolerance` |
| `adjust_hsl` | 单个 cel | `hue_shift`（±360）、`saturation_shift` / `lightness_shift`（±100） |
| `apply_dither_gradient` | 矩形区域 | `color_start` → `color_end`、`horizontal` |
| `apply_dither_pattern` | 矩形区域 | `color_a` / `color_b`、`density` |

### `outline_cel` 的实现

先把原图 `clone()` 一份作为参考，再在原图上写（避免新写的描边像素被当成"不透明邻居"扩散出去）：

```lua
local src = img:clone()
local function opaque(x, y)
    if x < 0 or y < 0 or x >= src.width or y >= src.height then return false end
    return app.pixelColor.rgbaA(src:getPixel(x, y)) > 0
end
for py = 0, img.height - 1 do
    for px = 0, img.width - 1 do
        if app.pixelColor.rgbaA(src:getPixel(px, py)) == 0 then
            local touch = opaque(px - 1, py) or opaque(px + 1, py)
                          or opaque(px, py - 1) or opaque(px, py + 1)
            if not touch and {diag} then ... end
```

[`fx.py:59-81`](../aseprite_mcp/tools/fx.py#L59)。逻辑是"**透明像素**如果邻接不透明像素，就填成描边色"。`include_diagonals=False`（默认）是 4 邻域，`True` 额外看 4 个对角。

它用 `normalize_cel(..., false)` —— **不会**创建缺失的 cel，没有就报 `No cel at that layer/frame`。

### Bayer 4×4 有序抖动

两个抖动工具共用同一张矩阵和同一个判定式（[`fx.py:306-328`](../aseprite_mcp/tools/fx.py#L306)）：

```lua
local bayer = {
    { 0,  8,  2, 10},
    {12,  4, 14,  6},
    { 3, 11,  1,  9},
    {15,  7, 13,  5},
}
...
local f = ({axis}) / math.max(1, {span} - 1)
local threshold = (bayer[(py % 4) + 1][(px % 4) + 1] + 0.5) / 16
if f >= threshold then pset(img, px, py, c2) else pset(img, px, py, c1) end
```

要点：

- `(v + 0.5) / 16` 把 0–15 的矩阵值映射到 `(0, 1)` 区间，**+0.5 让阈值居中**，避免 `f == 0` 时整片偏色。
- `py % 4 + 1` 是 Lua 的 1-based 索引修正：矩阵是 4×4，取模后加 1。
- `f >= threshold` 决定取 `c2`（`color_end` / `color_b`）。
- 抖动矩阵是**位置相关**的，所以输出只有两种颜色，**不产生中间色** —— 这正是像素画需要它而不是线性插值的原因。

### 两个抖动工具的差异

| | `apply_dither_gradient` | `apply_dither_pattern` |
|---|---|---|
| 混合比例 | 沿一个轴从 0 线性升到 1 | 全区域恒定 `density` |
| 方向 | `horizontal`（默认 **False**，即自上而下） | 无 |
| `create_if_missing` | 有（默认 True） | 有（默认 True） |

注意 `apply_dither_gradient` 的 `horizontal` 默认值是 **`False`**，与 `drawing.apply_gradient_rect` 的默认 `True` **相反**。这是个容易踩的不一致。

两个工具都走 `ENSURE_LAYER` + `normalize_cel`，所以能自动创建缺失的顶层图层与 cel —— 这是 [commit `0f2bebf`](03-painting.md#三本子系统工具一览) 那批改动的产物，回归测试见 [`tests/test_visibility.py:239-265`](../tests/test_visibility.py#L239)。

---

## 三、`native_fx.py` 的七个工具

| 工具 | 包装的 `app.command.*` | 关键参数 |
|---|---|---|
| `outline_native` | `Outline` | `place`(outside/inside)、`matrix`(circle/square) |
| `adjust_hsl_native` | `HueSaturation` | `hue`(−180..180)、`saturation`/`lightness`(−100..100)、区域 |
| `adjust_brightness_contrast` | `BrightnessContrast` | `brightness`/`contrast`(−100..100)、区域 |
| `invert_colors` | `InvertColor` | 区域 |
| `apply_convolution` | `ConvolutionMatrix` | `matrix`（内置资源名）、区域 |
| `list_convolution_matrices` | — | 无（返回冻结名单） |
| `extract_palette` | `ColorQuantization` | `max_colors`(1..256)、`with_alpha` |

### 区域作用域

五个能作用于区域的工具用同一个约定（[`native_fx.py:36-37`](../aseprite_mcp/tools/native_fx.py#L36)）：

```python
def _region(x: int, y: int, width: int, height: int):
    return (x, y, width, height) if width > 0 and height > 0 else None
```

即**宽高都 > 0 才算限定区域**，否则 `None` 表示整个图层。返回的元组交给 `build_native_command_script`，由它转成：

```lua
spr.selection = Selection(Rectangle(x, y, w, h))
```

执行完再 `deselect()`。这是唯一用 Aseprite **选区**机制限定作用范围的地方（[01 §6](01-lua-bridge.md#六corenativepy原生命令为什么要包装)）。

### 卷积矩阵名单是被冻结的

`CONVOLUTION_MATRICES`（[`native_fx.py:20-33`](../aseprite_mcp/tools/native_fx.py#L20)）是 **Aseprite 内置资源 `data/convmatr.def` 的名字快照**，38 项：

| 类别 | 名字 |
|---|---|
| 基础 | `brightness` `contrast` `negative` |
| 模糊 | `blur-3x3` `blur-3x3-hard` `blur-5x5` `blur-7x7` `blur-9x9` `blur-17x17` |
| 方向模糊 | `blur-5x3-left` `blur-17x3-left` `blur-3x17-top` `blur-5x5-diagonal(\)` `blur-5x5-diagonal(/)` |
| 锐化 | `sharpen-3x3` `sharpen-5x5` `sharpen-7x7` |
| 边缘 | `edges-find` `edges-find-horizontal` `edges-find-vertical` |
| 杂项 | `misc-contour` `misc-texturize` `misc-emboss` `misc-marmolize` `misc-rock` `misc-rock-edges` |
| 抖动位移 | `drunk-3x3_x` `drunk-3x3_+` `drunk-5x5_x` `drunk-5x5_+` `drunk-7x7_x` `drunk-7x7_+` `drunk-9x9_x` `drunk-9x9_+` `drunk-17x17_x` `drunk-17x17_+` `drunk-17x17_o` |
| 透明层描边 | `outline-transparent-layer-(cross)` `outline-transparent-layer-(square)` |

它是 `frozenset`，校验在 Python 侧完成（不合法就报错），所以**名字拼错会在拼脚本前被拦下**。`list_convolution_matrices` 就是把这个集合排好序返回，让调用方能发现可用值。

**局限**：名单是**硬编码的快照**。上游 Aseprite 新增的矩阵不会自动出现在这里，需要手工同步。

### `extract_palette` 的槽位语义

这是全套工具里语义最绕的一个，docstring 花了很长篇幅解释（[`native_fx.py:238-263`](../aseprite_mcp/tools/native_fx.py#L238)）：

> `max_colors` is a slot budget, not a promise of that many colours: Aseprite always reserves palette slot 0 for the sprite's transparent colour, and the quantiser's median cut can also come up short. Expect at most `max_colors - 1` usable colours, sometimes fewer — and asking for `max_colors + 1` does not reliably recover the difference.

实现上的关键处理（[`native_fx.py:278-291`](../aseprite_mcp/tools/native_fx.py#L278)）：

```lua
-- Slot 0 of an Aseprite palette is conventionally the transparent colour
-- (alpha 0). It paints nothing, so listing it as a colour invents a
-- duplicate "#000000" whenever the art really contains black; report it
-- apart from the colours instead.
print("PALETTE_SIZE:" .. #pal)
local transparent_index = -1
for i = 0, #pal - 1 do
    local c = pal:getColor(i)
    if c.alpha == 0 then
        if transparent_index < 0 then transparent_index = i end
    else
        print(string.format("PALETTE:#%02X%02X%02X", c.red, c.green, c.blue))
    end
end
print("TRANSPARENT:" .. transparent_index)
```

返回的 JSON：

```json
{
  "colors": ["#1D2B53", "#7E2553"],
  "count": 2,
  "transparent_index": 0,
  "max_colors": 8,
  "palette_size": 3
}
```

**两个副作用必须知道**：

1. **它会改写 sprite 的调色板**（`ColorQuantization` 会写进去），然后 `saveAs` 保存。它不是只读工具。
2. **要求 sprite 处于 RGB 模式**。索引色模式下量化没有意义。

`count` 是**可用颜色数**（`palette_size - 1`，当存在透明槽时），`palette_size` 是**实际槽位总数**。别用 `max_colors` 去规划配色，用 `palette_size`。

---

## 四、已知不一致

| 项 | 说明 |
|---|---|
| `tilemap.py` 有本地 `_parse_hex_color` | 只支持 6 位、无 alpha，**未**统一到 `core/colors.py`（[`tilemap.py:9-16`](../aseprite_mcp/tools/tilemap.py#L9)） |
| `native_fx` 从 `fx` 借用解析器 | `from .fx import _parse_hex_color`（[`native_fx.py:16`](../aseprite_mcp/tools/native_fx.py#L16)），而 `fx` 的那份是 `parse_hex_color` 的 `rgba[:3]` 包装 —— 所以原生特效**不支持 alpha 颜色** |
| 三个功能重复对 | 见第一节的表格，属刻意的 "deprecate, don't break" |
| 抖动渐变方向默认值相反 | `apply_dither_gradient(horizontal=False)` vs `drawing.apply_gradient_rect(horizontal=True)` |
| 卷积矩阵名单硬编码 | 上游新增不会自动出现 |

---

## 第二部分：网格与区域抽象

## 五、tilemap

### 瓦片尺寸是 sprite 级全局的

这是 tilemap 最容易搞错的一点：**瓦片尺寸不存在图层上，存在 sprite 的 `gridBounds` 上**（[`tilemap.py:62`](../aseprite_mcp/tools/tilemap.py#L62)）：

```lua
spr.gridBounds = Rectangle(0, 0, {tile_width}, {tile_height})
app.command.NewLayer { tilemap = true }
app.activeLayer.name = "{safe_layer}"
```

所以：

- 一个 sprite 只有**一套**网格尺寸，所有 tilemap 图层共享。
- 创建第二个 tilemap 图层时如果传不同的 `tile_width/height`，**网格会被改掉**，已有 tilemap 图层的解释随之变化。
- 网格原点是 `(0, 0)`，只存尺寸。

### tile 0 是保留的空格

瓦片索引 **0 恒为空**，真实瓦片从 1 开始。所以：

- `draw_on_tile` 拒绝 `tile_index < 1`（[`tilemap.py:98-99`](../aseprite_mcp/tools/tilemap.py#L98)）。
- tileset 的"真实瓦片数"是 `#ts - 1`（[`tilemap.py:136`](../aseprite_mcp/tools/tilemap.py#L136)）。
- `get_tilemap_info` 返回的 `tile_count` 是 `#ts - 1`。
- `set_tiles` 里 `tile_index = 0` 表示**清除该格**。

### 顶层判重

`create_tilemap_layer` 刻意**不用** `find_layer` 做判重（[`tilemap.py:52-59`](../aseprite_mcp/tools/tilemap.py#L52)）：

```lua
-- Duplicate-name guard is top-level only: the new layer is created at the
-- root, and Aseprite permits the same name inside a different group, so a
-- recursive find_layer would reject valid names.
local name_taken = false
for _, layer in ipairs(spr.layers) do
    if layer.name == "{safe_layer}" then name_taken = true break end
end
```

因为新层建在**顶层**，而 Aseprite 允许不同组里有同名图层 —— 用递归的 `find_layer` 判重会误拒合法名字。这与 [04 §1](04-layers-and-canvas.md#一图层树模型) 里"判重只看顶层"的原则一致。

### `draw_on_tile`：编辑 tileset

作用对象是 **tileset 里的一个瓦片**，不是某帧的某个格子。坐标是 **tile-local**（`(0,0)` = 瓦片左上角）。

追加瓦片的约定：**`tile_index == #ts` 时自动新建一个瓦片**（[`tilemap.py:138-141`](../aseprite_mcp/tools/tilemap.py#L138)）：

```lua
if idx == #ts then
    spr:newTile(ts)
end
```

`idx > #ts` 则报错并给出可用的追加索引：

```text
ERROR:tile_index out of range (tileset has 3 real tiles; pass 4 to append)
```

写入方式是**克隆 → 改 → 赋值**（[`tilemap.py:142-150`](../aseprite_mcp/tools/tilemap.py#L142)）：`tile.image:clone()` 后逐点 `putPixel`，最后 `tile.image = img`。局部 `put` 带边界判断。

颜色用 `app.pixelColor.rgba(r, g, b, 255)` 打包，**alpha 固定 255** —— 本地解析器也不支持 alpha。

### `set_tiles`：在帧上摆放瓦片

坐标是 **0-based 网格坐标**（`col` / `row`），映射尺寸由网格与画布推出（[`tilemap.py:208-209`](../aseprite_mcp/tools/tilemap.py#L208)）：

```lua
local cols = math.ceil(spr.width / tw)
local rows = math.ceil(spr.height / th)
```

**先全量预校验再动手**（[`tilemap.py:212-221`](../aseprite_mcp/tools/tilemap.py#L212)）：任一格越界或 `tile_index >= #ts` 就报错 `return`，一个格子都不写。这避免了"改了一半才失败"。

cel 的处理有一段迁移逻辑（[`tilemap.py:226-246`](../aseprite_mcp/tools/tilemap.py#L226)）：

```lua
if cel and cel.image.width == cols and cel.image.height == rows
   and cel.position.x == 0 and cel.position.y == 0 then
    img = cel.image                       -- 已经是标准形态，直接用
else
    img = Image(cols, rows, ColorMode.TILEMAP)
    if cel then                           -- 把旧图按网格偏移搬过来
        local ox = cel.position.x // tw
        local oy = cel.position.y // th
        for y = 0, old.height - 1 do
            for x = 0, old.width - 1 do
                local nx, ny = x + ox, y + oy
                if nx >= 0 and ny >= 0 and nx < cols and ny < rows then
                    img:putPixel(nx, ny, old:getPixel(x, y))
                end
            end
        end
    end
    cel = spr:newCel(target, frame, img, Point(0, 0))
end
```

即 cel 不是"画布网格大小且锚在 (0,0)"时，**整块重建**并按下取整的网格偏移搬迁旧数据。越界的旧格子被丢弃。

### 两个读取工具

| 工具 | 输出 | 说明 |
|---|---|---|
| `get_tile_at` | `TILE:<n>` → JSON `{col, row, tile_index}` | 0 表示空格。越界或没有 cel 时返回 0 |
| `get_tilemap_info` | `INFO:tw,th,count,cols,rows` → JSON | `tile_count` 已排除空格 |

`get_tile_at` 也要处理 cel 偏移（[`tilemap.py:303-304`](../aseprite_mcp/tools/tilemap.py#L303)）：

```lua
local cx = {col} - cel.position.x // grid.width
local cy = {row} - cel.position.y // grid.height
```

`tilemap` 的 cel 存的是**瓦片索引**而不是像素（用 `app.pixelColor.tileI` 从打包值里取出索引）。这正是 [08 §4](08-inspection-and-quality.md#四tilemap-图层为什么不能逐像素读取) 里"逐像素读取被拒绝"的原因。

### 全量工具

| 工具 | 关键参数 |
|---|---|
| `create_tilemap_layer` | `layer_name`、`tile_width`、`tile_height` |
| `draw_on_tile` | `tile_index`、`pixels=[{x,y,color}]`（tile-local） |
| `set_tiles` | `frame_index`、`tiles=[{col,row,tile_index}]`（0-based） |
| `get_tile_at` | `frame_index`、`col`、`row` |
| `get_tilemap_info` | `layer_name` |

---

## 六、slices

slice 是精灵里的**命名矩形区域**，游戏引擎用它切九宫格素材。与图层不同，**slice 是一个平坦列表**（`spr.slices`），没有嵌套，所以它有自己的查找函数而不是复用 `FIND_LAYER`（[`slices.py:6-13`](../aseprite_mcp/tools/slices.py#L6)）：

```lua
local function find_slice(spr, name)
    for _, slice in ipairs(spr.slices) do
        if slice.name == name then return slice end
    end
    return nil
end
```

### 坐标系

| 属性 | 参照 |
|---|---|
| `bounds`（`x`/`y`/`width`/`height`） | **sprite 全局** |
| `center`（九宫格可拉伸中心） | **相对 slice 原点** |
| `pivot`（轴心点） | **相对 slice 原点** |

`create_slice` 拒绝空名字与重复名字（[`slices.py:32-35`](../aseprite_mcp/tools/slices.py#L32), [`:43`](../aseprite_mcp/tools/slices.py#L43)）。`set_slice_center` / `set_slice_pivot` 都要求 slice 已存在。

### `list_slices` 的输出协议

这里有一个为了**健壮性**而刻意复杂化的设计（[`slices.py:158-160`](../aseprite_mcp/tools/slices.py#L158)）：

```python
# Emit one JSON object per slice (name via Lua %q) instead of a
# '|'-delimited line, so a '|' (or comma/colon) in a slice name can no
# longer break the parse for the whole sprite.
```

输出是**每个 slice 一行**、每行以 `SLICE:` 开头，末尾一行 `DONE`：

```lua
print("SLICE:{" .. table.concat(parts, ",") .. "}")   -- 每行一个完整 JSON 对象
print("DONE")
```

切片名用 Lua 的 `%q` 输出（`string.format("%q", slice.name)`），它会对引号和控制字符做正确转义。于是名字里含 `|`、`,`、`:` 都不会破坏解析 —— 而早期的"用 `|` 连接一行"方案在遇到这些字符时会整批解析失败。回归测试：[`tests/test_slices_pipe.py`](../tests/test_slices_pipe.py)。

Python 侧只 `json.loads` 每个 `SLICE:` 行并收进列表（[`slices.py:186-191`](../aseprite_mcp/tools/slices.py#L186)），最后整体 `json.dumps`。所以工具返回的是一个**JSON 数组**，而传输层用的是**逐行协议** —— 两层是分开的。

### 全量工具

| 工具 | 关键参数 |
|---|---|
| `create_slice` | `name`、`x`、`y`、`width`、`height` |
| `set_slice_center` | `name`、相对 slice 原点的矩形 |
| `set_slice_pivot` | `name`、相对 slice 原点的点 |
| `list_slices` | 无 |
| `delete_slice` | `name` |

---

## 七、陷阱表

| 项 | 说明 |
|---|---|
| 网格尺寸是 sprite 级 | 建第二个 tilemap 图层会覆盖已有网格；多 tilemap 图层共享一套瓦片尺寸 |
| tile 0 是空格 | `draw_on_tile` 拒绝 0；"真实瓦片数" 是 `#ts - 1`；`set_tiles` 用 0 清格 |
| 瓦片坐标与帧号进制不同 | `col`/`row` 0-based，`frame_index` 1-based |
| `draw_on_tile` 的 `tile_index` 是**追加索引** | 等于 `#ts` 时新建，不是"覆盖" |
| 网格越界处丢弃而非报错 | `set_tiles` 的迁移逻辑会丢掉越界的旧格子 |
| `extract_palette` 不是只读 | 改写并保存 sprite 调色板；要求 RGB 模式 |
| `extract_palette` 的颜色数上限是 `max_colors - 1` | 槽位 0 归透明色 |
| 卷积矩阵名单是硬编码快照 | 上游新增不会自动同步 |
| 抖动渐变方向默认值与 `apply_gradient_rect` 相反 | `False` vs `True` |
| 原生特效不支持 alpha 颜色 | 经 `fx._parse_hex_color` 丢掉了 alpha |
| `tilemap.py` 的本地颜色解析器只认 6 位 | 遗留不一致 |

---

## 相关测试

| 测试 | 覆盖 |
|---|---|
| [`tests/test_fx.py`](../tests/test_fx.py) | `outline_cel`、`replace_color`、`adjust_hsl`、两个抖动工具 |
| [`tests/test_native_fx.py`](../tests/test_native_fx.py) | 卷积矩阵列举与未知值拒绝、原生描边、精确反色、HSL、亮度对比、模糊、范围校验、`extract_palette` |
| [`tests/test_tilemap.py`](../tests/test_tilemap.py) | 创建 tilemap 图层、`draw_on_tile`、tilemap 信息、`set_tiles`/`get_tile_at`、越界索引被拒 |
| [`tests/test_slices.py`](../tests/test_slices.py) | 创建（重复名被拒）、中心、轴心、列举、删除 |
| [`tests/test_slices_pipe.py`](../tests/test_slices_pipe.py) | **回归**：slice 名字里含 `\|` 和 `,` 时 `list_slices` 仍能解析 |
| [`tests/test_visibility.py`](../tests/test_visibility.py) | **回归**：`extract_palette` 排除透明槽并遵守 N−1 预算、抖动工具自动建层与拒绝 |

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md#六corenativepy原生命令为什么要包装) —— `build_native_command_script` 的目标激活机制
- [03 · 绘图与像素编辑](03-painting.md#七调色板) —— `quantize_to_palette`（吸附到已有调色板）与 `extract_palette`（推导调色板）的分工
- [08 · 读取、分析与质量校验](08-inspection-and-quality.md#四tilemap-图层为什么不能逐像素读取) —— 为什么 tilemap 不能逐像素读
- [reference/tools.md](reference/tools.md#fxpy) —— 四个模块的完整签名
