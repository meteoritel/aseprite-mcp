# 04 · 画布、图层与跨文件复制

画布与图层工具直接调用；跨工程复制属于 scene 扩展，经 `search_tools(category="scene")` 查找后使用 `call_tool` 执行。

> 创建画布、维护图层树（含组与嵌套）、调整堆叠与混合，以及在两个精灵文件之间搬运图层。
> 覆盖源文件：[`tools/canvas.py`](../aseprite_mcp/tools/canvas.py) · [`tools/layers.py`](../aseprite_mcp/tools/layers.py) · [`tools/scene.py`](../aseprite_mcp/tools/scene.py)

## 职责边界

**负责**：精灵的创建、图层/组的增删改名与嵌套、图层的堆叠顺序与混合模式、合并与展平、跨文件图层复制。

**不负责**：

- **可见性与不透明度** —— 这两个工具（`set_layer_visibility`、`set_layer_opacity`）在 [`animation.py`](../aseprite_mcp/tools/animation.py) 里，因为它们和帧渲染关系更近。见 [05 · 动画](05-animation.md)
- 把像素画进 cel → [03 · 绘图与像素编辑](03-painting.md)
- 帧的增删与 cel 生命周期 → [05 · 动画](05-animation.md)
- 图层名如何解析成对象 → [01 · Lua 桥](01-lua-bridge.md)

---

## 一、图层树模型

Aseprite 的图层是**树**：顶层是 `spr.layers`，每个图层若 `isGroup` 则还有自己的 `.layers`。组可以任意嵌套。

```text
spr.layers
├── "background"       (image layer)
├── "character"        (group)
│   ├── "body"         (image layer)
│   └── "armor"        (image layer)
└── "effects"          (group)
    └── "glow"         (image layer)
```

### 名字解析

所有工具都靠 [`core/lua.py` 的 `FIND_LAYER`](../aseprite_mcp/core/lua.py) 把用户给的名字变成图层对象。它的两段式策略（BFS 精确全名匹配 → `group/child` 路径最长前缀回溯）在 [01 §5](01-lua-bridge.md) 有完整说明。

需要记住的三条后果：

1. **名字里的 `/` 有歧义**：`abc/x/y` 既可能指一个叫 `abc/x` 的组里的 `y`，也可能指 `abc → x → y` 三级结构。两种都成立时取最长的组名前缀。
2. **裸名匹配优先取较浅的层**：不同组里有同名图层时，靠树的 BFS 顺序决定命中哪个。
3. **判重只看顶层**。这是刻意的 —— Aseprite 允许不同组里有同名图层，所以"这个名字是否已存在"的检查必须限定在顶层，否则会误报。见 [`lua.py`](../aseprite_mcp/core/lua.py) 的共享查层规则。

### 自动创建只处理顶层

`ENSURE_LAYER` 里的守卫（[`lua.py:82`](../aseprite_mcp/core/lua.py)）：

```lua
if create and not string.find(name, "/", 1, true) then
```

**含 `/` 的名字永远不会被凭空创建。** 系统不会为了满足 `character/armor` 就顺手造出 `character` 组 —— 组的创建是显式操作（`add_group`）。绘图类工具因此可以直接对一个不存在的顶层图层名作画，但对 `group/child` 必须先建组。

---

## 二、工具一览与职责

### `canvas.py` —— 原生工程、图层与帧

`create_canvas` 要求绝对路径，只接受 `.aseprite`／`.ase`，无扩展名补 `.aseprite`。默认拒绝覆盖，`overwrite=true` 才替换已有工程；保存校验成功后锚定。

`add_layer`／`add_group` 可指定父组，父目标须已存在且为 group。`add_frame` 追加帧，`set_frame_duration` 设置明确帧的时长。cel 编辑由各工具显式指定 layer/frame。

标准修改调用 `execute_edit_script`：Lua 用 `save_project(spr)` 保存到目标同目录暂存，原生头验证后精确替换目标。失败保全源工程，见 [01 · 编辑提交](01-lua-bridge.md)。

### `layers.py` —— 图层运维

| 工具 | 关键点 |
|---|---|
| `delete_layer` | 剩最后一个图层时拒绝（`Cannot delete the only layer`） |
| `rename_layer` | 空名字被拒 |
| `duplicate_layer` | 深拷贝所有帧的 cel，继承不透明度与混合模式 |
| `reorder_layer` | 设 `stackIndex`（1-based，**1 是最底层**） |
| `set_layer_blend_mode` | 未知模式报错并列出合法值 |
| `merge_layer_down` | `app.command.MergeDownLayer()`，最底层拒绝 |
| `flatten_sprite` | `spr:flatten()`，全部图层合成一层 |

