# Aseprite MCP

通过 MCP 让 AI 助手调用本机 [Aseprite](https://www.aseprite.org/)，创建、编辑和导出像素画、动画及游戏纹理。作品保存在 `.aseprite`／`.ase` 原生工程中，可继续用 Aseprite 编辑。

## 可以做什么

- **绘制与编辑**：绘制像素、图形和字符网格，从复合网格创建可编辑的分层工程，管理调色板与特效，导入图片。
- **制作动画**：编辑帧和图层内容，设置帧时长、播放区间与补间。
- **读取与审阅**：回读像素，检查可见合成、颜色统计和帧间差异，生成放大预览。
- **导出交付**：输出 PNG、GIF、精灵表及 Minecraft Java Edition 纹理。单件静态纹理默认发布 PNG，动画和命名切片同时发布 `.png.mcmeta`。
- **文字与瓦片**：绘制文字，编辑 tilemap 和 slice。

核心工具的定义由 MCP `tools/list` 提供。`search_tools` 浏览目录和调用入口，指定 `detail="full"` 可查参数和示例。 [绘制与交付流程](SKILL.md)

## 安装与配置

需要 Python 3.13+、uv 和本机安装的 Aseprite。在项目根目录安装依赖。 [uv](https://docs.astral.sh/uv/)

```sh
uv sync --locked
```

项目从源码目录运行，请保留根目录的 [SKILL.md](SKILL.md)，服务会读取其中的运行指令。

在支持 `mcpServers` 的客户端中添加以下配置，将占位路径替换为本机绝对路径。

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

`ASEPRITE_PATH` 指向 Aseprite 可执行文件，已加入 PATH 时可省略。`ASERITE_MCP_WORKSPACE` 指定相对素材路径的基准，变量名按示例保留。

Codex 在 `~/.codex/config.toml` 中使用对应的 TOML 配置。

```toml
[mcp_servers.aseprite]
command = "uv"
args = ["--directory", "YOUR_ASEPRITE_MCP_PATH", "run", "--locked", "-m", "aseprite_mcp"]

[mcp_servers.aseprite.env]
ASEPRITE_PATH = "YOUR_ASEPRITE_PATH"
ASERITE_MCP_WORKSPACE = "YOUR_WORKSPACE_PATH"
```

保存配置后重新连接 MCP。客户端找不到 `uv` 时，将 `command` 设为 uv 可执行文件的绝对路径。

## 开发

项目结构、执行流程和测试入口见 [开发者文档](docs/README.md)。
