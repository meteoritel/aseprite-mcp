# Aseprite MCP · 开发者技术总览

> 面向贡献者的架构与机制文档入口。这个 server 把 [Aseprite](https://www.aseprite.org/) 当成无头的像素图编辑/渲染引擎驱动，通过 MCP 暴露给 AI 助手。

| | |
|---|---|
| 传输 | **stdio only**；支持 `initialize` 握手与 `2026-07-28` `server/discover` |
| 运行时 | Python ≥ 3.13，依赖 `mcp[cli]`、`pillow`、`httpx`、`python-dotenv` |
| 外部依赖 | 一个 `aseprite` 可执行文件（由 `ASEPRITE_PATH` 定位） |

用户向的展示型文档（示例图、工具分类表）是仓库根的 [`README.md`](../README.md)。本文档集是面向开发者的机制文档，两者受众不同。

---

## 一、它是什么

一句话：**每次工具调用都新起一个 Aseprite 进程，跑一段生成的 Lua，从 stdout 读回结果。**

因此它没有长驻编辑器、没有 socket、没有 sprite 缓存。Python 侧只持有一点点会话状态（哪个文件是"当前文件"）；MCP 协议与 stdio 生命周期由官方 Python SDK 管理。所有真正的图像工作都由 Aseprite 自己的 Lua API（`app.*`、`Sprite`、`Layer`、`Cel`、`Image`）完成。

这个设计让 Aseprite 执行端无需维护长驻编辑会话、并发状态同步或图像缓存。代价是每次调用都要冷启动一次 Aseprite，且每次都要重新打开文件。

---

## 二、三层架构

```text
┌──────────────────────────────────────────────────────────────────┐
│  MCP 工具层          aseprite_mcp/tools/*.py                       │
│  · 参数校验（Python 侧）                                          │
│  · 用 f-string 拼 Lua 脚本                                        │
│  · 解析 stdout，返回人类可读字符串                                 │
└───────────────────────────┬──────────────────────────────────────┘
                            │ 只依赖
┌───────────────────────────▼──────────────────────────────────────┐
│  机制层              aseprite_mcp/core/*.py                       │
│  commands  子进程执行 · Lua 转义 · 穿越拒绝                        │
│  lua       可复用 Lua 片段（图层解析、cel 归一化、HSL…）            │
│  native    app.command.* 的目标激活包装                            │
│  state     prepare_filename · 活跃文件 · 工作区                    │
│  colors    十六进制颜色解析                                       │
│  fonts     字形栅格化（bitmap / TrueType）                        │
└───────────────────────────┬──────────────────────────────────────┘
                            │ subprocess
┌───────────────────────────▼──────────────────────────────────────┐
│  外部            aseprite --batch [file] --script <tmp.lua>       │
│                  每次调用一个新进程，跑完即退                       │
└──────────────────────────────────────────────────────────────────┘
```

`aseprite_mcp/__init__.py` 创建 `MCPServer` 单例，`aseprite_mcp/__main__.py` 是入口。

**依赖方向是单向的**：`tools/` 依赖 `core/`，`core/` 之间只按 `commands ← state ← tools` 这条链互相引用，不存在 `core/` 反向依赖 `tools/`。唯一跨模块的横向引用是 `core/state.py` 从 `core/commands.py` 取 `reject_traversal`。

---

## 三、一次工具调用的完整数据流

以 `draw_rectangle_at(filename="D:/art/knight.aseprite", layer_name="armor", frame_index=1, x=8, y=8, width=16, height=16, fill=True)` 为例：

| # | 阶段 | 位置 |
|---|---|---|
| 1 | 客户端按 JSON Schema 调用工具 | MCPServer 依据函数签名生成 schema |
| 2 | `filename` 解析成绝对路径，或返回错误字符串 | [`state.py:72`](../aseprite_mcp/core/state.py#L72) → [02](02-paths-errors-lifecycle.md#一prepare_filename唯一的路径漏斗) |
| 3 | Python 侧校验（尺寸、颜色、`pixels` 的 `x`/`y`） | [02](02-paths-errors-lifecycle.md#六参数校验与-lua-注入) |
| 4 | 用户字符串经 `lua_escape` 转义 | [`commands.py:11`](../aseprite_mcp/core/commands.py#L11) → [01](01-lua-bridge.md#四lua-字符串转义) |
| 5 | f-string 拼出 Lua，嵌入 `core/lua.py` 的共享片段 | [01](01-lua-bridge.md#五共享-lua-片段库-coreluapy) |
| 6 | 脚本以 UTF-8 写入临时 `.lua` 文件 | [`commands.py:113`](../aseprite_mcp/core/commands.py#L113) |
| 7 | `aseprite --batch <sprite> --script <tmp>` 子进程执行 | [`commands.py:75`](../aseprite_mcp/core/commands.py#L75) |
| 8 | Lua 内：`app.transaction(...)` → `spr:saveAs(spr.filename)` → `print("OK")` | 各工具模块 |
| 9 | Python 扫 stdout 找行首 `ERROR:`，决定成败 | [`commands.py:131`](../aseprite_mcp/core/commands.py#L131) → [01](01-lua-bridge.md#三stdout-文本协议核心机制) |
| 10 | 工具返回字符串，MCPServer 包成一个 text content block | 各工具模块 |

### 两条必须记住的推论

**图像从不通过 MCP 返回。** 工具的返回类型都是 `str`，没有工具返回 image content block、base64 或 MCP resource。图片只能先写到磁盘，再把**绝对路径文本**交给客户端 —— 或者用 `start_preview_server` 起一个本地 HTTP 服务，让客户端去 `http://localhost:<port>/<file>` 取。这是这个项目视觉反馈循环（`export_frame` → 看图 → 改）的实现方式。

**退出码 0 不等于成功。** 批量模式下 Lua 无法设置进程退出码，所以失败靠脚本 `print("ERROR:...")` 表达；反过来，Aseprite 在若干失败场景下仍以 0 退出却不写文件，导出类工具因此必须在成功退出后**查文件系统**。见 [07](07-output.md#四退出码-0-但没写文件)。

---

## 四、装配与注册

### server 实例

[`aseprite_mcp/__init__.py:33`](../aseprite_mcp/__init__.py#L33)：

```python
mcp = MCPServer("aseprite", instructions=_load_skill_instructions())
```

`_load_skill_instructions()`（[`__init__.py:18-30`](../aseprite_mcp/__init__.py#L18)）读取仓库根的 `SKILL.md` 作为 MCP 的 `instructions` 字段 —— 也就是**连接时推给模型的文件处理契约**。文件读不到（`OSError`）或内容为空时，回退到 `_FALLBACK_INSTRUCTIONS`（[`__init__.py:7-15`](../aseprite_mcp/__init__.py#L7)），那段是英文的精简版同样规则。

> Docker 镜像里 `SKILL.md` 不存在（`.dockerignore` 排除了除 `README.md` 外的所有 `*.md`），所以容器内**恒定**走 fallback。详见 [development.md](development.md#五docker)。

### 工具注册是导入副作用，不是自动发现

每个工具模块自己做两件事（[`canvas.py:1-8`](../aseprite_mcp/tools/canvas.py#L1)）：

```python
from .. import mcp

@mcp.tool()
async def create_canvas(width: int, height: int, *, filename: str) -> str:
```

然后 [`tools/__init__.py`](../aseprite_mcp/tools/__init__.py) 显式 `from . import <module>` 逐个导入工具模块，`__main__.py` 再 `from .tools import *`。

没有 `pkgutil` 扫描、没有注册表、没有 `__all__`。**新增一个模块必须手工加进 `tools/__init__.py`，否则它的工具不会出现**；在已有模块里加工具则不需要改任何注册代码。

### 入口

[`aseprite_mcp/__main__.py`](../aseprite_mcp/__main__.py) 导入工具模块并启动 stdio server：

```python
from . import mcp
from .tools import *

if __name__ == "__main__":
    mcp.run(transport='stdio')
```

---

## 五、如何新增一个工具

### 落点

优先加到语义最接近的**已有模块**，而不是新建文件。工具模块的职责划分见 [reference/tools.md 的模块索引](reference/tools.md#模块索引)，各模块的边界写在对应子系统文档的「职责边界」一节。

### 骨架

```python
from ..core.commands import AsepriteCommand, lua_escape
from ..core.state import prepare_filename
from ..core.lua import ENSURE_LAYER, LAYER_NAMES
from .. import mcp

@mcp.tool()
async def my_tool(filename: str = "", *, layer_name: str, frame_index: int = 1) -> str:
    """One-line summary.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: ...
        frame_index: Frame index starting at 1
    """
    filename, err = prepare_filename(filename)
    if err:
        return err

    safe_layer = lua_escape(layer_name)
    script = f"""
    {ENSURE_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = ensure_layer(spr, "{safe_layer}", true)
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end
    local cel = normalize_cel(spr, target, {frame_index}, true)
    if not cel then print("ERROR:Frame index out of range") return end

    app.transaction(function()
        cel.image:putPixel(0, 0, Color(255, 0, 0, 255))
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)
    if success:
        return f"Did the thing on '{layer_name}' in {filename}"
    return f"Failed to do the thing: {output}"
```

### 检查清单

| # | 事项 | 依据 |
|---|---|---|
| 1 | 首参 `filename: str = ""`，其余用 `*` 变成 keyword-only | 全仓库唯一例外是 5 个 legacy 绘图工具 |
| 2 | docstring 用 Google 风格 `Args:` —— 生成器靠它填参数说明列 | [`gen_tool_reference.py`](../scripts/gen_tool_reference.py) |
| 3 | 开头 `filename, err = prepare_filename(filename)`，`if err: return err` | [02 §1](02-paths-errors-lifecycle.md#一prepare_filename唯一的路径漏斗) |
| 4 | 写往别处的路径必须 `must_exist=False, anchor=False` | [02 §4](02-paths-errors-lifecycle.md#四输出路径铁律) |
| 5 | 校验顺序：filename → 标量范围 → 颜色 → `pixels` 的 `x`/`y` | [02 §6](02-paths-errors-lifecycle.md#六参数校验与-lua-注入) |
| 6 | 需要"缺了就建"的图层用 `ENSURE_LAYER` + `ensure_layer`，不要用裸 `FIND_LAYER` | [01 §5](01-lua-bridge.md#五共享-lua-片段库-coreluapy) |
| 7 | 报错带上 `layer_names(spr)` 与 `Tip:` —— 让调用方一轮自我纠正 | [02 §7](02-paths-errors-lifecycle.md#可操作性上下文) |
| 8 | 字符串插值前 `lua_escape`；裸数字（如 `pixels` 的 `x`/`y`）用 `parse_pixel_xy` | [01 §4](01-lua-bridge.md#四lua-字符串转义) |
| 9 | 改动包在 `app.transaction(function() ... end)` 里，结尾 `spr:saveAs(spr.filename)` + `print("OK")` | [01 §8](01-lua-bridge.md#八约定与陷阱) |
| 10 | 用 `execute_lua_script_checked`（不是 `execute_lua_script`） | [01 §2](01-lua-bridge.md#二asepritecommand-的三个方法) |
| 11 | 失败返回 `f"Failed to <verb>: {output}"` | [02 §7](02-paths-errors-lifecycle.md#七错误契约) |
| 12 | 有输出文件就做文件系统后验（Aseprite 会退出 0 却不写文件） | [07 §3](07-output.md#四退出码-0-但没写文件) |
| 13 | 改了 `app.command.*` 就用 `build_native_command_script` 包一层 | [01 §6](01-lua-bridge.md#六corenativepy原生命令为什么要包装) |
| 14 | 重跑 `uv run python scripts/gen_tool_reference.py`，并跑 `--check` 确认 | [development.md](development.md#七文档保鲜) |
| 15 | 加测试；尽量让错误消息以 `Failed`/`Invalid`/`ERROR`/`Script failed` 开头 | [02 §7](02-paths-errors-lifecycle.md#陷阱ok-覆盖不了范围校验类消息) |
| 16 | 如果它改变了模型应该怎样使用这个 server，**同时更新 `SKILL.md`** | 它是运行时的 `instructions` |

第 16 条容易漏：`SKILL.md` 不是普通文档，它是模型连接时收到的指令。改了工具契约（比如新增一个会自动创建图层的工具，或改变 `create_canvas` 的路径要求）却不更新它，模型就会拿着过时的规则去调用。

---

## 六、文档地图

### 横切机制

跨所有子系统生效的约定，先读这两篇再读其余。

| 文档 | 内容 |
|---|---|
| [01 · Lua 桥与 Aseprite 调用模型](01-lua-bridge.md) | 一次调用一个进程的模型、`AsepriteCommand`、**stdout 文本协议总表**、`lua_escape`、`core/lua.py` 共享片段、`core/native.py` 的目标激活、`run_lua_script` |
| [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md) | `prepare_filename` 漏斗、活跃文件、`ASERITE_MCP_WORKSPACE`、输出路径铁律、UTF-8 IO 全表、**参数校验与注入防护**、错误契约、MCP stdio 生命周期 |

### 子系统

| 文档 | 覆盖源文件 | 主题 |
|---|---|---|
| [03 · 绘图与像素编辑](03-painting.md) | `drawing` `sprite_map` `selection` `transform` `text` `palette` + `core/fonts` | 两种落像素机制、坐标与笔刷约定、字符网格（sprite map）、字体栅格化、区域操作、调色板与量化 |
| [04 · 画布、图层与跨文件复制](04-layers-and-canvas.md) | `canvas` `layers` `scene` | 图层树、组路径解析、堆叠顺序、混合模式、两个文件之间的图层搬运 |
| [05 · 动画](05-animation.md) | `animation` `guide` | 帧/cel/tag 模型、补间与缓动、onion skin 的两个含义、已知缺口 |
| [06 · 特效与网格结构](06-effects-and-tilemap.md) | `fx` `native_fx` `tilemap` `slices` | 手写特效 vs 原生滤镜、有序抖动、tilemap 全局网格、slice 输出协议 |
| [07 · 导出与预览](07-output.md) | `export` `preview` | 直接调 CLI 的导出路径、参数顺序陷阱、文件系统后验、预览闭环 |
| [08 · 读取、分析与质量校验](08-inspection-and-quality.md) | `pixel_read` `analysis` `quality` | 单 cel 读 vs 合成读、`_COMPOSE_FRAME`、颜色统计、结构校验器 |

### 参考与开发

| 文档 | 内容 |
|---|---|
| [reference/tools.md](reference/tools.md) | 工具的完整清单（签名、参数、默认值、源码行号），由脚本从 AST 生成 |
| [development.md](development.md) | 环境与安装、**全部环境变量**、测试 harness、Docker、CI、文档保鲜 |

### 推荐阅读顺序

1. 本文档（你在这里）—— 拿到架构与数据流的心智模型
2. [01](01-lua-bridge.md) —— stdout 协议是理解所有工具代码的前提
3. [02](02-paths-errors-lifecycle.md) —— 路径与错误契约是写新工具的前提
4. 你打算改动的那个子系统
5. [reference/tools.md](reference/tools.md) 按需查签名

---

## 七、术语表

| 术语 | 含义 |
|---|---|
| **sprite** | 一个 `.aseprite` 文件的内容：画布 + 图层 + 帧 + 调色板 + tag + slice |
| **layer** | 图层。可以是普通图像层，也可以是 **group**（组），组可以嵌套 |
| **cel** | 某个图层在某一帧上的图像单元。**空帧意味着该图层那一帧没有 cel** |
| **frame** | 帧。外部 API 一律 **1-based** |
| **tag** | 动画标签，标记一段帧区间并带播放方向（`AniDir`） |
| **slice** | 精灵里的命名矩形区域，带九宫格中心和轴心点 |
| **tilemap** | 瓦片图层。瓦片尺寸存在 **sprite 级别的 `gridBounds`** 上，不是每层一份 |
| **cel-local 坐标** | `cel.image` 上的像素坐标；与 sprite 全局坐标差一个 `cel.position` |
| **sprite-global 坐标** | 以画布左上角为原点、y 向下的坐标。绘图/选区/变换工具对外都用它 |
| **batch 模式** | `aseprite --batch`，无 UI、无窗口。**UI 相关的 API 在批量模式下无效** |
| **`ui=false`** | 传给 `app.command.*` 的标志，表示在无 UI 环境下执行 |
| **active file** | 会话当前锚定的 sprite 文件，省略 `filename` 时作用于它 |
| **原生（native）** | 指 Aseprite 自己编译进去的滤镜/命令（`app.command.*`），相对本项目手写的逐像素实现 |

---

## 八、已知偏差与待办

以下是调研中确认的、**文档与实现不一致或实现存在缺口**的地方。它们**尚未修复**，阅读代码时不要以为文档写错了。

### 文档与实现不一致

| # | 偏差 | 影响 |
|---|---|---|
| 1 | 根 [`README.md`](../README.md) 的 Tool Categories 表与实现有差：未列出 `native_fx.py` 的原生滤镜，也未列入 `get_composite_pixel` / `get_composite_rect`，Canvas 工具数与实现不符，且 `get_sprite_info` 在 Inspection 与 Animation 两处重复计入 | 使用者可能以为没有原生滤镜和合成读取能力。权威清单以 [reference/tools.md](reference/tools.md) 为准 |
| 2 | `DOCKER.md` 与 `DOCKER_SETUP_SUMMARY.md` 声称容器里有非 root 用户 `mcpuser`，但 `Dockerfile` 从未创建该用户，实际以 **root** 运行 | 安全预期错位 |
| 3 | `DOCKER.md` 引用的 `scripts/aseprite-docker.sh` 包装的是 `aseprite-from-source:latest` 镜像，本仓库**没有**构建它 | 脚本不可用 |
| 4 | `requirements.txt` 与 `pyproject.toml` 冲突：前者缺 `httpx`/`mcp`，多了 `black`/`flake8`/`typing_extensions`，`pytest` 版本要求也不同 | 以 `pyproject.toml` 为准 |
| 5 | `python-dotenv` 被 [`commands.py:5`](../aseprite_mcp/core/commands.py#L5) 直接 import，但**未在 `pyproject.toml` 声明**，只靠 `mcp` 的传递依赖存在 | 依赖收紧时会断 |

### 命名与历史包袱

| # | 问题 |
|---|---|
| 6 | 环境变量是 `ASERITE_MCP_WORKSPACE`（少一个 `P`），代码与文档全仓库一致。改它会破坏兼容 |
| 7 | [`tilemap.py:9-16`](../aseprite_mcp/tools/tilemap.py#L9) 仍有本地 `_parse_hex_color`，只支持 6 位无 alpha，未统一到 `core/colors.py` |
| 8 | `quality.py` 名字像评分器，实际**没有任何数值评分或阈值**，只是结构校验器 |
| 9 | [`export.py:33-39`](../aseprite_mcp/tools/export.py#L33) 的 gif 分支与 else 分支代码完全相同 |
| 10 | `pyproject.toml` 没有 build backend，项目**不可安装**，也没有 console script 入口；`__version__` 同时存在于 `pyproject.toml` 和 [`__init__.py:35`](../aseprite_mcp/__init__.py#L35) |
| 11 | `.dockerignore` 排除 `docs/` 与除 `README.md` 外的所有 `*.md`，所以镜像内**没有 `SKILL.md`**，`instructions` 恒走 fallback |

### 实现缺口

| # | 缺口 |
|---|---|
| 12 | **子进程无超时**：`subprocess.run` 没传 `timeout=`，挂死的 Aseprite 会永久阻塞工具调用（[02 §8.3](02-paths-errors-lifecycle.md#83-子进程没有超时)） |
| 13 | **没有播放/循环控制工具**：无 `set_loop`、无播放控制，循环行为只能由 tag 方向间接表达（[05](05-animation.md#十已知缺口)） |
| 14 | `set_onion_skin` 是**文档化的 no-op**（UI-only）；真正的洋葱皮是 `analysis.render_onion_skin`（[05](05-animation.md#六onion-skin两个不同含义)） |
| 15 | 错误消息前缀不统一：范围校验类（`Width and height must be > 0`、`Start frame must be >= 1`、`Unsupported anchor …`）**不在** `ok()` 检查的 4 个前缀内，测试会静默放过（[02 §7](02-paths-errors-lifecycle.md#陷阱ok-覆盖不了范围校验类消息)） |
| 16 | CI **不跑 pytest**：`.github/workflows/docker-build.yml` 只构建/推送镜像并在 PR 上做冒烟，测试没有自动化入口（[development.md](development.md#六ci)） |

---

## 相关文档

- [根 README.md](../README.md) —— 用户向的展示与安装说明
- [SKILL.md](../SKILL.md) —— 运行时推给模型的 `instructions`（中文）
- [DOCKER.md](../DOCKER.md) —— Docker 使用说明（注意第八节的偏差项）
- [01 · Lua 桥](01-lua-bridge.md) —— 开始读代码前建议先看这篇
