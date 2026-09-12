#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语言规格表（smart-code-commenter 共享模块）。

为扫描器与校验器提供**单一可信来源**的语言→语法映射，避免此前
两个脚本各自维护一份不一致的语言表（实测发现注释语法、扩展名、
文档注释前缀三处口径不一，导致校验命令在备份文件上失效）。

核心能力：
- `detect_language(path)`：先从扩展名判断；失败时回退到**文件名
  关键词 + 内容特征**探测，从而正确处理 `app.js.bak`、
  `foo.commenter.bak` 这类备份/临时文件名。
- `LANG_SPECS`：每种语言的元信息（注释符、文档注释前缀、
  是否支持块注释等）。

设计约束：
- 仅使用 Python 标准库，零第三方依赖；
- 只读，纯函数式（无全局可变状态）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# 语言规格
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LangSpec:
    """一种语言的注释语法规格。

    Attributes:
        name: 语言的规范名称，用于报告中展示与查表。
        line: 行注释符，如 ``//``、``#``、``--``。
        block_open: 块注释起始符，无块注释时为 None。
        block_close: 块注释结束符，无块注释时为 None。
        doc_prefixes: 判定"文档注释"时认可的起始记号。
        hash_doc: 该语言用 ``///`` 形式的文档注释（C#/Rust 等）。
        nesting: 块注释支持嵌套（Rust/Swift/Kotlin 支持）。
    """

    name: str
    line: str
    block_open: Optional[str] = None
    block_close: Optional[str] = None
    doc_prefixes: Tuple[str, ...] = ()
    hash_doc: bool = False
    nesting: bool = False


_BLOCK_C = ("/*", "*/")

# 单一可信来源：所有语言在此登记一次
LANG_SPECS = {
    "Python": LangSpec(
        "Python", "#", doc_prefixes=('"""', "'''", "#:"),
    ),
    "JavaScript": LangSpec(
        "JavaScript", "//", *_BLOCK_C,
        doc_prefixes=("/**",),
    ),
    "TypeScript": LangSpec(
        "TypeScript", "//", *_BLOCK_C,
        doc_prefixes=("/**",),
    ),
    "Java": LangSpec(
        "Java", "//", *_BLOCK_C,
        doc_prefixes=("/**",),
    ),
    "Go": LangSpec(
        "Go", "//", *_BLOCK_C,
        doc_prefixes=("//",),      # godoc 用普通行注释
    ),
    "C": LangSpec(
        "C", "//", *_BLOCK_C,
        doc_prefixes=("/**", "/*!", "///"),
    ),
    "C++": LangSpec(
        "C++", "//", *_BLOCK_C,
        doc_prefixes=("/**", "/*!", "///"),
    ),
    "Rust": LangSpec(
        "Rust", "//", *_BLOCK_C,
        doc_prefixes=("///", "//!"), nesting=True,
    ),
    "C#": LangSpec(
        "C#", "//", *_BLOCK_C,
        doc_prefixes=("///",),
    ),
    "Kotlin": LangSpec(
        "Kotlin", "//", *_BLOCK_C,
        doc_prefixes=("/**",), nesting=True,
    ),
    "PHP": LangSpec(
        "PHP", "//", *_BLOCK_C,
        doc_prefixes=("/**",),
    ),
    "Ruby": LangSpec(
        "Ruby", "#", ("=begin", "=end"),
        doc_prefixes=("#",),
    ),
    "Shell": LangSpec(
        "Shell", "#", doc_prefixes=("#",),
    ),
    "PowerShell": LangSpec(
        "PowerShell", "#", ("<#", "#>"),
        doc_prefixes=("#", "<#"),
    ),
    "SQL": LangSpec(
        "SQL", "--", *_BLOCK_C,
        doc_prefixes=("--",),
    ),
    "Lua": LangSpec(
        "Lua", "--", ("--[[", "]]"),
        doc_prefixes=("---", "--[[", "--"),
    ),
    "R": LangSpec(
        "R", "#", doc_prefixes=("#", "#'"),
    ),
    "Swift": LangSpec(
        "Swift", "//", *_BLOCK_C,
        doc_prefixes=("///", "/**"), nesting=True,
    ),
    "Scala": LangSpec(
        "Scala", "//", *_BLOCK_C,
        doc_prefixes=("/**",),
    ),
    "Dart": LangSpec(
        "Dart", "//", *_BLOCK_C,
        doc_prefixes=("///", "/**"),
    ),
    "Perl": LangSpec(
        "Perl", "#", ("=pod", "=cut"),
        doc_prefixes=("#",),
    ),
}

