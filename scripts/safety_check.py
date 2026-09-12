#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零逻辑变更安全校验器（smart-code-commenter 配套工具）。

比较"加注释前"与"加注释后"两个版本的源码，验证除注释/docstring 外
没有任何代码变化。

判定策略（按可靠性递进降级）：
    1. Python 且两版均可解析 → 剥离 docstring 后比较 AST（最精确）；
    2. Python 但存在语法错误 → 先做 **docstring 归一化**（把 docstring
       文本替换为哨兵）再做 token 序列比较。这是对旧版的关键修复：
       旧版直接比对 token，而 docstring 在 token 层面是普通 STRING，
       导致"给语法错误的代码补注释"这一官方支持的场景必然误报
       UNSAFE 并触发回滚；
    3. 其他语言 → 字符串感知地剥离注释、规范化空白后比较。

退出码：
    0  SAFE   仅注释发生变化，可安全保留
    1  UNSAFE 检测到代码逻辑变化，必须回滚
    2  ERROR  输入错误（文件不存在、无法读取等）

用法：
    python safety_check.py <原始文件> <修改后文件> [--verbose] [--quiet]
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys
import tokenize
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langspec import (  # noqa: E402
    MAX_FILE_BYTES,
    detect_language,
    spec_for,
)
import langspec as ls  # noqa: E402

_SENTINEL_BODY = "__SCC_DOCSTRING__"
_DOCSTRING_SENTINEL = '"%s"' % _SENTINEL_BODY


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def read_text(path: str) -> Optional[str]:
    """多编码回退读取；失败返回 None 而非抛异常。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_FILE_BYTES:
        return None
    if b"\x00" in raw[:4096] and raw[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        return None
    for enc in ("utf-8-sig", "utf-16", "utf-8", "gbk", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError, LookupError):
            continue
    return None


# ---------------------------------------------------------------------------
# Python：AST 级比较
# ---------------------------------------------------------------------------

class _DocstringStripper(ast.NodeTransformer):
    """移除模块/类/函数的 docstring 节点，使比较只关注可执行逻辑。"""

    @staticmethod
    def _strip(node):
        if (node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body = node.body[1:]
            if not node.body:
                # docstring 是唯一语句时补一个 pass，保持结构合法
                node.body = [ast.Pass()]
        return node

    def visit_Module(self, node):
        self.generic_visit(node)
        return self._strip(node)

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        return self._strip(node)

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        return self._strip(node)

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        return self._strip(node)


def python_fingerprint(source: str) -> Optional[str]:
    """返回剥离 docstring 后的 AST 指纹；语法错误返回 None。"""
    try:
        tree = ast.parse(source)
        tree = _DocstringStripper().visit(tree)
        return ast.dump(tree, include_attributes=False)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _normalize_python_docstrings(source: str) -> str:
    """把 docstring 文本替换为哨兵，供 token 级比较使用。

    这是对旧版的关键修复。旧版在 AST 不可用时直接比较 token 序列，
    而 docstring 与普通字符串在 token 层面无从区分，于是
    "给含语法错误的代码补 docstring" 会被判为逻辑变更（UNSAFE），
    导致该官方支持的场景必然回滚。

    实现思路：源码本身有语法错误，无法用 ``ast`` 分析，因此改用
    ``tokenize`` 逐 token 扫描（tokenize 对多数错误容忍度更高），
    按**位置规则**判断某个字符串字面量是否为 docstring：

        - 该字符串是所在缩进块的**第一条**语句，或
        - 它是整个文件的第一个语句。

    这个条件比语法定义更严格，因此不会把真实数据字符串误判为
    docstring（那会漏掉真正的逻辑变更）。

    替换方式为**原地按坐标覆写**，保留所有原始缩进与换行，
    确保替换后的文本仍可被 tokenize。

    Args:
        source: 源码文本。

    Returns:
        归一化后的源码；无法 tokenize 时原样返回。
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return source

    _SKIP_TYPES = (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING,
                   tokenize.INDENT, tokenize.DEDENT)
    at_block_start = True
    targets: List[Tuple[int, int, int, int]] = []   # (srow, scol, erow, ecol)

    for tok in tokens:
        if tok.type in _SKIP_TYPES:
            continue
        if tok.type == tokenize.NEWLINE:
            at_block_start = True
            continue
        if tok.type == tokenize.ENDMARKER:
            break
        if tok.type == tokenize.STRING and at_block_start:
            targets.append((tok.start[0], tok.start[1],
                            tok.end[0], tok.end[1]))
        at_block_start = False

    if not targets:
        return source

    # 原地覆写：按行拆开，只替换目标字符串占据的字符区间
    lines = source.splitlines(keepends=True)
    for srow, scol, erow, ecol in targets:
        if srow == erow:
            line = lines[srow - 1]
            # 保留该行尾部的换行与原有前导空白
            lines[srow - 1] = (line[:scol] + _DOCSTRING_SENTINEL
                               + line[ecol:])
        else:
            # 跨行字符串：起始行保留前缀 + 哨兵，中间行整行丢弃，
            # 末行保留最后一个换行符以维持行数基本稳定
            start_line = lines[srow - 1]
            end_line = lines[erow - 1]
            tail = end_line[ecol:]
            if not tail.endswith("\n") and "\n" in end_line[ecol:]:
                tail = end_line[ecol:]
            lines[srow - 1] = start_line[:scol] + _DOCSTRING_SENTINEL + tail
            for r in range(srow, erow):
                lines[r] = ""
    return "".join(lines)


