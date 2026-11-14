# 07 · 导出与预览

> 把精灵渲染成 PNG/GIF/精灵表/分层文件、把外部图片导入图层，以及把产物交给客户端看的 HTTP 预览服务。
> 覆盖源文件：[`tools/export.py`](../aseprite_mcp/tools/export.py) · [`tools/preview.py`](../aseprite_mcp/tools/preview.py)

## 职责边界

**负责**：格式导出、单帧导出（视觉反馈循环的核心）、精灵表打包、分层导出、按 tag 导出、外部图片导入、本地 HTTP 预览服务。

**不负责**：

- 导出路径的解析规则与"输出路径铁律" → [02 §4](02-paths-errors-lifecycle.md#四输出路径铁律)
- 帧/cel/tag 的模型与语义 → [05 · 动画](05-animation.md)
- 合成读取（不写文件、只在内存里算） → [08 · 读取、分析与质量校验](08-inspection-and-quality.md)
- **图像如何被客户端"看到"** —— 本文档第七节，这是理解整个视觉反馈循环的关键

---

## 一、两条技术路线

导出模块是整个项目里**最多使用 CLI 直调**的地方。多数工具走 Lua 脚本，导出则大量直接拼 Aseprite 的命令行参数：

| 路线 | 工具 | 原因 |
|---|---|---|
| **CLI 直调**（`run_command`） | `export_sprite` `export_frame` `export_spritesheet` `export_layers` `export_tag` | 导出是 Aseprite 的 CLI 专长（`--save-as` / `--sheet` / `--split-layers` / `--tag`），用 Lua 反而做不到 |
| **Lua 脚本**（`execute_lua_script_checked`） | `copy_sprite` `import_image_as_layer` | 这两件是"打开后另存"和"往 cel 上贴图"，用 `spr:saveAs` / `drawImage` 更直接 |

CLI 路线意味着**错误捕获方式不同**：`run_command` 返回 `(success, output)`，`success` 来自子进程退出码。而退出码不可靠（见第三节），所以每个 CLI 导出都必须自己补文件系统后验。

---

## 二、导出工具

| 工具 | 路线 | 关键参数 | 产物 |
|---|---|---|---|
| `export_sprite` | CLI | `output_filename`、`format` | 任意 `--save-as` 支持的格式 |
| `copy_sprite` | Lua | `output_filename`、`overwrite` | `.aseprite` |
| `export_frame` | CLI | `frame_index`、`scale`(1–64) | PNG（可整数放大） |
| `export_spritesheet` | CLI | `sheet_type`、`data_filename`、`scale`、`padding`、`tag_name`、`data_format`、`list_tags` | 图集 PNG + 可选 JSON |
| `export_layers` | CLI | `output_directory`、`include_hidden` | 每层一个 PNG |
| `export_tag` | CLI | `tag_name`、`output_filename`、`scale` | GIF 或 PNG 序列 |
| `import_image_as_layer` | Lua | `image_path`、`layer_name`、`frame_index`、`x`、`y` | 修改 sprite 本身 |

### `export_frame` 是视觉反馈循环的核心

它的 docstring 把用途写在最前面（[`export.py:107-109`](../aseprite_mcp/tools/export.py#L107)）：

> Use this for visual feedback while drawing: export at scale 8-10 and open the PNG to inspect the result, then keep iterating.

配合 `scale` 的 1–64 范围与**最近邻**放大，模型可以"画 → 导出放大图 → 看 → 改"。这是这个 server 让 LLM 产出可用像素画的关键机制 —— 没有它，模型只能盲画。

`--scale` 是 Aseprite CLI 的最近邻缩放，不会引入插值模糊，所以 8× 图能真实反映像素网格。

### `export_spritesheet` 的布局选项

`sheet_type ∈ {horizontal, vertical, rows, columns, packed}`，`data_format ∈ {json-array, json-hash}`。

`data_filename` 给出时才加 `--data <path> --format <fmt>`，此时 `list_tags` 才会加 `--list-tags`（[`export.py:227-233`](../aseprite_mcp/tools/export.py#L227)）—— 没有数据文件就没有"给 tag 元数据的地方"。

### `export_layers` 的模板占位符

```python
args += [
    "--split-layers", filename,
    "--save-as", os.path.join(output_directory, "{layer}.png"),
]
```

[`export.py:276-279`](../aseprite_mcp/tools/export.py#L276)。`{layer}.png` 是 **Aseprite 自己的模板语法**，不是 Python 的 f-string —— 它之所以能活着到这里，是因为这一串没走 f-string，是普通字符串字面量。产物按图层名命名，写在 `output_directory` 里。默认只导可见层，`include_hidden=True` 时加 `--all-layers`。

成功判定是**统计目录里有几个 PNG**（[`export.py:283-287`](../aseprite_mcp/tools/export.py#L283)），一个都没有就报 `Aseprite exited 0 but wrote no PNG files`。

### `copy_sprite` 的覆盖保护

它在 Python 侧检查（[`export.py:77-78`](../aseprite_mcp/tools/export.py#L77)）：

```python
if os.path.exists(output_filename) and not overwrite:
    return f"Output file {output_filename} already exists"
```

这是**唯一**有覆盖保护的工具 —— 其余导出会静默覆盖同名文件。它保留 `.aseprite` 后缀（缺则补），然后用 `spr:saveAs` 另存。

### `import_image_as_layer` 的锚定例外

源图片路径用 `anchor=False` 但**保留存在性要求**（[`export.py:377`](../aseprite_mcp/tools/export.py#L377)）：

```python
image_path, err = prepare_filename(image_path, anchor=False)
```

读一个数据源不应该改变会话的活跃 sprite 文件，但它必须真实存在。（[02 §4](02-paths-errors-lifecycle.md#四输出路径铁律) 里把这归为"只读的导入源"。）

目标是 `find_layer` 找不到就 `spr:newLayer()` 建顶层层（[`export.py:396-400`](../aseprite_mcp/tools/export.py#L396)），cel 走 `normalize_cel(..., true)` 按需创建，最后 `drawImage(src, Point(x, y))`。

---

## 三、CLI 参数拼装的两个陷阱

### 陷阱 1：`--frame-range` 必须出现在输入文件**之前**

[`export.py:195-221`](../aseprite_mcp/tools/export.py#L195)：

```python
args = ["--batch"]
if tag_name:
    # Frame filters only apply to --sheet when they appear before
    # the input file; resolve the tag to a 0-based --frame-range so
    # missing tags produce a clear error.
    ...
    args += ["--frame-range", frame_range]
args.append(filename)
```

顺序是：`--batch` → `--frame-range ...` → **然后才是文件名** → `--scale` / `--sheet-type` / `--shape-padding` / `--data ...` → `--sheet <out>`。

把 `--frame-range` 放到文件名之后，Aseprite 会**忽略**它，导出一整张表而不是 tag 的帧区间 —— 而且不报错。这是最隐蔽的一类 CLI 陷阱。

### 陷阱 2：CLI 的帧号是 0-based

MCP 对外一律 1-based，CLI 一律 0-based，转换点在两个地方：

| 位置 | 转换 |
|---|---|
| [`export.py:128`](../aseprite_mcp/tools/export.py#L128) | `f0 = frame_index - 1  # CLI --frame-range is 0-based` |
| [`export.py:205`](../aseprite_mcp/tools/export.py#L205) | tag 区间 `(fromFrame.frameNumber - 1) .. (toFrame.frameNumber - 1)` |

tag 那条走的是 `RANGE:<from>,<to>` 协议（[01 §3](01-lua-bridge.md#标记总表)），Lua 里就把 1-based 减成 0-based 再打印，Python 侧拿到就能直接用。

---

## 四、退出码 0 但没写文件

这是 [01 §3](01-lua-bridge.md#退出码-0-但没有成功) 提到的那类问题的具体表现。**四类后验**，每类都对应一种"看起来成功其实失败"的场景：

| 位置 | 检查 | 场景 |
|---|---|---|
| [`export.py:46-50`](../aseprite_mcp/tools/export.py#L46) `export_sprite` | 精确路径 **或** `glob(f"{base}*{ext}")` | 不支持的格式（如 `format="json"`）；多帧存成静图会产出编号兄弟文件 |
| [`export.py:141-147`](../aseprite_mcp/tools/export.py#L141) `export_frame` | 精确路径，否则 `os.replace` 兄弟文件回名 | 多帧 sprite 上 Aseprite 会自行追加帧号 |
| [`export.py:237-242`](../aseprite_mcp/tools/export.py#L237) `export_spritesheet` | sheet **和** data 两个文件都要存在 | 参数组合不合法时静默不写 |
| [`export.py:337-344`](../aseprite_mcp/tools/export.py#L337) `export_tag` | 同 `export_sprite` | 同上 |
| [`export.py:283-287`](../aseprite_mcp/tools/export.py#L283) `export_layers` | 目录里至少有一个 PNG | `--split-layers` 没产出 |
| [`export.py:90-92`](../aseprite_mcp/tools/export.py#L90) `copy_sprite` | `saveAs` 后文件存在 | Lua 脚本成功但文件没落地 |

统一的话术是 **`"Aseprite exited 0 but wrote no file"`**（各工具措辞略有不同），这是刻意保持一致的诊断信息 —— 见到它就知道问题出在 Aseprite 那边而不是路径解析。

### 编号兄弟文件的回名

`export_frame` 是最完整的例子（[`export.py:141-147`](../aseprite_mcp/tools/export.py#L141)）：

```python
# With multi-frame sprites Aseprite may append the frame number to
# the filename; rename the produced file when that happens.
if not os.path.exists(output_filename):
    base, ext = os.path.splitext(output_filename)
    candidates = sorted(glob.glob(f"{base}*{ext}"))
    if candidates:
        os.replace(candidates[0], output_filename)
    else:
        return f"Export reported success but {output_filename} was not created"
```

多帧 sprite 用 `--save-as out.png` 时，Aseprite 实际写的是 `out1.png`、`out2.png`……所以取排序后的第一个（帧号最小者）重命名成用户要的名字。`export_sprite` 和 `export_tag` 只做"存在性放行"，不回名。

### `--tag` 缺失时静默导出全部帧

[`export.py:316-318`](../aseprite_mcp/tools/export.py#L316) 的注释解释了为什么要先做一次 Lua 校验：

> `--tag` silently exports *all* frames (exit 0) when the tag does not exist, so a produced file is not proof the tag was honoured.

也就是说：tag 名拼错时，CLI 会**成功导出全部帧**并退出 0。光看"文件生成了"无法发现这个错误 —— 拿到的是一个帧数不对的 GIF，而不是一个报错。

所以 `export_tag` 先用一段小 Lua 脚本确认 tag 存在（[`export.py:319-330`](../aseprite_mcp/tools/export.py#L319)），`export_spritesheet` 在 `tag_name` 非空时也共用同一思路（顺便把区间解析出来）。

---

## 五、`export_sprite` 的两个分支完全相同

[`export.py:32-39`](../aseprite_mcp/tools/export.py#L32)：

```python
# For animated exports
if format == "gif":
    args = ["--batch", filename, "--save-as", output_filename]
    success, output = AsepriteCommand.run_command(args)
else:
    # For still image exports
    args = ["--batch", filename, "--save-as", output_filename]
    success, output = AsepriteCommand.run_command(args)
```

gif 分支与 else 分支**逐字相同**。实际决定导出结果的是**输出文件的扩展名**（Aseprite 按扩展名选编码器），`format` 参数只用于补后缀：

```python
if not output_filename.lower().endswith(f".{format}"):
    output_filename = f"{output_filename}.{format}"
```

所以这个分支是历史遗留的冗余结构。行为上没有问题，但读代码时不要以为"gif 走了特殊路径"。

---

## 六、返回值：只有绝对路径文本

**所有导出工具的返回值都是一个人可读字符串，内嵌解析后的绝对路径。** 例如：

```text
Sprite exported successfully to D:/art/sprites/coin.png
Frame 3 exported to D:/art/sprites/coin_f3.png at 8x
Sprite sheet exported to D:/art/coin_sheet.png (horizontal) with data file D:/art/coin_sheet.json
Layers exported to D:/art/layers: body.png, armor.png, glow.png
```

**没有任何工具返回 image content block、base64 数据或 MCP resource。** 全部 118 个工具都是 `async def ... -> str`（[02 §7](02-paths-errors-lifecycle.md#七错误契约)）。

这意味着**图像传到客户端有且只有两条路**：

1. 客户端自己去读那个绝对路径（本地场景）。
2. 用 `start_preview_server` 起本地 HTTP，通过 URL 取（远程/Docker 场景）。

这就是第七节的主题。

---

## 七、预览服务器的完整闭环

`preview.py` 只有两个工具，但它补上了"图像怎么给客户端看"这一环。

### 闭环

```text
1. export_frame(output_filename="D:/art/preview/coin_8x.png", scale=8)
2. start_preview_server(directory="D:/art/preview")   → http://localhost:8000/
3. 客户端取 http://localhost:8000/coin_8x.png
4. 看、改、重新导出（同名覆盖）
5. stop_preview_server(port=8000)
```

### 工具行为

| 工具 | 行为 |
|---|---|
| `start_preview_server(directory="", port=8000)` | 起 `python -m http.server <port> --directory <dir>`，返回 `Preview server started: http://localhost:<port>/` |
| `stop_preview_server(port=8000)` | 按 PID 文件杀掉服务，删除 PID 文件 |

**目录解析绕过了 `prepare_filename`**（[`preview.py:35`](../aseprite_mcp/tools/preview.py#L35)）：

```python
directory = resolve_path(directory) if directory else get_workspace_dir()
if not os.path.isdir(directory):
    return f"Directory {directory} not found"
```

因为它服务的是一个**已存在的目录**，不是精灵文件 —— 复用 `prepare_filename` 的存在性检查语义在这里没有意义。缺省目录是工作区。

### 进程细节

见 [02 §8.4](02-paths-errors-lifecycle.md#84-preview-server-的进程侧)。要点：

- 进程**跨多次工具调用存活**（这是唯一这样的进程，Aseprite 子进程都是秒级的）。
- Windows 用 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`，POSIX 用 `start_new_session=True`，stdout/stderr 丢弃。
- PID 存在 `tempfile.gettempdir()/aseprite_mcp_preview_<port>.pid`（UTF-8）。
- 重复启动有探活保护：PID 还在跑就拒绝重复启动，僵死则清掉残留 PID 文件。
- 停止在 Windows 用 `taskkill /PID <pid> /T /F`，POSIX 用 `SIGTERM`。

⚠️ **安全提示**：它把整个目录暴露在 HTTP 上。`directory` 缺省是工作区根目录，所以不要在有敏感内容的目录下随意调用。

---

## 八、陷阱表

| 项 | 说明 |
|---|---|
| `--frame-range` 位置 | 必须在输入文件**之前**，否则被 Aseprite 静默忽略 |
| CLI 帧号 0-based | 与 MCP 的 1-based 相反，两个转换点只出现在 `export.py` |
| 退出码 0 不代表成功 | 每个 CLI 导出都必须自己查文件系统 |
| 多帧存静图会产出编号兄弟文件 | `export_frame` 会自动重命名回名，其它工具只放行不重名 |
| `--tag` 缺失时静默导出全部帧 | 所以必须先校验 tag；"文件生成了"不是证据 |
| `export_sprite` 的 `format` 只补后缀 | 决定编码器的是输出文件扩展名；if/else 两分支完全相同 |
| 只有 `copy_sprite` 有覆盖保护 | 其余导出静默覆盖同名文件 |
| `{layer}.png` 是 Aseprite 的模板语法 | 不是 Python f-string，改动时别把它 f-string 化 |
| 输出路径必须 `anchor=False` | 否则导出会把会话活跃文件指向 PNG（[02 §4](02-paths-errors-lifecycle.md#四输出路径铁律)） |
| 预览服务暴露整个目录 | 缺省是工作区根目录，注意内容敏感性 |
| 图像不通过 MCP 返回 | 只有绝对路径文本 + 可选的 HTTP 服务两条路 |

---

## 相关测试

| 测试 | 覆盖 |
|---|---|
| [`tests/test_export.py`](../tests/test_export.py) | `export_frame` 的缩放（校验 PNG 头里的尺寸）、精灵表 + JSON 数据、tag 过滤、分层导出、GIF tag、图片导入 |
| [`tests/test_error_propagation.py`](../tests/test_error_propagation.py) | **回归（issue #15）**：非法输入必须报失败而非伪造成功，跨 9 个工具模块 15 处 |
| [`tests/test_path_resolution.py`](../tests/test_path_resolution.py) | 输出路径的 `must_exist=False, anchor=False` 语义 |

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md#三stdout-文本协议核心机制) —— `RANGE:` 协议、退出码不可靠的原因
- [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md#四输出路径铁律) —— 输出路径铁律、preview 进程
- [05 · 动画](05-animation.md#四tag-与播放方向) —— tag 与 `AniDir` 的语义
- [08 · 读取、分析与质量校验](08-inspection-and-quality.md) —— 不写文件的"内存内合成"读取
- [reference/tools.md](reference/tools.md#exportpy) —— 完整签名与参数默认值
