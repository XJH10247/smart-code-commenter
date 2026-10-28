#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注释覆盖率扫描器（smart-code-commenter 配套工具）。

扫描单个源码文件或目录，统计注释覆盖率并列出缺少文档注释的
函数/类，同时检测疑似过期注释（TODO/FIXME 积压、文档参数与
函数签名不一致）。

用法：
    python comment_scanner.py <路径> [选项]

常用选项：
    --format json|markdown|text  输出格式（默认 markdown）
    --max-files N                目录扫描文件数上限（默认 500）
    --min-coverage PCT           覆盖率门禁，低于则退出码 1（默认关闭）
    --include-private            将私有/半私有符号计入分母（默认计入，
                                 用 --no-private 关闭）
    --no-private                 排除私有符号
    --include-tests              不跳过测试文件（默认跳过）
    --quiet                      只输出摘要

退出码：
    0  扫描完成且满足门禁
    1  扫描完成但覆盖率低于 --min-coverage
    2  输入错误（路径不存在等）
    3  扫描不完整，或带门禁但没有可计符号

设计约束：
- 仅使用 Python 标准库，零第三方依赖；
- 任何单个文件的解析失败都不会导致整体崩溃（逐文件隔离异常）；
- 只读操作，绝不修改、删除、执行被扫描的代码。

相对旧版的关键修正（详见 CHANGELOG）：
1. 语言识别统一走 `langspec`，符号统计与注释剥离口径一致；
2. 补齐 Ruby / Lua / R / Shell / PowerShell / SQL / Scala / Swift /
   Dart / Perl 的符号解析（旧版这 7 种语言符号恒为 0，覆盖率失真）；
3. 文档注释识别改为"向上扫描连续注释块"，修掉旧版
   「JSDoc 与函数之间夹一行 // 就判无注释」与
   「普通行注释+空行被判为有文档」两类误判；
4. 私有符号默认计入分母（对齐 interrogate/--ignore-private 语义），
   避免分母缩水导致覆盖率虚高；
5. minified 检测改为全文采样，不再只看前 50 行；
6. 新增 --min-coverage 门禁，可直接接入 CI。
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import math
import os
import re
import sys
import tokenize
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

# 允许以脚本方式直接运行（无需安装为包）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langspec import (  # noqa: E402
    LANG_SPECS,
    SKIP_DIRS,
    MAX_FILE_BYTES,
    MINIFIED_LINE_LEN,
    detect_language,
    spec_for,
)

# ---------------------------------------------------------------------------
# 符号提取正则（覆盖 langspec 中登记的、有明确函数/类语法的语言）
# ---------------------------------------------------------------------------

FUNC_PATTERNS: Dict[str, re.Pattern] = {
    "JavaScript": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"
        r"|^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?"
        r"(?:function\b|\()"
        r"|^\s*(?:export\s+)?class\s+(\w+)"
        r"|^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\w+\s*=>"
    ),
    "TypeScript": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"
        r"|^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?"
        r"(?:function\b|\()"
        r"|^\s*(?:export\s+)?(?:abstract\s+)?(?:class|interface|enum|type)\s+(\w+)"
        r"|^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\w+\s*=>"
    ),
    "Java": re.compile(
        r"^\s*(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:public|protected)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?"
        r"(?:[\w<>\[\],.?\s]+?)\s+(\w+)\s*\("
        r"|^\s*(?:public\s+)?(?:abstract\s+|final\s+|sealed\s+)?"
        r"(?:class|interface|enum|record)\s+(\w+)"
    ),
    "Go": re.compile(
        r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*(?:\[[^\]]*\])?\s*\("
        r"|^type\s+(\w+)\s+(?:struct|interface)"
    ),
    "C": re.compile(
        r"^\s*[A-Za-z_][\w\s\*]*?\b(\w+)\s*\([^;{}]*\)\s*"
        r"(?:const\s*)?(?:\{|;|\{\s*\}|$)"
        r"|^\s*(?:typedef\s+)?(?:struct|union|enum)\s+(\w+)\s*\{"
    ),
    "C++": re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?[A-Za-z_~][\w\s\*:<>,~&]*?"
        r"\b(\w+)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?"
        r"(?:override\s*)?(?:final\s*)?(?:\{|;|\{\s*\}|$)"
        r"|^\s*(?:class|struct|union|enum(?:\s+class)?)\s+(\w+)"
    ),
    "Rust": re.compile(
        r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?"
        r"(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+(\w+)"
        r"|^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union)\s+(\w+)"
        r"|^\s*impl(?:<[^>]*>)?\s+([\w:]+)"
    ),
    "C#": re.compile(
        r"^\s*(?:\[[\w()\s,.]+\]\s*)*(?:public|protected|internal)\s+"
        r"(?:static\s+)?(?:async\s+)?(?:virtual\s+)?(?:override\s+)?"
        r"(?:partial\s+)?(?:[\w<>\[\],.?\s]+?)\s+(\w+)\s*\("
        r"|^\s*(?:public\s+)?(?:abstract\s+|sealed\s+|static\s+|partial\s+)?"
        r"(?:class|interface|struct|enum|record)\s+(\w+)"
    ),
    "Kotlin": re.compile(
        r"^\s*(?:public\s+|internal\s+|private\s+|protected\s+)?"
        r"(?:suspend\s+)?(?:inline\s+)?fun\s+(?:<[^>]*>\s*)?"
        r"(?:[\w<>.?]+\.)?(\w+)\s*\("
        r"|^\s*(?:data\s+|open\s+|sealed\s+|abstract\s+|enum\s+|annotation\s+)?"
        r"class\s+(\w+)"
    ),
    "PHP": re.compile(
        r"^\s*(?:abstract\s+|final\s+)?(?:public\s+|protected\s+|private\s+)?"
        r"(?:static\s+)?function\s+(\w+)"
        r"|^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+(\w+)"
    ),
    "Ruby": re.compile(
        r"^\s*def\s+(?:self\.)?([\w?!=\[\]<>+*/-]+)"
        r"|^\s*(?:class|module)\s+(\w+)"
    ),
    "Lua": re.compile(
        r"^\s*(?:local\s+)?function\s+([\w.:]+)"
        r"|^\s*([\w.]+)\s*=\s*function\b"
    ),
    "R": re.compile(
        r"^\s*(\w+)\s*(?:<-|=)\s*function\b"
        r"|^\s*setMethod\s*\(\s*[\"']([\w.]+)"
    ),
    "Shell": re.compile(
        r"^\s*function\s+([\w.-]+)\s*\(?\)?"
        r"|^\s*([\w.-]+)\s*\(\s*\)\s*\{"
    ),
    "PowerShell": re.compile(
        r"^\s*function\s+(?:[\w-]+:)?([\w-]+)"
        r"|^\s*(?:class|enum)\s+([\w-]+)"
    ),
    "SQL": re.compile(
        r"(?i)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?"
        r"(?:PROCEDURE|FUNCTION|TRIGGER|VIEW|TABLE)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([\w.]+)"
    ),
    "Swift": re.compile(
        r"^\s*(?:public\s+|internal\s+|private\s+|fileprivate\s+|open\s+)?"
        r"(?:static\s+|class\s+)?(?:mutating\s+)?func\s+(\w+)"
        r"|^\s*(?:public\s+|open\s+)?(?:final\s+)?(?:class|struct|enum|protocol)\s+(\w+)"
    ),
    "Scala": re.compile(
        r"^\s*(?:private\s+|protected\s+|override\s+|final\s+)*def\s+(\w+)"
        r"|^\s*(?:case\s+)?(?:class|object|trait)\s+(\w+)"
    ),
    "Dart": re.compile(
        r"^\s*(?:@\w+\s*)*(?:[\w<>?,\s]+?\s+)?(\w+)\s*\([^;{}]*\)\s*(?:async\s*)?\{"
        r"|^\s*(?:abstract\s+)?class\s+(\w+)"
    ),
    "Perl": re.compile(r"^\s*sub\s+(\w+)"),
}

