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

[`__main__.py`](../aseprite_mcp/__main__.py) 导入工具并调用 `mcp.run(transport='stdio')`。**没有 console script 入口**，`aseprite-mcp` 不是一个可执行命令（原因见第三节）。

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

[`commands.py:7-8`](../aseprite_mcp/core/commands.py)：

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
| `ASEPRITE_PATH` | ✅ | [`commands.py:75`](../aseprite_mcp/core/commands.py)；shell: [`docker-entrypoint.sh:12-13`](../scripts/docker-entrypoint.sh#L12) | `aseprite`（查 `PATH`） | 所有 Aseprite 子进程的可执行文件路径 |
| `ASERITE_MCP_WORKSPACE` | ⚠️ **少一个 `P`** | [`state.py:28,58`](../aseprite_mcp/core/state.py) | 未设 → `os.getcwd()` | 相对文件名解析的基准目录 |
| `STEAM_USERNAME` | ✅ | [`docker-entrypoint.sh:5`](../scripts/docker-entrypoint.sh#L5)、[`install-aseprite-steam.sh:15,28`](../scripts/install-aseprite-steam.sh#L15) | 未设 | 容器内 SteamCMD 登录 |
| `STEAM_PASSWORD` | ✅ | 同上 | 未设 | 同上 |
| `STEAM_GUARD_CODE` | ✅ | [`install-aseprite-steam.sh:29-30`](../scripts/install-aseprite-steam.sh#L29) | 未设 | Steam Guard 二次验证码 |
| `STEAM_APPID` | ✅ | [`install-aseprite-steam.sh:12`](../scripts/install-aseprite-steam.sh#L12)、Dockerfile `ENV` | `431730` | Aseprite 在 Steam 上的 app id |
| `STEAM_INSTALL_DIR` | ✅ | [`install-aseprite-steam.sh:13`](../scripts/install-aseprite-steam.sh#L13)、Dockerfile `ENV` | `/opt/steamapps` | Steam 安装根目录 |

### ⚠️ `ASERITE_MCP_WORKSPACE` 的拼写

这是**代码里的既有拼写**，缺一个 `P`。它在以下位置完全一致地出现：

- [`state.py:28`](../aseprite_mcp/core/state.py) 的常量定义、[`state.py:55`](../aseprite_mcp/core/state.py) 的 docstring
- [`sample.env:6`](../sample.env#L6)
- 根 [`README.md`](../README.md) 与 [`SKILL.md`](../SKILL.md)
- [`tests/test_path_resolution.py`](../tests/test_path_resolution.py) 的 6 处
- [`__init__.py:13`](../aseprite_mcp/__init__.py) 的 fallback instructions

所以**不要"顺手修正"文档里的这个名字** —— 那会让文档与实现不符，用户照文档设的变量名会失效。真要更正需要代码与文档同时改，属于破坏兼容的变更。

---

## 三、打包与依赖现状

### 项目不可安装

[`pyproject.toml`](../pyproject.toml) **没有 `[build-system]`**，也没有 `[project.scripts]`：

运行依赖与版本约束以 `pyproject.toml` 和 `uv.lock` 为准。

后果：

- `uv.lock` 把项目记为 `source = { virtual = "." }`，即**永不安装为包**。唯一受支持的运行方式是原地 `uv run -m aseprite_mcp`。
- 没有 console script，所以 `aseprite-mcp` 不是命令。
- `description` 还是脚手架占位符 `"Add your description here"`。
- `__version__` **有两处来源**：`pyproject.toml` 的 `0.1.0` 与 [`__init__.py:35`](../aseprite_mcp/__init__.py) 里硬编码的 `"0.1.0"`，没有单一事实源。

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

[`commands.py:5`](../aseprite_mcp/core/commands.py) 直接 `import dotenv`，但 `python-dotenv` **没有**列在 `pyproject.toml` 的 `dependencies` 里。它目前只是靠 `mcp` 的传递依赖恰好存在（`uv.lock` 里能看到 python-dotenv）。

**风险**：上游若收紧依赖，`.env` 加载会以 `ImportError` 崩掉。加新依赖时顺带把它补进 `pyproject.toml` 是低风险改进。

---

## 四、测试

集成测试使用真实 Aseprite，`ASEPRITE_PATH` 指向二进制或已有 wrapper。Pillow 独立解码 PNG／GIF；工程读取会重新打开原生文件。执行与发布失败条件使用受控 Python 子进程或定向注入。

```bash
uv run python -B -m pytest -p no:cacheprovider
uv run python -B -m pytest tests/test_export.py::test_export_tag_gif tests/test_export.py::test_import_image_as_layer tests/test_visibility.py::test_compare_frames_ignores_hidden_layer
```

`tests/conftest.py` 在平台临时根下创建每次运行独有目录，兼容 wrapper 的临时路径挂载。`new_sprite` 工厂和 `sprite` fixture 为各场景创建独立工程；测试自建 tag、导入图片和输出文件，活跃文件在测试间重置。清理只删除本次运行拥有的文件和 review 目录。

`run(coro)` 驱动直接工具调用；`failure(coro)` 验证抛出 `ToolError` 并提供诊断供断言。成功还须检查手写预期的像素、结构或产物；MCP 测试检查 `isError`。

| 场景 | 入口 |
|---|---|
| 原生编辑、group、cel 元数据与失败保全 | `test_project_editing.py` |
| 网格 RGBA、镜像冲突与回灌 | `test_sprite_map.py`、`test_project_editing.py` |
| PNG／GIF、JE 时序、发布恢复 | `test_export.py`、`test_minecraft_export.py` |
| 隐藏层差异与可见合成 | `test_visibility.py` |
| 超时、取消、输出预算与进程回收 | `test_execution.py`、`test_encoding.py` |
| discovery、tools/call、取消恢复、并发编辑 | `test_protocol.py` |
| 客户端断开退出 | `test_stdio_lifecycle.py` |

协议读取和生命周期握手都有截止时间，失败时回收测试拥有的进程。IDE 分析应使用项目 `.venv`；系统解释器中的不同 MCP 版本可能产生导入和类型误报，以项目实际依赖与运行结果核对。

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

1. **`SKILL.md` 不在镜像里**，所以 [`_load_skill_instructions()`](../aseprite_mcp/__init__.py) 在容器内**恒定**走 `_FALLBACK_INSTRUCTIONS`。容器里的模型收到的是那段英文精简版，不是完整的中文 `SKILL.md`。
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

工作流只构建镜像、推送镜像，并在 PR 上冒烟验证解释器和 uv。测试目前没有自动化入口，`uv run pytest` 依赖开发者本地执行。

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

[`SKILL.md`](../SKILL.md) 被 [`_load_skill_instructions()`](../aseprite_mcp/__init__.py) 读进 `MCPServer(instructions=...)`，在**客户端连接时推给模型**。它讲的是"模型应该怎样使用这些工具"（文件处理规则、哪些工具会自动建层、该用哪族读取工具、典型工作流）。

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
| 7 | 预期失败抛 `ToolError`；直接测试检查异常，协议测试检查 `isError` |
| 8 | 碰了输出路径？确认带 `must_exist=False, anchor=False`（[02 §4](02-paths-errors-lifecycle.md)） |
| 9 | 碰了原生命令？用 `build_native_command_script` 而不是手写目标激活（[01 §6](01-lua-bridge.md)） |
| 10 | 碰了合成读取？复用 `_COMPOSE_FRAME`，不要自己 `flatten()`（[08 §2](08-inspection-and-quality.md#二_compose_frame为什么不能直接用-flatten)） |

---

## 相关文档

- [docs/README.md](README.md) —— 架构总览、数据流、**新增工具的分步指南**
- [02 · 路径、错误与进程生命周期](02-paths-errors-lifecycle.md) —— 环境变量在代码里的语义
- [reference/tools.md](reference/tools.md) —— 生成器产物，改动工具后需要重新生成
