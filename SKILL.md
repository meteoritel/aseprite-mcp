# Aseprite MCP 工作流

受托绘制 Minecraft 纹理时，直接用 Aseprite MCP 工具在原生工程中绘制和修订。已有外部素材可导入指定图层。

1. 用 `create_canvas` 建立原生工程。用 `draw_sprite_maps` 批量绘制各层网格，按任务需要保持图层可独立编辑。
2. 用 `review_frame` 查看可见合成。局部修改时指定目标图层，保留本次审阅结果，从可编辑 cel 网格的副本制作改动。
3. 用 `draw_sprite_map` 提交局部修改。再次调用 `review_frame`，使用上次快照核对同一帧和区域。结合内联图、合成差异与目标 cel 差异确认结果。
4. 用 `export_minecraft_texture` 交付 Java Edition 纹理。动画先安排帧、时长和播放范围。保留原生工程供后续编辑。

核心工具可直接调用。查阅工具用途、参数和示例时使用 `search_tools`，按返回的调用入口执行。编辑 cel 时明确指定图层和帧，优先用精确图层路径。