# 扩展名 → 语言名
EXT_TO_LANG = {
    ".py": "Python", ".pyi": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".hh": "C++", ".hxx": "C++", ".ino": "C++",
    ".rs": "Rust",
    ".cs": "C#",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".php": "PHP", ".phtml": "PHP",
    ".rb": "Ruby", ".rake": "Ruby", ".gemspec": "Ruby",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ksh": "Shell",
    ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    ".sql": "SQL",
    ".lua": "Lua",
    ".r": "R", ".rmd": "R",
    ".swift": "Swift",
    ".scala": "Scala", ".sc": "Scala",
    ".dart": "Dart",
    ".pl": "Perl", ".pm": "Perl",
}

# 备份/临时文件后缀：这些后缀本身不代表语言，需要剥掉后重新判断
_BACKUP_SUFFIXES = (
    ".bak", ".orig", ".old", ".save", ".tmp", ".swp", ".copy",
    ".commenter", ".rej", "~",
)

# 内容特征探测：语言 → 高置信度特征正则列表
_CONTENT_HINTS = {
    "Python": (r"^\s*(?:def|class)\s+\w+.*:\s*$", r"^\s*(?:import|from)\s+\w+"),
    "JavaScript": (r"\b(?:const|let|var)\s+\w+\s*=", r"=>\s*\{", r"^\s*import\s+.*from\s+['\"]"),
    "TypeScript": (r":\s*(?:string|number|boolean|void)\b", r"\binterface\s+\w+\s*\{"),
    "Java": (r"\bpublic\s+(?:static\s+)?(?:final\s+)?class\s+\w+", r"System\.out\.print"),
    "Go": (r"^\s*package\s+\w+\s*$", r"^\s*func\s+\(?\w*\)?\s*\w+\s*\("),
    "Rust": (r"^\s*(?:pub\s+)?fn\s+\w+", r"^\s*use\s+[\w:]+;", r"\blet\s+mut\b"),
    "C#": (r"\busing\s+System\b", r"\bnamespace\s+[\w.]+"),
    "Kotlin": (r"^\s*fun\s+\w+\s*\(", r"\bval\s+\w+\s*[:=]"),
    "PHP": (r"<\?php", r"\$\w+\s*="),
    "Ruby": (r"^\s*(?:def|class|module)\s+\w+", r"\bend\s*$"),
    "Shell": (r"^#!.*\b(?:bash|sh|zsh)\b", r"\$\{?\w+\}?"),
    "SQL": (r"(?i)^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE)\b",),
    "Lua": (r"^\s*(?:local\s+)?function\s+\w+", r"\bend\s*$"),
    "C": (r"#include\s*<", r"\bint\s+main\s*\("),
    "C++": (r"#include\s*<", r"\bstd::", r"\bnamespace\s+\w+"),
    "Swift": (r"^\s*(?:import\s+\w+|func\s+\w+)", r"\blet\s+\w+\s*[:=]"),
    "Dart": (r"^\s*(?:import\s+'|class\s+\w+)", r"\bvoid\s+main\s*\("),
}
_CONTENT_HINTS_COMPILED = {
    lang: [re.compile(p, re.MULTILINE) for p in pats]
    for lang, pats in _CONTENT_HINTS.items()
}


def _strip_backup_suffixes(path: str) -> Tuple[str, bool]:
    """剥离备份/临时后缀，返回 (净化后的文件名, 是否剥离过)。"""
    name = os.path.basename(path)
    changed = False
    # 反复剥离（如 app.js.commenter.bak）
    while True:
        low = name.lower()
        for suffix in _BACKUP_SUFFIXES:
            if low.endswith(suffix):
                name = name[: -len(suffix)]
                changed = True
                break
        else:
            break
    return name, changed