# 被正则误捕的保留字，需排除
_NOT_A_SYMBOL = frozenset({
    "if", "for", "while", "switch", "return", "catch", "do", "else",
    "elif", "unless", "until", "foreach", "try", "except", "finally",
    "with", "match", "case", "when", "then", "new", "delete", "sizeof",
    "defined", "print", "printf", "echo", "exit", "begin", "end",
})

# 测试文件识别：默认跳过（这些文件的辅助函数不写 docstring 是合理的）
_TEST_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:tests?|__tests__|test|spec|specs)(?:[/\\]|$)"
    r"|(?:^|[/\\])[\w.-]*[._-](?:test|spec)s?\.[\w]+$"
    r"|(?:^|[/\\])test_[\w.]+$",
    re.IGNORECASE,
)

# TODO 家族标记
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG|OPTIMIZE|REVIEW)\b[:\s]*(.*)")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Symbol:
    """一个待检查文档注释的符号（函数/类/方法）。

    Attributes:
        name: 符号名。
        line: 定义所在行号（1 起）。
        kind: ``function`` / ``class`` / ``method``。
        documented: 是否已有文档注释。
        visibility: ``public`` / ``private`` / ``semiprivate``。
        end_line: 定义体结束行号（无法判定时为 -1）。
        is_test: 名称疑似测试函数。
    """

    name: str
    line: int
    kind: str = "function"
    documented: bool = False
    visibility: str = "public"
    end_line: int = -1
    is_test: bool = False

    @property
    def locatable(self) -> bool:
        """是否能定位到函数体（用于精确判断注释归属）。"""
        return self.end_line > self.line


@dataclass
class FileReport:
    """单个文件的扫描结果。"""
    path: str
    language: str = "Unknown"
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    symbols: List[Symbol] = field(default_factory=list)
    todos: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    parse_mode: str = "heuristic"      # ast / tokenize / heuristic
    diagnostics: List[Dict[str, object]] = field(default_factory=list)
    status: str = "scanned"           # scanned / skipped / excluded / truncated / error
    complete: bool = True

    # -- 覆盖率计算 ---------------------------------------------------------

    def _counted(self, include_private: bool, include_tests: bool) -> List[Symbol]:
        out = []
        for s in self.symbols:
            if not include_private and s.visibility != "public":
                continue
            if not include_tests and s.is_test:
                continue
            out.append(s)
        return out

    @property
    def documented_count(self) -> int:
        return sum(1 for s in self.symbols if s.documented)

    def doc_coverage(self, include_private: bool = True,
                     include_tests: bool = False) -> Optional[float]:
        """文档注释覆盖率；无可计符号时返回 None（而非 0，避免误导）。

        Args:
            include_private: 是否把私有/半私有符号计入分母。
            include_tests: 是否把测试函数计入分母。
        """
        counted = self._counted(include_private, include_tests)
        if not counted:
            return None
        return round(sum(1 for s in counted if s.documented) / len(counted) * 100, 1)

    @property
    def comment_ratio(self) -> float:
        """注释行占代码行的比例（不含空行）。"""
        if self.code_lines <= 0:
            return 0.0
        return round(self.comment_lines / self.code_lines * 100, 1)

    def counted_symbols(self, include_private: bool = True,
                        include_tests: bool = False) -> List[Symbol]:
        """暴露给渲染层的计数符号列表。"""
        return self._counted(include_private, include_tests)

    @property
    def undocumented(self) -> List["Symbol"]:
        return [s for s in self.symbols if not s.documented]


# ---------------------------------------------------------------------------
# 文件读取（多编码回退，保证不因编码问题崩溃）
# ---------------------------------------------------------------------------

