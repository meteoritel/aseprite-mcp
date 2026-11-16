# 01 · Lua 桥与 Aseprite 调用

[`core/commands.py`](../aseprite_mcp/core/commands.py) 执行异步 batch 进程；业务工具负责 Lua 和产物语义。每次执行重新打开工程，选中状态只在该进程内有效。

## 异步执行接口

| 方法 | 输入与结果 |
|---|---|
| `await run_command(args)` | 添加 `ASEPRITE_PATH`，运行 CLI，返回 stdout 字符串 |
| `await execute_lua_script(script, filename=None)` | 写 UTF-8 临时 Lua，运行后删除；可无工程执行 |
| `await execute_lua_script_checked(script, filename=None)` | 在执行成功后，将 stdout 行首 `ERROR:` 转为 `ToolError` |

启动、非零退出、超时和输出超限均抛 `ToolError`；非零退出保留退出码及 stdout／stderr。任意 Lua 的空 stdout 合法。进程用 `asyncio.create_subprocess_exec`，输出并行读取，执行期限与总输出预算集中在命名常量中；生命周期见 [02](02-paths-errors-lifecycle.md)。

## stdout 与字符串

Lua 的 `return` 值不会作为工具结果传回。脚本用 `print` 发出 `ERROR:`、`OK`、JSON 或工具自己的记录，如 `PIXEL:`、`DIFF:`、`SLICE:`。工具解析自己的负载；缺少预期内容时抛工具错误。

用户文本插入 Lua 字符串前经过 `lua_escape`，转义反斜杠、两种引号、换行、回车和 NUL。图层引用用 `lua_layer_ref`／`lua_layer_refs` 保留字符串或路径数组；像素对象在 MCP 参数模型中要求显式整数 x/y，直接 Python 调用另由 `parse_pixel_xy` 检查。

## 共享 Lua

[`core/lua.py`](../aseprite_mcp/core/lua.py) 集中承载这些规则：

| 片段 | 规则 |
|---|---|
| `FIND_LAYER` | 字符串先 BFS 完整字面匹配，再按组路径最长前缀回溯；数组逐段唯一匹配；输出路径保持完整名称 |
| `ENSURE_LAYER` | 查层；允许创建时只创建顶层名称，单段数组允许字面名称包含 `/` |
| `LAYER_NAMES` | 错误诊断中的现有层列表 |
| `EDIT_TARGET` | `require_frame`／`require_layer`／`require_cel` 验证明确目标 |
| `NORMALIZE_CEL` | 保留画布内原图，转换为画布大小、位置为原点的 cel，供全局坐标编辑 |
| `CEL_COPIES` | 递归叶层，快照图像、位置、opacity、zIndex，再写入目标 |
| `PSET` | 画布内写像素，丢弃越界目标像素 |
| `HSL` | RGB 与 HSL 运算 |

Aseprite 保存时可裁紧 cel，逐像素绘图必须先归一化到画布，才能在原图边缘以外新增笔画。复制则保留源 cel 原始边界与偏移。

## 原生编辑提交

[`core/editing.py`](../aseprite_mcp/core/editing.py) 为标准编辑注入 `save_project(sprite)`，将结果保存到目标同目录的独有暂存位置。执行与原生头校验成功后，`os.replace` 提交精确目标；失败与提交前取消保持源工程。已经验证的同目标空操作用内部 `PROJECT_UNCHANGED` 标记跳过保存，标记由编辑层移除。

`app.transaction` 包住业务修改，`save_project(spr)` 在修改完成后调用。所有标准保存通过该入口；读取不保存。

编辑层返回 `EditExecution(stdout, layer_paths)`；`EDIT_TARGETS:` 为内部回执记录，解析后移除。工具用 `edit_output` 返回类型化成功载荷。Lua 查找生成完整段路径；quality 内部以图层 id 关联规则，因为重复取得的 Layer userdata 虽相等，作为 Lua table key 时仍是不同键。Aseprite `json.decode` 的数组是可索引的 JsonObj；共享定位按字符串与路径序列区分输入。

## 原生命令与任意 Lua

`core/native.py` 的 `build_native_command_script` 先查明并激活 layer/frame/cel，再设置可选区域选区，执行 `app.command.*{ui=false}`，最后走标准保存。原生命令依赖进程内 active 状态，包装器在每次调用重新建立目标。

`run_lua_script` 提供任意 Lua，使用同一进程超时、输出预算与取消管理；修改保存由脚本负责。需要提交时调用 `spr:saveAs(spr.filename)`。工具的 `data.stdout` 保留原始脚本输出与换行。
