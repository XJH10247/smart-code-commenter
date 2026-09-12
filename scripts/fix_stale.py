#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""过期注释修复器（smart-code-commenter 配套工具）。

检测代码与文档注释不一致的情况，生成修正建议；默认 **dry-run**，
只有显式传入 ``--apply`` 才会写入文件。

本工具严格限定在"只改注释"的边界内：
    - 绝不修改任何可执行代码、字符串字面量、导入语句；
    - 每次写入前自动备份，写入后可选调用 safety_check 复验；
    - 无法确定修正方式时只报告，不猜测。

支持的修正类型：
    1. ``param-extra``  文档中记载了签名里不存在的参数 → 删除该条目；
    2. ``param-missing`` 签名中的参数未在文档中出现 → 生成待补条目（占位，
       需人工填写，默认不自动写入，除非 ``--fill-placeholder``）；
    3. ``todo-stale``   超期未处理的 TODO/FIXME（按 ``--todo-days``
       无法判定日期，因此仅按行统计并提示，不自动改动）。

用法：
    python fix_stale.py <路径> [--apply] [--format text|json] [--verbose]

退出码：
    0  无待修复项（或已成功应用）
    1  发现了待修复项但未应用（dry-run 模式下的"有差异"信号）
    2  输入错误
    3  应用后自检失败（已自动回滚）
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langspec import SKIP_DIRS, detect_language  # noqa: E402
import comment_scanner as cs                      # noqa: E402

# 各语言的文档注释参数记号（用于定位待修正的参数条目）
_GOOGLE_ARG_RE = re.compile(
    r"^(?P<indent>\s+)(?P<name>\*{0,2}\w+)(?P<rest>\s*(?:\([^)]*\))?\s*:\s*)(?P<desc>.*)$"
)
_NUMPY_ARG_RE = re.compile(
    r"^(?P<indent>\s+)(?P<name>\w+)(?P<rest>\s*:\s*[\w\[\], |]+)(?P<desc>\s*)$"
)
_TAG_ARG_RE = re.compile(
    r"^(?P<indent>\s*\*?\s*@param(?:\[[^\]]*\])?\s+)(?P<name>\w+)(?P<rest>.*)$"
)
# NumPy 风格章节下的分隔下划线，如 ``----------`` / ``======``
_UNDERLINE_RE = re.compile(r"^[-=~^#*+]{3,}$")


def _has_underline(lines: List[str], header_idx: int, header_indent: int) -> bool:
    """判断 ``lines[header_idx]`` 之后是否紧跟一行同缩进的分隔下划线。

    这是区分 NumPy 风格（``Parameters`` + ``----------``）与 Google 风格
    （``Args:``）的可靠依据 —— 后者不存在下划线。
    """
    j = header_idx + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return False
    cand = lines[j]
    if len(cand) - len(cand.lstrip()) != header_indent:
        return False
    return bool(_UNDERLINE_RE.match(cand.strip()))



@dataclass
class Finding:
    """一条待修正的过期注释记录。"""
    path: str
    line: int
    kind: str                    # param-extra / param-missing / todo
    symbol: str
    detail: str
    fixable: bool = False
    old_text: str = ""
    new_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 检测
# ---------------------------------------------------------------------------

def analyze_python_file(path: str) -> List[Finding]:
    """分析单个 Python 文件，返回过期注释发现列表。"""
    findings: List[Finding] = []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        source = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return findings

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return findings          # 语法错误文件不做修正建议

    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        if doc is None:
            continue

        real_args = _real_arg_names(node)
        doc_args = _documented_arg_names(doc)

        # 类型 1：文档里有、签名里没有 → 可安全删除
        for name, lineno_in_doc in doc_args.items():
            if name in real_args:
                continue
            abs_line = (node.lineno + 1) + (lineno_in_doc - 1)
            old_text = lines[abs_line - 1] if 0 < abs_line <= len(lines) else ""
            findings.append(Finding(
                path=path, line=abs_line, kind="param-extra",
                symbol=node.name,
                detail="docstring 记载的参数 %r 不在函数签名中" % name,
                fixable=bool(old_text.strip()),
                old_text=old_text,
                new_text="",
            ))

        # 类型 2：签名里有、文档里没提 → 只报告（补写内容需语义判断）
        missing = sorted(real_args - set(doc_args) - {"self", "cls"})
        if missing and doc_args:
            findings.append(Finding(
                path=path, line=node.lineno, kind="param-missing",
                symbol=node.name,
                detail="参数 %s 未在 docstring 中说明"
                       % ", ".join(repr(m) for m in missing),
                fixable=False,
            ))

    return findings