def read_text_safely(path: str) -> Optional[str]:
    """优先按 BOM 或声明编码读取，再回退；失败返回 None。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_FILE_BYTES:
        return None
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeError:
            return None
    if b"\x00" in raw[:4096]:
        return None
    header = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    header = b"\n".join(header.split(b"\n", 2)[:2])
    if re.search(br"(?m)^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+", header):
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            return raw.decode(encoding)
        except (UnicodeError, SyntaxError, LookupError):
            return None
    for enc in ("utf-8-sig", "gbk", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeError, LookupError):
            continue
    return None


# ---------------------------------------------------------------------------
# 注释与代码行统计（状态机，字符串感知）
# ---------------------------------------------------------------------------

def _split_lines_with_state(source: str, line_marker: str,
                            block: Optional[tuple]) -> List[tuple]:
    """逐行切分并标注 (行内容, 是否为注释行, 是否含代码)。

    实现为字符串感知的状态机，避免把字符串字面量里的注释符
    （典型如 ``url = "http://x"``）误判为注释。同时正确跟踪块注释
    跨行状态，并支持 Rust/Kotlin 等的块注释嵌套。
    """
    result: List[tuple] = []
    in_block = 0
    block_open = block[0] if block else None
    block_close = block[1] if block else None
    b_len = len(block_open) if block_open else 0

    for raw_line in source.splitlines():
        i, n = 0, len(raw_line)
        has_code = False
        has_comment = False
        in_str: Optional[str] = None
        in_template = False

        while i < n:
            ch = raw_line[i]

            if in_block:
                has_comment = True
                if block_close and raw_line.startswith(block_close, i):
                    in_block -= 1
                    i += len(block_close)
                    continue
                if (block_open and raw_line.startswith(block_open, i)):
                    in_block += 1
                    i += b_len
                    continue
                i += 1
                continue

            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
                    if not in_template:
                        has_code = True
                i += 1
                continue

            # 行注释
            if line_marker and raw_line.startswith(line_marker, i):
                # SQL 中 `--` 需要避免吃掉 `a--b` 这类表达式；此处保持宽松
                has_comment = True
                break

            # 块注释
            if block_open and raw_line.startswith(block_open, i):
                in_block = 1
                has_comment = True
                i += b_len
                continue

            # 字符串起始
            if ch in ("'", '"', "`"):
                in_str = ch
                in_template = ch == "`"
                has_code = True
                i += 1
                continue

            if not ch.isspace():
                has_code = True
            i += 1

        result.append((raw_line, has_comment, has_code))

    return result


def count_lines(source: str, report: FileReport) -> None:
    """统计代码行/注释行/空行，并收集 TODO 家族标记。"""
    spec = spec_for(report.language)
    block = (spec.block_open, spec.block_close) if spec.block_open else None
    lines = _split_lines_with_state(source, spec.line, block)

    for idx, (raw, has_comment, has_code) in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            report.blank_lines += 1
            continue
        if has_comment:
            report.comment_lines += 1
            m = _TODO_RE.search(stripped)
            if m:
                report.todos.append(
                    "第 %d 行 [%s] %s" % (idx + 1, m.group(1), m.group(2).strip()[:100])
                )
        if has_code:
            report.code_lines += 1


# ---------------------------------------------------------------------------
# 文档注释识别（修正旧版两类误判）
# ---------------------------------------------------------------------------

def _is_any_comment_line(line: str, spec) -> bool:
    """判断某行是否至少是一个注释行（无论普通注释还是文档注释）。

    用于向上扫描时**跨越**普通注释行，避免因中间夹了一行 ``//``
    说明就丢掉上方的 JSDoc 块。
    """
    s = line.strip()
    if not s:
        return False
    if s.startswith("*"):                      # 块注释主体/收尾
        return True
    if spec.line and s.startswith(spec.line):
        return True
    if spec.block_open and s.startswith(spec.block_open):
        return True
    if spec.block_close and s.startswith(spec.block_close):
        return True
    for prefix in spec.doc_prefixes:
        if s.startswith(prefix):
            return True
    return False


def _is_doc_comment_line(line: str, spec) -> bool:
    """判断某行是否可视为该语言文档注释的一部分。

    包含注释块的起始/结束定界行（``/**``、``*/``、``///``）与块内
    星号行（`` * 描述``），但不包含纯普通注释行（JS 的 ``//``）。
    """
    s = line.strip()
    if not s:
        return False
    if s.startswith("*"):                     # 含 */ 与 * 开头的块内行
        return True
    for prefix in spec.doc_prefixes:
        if s.startswith(prefix):
            return True
    return False


def _is_strong_doc_marker(line: str, spec) -> bool:
    """判断该行是否为**强**文档注释记号。

    强记号是各语言公认的文档注释起始，出现即可认定"有文档注释"：

    - ``/**`` / ``/*!`` / ``///`` / ``//!`` / ``#:``：块注释语言与
      Doxygen/C#/Rust 的文档定界符；
    - Python 三引号：docstring 定界符；
    - Go 的行注释：godoc **规定** ``//`` 即文档注释（``gofmt`` 不
      区分普通注释与文档注释），因此对 Go 而言 ``//`` 属强记号。

    其余弱记号（Shell/Ruby/SQL 的 ``#``、``--``）在语言中不区分
    文档与普通注释，需要额外长度判据。
    """
    s = line.strip()
    # Go：`//` 就是文档注释语法
    if spec.name == "Go" and s.startswith("//"):
        return True
    for prefix in spec.doc_prefixes:
        if prefix in ("//", "#", "--"):
            continue
        if s.startswith(prefix):
            return True
    return False


def _is_block_boundary(line: str, spec) -> bool:
    """判断该行是否为块注释的定界行（``/**`` / ``*/`` / ``/*!``）。"""
    s = line.strip()
    if s.startswith("*/") or s.startswith("/*"):
        return True
    for prefix in spec.doc_prefixes:
        if prefix.startswith("/*") and s.startswith(prefix):
            return True
    return False


def _block_has_delimiters(lines: List[str], index: int) -> bool:
    """向上确认 index 处属于一个真正的块注释（存在 ``/**`` 起始行）。

    JSDoc/Javadoc/KDoc/Doxygen 的文档注释形如::

        /**
         * 描述
         */

    仅看到收尾的 ``*/`` 不足以断定这是文档注释（可能是文件末尾的
    普通块注释）。因此向上找配对的 ``/*`` 起始行，确认其是否为
    ``/**`` 或 ``/*!``（文档注释定界符）。
    """
    j = index
    limit = max(-1, index - 200)
    while j > limit:
        s = lines[j].strip()
        if s.startswith("/*"):
            # 起始行本身即文档注释定界符，且必须在 index 之前找到配对的 */
            return s.startswith(("/**", "/*!", "/***"))
        j -= 1
    return False


