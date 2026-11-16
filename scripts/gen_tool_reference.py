#!/usr/bin/env python3
"""Generate docs/reference/tools.md from the source tree.

Static-only: parses `aseprite_mcp/tools/*.py` with `ast`, so it needs neither a
running Aseprite nor the project dependencies. Re-run it after adding, removing
or re-signing a tool so the reference cannot drift from the code:

    uv run python scripts/gen_tool_reference.py
    uv run python scripts/gen_tool_reference.py --check   # exit 1 if stale
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "aseprite_mcp" / "tools"
OUTPUT = REPO_ROOT / "docs" / "reference" / "tools.md"

# One-line index labels. Used when the module has no docstring of its own, so
# the module index stays readable without duplicating the developer docs.
MODULE_SUMMARY = {
    "canvas.py": "画布创建、图层/帧的增删与活跃状态设置",
    "drawing.py": "像素、线、矩形、圆、椭圆、多边形、路径、填充、渐变",
    "text.py": "用 bitmap 或 TrueType 字体绘制与测量文本",
    "layers.py": "图层删除、重命名、复制、排序、混合模式、合并、展平",
    "selection.py": "矩形区域的移动/复制/擦除，以及按颜色擦除",
    "transform.py": "翻转、旋转、缩放、裁剪",
    "palette.py": "调色板读写、复古预设、色阶生成、量化、色彩模式",
    "animation.py": "帧、cel、tag、带缓动的补间与传播",
    "fx.py": "手写逐像素特效：描边、换色、HSL 调整、有序抖动",
    "native_fx.py": "Aseprite 原生滤镜包装（app.command.*）",
    "tilemap.py": "tilemap 图层、tileset 编辑、瓦片摆放与读取",
    "slices.py": "命名区域、九宫格中心、轴心点",
    "export.py": "PNG/GIF/精灵表/分层/按 tag 导出与图片导入",
    "preview.py": "本地 HTTP 预览服务器",
    "pixel_read.py": "单 cel 与合成后的像素读取",
    "sprite_map.py": "字符网格（sprite map）的紧凑批量绘制与回读",
    "analysis.py": "洋葱皮渲染、帧差异、颜色统计",
    "quality.py": "动画一致性校验与归一化（结构校验器，非评分器）",
    "scene.py": "在两个精灵文件之间复制图层",
    "guide.py": "返回面向 LLM 的动画工作流指南文本",
    "script.py": "任意 Aseprite Lua 的逃生舱",
}

# Which developer doc owns each tool module. Keep in sync with docs/.
DOC_MAP = {
    "canvas.py": "../04-layers-and-canvas.md",
    "layers.py": "../04-layers-and-canvas.md",
    "scene.py": "../04-layers-and-canvas.md",
    "drawing.py": "../03-painting.md",
    "sprite_map.py": "../03-painting.md",
    "selection.py": "../03-painting.md",
    "transform.py": "../03-painting.md",
    "text.py": "../03-painting.md",
    "palette.py": "../03-painting.md",
    "animation.py": "../05-animation.md",
    "guide.py": "../05-animation.md",
    "fx.py": "../06-effects-and-tilemap.md",
    "native_fx.py": "../06-effects-and-tilemap.md",
    "tilemap.py": "../06-effects-and-tilemap.md",
    "slices.py": "../06-effects-and-tilemap.md",
    "export.py": "../07-output.md",
    "preview.py": "../07-output.md",
    "pixel_read.py": "../08-inspection-and-quality.md",
    "analysis.py": "../08-inspection-and-quality.md",
    "quality.py": "../08-inspection-and-quality.md",
    "script.py": "../01-lua-bridge.md",
}


def module_order() -> list[str]:
    """Read tools/__init__.py so the doc follows the registration order."""
    init_path = TOOLS_DIR / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is None:
            for alias in node.names:
                order.append(f"{alias.name}.py")
    if not order:
        raise SystemExit(f"could not read tool import order from {init_path}")
    return order


def is_mcp_tool(node: ast.stmt) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "tool":
            return True
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            if dec.func.attr == "tool":
                return True
    return False


def unparse(node: ast.expr | None) -> str:
    return ast.unparse(node) if node is not None else ""


def cell(text: str) -> str:
    """Make a string safe inside a Markdown table cell.

    Type annotations are written PEP 604 style (`int | None`), and an unescaped
    pipe would be read as a column separator and break the row.
    """
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
    """Flatten positional/keyword-only params into a common shape."""
    a = fn.args
    params: list[dict] = []
    positional = list(a.posonlyargs) + list(a.args)
    # defaults align to the tail of positional args
    pad = len(positional) - len(a.defaults)
    for i, arg in enumerate(positional):
        default = a.defaults[i - pad] if i >= pad else None
        params.append(
            {
                "name": arg.arg,
                "type": unparse(arg.annotation),
                "default": unparse(default),
                "required": default is None,
            }
        )
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        params.append(
            {
                "name": arg.arg,
                "type": unparse(arg.annotation),
                "default": unparse(default),
                "required": default is None,
            }
        )
    return params


def render_signature(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> str:
    """Rebuild the call shape: `name(a, b=1, *, c)` with annotations."""
    a = fn.args
    positional = list(a.posonlyargs) + list(a.args)
    pad = len(positional) - len(a.defaults)
    parts = []
    for i, arg in enumerate(positional):
        text = arg.arg
        if arg.annotation:
            text += f": {unparse(arg.annotation)}"
        if i >= pad:
            text += f" = {unparse(a.defaults[i - pad])}"
        parts.append(text)
    if a.kwonlyargs:
        parts.append("*")
        for arg, default in zip(a.kwonlyargs, a.kw_defaults):
            text = arg.arg
            if arg.annotation:
                text += f": {unparse(arg.annotation)}"
            if default is not None:
                text += f" = {unparse(default)}"
            parts.append(text)
    ret = f" -> {unparse(fn.returns)}" if fn.returns else ""
    return f"{name}({', '.join(parts)}){ret}"


def split_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Return (summary, {param: description}) from a Google-style docstring."""
    if not doc:
        return "", {}
    doc = doc.strip()
    marker = "\nArgs:"
    body, _, args_blob = doc.partition(marker)
    summary = " ".join(body.split())
    if not args_blob:
        return summary, {}

    described: dict[str, str] = {}
    current: str | None = None
    for raw in args_blob.splitlines():
        if not raw.strip():
            continue
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        head, sep, rest = stripped.partition(":")
        head = head.split("(")[0].strip()
        if indent <= 8 and sep and head.isidentifier():
            current = head
            described[current] = " ".join(rest.split())
        elif current:
            described[current] = " ".join(f"{described[current]} {stripped}".split())
    return summary, described