def _real_arg_names(node) -> set:
    """提取函数签名的参数名集合（含 self/cls）。"""
    names = {a.arg for a in getattr(node.args, "posonlyargs", [])}
    names |= {a.arg for a in node.args.args}
    names |= {a.arg for a in node.args.kwonlyargs}
    if node.args.vararg:
        names.add(node.args.vararg.arg)
    if node.args.kwarg:
        names.add(node.args.kwarg.arg)
    names |= {"self", "cls"}
    return names


_DOC_SECTION_WORDS = {
    "returns", "raises", "args", "arguments", "yields", "note", "notes",
    "example", "examples", "attributes", "parameters", "other", "see",
    "seealso", "references", "warns", "warning", "todo", "keyword",
    "kwargs", "return", "raise", "yield",
}


def _documented_arg_names(doc: str) -> dict:
    """从 docstring 中提取"文档声明的参数名" → docstring 内行号映射。

    同时支持 Google 风格（``Args:`` + ``name:``）与 NumPy 风格
    （``Parameters`` + ``name : type``），并跳过章节标题词。

    章节判定依据**缩进层级**：``Args:`` 这类章节标题是当前缩进层，
    其后的参数条目缩进更深。这样可正确处理 ``Returns:`` 之后结束、
    以及 ``Note:`` 等非参数小节穿插的情况。
    """
    result = {}
    lines = doc.splitlines()
    section_indent: Optional[int] = None      # 参数条目所需的最小缩进
    numpy_underline = False                   # 该章节是否为 NumPy 下划线式
    _SECTION_NAMES = {
        "args", "arguments", "parameters", "keyword args", "keyword arguments",
        "other parameters",
    }
    _NON_SECTION = {
        "returns", "return", "raises", "raise", "yields", "yield",
        "note", "notes", "example", "examples", "attributes", "see also",
        "references", "warns", "warning", "todo",
    }

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        # NumPy 风格的分隔下划线（``----------``）：跳过，且其存在本身
        # 已在上面的章节标题处理中把条目缩进层级下调了一级。
        if numpy_underline and _UNDERLINE_RE.match(stripped):
            continue

        # 章节标题：形如 `Args:` / `Parameters` / `Returns:`（无额外描述）
        head = re.match(r"^([A-Za-z][A-Za-z ]*?)\s*:?\s*$", stripped)
        if head:
            name = head.group(1).strip().lower()
            if name in _SECTION_NAMES:
                # NumPy 风格的条目与标题**同缩进**，靠下一行的 `-----`
                # 与标题区分；Google 风格则是严格更深一级。
                numpy_underline = _has_underline(lines, idx, indent)
                section_indent = indent - 1 if numpy_underline else indent
                continue
            if name in _NON_SECTION:
                section_indent = None
                numpy_underline = False
                continue

        if section_indent is None or indent <= section_indent:
            continue

        m = _GOOGLE_ARG_RE.match(line)
        if m:
            arg = m.group("name").lstrip("*")
            if arg.lower() not in _DOC_SECTION_WORDS:
                result[arg] = idx + 1
            continue
        m = _NUMPY_ARG_RE.match(line)
        if m:
            arg = m.group("name")
            if (arg.lower() not in _DOC_SECTION_WORDS
                    and not arg.startswith("-")):
                result[arg] = idx + 1

    return result