def find_doc_block_above(lines: List[str], index: int, spec) -> bool:
    """从定义行向上扫描，判断是否存在紧邻的文档注释块。

    修正旧版逻辑的三个缺陷：

    1. 旧版只看**紧邻上一行**，遇到 ``JSDoc + 一行普通 // 注释 + 函数``
       会误判为"无文档注释"；本实现向上遍历连续注释行，允许中间夹
       普通注释行。
    2. 旧版把任何 ``//`` 开头的行都当作文档注释（DOC_PREFIXES 含
       ``"//"``），导致普通行注释也算有文档；本实现改用语言的
       ``doc_prefixes`` 做强度分级：JS/TS/Java 只认 ``/**``，
       Go/Shell 认 ``//``/``#`` 但要求注释块有实质长度。
    3. 旧版遇到块注释收尾行 ``*/`` 时因不在前缀表内而直接判定无注释；
       本实现显式识别 ``*/`` 并向上配对校验起始定界符。

    扫描在遇到第一个"非注释且非空"的行时停止——保证注释块确实紧贴
    在定义之上（中间隔了代码就不算文档注释）。

    Args:
        lines: 文件全部行。
        index: 定义所在行下标（0 起）。
        spec: 语言规格。

    Returns:
        是否存在文档注释块。
    """
    j = index - 1
    if j < 0:
        return False

    # 允许跳过 1 个空行（JSDoc 与函数之间常有空行）
    skipped_blank = 0
    while j >= 0 and not lines[j].strip() and skipped_blank < 2:
        j -= 1
        skipped_blank += 1
    if j < 0 or not lines[j].strip():
        return False

    s = lines[j].strip()

    # 非注释行 → 不可能是文档注释
    if not _is_any_comment_line(s, spec):
        return False

    # 走完整个连续注释区（允许内部夹杂普通注释行，如 JSDoc 后跟一行
    # `// 补充说明`）。遇到第一个"非注释且非空"行即停止。
    k = j
    limit = max(-1, index - 80)
    while k > limit and _is_any_comment_line(lines[k], spec):
        k -= 1
    k += 1                                   # k 为注释区首行下标
    block = lines[k:j + 1]

    # 判据 1：注释区含强文档记号（/**、///、//!、三引号、#:，或 Go 的 //）
    for line in block:
        if _is_strong_doc_marker(line, spec):
            return True

    # 判据 2：注释区含块注释主体行，且向上能找到配对的 `/**` 起始符
    for off, line in enumerate(block):
        if line.strip().startswith("*"):
            if _block_has_delimiters(lines, k + off - 1):
                return True

    # 判据 3：纯弱记号行注释（Shell/SQL 的 #/-- 等）。
    # 注意：对**有明确文档注释语法的语言**（JS/TS/Java/Kotlin/PHP/
    # Rust/C#…）而言，``//`` 是普通注释而非文档注释，因此这里只在
    # 该语言"没有独立文档注释语法"时才认可连续行注释块。
    has_doc_syntax = any(
        p not in ("//", "#", "--") for p in spec.doc_prefixes
    )
    if has_doc_syntax:
        return False

    text_len = sum(len(x.strip()) for x in block)
    if len(block) >= 2:
        return True
    # 单行注释：要求内容达到一定长度，且必须是紧贴定义的独立注释行
    return text_len >= 24


# ---------------------------------------------------------------------------
# Python：基于 AST 的精确分析
# ---------------------------------------------------------------------------

@dataclass
class DocParameter:
    """参数条目；行号为传入 doc 文本的 1-based、两端包含区间。"""

    names: Tuple[str, ...]
    start_line: int
    end_line: int


_GOOGLE_PARAMETERS = frozenset({"Args", "Arguments", "Keyword Args"})
_NUMPY_PARAMETERS = frozenset({"Parameters", "Other Parameters"})
_DOC_HEADINGS = _GOOGLE_PARAMETERS | _NUMPY_PARAMETERS | frozenset({
    "Returns", "Return", "Yields", "Yield", "Raises", "Raise", "Warns",
    "Warnings", "Warning", "Attributes", "Methods", "Notes", "Note",
    "Examples", "Example", "See Also", "References", "Todo", "Details",
})
_DOC_NAME = r"\*{0,2}[^\W\d]\w*"
_GOOGLE_PARAMETER = re.compile(
    r"^(" + _DOC_NAME + r")\s*(?:\([^)]*\))?\s*:\s*.*$"
)
_NUMPY_PARAMETER = re.compile(
    r"^(" + _DOC_NAME + r"(?:\s*,\s*" + _DOC_NAME + r")*)(?:\s*:\s*.*)?$"
)


def _doc_sections(lines: List[str]) -> List[Tuple[int, int, str, bool]]:
    """返回顶层章节 (标题下标, 正文下标, 风格, 是否为参数章节)。"""
    body_indents = [_indent_of(s) for s in lines[1:] if s.strip()]
    margin = min(body_indents) if body_indents else 0
    if (lines and lines[0].strip().rstrip(":") in _DOC_HEADINGS
            and lines[0].strip().rstrip(":") not in _GOOGLE_PARAMETERS | _NUMPY_PARAMETERS):
        margin = min(margin, _indent_of(lines[0]))
    sections = []
    for i, line in enumerate(lines):
        title = line.strip()
        if not title or (i != 0 and _indent_of(line) > margin):
            continue
        if (i + 1 < len(lines)
                and re.fullmatch(r"-{3,}", lines[i + 1].strip())
                and (i == 0 or _indent_of(lines[i + 1]) == _indent_of(line))
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]*", title)):
            sections.append((i, i + 2, "numpy", title in _NUMPY_PARAMETERS))
        elif title.endswith(":") and title[:-1] in _DOC_HEADINGS:
            sections.append((i, i + 1, "google", title[:-1] in _GOOGLE_PARAMETERS))
    return sections


def parse_doc_parameters(doc: str) -> Tuple[List[DocParameter], bool]:
    """仅解析 Google/NumPy 参数章节；保留原行号，参数名去掉 * 前缀。"""
    lines = [line.expandtabs() for line in doc.splitlines()]
    sections = _doc_sections(lines)
    entries: List[DocParameter] = []
    found = False
    for index, (header, start, style, supported) in enumerate(sections):
        if not supported:
            continue
        found = True
        stop = sections[index + 1][0] if index + 1 < len(sections) else len(lines)
        header_indent = _indent_of(lines[header])
        entry_indent = None
        current = None
        pattern = _GOOGLE_PARAMETER if style == "google" else _NUMPY_PARAMETER
        for i in range(start, stop):
            text = lines[i].strip()
            if not text:
                if current is not None:
                    current.end_line = i + 1
                continue
            indent = _indent_of(lines[i])
            if indent < header_indent or (style == "google" and indent == header_indent):
                break
            if entry_indent is None:
                entry_indent = indent
            if indent < entry_indent:
                break
            if indent == entry_indent:
                match = pattern.fullmatch(text)
                if match is None:
                    break                       # 不把同级说明文字并入可删除条目
                names = tuple(name.strip().lstrip("*") for name in match.group(1).split(","))
                current = DocParameter(names, i + 1, i + 1)
                entries.append(current)
            elif current is not None:
                current.end_line = i + 1
    return entries, found


def _diagnose(report: FileReport, code: str, node, message: str) -> None:
    report.diagnostics.append({
        "code": code, "line": node.lineno, "symbol": node.name, "message": message,
    })
    report.warnings.append(message)


def _visitor_to_symbol(node, name: str, kind: str, documented: bool,
                       end_line: int = -1) -> Symbol:
    if name.startswith("__") and name.endswith("__"):
        visibility = "public"          # dunder 视为公开（__init__ 等）
    elif name.startswith("_"):
        visibility = "semiprivate"
    else:
        visibility = "public"
    is_test = name.startswith("test_") or name.endswith("_test")
    return Symbol(name, node.lineno, kind, documented, visibility,
                  end_line, is_test)


