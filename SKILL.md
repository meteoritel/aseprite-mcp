# Aseprite MCP 工作流

受托绘制 Minecraft 纹理时，直接用 Aseprite MCP 工具在原生工程中绘制和修订。已有外部素材可导入指定图层。

1. 各层已有独立网格时，用 `create_canvas(initial_layers=[…])` 按从底到顶的顺序建立图层，再用 `draw_sprite_maps` 批量绘制。多层共用调色板时在批次顶层传一次 `palette`，单层可传自己的完整色板。只有一张复合网格时，查找 `create_layered_sprite`，用显式字符映射一次创建分层工程。同一字符可同时映射到底色和上层。
2. 用 `review_frame` 查看可见合成。局部修改时指定目标图层，保留本次审阅结果，从可编辑 cel 网格的副本制作改动。
3. 用 `draw_sprite_map` 提交局部修改。再次调用 `review_frame`，使用上次快照核对同一帧和区域。结合内联图、合成差异与目标 cel 差异确认结果。
4. 单件或动画用 `export_minecraft_texture` 交付 Java Edition 纹理。套装排在同一个单帧工程时，查找 `create_slice` 创建命名切片，调用 `export_slices_to_minecraft` 批量交付原尺寸 PNG 和静态 `.png.mcmeta`。保留原生工程供后续编辑。需要持久放大图时，另用 `export_frame(scale=8)` 输出展示 PNG。

## 工具发现与扩展调用

当前连接直接列出的核心工具可以按名称调用。任务需要的操作不在直接工具列表中、只知道效果而不知道工具名，或需要查询扩展工具的参数和示例时，先调用 `search_tools`，按工具名、用途词或类别查找完整目录。抖动填充、HSL 调整、文字、tilemap、切片、质量检查和高级动画等能力可从扩展目录发现。

根据搜索结果的 `invocation` 选择入口：`direct` 表示直接按结果中的工具名调用；`call_tool` 表示调用 `call_tool`，并把结果中的工具名和目标参数分别传入 `name` 与 `arguments`。按返回的 `inputSchema` 和 `examples` 组织参数，不猜测扩展工具名称或参数。分页结果带有 `next_offset` 时，用该值继续查询。

例如，需要将一个矩形填成双色 Bayer 抖动时，若直接工具列表里没有 `apply_dither_pattern`，先用 `search_tools` 查询该工具，再按其 `invocation` 执行。已有图层的透明轮廓抖动细节可直接调用核心工具 `draw_dither_detail`。

编辑 cel 时明确指定图层和帧，优先用精确图层路径。