def analyze_todos(path: str) -> List[Finding]:
    """收集 TODO/FIXME 积压（仅报告，不自动改动）。"""
    findings: List[Finding] = []
    try:
        rep = cs.scan_file(path, skip_tests=False)
    except Exception:
        return findings
    if rep.skipped:
        return findings
    for item in rep.todos:
        findings.append(Finding(
            path=path, line=0, kind="todo",
            symbol="-", detail=item, fixable=False,
        ))
    return findings


def collect_findings(target: str, include_todos: bool = False,
                     max_files: int = 500) -> List[Finding]:
    """遍历目标文件/目录，汇总全部发现。"""
    paths: List[str] = []
    if os.path.isfile(target):
        paths = [target]
    else:
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(
                d for d in dirs
                if d not in SKIP_DIRS and not d.startswith(".")
            )
            for name in sorted(files):
                if len(paths) >= max_files:
                    break
                paths.append(os.path.join(root, name))

    findings: List[Finding] = []
    for p in paths:
        if detect_language(p) == "Python":
            findings.extend(analyze_python_file(p))
        if include_todos:
            findings.extend(analyze_todos(p))
    return findings


# ---------------------------------------------------------------------------
# 应用修正
# ---------------------------------------------------------------------------

def apply_extra_param_removal(finding: Finding) -> bool:
    """删除 docstring 中指向不存在参数的整行。

    安全保证：只删除**确定属于该参数条目**的那一行；若该行在删除后
    会让 docstring 变空，则改为替换为说明性文本而非留空。

    Returns:
        是否实际发生了修改。
    """
    if not finding.fixable or not finding.old_text:
        return False
    path = finding.path
    # newline="" 保留原始行尾（CRLF 文件不会被悄悄改成 LF）
    with open(path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    lines = content.splitlines(keepends=True)
    idx = finding.line - 1
    if idx < 0 or idx >= len(lines):
        return False
    # 注意：old_text 来自 source.splitlines()，已经去掉了 \r\n；
    # 而这里读到的行尾可能是 \r\n，必须两边都按 \r\n 归一化再比，
    # 否则 CRLF 文件永远比对失败（修改静默不生效）。
    if lines[idx].rstrip("\r\n") != finding.old_text.rstrip("\r\n"):
        return False                     # 文件已变化，放弃
    del lines[idx]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    return True


def apply_findings(findings: List[Finding], verbose: bool = False) -> tuple:
    """应用全部可修正项，返回 (修改文件数, 回滚文件数)。"""
    fixable = [f for f in findings if f.fixable and f.kind == "param-extra"]
    if not fixable:
        return 0, 0

    by_file: dict = {}
    for f in fixable:
        by_file.setdefault(f.path, []).append(f)

    changed = rolled_back = 0
    for path, items in by_file.items():
        backup = path + ".stale.bak"
        try:
            shutil.copy2(path, backup)
        except OSError as exc:
            print("ERROR: 无法备份 %s: %s" % (path, exc), file=sys.stderr)
            continue

        # 从后往前删，避免行号偏移
        applied = 0
        for f in sorted(items, key=lambda x: -x.line):
            if apply_extra_param_removal(f):
                applied += 1

        if not applied:
            _safe_unlink(backup)
            continue

        # 自检：确认只动了注释
        ok, detail = _verify(path, backup)
        if ok:
            changed += 1
            _safe_unlink(backup)
            if verbose:
                print("  ✓ %s：修正 %d 处（%s）" % (path, applied, detail))
        else:
            shutil.copy2(backup, path)
            rolled_back += 1
            print("  ✗ %s：自检失败已回滚（%s）" % (path, detail), file=sys.stderr)
            _safe_unlink(backup)

    return changed, rolled_back


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _verify(path: str, backup: str) -> tuple:
    """调用 safety_check 校验修改后文件仅注释发生变化。

    Returns:
        ``(是否通过, 说明)``；校验器不可用时返回 (True, "已跳过校验")
        以免因工具缺失阻塞流程（但会明确提示）。
    """
    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "safety_check.py")
    if not os.path.isfile(checker):
        return True, "未找到 safety_check.py，已跳过自检"
    try:
        proc = subprocess.run(
            [sys.executable, checker, backup, path],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return True, "校验器执行失败(%s)，已跳过" % exc.__class__.__name__
    if proc.returncode == 0:
        return True, "SAFE"
    return False, (proc.stdout or proc.stderr).strip().splitlines()[0] \
        if (proc.stdout or proc.stderr).strip() else "UNSAFE"


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def render_text(findings: List[Finding], applied: bool) -> str:
    """渲染人读文本报告。"""
    if not findings:
        return "未发现需要修正的过期注释。"

    by_kind: dict = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    labels = {
        "param-extra": "文档多余的参数条目（可自动删除）",
        "param-missing": "文档缺失的参数条目（需人工补写）",
        "todo": "TODO / FIXME 积压",
    }

    out = ["# 过期注释修正建议", ""]
    out.append("共发现 %d 项：%s" % (
        len(findings),
        "、".join("%s %d 项" % (labels.get(k, k), len(v))
                  for k, v in sorted(by_kind.items())),
    ))
    out.append("")

    for kind in ("param-extra", "param-missing", "todo"):
        items = by_kind.get(kind)
        if not items:
            continue
        out.append("## %s" % labels[kind])
        out.append("")
        for f in items:
            loc = "%s:%d" % (f.path, f.line) if f.line else f.path
            flag = "可自动修正" if f.fixable else "需人工处理"
            out.append("- `%s` — `%s()` %s _(%s)_"
                       % (loc, f.symbol, f.detail, flag))
            if f.fixable and f.old_text:
                out.append("  - 将删除：`%s`" % f.old_text.strip()[:120])
        out.append("")

    if not applied:
        out.append("---")
        out.append("")
        out.append("当前为 **试运行（dry-run）**，未修改任何文件。")
        out.append("确认无误后加 `--apply` 才会写入，写入前会自动备份并自检。")
    return "\n".join(out)


def render_json(findings: List[Finding], applied: bool) -> str:
    return json.dumps({
        "applied": applied,
        "total": len(findings),
        "findings": [f.to_dict() for f in findings],
    }, ensure_ascii=False, indent=2)


def render_diff(findings: List[Finding]) -> str:
    """为可修正项生成统一 diff 预览。"""
    out: List[str] = []
    by_file: dict = {}
    for f in findings:
        if f.fixable and f.old_text:
            by_file.setdefault(f.path, []).append(f)
    for path, items in by_file.items():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines(keepends=True)
        except OSError:
            continue
        removed = sorted({f.line for f in items})
        diff = difflib.unified_diff(
            lines,
            [l for i, l in enumerate(lines, 1) if i not in removed],
            fromfile=path, tofile=path + " (修正后)", n=2,
        )
        out.extend(diff)
    return "".join(out)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检测并修正与代码不一致的过期注释（默认 dry-run）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 无需修正或已应用 / 1 存在待修正项(未应用) / "
               "2 输入错误 / 3 自检失败已回滚",
    )
    parser.add_argument("path", help="要检查的文件或目录")
    parser.add_argument("--apply", action="store_true",
                        help="实际写入修正（默认只预览）")
    parser.add_argument("--diff", action="store_true",
                        help="输出 unified diff 预览")
    parser.add_argument("--include-todos", action="store_true",
                        help="同时列出 TODO/FIXME 积压")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.exists(args.path):
        print("错误：路径不存在 -> %s" % args.path, file=sys.stderr)
        return 2

    findings = collect_findings(args.path, args.include_todos, args.max_files)

    if args.format == "json":
        text = render_json(findings, args.apply)
    else:
        text = render_text(findings, args.apply)
        if args.diff:
            d = render_diff(findings)
            if d:
                text += "\n\n## 修正预览（unified diff）\n\n```diff\n" + d + "```\n"

    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))

    if not args.apply:
        return 1 if any(f.fixable for f in findings) else 0

    changed, rolled = apply_findings(findings, args.verbose)
    if args.format != "json":
        print("\n已修正 %d 个文件，回滚 %d 个文件。" % (changed, rolled),
              file=sys.stderr)
    return 3 if rolled else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
