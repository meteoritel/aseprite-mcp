# 03 · 绘图与像素编辑

文字与字体工具属于扩展：`search_tools(category="text")` 返回完整 schema，再用 `call_tool(name=目标名称, arguments=原参数对象)` 执行。本页其它绘图、选区、变换和调色板工具直接调用。

> 把像素画到画布上（含按字符网格批量作画）、把已有像素搬走或改色、以及文本栅格化与调色板。
> 覆盖源文件：[`tools/drawing.py`](../aseprite_mcp/tools/drawing.py) · [`tools/sprite_map.py`](../aseprite_mcp/tools/sprite_map.py) · [`tools/selection.py`](../aseprite_mcp/tools/selection.py) · [`tools/transform.py`](../aseprite_mcp/tools/transform.py) · [`tools/text.py`](../aseprite_mcp/tools/text.py) · [`tools/palette.py`](../aseprite_mcp/tools/palette.py) · [`core/fonts.py`](../aseprite_mcp/core/fonts.py)

## 职责边界

**负责**：图元的绘制、按字符网格的批量绘制与回读、像素的搬移与擦除、图像级几何变换（翻转/旋转/缩放/裁剪）、文本的栅格化与合成、调色板读写与色彩量化。

**不负责**：

- 图层本身的创建/删除/排序/混合模式 → [04 · 画布、图层与跨文件复制](04-layers-and-canvas.md)
- 帧与 cel 的生命周期、补间 → [05 · 动画](05-animation.md)
- 描边、换色、HSL、抖动、原生滤镜 → [06 · 特效与网格结构](06-effects-and-tilemap.md)（注意 `drawing.py` 只负责"画"，"改"归 06）
- 读取像素 → [08 · 读取、分析与质量校验](08-inspection-and-quality.md)。**一个例外**：`get_sprite_map` 作为 `draw_sprite_map` 的逆运算留在本文（[§三](#字符网格sprite-map)），因为这对工具的读写必须共享同一套格式约定

---

## 一、显式目标与落像素机制

绘图工具以 `layer_name` 和 `frame_index` 确定目标；参数必填，每次调用重新定位。`EDIT_TARGET` 验证层、帧与 cel；`create_if_missing=true` 时可以创建顶层裸名图层与 cel，组路径须预先存在。

逐像素、线、多边形、路径和渐变直接写 `Image`；矩形、圆、椭圆和填充使用 `app.useTool`。两条路径都走标准原生暂存保存，失败不提交。

## 二、坐标、颜色与笔刷约定

### 2.1 坐标系

对外统一为 sprite-global：原点在画布左上，x 向右、y 向下。Aseprite 保存时会裁紧 cel；绘图前用 `NORMALIZE_CEL` 将画布内原图放到画布大小的图像，并把位置设为原点，保证下一笔可以落在既有 cel 边界以外。该操作调整内部 cel 边界，保留原画布内像素。

图像复制使用源快照保留原始边界和偏移，见 [05 · 动画](05-animation.md)。

### 2.2 矩形的闭区间转换

`app.useTool` 把两个点当作**包含端点**的角，所以 width×height 的矩形第二个点在 `+width-1`（[`drawing.py:193-196`](../aseprite_mcp/tools/drawing.py)）：

```python
# app.useTool treats both points as inclusive corners, so the second
# point sits at (x+width-1, y+height-1) for a width x height rect.
x2 = x + width - 1
y2 = y + height - 1
```

而圆/椭圆传的是**外接矩形的两个角**，用 `center ± radius`（[`drawing.py:328-329`](../aseprite_mcp/tools/drawing.py)），不做 `-1`：半径 r 的圆在 Aseprite 语义下跨度是 `2r`。

### 2.3 笔刷：只有一个方形

`thickness` 出现在 `draw_line_at` / `draw_path` 上，实现是一个方形刷（[`drawing.py:110-117`](../aseprite_mcp/tools/drawing.py)）：

```lua
local function put_thick(img, x, y, color, size)
    local r = math.max(0, math.floor(size / 2))
    for oy = -r, r do
        for ox = -r, r do
            img:putPixel(x + ox, y + oy, color)
        end
    end
end
```

`thickness=1` 时绕过它直接写单像素。**没有**笔刷形状、没有抗锯齿、没有压感/抖动选项。

线本身是 Bresenham 实现（[`drawing.py:119-135`](../aseprite_mcp/tools/drawing.py)），多边形和路径复用同一份 `draw_line`。

### 2.4 颜色

唯一解析器是 [`core/colors.py`](../aseprite_mcp/core/colors.py) 的 `parse_hex_color`，接受 `#RGB` / `#RGBA` / `#RRGGBB` / `#RRGGBBAA`，见 [02 §6](02-paths-errors-lifecycle.md)。

各模块对 alpha 的态度不同：

| 模块 | 包装 | 行为 |
|---|---|---|
| [`drawing.py:10-12`](../aseprite_mcp/tools/drawing.py) | 直接使用 `parse_hex_color` | **保留** alpha，`#FF000080` 有效 |
| [`selection.py:8-11`](../aseprite_mcp/tools/selection.py)、[`palette.py:46-49`](../aseprite_mcp/tools/palette.py) | `rgba[:3]` | **丢弃** alpha |
| [`fx.py`](../aseprite_mcp/tools/fx.py) / [`native_fx.py`](../aseprite_mcp/tools/native_fx.py) | 转调 | 见 [06](06-effects-and-tilemap.md) |
| [`tilemap.py:9-16`](../aseprite_mcp/tools/tilemap.py) | 自己的副本 | 只支持 6 位、无 alpha —— 遗留不一致，见 [06 §5](06-effects-and-tilemap.md#四已知不一致) |

绘图工具的默认颜色是 `#000000`，文本是 `#FFFFFF`。

### 2.5 校验顺序

统一在拼 Lua 之前：`prepare_filename` → 尺寸/半径范围 → 颜色解析 →（`pixels` 的 `x`/`y` 强制转换）。所以 `draw_pixels_at` 会在**遍历 `pixels` 列表的过程中**逐个校验，遇到第一个坏的立刻返回，一个像素都不会落盘（[`drawing.py:53-63`](../aseprite_mcp/tools/drawing.py)）。

---

## 三、本子系统工具一览

| 工具 | 机制 | 关键参数 |
|---|---|---|
| `draw_pixels_at` | putPixel | `pixels=[{x,y,color}]`、`layer_name`、`frame_index` |
| `draw_sprite_map` | putPixel（字符网格整批） | `rows=[str]`、`palette={char:hex}`、`x,y`、`mirror_x/y`、`erase_transparent` |
| `get_sprite_map` | 单 cel 或合成读取（字符网格整批） | `x,y,width,height`、`palette`（回灌）、`max_colors`、`composite` |
| `draw_line_at` | putPixel + Bresenham | `x1,y1,x2,y2`、`thickness` |
| `draw_rectangle_at` | useTool | `x,y,width,height`、`fill` |
| `draw_circle_at` | useTool | `center_x,center_y,radius`、`fill` |
| `draw_ellipse_at` | useTool | `radius_x`、`radius_y`（可不等） |
| `draw_polygon` | putPixel + 扫描线填充 | `points=[{x,y}]`（≥3）、`fill` |
| `draw_path` | putPixel + Bresenham | `points`（≥2）、`thickness` |
| `fill_area_at` | useTool `paint_bucket` | `x,y` |
| `apply_gradient_rect` | putPixel 逐像素插值 | `color_start`、`color_end`、`horizontal` |
| `move_region` / `copy_region` | 读入 Lua 2D buffer 再写出 | 源矩形 + `dest_x/dest_y`（+ 目标层/帧） |
| `erase_region` / `erase_color` | putPixel | 矩形 / `color` + `tolerance` |
| `flip_layer` / `rotate_layer` | 全图读入再写回 | `direction` / `angle ∈ {90,180,270}` |
| `resize_canvas` / `crop_canvas` | `spr:resize` / `spr:crop` | 新尺寸 / 矩形 |
| `list_text_fonts` / `measure_text` / `draw_text` | Python 栅格化 + blit | 见第四节 |
| `get_palette` / `set_palette` / `list_palette_presets` / `apply_palette_preset` | Lua 调色板 | — |
| `generate_color_ramp` | 纯 Python（`colorsys`） | `base_color`、`steps`、`hue_shift_degrees` |
| `quantize_to_palette` | putPixel + 最近色缓存 | `layer_name`（空=全部顶层图像层）、帧区间 |
| `remap_colors_in_cel_range` | putPixel 精确替换 | `mappings=[{from,to}]`、`tolerance` |
| `set_color_mode` | `app.command.ChangePixelFormat` | `mode ∈ {rgb, grayscale, indexed}` |

完整签名与参数说明见 [reference/tools.md](reference/tools.md#drawingpy)（`sprite_map.py` 见 [该节](reference/tools.md#sprite_mappy)）。

### 多边形的扫描线填充

`draw_polygon(fill=True)` 自己实现了一条扫描线算法（[`drawing.py:820-850`](../aseprite_mcp/tools/drawing.py)）：按 y 求所有边的交点、排序、成对填充，交点用 `math.floor(x + 0.5)` 取整。顶点越界不会崩，因为走的是 `pset`（带边界判断）。回归测试：[`tests/test_drawing_fixes.py`](../tests/test_drawing_fixes.py)。

### 渐变的插值

`apply_gradient_rect` 逐像素线性插值，四个通道各自算（[`drawing.py:1056-1070`](../aseprite_mcp/tools/drawing.py)）：

```lua
t = (w > 1) and (ix / (w - 1)) or 0
local r = math.floor({sr} + ({er} - {sr}) * t + 0.5)
```

`w == 1` 时 `t = 0`，避免除零。`horizontal=False` 改用 `iy / (h - 1)`。

### 字符网格（sprite map）

`draw_sprite_map` 在 Python 侧解析等宽 rows 与字符 palette，生成坐标到 RGBA 的写入集合。先展开显式颜色和镜像；同色合并，异色相撞报错。`erase_transparent=true` 最后对未着色格擦除，因此 `A...` 水平镜像与擦除得到 `A..A`。区域偏移在展开后应用，区域外像素保留。

`transparent` 默认 `"."`；默认跳过已有像素，需要删除格子时显式启用擦除。颜色接受短／长 RGB 或 RGBA。绘图要求 RGB 工程。

`get_sprite_map` 返回 `rows`、`palette`、`transparent`、`columns` 与 `lossy`。默认 `max_colors=0, alpha_threshold=1`，保留所有有效 RGBA；单 cel 精确读取适合回灌。自定义透明字符与已占 palette 字符从自动字符池中排除；容量不足时报错，可分区或显式量化。

显式 alpha 阈值过滤有效像素，或量化实际改变颜色时 `lossy=true`。`composite=true` 复用可见合成，用于审阅；单 cel 读取要求明确层和帧，拒绝 tilemap 与非 RGB 编码。

## 四、文本与字体

### 4.1 为什么在 Python 侧栅格化

[`text.py:1-5`](../aseprite_mcp/tools/text.py) 与 [`fonts.py:1-5`](../aseprite_mcp/core/fonts.py) 把原因写得很直接：

> Aseprite's Lua API has no text drawing: there is no `Font` object and no `Image:drawText`, and the GUI text tool is an editor state that scripts cannot drive.

也就是 Aseprite 1.3 的脚本 API **没有**字体对象、没有 `Image:drawText`，GUI 的文字工具是编辑态、脚本驱动不了。所以 `core/fonts.py` 在 Python 侧把文字栅格化成一张 RGBA 图，再作为图片 blit 进 sprite。

字体栅格化与审阅图放大使用 Pillow。

### 4.2 两种字体后端

| 后端 | 来源 | `size` 的含义 | 适用 |
|---|---|---|---|
| **bitmap** | 一个目录，内含 `font.json` + 一张或多张 sheet PNG | **整数放大倍数**（≥1） | 像素画首选：字形本来就是像素，不会被重采样 |
| **truetype** | `.ttf` / `.otf` / `.ttc` 文件 | **像素高度** | 需要任意字号时 |

查找顺序（[`fonts.py:312-346`](../aseprite_mcp/core/fonts.py)）：先用户目录 `~/.aseprite-mcp/fonts`，再系统字体目录（`_SYSTEM_FONT_DIRS` 覆盖 macOS `/System/Library/Fonts`、`/Library/Fonts`、`~/Library/Fonts`，Linux `/usr/share/fonts`、`/usr/local/share/fonts`、`~/.fonts`，Windows `C:/Windows/Fonts`）。按名字**大小写不敏感**去重，用户字体优先。

`load_font(spec)`（[`fonts.py:352`](../aseprite_mcp/core/fonts.py)）先判断 `spec` 是不是路径（含分隔符或以字体扩展名结尾），是则直接加载；否则按名字查表。查不到抛 `FontError`，消息会引导调用 `list_text_fonts`。结果有模块级缓存 `_loaded`，`clear_cache()` 可清空。

### 4.3 `font.json` 结构

[`fonts.py:20-43`](../aseprite_mcp/core/fonts.py) 是权威 schema：

```json
{
  "name": "minecraft",
  "letter_gap": 1,
  "space_width": 3,
  "sheets": [{
    "file": "ascii.png",
    "cell_w": 8, "cell_h": 8,
    "ascent": 7,
    "origin": [0, 0],
    "ink_rule": "alpha",
    "advance": "ink",
    "chars": ["ABC...", "0123..."]
  }],
  "overrides": {
    "86": {"ascent": 7, "rows": ["#...#", ".#.#.", "..#.."]}
  }
}
```

几个容易忽略的设计：

- `chars` 是**每行一个字符串**，按行从左到右铺在 cell 网格上。`_index` 把 codepoint 映射到 (sheet, row, col)，**先到先得**（[`fonts.py:114-140`](../aseprite_mcp/core/fonts.py)）—— 所以一张紧凑 ASCII sheet 可以排在前面抢占字符。
- **每张 sheet 自带 `ascent`**，这正是"不同 cell 高度的多张 sheet 能共用一条基线"的实现方式。
- `ink_rule`: `"alpha"` 按 alpha 通道判断墨迹；`"dark"` 用于"不透明白底界定变宽字形框"的 sheet，靠扫描找不透明背景来推断字形框。
- `advance`: `"ink"` 按墨迹宽度推进（外加 `letter_gap`）；`"box"` 按 cell 框宽推进。
- `origin` 在 sheet 有边距时平移网格起点。
- `overrides` 用 `#`/`.` 的手绘行**替换**单个字形，用于原 sheet 里偏心或过高的字符。

### 4.4 字形坐标与度量

`shape(text, font, size, letter_spacing, bold, antialias, threshold)`（[`fonts.py:401-449`](../aseprite_mcp/core/fonts.py)）返回 `(ink, metrics)`。坐标语义很关键：

> Ink coordinates run from the pen origin on x and from the baseline on y, so anything above the baseline is negative.

即 **x 相对笔原点、y 相对基线，基线上方为负**。度量字典含 `advance_width` / `width` / `height` / `left` / `top` / `bottom`（后三者是墨迹的极值，`top` 通常为负）。

`bold` 用 `_dilate` 做伪粗体：**只向右和向下扩**，这样字腔（counter）不会被填死（[`fonts.py:394-398`](../aseprite_mcp/core/fonts.py)）。

TrueType 后端默认**不做抗锯齿** —— 把覆盖度按阈值切成硬边像素，这才是像素画要的（[`fonts.py:300-303`](../aseprite_mcp/core/fonts.py)）；`antialias=True` 才保留灰度边。

### 4.5 `draw_text` 的合成流程

[`text.py:184-220`](../aseprite_mcp/tools/text.py)：

1. 从字形集合算出三层：`ink`（字面）、`outline`（对 ink 做 `outline_width` 次膨胀，`outline_diagonal` 决定是否含对角邻居，**再减掉 ink**）、`shadow`（ink 平移 `shadow_dx/dy`，**再减掉 ink 与 outline**）。
2. 求三者并集的包围盒，决定 stamp 的尺寸。
3. 按 **shadow → outline → ink** 的顺序（从后往前）画到 PIL 的 RGBA 图上。
4. 存成临时 PNG，脚本里 `Image{ fromFile = "..." }` 载入，再 `cel.image:drawImage(stamp, Point(blit_x, blit_y), 255, BlendMode.NORMAL)`。

**anchor 只吸附字形盒**（[`text.py:206-208`](../aseprite_mcp/tools/text.py)）：

> The anchor is resolved against the glyph box alone, so adding an outline or a shadow never shifts where the letters themselves land.

即加轮廓或阴影会让 stamp 变大、但**字母位置不动**。12 个 anchor 取值（`topleft`/`top`/`topright`/`left`/`center`/`right`/`bottomleft`/`bottom`/`bottomright`/`baselineleft`/`baseline`/`baselineright`）在 `_text_origin` 里换算（[`text.py:28-49`](../aseprite_mcp/tools/text.py)）：`baseline*` 系列在 y 方向**完全不做修正**（因为 y 本来就相对基线），box 系列按墨迹高度偏移。

空文本或全是空白字符时，`ink` 为空，函数在任何脚本执行前就返回 `"OK: nothing to draw (text has no visible glyphs)"`（[`text.py:180-181`](../aseprite_mcp/tools/text.py)）。

### 4.6 目标图层与临时文件

`draw_text` 明确指定 layer/frame，沿用 `EDIT_TARGET` 与顶层图层创建规则。Pillow 将文字栅格化为临时 RGBA PNG，再由 Lua 合成到归一化 cel；标准编辑提交后清理临时图片。

## 五、选区与区域操作

四个工具都在**单个 cel** 上工作，源/目标 cel 的存在性要求不同：

| 工具 | 源 cel | 目标 cel |
|---|---|---|
| `move_region` | `normalize_cel(..., false)` → 不存在则报 `No cel at that layer/frame`（[`selection.py:55`](../aseprite_mcp/tools/selection.py)） | 同源 |
| `copy_region` | 同上（[`selection.py:146`](../aseprite_mcp/tools/selection.py)） | `normalize_cel(..., true)` → **按需创建**（[`selection.py:164`](../aseprite_mcp/tools/selection.py)） |
| `erase_region` | 直接取 `target:cel(...)` | 同源 |
| `erase_color` | 同上 | 同源 |

**图层**一律不自动创建：`copy_region` 会对源层和目标层分别查 `find_layer`，缺哪个就报 `<Source|Target> layer '...' not found` 并列出既有图层（[`selection.py:141-143`](../aseprite_mcp/tools/selection.py)）。

### 三个行为约定

**透明像素不覆盖目标。** 写出时检查 `app.pixelColor.rgbaA(v) > 0`（[`selection.py:77`](../aseprite_mcp/tools/selection.py), [`:169`](../aseprite_mcp/tools/selection.py)），所以拷贝一个带透明边缘的区域不会在目标上挖洞。

**`move_region` 是"读走即清零"**。它在读入 buffer 的同一次循环里把源像素写成 `0`（[`selection.py:66-67`](../aseprite_mcp/tools/selection.py)），`copy_region` 只读不清。

**越界处理不对称**：源越界读成 `0`（[`selection.py:69`](../aseprite_mcp/tools/selection.py)），目标越界被 `pset` 静默丢弃。所以"把区域移到画布外"不报错，只是像素没了 —— docstring 明确写了 `Pixels moved outside the canvas are discarded`。

`erase_region` 用 `math.max/math.min` 把矩形钳到画布内再写 0；`erase_color` 是带容差的魔术棒，逐通道比较 `abs(diff) <= tolerance`，且**只考虑 `alpha > 0` 的像素**（[`selection.py:289-303`](../aseprite_mcp/tools/selection.py)），返回 `COUNT:` 报告擦了多少个。

---

## 六、变换

**`flip_layer`** 把整个 `cel.image` 读进一个 Lua 二维表再镜像写回（[`transform.py:47-63`](../aseprite_mcp/tools/transform.py)），操作真实 `cel.image`，不做归一化。

**`rotate_layer`** 分两条实现（[`transform.py:94-136`](../aseprite_mcp/tools/transform.py)）：

| 角度 | 做法 |
|---|---|
| 180 | 原地读写（不会读写冲突，因为对称映射） |
| 90 / 270 | **新建** `Image(old_h, old_w, ...)`，映射写完后 `cel.image = new_img` |

⚠️ 90°/270° 的路径**没有调整 `cel.position`**。对非正方形的 cel，旋转后内容会相对原来的锚点发生位移。旋转整张画布大小的 cel（`position = (0,0)`）不受影响。

**`resize_canvas`** 是 `spr:resize(width, height)` —— 它**缩放内容**，不是改变画布尺寸并保持内容原尺寸。需要后者得用 `crop_canvas` 或自写 Lua。

**`crop_canvas`** 在调用 `spr:crop()` 前会先检查矩形是否完全落在画布外并报错（[`transform.py:202`](../aseprite_mcp/tools/transform.py)）。

---

## 七、调色板

### 内置预设

`PALETTE_PRESETS`（[`palette.py:11-44`](../aseprite_mcp/tools/palette.py)）8 套：`gameboy`(4) · `monochrome`(2) · `grayscale_4`(4) · `cga`(4) · `pico8`(16) · `c64`(16) · `dawnbringer16`(16) · `dawnbringer32`(32)。

`set_palette` 用 `Palette(n)` + 逐槽 `setColor` + `spr:setPalette` 重建调色板；`apply_palette_preset` 查表后 await 调用它，失败由 `ToolError` 传播（[`palette.py:274-277`](../aseprite_mcp/tools/palette.py)）。

### `generate_color_ramp`（纯 Python）

这是唯一一个**完全不碰 Aseprite** 的绘图类工具，在 Python 里用 `colorsys` 算，返回 JSON 数组（[`palette.py:303-326`](../aseprite_mcp/tools/palette.py)）：

```python
mid = (steps - 1) / 2
t = (i - mid) / (steps - 1)        # t ∈ [-0.5, 0.5]，负 = 暗侧
nh = (h - t * (hue_shift_degrees / 360)) % 1.0
nl = min(1.0, max(0.0, l + t * lightness_range))
ns = min(1.0, max(0.0, s - t * 0.15))   # 暗侧更饱和，亮侧更灰
```

三个可调维度：**色相按 t 反向旋转**（暗侧与亮侧朝相反方向偏），**明度线性展开** `lightness_range`，**饱和度在暗侧提高、亮侧降低**（固定的 ±0.15）。这就是像素画里 hue-shifting 阴影的标准做法。参数约束：`steps ∈ [2,16]`、`lightness_range ∈ [0,1]`。

### `quantize_to_palette`

把选中 cel 的不透明像素吸附到调色板最近色（[`palette.py:387-431`](../aseprite_mcp/tools/palette.py)）：

- 距离是 RGB 欧氏距离的平方（省一次开方）。
- 有 memo 缓存，键是 `r * 65536 + g * 256 + b`。
- 只处理 `alpha > 0` 的像素，**保留原 alpha**。
- 只在颜色真的变了才写回（`if c[1] ~= r or ...`），返回 `COUNT:` 报告改动数。
- `layer_name=""` 表示**全部顶层图像层**（`layer.isImage`），不递归进组。

### `remap_colors_in_cel_range`

按 `[{from, to}]` 映射表在多帧范围内做精确 RGB 替换，带 `source_frame_index`（从某一帧取参考）和 `create_missing_cels` 两个开关。用于批量换配色。

---

## 相关测试

| 测试 | 覆盖 |
|---|---|
| [`tests/test_drawing.py`](../tests/test_drawing.py) | `draw_ellipse_at` 画到中心、非法半径被拒 |
| [`tests/test_drawing_fixes.py`](../tests/test_drawing_fixes.py) | 多边形越界顶点不被静默裁剪、渐变落在 sprite 全局坐标、RGBA/短十六进制被接受、坏颜色被拒 |
| [`tests/test_text.py`](../tests/test_text.py) | 字体发现与报错、从磁盘 fixture 构建 bitmap 字体、度量/缩放/字距、粗体、基线、未映射字符、`overrides`、各 anchor、轮廓、空文本 no-op、TrueType（无系统字体则 skip） |
| [`tests/test_palette.py`](../tests/test_palette.py) | 预设列举、应用预设、未知预设被拒、量化、色阶、色彩模式往返 |
| [`tests/test_selection.py`](../tests/test_selection.py) | 区域复制/移动/擦除、按色擦除 |
| [`tests/test_pixel_xy_validation.py`](../tests/test_pixel_xy_validation.py) | `pixels` 的 `x`/`y` 非整数被拒（注入防护） |
| [`tests/test_visibility.py`](../tests/test_visibility.py) | 抖动工具的自动建层与拒绝、缺失图层报错带上下文 |
| [`tests/test_sprite_map.py`](../tests/test_sprite_map.py) | 字符网格落位与 `x,y` 锚点、`"."` 跳过 vs `erase_transparent` 擦除、镜像、四种非法输入被拒；`get_sprite_map` 的读→画→读像素完全一致、回灌 `palette` 后字符稳定、量化、合成读取、alpha 阈值 |

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md) —— `ENSURE_LAYER` / `NORMALIZE_CEL` / `PSET` 的确切语义
- [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md) —— `parse_hex_color` 的完整规则
- [04 · 画布、图层与跨文件复制](04-layers-and-canvas.md) —— 图层与组的创建/排序
- [06 · 特效与网格结构](06-effects-and-tilemap.md) —— 对已有像素做特效处理
- [reference/tools.md](reference/tools.md#drawingpy) —— 全部签名与参数默认值
