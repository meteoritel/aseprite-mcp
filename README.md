# Aseprite MCP

通过 MCP 让 AI 助手调用本机 [Aseprite](https://www.aseprite.org/)，创建、编辑和导出像素画、动画及游戏纹理。作品保存在 `.aseprite`／`.ase` 原生工程中，可继续用 Aseprite 编辑。

## 可以做什么

- **绘制与编辑**：绘制像素、图形和字符网格，管理图层、调色板与特效，导入图片。
- **制作动画**：编辑帧和图层内容，设置帧时长、播放区间与补间。
- **读取与审阅**：回读像素，检查可见合成、颜色统计和帧间差异，生成放大预览。
- **导出交付**：输出 PNG、GIF、精灵表，以及 Minecraft Java Edition 纹理和 `.png.mcmeta`。
- **文字与瓦片**：绘制文字，编辑 tilemap 和 slice。

核心工具可以直接调用；文字、tilemap、slice 等扩展通过 `search_tools` 查找，再由 `call_tool` 执行。完整工具与参数见[工具参考](docs/reference/tools.md)。

多层像素网格用 `draw_sprite_maps` 一次提交，再用 `review_frame` 取得同源精确网格和 8× 临时预览。所有成功结果统一为 `{summary,data}`，客户端读取 `structuredContent.data`；工具发现覆盖完整目录，并返回 schema、示例和调用入口。

## 安装与配置

需要 Python 3.13+、[uv](https://docs.astral.sh/uv/) 和本机安装的 Aseprite。下载或克隆本项目后，在项目根目录安装依赖：

```sh
uv sync --locked
```

项目从源码目录运行，请保留根目录的 [SKILL.md](SKILL.md)，服务会读取其中的运行指令。

在支持 `mcpServers` 配置的客户端中添加以下条目，将路径替换为本机的绝对路径：

```json
{
  "mcpServers": {
    "aseprite": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory", "YOUR_ASEPRITE_MCP_PATH",
        "run", "--locked", "-m", "aseprite_mcp"
      ],
      "env": {
        "ASEPRITE_PATH": "YOUR_ASEPRITE_PATH",
        "ASERITE_MCP_WORKSPACE": "YOUR_WORKSPACE_PATH"
      }
    }
  }
}
```

`ASEPRITE_PATH` 指向 Aseprite 可执行文件；已加入 PATH 时可省略。`ASERITE_MCP_WORKSPACE` 指定素材工作目录，用于解析相对路径，变量名按示例保留。macOS 和 Linux 使用对应的本机绝对路径。

保存配置后重新连接 MCP。Codex、Claude Code 等客户端的配置位置和格式见[客户端配置](docs/development.md#客户端配置)。如果客户端找不到 `uv`，将 `command` 改为 uv 可执行文件的绝对路径。

## 详细文档

- [使用流程与工程约定](SKILL.md)：创建工程、明确编辑目标、网格回灌与审阅。
- [工具参考](docs/reference/tools.md)：工具归属、参数和调用方式。
- [导出与纹理交付](docs/07-output.md)：图像导出、Minecraft 动画时序和审阅图。
- [本地开发与验证](docs/development.md)：环境变量、启动方式和测试入口。
- [开发者文档](docs/README.md)：架构、数据流和各领域的实现说明。