def collect() -> tuple[list[dict], list[str]]:
    tools: list[dict] = []
    warnings: list[str] = []
    for filename in module_order():
        path = TOOLS_DIR / filename
        if not path.exists():
            warnings.append(f"{filename}: listed in __init__.py but missing on disk")
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_doc = (ast.get_docstring(tree) or "").strip()
        # Curated Chinese label wins; the module docstring is a fallback for a
        # module added without a MODULE_SUMMARY entry.
        module_summary = MODULE_SUMMARY.get(filename)
        if not module_summary and module_doc:
            module_summary = " ".join(module_doc.splitlines()[0].split())
        for node in tree.body:
            if not is_mcp_tool(node):
                continue
            summary, described = split_docstring(ast.get_docstring(node))
            tools.append(
                {
                    "name": node.name,
                    "module": filename,
                    "module_summary": module_summary,
                    "signature": render_signature(node, node.name),
                    "summary": summary,
                    "described": described,
                    "params": render_params(node),
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
    return tools, warnings


def git_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(tools: list[dict], warnings: list[str]) -> str:
    modules: list[str] = []
    for tool in tools:
        if tool["module"] not in modules:
            modules.append(tool["module"])

    lines: list[str] = []
    lines.append("# 工具清单（自动生成）")
    lines.append("")
    lines.append(
        "> ⚠️ 本文件由 `scripts/gen_tool_reference.py` 解析源码 AST 生成，**请勿手改**。"
    )
    lines.append("> 新增或修改工具后重新生成：`uv run python scripts/gen_tool_reference.py`")
    lines.append(f"> 生成基线：`{git_revision()}`")
    lines.append("")
    lines.append(
        "参数列中 `*` 之后的是 keyword-only 参数；`filename` 通常可省略（回退到会话的活跃文件）。"
    )
    lines.append("")
    lines.append("## 模块索引")
    lines.append("")
    lines.append("| 模块 | 说明 | 开发者文档 |")
    lines.append("|---|---|---|")
    for module in modules:
        own = [t for t in tools if t["module"] == module]
        summary = own[0]["module_summary"] if own else ""
        doc = DOC_MAP.get(module, "")
        doc_link = f"[{Path(doc).name}]({doc})" if doc else "—"
        anchor = module.removesuffix(".py")
        lines.append(
            f"| [`{module}`](#{anchor}py) | {cell(summary)} | {doc_link} |"
        )
    lines.append("")

    for module in modules:
        own = [t for t in tools if t["module"] == module]
        summary = own[0]["module_summary"] if own else ""
        lines.append(f"## `{module}`")
        lines.append("")
        if summary:
            lines.append(summary)
            lines.append("")
        for tool in own:
            lines.append(f"### `{tool['name']}`")
            lines.append("")
            lines.append(f"```text")
            lines.append(tool["signature"])
            lines.append(f"```")
            lines.append("")
            lines.append(
                f"源码：[`aseprite_mcp/tools/{tool['module']}:{tool['line']}`]"
                f"(../../aseprite_mcp/tools/{tool['module']}#L{tool['line']})"
            )
            lines.append("")
            if tool["summary"]:
                lines.append(tool["summary"])
                lines.append("")
            if tool["params"]:
                lines.append("| 参数 | 类型 | 默认值 | 说明 |")
                lines.append("|---|---|---|---|")
                for param in tool["params"]:
                    ptype = f"`{cell(param['type'])}`" if param["type"] else "—"
                    if param["required"]:
                        default = "**必填**"
                    elif param["default"]:
                        default = f"`{cell(param['default'])}`"
                    else:
                        default = "—"
                    desc = cell(tool["described"].get(param["name"], ""))
                    lines.append(
                        f"| `{param['name']}` | {ptype} | {default} | {desc} |"
                    )
                lines.append("")

    if warnings:
        lines.append("## 生成器警告")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the committed file is out of date",
    )
    args = parser.parse_args()

    tools, warnings = collect()
    names = [t["name"] for t in tools]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    new_content = render(tools, warnings)

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != new_content:
            print(f"STALE: {OUTPUT.relative_to(REPO_ROOT)} needs regeneration")
            return 1
        print(f"OK: {OUTPUT.relative_to(REPO_ROOT)} is up to date ({len(tools)} tools)")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(new_content, encoding="utf-8")

    modules: list[str] = []
    for tool in tools:
        if tool["module"] not in modules:
            modules.append(tool["module"])
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    for module in modules:
        count = sum(1 for t in tools if t["module"] == module)
        print(f"  {module:<16} {count:>3} tools")
    print(f"  {'TOTAL':<16} {len(tools):>3} tools across {len(modules)} modules")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if duplicates:
        print(f"ERROR: duplicate tool names: {', '.join(duplicates)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
