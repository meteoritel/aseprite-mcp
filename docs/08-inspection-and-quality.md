# 08 · 读取、分析与质量校验

像素、网格、帧审阅和 analysis 工具直接调用；quality 工具经 `call_tool` 执行。`search_tools` 返回完整目录、schema、示例与调用入口；完整签名见[工具参考](reference/tools.md)。

## 单 cel 与可见合成

| 工具 | 读取目标 | `data` |
|---|---|---|
| `get_pixel_color` | 指定 layer/frame 的单个 cel 像素，忽略可见性 | `{x,y,hex,r,g,b,a}` |
| `get_pixels_rect` | 指定 cel 的矩形 | 上述像素对象数组 |
| `get_composite_pixel` | 指定帧的可见合成像素 | 像素对象 |
| `get_composite_rect` | 可见合成矩形 | 像素对象数组 |
| `get_sprite_map` | 单 cel，或 `composite=true` 的可见合成 | 精确字符网格及来源 |
| `review_frame` | 指定帧的可见合成，可选区域 | 同源网格与会话临时 8× PNG |

坐标以画布左上角为原点。单 cel 读取先减去 cel 偏移；读取区域落在图像外的像素返回透明黑，尺寸保持请求值。单 cel 定位接受旧字符串与精确路径数组，规则见[画布与图层](04-layers-and-canvas.md)。

tilemap cel 保存瓦片索引，单 cel 像素读取会拒绝该目标并提示 `get_tile_at`；合成读取返回实际渲染色。图像层的精确 RGBA 回灌使用 `get_sprite_map`，格式与透明擦除见[绘图文档](03-painting.md#字符网格sprite-map)。网格的 `source="cel"` 时 `layer` 为真实路径数组；`source="composite"` 时 `layer=null`。

## 可见合成

[`core/composite.py`](../aseprite_mcp/core/composite.py) 的 `COMPOSE_FRAME` 由像素读取、网格、analysis 与 review 共用。它克隆工程，递归删除隐藏层与隐藏组后再展平，让 Aseprite 处理混合模式、组不透明度和 tilemap 渲染。

临时克隆中保留占位层，使全隐藏工程仍可展平为透明图。遍历遇到隐藏组时整体删除该组，其子层随组删除；可见组继续递归检查子层。最终输出画布尺寸 RGBA，保留 cel 偏移和透明度的渲染结果。克隆只用于读取，源工程不保存。

## 同源帧审阅

`review_frame(filename="", frame_index=…, region=None, palette=None)` 只启动一次 Aseprite。该进程输出指定帧的可见合成 PNG，Python 从相同 RGBA 生成精确字符网格和 8× nearest-neighbor PNG。

返回 `data.filename`、`frame`、`map`、`preview_png`、`preview_scale=8`、`preview_lifetime="session"`。`map` 包含实际区域的 `x/y/width/height`、`rows/palette/transparent` 与 `lossy=false`。region 省略时覆盖整张画布；传入时宽高为正像素尺寸，支持画布外透明区域。palette 可复用上一轮映射，保持字符稳定。

打开 `preview_png` 检查形状，用 `map` 检查精确颜色。分层修改继续提交各层网格。颜色超出单字符容量时，缩小 region，或用 `get_sprite_map(max_colors=…)` 显式量化读取。

原始合成中间图在调用结束时删除；结果尚未完整形成即失败时清理本次预览。成功交付的预览由会话 lifespan 统一清理，须在会话退出前完成审阅。

## 图像分析

[`tools/analysis.py`](../aseprite_mcp/tools/analysis.py) 提供：

| 工具 | 行为 |
|---|---|
| `render_onion_skin` | 白底、邻帧按由远到近的顺序正常 alpha 合成，再叠当前帧；输出 nearest-neighbor PNG，路径在 `data.files` |
| `compare_frames` | 比较两个可见帧的 RGBA，返回变化像素数、比例与可选包围盒；两点都完全透明时视为相同 |
| `get_color_stats` | 可见帧的非透明像素计数与 RGB 颜色直方图，按使用量返回 top 颜色 |

`compare_frames` 没有变化时省略 `changed_bounds`。`get_color_stats` 按 RGB 汇总颜色，精确 alpha 检查使用像素或网格读取。

## 结构校验与修复

[`tools/quality.py`](../aseprite_mcp/tools/quality.py) 检查调用方声明的图层、cel、活动帧范围和矩形重叠。图层引用复用共享定位，默认遍历所有嵌套叶层；规则以实际图层 id 关联，输出使用完整路径数组。

| 工具 | 行为 |
|---|---|
| `ensure_layers_present` | 必填目标名单，先解析全部已有图像层，再补建指定帧范围内缺失的画布尺寸空 cel；任一层缺失或类型不支持即失败，保留源工程 |
| `validate_scene` | 必填要求名单；返回 `frames`、`range`、`missing_layers` 与 `missing_cels`，只读 |
| `audit_animation` | 检查指定层对的 cel 矩形重叠，以及声明活动范围外的 cel；只读 |
| `animation_sanitize` | 补 cel、同级图层排序、处理活动范围外的 cel，并返回分析；`report_only=true` 时保持工程原值 |

活动范围和重叠对优先使用结构化对象：

```json
{
  "layer_frame_ranges": [{"layer": ["character", "body"], "ranges": [[1, 8], [17, 24]]}],
  "overlap_pairs": [{"a": ["character", "body"], "b": ["effects", "glow"]}]
}
```

旧格式 `"body:1-8,17-24"` 与 `"body,glow"`／`"body:glow"` 继续支持。非法格式、倒序范围、越界帧、缺失目标或重复范围声明均明确失败；规则解析在编辑前完成。未声明活动范围的图层，其全部帧视为允许。

重叠按 cel 的 AABB 判断，边缘接触不算重叠。`max_overlaps` 和 `max_out_of_range` 控制返回样本；audit summary 中对应的 `*_total` 与 `*_truncated` 给出总数及截断状态。`report_cels=true` 附每帧 cel 清单，`report_bounds=true` 附矩形信息。

sanitize 的 `layer_order` 表示同一父级下的叶层从底到顶顺序；名单外同级层保留相对顺序并排在其后，跨父级名单报错。`ensure_layers` 只接受已有图像层。`out_of_range_action` 支持 `set_opacity_zero`、`delete_cels`、`none`；默认把 cel opacity 设为 `out_of_range_opacity=0`。`ignore_full_canvas_overlaps=true` 跳过任一 cel 为全画布尺寸的重叠对。

sanitize 返回 `reordered`、`ensured`、`out_of_range`、`opacity_set`、`deleted`、`analysis`、路径化 `layer_stats`、`alerts` 与 `overlap_samples`。report_only 下，`reordered/ensured` 表示拟执行效果，`opacity_set/deleted` 保持实际修改计数零；`out_of_range` 仍报告待处理 cel。统计 bounds 为 `[min_x,min_y,max_x,max_y]`，无 cel 时为 null。

## 验证入口

- [工具链工作流](../tests/test_toolchain_workflow.py)：精确路径、嵌套同名目标、quality 失败保全与修复、审阅逐像素一致、进程/提交次数和失败清理。
- [可见工作流](../tests/test_visual_workflow.py)：隐藏层/组、帧差、颜色统计与独立 CLI 导出一致。
- [MCP 工作流](../tests/test_mcp_workflow.py)：真实 stdio 的批量编辑、审阅、文字代理与 JE 交付闭环，以及会话退出清理。
- [可选扩展链路](../tests/optional/extension_workflows.py)：tilemap 的索引、渲染色与错误恢复。
