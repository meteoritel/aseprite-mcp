# Aseprite MCP — AI 助手使用指南

核心纹理流程：创建原生工程 → 显式 layer/frame 绘制 → 精确回读 → 复制并修改动画帧 → 设置时长与 tag → 导出原尺寸 PNG、mcmeta 和会话临时 8× 审阅图。核心工具直接调用；文字、tilemap、补间等扩展统一通过 `search_tools` 发现，再经 `call_tool` 执行。

## 工具调用

`tools/list` 固定公开核心工具及 `search_tools`／`call_tool`。扩展以原名称和参数使用，搜索、调用与重连均保持同一公开列表。搜索结果是普通工具输出，其中提供完整 `inputSchema`、类别和说明；按 schema 构造 `arguments` 即可代理执行。

```python
search_tools(query="draw_text", category="text")
call_tool(name="draw_text", arguments={
    "text": "A", "font": "字体名称或路径", "x": 0, "y": 0,
    "layer_name": "label", "frame_index": 1
})
```

已知扩展名称时可直接 `call_tool`，无需先搜索。空 query 可浏览类别；返回 `available_categories` 和下一页 `next_offset`，末页为 null。未知名称、非法参数及执行失败均作为工具失败返回。核心工具直接调用，代理只接受扩展。

文字与字体查询、tilemap／slice、补间、额外滤镜、场景／质量校验、分层／精灵表导出和本地 HTTP 预览属于扩展。完整归属与参数见 [工具参考](docs/reference/tools.md)；文字用法见 [绘图文档](docs/03-painting.md)，瓦片与滤镜见 [特效文档](docs/06-effects-and-tilemap.md)。客户端针对 `call_tool` 入口配置工具策略，扩展目标共用此入口。

## 文件与编辑目标

- 用 `create_canvas(width, height, filename=绝对路径)` 创建可编辑工程。省略扩展名会补 `.aseprite`，接受 `.aseprite`／`.ase`；覆盖已有工程须明确传 `overwrite=true`。
- 第一个成功解析的已有 `filename`，或成功创建的工程，会成为会话活跃文件；后续调用可省略 `filename`。其它相对路径基于 `ASERITE_MCP_WORKSPACE` 或 server 工作目录。导出路径应传绝对路径，输出不会切换活跃工程。路径拒绝 `..`。
- 每次 cel 编辑都明确传 `layer_name` 与 `frame_index`。所有外部帧号从 1 开始。批处理进程之间只保存工程内容，不保存 UI 的选层、选帧状态。
- 绘图用 `draw_pixels_at`、`draw_line_at`、`draw_rectangle_at`、`draw_circle_at`、`draw_ellipse_at`、`fill_area_at`、`draw_polygon`、`draw_path`、`apply_gradient_rect` 或 `draw_sprite_map`；文字使用扩展 `draw_text`。编辑坐标以画布左上角为原点。
- 绘图默认可自动创建顶层图层和 cel；帧须先用 `add_frame`／`add_frames` 建立。含 `/` 的层名按组路径查找，组和子层须先用 `add_group`／`add_layer(group=…)` 创建。其它编辑多数要求图层已存在；用 `get_sprite_info` 查层树、帧时长和 tag。
- `copy_frame` 复制所有叶层，包括隐藏层与嵌套组中的 cel；同帧复制保持工程原值。`copy_cel` 默认可补齐目标帧，`create_target_frame=false` 时越界报错。复制保留 cel 偏移、不透明度与 zIndex。
- 标准编辑在新原生工程保存、校验成功后提交；错误会作为 MCP 工具失败返回。`run_lua_script` 是任意 Lua 入口，脚本自行负责保存。

## 小画布与精确回灌

16×16／32×32 纹理优先用 `draw_sprite_map`。`rows` 自上而下，每行等宽；`palette` 将单字符映射为 `#RGB`／`#RGBA`／`#RRGGBB`／`#RRGGBBAA`。

- `transparent` 默认为 `"."`，默认跳过该格；传 `erase_transparent=true` 才擦除。
- `mirror_x`／`mirror_y` 在原网格宽高内补出反射坐标。着色先合并，透明擦除只作用于剩余格；不同显式颜色在同一镜像位置相撞会报错。
- `get_sprite_map` 默认 `max_colors=0, alpha_threshold=1`，保留 alpha 大于零的原 RGBA。单 cel RGB 读取的 `rows`／`palette`／`transparent` 可回灌；要删除透明格时同时传 `erase_transparent=true`。
- 返回 `lossy` 表示阈值过滤或量化是否实际改变像素。显式过滤或量化后的结果用于观察或有意简化配色；自动字符分配排除 transparent 和已占字符，容量不足时报错，可分区读取或显式量化。
- 精确网格要求 RGB 工程；其它模式先 `set_color_mode(mode="rgb")`。

## 读取与审阅

- `get_pixel_color`／`get_pixels_rect`／默认的 `get_sprite_map` 读取明确 layer/frame 的单 cel，忽略图层可见性。
- `get_composite_pixel`／`get_composite_rect`／`get_sprite_map(composite=true)`／`get_color_stats`／`compare_frames` 读取实际可见合成。隐藏层和隐藏组被排除；合成网格适合审阅。
- tilemap 的 cel 保存索引；通过代理调用扩展 `get_tile_at` 读瓦片，用核心合成读取查看渲染色。
- `extract_palette(max_colors=N)` 的预算包含透明槽，实际颜色看返回的 `colors` 和 `palette_size`。
- 普通 PNG／GIF 用 `export_frame`／`export_sprite`／`export_tag`；`render_onion_skin` 输出白底幽灵帧 PNG。

## Java Edition 交付

`export_minecraft_texture(output_filename=游戏PNG绝对路径)` 默认导出完整时间线；可选 `frame_index` 或 `tag_name`，两者互斥。

- 游戏 PNG 保持原尺寸：静态为原画布，动画为无间距的垂直条带，每个选中源帧只存一次。
- 相邻 `.png.mcmeta`：静态为 `{}`；动画按 tag 方向生成区间内从 0 开始的播放索引，每次引用使用源帧时长，关闭插帧。
- 动画时长须为正整数 tick，即 50 ms 的正整数倍；不满足时先用 `set_frame_duration` 调整。
- 返回 JSON 包含 `png`、`mcmeta`、`preview_png`、`preview_scale` 和源帧映射。`preview_png` 是最终游戏 PNG 的 8× nearest-neighbor 审阅图，随 stdio 会话退出删除；审阅须在会话结束前完成。
- 用原生工程持续编辑，PNG 和 mcmeta 放入游戏纹理目录。此工具交付纹理及 metadata，资源包 manifest 由目标游戏版本决定。

```python
create_canvas(16, 16, filename="D:/art/coin.aseprite")
draw_sprite_map(layer_name="coin", frame_index=1,
                rows=[".AA.", "ABBA", ".AA."],
                palette={"A": "#8B5A2B", "B": "#F2C48D"})
get_sprite_map(layer_name="coin", frame_index=1, x=0, y=0, width=4, height=3)
export_minecraft_texture(output_filename="D:/art/coin.png")
```
