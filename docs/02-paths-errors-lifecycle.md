# 02 · 路径、错误与进程生命周期

> 三个横切关注点：文件名如何变成受校验的绝对路径、失败如何表达给调用方、以及这条 stdio 服务链上有哪些进程、谁负责让它们死掉。
> 覆盖源文件：[`core/state.py`](../aseprite_mcp/core/state.py) · [`core/colors.py`](../aseprite_mcp/core/colors.py) · [`core/lifecycle.py`](../aseprite_mcp/core/lifecycle.py) · [`tools/preview.py`](../aseprite_mcp/tools/preview.py)（进程部分）· [`tests/conftest.py`](../tests/conftest.py)（错误契约的权威定义）

## 职责边界

**负责**：`filename` 参数到绝对路径的解析与校验、会话活跃文件、工作区解析、目录穿越拒绝、UTF-8 IO 的落点、错误消息契约与参数校验约定、server/子进程/preview server 的生死。

**不负责**：

- Lua 桥、stdout 协议、转义 → [01 · Lua 桥](01-lua-bridge.md)
- 单个工具的业务校验含义（比如"半径必须为正"） → 各子系统文档
- 导出后的文件系统后验 → [07 · 导出与预览](07-output.md#四退出码-0-但没写文件)

---

## 一、`prepare_filename`：唯一的路径漏斗

[`core/state.py:72-107`](../aseprite_mcp/core/state.py#L72)。**每个**碰文件的工具都从这一句开始：

```python
filename, err = prepare_filename(filename)
if err:
    return err
```

它在 [reference/tools.md](reference/tools.md) 的 100 多处调用点出现，是"文件永不悄悄落到错误目录"这条保证的唯一实现点。

### 执行顺序（顺序本身是有意义的）

```text
1. resolve_filename        显式 filename 优先，否则回退活跃文件；都没有 → NO_ACTIVE_FILE_ERROR
2. reject_traversal        在【原始字符串】上检查 `..`
3. resolve_path            expanduser → 相对路径按 workspace 拼接 → abspath
4. must_exist 检查         默认 True，失败 → "File <abs> not found — ..."
5. anchor                  默认 True，把绝对路径记为活跃文件
```

**第 2 步必须在第 3 步之前**，源码注释写明了原因：

> Check traversal on the RAW input: resolving first would let `os.path.abspath` silently collapse `..` and hide the attack.

即 `os.path.abspath("a/../../etc/x")` 会先把 `..` 折掉，检查就永远看不到它了。

### 两个开关

| 参数 | 默认 | 何时改 |
|---|---|---|
| `must_exist` | `True` | **输出**路径改 `False`（文件还不存在） |
| `anchor` | `True` | **输出**路径改 `False`（见第四节） |

返回 `(absolute_path, None)` 或 `(None, error_message)`。

---

## 二、活跃文件（会话状态）

[`core/state.py:16`](../aseprite_mcp/core/state.py#L16)：

```python
_active_file: str | None = None
```

一个**模块级全局变量**，通过 `set_active_file()` / `get_active_file()` 访问。它**不是** per-session、不是按连接分键、也没有锁。

实践上这没问题：stdio 传输下每个 server 进程服务一个 client，所以进程全局与"会话"重合。但对嵌入式或多客户端复用要保持警惕 —— 测试通过直接改模块全局来重置它（[`tests/test_path_resolution.py:24-32`](../tests/test_path_resolution.py#L24)）。

语义：

| 函数 | 行为 |
|---|---|
| `resolve_filename(filename)` | 显式 `filename` 胜利；否则回退 `_active_file`；都没有返回 `None` |
| `set_active_file(filename)` | 锚定。**只在校验通过后调用** |
| `get_active_file()` | 读当前锚定值（`run_lua_script` 用它做回退，见 [01](01-lua-bridge.md#七toolsscriptpy逃生舱)） |

两个常量错误消息（[`state.py:18-26`](../aseprite_mcp/core/state.py#L18)）：`NO_ACTIVE_FILE_ERROR`（提示先 `create_canvas` 或显式传 filename）和 `FILE_NOT_FOUND_HINT`（提示改用绝对路径或相对工作区的路径）。两者都刻意写成"教 AI 下一步怎么做"的句子。

---

## 三、工作区与相对路径解析

### 环境变量名是 `ASERITE_MCP_WORKSPACE`

注意拼写：**`ASERITE`**，缺一个 `P`。[`state.py:28`](../aseprite_mcp/core/state.py#L28)：

```python
WORKSPACE_ENV_VAR = "ASERITE_MCP_WORKSPACE"
```

这是全仓库一致的既有拼写 —— 代码、`sample.env`、根 `README.md`、`SKILL.md`、测试里全都是这个写法。**改文档时不要"顺手修正"，那会让它和代码对不上**。要修就得代码和文档一起改，属于破坏兼容的改动。

### 解析规则

[`state.py:52-69`](../aseprite_mcp/core/state.py#L52)：

```python
def get_workspace_dir() -> str:
    workspace = os.getenv(WORKSPACE_ENV_VAR)
    if workspace:
        return os.path.abspath(os.path.expanduser(workspace))
    return os.getcwd()

def resolve_path(path: str) -> str:
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(get_workspace_dir(), expanded)
    return os.path.abspath(expanded)
```

| 输入 | 结果 |
|---|---|
| 绝对路径 | 原样使用（仅 `~` 展开 + `abspath` 规范化） |
| `~/x.aseprite` | 展开到用户主目录，**不**再拼工作区 |
| `sprites/x.aseprite` + 设了 `ASERITE_MCP_WORKSPACE` | `<workspace>/sprites/x.aseprite` |
| `sprites/x.aseprite` + 未设 | `<server cwd>/sprites/x.aseprite` |
| 任一段含 `..` | 直接拒绝 |

### `create_canvas` 是唯一的例外

它是唯一**要求** `filename` 且必须是绝对路径的工具（[`canvas.py:24-28`](../aseprite_mcp/tools/canvas.py#L24)）：

```python
if not os.path.isabs(filename):
    return (
        "create_canvas requires an ABSOLUTE filename, e.g. "
        f"'D:/art/sprites/coin.aseprite'. Got: '{filename}'"
    )
```

理由是相对路径会按工作区解析，也就是落在 server 自己的目录里 —— 用户从未打算把画布放在那儿。它是**显式失败**而不是猜用户的意图。

注意这条错误消息以 `create_canvas requires` 开头，**不匹配** `ok()` 检查的四个前缀（见第七节），所以 `conftest` 的 `sprite` fixture 额外断言了文件真的存在。

它调用时用 `must_exist=False, anchor=False`，然后在**脚本成功之后**才 `set_active_file`（[`canvas.py:31,45`](../aseprite_mcp/tools/canvas.py#L31)），这样一次失败的创建不会把活跃文件指向不存在的文件。回归测试：[`tests/test_path_resolution.py:110-154`](../tests/test_path_resolution.py#L110)。

---

## 四、输出路径铁律

写往别处的路径必须传 `must_exist=False, anchor=False`：

```python
output_filename, err = prepare_filename(output_filename, must_exist=False, anchor=False)
```

已知的调用点：

| 位置 | 参数 |
|---|---|
| [`export.py:24`](../aseprite_mcp/tools/export.py#L24) | `output_filename`（`export_sprite`） |
| [`export.py:70`](../aseprite_mcp/tools/export.py#L70) | `output_filename`（`copy_sprite`） |
| [`export.py:122`](../aseprite_mcp/tools/export.py#L122) | `output_filename`（`export_frame`） |
| [`export.py:188`](../aseprite_mcp/tools/export.py#L188) | `output_filename`（`export_spritesheet`） |
| [`export.py:228`](../aseprite_mcp/tools/export.py#L228) | `data_filename`（精灵表 JSON） |
| [`export.py:268`](../aseprite_mcp/tools/export.py#L268) | `output_directory` |
| [`export.py:312`](../aseprite_mcp/tools/export.py#L312) | `output_filename`（`export_tag`） |
| [`export.py:377`](../aseprite_mcp/tools/export.py#L377) | 只读的导入源（`anchor=False`，但仍要求存在） |
| [`analysis.py:90`](../aseprite_mcp/tools/analysis.py#L90) | `output_filename`（`render_onion_skin`） |
| [`scene.py:28`](../aseprite_mcp/tools/scene.py#L28) | `target_filename` |

**为什么这条重要**：`anchor=True` 会把输出路径记为活跃文件。导出一次 `coin.png` 之后，后续省略 `filename` 的调用就会去操作那个 PNG，而它根本不是 Aseprite 文件 —— 会话直接坏掉。回归测试锁定这一点：[`tests/test_path_resolution.py:95-107`](../tests/test_path_resolution.py#L95)。

---

## 五、UTF-8 IO 的落点

Windows 上 `text=True` 会用 ANSI 代码页（中文系统是 GBK）解码，非 ASCII 的路径、图层名、报错都会变乱码。所以每处跨越"Python ↔ 外部"的文本边界都要显式指定 UTF-8：

| 位置 | 做法 | 若不做会怎样 |
|---|---|---|
| [`commands.py:79-86`](../aseprite_mcp/core/commands.py#L79) | `subprocess.run(..., encoding="utf-8", errors="replace")` | 非 ASCII 输出变乱码 |
| [`commands.py:113-117`](../aseprite_mcp/core/commands.py#L113) | 临时 `.lua` 以 `mode='w', encoding='utf-8'` 写 | 脚本里的中文路径变乱码，文件存到错的地方 |
| [`__init__.py:26`](../aseprite_mcp/__init__.py#L26) | 读 `SKILL.md` 指定 UTF-8 | instructions 变乱码 |
| [`fonts.py:102`](../aseprite_mcp/core/fonts.py#L102) | 读 `font.json` 指定 UTF-8 | 字体元数据变乱码 |
| [`preview.py:42,57,73`](../aseprite_mcp/tools/preview.py#L42) | PID 文件读写指定 UTF-8 | 影响很小，但保持一致 |

`errors="replace"` 是刻意的选择：宁可输出里出现替换字符，也不要因为一个坏字节让整次调用抛 `UnicodeDecodeError`。

回归测试：[`tests/test_encoding.py`](../tests/test_encoding.py)（用 `ASEPRITE_PATH=sys.executable` 伪造一个 Aseprite 来触发子进程解码路径）。

---

## 六、参数校验与 Lua 注入

### 目录穿越拒绝

[`commands.py:42-58`](../aseprite_mcp/core/commands.py#L42)：

```python
components = [p for p in re.split(r"[\\/]+", path) if p not in ("", ".")]
if ".." in components:
    return "Invalid filename: parent directory traversal not allowed"
```

三个细节：

- 按**两个分隔符**切分，所以 Windows 风格和 POSIX 风格都覆盖。
- `foo..bar.aseprite` 这种"点在一个组件内部"的情况**不误报**（它是整段比较，不是子串查找）。
- 绝对路径和 `~` **不被拒绝**。这个函数只管穿越，不管访问范围限制 —— 文档里不要把它写成沙箱。

### 颜色解析

[`core/colors.py:10-26`](../aseprite_mcp/core/colors.py#L10) 是唯一的十六进制颜色解析器：

```python
def parse_hex_color(value: str) -> tuple[int, int, int, int] | None:
```

| 接受的写法 | 说明 |
|---|---|
| `#RGB` / `RGB` | 每位复制一次（`#abc` → `#aabbcc`） |
| `#RGBA` | 同上，第 4 位是 alpha |
| `#RRGGBB` | alpha 默认 255 |
| `#RRGGBBAA` | 显式 alpha |

带不带 `#` 都可以，大小写不敏感，非法输入返回 `None`（调用方再翻成 `"Invalid color value ..."`）。

**尚未统一**：[`tilemap.py:9-16`](../aseprite_mcp/tools/tilemap.py#L9) 仍保留自己的 `_parse_hex_color`，只支持 6 位、无 alpha。这是遗留副本，见 [06 · 特效与网格结构](06-effects-and-tilemap.md#四已知不一致)。

### 数字参数的注入面

`pixels` 这类参数的类型是 `Dict[str, Any]`，`x`/`y` **不经过 schema 校验**就被插值进 Lua（`img:putPixel({x}, {y}, ...)`），绕过了 `lua_escape` 的引号保护。所以有：

```python
def parse_pixel_xy(pixel: dict) -> tuple[int, int] | None:
    try:
        return int(pixel.get("x", 0)), int(pixel.get("y", 0))
    except (TypeError, ValueError):
        return None
```

[`commands.py:29-39`](../aseprite_mcp/core/commands.py#L29)。`int()` 强制转换拒绝了 `3.5` 和字符串，也就关掉了注入通道 —— 回归测试用的载荷是 `"0) os.execute('boom') --"`（[`tests/test_pixel_xy_validation.py`](../tests/test_pixel_xy_validation.py)）。

### 校验顺序

统一在**生成任何 Lua 之前**完成，这样坏输入永远不会到 Aseprite：

```text
filename（prepare_filename）
→ 标量范围（width > 0、opacity ∈ [0,255]、frame_index ≥ 1 …）
→ 颜色解析
→ pixels 的 x/y 强制转换
→ 才拼脚本
```

---

## 七、错误契约

这是全项目最容易被误解的一点：**没有统一的返回信封**。

- 没有 `{"success": bool, ...}` 包装，没有结果对象。
- 没有自定义异常体系（唯一的自定义异常是字体模块的 `FontError`），没有全局异常处理器。
- 每个工具都是 `async def ... -> str`，返回一条给人看的字符串；FastMCP 把它包成 MCP 的 text content。
- 成功/失败**靠消息文本区分**。

### 四个前缀就是契约

[`tests/conftest.py:37-42`](../tests/conftest.py#L37) 是这条契约的权威定义：

```python
def ok(result):
    """Assert a tool call did not return an error message."""
    assert not str(result).startswith(
        ("Failed", "ERROR", "Invalid", "Script failed")
    ), result
```

对应的消息形态：

| 前缀 | 来源 | 例子 |
|---|---|---|
| `Failed ...` | Lua/子进程失败被 Python 包装 | `Failed to add layer: <output>` |
| `ERROR ...` | 脚本内的 `ERROR:` 被 `_checked` 剥前缀后仍以 ERROR 开头，或直接透出 | `ERROR:No active sprite` |
| `Invalid ...` | Python 侧校验 | `Invalid color value: '#GGGGGG'` |
| `Script failed ...` | 仅 `run_lua_script` | `Script failed: <output>` |

成功侧则是动宾短语 + 解析后的文件名，例如 `Layer 'body' added to D:/art/x.aseprite`，只读工具返回 `json.dumps` 后的字符串。

### 陷阱：`ok()` 覆盖不了范围校验类消息

`ok()` 只认那 4 个前缀，而大量范围校验直接返回普通句子：

```text
Width and height must be > 0
Start frame must be >= 1
End frame must be >= start frame
Opacity must be between 0 and 255
Tolerance must be between 0 and 255
Scale must be > 0
Duration must be > 0
Count must be >= 1
Position must be >= 1
Pixels list cannot be empty
Polygon requires at least 3 points
Unsupported anchor (center, topleft)
Unsupported easing (linear, ease_in, ...)
Unsupported out_of_range_action
create_canvas requires an ABSOLUTE filename, ...
No diff data returned
```

这些都**不会**被 `ok()` 拦下，测试会静默通过。`conftest.py:58-61` 已经承认这点，并用 `assert os.path.exists(path)` 给 `sprite` fixture 补了存在性断言。写新测试时不要只依赖 `ok()`。

### 可操作性上下文

缺目标的错误会带上"当前有什么"和"下一步做什么"，让 AI 一轮就能自我纠正：

```text
ERROR:Layer 'foo' not found. Existing layers: [body, armor]. Tip: call add_layer first; drawing tools auto-create top-level layers when create_if_missing=true.
```

[`drawing.py:379`](../aseprite_mcp/tools/drawing.py#L379)。帧越界则报出总帧数和 1-based 约定。回归测试：[`tests/test_visibility.py:239-265`](../tests/test_visibility.py#L239)。

---

## 八、进程生命周期

### 8.1 链上一共有三个进程

| 进程 | 谁启动 | 生命周期 | 谁负责收尸 |
|---|---|---|---|
| MCP server（本进程） | MCP client（经 `uv` 启动器链） | 整个会话 | **自己**，靠看门狗（8.2） |
| `aseprite --batch` | 每次工具调用 | 秒级，跑完即退 | 自然退出；**没有超时兜底** |
| `python -m http.server` | `start_preview_server` | 跨多次调用，直到显式停止 | `stop_preview_server`（8.4） |

### 8.2 客户端看门狗（`core/lifecycle.py`）

`install_client_watchdog()` 在 [`__main__.py:9`](../aseprite_mcp/__main__.py#L9) 里于 `mcp.run()` **之前**调用。它解决的是一类"孤儿进程堆积"问题，模块 docstring 记录了两个成因：

1. **client 的直接子进程不是 server**。`uv --directory ... run -m aseprite_mcp` 展开成 `uv.exe → python(venv launcher) → python -m aseprite_mcp`，而 venv launcher 不监视*它*的父进程，所以杀掉 client（或只杀掉 `uv.exe`）会留下两个 python 进程永久孤儿化。
2. **stdio 传输无法总是自己结束**。stdin EOF 时 reader 结束了，但 writer 还阻塞在一个没人关闭的流上，包裹它们的 task group 永不退出，`anyio.run()` 也就永不返回。

实测数据（写进 docstring 与根 README）：一个 server 在 stdin 关闭 20 秒后仍活着；每个崩溃/强杀会话累积一对约 60 MB 的孤儿，Windows 上除 `taskkill /T /F` 无法清除。

#### 判死信号

**stdin 是权威信号，且任何检查都不消费输入**（否则会把已缓冲的请求从传输层偷走）：

```python
def _stdin_eof() -> bool | None:
    """Tri-state: True = client gone, False = client connected, None = unknown."""
```

| 平台 | 手段 | 细节 |
|---|---|---|
| Windows | `PeekNamedPipe`（ctypes `kernel32`） | 成功 ⇒ `False`（有客户端在写）；`ERROR_BROKEN_PIPE`(109) ⇒ `True`；其他错误 ⇒ `None`（无法判断，例如 stdin 被重定向到文件） |
| POSIX | `select.poll` | **只注册 `POLLHUP \| POLLERR`**，这样"stdin 有数据可读"不会被误报成 EOF |
| macOS | 无 `poll` | 返回 `None`，交给父进程兜底 |

```python
poller.register(fd, select.POLLHUP | select.POLLERR)
```

[`lifecycle.py:142`](../aseprite_mcp/core/lifecycle.py#L142)。

**父进程只是兜底**，仅当 stdin 无法回答时才启用。优先级是刻意的（[`lifecycle.py:205-229`](../aseprite_mcp/core/lifecycle.py#L205)）：

> A readable stdin is *proof* the client is still connected, and it is deliberately allowed to veto the parent signal

因为客户端可能通过短命包装器启动 server（`cmd /c start`、分离式 spawner、shell 包装），此时父进程已死但会话完全可用 —— 信任父信号会让看门狗在健康会话里 `os._exit(0)`。反过来说，当父进程**就是**客户端时（比如直接 `python -m aseprite_mcp`），兜底既准确又即时。

`_ParentWatch` 的实现：Windows 用 `OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject`（内核在父进程一死就发信号，即使是被强杀）；POSIX 比较 `os.getppid()` 与启动时的值（ppid 为 1 表示已被 reparent，没有基准可比，直接判定为 `False`）。

#### 迟滞与退出方式

```python
_CONFIRMATIONS = 2   # 同一个答案必须连续出现两次
```

- 退出不可逆，所以条件要连续两次成立才动手。代价是最多让孤儿多活一个周期（2 秒）。
- probe 抛异常时**重置 strikes 而不是解除武装**（[`lifecycle.py:251-254`](../aseprite_mcp/core/lifecycle.py#L251)）—— 一个打嗝就自杀的看门狗比没有更糟。
- 退出走 `os._exit(0)`（[`lifecycle.py:278`](../aseprite_mcp/core/lifecycle.py#L278)）是刻意的：解释器**不能**去等那个被阻塞的传输 task 或任何非守护线程，因为那正是要逃离的状态。
- 线程是 daemon，名为 `mcp-client-watchdog`，默认每 2 秒（`DEFAULT_INTERVAL_SECONDS`）检查一次。

#### 开关与可测试性

`ASEPRITE_MCP_CLIENT_WATCHDOG` —— 未设置或空白视为**开启**，只有 `0` / `false` / `no` / `off` 关闭（[`lifecycle.py:77-82`](../aseprite_mcp/core/lifecycle.py#L77)）。关闭的典型场景：把 server 嵌在一个预期比它活得更久的非 MCP 父进程下，或 macOS 上隔着启动包装器（那里只有父信号可用，而它描述的可能是包装器而非客户端）。

`install_client_watchdog(*, interval, probe, on_client_gone)` 三个关键字参数可注入（[`lifecycle.py:257`](../aseprite_mcp/core/lifecycle.py#L257)）；**只要注入了 `probe`，就会跳过环境变量检查**，测试因此能在被禁用的环境下驱动逻辑。

### 8.3 子进程没有超时

`subprocess.run` 全程没有 `timeout=`。挂死的 Aseprite 会永久阻塞那一次工具调用 —— 没有兜底、没有取消路径。这是当前实现的真实缺口，不是文档遗漏。

### 8.4 preview server 的进程侧

[`tools/preview.py`](../aseprite_mcp/tools/preview.py) 是唯一启动**跨越多次调用**的进程的地方：

- 启动：`Popen([sys.executable, "-m", "http.server", port, "--directory", directory])`，Windows 用 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`，POSIX 用 `start_new_session=True`，stdout/stderr 丢进 `DEVNULL`。PID 写到 `tempfile.gettempdir()/aseprite_mcp_preview_<port>.pid`（UTF-8）。
- 重复启动保护：PID 文件存在时先探活（Windows `tasklist /FI "PID eq <pid>"`，POSIX `os.kill(pid, 0)`），活着就拒绝重复启动，僵死就删掉残留 PID 文件。
- 停止：读 PID，Windows `taskkill /PID <pid> /T /F`，POSIX `SIGTERM`；PID 文件在 `finally` 里删除。

它刻意绕开了 `prepare_filename`，改为 `resolve_path(directory) if directory else get_workspace_dir()`（[`preview.py:35`](../aseprite_mcp/tools/preview.py#L35)）—— 因为它服务的是一个**已存在的目录**，不是精灵文件。完整的预览闭环见 [07 · 导出与预览](07-output.md#七预览服务器的完整闭环)。

---

## 相关测试

| 测试 | 覆盖 |
|---|---|
| [`tests/test_path_resolution.py`](../tests/test_path_resolution.py) | 工作区解析、`~` 展开、穿越拒绝、锚定语义、`create_canvas` 只在成功后锚定、`run_lua_script` 的活跃文件回退。**纯单元测试，不需要 Aseprite** |
| [`tests/test_encoding.py`](../tests/test_encoding.py) | UTF-8 落盘与子进程解码。不需要真 Aseprite（monkeypatch / `ASEPRITE_PATH=sys.executable`） |
| [`tests/test_pixel_xy_validation.py`](../tests/test_pixel_xy_validation.py) | 非整数 `x`/`y` 的注入载荷在校验阶段被拒。不需要真 Aseprite |
| [`tests/test_lifecycle.py`](../tests/test_lifecycle.py) | 看门狗只触发一次、存活时不触发、需要连续两次、probe 异常不解除、环境变量关闭、stdin 检查不消费输入、stdin 优先于死父进程、父进程兜底，以及一个在真实 spawn 出的 server 上做的 A/B 孤儿测试 |
| [`tests/test_error_propagation.py`](../tests/test_error_propagation.py) | 非法输入必须报失败而非伪造成功（issue #15） |

> `tests/test_lifecycle.py::test_watchdog_is_what_ends_the_orphan_case` 是 A/B 端到端测试，对环境影响敏感（控制组依赖"看门狗关闭时 server 存活"），`.pytest_cache` 记录它曾失败过。

## 相关文档

- [01 · Lua 桥](01-lua-bridge.md) —— stdout 协议、转义、`ERROR:` 的产生与消费
- [07 · 导出与预览](07-output.md) —— 输出路径铁律的消费方、文件系统后验
- [development.md](development.md) —— 全部环境变量一览、测试如何跑、Docker 下的行为差异
