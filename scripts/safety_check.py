#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""有限范围的源码比较：SAFE / UNSAFE / UNVERIFIED，退出码 0 / 1 / 3；输入错误为 2。"""

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

from langspec import MAX_FILE_BYTES, detect_language, spec_for  # noqa: E402
import langspec as ls  # noqa: E402


_DIRECTIVE = re.compile(
    r"(?im)(?:^#!|coding\s*[:=]|"
    r"\bgo\s*:|^//\s*\+build\b|^(?://|/\*)\s*(?:line|extern|export)\s|\bcgo\b|"
    r"\b(?:noqa|nosec|nolint|eslint|jshint|jslint|tslint|pylint|ruff|"
    r"pyright|mypy|shellcheck|rubocop|prettier|istanbul|coverage)\b|"
    r"@(?:ts-(?:check|nocheck|ignore|expect-error)|flow|noflow|type|typedef|"
    r"jsx\w*|cc_on)\b|<reference\b|"
    r"\btype\s*:|\b(?:fmt|yapf|isort)\s*:|\bpragma\b|"
    r"\b(?:frozen_string_literal|warn_indent|shareable_constant_value)\s*:|"
    r"\bsource(?:Mapping)?URL\s*=|^/\*(?:!|\+|M!))"
)
_TRAILING_SPACE = re.compile(r"[ \t\r\n]*")
_LINE_END = re.compile(r"[\r\n]")
_WORD = re.compile(
    r"(?:[^\W\d]|[$])(?:\w|[$])*|(?:\d|\.\d)(?:[\w.]|(?<=[eEpP])[+-])*",
    re.UNICODE,
)
_OPERATOR = re.compile(
    r">>>=|<<=|>>=|===|!==|>>>|\*\*=|&&=|\|\|=|\?\?=|<=>|\.\.\.|\?\.\.|"
    r"->\*|\.\*|::|->|=>|==|!=|~=|<=|>=|\+\+|--|&&|\|\||\?\?|\?\.|"
    r"\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|\*\*|//|:=|\.\.|##|[^\s]"
)


def read_text(path: str) -> Optional[str]:
    """多编码回退读取；失败返回 None。"""
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


def _protected_comment(source: str, start: int, end: int) -> Optional[str]:
    text = source[start:end]
    if not _DIRECTIVE.search(text):
        return None
    line = source.count("\n", 0, start) + 1
    column = start - source.rfind("\n", 0, start) - 1
    following = _TRAILING_SPACE.match(source, end).group()
    return repr((line, column, text, following))


