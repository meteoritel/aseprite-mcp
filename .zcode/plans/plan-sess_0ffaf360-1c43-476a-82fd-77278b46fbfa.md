# 为 aseprite_mcp 撰写开发者文档

## 一、调研结论（已核实）

| 事实 | 数据 |
|---|---|
| 注册的 MCP 工具总数 | **116**（`grep -c "@mcp.tool()"` 实测，21 个工具模块） |
| 工具模块 | 21 个，`aseprite_mcp/tools/*.py` |
| 核心模块 | 7 个，`aseprite_mcp/core/*.py` |
| 传输方式 | stdio only（`mcp.run(transport='stdio')`） |
| Aseprite 调用 | 每次操作起一个短命 `aseprite --batch … --script <tmp.lua>` 子进程，无长驻进程/无 socket |
| 现存文档 | 根 `README.md`(英,427行)、`SKILL.md`(中,运行时 instructions)、`DOCKER.md`、`DOCKER_SETUP_SUMMARY.md`；**无 `docs/`** |
| 测试 | 27 个文件，集成测试为主，需真实 Aseprite（经 `ASEPRITE_PATH`） |

**根 README.md 与实际代码已漂移**：声称「104 tools across 17 categories」，实际 116 个工具、且完全没记录 `native_fx.py` 的 7 个工具与 `get_composite_pixel`/`get_composite_rect`。按你的选择，根 README 保持不动，这一偏差会记入新文档并在最后向你汇报。

---

## 二、交付物：11 个文件

```
docs/
├── README.md                        ① 技术总览
├── 01-lua-bridge.md                 ② 横切：Lua 桥与 Aseprite 调用模型
├── 02-paths-errors-lifecycle.md     ③ 横切：路径/编码 · 错误契约 · 进程生命周期
├── 03-painting.md                   ④ 子系统：绘图与像素编辑
├── 04-layers-and-canvas.md          ⑤ 子系统：画布 · 图层 · 组 · 跨文件复制
├── 05-animation.md                  ⑥ 子系统：帧 · cel · tag · 补间
├── 06-effects-and-tilemap.md        ⑦ 子系统：特效与网格结构
├── 07-output.md                     ⑧ 子系统：导出与预览
├── 08-inspection-and-quality.md     ⑨ 子系统：读取 · 分析 · 质量校验
├── reference/tools.md               ⑩ 116 个工具全清单（脚本生成）
└── development.md                   ⑪ 环境 · 测试 · Docker/CI
scripts/gen_tool_reference.py        ⑫ 新增：工具清单生成器
```

根 `README.md` 仅**在末尾追加 2 行**指向 `docs/`（引用链接），其余一字不动。

### 模块 → 文档映射（保证每个源文件都有归属，不重不漏）

| 文档 | 覆盖源文件 |
|---|---|
| ① README | `aseprite_mcp/__init__.py`、`__main__.py`、`tools/__init__.py` + 架构分层 + 新增工具指南 |
| ② 01-lua-bridge | `core/commands.py`、`core/lua.py`、`core/native.py`、`tools/script.py` |
| ③ 02-paths-errors-lifecycle | `core/state.py`、`core/colors.py`、`core/lifecycle.py`、`tools/preview.py`(进程部分) |
| ④ 03-painting | `tools/drawing.py`、`selection.py`、`transform.py`、`text.py`、`core/fonts.py`、`tools/palette.py` |
| ⑤ 04-layers-and-canvas | `tools/canvas.py`、`layers.py`、`scene.py` |
| ⑥ 05-animation | `tools/animation.py`、`guide.py` |
| ⑦ 06-effects-and-tilemap | `tools/fx.py`、`native_fx.py`、`tilemap.py`、`slices.py` |
| ⑧ 07-output | `tools/export.py`、`preview.py` |
| ⑨ 08-inspection-and-quality | `tools/pixel_read.py`、`analysis.py`、`quality.py` |
| ⑪ development | `tests/*`、`pyproject.toml`、`Dockerfile`、`.github/workflows/` |

### 每篇统一骨架

```
# 标题
> 一句话职责 | 覆盖的源文件（可点击路径）
## 职责边界          —— 做什么 / 不做什么，边界交给哪篇文档
## 关键符号           —— 函数/常量/file:line
## 机制要点           —— 真实实现，配关键代码片段
## 工具清单           —— 表格 + 链接到 reference/tools.md
## 约定与陷阱         —— 易错点、历史坑
## 相关测试 / 相关文档 —— 双向链接
```

---

## 三、各篇内容要点

