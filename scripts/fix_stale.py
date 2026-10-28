#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""默认 dry-run；仅删除可精确定位的多余参数条目，候选校验后逐文件提交。"""

from __future__ import annotations

import argparse
import ast
import difflib
import fnmatch
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langspec import MAX_FILE_BYTES, SKIP_DIRS, detect_language  # noqa: E402
import comment_scanner as cs  # noqa: E402


class AnalysisError(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    raw: bytes
    source: str
    encoding: str
    identity: tuple
    mode: int


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    symbol: str
    detail: str
    fixable: bool = False
    old_text: str = ""
    new_text: str = ""
    end_line: int = 0
    applied: bool = False
    _snapshot: Optional[Snapshot] = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}


@dataclass
class FileResult:
    path: str
    findings: List[Finding] = field(default_factory=list)
    status: str = "clean"
    error: str = ""
    backup: str = ""
    retained_files: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path, "status": self.status, "error": self.error,
            "applied_findings": sum(f.applied for f in self.findings),
            "pending_findings": sum(not f.applied for f in self.findings),
            "backup": self.backup, "retained_files": self.retained_files,
        }


def _identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)


def _read_snapshot(path: str) -> Snapshot:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            raise AnalysisError("不是普通文件（不自动修改符号链接）")
        with open(path, "rb") as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > MAX_FILE_BYTES:
            raise AnalysisError("文件超过 MAX_FILE_BYTES 限制")
        if not (_identity(info) == _identity(before) == _identity(after)
                == _identity(os.lstat(path))):
            raise AnalysisError("读取期间文件发生变化")
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        source = raw.decode(encoding)
        if source.encode(encoding) != raw:
            raise AnalysisError("编码不能无损往返")
        return Snapshot(raw, source, encoding, _identity(info),
                        stat.S_IMODE(info.st_mode))
    except (OSError, UnicodeError, SyntaxError, LookupError) as exc:
        raise AnalysisError("读取失败: %s" % exc) from exc


def _lines(source: str) -> List[str]:
    return io.StringIO(source, newline="").readlines()


def _real_arg_names(node) -> set:
    names = {a.arg for a in getattr(node.args, "posonlyargs", [])}
    names.update(a.arg for a in node.args.args)
    names.update(a.arg for a in node.args.kwonlyargs)
    if node.args.vararg:
        names.add(node.args.vararg.arg)
    if node.args.kwarg:
        names.add(node.args.kwarg.arg)
    return names


def _doc_token(value, tokens, source_lines):
    """只接受独占起止行、与 AST 原文逐字符一致的单个三引号 token。"""
    token = tokens.get((value.lineno, value.col_offset))
    if token is None:
        return None
    a, b = token.start, token.end
    b_byte = (b[0], len(source_lines[b[0] - 1][:b[1]].encode("utf-8")))
    if b_byte != (value.end_lineno, value.end_col_offset):
        return None
    match = re.match(r"(?i)^(?:r|u)?(\"\"\"|''')", token.string)
    if not match or not token.string.endswith(match.group(1)):
        return None
    body = token.string[match.end():-3]
    if ("\\" in body or body != value.value
            or any(c in body for c in "\v\f\x1c\x1d\x1e\x85\u2028\u2029")):
        return None
    if (source_lines[a[0] - 1][:a[1]].strip()
            or source_lines[b[0] - 1][b[1]:].strip()):
        return None
    return token


