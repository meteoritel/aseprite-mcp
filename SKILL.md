# Aseprite MCP 工作流

受托绘制 Minecraft 纹理时，直接在原生 `.aseprite` 工程中绘制、审阅并交付；外部 `.png` 参考图可直接只读检查与拼图比对，无需回退本地脚本。

## 核心主链路

1. **建布与初始化**：用 `create_canvas(initial_layers=[…], palette=[…])` 一次建立从底到顶的图层与工程色板（配置 `ASEPRITE_MCP_WORKSPACE` 后支持相对路径）；随后用 `draw_sprite_maps(palette=…, sync_palette=True)` 原子提交多层网格并同步色板。单图拆多层时经 `call_tool("create_layered_sprite", …)` 一次完成。
2. **审阅与多背景验收**：用 `review_frame` 查看 8× 预览与精确网格。涉及半透明 Alpha、暗色轮廓或 HUD/GUI 图标时，传 `backgrounds=["mc_hud", "mc_slot", "checker"]`（支持任意 `#RRGGBB`）并按需开 `show_grid=True`；纯视觉/差异复审传 `grid_mode="none"` 压缩返回体；需要长期留存给报告引用时传 `save_preview_to`。保存 `snapshot_id` 供下一轮对比。
3. **迭代与差异复核**：修改 `cel.edit` / `cels` 副本后调用 `draw_sprite_maps` 提交；复核时传 `review_frame(before_id=…)`。基线快照支持纯合成复审、子集或重排图层复审，并在省略 `palette` 时自动沿用已有颜色字符映射。
4. **交付**：用 `export_minecraft_texture` 发布 Java Edition 纹理（单帧默认仅出 PNG，需空 `.png.mcmeta` 传 `emit_mcmeta="always"`；动画自动校验 50 ms 游戏刻并生成竖条带与 `.png.mcmeta`）。

## 场景路由表（避免漏用已有工具）

| 场景 | 调用方式 | 目标工具 |
| --- | --- | --- |
| 套装多文件 / 多帧 / 参考 PNG 同屏对齐 | 直接调用 | `review_contact_sheet(filenames=[…], backgrounds=["mc_hud", "mc_slot"])` |
| 读取外部参考 PNG 的用色 / 网格 / 色板（只读不改活跃工程） | 直接调用 | `get_color_stats` / `get_sprite_map` / `extract_palette` / `review_frame` |
| 生成色相偏移明暗色阶（纯计算，零进程开销） | 直接调用 | `generate_color_ramp` |
| 跨 `.aseprite` 工程复制复用图层（如药水瓶/盔甲底座） | `call_tool` | `copy_layers_between_sprites` |
| 1px 轮廓描边 / HSL 调色 / 亮度对比度 / 模糊锐化 | `call_tool` | `outline_native` / `outline_cel` / `adjust_hsl_native` / `adjust_brightness_contrast` / `apply_convolution` |
| 已有轮廓加 Bayer 质感抖动 / 双色矩形抖动与渐变 | 直接 / `call_tool` | `draw_dither_detail`（直调）/ `apply_dither_pattern`、`apply_dither_gradient`（扩展） |
| 单画布命名切片套装批量交付 / 精灵表与分图层导出 | `call_tool` | `create_slice` + `export_slices_to_minecraft` / `export_spritesheet` / `export_layers` |
| 动画补间缓动 / 呼吸漂浮 / 场景与帧质量审计 | `call_tool` | `tween_cel_positions_eased` / `oscillate_cel_positions` / `validate_scene` / `audit_animation` / `animation_sanitize` |
| 像素文字 / Tilemap 瓦片 / 本地 HTTP 预览 | `call_tool` | `draw_text` / `create_tilemap_layer` / `start_preview_server` |

## 并发与扩展发现约定

- **多文件并发**：服务端按文件路径分锁并行调度。并行操作多个工程时，每次调用显式传入 `filename`（避免依赖单会话隐式活跃文件）。
- **发现与调用契约**：不确定工具名或需查参数时，调用 `search_tools(query=…)`（支持中英文意图词及 `category` 过滤），再用 `search_tools(query="<工具名>", detail="full", limit=1)` 获取完整 `inputSchema` 与已校验 `examples`。`invocation="direct"` 直接调用，`invocation="call_tool"` 经 `call_tool(name=…, arguments=…)` 执行。编写 `run_lua_script` 前先查 `search_tools`。
- **精确目标**：接手已有工程时，用 `get_color_stats` 看可见帧实际用色，用 `get_palette` 读保存色板；编辑 cel 明确指定图层路径与帧号。
