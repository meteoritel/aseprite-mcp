# Aseprite MCP — AI 助手使用指南

核心纹理流程：创建原生工程与层结构 → 用 `draw_sprite_maps` 一次提交各层网格 → 用 `review_frame` 取得精确网格与同源预览并打开预览 → 按需继续编辑 → 复制并修改动画帧 → 设置时长与 tag → 导出原尺寸 PNG、mcmeta 并审阅返回的 8× PNG。

## 工具调用

`tools/list` 固定公开核心工具及 `search_tools`／`call_tool`。`search_tools` 查询完整核心与扩展目录，返回 `inputSchema`、`outputSchema`、`examples`、类别和 `invocation`；`direct` 表示直接调用，`call_tool` 表示通过代理执行。按 schema 构造参数，输入对象中的未定义字段会报错。

所有成功调用都返回 `{summary, data}`：客户端直接读取 `structuredContent.data`，text content 是同一对象的 JSON。编辑回执含 `filename`、实际 `layer_paths` 和适用的 `frame`；导出路径在 `data.files`，JE 交付有专用载荷。`run_lua_script` 的原始 stdout 在 `data.stdout`，保留换行。失败使用 `isError=true`。

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
- `get_sprite_info` 返回图层的 `path` 段数组与 `type`。定位参数接受旧字符串或精确数组：`["art", "ink"]` 是组内图层，`["art/ink"]` 是名称含 `/` 的顶层图层；数组逐段要求唯一命中。旧字符串先匹配完整字面名称，再尝试组路径。
- 绘图默认可创建顶层图层和 cel；单段数组也可创建名称含 `/` 的顶层层。多段路径要求组与子层先用 `add_group`／`add_layer(group=…)` 建立；帧先用 `add_frame`／`add_frames` 建立。其它编辑多数要求目标已存在。
- `copy_frame` 复制所有叶层，包括隐藏层与嵌套组中的 cel；同帧复制保持工程原值。`copy_cel` 默认可补齐目标帧，`create_target_frame=false` 时越界报错。复制保留 cel 偏移、不透明度与 zIndex。
- 标准编辑在新原生工程保存、校验成功后提交；错误会作为 MCP 工具失败返回。`run_lua_script` 是任意 Lua 入口，脚本自行负责保存。

## 小画布与精确回灌

16×16／32×32 纹理优先用网格。单层用 `draw_sprite_map`，多层或跨帧用 `draw_sprite_maps(maps=[…])`；每个 map 显式指定 layer/frame 及网格。批量按列表顺序覆盖，一次 Aseprite 执行、一次保存提交；任一 map 失败则保持原工程。`rows` 自上而下，每行等宽；`palette` 将单字符映射为 `#RGB`／`#RGBA`／`#RRGGBB`／`#RRGGBBAA`。

- `transparent` 默认为 `"."`，默认跳过该格；传 `erase_transparent=true` 才擦除。
- `mirror_x`／`mirror_y` 在原网格宽高内补出反射坐标。着色先合并，透明擦除只作用于剩余格；不同显式颜色在同一镜像位置相撞会报错。
- `get_sprite_map` 默认 `max_colors=0, alpha_threshold=1`，保留 alpha 大于零的原 RGBA。单 cel RGB 读取的 `rows`／`palette`／`transparent` 可回灌；要删除透明格时同时传 `erase_transparent=true`。
- 返回 `lossy` 表示阈值过滤或量化是否实际改变像素。显式过滤或量化后的结果用于观察或有意简化配色；自动字符分配排除 transparent 和已占字符，容量不足时报错，可分区读取或显式量化。
- 精确网格要求 RGB 工程；其它模式先 `set_color_mode(mode="rgb")`。

## 读取与审阅

- `review_frame(frame_index=…, region=可选矩形, palette=可选映射)` 一次执行生成同源的 `data.map` 和 `data.preview_png`。打开返回的 8× nearest-neighbor PNG，结合网格检查形状与颜色；预览寿命为当前会话。颜色超出单字符容量时缩小 region，或使用 `get_sprite_map(max_colors=…)` 显式量化读取。
- `get_pixel_color`／`get_pixels_rect`／默认的 `get_sprite_map` 读取明确 layer/frame 的单 cel，忽略图层可见性。
- `get_composite_pixel`／`get_composite_rect`／`get_sprite_map(composite=true)`／`get_color_stats`／`compare_frames` 读取实际可见合成。隐藏层和隐藏组被排除；合成网格适合审阅。
- tilemap 的 cel 保存索引；通过代理调用扩展 `get_tile_at` 读瓦片，用核心合成读取查看渲染色。
- `extract_palette(max_colors=N)` 的预算包含透明槽，实际颜色看返回的 `colors` 和 `palette_size`。
- 普通 PNG／GIF 用 `export_frame`／`export_sprite`／`export_tag`；`render_onion_skin` 输出白底幽灵帧 PNG。
- 单 cel 网格的 `source="cel"`、`layer` 为实际路径数组；合成网格的 `source="composite"`、`layer=null`。合成网格用于审阅，分层修改继续提交各层 map。
- quality 工具按明确结构要求检查：`ensure_layers_present` 只给已存在的图像层补 cel，任一目标缺失即失败；`validate_scene` 报缺失层与 cel。范围/重叠规则优先用结构化路径对象；非法旧格式会明确报错。
- `draw_text` 正常 alpha 合成，透明字形空洞保留底图；`data.stamp_bounds` 返回包含描边/阴影、尚未按画布裁剪的全局矩形。需要单独管理文本时，显式选择独立图层。

## Java Edition 交付

`export_minecraft_texture(output_filename=游戏PNG绝对路径)` 默认导出完整时间线；可选 `frame_index` 或 `tag_name`，两者互斥。

- 游戏 PNG 保持原尺寸：静态为原画布，动画为无间距的垂直条带，每个选中源帧只存一次。
- 相邻 `.png.mcmeta`：静态为 `{}`；动画按 tag 方向生成区间内从 0 开始的播放索引，每次引用使用源帧时长，关闭插帧。
- `pingpong` 的播放索引如 `[0,1,2,3,2,1]`；PNG 条带只存选中源帧各一次，源帧号仍从 1 开始。
- 动画时长须为正整数 tick，即 50 ms 的正整数倍；不满足时先用 `set_frame_duration` 调整。
- `data` 包含 `png`、`mcmeta`、`preview_png`、`preview_scale` 和源帧映射。`preview_png` 是最终游戏 PNG 的 8× nearest-neighbor 审阅图，随 stdio 会话退出删除；审阅须在会话结束前完成。
- 用原生工程持续编辑，PNG 和 mcmeta 放入游戏纹理目录。此工具交付纹理及 metadata，资源包 manifest 由目标游戏版本决定。

```python
create_canvas(16, 16, filename="D:/art/coin.aseprite")
draw_sprite_map(layer_name="coin", frame_index=1,
                rows=[".AA.", "ABBA", ".AA."],
                palette={"A": "#8B5A2B", "B": "#F2C48D"})
get_sprite_map(layer_name="coin", frame_index=1, x=0, y=0, width=4, height=3)
export_minecraft_texture(output_filename="D:/art/coin.png")
```