def detect_from_content(source: str) -> Optional[str]:
    """内容特征探测：返回命中特征最多的语言，无把握时返回 None。

    为避免误判，要求命中数至少为 1，且采用"命中数最高"策略；
    平局时返回 None（宁可退化也不猜错）。
    """
    if not source:
        return None
    head = source[:4000]
    scores = {}
    for lang, patterns in _CONTENT_HINTS_COMPILED.items():
        hits = sum(1 for p in patterns if p.search(head))
        if hits:
            scores[lang] = hits
    if not scores:
        return None
    best = max(scores.values())
    winners = [lang for lang, s in scores.items() if s == best]
    return winners[0] if len(winners) == 1 else None


def _prefix_match(name: str) -> Optional[str]:
    """按文件名惯例判断：``Dockerfile``、``Makefile``、``Rakefile`` 等。

    Makefile / Dockerfile 的注释符同为 ``#``，按 Shell 语法处理即可
    给出正确的注释剥离与统计行为。
    """
    base = os.path.basename(name).lower()
    if base.startswith(("dockerfile", "makefile", "jenkinsfile")):
        return "Shell"
    if base.startswith(".bash") or base in ("bashrc", ".profile", ".zshrc"):
        return "Shell"
    if base in ("rakefile", "gemfile", "vagrantfile", "brewfile"):
        return "Ruby"
    return None


def detect_language(path: str, source: Optional[str] = None) -> str:
    """推断文件语言，返回 ``LANG_SPECS`` 中的键，失败返回 ``"Unknown"``。

    探测顺序（逐级降级，任一级命中即返回）：
        1. 直接扩展名精确匹配；
        2. 剥离备份后缀后的扩展名（解决 ``app.js.bak`` 问题）；
        3. 文件名前缀惯例（``Dockerfile``、``Rakefile`` 等）；
        4. 内容特征正则（需提供 source）。

    Args:
        path: 文件路径（只用于取扩展名/文件名，不读取文件）。
        source: 可选的文件文本内容，用于第 4 级探测。

    Returns:
        语言名，如 ``"Python"``；无法判定时为 ``"Unknown"``。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in EXT_TO_LANG:
        return EXT_TO_LANG[ext]

    # 第 2 级：剥离 .bak / .commenter.bak 等后缀
    cleaned, changed = _strip_backup_suffixes(path)
    if changed:
        ext2 = os.path.splitext(cleaned)[1].lower()
        if ext2 in EXT_TO_LANG:
            return EXT_TO_LANG[ext2]

    # 第 3 级：文件名前缀惯例
    hinted = _prefix_match(os.path.basename(path) or cleaned)
    if hinted:
        return hinted

    # 第 4 级：内容探测
    if source:
        by_content = detect_from_content(source)
        if by_content:
            return by_content

    return "Unknown"


def spec_for(language: str) -> LangSpec:
    """按语言名取规格。

    未知语言返回一个安全的默认规格（``#`` 行注释、无块注释），
    保证调用方无需处理 None。可用 ``result.name == "Unknown"``
    判断是否已降级。
    """
    spec = LANG_SPECS.get(language)
    if spec is not None:
        return spec
    return LangSpec("Unknown", "#")


def spec_for_path(path: str, source: Optional[str] = None) -> LangSpec:
    """便捷函数：探测路径语言并返回规格（未知时给出安全默认值）。"""
    return spec_for(detect_language(path, source))


# 目录扫描时跳过的常见依赖/产物目录
SKIP_DIRS = frozenset({
    ".git", ".svn", ".hg", ".bzr", "node_modules", "__pycache__",
    ".venv", "venv", "env", ".env", "dist", "build", "target",
    "vendor", ".idea", ".vscode", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", "bin", "obj", "out", "coverage",
    ".next", ".nuxt", "site-packages", "third_party", "bower_components",
})

MAX_FILE_BYTES = 10 * 1024 * 1024   # 单文件 10 MB 上限
MINIFIED_LINE_LEN = 800             # 单行超长判定阈值


if __name__ == "__main__":   # pragma: no cover - 手动排查用
    import sys
    for arg in sys.argv[1:]:
        print("%-45s -> %s" % (arg, detect_language(arg)))