def _analyze(path: str, snapshot: Snapshot) -> List[Finding]:
    source = snapshot.source.replace("\r\n", "\n").replace("\r", "\n")
    try:
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")
        source_lines = source.split("\n")
        tokens = {}
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING:
                row, col = token.start
                tokens[(row, len(source_lines[row - 1][:col].encode("utf-8")))] = token
        original_lines = _lines(snapshot.source)
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.body or not isinstance(node.body[0], ast.Expr):
                continue
            value = node.body[0].value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            entries, has_section = cs.parse_doc_parameters(value.value)
            real_args = _real_arg_names(node)
            documented = {name for entry in entries for name in entry.names}
            token = _doc_token(value, tokens, source_lines)
            for entry in entries:
                extras = sorted(set(entry.names) - real_args)
                if not extras:
                    continue
                line = value.lineno
                end_line = line
                old_text = ""
                reason = "源码与 docstring 行映射不确定（转义、拼接或同行内容）"
                fixable = False
                if token:
                    line = token.start[0] + entry.start_line - 1
                    end_line = token.start[0] + entry.end_line - 1
                    if not (1 <= entry.start_line <= entry.end_line
                            <= len(value.value.splitlines())):
                        raise AnalysisError("参数解析器返回了无效行范围")
                    # 章节末的空白不属于说明，不删除承载结束引号的行。
                    doc_lines = value.value.splitlines()
                    while (end_line >= line
                           and not doc_lines[end_line - token.start[0]].strip()):
                        end_line -= 1
                    if token.start[0] < line <= end_line < token.end[0]:
                        old_text = "".join(original_lines[line - 1:end_line])
                        fixable = True
                    else:
                        reason = "参数范围与 docstring 引号所在行重叠"
                if set(entry.names) & real_args:
                    fixable = False
                    reason = "组合参数条目仍包含有效参数，需人工拆分"
                detail = "docstring 记载的参数 %s 不在函数签名中" % ", ".join(
                    repr(name) for name in extras)
                if not fixable:
                    detail += "；不可自动修复：" + reason
                findings.append(Finding(
                    path, line, "param-extra", node.name, detail, fixable,
                    old_text, "", end_line, _snapshot=snapshot))
            missing = sorted(real_args - documented - {"self", "cls"})
            if missing and has_section:
                findings.append(Finding(
                    path, node.lineno, "param-missing", node.name,
                    "参数 %s 未在 docstring 中说明" % ", ".join(map(repr, missing)),
                    _snapshot=snapshot))
        return findings
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError("分析失败: %s: %s" % (type(exc).__name__, exc)) from exc


def analyze_python_file(path: str) -> List[Finding]:
    path = os.path.abspath(path)
    return _analyze(path, _read_snapshot(path))


def analyze_todos(path: str) -> List[Finding]:
    path = os.path.abspath(path)
    snapshot = _read_snapshot(path)
    if not snapshot.source.strip():
        return []
    try:
        report = cs.scan_file(path, skip_tests=False)
        if report.skipped or not getattr(report, "complete", True):
            raise AnalysisError(report.skip_reason or "TODO 分析不完整")
        return [Finding(path, 0, "todo", "-", item) for item in report.todos]
    except Exception as exc:
        raise AnalysisError("TODO 分析失败: %s" % exc) from exc


def _collect(target: str, include_todos: bool, max_files: int,
             exclude: Optional[List[str]] = None) -> List[FileResult]:
    if not isinstance(max_files, int) or max_files <= 0:
        raise ValueError("--max-files 必须大于 0")
    target = os.path.abspath(target)
    if not (os.path.isfile(target) or os.path.isdir(target)):
        raise ValueError("路径不是可扫描的文件或目录: " + target)
    root = os.path.dirname(target) if os.path.isfile(target) else target
    reports = []
    paths = []

    def excluded(path, directory=False):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        return any(fnmatch.fnmatchcase(relative, pattern)
                   or (directory and fnmatch.fnmatchcase(relative + "/", pattern))
                   for pattern in (exclude or []))

    def eligible(path):
        return detect_language(path) == "Python" and not excluded(path)

    def walk_error(exc):
        reports.append(FileResult(os.path.abspath(exc.filename or root),
                                  status="failed", error="遍历失败: %s" % exc))

    if os.path.isfile(target):
        if eligible(target):
            paths.append(target)
    else:
        truncated = False
        try:
            for directory, dirs, files in os.walk(target, onerror=walk_error):
                dirs[:] = sorted(d for d in dirs
                                 if d not in SKIP_DIRS and not d.startswith(".")
                                 and not excluded(os.path.join(directory, d), True)
                                 and not os.path.islink(os.path.join(directory, d)))
                for name in sorted(files):
                    path = os.path.join(directory, name)
                    if not eligible(path):
                        continue
                    if len(paths) >= max_files:
                        reports.append(FileResult(path, status="truncated",
                                                  error="达到 --max-files，分析不完整"))
                        truncated = True
                        break
                    paths.append(path)
                if truncated:
                    break
        except OSError as exc:
            walk_error(exc)
    for path in sorted(set(paths)):
        report = FileResult(path)
        reports.append(report)
        try:
            report.findings = analyze_python_file(path)
            if include_todos:
                report.findings.extend(analyze_todos(path))
            if report.findings:
                report.status = "pending" if any(f.fixable for f in report.findings) else "manual"
        except Exception as exc:
            report.status, report.error = "failed", str(exc)
    return sorted(reports, key=lambda r: r.path)


def collect_findings(target: str, include_todos: bool = False,
                     max_files: int = 500,
                     exclude: Optional[List[str]] = None) -> List[Finding]:
    reports = _collect(target, include_todos, max_files, exclude)
    errors = [r.path + ": " + r.error for r in reports if r.status in {"failed", "truncated"}]
    if errors:
        raise AnalysisError("; ".join(errors))
    return [f for r in reports for f in r.findings]


