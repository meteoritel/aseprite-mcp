# 开发者文档

Aseprite MCP 将绘制、审阅和导出请求转换为本机 Aseprite 批处理，以 `.aseprite` 或 `.ase` 工程保存可编辑状态。PNG、GIF 和 Minecraft 纹理是从该工程生成的交付产物。

## 阅读路径

1. 了解 MCP 请求如何进入工具层，以及工程如何编辑、读取和交付。 [运行架构](architecture.md)
2. 启动服务、运行测试、维护工具契约。 [本地开发](development.md)

## 工具契约

`tools/list` 返回核心工具的说明与 schema。`search_tools` 查询工具目录，默认返回摘要、必填参数名和调用入口。用工具名和 `detail="full", limit=1` 查输入与输出 schema 及示例。