**① docs/README.md**
- 这个 server 是什么：把 Aseprite 当无头渲染/编辑引擎的 stdio MCP server
- 三层架构图：`tools/*.py`（MCP 工具层）→ `core/*`（机制层）→ `aseprite` 子进程
- **一次工具调用的完整数据流**：`prepare_filename` → 参数校验 → f-string 拼 Lua → 临时 `.lua` 文件 → `--batch --script` → stdout 标记解析 → 文本返回
- 装配与注册：`FastMCP("aseprite")`、`@mcp.tool()` 装饰器 + `tools/__init__.py` 显式 import 副作用（无自动发现）、instructions 来自 `SKILL.md`
- **新增一个工具的 checklists**（最有价值的贡献者内容）
- 文档地图 + 阅读顺序
- 已知偏差清单（见第五节）

**② 01-lua-bridge**（横切）
- 调用模型：无长驻进程，每调用一进程；`ASEPRITE_PATH` 定位二进制
- `AsepriteCommand` 三个方法：`run_command` / `execute_lua_script` / `execute_lua_script_checked`
- **stdout 文本协议**：`OK` / `ERROR:<msg>` / `RANGE:` / `PIXEL:` / `DIFF:` / `COLOR:` / `COUNT:` / `INFO:` / `MISSING:` / `OK|frames_added=N` 全表
- 为何靠 stdout 而非退出码（batch 模式 Lua 无法设退出码；错误写在 stdout、stderr 为空）
- `lua_escape` 双引号单引号都转义的原因；路径先 `\`→`/` 再转义
- `core/lua.py` 共享片段库：`FIND_LAYER`（BFS + `group/child` 最长前缀回溯）、`LAYER_NAMES`、`ENSURE_LAYER`（`/` 永不自动建）、`NORMALIZE_CEL`、`PSET`、`HSL`
- `core/native.py`：为何必须先 resolve+activate 再执行 `app.command.*`
- `tools/script.py` 逃生舱与安全提示
- 陷阱：无 `timeout=`；`os.path.exists` 守卫导致文件不存在时静默丢参

**③ 02-paths-errors-lifecycle**（横切）
- `prepare_filename` 唯一漏斗：active file 回退 → 原始串上先拒 `..` → workspace/cwd 解析 → 存在性检查 → anchor
- `ASERITE_MCP_WORKSPACE`（**保留这个拼写**，全仓库一致的笔误）+ `expanduser` + `abspath`
- 输出路径铁律：`must_exist=False, anchor=False`，否则导出会篡改会话活跃文件
- `create_canvas` 是唯一要求绝对路径的工具
- UTF-8 IO 全表：subprocess `encoding="utf-8", errors="replace"`（否则 Windows 走 GBK）、Lua 临时脚本 UTF-8、SKILL.md/font.json/PID 文件
- `core/colors.py`：`#RGB/#RGBA/#RRGGBB/#RRGGBBAA`，alpha 默认 255；标注 `tilemap.py` 仍留本地副本
- 错误契约：无 envelope、无异常包装；错误前缀集合 `Failed`/`ERROR`/`Invalid`/`Script failed`（`tests/conftest.py:37` 是权威定义）；退出码 0 但没写文件 → 必须做文件系统后验
- `parse_pixel_xy` 与 Lua 注入防护（`pixels` 不做 schema 校验）
- 进程生命周期：`core/lifecycle.py` 看门狗 —— stdin 优先（Windows `PeekNamedPipe` 不消费缓冲、POSIX 只监听 `POLLHUP`）、父进程仅兜底（macOS 无 `poll`）、连续 2 次才退出、`os._exit(0)` 的原因、`ASEPRITE_MCP_CLIENT_WATCHDOG=0` 关闭
- `tools/preview.py` 的进程侧：detached `http.server` + PID 文件 + `taskkill /T /F`

**④ 03-painting**
- 绘图两代工具（legacy 作用于 `activeCel` vs `_at` 系列按 layer/frame 定位）
- 两种落到像素的机制：`img:putPixel` 直写 vs `app.useTool{...}`；矩形闭区间转换 `x2 = x+w-1`
- 坐标约定：sprite-global / 原点左上 / y 向下；`cox/coy` 偏移相减 vs `NORMALIZE_CEL` 归一化两条路径
- `thickness` 的方形笔刷实现（无笔刷形状、无抗锯齿）
- 字体的完整机制：Aseprite 1.3 无文本 API → `core/fonts.py` 在 Python 侧栅格化 → 存临时 PNG → Lua `drawImage` blit；bitmap `font.json` schema、`ink_rule`/`advance`、`overrides`、TrueType 阈值化、`anchor` 只吸附字形盒
- `selection.py`：区域读入 Lua 2D buffer、透明像素不覆盖目标、`copy_region` 只建目标 cel 不建图层
- `transform.py`：90/270 新建 Image 且不调整 `cel.position` 的已知影响
- `palette.py`：预设、hue-shifted ramp、量化与 memo、`remap_colors_in_cel_range`

