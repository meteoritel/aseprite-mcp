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

默认测试围绕真实编辑、审阅、交付和会话生命周期组织，需要本机 Aseprite。工程和输出由 pytest 的 `tmp_path` 隔离；`tests/conftest.py` 提供独立工程和确定的 bitmap 字体，并在场景结束后重置活跃文件、清理审阅图。`tests/support.py` 集中承载 stdio 会话、按 requestId 暂存响应和独立 CLI 图片读取。

| 验证面 | 测试入口 |
|---|---|
| MCP 发现、绘制、回读、文字代理、JE 交付与失败恢复 | `tests/test_mcp_workflow.py` |
| 明确编辑目标、嵌套组、RGBA 回灌、区域编辑、复制与提交保全 | `tests/test_editing_workflow.py` |
| 可见合成、隐藏层和组、帧差与审阅图 | `tests/test_visual_workflow.py` |
| PNG／GIF、JE 时序、产物校验与发布恢复 | `tests/test_delivery_workflow.py` |
| 并发、取消、断开与客户端突然退出 | `tests/test_lifecycle.py` |
| 真实子进程的期限、预算、UTF-8 诊断与回收 | `tests/test_process_adapter.py` |

扩展场景和维护校验使用显式入口，按需执行：

```text
uv run --locked python -B -m pytest -p no:cacheprovider tests/optional/extension_workflows.py
uv run --locked python -B -m pytest -p no:cacheprovider tests/maintenance/checks.py
```

扩展链路验证 tilemap 的绘制、放置和渲染，slice 元数据往返，原生颜色处理与调色板读取，以及图层和 tag 精灵表交付。维护校验验证参考生成、接口变化检测和启动指令资源；这些文件不参与默认测试收集。

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
