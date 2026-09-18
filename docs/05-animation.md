# 05 · 动画

> 帧与 cel 的生命周期、动画 tag、带缓动的补间与振荡，以及图层的可见性/不透明度。
> 覆盖源文件：[`tools/animation.py`](../aseprite_mcp/tools/animation.py) · [`tools/guide.py`](../aseprite_mcp/tools/guide.py)

## 职责边界

**负责**：帧的增删与时长、cel 的创建/复制/删除与位置和不透明度、tag 的增删改、位置/不透明度/缩放的补间与正弦振荡、图层可见性与不透明度、精灵元信息读取。

**不负责**：

- 图层/组的创建、排序、混合模式、合并展平 → [04 · 画布、图层与跨文件复制](04-layers-and-canvas.md)
- 往 cel 里画像素 → [03 · 绘图与像素编辑](03-painting.md)
- **洋葱皮的渲染** → [08 · 读取、分析与质量校验](08-inspection-and-quality.md)。本模块的 `set_onion_skin` 是 no-op，见 [第六节](#六onion-skin两个不同含义)
- 动画一致性审计与修复 → [08](08-inspection-and-quality.md#五qualitypy结构校验器不是评分器)
- 导出 → [07 · 导出与预览](07-output.md)

这是工具数最多的模块（24 个），因为"帧 × 图层 × 属性"的组合空间大。

---

## 一、帧模型

### 1-based 与闭区间

帧号**在所有地方都是 1-based**，区间一律用 `start_frame` / `end_frame` 的**闭区间**。校验片段在多个工具里逐字重复：

```lua
if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
    print("ERROR:Frame range out of bounds") return
end
```

单帧越界的消息更详细，会报出总帧数并提醒是 1-based（[`animation.py:374`](../aseprite_mcp/tools/animation.py#L374)）：

```text
ERROR:Frame index 5 out of range (sprite has 3 frame(s), 1-based). Tip: call add_frame first.
```

注意：**tilemap 的网格坐标和 slice/region 矩形坐标是 0-based**，只有帧号是 1-based。这个混用是 API 的历史产物，写新工具时不要"顺手统一"。

### 时长：对外毫秒，对内秒

Aseprite 用秒存 `frame.duration`，MCP 层对外一律毫秒，转换发生在生成 Lua 时（[`animation.py:25`](../aseprite_mcp/tools/animation.py#L25)）：

```python
duration_line = f"spr.frames[#spr.frames].duration = {duration_ms} / 1000.0"
```

回读时反向换算并四舍五入（[`animation.py:184`](../aseprite_mcp/tools/animation.py#L184)）：

```lua
table.insert(parts, tostring(math.floor(frame.duration * 1000 + 0.5)))
```

设置时长的工具有两个，分属两个模块：

| 工具 | 位置 | 作用范围 |
|---|---|---|
| `set_frame_duration` | [`canvas.py:213`](../aseprite_mcp/tools/canvas.py#L213) | 单个帧 |
| `set_frame_duration_all` | [`animation.py:48`](../aseprite_mcp/tools/animation.py#L48) | 所有帧 |

`add_frames(count, duration_ms)` 在循环里每建一帧就重设**最后一帧**的时长（[`animation.py:31-36`](../aseprite_mcp/tools/animation.py#L31)），所以每帧都会拿到 `duration_ms`。`duration_ms` 省略或 ≤0 时不设时长，新帧用 Aseprite 默认值。

---

## 二、cel 模型与生命周期

**cel 是 (图层, 帧) 交叉点上的图像单元。** 一个图层在某一帧上"没有 cel"就是空帧 —— 没有内容，也不占存储。

| 工具 | 语义 | 关键参数 |
|---|---|---|
| `create_cel` | 建一个**画布大小**的空 cel，锚在 `Point(x, y)` | `layer_name` `frame_index` `x` `y` |
| `clear_cel` | 删除该 cel（该帧该层变空） | `layer_name` `frame_index` |
| `copy_cel` | 单层跨帧复制，**可自动扩帧** | `source_frame` `target_frame` `replace` `create_target_frame` |
| `set_cel_position` | 设 `cel.position`；可顺带建 cel | `x` `y` `create_if_missing` `source_frame_index` |
| `set_cel_opacity` | 设 `cel.opacity`（0–255） | `opacity` |

### 两个不变的复制语义

**cel 图像必须 `clone()`。** 所有复制路径都是：

```lua
local img = cel.image:clone()
spr:newCel(layer, frame, img, cel.position)
```

直接传 `cel.image` 会让两个 cel 共享同一份像素数据。

**`cel.position` 被保留。** 复制出来的是被裁剪过的 cel 的**原尺寸与偏移**，不是画布大小。这与 `create_cel` 的行为相反 —— 后者明确建一张画布大小的图（[`animation.py:507-508`](../aseprite_mcp/tools/animation.py#L507)）。需要画布对齐的新 cel 用 `create_cel`，需要保留原样的用复制。

### 组图层永远被跳过

凡是遍历 `spr.layers` 的复制/传播逻辑都带这个守卫：

```lua
if not layer.isGroup then
```

出现于 [`animation.py:255`](../aseprite_mcp/tools/animation.py#L255)、[`:651`](../aseprite_mcp/tools/animation.py#L651)、[`:660`](../aseprite_mcp/tools/animation.py#L660)、[`:716`](../aseprite_mcp/tools/animation.py#L716)。组没有 cel，调用 `layer:cel(frame)` 只会得到 nil。

> 注意它是**非递归**的：`for _, layer in ipairs(spr.layers)` 只看顶层。所以嵌套在组里的图层不会被 `duplicate_frame_range` / `copy_frame` / `propagate_frame_to_range` 覆盖到。要处理组内图层请用 `propagate_cels(layer_names=[...])` 显式点名。

### `copy_cel` 的自动扩帧

`create_target_frame=True`（默认）时目标帧可以超出当前帧数，脚本会补齐（[`animation.py:591-593`](../aseprite_mcp/tools/animation.py#L591)）：

```lua
local frames_added = math.max(0, dst_idx - #spr.frames)
app.transaction(function()
    while #spr.frames < dst_idx do spr:newFrame() end
```

补了几帧通过自定义协议回传，Python 侧再解析（[`animation.py:608-620`](../aseprite_mcp/tools/animation.py#L608)）：

```lua
print("OK|frames_added=" .. frames_added)
```

```python
for line in output.splitlines():
    if line.startswith("OK|frames_added="):
        frames_added = int(line.split("=", 1)[1])
```

这是项目里唯一把 `OK` 扩展成带负载形式的标记（见 [01 §3](01-lua-bridge.md#标记总表)）。传 `create_target_frame=False` 则改为报错并提示两个选项。

---

## 三、帧序列操作

| 工具 | 语义 | 覆盖范围 |
|---|---|---|
| `duplicate_frame_range` | 克隆 `[start, end]` 的 cel 并**追加到末尾**，重复 `times` 次 | 所有顶层非组图层 |
| `copy_frame` | 把一帧的所有 cel 拷到 `target_frame`；`target_frame=None` 时**追加新帧** | 所有顶层非组图层 |
| `propagate_frame_to_range` | 把一帧的 cel 拷到整个区间 | 所有顶层非组图层 |
| `propagate_cels` | 同上，但只针对 `layer_names` 里点名的层 | 指定层 |
| `delete_frame` | 删除帧；**只剩一帧时拒绝** | — |

注意这三者的**覆盖范围都是顶层非组图层**，嵌套在组里的图层需要 `propagate_cels` 点名。

`propagate_cels` 解析层名用的是 `FIND_LAYER`，**找不到的名字被静默丢弃**（[`animation.py:857-861`](../aseprite_mcp/tools/animation.py#L857)）：

```lua
for _, name in ipairs(name_list) do
    local m = find_layer(spr, name)
    if m then table.insert(targets, m) end
end
if #targets == 0 then print("ERROR:No layers found") return end
```

只有在**一个都没匹配上**时才报 `ERROR:No layers found`。部分匹配失败不会告知 —— 想确认实际命中了哪些，先调 `get_sprite_info`。

---

## 四、tag 与播放方向

### `set_tag` 是 upsert

[`animation.py:777-788`](../aseprite_mcp/tools/animation.py#L777)：先按名字找，找到就改 `fromFrame` / `toFrame`，找不到就 `spr:newTag(start, end)`。无论哪条路径都会重设 `name` 与 `aniDir`，所以同一个调用既能创建也能更新。

### 四种方向

`direction` 映射到 `AniDir` 枚举（[`animation.py:757-762`](../aseprite_mcp/tools/animation.py#L757)）：

| 参数值 | Lua 常量 |
|---|---|
| `forward` | `AniDir.FORWARD` |
| `reverse` | `AniDir.REVERSE` |
| `pingpong` | `AniDir.PING_PONG` |
| `pingpong_reverse` | `AniDir.PING_PONG_REVERSE` |

方向是**枚举序号**存进文件的，回读时靠一张索引表还原（[`animation.py:205`](../aseprite_mcp/tools/animation.py#L205)）：

```lua
local dirs = {[0]="forward", "reverse", "pingpong", "pingpong_reverse"}
```

这是 Lua 的数组构造技巧：`[0]` 显式指定 index 0，后面的元素依次是 1、2、3。所以四种方向的数值编码是 0/1/2/3。

### 删除与缺项

`delete_tag` 按名字找，找不到报 `ERROR:Tag not found`，然后 `spr:deleteTag(target)`。

**没有 tag 改名工具** —— 改名需要先 `delete_tag` 再 `set_tag`。

---

## 五、图层可见性与不透明度

这两组工具在 `animation.py` 而不是 `layers.py`，因为它们影响的是**渲染结果**而非图层结构：

| 工具 | 目标 | 取值 |
|---|---|---|
| `set_layer_visibility` | `layer.isVisible` | bool |
| `set_layer_opacity` | `layer.opacity` | 0–255 |
| `set_cel_opacity` | `cel.opacity` | 0–255 |

**层级与 cel 级是两个独立的量**：`set_layer_opacity` 作用于整个图层（所有帧），`set_cel_opacity` 只作用于 (图层, 帧) 那一个 cel。两者相乘生效。

**组的可见性是继承的**：隐藏一个组会连带隐藏组内所有子层。这一点在合成读取时有精确的语义要求，见 [08 §2](08-inspection-and-quality.md#二_compose_frame为什么不能直接用-flatten)。

---

## 六、onion skin：两个不同含义

这是本模块最容易误解的地方。

### `set_onion_skin` 是 no-op

[`animation.py:800-819`](../aseprite_mcp/tools/animation.py#L800) 会校验参数，然后**什么都不做**，返回一条解释性消息：

```python
return (
    "Onion skin settings are UI-only in batch mode; no changes applied "
    f"(enabled={enabled}, before={before}, after={after}, opacity={opacity})"
)
```

原因就是 [01](01-lua-bridge.md) 的那个根本约束：批量模式下没有 UI，而洋葱皮是 Aseprite 的**编辑器状态**，脚本无法驱动。

它保留下来是为了兼容 —— 调用它能拿到一个"已废弃"的明确说明，好过让调用方以为设置生效了。

### 真正的洋葱皮是 `render_onion_skin`

在 [`analysis.py`](../aseprite_mcp/tools/analysis.py) 里，**把当前帧叠在相邻帧的半透明残影上渲染成一张 PNG**（[08 §3](08-inspection-and-quality.md#三analysispy-的三个工具)）。这是批量模式下唯一可行的洋葱皮：不是编辑器里的辅助显示，而是一张可以看的图片。

**要看动画连贯性就用它，不要用 `set_onion_skin`。**

---

## 七、补间与振荡

四个补间/振荡工具共享同一套骨架。

### 归一化参数 t 与取整

```lua
local span = end_idx - start_idx
for fi = start_idx, end_idx do
    local t = 0
    if span > 0 then t = (fi - start_idx) / span end
    local e = ease(t)
    ...
    local x = math.floor({start_x} + ({end_x} - {start_x}) * e + 0.5)
```

`t ∈ [0, 1]`，`span == 0`（单帧区间）时 `t = 0`。所有落值都走 `math.floor(v + 0.5)` 四舍五入到整数像素。同一个 `ease` 函数被**复制**到每个工具的脚本里（不是共享片段），公式完全一致：

| `easing` | 公式 |
|---|---|
| `linear` | `t` |
| `ease_in` | `t²` |
| `ease_out` | `1 − (1−t)²` |
| `ease_in_out` | `t < 0.5 ? 2t² : 1 − (−2t+2)²/2` |
| `smoothstep`（默认） | `t²(3 − 2t)` |

非法值报 `Unsupported easing (linear, ease_in, ease_out, ease_in_out, smoothstep)`。

### 四个工具的行为差异

| 工具 | 变化量 | `create_missing_cels` 默认 | 对已有 cel |
|---|---|---|---|
| `tween_cel_positions` | 线性位置 | `False` | 改写 `cel.position` |
| `tween_cel_positions_eased` | 缓动位置 | `False` | 改写 `cel.position` |
| `tween_cel_opacity_eased` | 缓动不透明度 | `False` | 改写 `cel.opacity`（钳到 0–255） |
| `tween_cel_scale_eased` | 缓动缩放 | **`True`** | `replace` 默认 `True`，**删掉重建** |
| `oscillate_cel_positions` | 正弦位移 | `False` | **叠加**到现有位置 |

⚠️ **`tween_cel_scale_eased` 的默认值与众不同**：它默认 `create_missing_cels=True` 且 `replace=True`，因此会**删掉目标帧已有的 cel 再重建**。缩放补间不是幂等操作，重复调用会以缩小后的图为基准再缩一次。

⚠️ **`oscillate_cel_positions` 是叠加而非绝对定位**（[`animation.py:1042-1044`](../aseprite_mcp/tools/animation.py#L1042)）：

```lua
local pos = cel.position
cel.position = Point(pos.x + dx, pos.y + dy)
```

所以第二次调用会在第一次的结果上再振一次。而且 `dx` 用 `sin`、**`dy` 用 `cos`**（[`animation.py:1022-1024`](../aseprite_mcp/tools/animation.py#L1022)），意味着 `t=0` 时 y 偏移是 `amplitude_y` 而不是 0 —— 想让首帧回到原位需要设 `phase_deg`。

### 补 cel 时的来源帧

`create_missing_cels=True` 时新 cel 的像素从哪来，由 `source_frame_index` 决定；省略则用 `start_frame`。若该来源帧也没有 cel，就退化为一张画布大小的空图：

```lua
local source_cel = target_layer:cel(spr.frames[source_frame])
if source_cel then
    local img = source_cel.image:clone()
    cel = spr:newCel(target_layer, frame, img, source_cel.position)
else
    local img = Image(spr.width, spr.height, spr.colorMode)
    cel = spr:newCel(target_layer, frame, img, Point(0, 0))
end
```

### 缩放补间的实现

它克隆**源 cel 的图像**作为基准，逐帧 `img:resize(new_w, new_h)` 后新建 cel（[`animation.py:1201-1248`](../aseprite_mcp/tools/animation.py#L1201)）：

```lua
local base_img = source_cel.image:clone()
local new_w = math.max(1, math.floor(base_w * scale + 0.5))
local new_h = math.max(1, math.floor(base_h * scale + 0.5))
```

`anchor` 只有 `center` 和 `topleft` 两个值。`center` 时按源 cel 的中心重算位置：

```lua
local cx = base_pos.x + base_w / 2
local cy = base_pos.y + base_h / 2
pos_x = math.floor(cx - new_w / 2 + 0.5)
pos_y = math.floor(cy - new_h / 2 + 0.5)
```

注意它缩放的是**被裁剪的 cel 图像**，不是画布 —— 所以 `base_w` 可能是 cel 的紧凑尺寸而非 `spr.width`。

---

## 八、`get_sprite_info`

唯一的读取类工具，返回手写拼装的 JSON（[`animation.py:167-213`](../aseprite_mcp/tools/animation.py#L167)）。形状：

```json
{
  "width": 32, "height": 32, "color_mode": "rgb", "frames": 4,
  "durations_ms": [100, 100, 100, 100],
  "layers": [
    {"name": "body", "visible": true, "opacity": 255, "is_group": false, "parent": null},
    {"name": "character", "visible": true, "opacity": 255, "is_group": true, "parent": null},
    {"name": "armor", "visible": true, "opacity": 255, "is_group": false, "parent": "character"}
  ],
  "tags": [
    {"name": "idle", "from": 1, "to": 4, "direction": "forward"}
  ]
}
```

几个实现要点：

- **JSON 是 Lua 手工拼字符串的**，不是 Lua 有序列化库。所以它是"能拼出来就对"的实现，字段名靠 `\\"name\\"` 这样的转义写进脚本。
- `color_mode` 从 `spr.colorMode` 枚举映射成 `rgb` / `indexed` / `gray` / `unknown`。
- `layers` 是**递归**的（`walk_layers` 会下钻 `layer.layers`），每个条目带**直接父组名**（顶层为 `null`）。这是 [issue #17](04-layers-and-canvas.md#一图层树模型) 的修复产物，回归测试见 [`tests/test_sprite_info_groups.py`](../tests/test_sprite_info_groups.py)。
- 图层名用 `string.format("%q", ...)` 输出，所以名字里的引号会被正确转义 —— 图层名不会破坏 JSON。
- 脚本里有一条关键注释（[`animation.py:166`](../aseprite_mcp/tools/animation.py#L166)）：

  > batch mode discards Lua `return` values — output MUST go through print()

  这是 [01 §3](01-lua-bridge.md#三stdout-文本协议核心机制) 那条"print 是唯一数据通道"的又一处体现。

---

## 九、`guide.py`

只有一个工具 `animation_workflow_guide(use_case="character")`，返回一段**英文**的分步工作流建议文本，按 `character` / `environment` / 其它（兜底）三套内容（[`guide.py:8-36`](../aseprite_mcp/tools/guide.py#L8)）。

它是纯静态字符串，不碰 Aseprite，存在的意义是给模型一个"推荐的动画工作方式"提示（先打关键帧再补间、静态层用 `propagate_cels`、最后跑 `audit_animation` 校验）。

---

## 十、已知缺口

| 缺口 | 说明 |
|---|---|
| **没有播放/循环控制** | 没有 `set_loop`、没有播放控制、没有 "repeat" 开关。循环行为只能由 tag 的 `direction`（`AniDir`）间接表达，而批次模式本身也不播放动画 |
| `set_onion_skin` 是 no-op | 见第六节 |
| **没有 tag 改名** | 只能 `delete_tag` + `set_tag` |
| `copy_frame` 目标帧越界会静默成功 | 见下方陷阱表 |
| `propagate_cels` 部分缺层不告知 | 只在一个都没匹配时报错 |
| 补间工具不复用共享片段 | `ease` 函数被复制到每个脚本里，改公式要改 4 处 |
| 非递归跳过组 | 帧序列工具不覆盖嵌套在组里的图层 |

### 陷阱表

| 项 | 说明 |
|---|---|
| `copy_frame` 目标帧越界会**静默返回成功** | 脚本里是 `if dst_idx < 1 or dst_idx > #spr.frames then return end`（[`animation.py:647`](../aseprite_mcp/tools/animation.py#L647)），**没有** `print("ERROR:...")`。所以它什么也没做却报告 `Frame copied`。用 `copy_cel` 会得到明确的越界报错 |
| `oscillate_cel_positions` 是叠加 | 重复调用会累积位移 |
| `tween_cel_scale_eased` 默认删掉重建 | `replace=True` + `create_missing_cels=True`，不是幂等的 |
| 帧序列工具不覆盖组内图层 | 顶层遍历 + `not layer.isGroup` |
| 帧号 1-based，网格/矩形 0-based | 不要跨族混用 |
| `add_frames` 只在新帧上设时长 | 已有帧的时长不受影响 |
| `delete_frame` / `delete_layer` 都拒绝删最后一个 | Aseprite 要求至少留一个 |

---

## 相关测试

| 测试 | 覆盖 |
|---|---|
| [`tests/test_animation.py`](../tests/test_animation.py) | `add_frames`、cel 不透明度、tag 的设置与删除（含删除不存在的 tag）、`delete_frame` |
| [`tests/test_sprite_info_groups.py`](../tests/test_sprite_info_groups.py) | **回归**：`get_sprite_info` 枚举组内子层并带 `parent` 字段 |
| [`tests/test_auto_create.py`](../tests/test_auto_create.py) | **回归**：`copy_cel` 自动补帧并在回复中说明补了几帧、传 `false` 时改为报错 |
| [`tests/test_visibility.py`](../tests/test_visibility.py) | **回归**：分组可见性、隐藏层被排除出合成结果 |

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md#三stdout-文本协议核心机制) —— `OK|frames_added=N` 协议、print 是唯一数据通道
- [04 · 画布、图层与跨文件复制](04-layers-and-canvas.md) —— 图层树、`flatten()` 陷阱、跨文件图层复制
- [08 · 读取、分析与质量校验](08-inspection-and-quality.md) —— `render_onion_skin`、`compare_frames`、`audit_animation`、`animation_sanitize`
- [reference/tools.md](reference/tools.md#animationpy) —— 24 个工具的完整签名