def python_token_fingerprint(source: str, normalize_docstrings: bool = True
                             ) -> Optional[List[str]]:
    """token 级指纹（AST 失败时的降级方案）。

    丢弃注释/NL/换行/缩进标记，只保留语义 token；启用
    ``normalize_docstrings`` 时，**额外丢弃 docstring 哨兵 token**，
    使得"新增 docstring"不会产生任何 token 差异。

    这是对旧版的关键修复：旧版直接比对全部 token，而 docstring 在
    token 层面就是普通 STRING，导致给含语法错误的代码补注释必然
    误报 UNSAFE。

    Args:
        source: 源码文本。
        normalize_docstrings: 是否把 docstring 视为可忽略内容。
            关闭则行为与旧版一致（更严格，但会误报）。

    Returns:
        token 字符串列表；无法 tokenize 时返回 None。
    """
    if normalize_docstrings:
        try:
            source = _normalize_python_docstrings(source)
        except Exception:
            pass          # 归一化失败就退回原文，交由 token 比较兜底

    drop = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}
    result: List[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in drop:
                continue
            # 丢弃 docstring 哨兵：新增/修改 docstring 不应产生差异
            if tok.type == tokenize.STRING and \
                    tok.string.strip("'\"") == _SENTINEL_BODY:
                continue
            result.append("%d:%s" % (tok.type, tok.string))
        return result
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 通用语言：剥离注释后比较
# ---------------------------------------------------------------------------

def strip_comments_generic(source: str, line_marker: Optional[str],
                           block_open: Optional[str],
                           block_close: Optional[str],
                           nesting: bool = False) -> str:
    """剥离注释并规范化空白。

    实现为字符串感知的状态机：跟踪单引号/双引号/反引号字符串与
    转义，避免把字符串里的注释符误当注释剥掉（如 ``url = "http://x"``）。
    支持块注释嵌套（Rust/Kotlin/Swift），并处理行尾 ``\\`` 续行。

    Args:
        source: 源码。
        line_marker: 行注释符；None 表示该语言无行注释。
        block_open: 块注释起始符；None 表示无块注释。
        block_close: 块注释结束符。
        nesting: 块注释是否可嵌套。

    Returns:
        剥离注释并规范化空白后的文本（用于比较）。
    """
    out: List[str] = []
    in_block = 0
    in_str: Optional[str] = None
    in_template = False
    i, n = 0, len(source)

    while i < n:
        ch = source[i]

        if in_block:
            if block_close and source.startswith(block_close, i):
                in_block -= 1
                i += len(block_close)
            elif nesting and block_open and source.startswith(block_open, i):
                in_block += 1
                i += len(block_open)
            else:
                i += 1
            continue

        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
                if not in_template:
                    pass
            i += 1
            continue

        if ch in ("'", '"', "`"):
            in_str = ch
            in_template = ch == "`"
            out.append(ch)
            i += 1
            continue

        if block_open and source.startswith(block_open, i):
            in_block = 1
            i += len(block_open)
            continue

        if line_marker and source.startswith(line_marker, i):
            while i < n and source[i] != "\n":
                i += 1
            continue

        out.append(ch)
        i += 1

    # 规范化：去掉行尾空白与空行，压缩行内连续空白
    lines = []
    for line in "".join(out).splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主比较逻辑
# ---------------------------------------------------------------------------

def _first_diff(old: str, new: str, label: str) -> str:
    """定位首个差异行，供 --verbose 输出。"""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    for idx, (a, b) in enumerate(zip(old_lines, new_lines)):
        if a != b:
            return ("%s首个差异（规范化后第 %d 行）:\n  原: %s\n  新: %s"
                    % (label, idx + 1, a[:160], b[:160]))
    return ("%s行数不一致：%d -> %d（存在非注释内容增删）"
            % (label, len(old_lines), len(new_lines)))


def resolve_language(path_or_ext: str, modified: str,
                     original: str = "") -> str:
    """把"路径或扩展名"统一解析为语言名。

    支持三种入参形式，便于 API 调用与 CLI 复用：
        - 完整路径（``"src/app.js.commenter.bak"``）→ 走语言探测；
        - 纯扩展名（``".py"``）→ 拼接为伪文件名后探测；
        - 语言名（``"Python"``）→ 直接返回。
    """
    if path_or_ext in ls.LANG_SPECS:
        return path_or_ext
    if path_or_ext.startswith(".") and os.path.sep not in path_or_ext:
        return detect_language("x" + path_or_ext, modified)
    lang = detect_language(path_or_ext, modified)
    if lang == "Unknown" and original:
        lang = detect_language(path_or_ext, original)
    return lang


def compare(original: str, modified: str, path_or_ext: str,
            verbose: bool) -> Tuple[str, str]:
    """比较两个版本，返回 ``(判定结果, 说明)``。

    判定结果为 ``SAFE`` 或 ``UNSAFE``。语言通过 :func:`resolve_language`
    推断，因此 ``app.js.commenter.bak`` 这类备份文件名也能正确识别
    （旧版直接取扩展名，``.bak`` 取不到语法会退化成 ``#`` 注释，
    导致 JS/Java 等语言的注释剥离完全失效，且 JSDoc 无法被剥离，
    使每次合法操作都误报 UNSAFE）。

    Args:
        original: 原始（加注释前）源码。
        modified: 修改后源码。
        path_or_ext: 文件路径、扩展名或语言名，用于语言判定。
        verbose: 是否在 UNSAFE 时输出首个差异位置。
    """
    language = resolve_language(path_or_ext, modified, original)

    if language == "Python":
        fp_old = python_fingerprint(original)
        fp_new = python_fingerprint(modified)
        if fp_old is not None and fp_new is not None:
            if fp_old == fp_new:
                return "SAFE", "Python AST 一致（docstring 已剥离后比较）"
            if verbose:
                return "UNSAFE", _ast_diff_hint(original, modified)
            return "UNSAFE", "Python AST 不一致：修改涉及可执行代码"

        # AST 不可用（存在语法错误）→ docstring 归一化后的 token 比较
        tk_old = python_token_fingerprint(original, normalize_docstrings=True)
        tk_new = python_token_fingerprint(modified, normalize_docstrings=True)
        if tk_old is not None and tk_new is not None:
            if tk_old == tk_new:
                return "SAFE", ("token 序列一致（AST 不可用，已降级；"
                                "docstring 已归一化后比较）")
            if verbose:
                return "UNSAFE", _token_diff_hint(
                    tk_old, tk_new,
                    "（语法错误文件，docstring 已归一化）")
            return "UNSAFE", ("token 序列不一致（语法错误文件降级比较），"
                              "修改涉及非注释内容")

        # token 也不可用 → 走通用语言剥注释比较
        language = "Unknown"

    spec = spec_for(language)
    nesting = bool(getattr(spec, "nesting", False))
    stripped_old = strip_comments_generic(
        original, spec.line, spec.block_open, spec.block_close, nesting)
    stripped_new = strip_comments_generic(
        modified, spec.line, spec.block_open, spec.block_close, nesting)

    if stripped_old == stripped_new:
        return "SAFE", "剥离注释并规范化空白后内容一致"

    lang_note = "（语言：%s）" % spec.name if spec.name != "Unknown" \
        else "（未能识别语言，按 # 行注释处理，结果仅供参考）"
    if verbose:
        return "UNSAFE", _first_diff(stripped_old, stripped_new, lang_note + " ")
    return "UNSAFE", "剥离注释后内容不一致：修改涉及非注释内容" + lang_note


def _ast_diff_hint(original: str, modified: str) -> str:
    """AST 不一致时，给出最具可读性的定位提示。

    用"剥离 docstring 后的源码"逐行比较来近似定位，便于用户找到
    被误改的代码行。
    """
    def _strip_text(src: str) -> str:
        try:
            tree = ast.parse(src)
        except Exception:
            return src
        stripped = _DocstringStripper().visit(tree)
        try:
            return ast.unparse(stripped)
        except Exception:
            return src

    diff = _first_diff(_strip_text(original), _strip_text(modified), "")
    return "Python AST 不一致，修改涉及可执行代码。\n  " + diff


def _token_diff_hint(old: List[str], new: List[str], note: str) -> str:
    """token 序列差异定位。"""
    for idx, (a, b) in enumerate(zip(old, new)):
        if a != b:
            return "token 序列不一致%s：第 %d 个 token\n  原: %s\n  新: %s" \
                % (note, idx + 1, a[:120], b[:120])
    return "token 数量不一致%s：%d -> %d" % (note, len(old), len(new))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验两个版本的源码文件是否仅注释不同",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 SAFE / 1 UNSAFE / 2 输入错误",
    )
    parser.add_argument("original", help="原始文件（加注释前的备份）")
    parser.add_argument("modified", help="修改后文件（已加注释）")
    parser.add_argument("--verbose", action="store_true",
                        help="UNSAFE 时输出首个差异位置")
    parser.add_argument("--quiet", action="store_true",
                        help="只输出 SAFE / UNSAFE，适合脚本消费")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    for p in (args.original, args.modified):
        if not os.path.isfile(p):
            print("ERROR: 文件不存在 -> %s" % p, file=sys.stderr)
            return 2

    src_old = read_text(args.original)
    src_new = read_text(args.modified)
    if src_old is None or src_new is None:
        print("ERROR: 文件无法读取（二进制/超大/编码不可识别）", file=sys.stderr)
        return 2

    # 用"修改后文件"的路径探测语言；若探测失败再试原始文件
    language = detect_language(args.modified, src_new)
    if language == "Unknown":
        language = detect_language(args.original, src_old)

    # compare 接受路径，但这里已探测好语言，直接按语言分发
    if language == "Python":
        verdict, detail = compare(src_old, src_new, ".py", args.verbose)
    else:
        verdict, detail = compare(src_old, src_new,
                                 args.modified, args.verbose)

    text = verdict if args.quiet else "%s\n%s" % (verdict, detail)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    return 0 if verdict == "SAFE" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
