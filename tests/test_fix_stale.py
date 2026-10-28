#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_stale 专项测试：标准库、check 计数，可直接运行。"""

import codecs
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import comment_scanner as cs  # noqa: E402
import fix_stale as fs  # noqa: E402

PASS = FAIL = 0


def check(label, got, expect):
    global PASS, FAIL
    if got == expect:
        PASS += 1
        print("  [OK  ] %s" % label)
    else:
        FAIL += 1
        print("  [FAIL] %s\n         期望 %r\n         实际 %r" % (label, expect, got))


DOC = '''执行转账。

    Args:
        from_acct: 转出账户。
        to_acct: 转入账户。
        amount: 金额。
        currency: 币种。

    Returns:
        流水号。
    '''

DOC_NUMPY = '''执行转账。

    Parameters
    ----------
    from_acct : str
        转出账户。
    amount : int
        金额。
    currency : str
        币种。

    Returns
    -------
    str
        流水号。
    '''

SOURCE = '''def transfer(
    from_acct,
    to_acct,
    amount,
):
    """执行转账。

    Args:
        from_acct: 转出账户。
        to_acct: 转入账户。
        amount: 金额。
        currency: 币种（签名里已无此参数）。
            完整的多行说明。
            最后一行说明。
        legacy_flag: 已废弃参数。

    Raises:
        ValueError: 金额不合法。
            异常的补充说明。
    Returns:
        流水号。
    """
    return "ok"
'''

SMALL = '''def f(a):
    """Summary.

    Args:
        a: Keep.
        old: Remove.
            Remove the entire description.
    """
    return a
'''


def write(path, source=SOURCE):
    raw = source.encode("utf-8") if isinstance(source, str) else source
    with open(path, "wb") as stream:
        stream.write(raw)
    return raw


def read(path):
    with open(path, "rb") as stream:
        return stream.read()


