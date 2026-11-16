# 05 · 动画

[`tools/animation.py`](../aseprite_mcp/tools/animation.py) 管理 cel、帧区间、tag、可见性及位置补间。`canvas.py` 提供单帧追加与时长编辑。所有外部帧号从 1 开始；标准修改通过原生暂存提交。

帧、cel、tag 和图层属性工具直接调用。位置补间、批量移动、缓动与振荡通过 `search_tools(category="animation")` 查找，再用 `call_tool(name=目标名称, arguments=原参数对象)` 执行；完整归属见 [工具参考](reference/tools.md#animationpy)。

## 帧与 cel

frame 是时间线位置，拥有时长；cel 是 layer/frame 上的图像，拥有位置、opacity 和 zIndex。图层的 opacity 与 cel opacity 分别影响合成。

`add_frame`／`add_frames` 建帧；`set_frame_duration` 编辑单帧，`set_frame_duration_all` 编辑全时间线。`create_cel`、`clear_cel` 管理明确 layer/frame 的 cel，`set_cel_position` 和 `set_cel_opacity` 修改其属性。仅剩一帧时 `delete_frame` 拒绝删除。

`get_sprite_info` 经 `core/inspection.py` 读取画布、递归层树、帧时长和 tag，返回 JSON；导出复用同一内部读取函数。

## 快照复制

`core/lua.py` 的 `CEL_COPIES` 在目标删除或扩帧前克隆源图像，保存 position、opacity 与 zIndex。复制整帧递归遍历所有叶层，包含隐藏层与嵌套组；group 本身没有 cel。

| 工具 | 目标与覆盖语义 |
|---|---|
| `copy_frame` | 目标省略则追加，采用源时长；已有目标保留原时长。`overwrite=false` 只补缺 cel |
| `propagate_frame_to_range` | 同一源快照写入区间，跳过源帧，保留各目标时长 |
| `copy_cel` | 显式单层复制，源须有 cel；默认可补齐目标帧，关闭扩帧时越界报错 |
| `propagate_cels` | 明确列出叶层，所有层名先验证；有源 cel 的层使用同一快照传播 |
| `duplicate_frame_range` | 先快照整个区间，按源顺序追加并继承各自时长，可重复追加 |

同帧复制验证输入后保持工程原值。覆盖型整帧复制中，源缺失 cel 会清除目标对应 cel；非覆盖型保持已有 cel。复制不改变已有 tag。

## tag 与 JE 播放

`set_tag` 按名称创建或更新区间和方向；`delete_tag` 删除已存在的标签。方向支持 `forward`、`reverse`、`pingpong`、`pingpong_reverse`。

Java 交付由 [07 · 导出](07-output.md) 将源帧区间映射为局部从 0 开始的播放索引，按源帧时长生成游戏 tick。条带只存一次每个源帧，方向由 mcmeta 的引用顺序表示。

## 可见性、补间与审阅

`set_layer_visibility` 隐藏图层或组；合成读取排除其内容。`set_layer_opacity` 作用于整层，`set_cel_opacity` 作用于单 cel。

位置补间、缓动与振荡工具按选定帧区间计算 cel 位置，不增加帧；需要建 cel 时使用工具提供的创建选项。它们用于位置动画，像素纹理的逐帧改图使用显式绘制和快照复制。

实际可审阅的白底幽灵帧 PNG 由核心工具 `render_onion_skin` 输出。动画回归覆盖独立场景、隐藏组、cel 元数据、目标时长、tag、GIF 和 JE 播放顺序。
