# Aseprite MCP 工作流

受托绘制 Minecraft 纹理时，直接用 Aseprite MCP 工具在原生工程中绘制和修订。已有外部素材可导入指定图层。

1. 各层已有独立网格时，用 `create_canvas(initial_layers=[…])` 按从底到顶的顺序建立图层，再用 `draw_sprite_maps` 批量绘制。多层共用调色板时在批次顶层传一次 `palette`，单层可传自己的完整色板。只有一张复合网格时，查找 `create_layered_sprite`，用显式字符映射一次创建分层工程。同一字符可同时映射到底色和上层。
2. 用 `review_frame` 查看可见合成。编辑一层用 `layer_name`，一次读取多层用 `layer_names`。需要隔离图时传 `preview_mode="both"`。保存 `snapshot_id`，在 `cel.edit` 或 `cels` 中的编辑网格副本上修改像素。
3. 用 `draw_sprite_map` 或 `draw_sprite_maps` 提交改动。保持工程、帧、区域和图层顺序一致，再调用 `review_frame(before_id=…)` 核对合成和 cel 差异。快照限当前会话。合成或单层也可用前次 `data` 中的 `filename`、`frame`、`region`、`map`、`cel` 组成 `before`。
4. 用 `export_minecraft_texture` 交付 Java Edition 纹理。单件静态默认只发布 PNG，需要空 `.png.mcmeta` 时传 `emit_mcmeta="always"`。动画同时发布时序元数据。套装排在同一个单帧工程时，用 `create_slice` 创建命名切片，再用 `export_slices_to_minecraft` 批量交付。需要持久放大图时，另用 `export_frame(scale=8)` 输出展示 PNG。

接手已有素材时，用 `get_color_stats` 查看可见帧实际用色，用 `get_palette` 读取工程保存色板。需要量化并写回色板时使用 `extract_palette`。

## 工具发现与扩展调用

当前连接直接列出的核心工具可以按名称调用。任务需要的操作不在直接工具列表中、只知道效果而不知道工具名，或需要查询扩展工具的参数和示例时，先调用 `search_tools`，按工具名、用途词或类别查找完整目录。抖动填充、HSL 调整、文字、tilemap、切片、质量检查和高级动画等能力可从扩展目录发现。

默认搜索返回工具摘要和调用入口。选中工具后，用工具名和 `detail="full", limit=1` 获取 `inputSchema` 与 `examples`。`invocation="direct"` 表示直接调用该工具，`invocation="call_tool"` 表示将工具名和目标参数传给 `call_tool` 的 `name` 与 `arguments`。用 `next_offset` 继续浏览。

双色 Bayer 矩形填充可用 `search_tools(query="apply_dither_pattern", detail="full", limit=1)` 查调用契约。已有图层的透明轮廓抖动细节可直接调用核心工具 `draw_dither_detail`。

编辑 cel 时明确指定图层和帧，优先用精确图层路径。
