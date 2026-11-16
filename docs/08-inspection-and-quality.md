# 08 · 读取、分析与质量校验

> 从精灵里读回像素与统计信息、渲染可视结果用于检查，以及审计动画的结构一致性。
> 覆盖源文件：[`tools/pixel_read.py`](../aseprite_mcp/tools/pixel_read.py) · [`tools/analysis.py`](../aseprite_mcp/tools/analysis.py) · [`tools/quality.py`](../aseprite_mcp/tools/quality.py)

像素与 analysis 工具直接调用；quality 工具经 `search_tools(category="quality")` 发现后使用 `call_tool` 执行。完整签名见 [工具参考](reference/tools.md)。

## 职责边界

**负责**：单个 cel 的像素读取、可见合成结果的像素读取、帧差异对比、颜色直方图、洋葱皮渲染、图层/ cel 覆盖度校验与动画结构归一化。

**不负责**：

- 修改像素 → [03 · 绘图与像素编辑](03-painting.md) 与 [06 · 特效与网格结构](06-effects-and-tilemap.md)
- 把结果写成文件交付 → [07 · 导出与预览](07-output.md)
- 帧/cel/tag 的语义与补间 → [05 · 动画](05-animation.md)
- tilemap 的瓦片读取（`get_tile_at` 在 [`tilemap.py`](../aseprite_mcp/tools/tilemap.py)） → [06 §5](06-effects-and-tilemap.md#五tilemap)

这三个模块构成项目的**自检能力**：让模型能"看"自己的产出（`export_frame` + 预览，或这里的合成读取与统计）并在交活之前自查结构问题。`analysis.py` 与 `pixel_read.py` 里的合成逻辑是共享的 —— `pixel_read` 直接 `from .analysis import _COMPOSE_FRAME`。

---

## 一、两族读取工具

`pixel_read.py` 的四个工具分成**语义完全不同**的两族，混用是这里最常见的错误。

| 工具 | 读什么 | 是否看可见性 | 是否合成 |
|---|---|---|---|
| `get_pixel_color` | 单个 cel 的一个像素 | **否** | 否 |
| `get_pixels_rect` | 单个 cel 的一块矩形 | **否** | 否 |
| `get_composite_pixel` | 可见合成结果的一个像素 | **是** | 是 |
| `get_composite_rect` | 可见合成结果的一块矩形 | **是** | 是 |

docstring 对单 cel 族的描述很直白（[`pixel_read.py:13-15`](../aseprite_mcp/tools/pixel_read.py)）：

> This is a single-cel read: it ignores layer visibility and everything drawn above or below. For "what the player sees", use `get_composite_pixel` instead.

也就是说：`get_pixel_color(layer_name="armor")` 读的是**图层 `armor` 自己的 cel 文件**，无论它是否隐藏，也不管上面压着什么、下面垫着什么。

**该用哪个**：做配色/对比度/明度检查、判断"玩家实际看到什么"时，一律用合成族。想检查某个具体图层的原始数据（例如确认某个像素到底写没写进去）才用单 cel 族。

还有第三种读法：`get_sprite_map` 把一块矩形读成**字符网格**（紧凑、且 `rows`/`palette` 可原样回灌给 `draw_sprite_map`）。它归 [03 §三](03-painting.md#字符网格sprite-map)，因为它必须与写入端共享同一套格式约定。要逐像素断言用 `get_pixels_rect`；要"看整体形状 + 改一处"用 `get_sprite_map`。

### 坐标与越界

对外一律 **sprite 全局坐标**，内部减去 cel 偏移转成 cel-local（[`pixel_read.py:53-55`](../aseprite_mcp/tools/pixel_read.py)）：

```lua
local img = cel.image
-- Coordinates are sprite-global; offset into cel-local space.
local cx = {x} - cel.position.x
local cy = {y} - cel.position.y
```

**越界不报错，返回透明黑**（`r=g=b=a=0`）：

```lua
local r, g, b, a = 0, 0, 0, 0
if cx >= 0 and cy >= 0 and cx < img.width and cy < img.height then
    ...
end
```

所以矩形读取总是返回 `width × height` 个点，画布外的那些是 `#000000`/`a=0`。这一点在批量采样时很有用（形状统一），但要小心别把"越界"误读成"那里是黑的" —— 判据是 `a == 0`。

### 输出格式不同

| 工具 | 返回 |
|---|---|
| `get_pixel_color` / `get_composite_pixel` | 文本：`#d04648 (r=208, g=70, b=72, a=255)` |
| `get_pixels_rect` / `get_composite_rect` | `json.dumps` 的数组，每点 `{x, y, hex, r, g, b, a}` |

单点返回文本而矩形返回 JSON 是历史不一致，写调用方代码时要注意。

### 显式目标与错误

单 cel 读取要求明确 `layer_name` 和 `frame_index`，直接查找对应 cel。`execute_lua_script` 异步返回 stdout，读取工具将行首 `ERROR:` 转为 `ToolError` 并解析 `PIXEL:`。缺少预期像素记录时失败；矩形结果须覆盖完整请求区域。

合成工具按选定帧读取可见图层；调用方可用 `get_sprite_map(composite=true)` 获取紧凑审阅网格。精确 RGBA 回灌使用单 cel RGB 网格及其 `lossy` 标志，见 [03](03-painting.md)。

## 二、`_COMPOSE_FRAME`：为什么不能直接用 `flatten()`

这是整个项目里最重要的一段基础设施，位于 [`analysis.py:17-63`](../aseprite_mcp/tools/analysis.py)，并被 `pixel_read` 复用。

### 问题

**`Sprite:flatten()`（Aseprite 1.3.x）会把隐藏图层也合并进去。** 于是"展平一个副本再读像素"这个最直觉的做法，得到的是**玩家永远看不到的颜色**。这不是小误差 —— 隐藏层的颜色会污染配色统计和帧差异结果。

### 为什么不是自己实现渲染器

模块注释把权衡写清楚了（[`analysis.py:11-16`](../aseprite_mcp/tools/analysis.py)）：

> Rather than re-implementing the renderer — blend modes, group opacity and tilemap rasterisation are all easy to get subtly wrong — drop every invisible layer from a throwaway clone and only then flatten. The merge stays Aseprite's own code, so the result agrees with `export_frame` pixel for pixel.

即：自己实现混合模式、组不透明度和 tilemap 光栅化太容易出细节错误。改成"**先删掉不可见的，再让 Aseprite 自己合并**"。

### 实现

```lua
local function visible_clone(spr)
    local clone = Sprite(spr)

    -- flatten() needs a layer to produce, and this also keeps the sprite from
    -- reaching zero layers while the hidden ones are being deleted.
    local keep = clone:newLayer()
    keep.name = "__visible_only__"

    local doomed = {}
    local function scan(layers)
        for _, layer in ipairs(layers) do
            if not layer.isVisible then
                doomed[#doomed + 1] = layer
            elseif layer.isGroup then
                -- A hidden group takes its children with it, so do not descend
                -- into it: they would be collected twice and the second delete
                -- would fail.
                scan(layer.layers)
            end
        end
    end
    scan(clone.layers)
    for _, layer in ipairs(doomed) do clone:deleteLayer(layer) end

    clone:flatten()
    return clone
end
```

三处不能省的细节：

1. **占位层 `__visible_only__`**。`flatten()` 需要有图层可产出，同时在逐个删隐藏层的过程中不能把 sprite 删到零图层 —— 加了它，后续删除永远有落脚点。
2. **不递归进隐藏组**。隐藏组会连带隐藏子层，所以子层已经被"隐藏组"这一次收集覆盖了。若继续下钻，子层会被收进 `doomed` **两次**，第二次 `deleteLayer` 就会失败。
3. **只在可见组上下钻**。`elseif layer.isGroup then scan(layer.layers)` 这一支保证可见组里的隐藏子层仍会被单独收集。

### 合成结果

```lua
local function compose_frame(spr, frame_idx, bg)
    local clone = visible_clone(spr)
    local img = Image(spr.width, spr.height, ColorMode.RGB)
    if bg then
        -- 逐像素铺底
    end
    local layer = clone.layers[#clone.layers]
    local cel = layer:cel(clone.frames[frame_idx])
    if cel then
        img:drawImage(cel.image, cel.position)
    end
    return img
end
```

- 输出是**画布大小**的 RGB 图，所以 cel 偏移与裁剪问题自动消失（这正是 `analysis.py` 注释里说的"layer offsets and trimmed cels do not skew results"）。
- `bg` 给 `render_onion_skin` 铺白底用，其它工具传 `nil`（保持透明背景）。
- `clone.layers[#clone.layers]` 取最顶层 —— `flatten()` 的产物。

### 一致性保证

**结果与 `export_frame` 写出的 PNG 逐像素一致**，因为合并这一步是 Aseprite 自己的代码。这个不变量被测试直接锁定：[可见工作流](../tests/test_visual_workflow.py)。

写新的"合成读取"类工具时**必须**复用 `_COMPOSE_FRAME`，不要自己调 `spr:flatten()`。

---

## 三、`analysis.py` 的图像分析工具

| 工具 | 产物 | 关键参数 |
|---|---|---|
| `render_onion_skin` | **写一个 PNG 文件** | `frame_index`、`output_filename`、`before`、`after`、`scale`、`ghost_opacity` |
| `compare_frames` | JSON（内存内） | `frame_a`、`frame_b` |
| `get_color_stats` | JSON（内存内） | `frame_index`、`top` |

只有 `render_onion_skin` 写文件，另外两个纯计算。`render_onion_skin` 的输出路径同样遵守[输出路径铁律](02-paths-errors-lifecycle.md)（`must_exist=False, anchor=False`，[`analysis.py:90`](../aseprite_mcp/tools/analysis.py)）。

### `render_onion_skin`：批量模式下的"洋葱皮"

`render_onion_skin` 将当前帧和邻帧幽灵合成为可查看的 PNG，适用于 batch 审阅。

要点：

- 白底（`bg` 非空），因为洋葱皮叠在一起需要不透明背景才看得清。
- **残影从远到近绘制，让近的帧盖住远的**（`for offset = before, 1, -1`）：越靠近当前帧的幽灵越在上面，符合直觉。
- 残影用 `ghost_opacity` 经 `BlendMode.NORMAL` 画，当前帧用 alpha 255 画在最上层。
- 放大是**手写的最近邻循环**，不是 `img:resize`：

  ```lua
  local big = Image(comp.width * s, comp.height * s)
  ```

  这样保证是硬边放大，不会引入插值。

`before` / `after` 缺省都是 1，`scale` 缺省 4，`ghost_opacity` 缺省 100。

### `compare_frames`：帧差异

核心判定（[`analysis.py:203-217`](../aseprite_mcp/tools/analysis.py)）：

```lua
local aa = app.pixelColor.rgbaA(va)
local ab = app.pixelColor.rgbaA(vb)
local diff
if aa == 0 and ab == 0 then
    diff = false
else
    diff = va ~= vb
end
```

**两个都完全透明时不算变化。** 这是必要的特例：透明像素的 RGB 分量在 Aseprite 里可能是任意值，逐值比较会把"两处都空着"报成差异。

`min_x/min_y` 初值是 `math.huge`，而没有差异时 `math.huge` 无法用 `%d` 格式化，所以显式重置（[`analysis.py:221-224`](../aseprite_mcp/tools/analysis.py)）：

```lua
if changed == 0 then
    -- math.huge has no integer representation for %d
    min_x, min_y, max_x, max_y = 0, 0, -1, -1
end
```

Python 侧解析 `DIFF:` 行，`percent_changed` 保留两位小数，**`changed_bounds` 只在真的有差异时出现**（[`analysis.py:245-251`](../aseprite_mcp/tools/analysis.py)）—— 所以调用方要用 `"changed_bounds" in result` 判断，不能假定字段恒在。

输出形状：

```json
{
  "frame_a": 1, "frame_b": 2,
  "changed_pixels": 128, "total_pixels": 1024,
  "percent_changed": 12.5,
  "changed_bounds": {"x": 8, "y": 8, "width": 16, "height": 16}
}
```

### `get_color_stats`：配色纪律检查

合成可见图层后统计**不透明**像素的颜色直方图（[`analysis.py:292-304`](../aseprite_mcp/tools/analysis.py)），三段协议 `COLOR:` / `OPAQUE:` / `UNIQUE:`，Python 侧按 count 降序排后返回：

```json
{
  "frame": 1,
  "unique_colors": 7,
  "opaque_pixels": 640,
  "top_colors": [{"color": "#D04648", "count": 256}, ...]
}
```

`unique_colors` 是 Lua 侧数出来的去重数，**不受 `top` 截断影响** —— `top` 只限制 `top_colors` 返回几项（缺省 16）。它的用途是发现"近似的重复颜色"这类像素画常见问题（docstring 原话：*too many near-duplicate colors is a common pixel-art mistake*）。

---

## 四、tilemap 图层为什么不能逐像素读取

`pixel_read` 的两个单 cel 族工具会**显式拒绝** tilemap 图层（[`pixel_read.py:43`](../aseprite_mcp/tools/pixel_read.py)）：

```lua
if target.isTilemap then print("ERROR:Layer '{safe_layer}' is a tilemap layer: its cel stores tile indexes, not pixels, so a per-pixel read would return an index in the red channel instead of a colour. Existing layers: [" .. layer_names(spr) .. "]. Tip: use get_tile_at for the tile index at a grid cell, or get_composite_pixel / get_composite_rect for the rendered colour.") return end
```

原因是**数据模型不同**：tilemap 的 cel 是 `ColorMode.TILEMAP`，每个"像素"存的是一个**打包的瓦片索引**，不是一个颜色。`img:getPixel` 拿回来的是那个打包值，`rgbaR(v)` 取到的红通道其实是索引低位。用 `get_pixel_color` 读 tilemap 会得到一堆看起来像颜色、实际是索引的数字。

**替代方案**（错误消息里就给了）：

| 想要什么 | 用哪个 |
|---|---|
| 某个网格格子的**瓦片索引** | `get_tile_at`（[06 §5](06-effects-and-tilemap.md#两个读取工具)） |
| 某处的**渲染后颜色** | `get_composite_pixel` / `get_composite_rect`（合成会光栅化瓦片） |

合成族不受影响，因为 `_COMPOSE_FRAME` 交给 Aseprite 自己合并，瓦片光栅化是它的事 —— 这正是第二节那句"自己实现 tilemap 光栅化容易出错"所规避的。

---

## 五、`quality.py`：结构校验器，不是评分器

**先说清楚这个名字容易造成的误解**：这个模块**没有任何数值评分、没有权重、没有阈值、没有 pass/fail 判定**。它做的是结构完整性校验（哪些图层/cel 缺失、哪些 cel 落在声明范围之外、哪些声明的图层对在重叠），并把结果以 JSON 报出来。

唯一的"阈值"是两个**截断上限**（`max_overlaps` / `max_out_of_range`，缺省都是 200），用来防止结果体积失控，配套的 `*_truncated` 布尔量会告诉调用方"还有更多没列出来"。

四个工具分两类：

| 工具 | 只读 | 会改文件 |
|---|---|---|
| `ensure_layers_present` | | ✓ 补建缺失的 cel |
| `validate_scene` | ✓ | |
| `audit_animation` | ✓ | |
| `animation_sanitize` | | ✓（但 `report_only=True` 时是干跑） |

### 输入字符串的解析

两个工具接收"人写的紧凑格式"，解析全在 Python 侧，且**无效项静默跳过**：

| 参数 | 格式 | 例 |
|---|---|---|
| `layer_frame_ranges` | `"layer:起-止[,起-止...]"` 的列表 | `["body:1-8,17-24", "clouds:1-12"]` |
| `overlap_pairs` | `"A,B"` 或 `"A:B"` 的列表 | `["body,armor", "glow:effects"]` |

`_parse_layer_frame_ranges`（[`quality.py:7-36`](../aseprite_mcp/tools/quality.py)）跳过没有 `:` 的条目、空的层名、无法解析成整数的区间、以及 `start <= 0` 或 `end < start` 的区间。`_parse_overlap_pairs`（[`quality.py:38-54`](../aseprite_mcp/tools/quality.py)）同理。

**后果**：写错格式不会报错，只是那条约束**没有生效**。比如把 `"body:1-8"` 写成 `"body 1-8"`（漏了冒号），你就得到了一份"没有任何越界 cel"的审计报告 —— 因为约束根本不存在。**用 `animation_sanitize` 的 `include_stats` + `alerts` 交叉确认约束确实生效了**，或者先用 `validate_scene` 确认图层名拼对了。

### `ensure_layers_present`

按名单在帧区间内给缺 cel 的图层补建**画布大小**的空 cel（`Image(spr.width, spr.height, spr.colorMode)` 锚在 `(0,0)`）。它是"先把结构铺平，再逐帧作画"的准备工作。

### `validate_scene`

只读，报三样东西（[`quality.py:174-190`](../aseprite_mcp/tools/quality.py)）：

```json
{
  "frames": 4,
  "range": {"start": 1, "end": 4},
  "missing_layers": ["glow"],
  "missing_cels": [{"layer": "body", "frame": 3}]
}
```

它有一处特殊的实现：脚本用 `__START__` / `__END__` / `__LAYERS__` 三个占位符，再用 `str.replace` 注入（[`quality.py:193-198`](../aseprite_mcp/tools/quality.py)）——因为这段脚本不是 f-string（里面有大括号 JSON 字面量），没法直接插值。同文件的其它工具都用 f-string，所以这是**局部不一致的做法**。

注意它的 `find_layer` 是**顶层非递归**的（[`quality.py:153-158`](../aseprite_mcp/tools/quality.py)），所以嵌套在组里的图层会被报成 `missing_layers`。

### `audit_animation`

只读审计，两件检查：

**1. 声明的图层对是否重叠。** 用标准 AABB 判定（[`quality.py:356-359`](../aseprite_mcp/tools/quality.py)）：

```lua
local overlap = a_pos.x < b_pos.x + b_w
    and a_pos.x + a_w > b_pos.x
    and a_pos.y < b_pos.y + b_h
    and a_pos.y + a_h > b_pos.y
```

四条都是**严格不等号**，所以**边缘刚好贴齐不算重叠**。

**2. 越界 cel**：位于"该图层声明的帧范围"之外的 cel 会被记进 `out_of_range`。没在 `layer_frame_ranges` 里声明的图层，其所有 cel 都算**在范围内**（`in_ranges` 对未声明的层返回 true）—— 所以这个检查只对你显式声明的图层生效。

输出信封（[`quality.py:382-434`](../aseprite_mcp/tools/quality.py)）：

```json
{
  "frames": {"start": 1, "end": 4},
  "summary": {
    "total_layers": 3, "layers_checked": 3, "total_cels": 12,
    "overlaps": 2, "overlaps_total": 5, "overlaps_truncated": false,
    "out_of_range": 0
  },
  "overlaps": [{"frame": 1, "a": "body", "b": "armor"}],
  "out_of_range": []
}
```

`overlaps` 是**截断后的列表**（最多 `max_overlaps` 条），`overlaps_total` 才是真实总数。要判断"有没有被截断"看 `overlaps_truncated`。`report_cels=True` 时额外带 `cels` 数组（每帧的 cel 清单），`report_bounds=True` 时重叠条目额外带 `a_bounds` / `b_bounds`。

### `animation_sanitize`

功能最全的一个，既审计又能修。`report_only=True` 时是**完整干跑** —— 所有检查都做、`sanitized` 计数都算，但**不写文件**（[`quality.py:761-763`](../aseprite_mcp/tools/quality.py)）：

```lua
if not {report_only_flag} and changed then
    save_project(spr)
else
    print("PROJECT_UNCHANGED")
end
```

四种可选修复：

| 修复 | 触发参数 | 行为 |
|---|---|---|
| 图层重排 | `layer_order=["a","b","c"]` | 按名单设 `layer.stackIndex` |
| 补建 cel | `ensure_layers=["body"]` | 缺失的 cel 补成画布大小空图 |
| 越界 cel 处理 | `out_of_range_action` | `set_opacity_zero`（默认）/ `delete_cels` / `none` |
| 重叠检测 | `overlap_pairs` | 见下 |

细节：

- **`layer_order` 按位置重排**：名单里的层依次排前面，未列到的层保持在后面（[`quality.py:607-622`](../aseprite_mcp/tools/quality.py)）。
- **存在组时跳过重排**（[`quality.py:591-606, 623-629`](../aseprite_mcp/tools/quality.py)）。`has_groups` 会在两种情况下置真：sprite 里有任何 `isGroup` 图层，或目标图层的 `parent` 不一致。跨组设 `stackIndex` 语义不明确，所以直接放弃。此时仍报 `sanitized.reordered = not has_groups`，所以读到 `"reordered": true` 表示"**重排生效了**"（或"在 `report_only` 下本来会生效"），`false` 表示被跳过。
- **`out_of_range_action` 的默认值 `set_opacity_zero`** 把越界 cel 的 `opacity` 设为 `out_of_range_opacity`（默认 0），而不是删除。这是"可恢复"的默认：像素还在，只是看不见，反悔成本低。
- **`ignore_full_canvas_overlaps` 默认 `True`**：只要参与重叠检测的任一 cel 是**整张画布**大小就跳过该对（[`quality.py:709-717`](../aseprite_mcp/tools/quality.py)）。因为全画布层几乎必然与任何层重叠，这类命中是噪声。

输出信封在 `audit_animation` 的基础上多了修复计数与统计：

```json
{
  "frames": {"start": 1, "end": 4},
  "reordered": true, "ensured": 2, "out_of_range": 0,
  "opacity_set": 0, "deleted": 0,
  "analysis": {
    "total_layers": 3, "layers_checked": 3, "total_cels": 14,
    "empty_frames": 0, "overlaps": 0, "overlaps_total": 0,
    "overlaps_truncated": false, "inactive_layers": []
  },
  "layer_stats": {
    "body": {"frames_active": 4, "cel_count": 4, "full_canvas_cels": 4, "bounds": [0, 0, 32, 32]}
  },
  "alerts": ["full_canvas_cels:body"],
  "overlap_samples": []
}
```

- `layer_stats` 由 `include_stats=True`（默认）控制，`bounds` 是该层所有 cel 的并集包围盒（`[min_x, min_y, max_x, max_y]`），没有 cel 时为 `null`。
- `alerts` 是**派生出来的告警字符串**（[`quality.py:811-822`](../aseprite_mcp/tools/quality.py)）：`empty_frames_detected`、`cels_out_of_range`、以及每个有全画布 cel 的层一条 `full_canvas_cels:<layer>`。这是最该被调用方检视的字段。
- `inactive_layers` 是整个区间内**一个 cel 都没有**的图层。

---

## 六、陷阱表

| 项 | 说明 |
|---|---|
| **两族读取语义完全不同** | 单 cel 族无视可见性；要"玩家看到的"必须用合成族 |
| 省略 `layer_name` 语义不稳定 | 回退到 `app.activeCel`，等于文件里当前选中的图层 |
| 越界像素返回透明黑而非报错 | 判据是 `a == 0`，不是颜色值 |
| `changed_bounds` 可能不存在 | 无差异时该字段被省略 |
| 单点返回文本、矩形返回 JSON | 格式不一致 |
| `pixel_read` 不用 `_checked` | 自己扫 `ERROR:`，因为要同时取数据行 |
| 不要自己 `flatten()` | 会合入隐藏层；复用 `_COMPOSE_FRAME` |
| tilemap 不能逐像素读 | cel 存的是索引；用 `get_tile_at` 或合成族 |
| **无效的 range/pair 字符串静默跳过** | 格式写错等于约束不存在，审计结果会"过于干净" |
| `overlaps` 是截断后的列表 | 真实总数看 `overlaps_total`，是否截断看 `overlaps_truncated` |
| `quality.py` 没有评分 | 名字像评分器，实际只做结构校验与截断 |
| 有组时 `layer_order` 被静默跳过 | 看 `reordered` 字段确认 |
| `out_of_range_action` 默认把不透明度设为 0 而非删除 | 是刻意选的可恢复默认 |
| `validate_scene` / `audit` 的层名查找是顶层非递归 | 组内图层会被报成缺失 |

---

## 相关测试

| 测试 | 验证链路 |
|---|---|
| [可见工作流](../tests/test_visual_workflow.py) | 可见层与组的合成、隐藏 cel 单独读取、颜色统计、帧差及审阅 PNG 与独立 CLI 渲染一致 |
| [MCP 工作流](../tests/test_mcp_workflow.py) | Lua 诊断、缺失目标上下文、坐标与路径拒绝、失败后继续编辑 |
| [可选扩展链路](../tests/optional/extension_workflows.py) | tilemap 索引读取与渲染色、错误像素读取提示、调色板透明槽 |

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md) —— `_checked` 与裸 `execute_lua_script` 的差别
- [04 · 画布、图层与跨文件复制](04-layers-and-canvas.md#六flatten_sprite-的隐藏图层陷阱) —— `flatten()` 陷阱的另一面
- [05 · 动画](05-animation.md) —— 逐帧编辑、复制与审阅
- [06 · 特效与网格结构](06-effects-and-tilemap.md#五tilemap) —— tilemap 的数据模型与 `get_tile_at`
- [reference/tools.md](reference/tools.md#pixel_readpy) —— 三个模块的完整签名
