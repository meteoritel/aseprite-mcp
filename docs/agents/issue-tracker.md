# Issue tracker：本地 Markdown

本仓库的 issue 和 spec 保存在 `.scratch/`。

## 文件约定

- 每个功能使用独立目录：`.scratch/<feature-slug>/`。
- Spec 保存为 `.scratch/<feature-slug>/spec.md`。
- 实现 issue 保存为 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`，编号从 `01` 开始，每张票独立一个文件。
- 普通实现 issue 的 triage 状态写在文件顶部附近的 `Status:` 行；状态值见 [triage-labels.md](triage-labels.md)。
- 评论和讨论追加到文件末尾的 `## Comments` 下。
- `.scratch/` 被根目录 `.gitignore` 忽略，issue 和 spec 保存在本地工作区。

## 发布与读取

技能要求“发布到 issue tracker”时，在上述位置创建对应的 spec 或 issue 文件，并返回路径。

技能要求“读取相关 ticket”时，读取指定路径。仅提供编号时，在对应功能目录中查找；存在多个匹配时，确认具体路径。

## Wayfinder 操作

使用 `/wayfinder` 时，按以下约定维护探索地图与子票：

- 地图保存为 `.scratch/<effort>/map.md`，包含 Notes、Decisions-so-far 和 Fog。
- 子票保存为 `.scratch/<effort>/issues/<NN>-<slug>.md`，编号从 `01` 开始，正文记录待解决问题。
- `Type:` 记录类型：`research`、`prototype`、`grilling` 或 `task`。
- Wayfinder 子票的 `Status:` 使用 `open`、`claimed`、`resolved`，表示探索进度；普通实现 issue 使用前述 triage 状态。
- 依赖写在顶部附近的 `Blocked by: NN, NN` 行；列出的子票全部为 `resolved` 后解除阻塞。
- 选择状态为 `open` 且已解除阻塞的子票，按编号从小到大处理。
- 开始处理前，先将状态保存为 `claimed`。
- 解决后，在 `## Answer` 下追加答案，将状态改为 `resolved`，并在地图的 Decisions-so-far 中追加结论摘要与子票链接。