def scan_python_ast(source: str, report: FileReport) -> bool:
    """用 ast 精确提取 Python 函数/类及其 docstring 状态。

    Returns:
        True 表示 AST 解析成功（parse_mode 置为 ``ast``）；
        False 表示语法错误已降级。
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        report.warnings.append(
            "Python 语法解析失败（%s），已降级为启发式统计，精度下降"
            % exc.__class__.__name__
        )
        report.complete = False
        return False

    report.parse_mode = "ast"
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        doc = ast.get_docstring(node)
        documented = bool((doc or "").strip())
        end = getattr(node, "end_lineno", -1) or -1
        report.symbols.append(
            _visitor_to_symbol(node, node.name, kind, documented, end)
        )
        if doc is not None and not documented:
            _diagnose(report, "DOC001", node,
                      "第 %d 行 %s: docstring 为空或仅含空白" % (node.lineno, node.name))
        if documented and not isinstance(node, ast.ClassDef):
            _check_doc_drift(node, report)
    return True


def _check_doc_drift(node, report: FileReport) -> None:
    """按共享章节解析结果检查参数名称；仅在顺序确定时报告 PAR003。"""
    doc = ast.get_docstring(node, clean=False) or ""
    entries, has_section = parse_doc_parameters(doc)
    if not has_section:
        return
    args = list(node.args.posonlyargs) + list(node.args.args)
    if node.args.vararg:
        args.append(node.args.vararg)
    args.extend(node.args.kwonlyargs)
    if node.args.kwarg:
        args.append(node.args.kwarg)
    real = [a.arg for a in args if a.arg not in {"self", "cls"}]
    named = [name for entry in entries for name in entry.names if name not in {"self", "cls"}]
    real_set, named_set = set(real), set(named)
    for name in dict.fromkeys(named):
        if name not in real_set:
            _diagnose(report, "PAR002", node,
                      "第 %d 行 %s(): docstring 记载的参数 '%s' 不在函数签名中，注释疑似过期"
                      % (node.lineno, node.name, name))
    missing = [name for name in real if name not in named_set]
    if missing:
        _diagnose(report, "PAR001", node,
                  "第 %d 行 %s(): 参数 %s 未在 docstring 中说明"
                  % (node.lineno, node.name, ", ".join(repr(a) for a in missing)))
    sections = _doc_sections([line.expandtabs() for line in doc.splitlines()])
    if (len(named) > 1 and len(named) == len(named_set)
            and named_set == real_set and named != real
            and all(len(entry.names) == 1 for entry in entries)
            and sum(1 for section in sections if section[3]) == 1):
        _diagnose(report, "PAR003", node,
                  "第 %d 行 %s(): docstring 参数顺序与函数签名不一致"
                  % (node.lineno, node.name))


def scan_python_fallback(source: str, report: FileReport) -> None:
    """语法错误时的降级方案：行级正则粗提取 def/class。"""
    report.parse_mode = "heuristic"
    pattern = re.compile(r"^(\s*)(?:async\s+)?(def|class)\s+(\w+)")
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        name = m.group(3)
        kind = "class" if m.group(2) == "class" else "function"
        documented = find_doc_block_above(lines, i, spec_for("Python"))
        fake = type("N", (), {"lineno": i + 1})()
        report.symbols.append(_visitor_to_symbol(fake, name, kind, documented))


# ---------------------------------------------------------------------------
# 其他语言：启发式分析（含缩进层级推算函数体范围）
# ---------------------------------------------------------------------------

def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _estimate_end(lines: List[str], start: int, language: str) -> int:
    """估算定义体结束行号（0 起下标，含）。

    用于把注释归属限定在"函数体之前的注释块"，避免把函数内部的
    行内注释误当作文档注释。

    策略：
        - 花括号语言：从定义行向下统计 ``{}`` 配平；
        - 缩进语言（Python/Ruby/Lua）：取下一个缩进 <= 当前的行；
        - 无法判定时返回 -1（调用方退化为向上扫描）。
    """
    if language in ("Ruby", "Lua", "R", "Shell", "PowerShell", "Perl"):
        base = _indent_of(lines[start])
        for j in range(start + 1, len(lines)):
            if not lines[j].strip():
                continue
            if _indent_of(lines[j]) <= base:
                return j - 1
        return len(lines) - 1

    depth = 0
    seen = False
    for j in range(start, min(len(lines), start + 4000)):
        line = lines[j]
        # 去掉字符串与注释后再数括号，避免误计
        cleaned = re.sub(r"//.*$", "", line)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned)
        for ch in cleaned:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return j
    return -1


def scan_generic(source: str, report: FileReport) -> None:
    """非 Python 语言的符号提取与文档注释检测（启发式）。"""
    pattern = FUNC_PATTERNS.get(report.language)
    if pattern is None:
        return
    spec = spec_for(report.language)
    lines = source.splitlines()

    # 内容探测结果可能与语言标签冲突时以标签为准；此处只用它判断
    # 是否明显是压缩代码（避免对生成物做无意义统计）
    for i, line in enumerate(lines):
        if len(line) > MINIFIED_LINE_LEN:
            continue
        m = pattern.match(line)
        if not m:
            continue
        name = next((g for g in m.groups() if g), None)
        if not name or name.lower() in _NOT_A_SYMBOL:
            continue
        if len(name) > 80:                     # 明显不是标识符
            continue

        documented = find_doc_block_above(lines, i, spec)
        kind = "class" if re.search(
            r"\b(class|interface|struct|enum|trait|protocol|record|union)\b", line
        ) else "function"
        end = _estimate_end(lines, i, report.language)

        # 可见性：按语言惯例粗判
        visibility = "public"
        if re.search(r"\b(private|protected|internal|fileprivate)\b", line):
            visibility = "private"
        elif name.startswith("_") and not name.startswith("__"):
            visibility = "semiprivate"
        is_test = bool(re.match(r"^(test|Test|it|spec|should)\w*$", name))

        report.symbols.append(
            Symbol(name, i + 1, kind, documented, visibility, end, is_test)
        )


# ---------------------------------------------------------------------------
# 单文件 / 目录扫描
# ---------------------------------------------------------------------------

def _looks_minified(lines: List[str]) -> bool:
    """全文采样判断是否压缩/生成代码（旧版只看前 50 行，会漏判）。"""
    if not lines:
        return False
    step = max(1, len(lines) // 200)          # 最多采样 200 行，覆盖全文
    long_lines = 0
    sampled = 0
    for i in range(0, len(lines), step):
        sampled += 1
        if len(lines[i]) > MINIFIED_LINE_LEN:
            long_lines += 1
    if sampled == 0:
        return False
    return long_lines >= 3 and long_lines / sampled > 0.02


def _skip_report(report: FileReport, status: str, reason: str) -> FileReport:
    report.skipped = True
    report.status = status
    report.skip_reason = reason
    report.complete = status not in {"error", "truncated"}
    return report


def scan_file(path: str, skip_tests: bool = True) -> FileReport:
    """扫描单个文件；任何内部异常都被捕获并转为 skipped 状态。"""
    return _scan_file(os.fspath(path), skip_tests)


def _scan_file(path: str, skip_tests: bool, limit_reached: bool = False) -> FileReport:
    report = FileReport(path=path)
    try:
        if skip_tests and _TEST_PATH_RE.search(path):
            return _skip_report(report, "excluded", "测试文件（可用 --include-tests 纳入）")
        report.language = detect_language(path)
        if limit_reached and report.language != "Unknown":
            return _skip_report(report, "truncated", "达到 --max-files，仍有合格源码文件")

        source = read_text_safely(path)
        if source is None:
            return _skip_report(
                report, "error" if report.language != "Unknown" else "skipped",
                "无法读取（二进制/超大/编码不可识别/权限不足）",
            )
        report.language = detect_language(path, source)
        if report.language == "Unknown":
            return _skip_report(report, "skipped", "未识别的源码类型")
        if limit_reached:
            return _skip_report(report, "truncated", "达到 --max-files，仍有合格源码文件")
        if not source.strip():
            return _skip_report(report, "skipped", "空文件")

        lines = source.splitlines()
        report.total_lines = len(lines)

        if _looks_minified(lines):
            report.warnings.append(
                "疑似压缩/生成代码（存在大量超长行），符号统计仅供参考"
            )

        count_lines(source, report)

        if report.language == "Python":
            if not scan_python_ast(source, report):
                scan_python_fallback(source, report)
        else:
            report.parse_mode = "heuristic"
            scan_generic(source, report)

        # 私有符号占比过高时提示（可能是生成代码或命名风格异常）
        if report.symbols:
            private_ratio = sum(
                1 for s in report.symbols if s.visibility != "public"
            ) / len(report.symbols)
            if private_ratio > 0.8 and len(report.symbols) >= 10:
                report.warnings.append(
                    "80% 以上符号为私有/半私有，覆盖率按公开 API 口径可能失真"
                )
    except Exception as exc:  # 兜底：单文件失败绝不影响整体
        _skip_report(report, "error", "解析异常: %s: %s" % (exc.__class__.__name__, exc))
    return report


def _is_excluded(relative: str, patterns: List[str], directory: bool = False) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern)
               or (directory and fnmatch.fnmatchcase(relative + "/", pattern))
               for pattern in patterns)


def scan_path(target: str, max_files: int,
              skip_tests: bool = True,
              exclude: Optional[List[str]] = None) -> List[FileReport]:
    """返回文件报告及排除/截断/错误哨兵；用 scan_status 汇总完整性。"""
    if not isinstance(max_files, int) or max_files <= 0:
        raise ValueError("max_files 必须为正整数")
    target = os.path.abspath(os.fspath(target))
    if not os.path.isfile(target) and not os.path.isdir(target):
        raise ValueError("路径不是可扫描的文件或目录: %s" % target)
    patterns = list(exclude or [])
    reports: List[FileReport] = []
    if os.path.isfile(target):
        if _is_excluded(os.path.basename(target), patterns):
            return [_skip_report(FileReport(target), "excluded", "匹配 --exclude")]
        return [scan_file(target, skip_tests)]

    attempted = 0

    def walk_error(exc: OSError) -> None:
        reports.append(_skip_report(FileReport(str(exc.filename or target)), "error",
                                    "目录读取失败: %s" % exc))

    try:
        for root, dirs, files in os.walk(target, onerror=walk_error):
            kept = []
            for name in sorted(dirs):
                path = os.path.join(root, name)
                relative = os.path.relpath(path, target).replace("\\", "/")
                reason = ""
                if _is_excluded(relative, patterns, directory=True):
                    reason = "匹配 --exclude"
                elif name in SKIP_DIRS or name.startswith("."):
                    reason = "默认排除目录"
                elif skip_tests and _TEST_PATH_RE.search(path):
                    reason = "测试目录（可用 --include-tests 纳入）"
                elif os.path.islink(path):
                    reason = "符号链接目录（不递归）"
                if reason:
                    reports.append(_skip_report(FileReport(path), "excluded", reason))
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                path = os.path.join(root, name)
                relative = os.path.relpath(path, target).replace("\\", "/")
                if _is_excluded(relative, patterns):
                    report = _skip_report(FileReport(path), "excluded", "匹配 --exclude")
                elif attempted < max_files:
                    report = scan_file(path, skip_tests)
                else:
                    report = _scan_file(path, skip_tests, limit_reached=True)
                reports.append(report)
                if report.status == "truncated":
                    return reports
                if (not report.skipped or report.status == "error"
                        or (report.status == "skipped" and report.language != "Unknown")):
                    attempted += 1
    except OSError as exc:
        walk_error(exc)
    return reports


def scan_status(reports: List[FileReport]) -> Dict[str, object]:
    """统计已遇到的文件/目录条目；截断后未遍历的条目不计数。"""
    return {
        "scanned": sum(not r.skipped for r in reports),
        "skipped": sum(r.skipped and r.status not in {"excluded", "truncated"} for r in reports),
        "excluded": sum(r.status == "excluded" for r in reports),
        "truncated": any(r.status == "truncated" for r in reports),
        "errors": sum(not r.complete and r.status != "truncated" for r in reports),
        "complete": all(r.complete for r in reports),
    }


# ---------------------------------------------------------------------------
# 输出渲染
# ---------------------------------------------------------------------------

_MD_ESCAPE = {"|": "\\|", "`": "\\`", "[": "\\[", "]": "\\]", "<": "\\<", ">": "\\>"}


def _escape_md(text: str, max_len: int = 200) -> str:
    """清洗用户来源文本，防止 Markdown 注入与报告膨胀。

    处理：换行转空格、转义结构性符号、中和危险协议、截断超长文本。
    适用于表格单元格、代码跨度、列表项中的自由文本。
    """
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    text = "".join(_MD_ESCAPE.get(c, c) for c in text)
    text = re.sub(
        r"(?i)(javascript|data|vbscript)\\?:",
        lambda m: m.group(0).replace(":", "\\:"),
        text,
    )
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def _overall(scanned: List[FileReport], include_private: bool,
             include_tests: bool) -> tuple:
    """汇总总体覆盖率，返回 (符号总数, 已文档数, 覆盖率)。"""
    total = documented = 0
    for r in scanned:
        if r.skipped:
            continue
        for s in r.counted_symbols(include_private, include_tests):
            total += 1
            if s.documented:
                documented += 1
    pct = documented / total * 100 if total else None
    return total, documented, pct


def _coverage_text(coverage: Optional[float]) -> str:
    return "%.1f%%" % coverage if coverage is not None else "未适用"


def _status_text(reports: List[FileReport]) -> str:
    return " ".join("%s=%s" % (key, str(value).lower())
                    for key, value in scan_status(reports).items())


def render_markdown(reports: List[FileReport], include_private: bool = True,
                    include_tests: bool = False,
                    show_undocumented: bool = True,
                    include_covered: bool = False, quiet: bool = False) -> str:
    """按 assets/templates/report.md 的结构渲染 Markdown 报告。"""
    scanned = [r for r in reports if not r.skipped]
    skipped = [r for r in reports if r.skipped]
    total_symbols, total_doc, overall = _overall(
        scanned, include_private, include_tests
    )

    total_comment = sum(r.comment_lines for r in scanned)
    total_code = sum(r.code_lines for r in scanned)

    out = ["# 注释覆盖率报告", ""]
    out.append("- 扫描状态：%s" % _status_text(reports))
    out.append("- 扫描文件：%d 个（未扫描条目 %d 个）" % (len(scanned), len(skipped)))
    out.append("- 可注释符号：%d 个，已有文档注释：%d 个" % (total_symbols, total_doc))
    out.append("- **总体文档覆盖率：%s**" % _coverage_text(overall))
    if quiet:
        return "\n".join(out)
    if total_code:
        out.append("- 注释行占比：%.1f%%（%d 注释行 / %d 代码行）"
                   % (total_comment / total_code * 100, total_comment, total_code))
    if not include_private:
        out.append("- 口径：已排除私有/半私有符号")
    if include_tests:
        out.append("- 口径：已包含测试文件")
    out.append("")

    if scanned:
        out.append("## 各文件明细")
        out.append("")
        out.append("| 文件 | 语言 | 代码行 | 注释行 | 符号数 | 文档覆盖率 |")
        out.append("|------|------|-------|-------|-------|-----------|")
        for r in sorted(
            scanned,
            key=lambda x: (
                x.doc_coverage(include_private, include_tests)
                if x.doc_coverage(include_private, include_tests) is not None
                else 101
            ),
        ):
            cov = r.doc_coverage(include_private, include_tests)
            counted = len(r.counted_symbols(include_private, include_tests))
            out.append("| %s | %s | %d | %d | %d | %s |"
                       % (_escape_md(r.path), _escape_md(r.language),
                          r.code_lines, r.comment_lines, counted,
                          "%.1f%%" % cov if cov is not None else "—"))
        out.append("")

    if show_undocumented:
        undocumented = [
            (r.path, s)
            for r in scanned
            for s in r.counted_symbols(include_private, include_tests)
            if not s.documented
        ]
        if undocumented:
            out.append("## 缺少文档注释的符号（建议优先处理）")
            out.append("")
            for path, s in undocumented[:100]:
                vis = "" if s.visibility == "public" else " _(%s)_" % s.visibility
                out.append("- `%s:%d` — %s `%s`%s"
                           % (_escape_md(path), s.line, _escape_md(s.kind),
                              _escape_md(s.name), vis))
            if len(undocumented) > 100:
                out.append("- …… 其余 %d 项省略" % (len(undocumented) - 100))
            out.append("")

    if include_covered:
        covered = [(r.path, s) for r in scanned
                   for s in r.counted_symbols(include_private, include_tests) if s.documented]
        out.extend(["## 已有文档注释的符号", ""])
        for path, s in covered[:100]:
            out.append("- `%s:%d` — %s `%s`"
                       % (_escape_md(path), s.line, _escape_md(s.kind), _escape_md(s.name)))
        if not covered:
            out.append("- 无")
        if len(covered) > 100:
            out.append("- …… 其余 %d 项省略" % (len(covered) - 100))
        out.append("")

    todo_items = [(r.path, t) for r in scanned for t in r.todos]
    if todo_items:
        out.append("## TODO / FIXME 积压")
        out.append("")
        for path, t in todo_items[:50]:
            out.append("- `%s` %s" % (_escape_md(path), _escape_md(str(t))))
        if len(todo_items) > 50:
            out.append("- …… 其余 %d 项省略" % (len(todo_items) - 50))
        out.append("")

    warn_items = [(r.path, w) for r in scanned for w in r.warnings]
    if warn_items:
        out.append("## 疑似过期/异常注释")
        out.append("")
        for path, w in warn_items[:50]:
            out.append("- `%s` %s" % (_escape_md(path), _escape_md(str(w))))
        if len(warn_items) > 50:
            out.append("- …… 其余 %d 项省略" % (len(warn_items) - 50))
        out.append("")

    if skipped:
        out.append("## 跳过的文件")
        out.append("")
        reasons: Dict[str, int] = {}
        for r in skipped:
            reasons[r.skip_reason] = reasons.get(r.skip_reason, 0) + 1
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            out.append("- %d 个：%s" % (n, _escape_md(reason)))
        out.append("")

    return "\n".join(out)


def _shorten_path(path: str, width: int = 50) -> str:
    """把过长的路径缩短到 ``width`` 字符以内，**保留文件名**。

    文件名才是识别条目用的部分，因此超长时从左侧省略目录前缀
    （``…/parent/file.py``）而不是从右侧截断——后者会把文件名整个切掉，
    导致同一目录下的多个文件在报告里显示成一模一样的名字。
    """
    if len(path) <= width:
        return path
    base = os.path.basename(path)
    if len(base) >= width:
        return "…" + base[-(width - 1):]
    keep = width - len(base) - 4          # 4 = "…/" + "/"
    return "…/" + path[-keep:] if keep > 0 else "…/" + base


def render_text(reports: List[FileReport], include_private: bool = True,
                include_tests: bool = False, include_covered: bool = False,
                quiet: bool = False) -> str:
    """精简终端输出。"""
    scanned = [r for r in reports if not r.skipped]
    total, documented, overall = _overall(scanned, include_private, include_tests)
    lines = [
        "coverage=%s | 扫描 %d 个文件 | 符号 %d 个 | 已文档 %d 个"
        % (_coverage_text(overall), len(scanned), total, documented),
        _status_text(reports),
    ]
    if quiet:
        return "\n".join(lines)
    for r in sorted(
        scanned,
        key=lambda x: (x.doc_coverage(include_private, include_tests)
                       if x.doc_coverage(include_private, include_tests) is not None else 101),
    ):
        cov = r.doc_coverage(include_private, include_tests)
        counted = len(r.counted_symbols(include_private, include_tests))
        lines.append("  %7s  %-50s (%d 符号)"
                     % (_coverage_text(cov), _shorten_path(r.path, 50), counted))
    for documented_state, title in ((False, "缺少文档注释的符号"), (True, "已有文档注释的符号")):
        if documented_state and not include_covered:
            continue
        items = [(r.path, s) for r in scanned
                 for s in r.counted_symbols(include_private, include_tests)
                 if s.documented == documented_state]
        if items or documented_state:
            lines.append(title + ":")
            for path, s in items[:100]:
                lines.append("  %s:%d %s %s" % (path, s.line, s.kind, s.name))
            if not items:
                lines.append("  无")
            if len(items) > 100:
                lines.append("  …… 其余 %d 项省略" % (len(items) - 100))
    for r in reports:
        if r.skipped:
            lines.append("  [%s] %s: %s" % (r.status, r.path, r.skip_reason))
        for warning in r.warnings:
            lines.append("  %s: %s" % (r.path, warning))
    return "\n".join(lines)


def render_json(reports: List[FileReport], include_private: bool = True,
                include_tests: bool = False, include_covered: bool = False,
                quiet: bool = False) -> str:
    """渲染 JSON 报告（供程序化消费 / CI 集成）。"""
    scanned = [r for r in reports if not r.skipped]
    total, documented, overall = _overall(scanned, include_private, include_tests)
    status = scan_status(reports)
    payload = {
        "summary": {
            "files_scanned": status["scanned"],
            "files_skipped": status["skipped"],
            "symbols": total,
            "documented": documented,
            "undocumented": total - documented,
            "coverage_pct": overall,
            **status,
        },
    }
    if quiet:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    payload["files"] = []
    for r in reports:
        counted = r.counted_symbols(include_private, include_tests) if not r.skipped else []
        item = {
            "path": r.path,
            "language": r.language,
            "total_lines": r.total_lines,
            "code_lines": r.code_lines,
            "comment_lines": r.comment_lines,
            "blank_lines": r.blank_lines,
            "parse_mode": r.parse_mode,
            "coverage_pct": r.doc_coverage(include_private, include_tests) if not r.skipped else None,
            "symbols": [asdict(s) for s in r.symbols],
            "undocumented_symbols": [asdict(s) for s in counted if not s.documented],
            "todos": r.todos,
            "warnings": r.warnings,
            "diagnostics": r.diagnostics,
            "skipped": r.skipped,
            "skip_reason": r.skip_reason,
            "status": r.status,
            "complete": r.complete,
        }
        if include_covered:
            item["covered_symbols"] = [asdict(s) for s in counted if s.documented]
        payload["files"].append(item)
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器（抽出便于测试）。"""
    parser = argparse.ArgumentParser(
        description="注释覆盖率扫描器（只读，零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 正常 / 1 低于门禁 / 2 输入错误 / 3 扫描不完整或门禁无可计符号",
    )
    parser.add_argument("path", help="要扫描的文件或目录")
    parser.add_argument("--format", choices=("markdown", "json", "text"),
                        default="markdown", help="输出格式（默认 markdown）")
    parser.add_argument("--max-files", type=int, default=500,
                        help="合格源码文件扫描上限（正整数，默认 500）")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="排除相对扫描根目录的 POSIX 路径 glob（可重复；单文件使用文件名）")
    parser.add_argument("--min-coverage", type=float, default=None,
                        metavar="PCT",
                        help="覆盖率门禁：0..100 的有限数，低于时退出码为 1")
    parser.add_argument("--no-private", action="store_true",
                        help="将私有/半私有符号排除出分母")
    parser.add_argument("--include-tests", action="store_true",
                        help="不跳过测试文件")
    parser.add_argument("--include-covered", action="store_true",
                        help="保留缺失符号列表，并另列已文档符号")
    parser.add_argument("--quiet", action="store_true",
                        help="只输出摘要和扫描状态（JSON 格式保持有效 JSON）")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_files <= 0:
        print("错误：--max-files 必须为正整数", file=sys.stderr)
        return 2
    if (args.min_coverage is not None
            and (not math.isfinite(args.min_coverage) or not 0 <= args.min_coverage <= 100)):
        print("错误：--min-coverage 必须为 0..100 的有限数", file=sys.stderr)
        return 2
    if not os.path.isfile(args.path) and not os.path.isdir(args.path):
        print("错误：路径不是可扫描的文件或目录 -> %s" % args.path, file=sys.stderr)
        return 2

    try:
        reports = scan_path(args.path, args.max_files,
                            skip_tests=not args.include_tests, exclude=args.exclude)
    except ValueError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        reports = [_skip_report(FileReport(os.path.abspath(args.path)), "error", str(exc))]

    include_private = not args.no_private
    include_tests = args.include_tests
    render_options = {"include_covered": args.include_covered, "quiet": args.quiet}
    if args.format == "json":
        text = render_json(reports, include_private, include_tests, **render_options)
    elif args.format == "text" or args.quiet:
        text = render_text(reports, include_private, include_tests, **render_options)
    else:
        text = render_markdown(reports, include_private, include_tests, **render_options)

    try:
        print(text)
    except UnicodeEncodeError:
        # Windows GBK 控制台兜底
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))

    if not scan_status(reports)["complete"]:
        print("INCOMPLETE: 扫描不完整，不能判定门禁通过", file=sys.stderr)
        return 3
    if args.min_coverage is not None:
        total, documented, overall = _overall(reports, include_private, include_tests)
        if overall is None:
            print("N/A: 无可计符号，覆盖率门禁未适用", file=sys.stderr)
            return 3
        numerator, denominator = args.min_coverage.as_integer_ratio()
        if documented * 100 * denominator < total * numerator:
            print("FAIL: 覆盖率 %.12g%% (%d/%d) 低于门禁 %.12g%%"
                  % (overall, documented, total, args.min_coverage), file=sys.stderr)
            return 1
        print("PASS: 覆盖率 %.12g%% (%d/%d) 达到门禁 %.12g%%"
              % (overall, documented, total, args.min_coverage), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