class _DocstringStripper(ast.NodeTransformer):
    """只移除模块、类、函数的首个字符串语句。"""

    @staticmethod
    def _strip(node):
        if (node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body = node.body[1:]
            if not node.body and not isinstance(node, ast.Module):
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
    """有效 Python 去除真正 docstring 后的 AST 指纹。"""
    try:
        tree = ast.parse(source)
        compile(tree, "<safety_check>", "exec", dont_inherit=True)
        return ast.dump(_DocstringStripper().visit(tree), include_attributes=False)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def python_token_fingerprint(source: str) -> Optional[List[Tuple[int, str]]]:
    """保留字符串、缩进、逻辑换行和受保护注释，不猜测 docstring。"""
    result = []
    offsets = [0]
    for line in source.split("\n"):
        offsets.append(offsets[-1] + len(line) + 1)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                start = offsets[tok.start[0] - 1] + tok.start[1]
                protected = _protected_comment(source, start, start + len(tok.string))
                if protected is not None:
                    result.append((tok.type, protected))
            elif tok.type == tokenize.NL and (
                    not tok.line.strip() or tok.line.lstrip().startswith("#")):
                continue
            elif tok.type != tokenize.ENCODING:
                result.append((tok.type, tok.string))
        return result
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None


class _Unverified(ValueError):
    pass


def _unsupported_at(source: str, i: int, language: str) -> bool:
    patterns = {
        "C": r'<[:%]|[:%]>|%:',
        "C++": r'(?:u8|u|U|L)?R"|<[:%]|[:%]>|%:',
        "Rust": r'(?:br|cr|r)\#*"',
        "C#": r'[@$]+"',
        "Kotlin": r'`',
        "Scala": r'`',
        "Dart": r'''[rR]['"]''',
        "Ruby": r'%|<<|__END__\b',
        "Perl": r'(?:q[qwrx]?|m|s|tr|y)\b|<<|__(?:END|DATA)__\b',
        "Shell": r'<<|\$[({]|`',
        "PowerShell": r'''@['"]|`|\$\(''',
        "PHP": r'<<<|__halt_compiler\b|\?>|<\?(?!php\b)',
        "Lua": r'(?:--)?\[=+\[|\[\[',
        "SQL": r'''\$(?:\w*\$)|[qQ]['"]|#''',
        "R": r'''[rR]['"]|%''',
        "Swift": r'#+["/]',
    }
    pattern = patterns.get(language)
    return bool(pattern and re.compile(pattern).match(source, i))


def _block_end(source: str, start: int, spec: ls.LangSpec) -> int:
    opening, closing = spec.block_open, spec.block_close
    i, depth = start + len(opening), 1
    while i < len(source):
        if source.startswith(closing, i):
            if opening.startswith("="):
                if (i and source[i - 1] != "\n") or (
                        i + len(closing) < len(source)
                        and not source[i + len(closing)].isspace()):
                    i += 1
                    continue
                end = source.find("\n", i)
                return len(source) if end < 0 else end
            depth -= 1
            i += len(closing)
            if not depth:
                return i
        elif source.startswith(opening, i):
            if spec.nesting:
                depth += 1
            elif spec.name in ("SQL", "PowerShell"):
                raise _Unverified("块注释嵌套依赖语言方言")
            i += len(opening)
        else:
            i += 1
    raise _Unverified("块注释未闭合")


def _string_end(source: str, start: int, language: str) -> int:
    quote = source[start]
    if source.startswith(quote * 3, start):
        raise _Unverified("不支持三引号/raw 字符串")
    if quote == "'" and language in ("Rust", "Scala") and (
            start + 2 >= len(source) or (
                source[start + 1] != "\\" and source[start + 2] != "'")):
        raise _Unverified("无法排除生命周期/符号字面量")
    if quote == "`" and language not in ("JavaScript", "TypeScript", "Go", "SQL"):
        raise _Unverified("不支持此反引号构造")
    raw = quote == "`" and language in ("Go", "SQL")
    single_raw = quote == "'" and language in ("Shell", "PowerShell", "SQL")
    i = start + 1
    while i < len(source):
        ch = source[i]
        if ch == quote:
            if language in ("SQL", "PowerShell") and source.startswith(quote * 2, i):
                i += 2
                continue
            return i + 1
        if ((language in ("JavaScript", "TypeScript") and quote == "`"
             and source.startswith("${", i))
                or (language in ("Ruby", "Perl") and quote == '"'
                    and ch in ("#", "$", "@"))
                or (language in ("Shell", "PowerShell", "PHP", "Kotlin", "Scala", "Dart")
                    and quote != "'" and ch in ("$", "`"))
                or (language == "Swift" and source.startswith("\\(", i))):
            raise _Unverified("不支持字符串内插/命令替换")
        if ch in "\r\n" and quote != "`":
            raise _Unverified("不支持此多行字符串或字符串未闭合")
        if ch == "\\" and not raw:
            if language == "SQL":
                raise _Unverified("SQL 字符串转义依赖方言")
            if not single_raw:
                i += 2
                continue
        if ch == "`" and language == "PowerShell" and quote == '"':
            raise _Unverified("不支持 PowerShell 转义字符串")
        i += 1
    raise _Unverified("字符串未闭合")


def generic_fingerprint(source: str, language: str) -> List[str]:
    """有限词法比较；不支持或未闭合的构造拒绝验证。"""
    spec = spec_for(language)
    if spec.name == "Unknown":
        raise _Unverified("未知语言")
    if "\x00" in source or "\u2028" in source or "\u2029" in source:
        raise _Unverified("不支持的控制字符/行分隔符")
    if language in ("C", "C++") and re.search(r"\\\r?\n|\?\?/", source):
        raise _Unverified("不支持预处理续行/trigraph")
    if language == "Java" and "\\u" in source:
        raise _Unverified("不支持词法分析前的 Java Unicode 转义")
    if language == "PHP" and not source.startswith("<?php"):
        raise _Unverified("无法确认 PHP 代码区边界")

    out: List[str] = []
    gap = False
    previous_kind = ""
    previous_text = ""
    preprocessor = False
    keep_spaces = language in (
        "Ruby", "Shell", "Perl", "PowerShell", "Swift", "Rust", "R",
        "Kotlin", "Scala", "C#", "SQL",
    )

    def emit(kind: str, text: str) -> None:
        nonlocal gap, previous_kind, previous_text
        if out and out[-1] != "newline" and gap and (
                keep_spaces or preprocessor
                or (kind == "literal" and previous_kind in ("word", "literal"))
                or (kind == "word" and previous_kind == "literal")):
            out.append("space")
        out.append(kind + ":" + repr(text))
        gap = False
        previous_kind = kind
        previous_text = text

    def newline() -> None:
        nonlocal gap, previous_kind, preprocessor
        if out and out[-1] != "newline":
            out.append("newline")
        gap = False
        previous_kind = ""
        preprocessor = False

    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch in "\r\n":
            newline()
            i += 2 if source.startswith("\r\n", i) else 1
            continue
        if ch in " \t":
            gap = True
            i += 1
            continue
        if ch.isspace() or ch == "\\":
            raise _Unverified("不支持的空白/字符串外转义")
        if _unsupported_at(source, i, language):
            raise _Unverified("不支持的 raw/heredoc/引用构造")

        block = bool(spec.block_open and source.startswith(spec.block_open, i))
        if block and spec.block_open.startswith("="):
            end = i + len(spec.block_open)
            block = (i == 0 or source[i - 1] == "\n") and (
                end == n or source[end].isspace())
        line = bool(spec.line and source.startswith(spec.line, i))
        if language == "SQL" and line and i + 2 < n and not source[i + 2].isspace():
            raise _Unverified("SQL 行注释边界依赖方言")
        if language == "Shell" and line:
            line = i == 0 or source[i - 1].isspace() or source[i - 1] in ";|&()<>"
        if language == "PHP" and ch == "#":
            if source.startswith("#[", i):
                raise _Unverified("不支持 PHP 属性构造")
            line = True
        if i == 0 and source.startswith("#!"):
            line = True
        if block or line:
            line_end = _LINE_END.search(source, i)
            end = _block_end(source, i, spec) if block else (
                line_end.start() if line_end else n)
            comment = source[i:end]
            if language == "PHP" and "?>" in comment:
                raise _Unverified("不支持注释内 PHP 关闭标签")
            protected = _protected_comment(source, i, end)
            if protected is not None:
                emit("directive", protected)
            gap = True
            if "\n" in comment or "\r" in comment:
                was_preprocessor = preprocessor
                newline()
                preprocessor = was_preprocessor
            i = end
            continue
        if ch in ("'", '"', "`"):
            end = _string_end(source, i, language)
            literal = source[i:end]
            if language == "Go" and re.fullmatch(
                    r'"(?:C|\\(?:x43|u0043|U00000043|103))"|`C`',
                    literal.replace("\r", "")):
                raise _Unverified("无法排除 cgo 前导注释")
            emit("literal", literal)
            i = end
            continue
        if ch == "/" and language in ("Ruby", "Perl", "Swift"):
            raise _Unverified("无法排除正则字面量")
        if language in ("JavaScript", "TypeScript") and ch in ("/", "<"):
            expression_start = {
                "return", "throw", "yield", "await", "case", "delete", "typeof",
                "void", "new", "in", "of", "instanceof", "else", "do", "extends",
                "default", "export", "import", "function", "class", "const", "let", "var",
            }
            if previous_kind not in ("word", "literal") or previous_text in expression_start:
                raise _Unverified("无法排除正则字面量或 JSX/TSX")
        if preprocessor and ch == "<":
            raise _Unverified("不支持预处理中的尖括号构造")
        if language == "Perl" and ch == "=" and (i == 0 or source[i - 1] == "\n"):
            raise _Unverified("不支持此 POD 指令")
        match = _WORD.match(source, i)
        if match:
            emit("word", match.group())
            i = match.end()
        else:
            if ch == "#" and language in ("C", "C++"):
                preprocessor = True
            match = _OPERATOR.match(source, i)
            if not match:
                raise _Unverified("无法识别的词法符号")
            emit("operator", match.group())
            i = match.end()

    if out and out[-1] == "newline":
        out.pop()
    return out


def _first_diff(old: str, new: str, label: str) -> str:
    """定位首个差异行。"""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    for idx, (a, b) in enumerate(zip(old_lines, new_lines)):
        if a != b:
            return "%s首个差异（第 %d 行）:\n  原: %s\n  新: %s" % (
                label, idx + 1, a[:160], b[:160])
    return "%s行数不一致：%d -> %d" % (label, len(old_lines), len(new_lines))


def resolve_language(path_or_ext: str, modified: str, original: str = "") -> str:
    """解析语言名、扩展名或路径；校验时不根据代码片段猜测语言。"""
    if path_or_ext in ls.LANG_SPECS or path_or_ext == "Unknown":
        return path_or_ext
    path = "x" + path_or_ext if path_or_ext.startswith(".") else path_or_ext
    if os.path.basename(path).lower().startswith(("makefile", "dockerfile", "jenkinsfile")):
        return "Unknown"
    return detect_language(path)


def compare(original: str, modified: str, path_or_ext: str,
            verbose: bool) -> Tuple[str, str]:
    """返回 SAFE、UNSAFE 或 UNVERIFIED 及说明，不保证运行行为等价。"""
    language = resolve_language(path_or_ext, modified, original)
    if language == "Python":
        fp_old, fp_new = python_fingerprint(original), python_fingerprint(modified)
        if fp_old is not None and fp_new is None:
            return "UNSAFE", "原 Python 有效，修改后无法编译"
        tk_old = python_token_fingerprint(original)
        tk_new = python_token_fingerprint(modified)
        if tk_old is not None and tk_new is not None:
            directives_old = [v for t, v in tk_old if t == tokenize.COMMENT]
            directives_new = [v for t, v in tk_new if t == tokenize.COMMENT]
            if directives_old != directives_new:
                return "UNSAFE", "受保护的指令/编码注释或其位置发生变化"
        if fp_old is not None and fp_new is not None:
            if tk_old is None or tk_new is None:
                return "UNVERIFIED", "无法验证 Python 指令注释"
            if fp_old == fp_new:
                return "SAFE", "Python AST 一致（仅剥离真正 docstring，指令注释已核对）"
            detail = "Python AST 不一致"
            if verbose:
                detail += "\n" + _first_diff(original, modified, "源码 ")
            return "UNSAFE", detail
        if tk_old is not None and tk_new is not None and tk_old != tk_new:
            uncertain = {tokenize.STRING, tokenize.NEWLINE, tokenize.NL,
                         tokenize.INDENT, tokenize.DEDENT}
            certain_old = [v for v in tk_old if v[0] not in uncertain]
            certain_new = [v for v in tk_new if v[0] not in uncertain]
            strings_old = [v for t, v in tk_old if t == tokenize.STRING]
            strings_new = [v for t, v in tk_new if t == tokenize.STRING]
            if certain_old != certain_new or strings_old == strings_new:
                detail = "Python AST 不可用，但检测到明确的 token/缩进/换行变化"
                if verbose:
                    detail += "\n" + _first_diff(original, modified, "源码 ")
                return "UNSAFE", detail
        return "UNVERIFIED", "原 Python 无效；token 比较不能确认 docstring 或源码等价"

    try:
        old = generic_fingerprint(original, language)
        new = generic_fingerprint(modified, language)
    except _Unverified as exc:
        return "UNVERIFIED", "%s：%s" % (language, exc)
    if old == new:
        return "SAFE", "%s：支持范围内的词法内容与指令注释一致" % language
    detail = "%s：源码词法内容、换行或受保护注释发生变化" % language
    if verbose:
        detail += "\n" + _first_diff("\n".join(old), "\n".join(new), "词法项 ")
    return "UNSAFE", detail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在支持的范围内比较源码是否仅普通注释/docstring 不同",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 SAFE / 1 UNSAFE / 2 输入错误 / 3 UNVERIFIED（未验证）",
    )
    parser.add_argument("original", help="原始文件（加注释前的备份）")
    parser.add_argument("modified", help="修改后文件（已加注释）")
    parser.add_argument("--verbose", action="store_true", help="UNSAFE 时输出首个差异位置")
    parser.add_argument("--quiet", action="store_true", help="只输出 SAFE / UNSAFE / UNVERIFIED")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    for path in (args.original, args.modified):
        if not os.path.isfile(path):
            print("ERROR: 文件不存在 -> %s" % path, file=sys.stderr)
            return 2
    src_old, src_new = read_text(args.original), read_text(args.modified)
    if src_old is None or src_new is None:
        print("ERROR: 文件无法读取（二进制/超大/编码不可识别）", file=sys.stderr)
        return 2
    language = resolve_language(args.modified, src_new, src_old)
    if language == "Unknown":
        language = resolve_language(args.original, src_new, src_old)
    verdict, detail = compare(src_old, src_new, language, args.verbose)
    text = verdict if args.quiet else "%s\n%s" % (verdict, detail)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    return {"SAFE": 0, "UNSAFE": 1, "UNVERIFIED": 3}[verdict]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