def _candidate(items: List[Finding]) -> tuple:
    snapshot = items[0]._snapshot
    if snapshot is None:
        raise AnalysisError("缺少原始源码快照")
    lines = _lines(snapshot.source)
    removed = set()
    for finding in sorted(items, key=lambda f: (f.line, f.end_line)):
        if finding._snapshot != snapshot:
            raise AnalysisError("同文件诊断的快照不一致")
        if not (1 <= finding.line <= finding.end_line <= len(lines)):
            raise AnalysisError("删除范围无效")
        if "".join(lines[finding.line - 1:finding.end_line]) != finding.old_text:
            raise AnalysisError("删除范围与原始条目不一致")
        removed.update(range(finding.line - 1, finding.end_line))
    candidate = "".join(line for i, line in enumerate(lines) if i not in removed)
    ast.parse(candidate)
    raw = candidate.encode(snapshot.encoding)
    if raw == snapshot.raw:
        raise AnalysisError("候选未产生修改")
    return snapshot, raw


def _write_temp(path: str, raw: bytes, mode: int, suffix: str,
                created: List[str]) -> str:
    fd, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".stale.",
                                     suffix=suffix, dir=os.path.dirname(path))
    created.append(temporary)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    return temporary


def _safe_unlink(path: str) -> bool:
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _verify(path: str, backup: str) -> tuple:
    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safety_check.py")
    if not os.path.isfile(checker):
        return False, "未找到 safety_check.py"
    try:
        proc = subprocess.run(
            [sys.executable, checker, backup, path, "--quiet"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
        )
        output = (proc.stdout or "").strip()
        if proc.returncode == 0 and output == "SAFE":
            return True, "SAFE"
        detail = output or (proc.stderr or "").strip() or "无 SAFE 判定"
        return False, "校验失败（退出码 %s）: %s" % (proc.returncode, detail)
    except Exception as exc:
        return False, "校验器执行失败: %s: %s" % (type(exc).__name__, exc)


def _apply_file(report: FileResult) -> None:
    items = [f for f in report.findings if f.fixable and f.kind == "param-extra"
             and not f.applied]
    if not items or report.status in {"failed", "truncated"}:
        return
    created = []
    backup = ""
    committed = False
    try:
        snapshot, raw = _candidate(items)
        if _read_snapshot(report.path) != snapshot:
            raise AnalysisError("源文件已变化，未应用")
        backup = _write_temp(report.path, snapshot.raw, snapshot.mode, ".bak", created)
        temporary = _write_temp(report.path, raw, snapshot.mode, ".py", created)
        ok, detail = _verify(temporary, backup)
        if not ok:
            raise AnalysisError(detail)
        if (_read_snapshot(temporary).raw != raw
                or _read_snapshot(backup).raw != snapshot.raw):
            raise AnalysisError("校验期间候选或备份发生变化")
        if _read_snapshot(report.path) != snapshot:
            raise AnalysisError("源文件在提交前发生变化，未覆盖并发修改")
        os.replace(temporary, report.path)
        committed = True
        created.remove(temporary)
        for finding in items:
            finding.applied = True
        report.status = "partial" if any(not f.applied for f in report.findings) else "changed"
    except Exception as exc:
        report.status, report.error = "failed", str(exc)
    finally:
        for temporary in created:
            if temporary == backup and not committed:
                report.backup = backup
                report.retained_files.append(backup)
            elif not _safe_unlink(temporary):
                report.retained_files.append(temporary)
                if temporary == backup:
                    report.backup = backup


def _group(findings: List[Finding]) -> List[FileResult]:
    grouped = {}
    for finding in findings:
        grouped.setdefault(finding.path, FileResult(finding.path)).findings.append(finding)
    for report in grouped.values():
        if any(f.applied for f in report.findings):
            report.status = "partial" if any(not f.applied for f in report.findings) else "changed"
        else:
            report.status = "pending" if any(f.fixable for f in report.findings) else "manual"
    return [grouped[path] for path in sorted(grouped)]


def apply_findings(findings: List[Finding], verbose: bool = False) -> List[FileResult]:
    """返回真实逐文件结果；渲染报告时必须传递这些结果。"""
    reports = _group([f for f in findings if not f.applied])
    for report in reports:
        _apply_file(report)
        if verbose:
            print("%s: %s" % (report.path, report.status), file=sys.stderr)
        if report.error:
            print("ERROR: %s: %s%s" % (
                report.path, report.error,
                "；备份: " + report.backup if report.backup else ""), file=sys.stderr)
    return reports


def _report_data(findings: List[Finding], apply_requested: bool,
                 reports: List[FileResult]) -> dict:
    changed = [r.path for r in reports if any(f.applied for f in r.findings)]
    return {
        "apply_requested": apply_requested, "applied": bool(changed),
        "changed_files": changed,
        "failed_files": [r.path for r in reports if r.status in {"failed", "truncated"}],
        "complete": not any(r.status in {"failed", "truncated"} for r in reports),
        "total": len(findings), "remaining": sum(not f.applied for f in findings),
        "files": [r.to_dict() for r in reports],
        "findings": [f.to_dict() for f in findings],
    }


def render_json(findings: List[Finding], apply_requested: bool,
                reports: List[FileResult]) -> str:
    return json.dumps(_report_data(findings, apply_requested, reports),
                      ensure_ascii=False, indent=2)


def render_text(findings: List[Finding], apply_requested: bool,
                reports: List[FileResult], verbose: bool = False) -> str:
    failed = [r for r in reports if r.status in {"failed", "truncated"}]
    out = ["过期注释修正报告" if findings or failed else "未发现需要修正的过期注释。"]
    if verbose:
        out.extend("%s: %s" % (r.path, r.status) for r in reports)
    for finding in findings:
        state = "已修正" if finding.applied else "可自动修正" if finding.fixable else "需人工处理"
        out.append("%s:%d [%s] %s: %s（%s）" % (
            finding.path, finding.line, finding.kind, finding.symbol, finding.detail, state))
    for report in reports:
        if report.error:
            out.append("ERROR: %s: %s" % (report.path, report.error))
        if report.retained_files:
            out.append("保留文件: " + ", ".join(report.retained_files))
    if apply_requested:
        out.append("已修正 %d 个文件，失败 %d 个文件；剩余 %d 项。" % (
            sum(any(f.applied for f in r.findings) for r in reports), len(failed),
            sum(not f.applied for f in findings)))
    else:
        out.append("当前为 dry-run，未修改文件；确认后传入 --apply 才会备份、校验并写入。")
    return "\n".join(out)


def render_diff(findings: List[Finding]) -> str:
    out = []
    for report in _group(findings):
        items = [f for f in report.findings if f.fixable and f.kind == "param-extra"]
        if not items:
            continue
        snapshot, raw = _candidate(items)
        out.extend(difflib.unified_diff(
            _lines(snapshot.source), _lines(raw.decode(snapshot.encoding)),
            fromfile=report.path, tofile=report.path + " (修正后)", n=2))
    return "".join(out)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("必须是正整数")
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检测过期注释；默认 dry-run，仅 --apply 才会写入",
        epilog="退出码：0 无问题或全部修正 / 1 尚有诊断 / 2 输入错误 / 3 分析或修复失败")
    parser.add_argument("path", help="要检查的文件或目录")
    parser.add_argument("--apply", action="store_true", help="确认并应用可安全删除的参数条目")
    parser.add_argument("--diff", action="store_true", help="输出 unified diff 预览")
    parser.add_argument("--include-todos", action="store_true", help="同时报告 TODO/FIXME")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--max-files", type=_positive_int, default=500)
    parser.add_argument("--exclude", action="append", default=[],
                        help="排除相对扫描根的 POSIX glob，可重复")
    parser.add_argument("--verbose", action="store_true",
                        help="文本报告显示逐文件状态；JSON 始终包含这些状态")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not (os.path.isfile(args.path) or os.path.isdir(args.path)):
        print("错误：路径不存在或不是文件/目录 -> %s" % args.path, file=sys.stderr)
        return 2
    try:
        reports = _collect(args.path, args.include_todos, args.max_files, args.exclude)
    except Exception as exc:
        reports = [FileResult(os.path.abspath(args.path), status="failed", error=str(exc))]
    findings = [f for report in reports for f in report.findings]
    preview = ""
    if args.diff:
        for report in reports:
            if report.status in {"failed", "truncated"}:
                continue
            try:
                preview += render_diff(report.findings)
            except Exception as exc:
                report.status, report.error = "failed", "生成候选失败: %s" % exc
    if args.apply:
        for report in reports:
            _apply_file(report)
    if args.format == "json":
        data = _report_data(findings, args.apply, reports)
        if args.diff:
            data["diff"] = preview
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        text = render_text(findings, args.apply, reports, verbose=args.verbose)
        if preview:
            text += "\n\n修正 diff：\n" + preview
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    if any(report.status in {"failed", "truncated"} for report in reports):
        return 3
    return 1 if any(not f.applied for f in findings) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