---

## 三、深拷贝：`duplicate_layer`

[`layers.py:148-165`](../aseprite_mcp/tools/layers.py) 是这个模块里最值得细看的一段：

```lua
local copy = spr:newLayer()
copy.name = "{safe_new}"
copy.opacity = src.opacity
copy.blendMode = src.blendMode
if parent then
    copy.parent = parent
else
    copy.stackIndex = src.stackIndex + 1
end
for _, frame in ipairs(spr.frames) do
    local cel = src:cel(frame)
    if cel then
        local c = spr:newCel(copy, frame, cel.image:clone(), cel.position)
        c.opacity = cel.opacity
    end
end
```

要点：

- **cel 图像必须 `clone()`**。直接传 `cel.image` 会让两层共享同一份图像数据，改一个就改两个。
- **`cel.position` 被保留**，所以被裁剪过的 cel 复制后位置不变。
- **`cel.opacity` 逐帧复制**（`spr:newCel` 不会继承它）。
- 放置策略：给了 `group` 就挂进组（此时**不**设 `stackIndex`），否则放在源层正上方（`src.stackIndex + 1`）。
- 默认名字是 `"{layer_name} copy"`（[`layers.py:128`](../aseprite_mcp/tools/layers.py)）。

注意它复制的是**图层的图像内容**，不是图层树结构 —— `src` 本身是组时，`src:cel(frame)` 返回 nil，循环什么也不做，结果是一个空的同名副本。

---

## 四、堆叠顺序

`reorder_layer` 直接写 `target.stackIndex`（[`layers.py:206`](../aseprite_mcp/tools/layers.py)），语义：

- **1-based，1 是最底层。** 与帧号一致。
- 越界检查用的是 `#spr.layers`，也就是**顶层图层的数量**（[`layers.py:203`](../aseprite_mcp/tools/layers.py)）。
- 因此这个工具本质上是**顶层内的重排**：对嵌套在组里的图层设 `stackIndex` 不会把它移出组。

`merge_layer_down` 同理依赖 `stackIndex`：`target.stackIndex <= 1` 表示已经是最底层，报 `Layer is the bottom layer; nothing to merge into`。它先 `app.activeLayer = target` 再调 `app.command.MergeDownLayer()`，因为该命令作用于**当前图层**（这正是 [01 §6](01-lua-bridge.md) 描述的"原生命令不接受目标参数"问题的手写版本）。

---

## 五、混合模式

`_BLEND_MODES`（[`layers.py:6-26`](../aseprite_mcp/tools/layers.py)）把 snake_case 名字映射到 Aseprite 的 `BlendMode.*` 常量：

| 分组 | 名字 |
|---|---|
| 基础 | `normal` |
| 变暗类 | `darken` `multiply` `color_burn` |
| 变亮类 | `lighten` `screen` `color_dodge` `addition` |
| 对比类 | `overlay` `soft_light` `hard_light` |
| 差值类 | `difference` `exclusion` `subtract` `divide` |
| HSL 类 | `hue` `saturation` `color` `luminosity` |

⚠️ **HSL 组的常量名有 `HSL_` 前缀**，这是唯一不是简单大写的映射：

```python
"hue": "BlendMode.HSL_HUE",
"saturation": "BlendMode.HSL_SATURATION",
"color": "BlendMode.HSL_COLOR",
"luminosity": "BlendMode.HSL_LUMINOSITY",
```

查表失败时返回的报错会列出**全部**合法模式（[`layers.py:238`](../aseprite_mcp/tools/layers.py)），调用方一轮就能自我纠正。

---

## 六、`flatten_sprite` 的隐藏图层陷阱

`flatten_sprite` 只是 `spr:flatten()`。但 Aseprite 1.3.x 的 `flatten()` **会把隐藏图层也合并进去** —— 这是整个项目里影响面最广的一个行为坑：

- 对 `flatten_sprite` 本身，这意味着"隐藏"并不等于"不影响结果"：展平后隐藏图层的内容会变成可见像素。
- 对**分析类工具**，这意味着不能用 `flatten()` 来求"玩家实际看到的画面"。