**⑤ 04-layers-and-canvas**
- 图层树模型、`group`/`group/subgroup` 路径解析、重名只在顶层判重
- `add_layer`/`add_group`/`duplicate_layer` 的 `parent` 挂载；`stackIndex` 1-based 且 1=最底
- 19 种 blend mode 映射表
- `scene.py`：Lua 内 `app.open` 双文件、`MISSING:` 回报、只保存目标文件
- 边界：可见性/不透明度在 05-animation（指向链接）

**⑥ 05-animation**
- 帧模型：1-based、区间表达、`duration_ms / 1000.0` 存秒
- cel 生命周期与 `image:clone()` + `cel.position` 保留 vs `create_cel` 画布对齐
- 跳过 group 图层的不变式
- tag 与 `AniDir` 四种方向；数值索引回读
- 补间族：`t` 归一化、`math.floor(t+0.5)`、五种 easing 公式、oscillate 正弦、scale 补间用 `img:resize` 且默认 `create_missing_cels=True`
- `guide.py` 的 `animation_workflow_guide`
- 明确写出缺口：**无播放/循环控制工具**；`set_onion_skin` 是文档化 no-op（真正的洋葱皮是 `analysis.render_onion_skin`）

**⑦ 06-effects-and-tilemap**
- `fx.py`（Python 生成 Lua 逐像素）vs `native_fx.py`（Aseprite 编译期滤镜）的分工与「deprecate, don't break」策略
- Bayer 4×4 有序抖动的阈值公式
- 冻结的卷积矩阵名单、`ColorQuantization` 留槽 0 给透明色（`max_colors` 是槽位预算不是承诺）
- tilemap：瓦片尺寸是**精灵级全局** `gridBounds`、tile 0 为空格、`draw_on_tile` 用 tile-local 坐标、`set_tiles` 用 0-based 网格坐标、偏移 cel 的瓦片迁移逻辑
- slices：`/` 与 `|` 出现在名字里时的 JSON 逐行输出协议（`test_slices_pipe.py` 保护的回归）

**⑧ 07-output**
- CLI 直调（非 Lua）的导出路径与参数拼装顺序（`--frame-range` 必须在输入文件之前才对 `--sheet` 生效）
- 0-based CLI 帧号 vs 1-based MCP 帧号
- 「Aseprite 退出 0 但没写文件」的文件系统后验 + 编号兄弟文件 `os.replace` 回名
- `export_tag` 先校验 tag 存在（`--tag` 缺失时静默导出全部帧）
- 输出恒为绝对路径文本，**无 image content block、无 base64、无 MCP resource**
- preview 的完整闭环：导出 PNG → `start_preview_server` → 客户端访问 `http://localhost:<port>/<file>`

**⑨ 08-inspection-and-quality**
- 单 cel 读取 vs 合成读取的行为差异（前者无视可见性）
- `_COMPOSE_FRAME`：为何不能用 `flatten()`（Aseprite 1.3 会合并隐藏图层）、`__visible_only__` 占位层、不递归进隐藏组的原因
- tilemap 图层逐像素读取被拒绝的语义原因与替代工具
- 越界像素返回透明黑而非报错
- `analysis.py` 三工具的输出解析（`DIFF:`/`COLOR:` 协议）
- `quality.py`：**它是结构校验器，不是评分器**——四个工具的输入解析（`"A,B"` / `"layer:1-8,17-24"`）、AABB 重叠判定、越界 cel、`report_only` 干跑、`ignore_full_canvas_overlaps`、截断上限 200

**⑪ development.md**
- 环境：Python 3.13、`uv`、`ASEPRITE_PATH`、`.env` 在 `core.commands` 导入时从仓库根加载
- **全部环境变量全表**（含 `STEAM_*`、`ASEPRITE_MCP_CLIENT_WATCHDOG`、`ASERITE_MCP_WORKSPACE`）与默认值
- 打包现状：`pyproject.toml` 无 build backend、不可安装、无 console script；`requirements.txt` 与 `pyproject.toml` 不一致（缺 `httpx`/`mcp`，多 `black`/`flake8`），`python-dotenv` 被直接 import 却未声明依赖
- 测试 harness：`conftest.py` 的 `BASE`（Windows `%TEMP%/ase-pytest`）、`run()`、`ok()` 前缀断言、`sprite` fixture；哪些测试不需要真 Aseprite（`test_lifecycle`/`test_path_resolution`/`test_pixel_xy_validation`/`test_encoding`）
- 测试命名两套风格：feature 镜像式 vs 回归/issue 式（并给出回归文件 ↔ 提交/issue 对照表）
- Docker：`ghcr.io/homebrew/brew` 基座、镜像内**不含** Aseprite（需 Steam 凭据）、entrypoint 的两个作用、`docker run -i` 才是可用形态
- CI：只构建推送镜像、PR 冒烟，**不跑 pytest**
- 文档保鲜：`uv run python scripts/gen_tool_reference.py` 重新生成清单

