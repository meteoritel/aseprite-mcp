# Aseprite MCP — AI 助手使用指南

## 文件处理

- 所有涉及精灵文件的工具都接受可选的 `filename`。第一个指明文件的调用会把它记为会话的**活跃文件**；后续调用可省略 `filename` 直接作用于它。会话中途再次传入 `filename` 即可切换文件。
- `create_canvas` 是例外：其 `filename` **必填**且必须是**绝对路径**（如 `"D:/art/sprites/coin.aseprite"`），相对路径会被拒绝。
- 其它工具中，绝对路径按原样使用，而相对路径基于 `ASERITE_MCP_WORKSPACE`（若客户端已设置）或 server 的工作目录解析 —— 因此优先使用绝对路径，且导出时 `output_filename` / `data_filename` 一律传绝对路径。
- 所有位置都拒绝父目录穿越（`..`）。

## 图层与帧

- 帧号在**所有位置都是 1-based**。
- **绘图类工具会自动创建图层和 cel**（`create_if_missing=true` 时，这是默认值）：`draw_pixels_at`、`draw_line_at`、`draw_rectangle_at`、`draw_circle_at`、`draw_ellipse_at`、`fill_area_at`、`draw_polygon`、`draw_path`、`apply_gradient_rect`、`apply_dither_pattern`、`apply_dither_gradient`、`draw_text`。因此可以直接对一个尚不存在的图层名作画。
- 自动创建**只处理顶层图层名**。含 `/` 的名字会被当作 `group/child` 路径解析，永远不会被凭空创建 —— 请先调用 `add_layer(group=…)` / `add_group(…)`。
- **其余多数工具要求图层已存在** —— 特效、变换、选区、tilemap、调色板、像素读取、多数动画操作。请先调用 `add_layer(layer_name=…)`，或用 `get_sprite_info()` 查询现有图层名。
- `copy_cel` 可以扩展精灵：当 `create_target_frame=true`（默认值）且 `target_frame` 超出末尾时，会自动补齐缺失的帧，并在回复中说明补了几帧。传 `false` 则改为报错。

## 读取像素：先选对工具族

- `get_pixel_color` / `get_pixels_rect` 读取**单个图层自己的 cel** —— 无论该图层是否隐藏，也不管其上方和下方的任何内容。
- `get_composite_pixel` / `get_composite_rect` / `get_color_stats` / `compare_frames` / `render_onion_skin` 读取**实际可见的结果**：`isVisible=false` 的图层会被排除，因此像素值与导出的 PNG 一致（`render_onion_skin` 会额外在画面及其幽灵帧下铺一层白底）。做配色、对比度、明度检查时用这几个。
- **tilemap 图层无法逐像素读取** —— tilemap 的 cel 存的是瓦片索引而非像素。上述两个工具会拒绝执行；请用 `get_tile_at` 读取某个格子的瓦片索引，或用 `get_composite_*` 读取渲染后的颜色。
- `extract_palette(max_colors=N)` 能给出的颜色**最多是 N−1**：Aseprite 固定把调色板 0 号槽留给精灵的透明色（即返回值里的 `transparent_index`），且量化器有时还填不满。`max_colors` 是槽位预算而非承诺 —— 真实槽位数看 `palette_size`，别按 `max_colors` 去规划配色。

## 典型工作流

```
create_canvas(32, 32, filename="D:/art/sprites/coin.aseprite")   # 记为活跃文件
draw_circle_at(layer_name="coin", frame_index=1, center_x=16, center_y=16, radius=8)
add_frames(count=3)                        # 只在需要更多帧时调用
export_sprite(output_filename="D:/art/sprites/coin.png")
```

当图层名或帧号不确定时先调用 `get_sprite_info()` —— 比猜测后重试更划算。