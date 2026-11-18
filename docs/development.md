# 本地开发

## 启动

开发环境使用 Python 3.13+、uv 和本机 Aseprite。在仓库根目录运行以下命令。

```sh
uv sync --locked
uv run --locked -m aseprite_mcp
```

服务通过 stdio 启动，读取仓库根目录的环境文件和运行指令。`ASEPRITE_PATH` 或 PATH 用来定位 Aseprite。`ASERITE_MCP_WORKSPACE` 指定相对素材路径的基准，默认使用服务工作目录。 [环境变量示例](../sample.env) · [运行指令](../SKILL.md)

客户端从其他目录启动时，使用 `uv --directory <仓库绝对路径> run --locked -m aseprite_mcp`。Codex 使用 TOML 配置，支持 `mcpServers` 的客户端使用 JSON。 [安装与配置](../README.md#安装与配置)

## 维护工具契约

1. 在工具层定义函数。用类型注解描述输入与输出，用 docstring 描述用途。docstring 的 `Args` 和 Pydantic 字段描述进入输入 schema。 [契约实现](../aseprite_mcp/core/contracts.py)
2. 在目录中登记核心或扩展归属。需要示范多字段搭配时，在目录登记输入示例。装配时校验并发布到 `inputSchema.examples`。 [工具目录](../aseprite_mcp/tool_catalog.py)
3. 通过真实 stdio 检查核心工具列表、扩展发现和实际执行结果。 [协议测试](../tests/test_toolchain_workflow.py)

## 验证

默认测试覆盖会话、原生编辑、审阅和交付。测试工程写入 pytest 临时目录。

```sh
uv run --locked python -B -m pytest -p no:cacheprovider
```

按需运行扩展工作流和启动资源检查。

```sh
uv run --locked python -B -m pytest -p no:cacheprovider tests/optional/extension_workflows.py tests/maintenance/checks.py
```
