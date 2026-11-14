# 01 · Lua 桥与 Aseprite 调用模型

> 把一次 MCP 工具调用翻译成一次 Aseprite 子进程执行，并把结果与错误带回 Python。
> 覆盖源文件：[`core/commands.py`](../aseprite_mcp/core/commands.py) · [`core/lua.py`](../aseprite_mcp/core/lua.py) · [`core/native.py`](../aseprite_mcp/core/native.py) · [`tools/script.py`](../aseprite_mcp/tools/script.py)

## 职责边界

**负责**：子进程启动与参数拼装、Lua 脚本的落盘与清理、Lua 字符串转义、stdout 文本协议的约定与解析、可复用 Lua 片段库、原生命令的目标激活包装。

**不负责**：

- 文件名/路径的解析与校验 → [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md)
- 具体工具的业务语义（画什么、画在哪） → [03](03-painting.md) 起各子系统文档
- 导出时直接调 CLI 而非 Lua 的那条路径 → [07 · 导出与预览](07-output.md)

---

## 一、调用模型：一次工具调用 = 一个短命子进程

这是理解整个项目的起点：**没有长驻的 Aseprite 进程，没有 socket，没有 stdin 协议。**

每次需要 Aseprite 干活时，都新起一个 `aseprite` 进程，跑完就退出：

```text
aseprite --batch [<sprite.aseprite>] --script <临时脚本.lua>
```

