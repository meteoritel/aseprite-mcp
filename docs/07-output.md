# 07 · 导出与预览

常用导出与图片导入直接调用；`export_spritesheet`、`export_layers` 和本地 HTTP preview 属于扩展，经 `search_tools` 查找后使用 `call_tool` 执行。

[`tools/export.py`](../aseprite_mcp/tools/export.py) 负责将原生工程转为图像并发布精确目标。导出不修改源工程或切换活跃文件；产物路径作为文本或 JSON 返回。

## 生成、校验与发布

每次导出在目标父目录下创建独有暂存目录。CLI 产物只从该目录读取：普通图像匹配精确名称或受控数字序列，图层导出读取本次目录中的 PNG。旧目标和同前缀参考图不参与候选。

成功退出后继续验证：图像必须存在、可解码；单帧核对范围和尺寸；sheet JSON 核对可解析的帧集合；JE 额外核对布局和时长。合法透明图也可交付。

发布前将每个 replacement 和已有目标备份准备在目标旁，支持 JSON 输出位于另一个卷。用 `os.replace` 替换明确路径，普通 IO 失败逆向恢复已经替换的文件。恢复失败则保留备份并在错误中给出路径。清理只作用于本次拥有的暂存内容。

PNG 与 mcmeta 是独立文件，发布支持普通捕获到的 IO 失败恢复；系统崩溃时不提供跨文件原子提交。

## 通用工具

| 工具 | 产物与语义 |
|---|---|
| `export_sprite` | PNG 等静态序列或 GIF，返回实际发布集合 |
| `export_frame` | 验证 1-based 帧范围，发布精确 PNG，可整数倍放大 |
| `export_spritesheet` | horizontal／vertical／rows／columns／packed，可输出 Aseprite JSON 和按 tag 过滤 |
| `export_layers` | 分层 PNG，可包含隐藏层，返回实际发布集合 |
| `export_tag` | 已存在 tag 的 GIF 或编号 PNG 序列 |
| `copy_sprite` | 原生工程复制，默认拒绝覆盖，校验原生暂存后提交 |
| `import_image_as_layer` | 导入图片到明确 layer/frame，通过标准编辑提交 |

CLI 帧过滤在打开文件前设置；`--scale` 等导出选项按 Aseprite 的处理顺序构建。Aseprite JSON 是图集数据，Minecraft sidecar 由 JE 工具单独生成。

## Java Edition 纹理

`export_minecraft_texture` 输入原生工程、游戏 PNG 路径，可选择 `frame_index` 或 `tag_name`，两者互斥；默认使用整个时间线。

| 素材 | PNG | `.png.mcmeta` |
|---|---|---|
| 单帧 | 原画布尺寸 | `{}` |
| 动画 | 原宽 × 原高乘源帧数，垂直无 padding | animation，含 width／height、interpolate=false、逐引用的 index／time |

条带按源顺序存储每个帧一次。metadata 的 index 从选中区间的 0 开始；源帧 2–4 的索引为 0–2。三帧方向分别为 `[0,1,2]`、`[2,1,0]`、`[0,1,2,1]`、`[2,1,0,1]`，往返端点不重复。播放项时长使用对应源帧值，须为 50 ms 的正整数倍，否则发布前报错并提示 `set_frame_duration`。

固定原尺寸、vertical、无 trim／旋转；逐帧核对 Aseprite JSON 的矩形和 duration。8× 审阅图由最终 PNG 经 Pillow `NEAREST` 放大，保留 alpha，生成校验后再发布游戏文件。

返回 JSON 包含 `png`、`mcmeta`、`preview_png`、`preview_scale` 和 `frames`（source_frame／index／duration_ms）。preview 位于会话独有临时目录，lifespan 退出时删除；失败时清理本次 preview。静态覆盖动画时空 metadata 替换旧 animation。

交付到 Java 纹理及 metadata；具体游戏版本的资源包 manifest 由上层准备。

## 预览与验证

临时审阅图须在会话退出前查看。持久审阅图可显式调用通用导出；`start_preview_server` 提供本地 HTTP 目录预览，`stop_preview_server` 按端口 PID 停止。

`test_export.py` 独立解码 PNG／GIF，检查内容、布局和时长；`test_minecraft_export.py` 检查四种方向、RGBA、局部索引、8×、源保全、无新文件和发布恢复。`test_protocol.py` 覆盖真实会话的审阅图清理。