后者就是 [`analysis.py` 的 `_COMPOSE_FRAME`](../aseprite_mcp/tools/analysis.py) 存在的原因：它先克隆 sprite、逐个删掉不可见图层、再 `flatten()`。详见 [08 · 读取、分析与质量校验](08-inspection-and-quality.md#二_compose_frame为什么不能直接用-flatten)。

如果你要写新的"合成读取"类工具，**不要**直接用 `spr:flatten()`，复用 `_COMPOSE_FRAME`。

---

## 七、跨文件复制：`copy_layers_between_sprites`

[`scene.py`](../aseprite_mcp/tools/scene.py) 只有一个工具，但它的实现方式和其它工具**都不一样**：Lua 使用 `app.open()` 取得源和目标，提交路径由标准编辑层管理。

### 路径与锚定

```python
source_filename = prepare_filename(source_filename)
...
target_filename = prepare_filename(target_filename, anchor=False)
```

[`scene.py:25-30`](../aseprite_mcp/tools/scene.py)。源文件按常规解析（**会**锚定，可省略）；目标文件用 `anchor=False`（存在性仍要求），所以"把图层搬到另一个文件"不会改变会话的活跃文件 —— 这与导出类工具遵循同一条[输出路径铁律](02-paths-errors-lifecycle.md)。

路径在插入 Lua 前统一 `\` → `/` 再转义（[`scene.py:34-35`](../aseprite_mcp/tools/scene.py)）。

### 执行流程

```text
app.open(src) / app.open(dst)   ← 两个都失败就 ERROR
FIND_LAYER                      ← 注意：没有 LAYER_NAMES
① 逐个检查请求的图层在源文件是否存在，分成 valid / missing
   全部缺失 → ERROR:None of the requested layers exist in the source: ...
app.transaction(...)
② create_missing_frames 时 while #dst.frames < #src.frames do dst:newFrame() end
③ 对每个 valid 名字：
     目标层不存在 → dst:newLayer() 并命名
     replace 时先删掉目标层所有帧的 cel
     逐帧 clone 源 cel 的 image 与 position
save_project(dst)               ← 暂存校验后提交目标
缺失的名字通过 MISSING: 回报
```

### 交付语义

- 返回 `Layers copied from X to Y`，若有跳过则追加 `(skipped missing layers: a, b)`（[`scene.py:111-118`](../aseprite_mcp/tools/scene.py)）。
- **部分成功不算失败**：只要至少复制了一个图层就返回成功消息，缺失的通过 `MISSING:` 告知。只有**全部**缺失才是 `ERROR`。
- **目标层不会被重命名或复用判重**：同名目标层存在就直接往里写，`replace=True`（默认）会先清空它的 cel。
- **源文件只读**：脚本结尾只 `save_project(dst)`，由标准编辑层提交目标。
- 目标层如果不存在会**自动创建**，且是顶层的 —— 不保留源文件的组结构。

### 与 `duplicate_layer` 的分工

| | `duplicate_layer` | `copy_layers_between_sprites` |
|---|---|---|
| 范围 | 同一个文件内 | 跨两个文件 |
| 组结构 | 可挂进指定组 | 不保留，一律顶层 |
| 缺失图层 | 报错 | 跳过并回报 |
| 帧数 | 天然够 | 可选自动补齐 |

---

## 八、陷阱与边界

| 项 | 说明 |
|---|---|
| `reorder_layer` 只作用于顶层 | `position` 上限是顶层图层数，嵌套层无法借此移出组 |
| `duplicate_layer` 复制组会得到空层 | 组没有 cel |
| `flatten_sprite` 会合入隐藏图层 | 见第六节，这是 `_COMPOSE_FRAME` 存在的原因 |
| 可见性/不透明度不在本文档 | 在 [`animation.py`](../aseprite_mcp/tools/animation.py)，见 [05 §5](05-animation.md) |
| `copy_layers_between_sprites` 不保留组结构 | 一律建成顶层图层 |
| `delete_layer` 拒绝删最后一个图层 | Aseprite 要求 sprite 至少有一层 |
| `add_frame` 不带时长参数 | 新帧用 Aseprite 的默认时长；批量设时长用 `set_frame_duration_all`（在 [05](05-animation.md)） |

---

## 相关测试

| 测试 | 验证链路 |
|---|---|
| [编辑工作流](../tests/test_editing_workflow.py) | 组路径和含 `/` 的名称、裸名优先浅层、嵌套层信息、明确 cel 编辑、复制保留元数据、原生创建和提交保全 |
| [MCP 工作流](../tests/test_mcp_workflow.py) | 会话活跃工程、工作区相对路径、嵌套组编辑、非法目标与失败后的继续编辑 |

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md) —— `FIND_LAYER` / `ENSURE_LAYER` 的解析规则
- [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md) —— `create_canvas` 的路径要求、输出路径铁律
- [05 · 动画](05-animation.md) —— 帧/cel/tag，以及图层可见性与不透明度
- [08 · 读取、分析与质量校验](08-inspection-and-quality.md#二_compose_frame为什么不能直接用-flatten) —— `flatten()` 陷阱的消费方
- [reference/tools.md](reference/tools.md#layerspy) —— 三个模块的完整签名