def invoke(path, *args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = fs.main([path] + list(args))
        except SystemExit as exc:
            code = exc.code
    return code, stdout.getvalue(), stderr.getvalue()


def invoke_json(path, *args):
    code, stdout, stderr = invoke(path, "--format", "json", *args)
    return code, json.loads(stdout), stderr


def parameter_starts(doc):
    entries, _ = cs.parse_doc_parameters(doc)
    return {name: entry.start_line for entry in entries for name in entry.names}


def test_parser():
    print("\n=== 公共参数解析接口 ===")
    check("Google 风格", parameter_starts(DOC),
          {"from_acct": 4, "to_acct": 5, "amount": 6, "currency": 7})
    check("NumPy 风格", parameter_starts(DOC_NUMPY),
          {"from_acct": 5, "amount": 7, "currency": 9})
    entries, section = cs.parse_doc_parameters(
        "Parameters\n----------\na, b : int\n    First.\n    Last.\n"
        "c : str\n    C.\nRaises\n------\nValueError\n    Keep.\n")
    check("顶格 NumPy 章节", section, True)
    check("组合参数 names", entries[0].names, ("a", "b"))
    check("完整说明行范围", (entries[0].start_line, entries[0].end_line), (3, 5))
    check("Raises 不解析为参数", [e.names for e in entries], [("a", "b"), ("c",)])
    for header in ("Arguments", "Keyword Args"):
        check(header + " 参数章节", parameter_starts(header + ":\n    a: Description.\n"),
              {"a": 2})
    check("Other Parameters", parameter_starts("Other Parameters\n----------------\nx : int\n    X.\n"),
          {"x": 3})


def test_normal(tmp):
    print("\n=== 精确删除、dry-run、JSON 和幂等性 ===")
    path = os.path.join(tmp, "normal.py")
    original = write(path)
    findings = fs.analyze_python_file(path)
    extras = [f for f in findings if f.kind == "param-extra"]
    check("检出两条多余参数", len(extras), 2)
    check("多行签名仍可自动定位", [f.fixable for f in extras], [True, True])
    check("真实原始行号", extras[0].line, 12)
    check("完整多行条目结束行", extras[0].end_line, 14)
    check("old_text 包含全部说明", "最后一行说明。" in extras[0].old_text, True)
    expected = original
    for finding in extras:
        expected = expected.replace(finding.old_text.encode("utf-8"), b"")
    before_files = sorted(os.listdir(tmp))
    code, text, _ = invoke(path, "--diff")
    check("dry-run 返回 1", code, 1)
    check("dry-run 提示确认", "dry-run" in text and "--apply" in text, True)
    check("diff 包含删除的说明", "-            最后一行说明。" in text, True)
    check("dry-run 源码不变", read(path), original)
    check("dry-run 不创建备份或临时文件", sorted(os.listdir(tmp)), before_files)
    code, data, _ = invoke_json(path, "--diff", "--verbose")
    check("dry-run JSON 状态", (code, data["apply_requested"], data["applied"]), (1, False, False))
    check("JSON diff 不混入 stdout", "diff" in data, True)
    check("dry-run 文件状态", data["files"][0]["status"], "pending")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    code, data, stderr = invoke_json(path, "--apply", "--verbose")
    check("apply 成功退出 0", code, 0)
    check("JSON 真实应用状态", (data["apply_requested"], data["applied"]), (True, True))
    check("JSON 修改文件列表", data["changed_files"], [path])
    check("JSON 失败文件列表", data["failed_files"], [])
    check("JSON 逐文件状态", data["files"][0]["status"], "changed")
    check("JSON 逐条实际应用状态", [f["applied"] for f in data["findings"]], [True, True])
    check("JSON 无人读日志", stderr, "")
    check("仅删除完整参数条目", read(path), expected)
    check("权限不变", stat.S_IMODE(os.stat(path).st_mode), mode)
    check("本次临时文件均清理", sorted(os.listdir(tmp)), before_files)
    after = read(path)
    code, data, _ = invoke_json(path, "--apply")
    check("再次 apply 幂等", (code, data["applied"], data["changed_files"], data["total"]),
          (0, False, [], 0))
    check("再次运行字节不变", read(path), after)


def test_numpy(tmp):
    print("\n=== NumPy 顶格、组合条目和 Raises ===")
    for indent in ("", "    "):
        path = os.path.join(tmp, "numpy%s.py" % len(indent))
        doc_lines = ["Parameters", "----------", "a : int", "    Keep a.",
                     "old : str", "    Remove first.", "    Remove last.",
                     "Other Parameters", "----------------", "older, oldest : int",
                     "    Remove both.", "Raises", "------", "ValueError", "    Keep error."]
        source = 'def f(a):\n    """Summary.\n\n' + "\n".join(indent + s for s in doc_lines)
        source += '\n    """\n    return a\n'
        original = write(path, source)
        findings = fs.analyze_python_file(path)
        check("NumPy %s 条目可修正" % len(indent), [f.fixable for f in findings], [True, True])
        expected = original
        for finding in findings:
            expected = expected.replace(finding.old_text.encode("utf-8"), b"")
        code, data, _ = invoke_json(path, "--apply")
        check("NumPy %s 整条删除" % len(indent), (code, read(path)), (0, expected))
        check("NumPy %s 保留 Raises" % len(indent), b"ValueError\n" in read(path), True)
    path = os.path.join(tmp, "combined.py")
    original = write(path, 'def f(a):\n    """Summary.\n\nParameters\n----------\n'
                     'a, old : int\n    Shared description.\n    """\n    return a\n')
    code, data, _ = invoke_json(path, "--apply")
    check("组合条目含有效参数只能人工处理", (code, data["applied"], data["files"][0]["status"]),
          (1, False, "manual"))
    check("组合条目完全保留", read(path), original)


def test_encoding(tmp):
    print("\n=== 编码、换行及字面量边界 ===")
    path = os.path.join(tmp, "bom.py")
    original = write(path, codecs.BOM_UTF8 + SOURCE.replace("\n", "\r\n").encode("utf-8"))
    findings = fs.analyze_python_file(path)
    expected = original
    for finding in findings:
        expected = expected.replace(finding.old_text.encode("utf-8"), b"")
    code, _, _ = invoke_json(path, "--apply")
    check("BOM/CRLF apply", code, 0)
    check("BOM/CRLF 完全保留", read(path), expected)
    check("无混入 LF", b"\n" in read(path).replace(b"\r\n", b""), False)
    path = os.path.join(tmp, "latin1.py")
    original = write(path, ("# coding: latin-1\n" + SMALL.replace("Summary.", "Résumé.")).encode("latin-1"))
    expected = original.replace(b"        old: Remove.\n            Remove the entire description.\n", b"")
    _, candidate = fs._candidate(fs.analyze_python_file(path))
    check("内存候选完整保留声明编码", candidate, expected)
    code, data, _ = invoke_json(path, "--apply")
    check("声明编码保留（%s）" % data["files"][0]["error"], (code, read(path)), (0, expected))
    for name, source in (
        ("raw", SMALL.replace('"""Summary.', 'r"""Summary.')),
        ("unicode", SMALL.replace('"""Summary.', 'u"""Summary.')),
        ("single", SMALL.replace('"""', "'''")),
        ("unicode_before", "# Unicode separator: \u2028 remains a physical line.\n" + SMALL),
        ("async", SMALL.replace("def f(a):", "async def f(a):")),
    ):
        path = os.path.join(tmp, name + ".py")
        write(path, source)
        code, _, _ = invoke_json(path, "--apply")
        check(name + " 精确修正", (code, b"old:" not in read(path)), (0, True))
    refused = {
        "escape": SMALL.replace("Remove.", r"Remove.\n            Escaped line."),
        "backslash": SMALL.replace("Summary.", r"Summary.\\path"),
        "concat": SMALL.replace('"""Summary.', '"prefix" """Summary.'),
        "multiline_concat": SMALL.replace('"""Summary.', '("prefix"\n     """Summary.').replace('    """\n', '    """)\n'),
        "same_line": SMALL.replace('    """\n', '    """; x = 1\n'),
        "comment_line": SMALL.replace('    """\n', '    """  # keep\n'),
        "inline_open": SMALL.replace('def f(a):\n    """', 'def f(a): """'),
        "closing_entry": SMALL.replace('description.\n    """', 'description."""'),
    }
    for name, source in refused.items():
        path = os.path.join(tmp, name + ".py")
        original = write(path, source)
        # 同行函数体不能在随后恢复缩进，保留一个合法单语句函数。
        if name == "inline_open":
            original = write(path, source.replace("    return a\n", ""))
        code, data, _ = invoke_json(path, "--apply")
        check(name + " 保守拒绝", (code, data["applied"], data["total"] > 0), (1, False, True))
        check(name + " 源码不变", read(path), original)


def test_reports(tmp):
    print("\n=== 仅报告诊断及错误退出码 ===")
    path = os.path.join(tmp, "missing.py")
    original = write(path, SMALL.replace("def f(a):", "def f(a, b):").replace(
        "        old: Remove.\n            Remove the entire description.\n", ""))
    for args in ((), ("--apply",)):
        code, data, _ = invoke_json(path, *args)
        check("missing 返回 1 %r" % (args,), (code, data["applied"], data["findings"][0]["kind"]),
              (1, False, "param-missing"))
        check("missing 不填占位", read(path), original)
    path = os.path.join(tmp, "empty_section.py")
    write(path, 'def f(a):\n    """Summary.\n\n    Args:\n    """\n    return a\n')
    code, data, _ = invoke_json(path)
    check("空 Args 章节仍报告 missing", (code, data["findings"][0]["kind"]), (1, "param-missing"))
    path = os.path.join(tmp, "todo.py")
    original = write(path, "# TODO: implement caching\nx = 1\n")
    code, data, _ = invoke_json(path, "--apply", "--include-todos")
    check("TODO 返回 1 且不修改", (code, data["applied"], read(path)), (1, False, original))
    check("TODO 类型", data["findings"][0]["kind"], "todo")
    with mock.patch.object(cs, "scan_file", side_effect=RuntimeError("TODO scan failed")):
        code, data, _ = invoke_json(path, "--include-todos")
    check("TODO 分析异常不可静默忽略", (code, data["complete"]), (3, False))
    path = os.path.join(tmp, "partial.py")
    write(path, SMALL.replace("def f(a):", "def f(a, b):"))
    code, data, _ = invoke_json(path, "--apply")
    check("部分修正仍返回 1", (code, data["applied"], data["remaining"], data["files"][0]["status"]),
          (1, True, 1, "partial"))
    for name, raw in (("syntax", b"def broken(:\n"), ("decode", b"# coding: utf-8\n\xff"),
                      ("invalid_ast", b"return 1\n")):
        path = os.path.join(tmp, name + ".py")
        write(path, raw)
        code, data, _ = invoke_json(path, "--apply")
        check(name + " 错误不能静默跳过", (code, data["failed_files"], data["applied"]),
              (3, [path], False))
        check(name + " 原始字节不变", read(path), raw)
    path = os.path.join(tmp, "large.py")
    write(path, SMALL)
    with mock.patch.object(fs, "MAX_FILE_BYTES", 8):
        code, data, _ = invoke_json(path)
    check("大小限制失败返回 3", (code, data["failed_files"]), (3, [path]))
    real_open = open

    def unreadable(name, *args, **kwargs):
        if os.fspath(name) == path:
            raise PermissionError("injected read failure")
        return real_open(name, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=unreadable):
        code, data, _ = invoke_json(path)
    check("读取失败返回 3", (code, data["files"][0]["status"]), (3, "failed"))
    for limit in ("0", "-1", "x"):
        code, _, _ = invoke(path, "--max-files", limit)
        check("非法 max-files " + limit, code, 2)
    code, _, _ = invoke(os.path.join(tmp, "not-found.py"))
    check("不存在的输入返回 2", code, 2)


def test_transactions(tmp):
    print("\n=== 逐文件事务与失败关闭 ===")
    path = os.path.join(tmp, "transaction.py")
    old_backup = path + ".stale.bak"
    write(old_backup, b"pre-existing backup")
    write(path, SMALL)
    code, data, _ = invoke_json(path, "--apply")
    check("已有固定备份不妨碍修正", code, 0)
    check("已有备份永不覆盖", read(old_backup), b"pre-existing backup")
    write(path, SMALL)
    findings = fs.analyze_python_file(path)
    with contextlib.redirect_stderr(io.StringIO()):
        results = fs.apply_findings(findings + findings)
    check("重复诊断去重删除", ([r.status for r in results], b"old:" not in read(path)),
          (["changed"], True))
    check("同批诊断再次应用无修改", fs.apply_findings(findings), [])
    original = write(path, SMALL)
    findings = fs.analyze_python_file(path)
    with mock.patch.object(fs, "_verify", return_value=(False, "injected rejection")):
        with contextlib.redirect_stderr(io.StringIO()):
            results = fs.apply_findings(findings)
    data = json.loads(fs.render_json(findings, True, results))
    check("API 报告保留实际失败", (data["complete"], data["failed_files"], data["files"][0]["status"]),
          (False, [path], "failed"))
    check("API 失败不可显示已应用", (data["applied"], data["changed_files"], read(path)),
          (False, [], original))
    check("API 文本保留失败原因", "injected rejection" in fs.render_text(findings, True, results), True)
    real_verify = fs._verify
    observed = []

    def inspect_candidate(candidate, backup):
        observed.append(read(path) == SMALL.encode("utf-8"))
        observed.append(os.path.dirname(candidate) == os.path.dirname(path))
        observed.append(candidate.endswith(".py"))
        observed.append(read(backup) == read(path))
        return real_verify(candidate, backup)

    write(path, SMALL)
    with mock.patch.object(fs, "_verify", side_effect=inspect_candidate):
        code, _, _ = invoke_json(path, "--apply")
    check("验证候选而非已写源文件", (code, observed), (0, [True] * 4))
    cases = (
        ("timeout", subprocess.TimeoutExpired("checker", 60)),
        ("startup", OSError("cannot start checker")),
        ("exception", RuntimeError("checker exception")),
    )
    for name, error in cases:
        original = write(path, SMALL)
        with mock.patch.object(fs.subprocess, "run", side_effect=error):
            code, data, _ = invoke_json(path, "--apply", "--verbose")
        check(name + " 校验失败", (code, data["applied"], data["changed_files"], data["failed_files"]),
              (3, False, [], [path]))
        check(name + " 不修改源码", read(path), original)
        backup = data["files"][0]["backup"]
        check(name + " 保留唯一备份", bool(backup) and backup != old_backup and read(backup) == original, True)
    real_isfile = os.path.isfile

    def checker_missing(name):
        return False if os.path.basename(name) == "safety_check.py" else real_isfile(name)

    original = write(path, SMALL)
    with mock.patch.object(fs.os.path, "isfile", side_effect=checker_missing):
        code, data, _ = invoke_json(path, "--apply")
    check("校验器缺失返回 3", (code, data["applied"], read(path)), (3, False, original))
    for status, stdout in ((1, "UNSAFE"), (2, "input error"), (3, "UNVERIFIED"),
                           (7, "SAFE"), (0, ""), (0, "UNVERIFIED")):
        original = write(path, SMALL)
        proc = subprocess.CompletedProcess([], status, stdout, "")
        with mock.patch.object(fs.subprocess, "run", return_value=proc):
            code, data, _ = invoke_json(path, "--apply")
        check("仅 0 SAFE 可提交 %r" % ((status, stdout),),
              (code, data["applied"], read(path)), (3, False, original))
    original = write(path, SMALL)
    with mock.patch.object(fs.os, "replace", side_effect=PermissionError("replace failed")):
        code, data, _ = invoke_json(path, "--apply")
    check("replace 失败原文件不变", (code, data["applied"], read(path)), (3, False, original))
    check("replace 失败保留备份", read(data["files"][0]["backup"]), original)
    real_fsync = fs.os.fsync
    calls = []

    def fail_candidate_write(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("candidate write failed")
        return real_fsync(fd)

    original = write(path, SMALL)
    before = set(os.listdir(tmp))
    with mock.patch.object(fs.os, "fsync", side_effect=fail_candidate_write):
        code, data, _ = invoke_json(path, "--apply")
    check("候选写入失败不改原文件", (code, data["applied"], read(path)), (3, False, original))
    check("候选写入失败仅保留本次备份", set(os.listdir(tmp)) - before,
          {os.path.basename(data["files"][0]["backup"])})
    before = set(os.listdir(tmp))
    with mock.patch.object(fs.os, "fsync", side_effect=OSError("backup write failed")):
        code, data, _ = invoke_json(path, "--apply")
    check("备份写入失败不改原文件", (code, read(path)), (3, original))
    check("失败的不完整备份已清理", set(os.listdir(tmp)), before)
    with mock.patch.object(fs.tempfile, "mkstemp", side_effect=OSError("no temporary file")):
        code, data, _ = invoke_json(path, "--apply")
    check("临时文件创建失败可见", (code, data["failed_files"]), (3, [path]))
    write(path, SMALL)
    stale_findings = fs.analyze_python_file(path)
    concurrent = write(path, SMALL + "# concurrent edit\n")
    with contextlib.redirect_stderr(io.StringIO()):
        result = fs.apply_findings(stale_findings)
    check("分析后并发修改不覆盖", ([r.status for r in result], read(path)), (["failed"], concurrent))

    def concurrent_edit(candidate, backup):
        result = real_verify(candidate, backup)
        write(path, SMALL + "# edited while verifying\n")
        return result

    write(path, SMALL)
    with mock.patch.object(fs, "_verify", side_effect=concurrent_edit):
        code, data, _ = invoke_json(path, "--apply")
    check("提交前再次校验源码快照", (code, data["applied"], read(path)),
          (3, False, (SMALL + "# edited while verifying\n").encode("utf-8")))

    def altered_candidate(candidate, backup):
        result = real_verify(candidate, backup)
        write(candidate, "x = 2\n")
        return result

    original = write(path, SMALL)
    with mock.patch.object(fs, "_verify", side_effect=altered_candidate):
        code, data, _ = invoke_json(path, "--apply")
    check("校验后候选篡改不提交", (code, read(path)), (3, original))
    check("固定备份始终不被删除", read(old_backup), b"pre-existing backup")


def test_selection(tmp):
    print("\n=== Python 候选额度、排除及逐文件汇总 ===")
    root = os.path.join(tmp, "selection")
    os.mkdir(root)
    sub = os.path.join(root, "nested")
    os.mkdir(sub)
    write(os.path.join(root, "00.txt"), "not Python")
    write(os.path.join(root, "01.js"), "const x = 1;")
    first = os.path.join(root, "a.py")
    second = os.path.join(root, "b.py")
    nested = os.path.join(sub, "c.py")
    for path in (first, second, nested):
        write(path, SMALL)
    code, data, _ = invoke_json(root, "--max-files", "1")
    check("非 Python 不占额度", data["findings"][0]["path"], first)
    check("额度截断明确标记不完整", (code, data["complete"], data["failed_files"]), (3, False, [second]))
    check("截断文件不进行分析", [(r["path"], r["status"]) for r in data["files"]],
          [(first, "pending"), (second, "truncated")])
    code, data, _ = invoke_json(root, "--exclude", "a.py", "--exclude", "nested/*.py")
    check("重复相对 POSIX glob 排除", [r["path"] for r in data["files"]], [second])
    for pattern in ("nested", "nested/", "nested/*"):
        code, data, _ = invoke_json(root, "--exclude", pattern)
        check("目录排除 " + pattern, [r["path"] for r in data["files"]], [first, second])
    code, data, _ = invoke_json(root, "--max-files", "1", "--exclude", "b.py", "--exclude", "nested")
    check("额度正好用完无漏扫时保持完整", (code, data["complete"]), (1, True))
    code, data, _ = invoke_json(first, "--exclude", "a.py")
    check("单文件以父目录为匹配根", (code, data["files"]), (0, []))
    real_replace = os.replace

    def replace_one(source, destination):
        if destination == second:
            raise PermissionError("only b.py fails")
        return real_replace(source, destination)

    with mock.patch.object(fs.os, "replace", side_effect=replace_one):
        code, data, _ = invoke_json(root, "--apply", "--exclude", "nested/*")
    check("跨文件部分失败返回 3", (code, data["applied"], data["changed_files"], data["failed_files"]),
          (3, True, [first], [second]))
    check("跨文件实际状态", [r["status"] for r in data["files"]], ["changed", "failed"])

    def unreadable_walk(target, onerror):
        onerror(PermissionError(13, "directory denied", target))
        return iter(())

    with mock.patch.object(fs.os, "walk", side_effect=unreadable_walk):
        code, data, _ = invoke_json(root)
    check("目录遍历失败报告不完整", (code, data["complete"], data["failed_files"]), (3, False, [root]))


def test_entrypoints(tmp):
    print("\n=== 实际 CLI 与 import main guard ===")
    path = os.path.join(tmp, "cli.py")
    write(path, SMALL)
    result = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fix_stale.py"), path,
                             "--apply", "--format", "json", "--verbose"],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    data = json.loads(result.stdout)
    check("真实子进程 CLI 可修复", (result.returncode, data["applied"]), (0, True))
    program = ("import importlib.util; s=importlib.util.spec_from_file_location('fix_tests', %r); "
               "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)" % __file__)
    result = subprocess.run([sys.executable, "-S", "-c", program], capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    check("import 测试模块不执行或退出", (result.returncode, result.stdout, result.stderr), (0, "", ""))


def main():
    global PASS, FAIL
    PASS = FAIL = 0
    print("fix_stale 专项测试")
    test_parser()
    with tempfile.TemporaryDirectory(prefix="fixstale-") as tmp:
        test_normal(tmp)
        test_numpy(tmp)
        test_encoding(tmp)
        test_reports(tmp)
        test_transactions(tmp)
        test_selection(tmp)
        test_entrypoints(tmp)
    print("\n通过 %d 项，失败 %d 项" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
