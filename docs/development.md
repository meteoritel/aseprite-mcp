# development · 环境、测试与部署

> 怎么把它跑起来、怎么验证改动、怎么打包，以及当前基础设施里已知的缺口。
> 相关文件：[`pyproject.toml`](../pyproject.toml) · [`requirements.txt`](../requirements.txt) · [`tests/conftest.py`](../tests/conftest.py) · [`Dockerfile`](../Dockerfile) · [`docker-compose.yml`](../docker-compose.yml) · [`.github/workflows/docker-build.yml`](../.github/workflows/docker-build.yml) · [`scripts/gen_tool_reference.py`](../scripts/gen_tool_reference.py)

---

## 一、环境与启动

### 前置

| 要求 | 说明 |
|---|---|
| Python **≥ 3.13** | `requires-python = ">=3.13"`，`.python-version` 也是 `3.13` |
| [`uv`](https://docs.astral.sh/uv/) | 唯一的依赖管理与运行方式 |
| Aseprite | 需要在 `PATH` 上，或由 `ASEPRITE_PATH` 指定 |

安装依赖：

```bash
uv sync          # 含 dev 组（pytest）
```

### 启动

```bash
uv run -m aseprite_mcp
```

[`__main__.py`](../aseprite_mcp/__main__.py) 做两件事：先 `install_client_watchdog()`，再 `mcp.run(transport='stdio')`。**没有 console script 入口**，`aseprite-mcp` 不是一个可执行命令（原因见第三节）。

### 客户端配置

项目自带的 [`.mcp.json`](../.mcp.json)：

```json
{
  "mcpServers": {
    "aseprite": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "-m", "aseprite_mcp"],
      "env": {}
    }
  }
}
```

注意它**没有 `--directory`**，所以依赖客户端的当前工作目录。跨目录启动时用根 README 里的形式：

```json
"args": ["--directory", "/path/to/aseprite_mcp", "run", "-m", "aseprite_mcp"],
"env": { "ASERITE_MCP_WORKSPACE": "${workspaceFolder}" }
```

### `.env` 的加载时机

[`commands.py:7-8`](../aseprite_mcp/core/commands.py#L7)：

```python
_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
dotenv.load_dotenv(dotenv_path=_ENV_PATH)
```

这是**模块导入时的副作用**，路径固定为仓库根（不是 cwd，也不是 server 的工作目录）。因为所有工具都间接导入 `core.commands`，仓库根的 `.env` 总是会被应用。

`.env` 被 `.gitignore` 忽略，提交的是 [`sample.env`](../sample.env)。

优先级：真实的进程环境与客户端 `env` 块正常优先于 `.env` 文件（`load_dotenv` 默认不覆盖已有变量）。

---

## 二、全部环境变量

| 变量 | 精确拼写 | 读取位置 | 默认值 | 作用 |
|---|---|---|---|---|
| `ASEPRITE_PATH` | ✅ | [`commands.py:75`](../aseprite_mcp/core/commands.py#L75)；shell: [`docker-entrypoint.sh:12-13`](../scripts/docker-entrypoint.sh#L12) | `aseprite`（查 `PATH`） | 所有 Aseprite 子进程的可执行文件路径 |
| `ASERITE_MCP_WORKSPACE` | ⚠️ **少一个 `P`** | [`state.py:28,58`](../aseprite_mcp/core/state.py#L28) | 未设 → `os.getcwd()` | 相对文件名解析的基准目录 |
| `ASEPRITE_MCP_CLIENT_WATCHDOG` | ✅ | [`lifecycle.py:62,79`](../aseprite_mcp/core/lifecycle.py#L62) | 启用；`0`/`false`/`no`/`off` 关闭 | 客户端存活看门狗 |
| `STEAM_USERNAME` | ✅ | [`docker-entrypoint.sh:5`](../scripts/docker-entrypoint.sh#L5)、[`install-aseprite-steam.sh:15,28`](../scripts/install-aseprite-steam.sh#L15) | 未设 | 容器内 SteamCMD 登录 |
| `STEAM_PASSWORD` | ✅ | 同上 | 未设 | 同上 |
| `STEAM_GUARD_CODE` | ✅ | [`install-aseprite-steam.sh:29-30`](../scripts/install-aseprite-steam.sh#L29) | 未设 | Steam Guard 二次验证码 |
| `STEAM_APPID` | ✅ | [`install-aseprite-steam.sh:12`](../scripts/install-aseprite-steam.sh#L12)、Dockerfile `ENV` | `431730` | Aseprite 在 Steam 上的 app id |
| `STEAM_INSTALL_DIR` | ✅ | [`install-aseprite-steam.sh:13`](../scripts/install-aseprite-steam.sh#L13)、Dockerfile `ENV` | `/opt/steamapps` | Steam 安装根目录 |

### ⚠️ `ASERITE_MCP_WORKSPACE` 的拼写

这是**代码里的既有拼写**，缺一个 `P`。它在以下位置完全一致地出现：

- [`state.py:28`](../aseprite_mcp/core/state.py#L28) 的常量定义、[`state.py:55`](../aseprite_mcp/core/state.py#L55) 的 docstring
- [`sample.env:6`](../sample.env#L6)
- 根 [`README.md`](../README.md) 与 [`SKILL.md`](../SKILL.md)
- [`tests/test_path_resolution.py`](../tests/test_path_resolution.py) 的 6 处
- [`__init__.py:13`](../aseprite_mcp/__init__.py#L13) 的 fallback instructions

所以**不要"顺手修正"文档里的这个名字** —— 那会让文档与实现不符，用户照文档设的变量名会失效。真要更正需要代码与文档同时改，属于破坏兼容的变更。

---

## 三、打包与依赖现状

### 项目不可安装

[`pyproject.toml`](../pyproject.toml) **没有 `[build-system]`**，也没有 `[project.scripts]`：

```toml
[project]
name = "aseprite-mcp"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.13"
dependencies = ["httpx>=0.28.1", "mcp[cli]>=1.6.0", "pillow>=10.0.0"]

[dependency-groups]
dev = ["pytest>=9.0.3"]
```

后果：

- `uv.lock` 把项目记为 `source = { virtual = "." }`，即**永不安装为包**。唯一受支持的运行方式是原地 `uv run -m aseprite_mcp`。
- 没有 console script，所以 `aseprite-mcp` 不是命令。
- `description` 还是脚手架占位符 `"Add your description here"`。
- `__version__` **有两处来源**：`pyproject.toml` 的 `0.1.0` 与 [`__init__.py:35`](../aseprite_mcp/__init__.py#L35) 里硬编码的 `"0.1.0"`，没有单一事实源。

### `requirements.txt` 与 `pyproject.toml` 冲突

[`requirements.txt`](../requirements.txt) 是陈旧的另一份清单：

| | `requirements.txt` | `pyproject.toml` |
|---|---|---|
| `httpx` / `mcp` | **缺**（真实运行时依赖） | 有 |
| `typing_extensions` / `black` / `flake8` | 有（未在别处声明，前两者也不被 import） | 无 |
| `pillow` | `>=10.0.0` | `>=10.0.0` ✅ |
| `pytest` | `>=8.0.0` | `>=9.0.3`（dev 组） |

**以 `pyproject.toml` 为准。** `requirements.txt` 既不是 `uv` 的输入也不被 Dockerfile 使用。

### `python-dotenv` 是未声明的直接依赖

[`commands.py:5`](../aseprite_mcp/core/commands.py#L5) 直接 `import dotenv`，但 `python-dotenv` **没有**列在 `pyproject.toml` 的 `dependencies` 里。它目前只是靠 `mcp` 的传递依赖恰好存在（`uv.lock` 里能看到 python-dotenv）。

**风险**：上游若收紧依赖，`.env` 加载会以 `ImportError` 崩掉。加新依赖时顺带把它补进 `pyproject.toml` 是低风险改进。

---

## 四、测试

### 定位：以集成测试为主

[`tests/conftest.py:1-4`](../tests/conftest.py#L1) 说得很直接：

> These tests run each MCP tool against a real Aseprite (`ASEPRITE_PATH`), so they are smoke/integration tests, not unit tests. Tests within a file form a sequence on a module-scoped sprite; files are independent.

所以跑测试**需要一个真的 Aseprite**：

```bash
# 确保 ASEPRITE_PATH 指向真实二进制（或它在 PATH 上）
uv run pytest
```

### `conftest.py` 提供的四样东西

| 名称 | 作用 |
|---|---|
| `BASE` | 固定的临时目录：Windows `%TEMP%/ase-pytest`，其它 `/tmp/ase-pytest` |
| `run(coro)` | `asyncio.run` 的包装，同步测试里调用 async 工具 |
| `ok(result)` | 断言返回值**不以** `Failed` / `ERROR` / `Invalid` / `Script failed` 开头 |
| `sprite` fixture | 每个测试模块一个全新的 32×32 sprite，含 `body` 图层与一块 `#D04648` 填充矩形 |

**为什么 `BASE` 不用 pytest 的 `tmp_path`**（[`conftest.py:6-11`](../tests/conftest.py#L6)）：

> Scratch files live under a fixed temp path (not pytest's `tmp_path`) so they resolve identically inside the Docker-wrapped Aseprite, which only mounts `/tmp` and `/var/folders`. On Windows, `/tmp/...` stopped counting as an absolute path in Python 3.13 (no drive letter), which `create_canvas` rejects — so use the platform temp dir there instead.

即：为了与 Docker 包装的 Aseprite 路径一致，以及绕开 Python 3.13 在 Windows 上不再把 `/tmp/...` 当绝对路径的问题。

`sprite` fixture 里那条额外的断言值得注意（[`conftest.py:58-61`](../tests/conftest.py#L58)）：

```python
# ok() only matches a few error prefixes; a message like "create_canvas
# requires an ABSOLUTE filename..." would slip through it silently.
# Asserting existence catches any such silent failure.
assert os.path.exists(path), f"sprite fixture did not create {path}"
```

这正是 [02 §7 那个陷阱](02-paths-errors-lifecycle.md#陷阱ok-覆盖不了范围校验类消息)在实践中的补丁。

### `ok()` 的局限

`ok()` 只认四个前缀。**范围校验类错误不在其中**，会被静默放过：

```text
Width and height must be > 0
Start frame must be >= 1
Opacity must be between 0 and 255
Scale must be > 0
Pixels list cannot be empty
Unsupported anchor (center, topleft)
Unsupported easing (...)
create_canvas requires an ABSOLUTE filename, ...
No diff data returned
```

写新测试时**不要只依赖 `ok()`** —— 对关键断言补上具体的内容检查或文件存在性检查。完整的消息清单见 [02 §7](02-paths-errors-lifecycle.md#陷阱ok-覆盖不了范围校验类消息)。

### 不需要真实 Aseprite 的测试

四个模块可以独立验证，改这些地方时不必配 Aseprite：

| 测试 | 为什么能脱离 Aseprite |
|---|---|
| [`tests/test_lifecycle.py`](../tests/test_lifecycle.py) | 看门狗是纯决策逻辑 + 可注入 probe；A/B 测试自己 spawn 一个真 server |
| [`tests/test_path_resolution.py`](../tests/test_path_resolution.py) | monkeypatch 掉 `execute_lua_script_checked` / `execute_lua_script` |
| [`tests/test_pixel_xy_validation.py`](../tests/test_pixel_xy_validation.py) | 校验在拼脚本前就返回，用一个 0 字节占位文件即可 |
| [`tests/test_encoding.py`](../tests/test_encoding.py) | monkeypatch `run_command`；两处用 `ASEPRITE_PATH=sys.executable` 当假 Aseprite |

[`tests/test_text.py`](../tests/test_text.py) 的 bitmap 与 measure 测试用 PIL 在磁盘上现造一个字体，只有 TrueType 那条需要系统装有字体，没装则 skip。

### 命名有两套风格

| 风格 | 命名 | 例子 |
|---|---|---|
| **镜像源模块** | `test_<模块名>.py` | `test_drawing` `test_sprite_map` `test_export` `test_layers` `test_text` `test_tilemap` `test_palette` `test_selection` `test_slices` `test_animation` `test_analysis` `test_fx` `test_native_fx` `test_script` |
| **按 bug / issue 命名** | `test_<主题>.py`，docstring 里写清 bug 经过 | `test_error_propagation` `test_group_layers` `test_create_into_group` `test_drawing_fixes` `test_auto_create` `test_visibility` `test_composite_read` `test_slices_pipe` `test_sprite_info_groups` `test_path_resolution` `test_pixel_xy_validation` `test_lifecycle` `test_encoding` |

新建回归测试请用第二种，并在模块 docstring 里写清"原来错在哪、现在为什么不会错"。

### 回归测试 ↔ 提交/issue 对照

| 测试 | 对应 |
|---|---|
| `test_error_propagation.py` | issue #15（退出码 0 却伪造成功） |
| `test_group_layers.py` + `test_create_into_group.py` + `test_sprite_info_groups.py` | issue #17（组图层可达性） |
| `test_slices_pipe.py` | `f51c97b`（slice 名里的 `\|` 破坏解析） |
| `test_drawing_fixes.py` | `20c5409`（多边形越界、渐变坐标、RGBA 颜色） |
| `test_composite_read.py` | `1676f8d`（合成读取） |
| `test_visibility.py` | `04d77ca`（合成读取排除隐藏层） |
| `test_auto_create.py` | `0f2bebf`（绘图工具自动建层） |
| `test_path_resolution.py` / `test_encoding.py` | `721a31e` / `2987155`（路径与 UTF-8 集中化） |
| `test_lifecycle.py` | `586420f`（客户端看门狗） |

### 已知失败

`.pytest_cache/v/cache/lastfailed` 记录 `tests/test_lifecycle.py::test_watchdog_is_what_ends_the_orphan_case` 曾失败。它是唯一在真实 spawn 出的 server 上做的 A/B 端到端测试，控制组依赖"看门狗关闭时 server 存活"，对运行环境敏感。

---

## 五、Docker

### 镜像构成

[`Dockerfile`](../Dockerfile)：

| 层 | 内容 |
|---|---|
| 基座 | `ghcr.io/homebrew/brew:latest` |
| 运行时 | `brew install python@3.13 uv`，`PATH` 前置 `/home/linuxbrew/.linuxbrew/bin` |
| apt 包 | `steamcmd` `lib32gcc-s1` `ca-certificates`（切到 `USER root`） |
| `ENV` | `STEAM_APPID=431730`、`STEAM_INSTALL_DIR=/opt/steamapps` |
| 项目 | `WORKDIR /app` → `COPY . .` → `uv sync` → `chmod +x scripts/*.sh` |
| 入口 | `ENTRYPOINT ["/bin/bash", "/app/scripts/docker-entrypoint.sh"]`，`CMD []` |

### ⚠️ 镜像里没有 Aseprite

这是 Docker 路径最关键的事实：**`docker build` 产出的镜像不含可用的 Aseprite。**

只有两个来源，都不在构建期：

1. **运行期用 SteamCMD 装**（[`scripts/install-aseprite-steam.sh`](../scripts/install-aseprite-steam.sh)），需要 `STEAM_USERNAME` / `STEAM_PASSWORD`（有 Steam Guard 时还要 `STEAM_GUARD_CODE`）。
2. **默认路径探测**（[`docker-entrypoint.sh:11-14`](../scripts/docker-entrypoint.sh#L11)）：`/opt/steamapps/common/Aseprite/aseprite` 可执行且 `ASEPRITE_PATH` 未设时自动设上。

宿主机的 Aseprite **无法**被容器内的 stdio 进程使用（没有挂载宿主路径），镜像里也没有 X11/GL 库。所以"不提供 Steam 凭据就用 Docker"这条路当前是走不通的。

### entrypoint 做两件事

```bash
# 1. 有凭据就尝试装 Aseprite（失败被吞掉）
if [[ -n "${STEAM_USERNAME:-}" && -n "${STEAM_PASSWORD:-}" ]]; then
  /app/scripts/install-aseprite-steam.sh || echo "[entrypoint] Steam install attempted. Proceeding..."
fi

# 2. 默认路径探测
if [[ -z "${ASEPRITE_PATH:-}" && -x "$DEFAULT_ASE" ]]; then
  export ASEPRITE_PATH="$DEFAULT_ASE"
fi

echo "ASEPRITE_PATH=${ASEPRITE_PATH:-aseprite}"
exec uv run -m aseprite_mcp
```

最后那个 `exec` 很重要：它让 server 成为 PID 1，stdin/stdout 保持直连。

### stdio over Docker 必须用 `-i`

传输是 stdio，所以客户端必须让 stdin 保持打开：

```bash
docker run --rm -i --env-file .env aseprite-mcp:latest
```

根 `README.md` 与 `DOCKER.md` 里写的是 `docker run -it`，[`docker-compose.yml`](../docker-compose.yml) 只设了 `stdin_open: true` + `tty: true`、也没暴露端口 —— 这些都不能让 compose 服务直接充当 MCP 传输。**只有 `docker run -i` 这个形态是验证过的**（CI 的 PR 冒烟测试用的就是它）。

`docker-compose.yml` 另有一个 `aseprite-mcp-dev` 服务（profile `dev`），入口是 `tail -f /dev/null`，用途是拿一个常驻 shell 手工调试。它声明了 `version: '3.8'`，这在 Compose v2 里已废弃。

### `.dockerignore` 的连带效果

[`.dockerignore`](../.dockerignore) 排除了 `docs/` 与除 `README.md` 外的所有 `*.md`：

```text
# Documentation
docs/
*.md
!README.md
```

两个后果：

1. **`SKILL.md` 不在镜像里**，所以 [`_load_skill_instructions()`](../aseprite_mcp/__init__.py#L18) 在容器内**恒定**走 `_FALLBACK_INSTRUCTIONS`。容器里的模型收到的是那段英文精简版，不是完整的中文 `SKILL.md`。
2. 本套 `docs/` 也不会进镜像 —— 对镜像体积是好事，但要知道容器里查不到文档。

### 文档与实现的偏差（尚未修）

| 偏差 | 实际 |
|---|---|
| `DOCKER.md` / `DOCKER_SETUP_SUMMARY.md` 声称有非 root 用户 `mcpuser` | Dockerfile 从未创建它，实际以 **root** 运行 |
| `DOCKER.md` 称 Python 3.13.5 / uv 0.8.0 / 镜像约 2.27 GB | Dockerfile 不 pin 任何版本 |
| `DOCKER.md` 引用的 `scripts/aseprite-docker.sh` | 它包装的是 `aseprite-from-source:latest`，本仓库没有构建该镜像的 Dockerfile |
| `install-aseprite-steam.sh:48` 把 export 追加到 `/etc/profile.d/aseprite.sh` | entrypoint 是非 login shell，不会 source 它；真正起作用的是 entrypoint 自己的默认路径探测 |

---

## 六、CI

[`.github/workflows/docker-build.yml`](../.github/workflows/docker-build.yml) 是仓库里**唯一**的工作流。

| 项 | 值 |
|---|---|
| 触发 | `push` 到 `main`/`develop` 与 `v*` tag；`pull_request` 到 `main` |
| 平台 | `linux/amd64,linux/arm64` |
| 缓存 | GHA cache，`mode=max` |
| 推送 | 非 PR 时推送；PR 只构建 |
| tag | branch / pr / semver（三档）/ 默认分支上的 `latest` |
| PR 冒烟 | `docker run --rm --entrypoint /bin/bash <image> -c "python3 --version && uv --version && ls -la /app"` |

### ⚠️ CI 不跑测试

工作流只做三件事：构建镜像、推送镜像、PR 上冒烟验证解释器和 uv 能跑。**27 个测试模块没有任何自动化入口** —— `uv run pytest` 完全依赖开发者本地手动执行。

这意味着一次只改了 Python 逻辑、没碰 Docker 的 PR，CI 会给绿灯而测试可能全红。**提交前请本地跑 `uv run pytest`。**

---

## 七、文档保鲜

### 工具清单是生成物

[`docs/reference/tools.md`](reference/tools.md) 由 [`scripts/gen_tool_reference.py`](../scripts/gen_tool_reference.py) 解析源码 AST 生成，**不要手改**。任何工具的新增、删除、改名、改签名、改 docstring 之后：

```bash
uv run python scripts/gen_tool_reference.py           # 重新生成
uv run python scripts/gen_tool_reference.py --check   # CI 友好：过期则退出 1
```

脚本是纯标准库 `ast`，**不需要 Aseprite、不需要装依赖**，所以可以在任何环境跑。它还会：

- 按 [`tools/__init__.py`](../aseprite_mcp/tools/__init__.py) 的顺序输出（与注册顺序一致）；
- 检测重复工具名，有则非零退出；
- 把模块 → 开发者文档的映射（`DOC_MAP`）和中文索引标签（`MODULE_SUMMARY`）写进索引表 —— **新增模块时要同步这两个字典**。

### `SKILL.md` 是运行时契约，不是普通文档

[`SKILL.md`](../SKILL.md) 被 [`_load_skill_instructions()`](../aseprite_mcp/__init__.py#L18) 读进 `FastMCP(instructions=...)`，在**客户端连接时推给模型**。它讲的是"模型应该怎样使用这些工具"（文件处理规则、哪些工具会自动建层、该用哪族读取工具、典型工作流）。

**改了工具契约就要同步它**，否则模型会拿着过时规则去调用。典型的触发场景：

- 新增/修改会自动创建图层的工具 → 更新"图层与帧"那节
- 改变 `filename` 的要求（如 `create_canvas` 的绝对路径规则） → 更新"文件处理"那节
- 新增读取类工具或改变合成语义 → 更新"读取像素：先选对工具族"那节
- 加了新的默认行为陷阱（如 `extract_palette` 的 N−1） → 补进去

### 本套 `docs/` 的定位

`docs/` 面向**贡献者**，讲机制与实现细节；`SKILL.md` 面向**模型**，讲怎么用；根 [`README.md`](../README.md) 面向**使用者**，讲有什么能做什么。三者受众不同，改代码时按上面的规则分别维护。

---

## 八、改代码前的检查清单

| # | 事项 |
|---|---|
| 1 | 加了新依赖？写进 `pyproject.toml`（顺带考虑补上缺声明的 `python-dotenv`） |
| 2 | 加了新工具模块？加进 [`tools/__init__.py`](../aseprite_mcp/tools/__init__.py)，否则不会注册；同步 `gen_tool_reference.py` 的 `DOC_MAP` 与 `MODULE_SUMMARY` |
| 3 | 改了任何工具签名或 docstring？重跑生成器并跑 `--check` |
| 4 | 改了工具契约？更新 `SKILL.md` |
| 5 | 本地跑 `uv run pytest`（CI 不会替你跑） |
| 6 | 新增回归测试按 bug 主题命名，docstring 里写清"原来错在哪" |
| 7 | 错误消息尽量落在 `Failed` / `Invalid` / `ERROR` / `Script failed` 四个前缀内，否则 `ok()` 拦不住 |
| 8 | 碰了输出路径？确认带 `must_exist=False, anchor=False`（[02 §4](02-paths-errors-lifecycle.md#四输出路径铁律)） |
| 9 | 碰了原生命令？用 `build_native_command_script` 而不是手写目标激活（[01 §6](01-lua-bridge.md#六corenativepy原生命令为什么要包装)） |
| 10 | 碰了合成读取？复用 `_COMPOSE_FRAME`，不要自己 `flatten()`（[08 §2](08-inspection-and-quality.md#二_compose_frame为什么不能直接用-flatten)） |

---

## 相关文档

- [docs/README.md](README.md) —— 架构总览、数据流、**新增工具的分步指南**
- [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md) —— 环境变量在代码里的语义
- [reference/tools.md](reference/tools.md) —— 生成器产物，改动工具后需要重新生成