---

## 四、生成器 `scripts/gen_tool_reference.py`

纯标准库 `ast`，不依赖 Aseprite 或第三方包，因此离线可跑：

1. 扫 `aseprite_mcp/tools/*.py`，按 `tools/__init__.py` 的模块顺序
2. 找 `@mcp.tool()` 装饰的 `FunctionDef`/`AsyncFunctionDef`，提取：工具名、参数（名/注解/默认值，`*` 分隔）、docstring 摘要、`file:line`
3. 输出 `docs/reference/tools.md`：顶部总计表（模块 → 工具数 → 锚点）+ 每模块小节表格 `| 工具 | 参数 | 说明 |`
4. 自检并打印：总数、重复工具名（有则非零退出）、与 `grep` 实测的 116 对账
5. 文件头写入「本文件由脚本生成，请勿手改」+ 生成命令

生成的清单与手写文档之间用锚点链接（`#tool-add_frames`）。

---

## 五、需在文档中记录的已知偏差（不改代码，只记录）

1. 根 README 声称 104 工具/17 分类，实际 **116 工具/21 模块**；未记录 `native_fx` 7 个工具与 `get_composite_*`
2. `ASERITE_MCP_WORKSPACE` 拼写错误，但代码/文档/测试全仓库一致 → 文档保留原拼写并显式标注
3. `.dockerignore` 排除 `docs/` 与 `*.md`（仅放行 `README.md`）→ 镜像内无 `SKILL.md`，`instructions` 恒走 fallback
4. `DOCKER.md` / `DOCKER_SETUP_SUMMARY.md` 声称的 `mcpuser` 用户在 Dockerfile 中不存在（实际以 root 运行）；`scripts/aseprite-docker.sh` 指向本仓库不构建的 `aseprite-from-source` 镜像
5. `requirements.txt` 陈旧且与 `pyproject.toml` 冲突；`python-dotenv` 未声明依赖
6. `pyproject.toml` 无 build backend，只能 `uv run -m aseprite_mcp`，无 console script；`__version__` 有 `pyproject.toml` 与 `__init__.py` 两处来源
7. `subprocess.run` 未设 `timeout` → 挂起的 Aseprite 会永久阻塞工具调用
8. `export_sprite` 的 gif 分支与 else 分支代码完全相同
9. `quality.py` 名不副实：无任何数值评分/阈值，只是结构校验器
10. `tilemap.py` 仍有本地 `_parse_hex_color`（只支持 6 位、无 alpha），未统一到 `core/colors.py`
11. 无播放/循环控制工具；`set_onion_skin` 为 no-op
12. CI 不执行 pytest；`.pytest_cache/v/cache/lastfailed` 记录 `test_lifecycle.py::test_watchdog_is_what_ends_the_orphan_case` 上次失败（环境敏感）

---

## 六、执行顺序

1. 写 `scripts/gen_tool_reference.py` → 跑出 `docs/reference/tools.md`，用实测 116 对账
2. 自己重读横切层源码（`core/state.py`、`commands.py`、`lua.py`、`native.py`、`lifecycle.py`、`colors.py`、`__init__.py`、`__main__.py`、`tools/__init__.py`）——机制类结论不依赖二手摘要
3. 写 ② 与 ③（横切）→ 写 ① README（需要横切结论做架构图与数据流）
4. 逐个写 ④⑤⑥⑦⑧⑨，每个模块动笔前重读对应源文件确认真实签名与行为
5. 写 ⑪ development.md（含环境变量全表、测试对照表）
6. 根 `README.md` 末尾追加指向 `docs/` 的链接行
7. 收尾校验：所有相对链接可达（脚本核对）、工具计数一致、术语统一（`cel`/`tag`/`slice`/`tilemap`/`gridBounds` 等保留英文）

## 七、验证方式

- 生成器输出与 `grep -c "@mcp.tool()"` 的 116 逐模块对账
- 遍历所有 `docs/**/*.md` 的内联相对链接，逐个 `test -f` 校验
- 文中每个 `file:line` 引用抽查回源确认
- 关键机制结论至少两个独立来源交叉验证（源码 + 对应测试文件）

## 八、明确不做

- 不改任何 `aseprite_mcp/**` 源码
- 不修根 `README.md` 的 104/116 数字与缺失工具（仅追加末尾链接；偏差记入 `docs/`，需要修可另行开工）
- 不重构 `requirements.txt`、不加 build backend、不修 Docker 文档里的 `mcpuser`
- 不引入 Sphinx/MkDocs/CI 文档检查（纯 Markdown + 相对链接）
- 不新增除 `gen_tool_reference.py` 外的脚本，不改测试
