# development · 本地环境与验证

项目从源码 checkout 运行，使用 Python 3.13+、uv 和本机 Aseprite。[pyproject.toml](../pyproject.toml) 声明直接依赖，[uv.lock](../uv.lock) 固定解析结果。

## 安装与启动

```text
uv sync --locked
uv run --locked -m aseprite_mcp
```

将 [sample.env](../sample.env) 复制为 `.env`，按需设置 `ASEPRITE_PATH`。跨目录启动使用：

```text
uv --directory /absolute/path/to/aseprite_mcp_2 run --locked -m aseprite_mcp
```

入口调用 `create_server()` 装配核心工具和发现入口，再启动 stdio。根 [SKILL.md](../SKILL.md) 是必需的运行指令；文件缺失、不可读或空白时启动失败，stderr 指出路径及恢复动作。

## 客户端配置

所有客户端使用相同 stdio 命令，替换示例中的绝对路径。Windows 路径可使用 `D:/art/...` 形式；若客户端找不到 `uv`，将 `command` 改为 uv 可执行文件的绝对路径。

### Codex

在 `~/.codex/config.toml` 的 MCP 配置中加入：

```toml
[mcp_servers.aseprite]
command = "uv"
args = ["--directory", "/absolute/path/to/aseprite_mcp_2", "run", "--locked", "-m", "aseprite_mcp"]

[mcp_servers.aseprite.env]
ASERITE_MCP_WORKSPACE = "/absolute/path/to/art-project"
```

配置字段参见 [Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp)。

### Claude Code

项目 `.mcp.json` 使用以下格式，配置字段见 [Claude Code MCP 文档](https://code.claude.com/docs/en/mcp)：

```json
{
  "mcpServers": {
    "aseprite": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/aseprite_mcp_2", "run", "--locked", "-m", "aseprite_mcp"],
      "env": {"ASERITE_MCP_WORKSPACE": "/absolute/path/to/art-project"}
    }
  }
}
```

仓库自带的 [.mcp.json](../.mcp.json) 使用原地启动，适用于以仓库为工作目录的客户端。

### Antigravity

在 MCP Servers 的 Manage MCP Servers → View raw config 中，将以下条目并入 `mcpServers`，入口说明见 [Antigravity MCP 文档](https://antigravity.google/docs/mcp/)：

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/aseprite_mcp_2", "run", "--locked", "-m", "aseprite_mcp"],
      "env": {"ASERITE_MCP_WORKSPACE": "/absolute/path/to/art-project"}
    }
  }
}
```

连接后直接调用核心工具；扩展通过 `search_tools` 读取完整 schema，再使用 `call_tool(name=目标名称, arguments=参数对象)`。已知名称时可直接代理调用。搜索结果是普通工具输出，各客户端均使用标准 MCP `tools/list`／`tools/call`。客户端针对代理入口配置工具策略，逐目标独立策略由同一入口承载。

## 环境变量与源码运行

| 变量 | 默认值 | 用途 |
|---|---|---|
| `ASEPRITE_PATH` | `aseprite`，由 PATH 查找 | 本机 Aseprite 可执行文件 |
| `ASERITE_MCP_WORKSPACE` | server 工作目录 | 相对文件路径的解析基准，保留此精确拼写 |

`core/commands.py` 在模块导入时加载仓库根 `.env`，路径与客户端 cwd 无关。`load_dotenv` 保留已存在的进程变量，因此客户端 `env` 优先于 `.env`。工具发现只构建描述；Aseprite 在实际需要它的工具执行时启动。

源码通过 `python -m aseprite_mcp` 运行。根 SKILL 和源码目录需要同时保留；pyproject 的依赖与 uv lock 是环境的唯一输入。直接依赖包括 MCP SDK、anyio、Pillow、Pydantic 和 python-dotenv；pytest 在 dev 组。

## 测试与参考生成

```text
uv lock --check
uv sync --locked
uv run --locked python -B scripts/gen_tool_reference.py
uv run --locked python -B scripts/gen_tool_reference.py --check
uv run --locked python -B -m pytest -p no:cacheprovider
git diff --check
```

标准编辑测试需要本机 Aseprite。`tests/conftest.py` 在 `tempfile.gettempdir()` 下为每次运行创建 UUID 隔离目录，每个场景使用独立原生工程；退出仅清理本次目录。

| 验证面 | 测试入口 |
|---|---|
| 原生编辑、group、cel 元数据与失败保全 | `test_project_editing.py` |
| 网格 RGBA、镜像与回灌 | `test_sprite_map.py`、`test_project_editing.py` |
| PNG／GIF、JE 时序和发布恢复 | `test_export.py`、`test_minecraft_export.py` |
| 可见合成与隐藏层 | `test_visibility.py` |
| 进程超时、取消、预算与回收 | `test_execution.py`、`test_encoding.py` |
| 标准发现、扩展代理、JE 闭环、串行与断开 | `test_protocol.py`、`test_stdio_lifecycle.py` |
| 注册副作用、完整 schema、确定性参考 | `test_tool_catalog.py` |

参考生成器只解析目录字面量和源码 AST，无需 Git 元数据、第三方依赖或 Aseprite。归属、签名及 docstring 变化会使 `--check` 报过期。IDE 分析使用项目 `.venv`；包版本相关提示结合该解释器中的实际导入与协议测试判断。

客户端产品验收时，记录客户端版本，依次检查核心调用、搜索完整 schema、代理调用、工具错误的显示；协议自动测试独立覆盖服务端契约。


## 客户端验收调用

使用已登录的客户端连接后，依次执行以下普通工具调用，并检查结果：

```text
list_palette_presets {}
search_tools {"query":"list_convolution_matrices","category":"native_fx"}
call_tool {"name":"list_convolution_matrices","arguments":{}}
call_tool {"name":"measure_text","arguments":{"text":"A","font":"missing-for-client-smoke"}}
```

核心调用返回调色板预设；搜索结果包含完整 inputSchema；代理返回卷积矩阵名称；最后一次调用应显示包含 measure_text 上下文的工具失败。调用前后公开列表保持一致，扩展目标通过 call_tool 执行。
