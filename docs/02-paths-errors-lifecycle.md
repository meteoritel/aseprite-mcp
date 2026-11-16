# 02 · 路径、错误与进程生命周期

## 路径与活跃文件

[`core/state.py`](../aseprite_mcp/core/state.py) 的 `prepare_filename` 成功返回绝对路径，失败抛 `ToolError`。它先使用显式文件名或会话活跃文件，检查原始路径中的 `..`，展开 `~`，基于工作区解析相对路径，再按需要检查存在性并锚定。

```python
filename = prepare_filename(filename)
output = prepare_filename(output_filename, must_exist=False, anchor=False)
```

`ASERITE_MCP_WORKSPACE` 指定工作区；未设置时使用 server 工作目录。该环境变量保留现有拼写。绝对路径直接使用。路径规则限制父目录穿越，不限制访问范围到工作区。

`create_canvas` 要求绝对文件名，只接受原生扩展名，省略扩展名补 `.aseprite`，默认拒绝覆盖。创建与提交成功后才锚定，失败保留原活跃文件。其它显式已有文件在解析成功时锚定。导出、复制目标、跨工程目标和中间文件使用 `anchor=False`。

## 错误契约

预期的参数、路径、Lua、进程、产物和发布错误统一抛 `mcp.server.mcpserver.exceptions.ToolError`。SDK 将它转为 `CallToolResult.isError=true`。成功工具返回可读文本或 JSON 字符串，错误状态不依赖文本前缀。

层错误应带目标名称、现有层列表和可执行提示。帧错误应说明外部编号从 1 开始。用户字符串先 `lua_escape`，像素字典坐标先 `parse_pixel_xy`，颜色通过 `core/colors.py` 解析；校验失败在提交前结束。

临时 Lua 与 JSON 使用 UTF-8；进程按 UTF-8 解码，无法解码的字节以替换字符保留诊断。失败诊断同时包含 stdout 与 stderr。

## 进程期限、输出与取消

[`core/commands.py`](../aseprite_mcp/core/commands.py) 用 `asyncio.create_subprocess_exec` 启动本次拥有的进程，异步 drain 双流并等待退出。`PROCESS_TIMEOUT_SECONDS` 为执行期限，`MAX_OUTPUT_BYTES` 为双流合计预算；超限作为错误结束，业务数据不截断为成功结果。

超时、取消或执行异常触发进程回收：POSIX 杀本次独立进程组，Windows 使用本次 PID 的 `taskkill /T /F`。等待回收后才删除 Lua 与业务暂存目录；AnyIO shield 保护清理，随后继续传播取消。

## 会话串行与退出

[`aseprite_mcp/__init__.py`](../aseprite_mcp/__init__.py) 的公开 middleware 锁住整个 `tools/call`，覆盖活跃文件解析、读取、编辑暂存、发布与结果生成。握手、discovery 和 `notifications/cancelled` 不取工具锁；等待中的调用取消后不会启动进程。

stdio 客户端断开后 SDK 结束 server。lifespan 清理当前会话的临时 8× 审阅图目录。独立 HTTP preview server 由 `start_preview_server`／`stop_preview_server` 和端口 PID 文件管理。

会话门控协调本 server 内的工具调用。外部 Aseprite GUI 或其它 server 同时写同一工程需要使用者协调。

## 验证入口

路径与编码见 `test_path_resolution.py`、`test_encoding.py`；执行期限、输出预算与回收见 `test_execution.py`；取消前工程保全见 `test_project_editing.py`；真实 MCP 的成功、失败、取消恢复与并发编辑见 `test_protocol.py`；断开退出见 `test_stdio_lifecycle.py`。