- 二进制定位只有一个来源：`ASEPRITE_PATH`，缺省值是裸名 `aseprite`（走 `PATH` 查找）。见 [`commands.py:75`](../aseprite_mcp/core/commands.py#L75)。
- `.env` 在 `core.commands` **被导入时**从仓库根加载（[`commands.py:7-8`](../aseprite_mcp/core/commands.py#L7)），是模块级副作用，不是显式初始化步骤。因为所有工具都间接导入 `core.commands`，仓库根的 `.env` 总是生效。

带来的直接后果：

| 后果 | 说明 |
|---|---|
| 无并发问题 | 进程之间互不干扰，不需要锁；`core/state.py` 的活跃文件是纯 Python 侧状态 |
| 无清理问题 | 子进程自己退出，服务端没有需要关闭的 Aseprite 连接 |
| 每次都是冷启动 | 连"打开某个 sprite"这件事也要每次重新做 |
| Python 侧不持有 sprite | 工具之间只通过磁盘上的 `.aseprite` 文件和活跃文件路径传递状态 |

Python 侧唯一的长驻状态是**会话活跃文件**（[02](02-paths-errors-lifecycle.md#二活跃文件会话状态)）。MCP 协议与 stdio 生命周期由官方 Python SDK 管理。

---

## 二、`AsepriteCommand` 的三个方法

[`core/commands.py:61-149`](../aseprite_mcp/core/commands.py#L61)，一个纯静态方法类：

| 方法 | 返回 | 用途 |
|---|---|---|
| `run_command(args)` | `(success, output)` | 拼 `[ASEPRITE_PATH] + args` 并执行。导出类工具直接用这一层传 CLI 参数 |
| `execute_lua_script(script_content, filename=None)` | `(success, output)` | 把脚本写入临时 `.lua` 文件，拼 `--batch [file] --script tmp` 执行，`finally` 里删临时文件 |
| `execute_lua_script_checked(script_content, filename=None)` | `(success, output)` | 在上一层的**成功结果**里继续扫 `ERROR:` 行，把脚本内的错误提升为失败 |

`execute_lua_script_checked` 的语义（[`commands.py:131-149`](../aseprite_mcp/core/commands.py#L131)）：

```python
success, output = AsepriteCommand.execute_lua_script(script_content, filename)
if not success:
    return False, output
for line in output.splitlines():
    if line.startswith("ERROR:"):
        return False, line[len("ERROR:"):]
return True, output
```

注意两点：只认**行首**的 `ERROR:`；返回的 error 已经剥掉了前缀，所以调用方拿到的是干净的错误文本，会再包成 `f"Failed to ...: {output}"`（[02](02-paths-errors-lifecycle.md#七错误契约)）。

### 临时脚本的落盘

[`commands.py:113-129`](../aseprite_mcp/core/commands.py#L113)：

```python
with tempfile.NamedTemporaryFile(
    suffix='.lua', delete=False, mode='w', encoding='utf-8'
) as tmp:
    tmp.write(script_content)
    script_path = tmp.name
try:
    ...
finally:
    os.remove(script_path)
```

`delete=False` + `finally: os.remove` 是必须的：Windows 上 Aseprite 还要按名字打开这个文件，句柄不能同时被 Python 持着。

### 输入文件的守卫

```python
if filename and os.path.exists(filename):
    args.append(filename)
```

[`commands.py:121`](../aseprite_mcp/core/commands.py#L121)。这一行是**静默的**：文件不存在时该参数被直接丢掉，脚本以"没有 `app.activeSprite`"的状态运行。所有生成的脚本因此都以同一段防御开头：

```lua
local spr = app.activeSprite
if not spr then print("ERROR:No active sprite") return end
```

调用方正常走 [`prepare_filename`](../aseprite_mcp/core/state.py#L72) 时文件已经过存在性校验，所以这条守卫主要是为 `run_lua_script` 这类允许不传文件的入口兜底。

---

## 三、stdout 文本协议（核心机制）

**批量模式下 Lua 无法设置进程退出码**，所以脚本只能靠 `print()` 表达成败，Python 侧扫 stdout 文本还原。这是全项目最需要记住的约定。

### 标记总表

| 标记 | 格式 | 生产者 | 含义 |
|---|---|---|---|
| `OK` | 单独一行 | 几乎每个变更类脚本的结尾 | 脚本成功跑完 |
| `ERROR:` | `ERROR:<message>` | 272 处，遍布所有模块 | 脚本内失败，`return` 前打印 |
| `OK\|frames_added=N` | `OK\|frames_added=3` | [`animation.py:608`](../aseprite_mcp/tools/animation.py#L608) | `copy_cel` 自动补了 N 帧（`OK` 的扩展形式） |
| `RANGE:` | `RANGE:<from>,<to>` | [`export.py:205`](../aseprite_mcp/tools/export.py#L205) | tag 的帧区间，**已转成 0-based** 供 CLI 用 |
| `PIXEL:` | `PIXEL:x,y,r,g,b,a` 或 `PIXEL:r,g,b,a` | [`pixel_read.py:64,152,212,270`](../aseprite_mcp/tools/pixel_read.py#L64) | 单点颜色 / 矩形内逐点颜色 |
| `DIFF:` | `DIFF:changed,total,minx,miny,maxx,maxy,any` | [`analysis.py:225`](../aseprite_mcp/tools/analysis.py#L225) | 两帧差异统计 |
| `COLOR:` / `OPAQUE:` / `UNIQUE:` | `COLOR:#RRGGBB,<count>` 等 | [`analysis.py:309-312`](../aseprite_mcp/tools/analysis.py#L309) | 颜色直方图的三段数据 |
| `COUNT:` | `COUNT:<n>` | [`fx.py:157`](../aseprite_mcp/tools/fx.py#L157)、[`selection.py:306`](../aseprite_mcp/tools/selection.py#L306)、[`palette.py:431`](../aseprite_mcp/tools/palette.py#L431) | 受影响像素数（三处各自定义） |
| `TILE:` | `TILE:<index>` | [`tilemap.py:309`](../aseprite_mcp/tools/tilemap.py#L309) | 某格子的瓦片索引 |
| `INFO:` | `INFO:tw,th,count,cols,rows` | [`tilemap.py:354`](../aseprite_mcp/tools/tilemap.py#L354) | tilemap 元信息 |
| `SLICE:` | 每行 `SLICE:{...}`，末行 `DONE` | [`slices.py:177-179`](../aseprite_mcp/tools/slices.py#L177) | 每个 slice 一条，避免分隔符冲突 |
| `PALETTE:` / `TRANSPARENT:` / `PALETTE_SIZE:` | `PALETTE:#RRGGBB` 等 | [`native_fx.py:282-292`](../aseprite_mcp/tools/native_fx.py#L282) | `extract_palette` 的三段数据 |
| `MISSING:` | `MISSING:a, b` | [`scene.py:103`](../aseprite_mcp/tools/scene.py#L103) | 源文件里不存在的图层名单 |

### 为什么优先 stdout 而不是 stderr

[`commands.py:88-95`](../aseprite_mcp/core/commands.py#L88) 的注释把原因写得很直白：

```python
except subprocess.CalledProcessError as e:
    # Batch-mode Aseprite reports Lua errors (runtime and syntax) on
    # *stdout* and exits non-zero, leaving stderr empty — reporting
    # only stderr would surface every crash as an empty message.
    parts = [p.strip() for p in (e.stdout, e.stderr) if p and p.strip()]
    return False, "\n".join(parts)
```

即：**Lua 运行时错误和语法错误都写在 stdout，stderr 是空的**。只看 stderr 会把每次崩溃报成空消息。拼接时 stdout 放在前面，因为两路都有内容时脚本自己的输出才是有用的那一半。

成功路径只返回 `result.stdout`，stderr 被丢弃（[`commands.py:87`](../aseprite_mcp/core/commands.py#L87)）。

### 「退出码 0 但没有成功」

因为退出码不可靠，导出类工具在拿到成功退出后还要**查文件系统**确认产物真的写出来了。这是[07 · 导出与预览](07-output.md#四退出码-0-但没写文件)的主题，也是回归测试 [`tests/test_error_propagation.py`](../tests/test_error_propagation.py) 覆盖的范围。

---

## 四、Lua 字符串转义

[`commands.py:11-26`](../aseprite_mcp/core/commands.py#L11)：

```python
def lua_escape(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("'", "\\'")
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\0", "\\0")
    )
```

**为什么双引号和单引号都要转义**：同一个名字会出现在两种字面量里 —— 查找时嵌在双引号里（`find_layer(spr, "<name>")`），报错回显时嵌在单引号里（`Layer '<name>' not found`）。Lua 在两种引号风格里都接受 `\'` 和 `\"`，所以两种都转义对两边都安全。

**路径要先换分隔符再转义**：

```python
safe_path = lua_escape(filename.replace("\\", "/"))
```

[`canvas.py:35`](../aseprite_mcp/tools/canvas.py#L35)。Lua 字符串里的 `\` 是转义引导符，而 Windows 路径满是 `\`；先统一成 `/` 再转义，Aseprite 在 Windows 上同样接受正斜杠。

**转义不是注入防护**。`lua_escape` 保护的是"值被引号包住"这一场景。`pixels` 参数里的 `x`/`y` 是被**直接插值**进脚本的裸数字，绕过了引号，因此需要单独校验 —— 见 [`parse_pixel_xy`](02-paths-errors-lifecycle.md#六参数校验与-lua-注入)。

---

## 五、共享 Lua 片段库 `core/lua.py`

这些是字符串常量，用 f-string 插进每个脚本的开头。它们承载了工具之间必须一致的语义。

### `FIND_LAYER`（[`lua.py:22-55`](../aseprite_mcp/core/lua.py#L22)）

最复杂的一段，两段式解析：

1. **精确全名匹配，BFS 遍历**。先广搜整棵图层树找同名者。这样"较浅的图层胜出"，且名字本身含 `/` 的图层/组能被直接命中。
2. **否则按 `group/child` 路径解析**。Aseprite 允许名字里含 `/`，所以段是**最长前缀优先 + 回溯**匹配：`abc/x/y` 既可能是一个叫 `abc/x` 的组的子层 `y`，也可能是 `abc → x → y` 三级结构。较长的前缀走不通时会退回较短的前缀，两种解析都成立时取最长的那个组名。

用途限定为**操作查找**：判重必须只看顶层，因为 Aseprite 允许不同组里有同名图层。相关的回归测试是 [`tests/test_group_layers.py`](../tests/test_group_layers.py) 与 [`tests/test_create_into_group.py`](../tests/test_create_into_group.py)。

### `LAYER_NAMES`（[`lua.py:59-71`](../aseprite_mcp/core/lua.py#L59)）

递归收集全部图层名并逗号连接，专门用于给出可操作的报错：

```lua
if not target then print("ERROR:Layer '<name>' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end
```

### `ENSURE_LAYER = FIND_LAYER + ensure_layer`（[`lua.py:77-89`](../aseprite_mcp/core/lua.py#L77)）

绘图类工具用它代替 `FIND_LAYER`。关键约束是那一行守卫：

```lua
if create and not string.find(name, "/", 1, true) then
    layer = spr:newLayer()
    layer.name = name
    return layer
end
```

**缺失的顶层名会自动创建，含 `/` 的名字永远不会被凭空创建**（不会顺手造出一堆组）。回归测试见 [`tests/test_auto_create.py:60`](../tests/test_auto_create.py#L60)。

### `NORMALIZE_CEL`（[`lua.py:93-111`](../aseprite_mcp/core/lua.py#L93)）

把一个 cel 的图像换成"画布大小、锚在 (0,0)"的等价图像，这样调用方可以直接用 sprite 全局坐标，不必做 cel 偏移运算。

**它有副作用**：当 cel 是被裁剪过的（`cel.position ≠ (0,0)` 或图像小于画布），函数会**替换 `cel.image` 并把 `cel.position` 归零**，永久改变该 cel 的边界。多边形、路径、渐变、选区、文本走这条路；legacy 绘图工具走的是手工减偏移那条路。两条路的并存见 [03 · 绘图与像素编辑](03-painting.md#12-落到像素的两条路)。

### `PSET`（[`lua.py:114-120`](../aseprite_mcp/core/lua.py#L114)）与 `HSL`（[`lua.py:123-166`](../aseprite_mcp/core/lua.py#L123)）

- `PSET`：带边界判断的 `putPixel`。几何图元（多边形顶点可能落在画布外）和目标可能越界的粘贴都用它，避免崩溃。
- `HSL`：`rgb_to_hsl` / `hsl_to_rgb`，`h ∈ [0,360)`、`s`/`l ∈ [0,1]`。供 `fx.adjust_hsl` 等逐像素变色使用。

---

## 六、`core/native.py`：原生命令为什么要包装

[`core/native.py`](../aseprite_mcp/core/native.py) 解决了一个容易踩的坑，模块 docstring 写得很清楚：

> Native engine commands act on the ACTIVE sprite / layer / frame (and the active selection for region scope), NOT on explicit arguments — so the wrapper resolves + activates the target BEFORE the command, error-first, or a filter silently hits the wrong layer.

也就是说 `app.command.Outline{}` 这类滤镜**不接受目标参数**，它作用于当前激活的图层/帧/选区。不先激活就可能把滤镜刷到错误的图层上，而且不会报错。

`build_native_command_script(command_lua, layer_name="", frame_index=1, region=None)`（[`native.py:13`](../aseprite_mcp/core/native.py#L13)）按固定顺序展开：

```text
FIND_LAYER + LAYER_NAMES
→ 检查 app.activeSprite 存在
→ 检查 frame_index 在 [1, #spr.frames]（1-based）
→ app.activeFrame = spr.frames[idx]
→ 若给了 layer_name：find_layer 并 app.activeLayer = target（找不到就 ERROR 并列出既有图层）
→ 若给了 region：spr.selection = Selection(Rectangle(x, y, w, h))
→ app.transaction(function() <command_lua> end)
→ 取消选区 spr.selection:deselect()
→ spr:saveAs(spr.filename)
→ print("OK")
```

消费方是 [`tools/native_fx.py`](../aseprite_mcp/tools/native_fx.py)，详见 [06 · 特效与网格结构](06-effects-and-tilemap.md#三native_fxpy-的工具)。

---

## 七、`tools/script.py`：逃生舱

[`run_lua_script(script, filename="")`](../aseprite_mcp/tools/script.py#L7) 是唯一一个不生成脚本、直接把用户脚本原样送进去的入口。它的 docstring 也是理解批量模式的最佳说明：

- 给了 `filename` 就先打开它，脚本里是 `app.activeSprite`；不给则回退活跃文件；都没有就允许 `app.activeSprite == nil`。
- **改动不会自动保存**：改了 sprite 必须在结尾自己 `spr:saveAs(spr.filename)`。
- **`print()` 是唯一的返回通道**。脚本干净退出不等于逻辑成功，所以要把要验证的东西打出来。
- cel 图像坐标是 **cel-local**：用 sprite 全局坐标前要按 `cel.position` 偏移。

它调用的是 `execute_lua_script`（**不带** `_checked`），自己扫输出，失败时返回 `f"Script failed: {output}"`（[`script.py:44-47`](../aseprite_mcp/tools/script.py#L44)）。

> ⚠️ 这个工具在宿主机上执行不受限的代码（含 `io`/`os` 访问）。文档里保留这条警告是刻意的。

---

## 八、约定与陷阱

| 陷阱 | 说明 |
|---|---|
| **没有超时** | `subprocess.run` 没传 `timeout=`。挂死的 Aseprite 会永久阻塞这次工具调用，没有任何兜底 |
| **错误必须是行首 `ERROR:`** | `execute_lua_script_checked` 用 `line.startswith("ERROR:")`，缩进或前缀都会让它漏判 |
| **脚本要自己保存** | 没有自动保存。标准结尾是 `spr:saveAs(spr.filename)` 后再 `print("OK")` |
| **每次调用都重新打开文件** | Python 侧不缓存 sprite；两次调用之间文件可能被外部改动 |
| **`--batch` 下 UI 相关能力不可用** | 这正是 `set_onion_skin` 成为 no-op 的原因，见 [05 · 动画](05-animation.md#六onion-skin两个不同含义) |
| **原生滤镜必须先激活目标** | 见第六节，用 `core/native.py` 的包装而不是手写 `app.command.*` |
| **临时 `.lua` 文件是明文落盘的** | 脚本内容（含图层名、路径）会短暂出现在系统临时目录 |

---

## 相关测试

- [`tests/test_error_propagation.py`](../tests/test_error_propagation.py) —— 15 个非法输入跨 9 个模块必须报失败而非伪造成功（issue #15）
- [`tests/test_script.py`](../tests/test_script.py) —— `run_lua_script` 返回 print 输出、空脚本被拒
- [`tests/test_encoding.py`](../tests/test_encoding.py) —— Lua 脚本文件 UTF-8 落盘、子进程输出 UTF-8 解码
- [`tests/test_group_layers.py`](../tests/test_group_layers.py) / [`tests/test_create_into_group.py`](../tests/test_create_into_group.py) —— `FIND_LAYER` 的名字与路径解析
- [`tests/test_auto_create.py`](../tests/test_auto_create.py) —— `ENSURE_LAYER` 的自动创建与拒绝
- [`tests/test_slices_pipe.py`](../tests/test_slices_pipe.py) —— `SLICE:` 逐行协议对分隔符的免疫

## 相关文档

- [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md) —— 文件名如何变成绝对路径、错误前缀集合、stdio 进程生命周期
- [06 · 特效与网格结构](06-effects-and-tilemap.md) —— `core/native.py` 的主要消费方
- [07 · 导出与预览](07-output.md) —— 绕过 Lua 直接调 CLI 的那条路径
- [reference/tools.md](reference/tools.md#scriptpy) —— `run_lua_script` 的完整签名
