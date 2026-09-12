#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smart-code-commenter 端到端自测。

零依赖，直接运行：
    python tests/test_skill.py
    python -m pytest tests/ -q          # 若已安装 pytest

覆盖范围：
- 语言探测（含 .bak 备份文件名这一历史 bug）
- 文档注释识别（JSDoc / Go / Rust / Java / C# 等的差异化规则）
- 多语言符号解析（重点覆盖旧版符号恒为 0 的语言）
- Python AST 与降级路径
- 注释行统计（字符串内的注释符不应被误判）
- 覆盖率计算口径（私有符号、测试文件）
- safety_check 的 SAFE/UNSAFE 判定（含语法错误文件的 docstring 场景）
- 两个脚本的 CLI 契约（退出码）

退出码：0 全部通过；1 有失败项。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import comment_scanner as cs          # noqa: E402
import safety_check as sc             # noqa: E402
import langspec as ls                 # noqa: E402

_PASS = 0
_FAIL = 0
_FAILURES = []


def check(label: str, got, expect) -> None:
    """断言并记录结果（而非抛异常，保证一次跑完所有用例）。"""
    global _PASS, _FAIL
    if got == expect:
        _PASS += 1
        print("  [OK  ] %s" % label)
    else:
        _FAIL += 1
        _FAILURES.append(label)
        print("  [FAIL] %s\n         期望: %r\n         实际: %r" % (label, expect, got))


def section(title: str) -> None:
    print("\n=== %s ===" % title)


def symbols_of(source: str, language: str):
    """辅助：对给定源码跑通用符号扫描，返回 [(name, documented)]。"""
    rep = cs.FileReport(path="sample", language=language)
    cs.scan_generic(source, rep)
    return [(s.name, s.documented) for s in rep.symbols]


# ---------------------------------------------------------------------------
# 1. 语言探测
# ---------------------------------------------------------------------------

def test_language_detection() -> None:
    section("语言探测")
    cases = [
        ("app.py", "Python"),
        ("app.js", "JavaScript"),
        ("app.tsx", "TypeScript"),
        ("Main.java", "Java"),
        ("main.go", "Go"),
        ("lib.rs", "Rust"),
        ("app.cs", "C#"),
        ("App.kt", "Kotlin"),
        ("index.php", "PHP"),
        ("task.rb", "Ruby"),
        ("deploy.sh", "Shell"),
        ("init.ps1", "PowerShell"),
        ("query.sql", "SQL"),
        ("mod.lua", "Lua"),
        ("analysis.r", "R"),
        ("main.swift", "Swift"),
        ("app.dart", "Dart"),
        # 历史 bug：备份文件名必须能推断出真实语言
        ("app.py.commenter.bak", "Python"),
        ("app.js.commenter.bak", "JavaScript"),
        ("service.ts.bak", "TypeScript"),
        ("main.go.orig", "Go"),
        # 文件名惯例
        ("Dockerfile", "Shell"),
        ("Makefile", "Shell"),
        ("Rakefile", "Ruby"),
        # 无法判定
        ("data.xyz", "Unknown"),
    ]
    for path, expect in cases:
        check("detect_language(%s)" % path, ls.detect_language(path), expect)


# ---------------------------------------------------------------------------
# 2. 文档注释识别
# ---------------------------------------------------------------------------

def test_doc_comment_detection() -> None:
    section("文档注释识别")
    js = [
        ("JSDoc 块", "/**\n * 描述\n */\nfunction a() {}\n", True),
        ("JSDoc 与函数间夹空行", "/**\n * 描述\n */\n\nfunction b() {}\n", True),
        ("JSDoc 后跟一行普通注释（旧版误判）",
         "/**\n * 描述\n */\n// 补充说明\nfunction c() {}\n", True),
        ("无任何注释", "function d() {}\n", False),
        ("孤立极短行注释", "// hi\nfunction e() {}\n", False),
        ("普通实现注释长行（不应算文档）",
         "// 这是一段足够长的说明文字用来测试阈值判断逻辑\nfunction f() {}\n", False),
    ]
    for label, src, expect in js:
        got = symbols_of(src, "JavaScript")
        check("JS: %s" % label, got[0][1] if got else None, expect)

    go = [
        ("Go 单行 // 即文档注释", "// Foo does things.\nfunc Foo() {}\n", True),
        ("Go 多行文档注释",
         "// Foo does things.\n//\n// More detail here.\nfunc Foo() {}\n", True),
    ]
    for label, src, expect in go:
        got = symbols_of(src, "Go")
        check("Go: %s" % label, got[0][1] if got else None, expect)

    others = [
        ("Rust", "/// 描述\npub fn a() {}\n", True),
        ("Rust", "// 内部说明\npub fn b() {}\n", False),
        ("Java", "/**\n * 描述\n */\npublic void m() {}\n", True),
        ("Java", "// 内部说明\npublic void n() {}\n", False),
        ("C#", "/// 描述\npublic void O() {}\n", True),
        ("Kotlin", "/**\n * 描述\n */\nfun a() {}\n", True),
        ("C++", "/// 描述\nvoid p() {}\n", True),
        ("C++", "/**\n * @brief 描述\n */\nvoid q() {}\n", True),
    ]
    for lang, src, expect in others:
        got = symbols_of(src, lang)
        check("%s: %s" % (lang, "有注释" if expect else "无注释"),
              got[0][1] if got else None, expect)


# ---------------------------------------------------------------------------
# 3. 多语言符号解析（重点：旧版符号恒为 0 的语言）
# ---------------------------------------------------------------------------

def test_symbol_extraction() -> None:
    section("多语言符号解析")
    cases = [
        ("Ruby", "def greet(name)\n  puts name\nend\n", ["greet"]),
        ("Lua", "function greet(name)\n  print(name)\nend\n", ["greet"]),
        ("R", "greet <- function(name) {\n  print(name)\n}\n", ["greet"]),
        ("Shell", "greet() {\n  echo hi\n}\n", ["greet"]),
        ("PowerShell", "function Greet($name) {\n  Write-Host $name\n}\n", ["Greet"]),
        ("SQL", "CREATE PROCEDURE get_users AS\nSELECT 1\n", ["get_users"]),
        ("Perl", "sub greet { my $n = shift; }\n", ["greet"]),
        ("Scala", "def greet(name: String): Unit = println(name)\n", ["greet"]),
        ("Swift", "func greet(name: String) { }\n", ["greet"]),
        ("PHP", "function greet($name) { }\n", ["greet"]),
        ("Kotlin", "fun greet(name: String) { }\n", ["greet"]),
        ("C#", "public void Greet(string name) { }\n", ["Greet"]),
        ("Rust", "pub fn greet(name: &str) { }\n", ["greet"]),
        ("Go", "func Greet(name string) { }\n", ["Greet"]),
        ("Java", "public void greet(String name) { }\n", ["greet"]),
        ("JavaScript", "export function greet(name) { }\n", ["greet"]),
        ("JavaScript", "const greet = (name) => { };\n", ["greet"]),
        ("TypeScript", "export interface User { }\n", ["User"]),
    ]
    for lang, src, expect in cases:
        rep = cs.FileReport(path="sample", language=lang)
        cs.scan_generic(src, rep)
        check("%s 符号名" % lang, [s.name for s in rep.symbols], expect)


# ---------------------------------------------------------------------------
# 4. Python 的 AST 与降级路径
# ---------------------------------------------------------------------------

def test_python_analysis() -> None:
    section("Python AST 分析")
    src = (
        'def public_api(a, b=1):\n'
        '    """做点事情。\n\n'
        '    Args:\n'
        '        a: 第一个参数。\n'
        '        b: 第二个参数。\n'
        '    """\n'
        '    return a + b\n\n\n'
        'def _private(x):\n'
        '    return x\n\n\n'
        'class Public:\n'
        '    """类说明。"""\n\n'
        '    def method(self):\n'
        '        return 1\n\n\n'
        'def test_something():\n'
        '    assert True\n'
    )
    rep = cs.FileReport(path="sample.py", language="Python")
    cs.scan_python_ast(src, rep)
    by_name = {s.name: s for s in rep.symbols}
    check("AST 解析模式", rep.parse_mode, "ast")
    check("public_api 有文档", by_name["public_api"].documented, True)
    check("_private 记为半私有", by_name["_private"].visibility, "semiprivate")
    check("_private 无文档", by_name["_private"].documented, False)
    check("Public 类有文档", by_name["Public"].documented, True)
    check("method 无文档", by_name["method"].documented, False)
    check("test_ 前缀识别为测试", by_name["test_something"].is_test, True)

    # 覆盖率口径
    check("默认含私有符号 → 4 个",
          len(rep.counted_symbols(True, False)), 4)
    check("排除私有符号 → 3 个",
          len(rep.counted_symbols(False, False)), 3)
    check("默认不含测试 → 覆盖率 50.0",
          rep.doc_coverage(True, False), 50.0)

    section("Python 降级路径（语法错误）")
    broken = "def parse_config(path)\n    return {}\n"
    rep2 = cs.FileReport(path="broken.py", language="Python")
    ok = cs.scan_python_ast(broken, rep2)
    check("AST 解析返回 False", ok, False)
    cs.scan_python_fallback(broken, rep2)
    check("降级后仍提取到符号", [s.name for s in rep2.symbols], ["parse_config"])
    check("降级告警已记录", len(rep2.warnings) > 0, True)


# ---------------------------------------------------------------------------
# 5. docstring 参数漂移检测
# ---------------------------------------------------------------------------

def test_doc_drift() -> None:
    section("过期 docstring 检测")
    src = (
        'def f(a, b):\n'
        '    """摘要。\n\n'
        '    Args:\n'
        '        a: 第一个。\n'
        '        b: 第二个。\n'
        '        c: 不存在的参数。\n'
        '    """\n'
        '    return a + b\n'
    )
    rep = cs.FileReport(path="x.py", language="Python")
    cs.scan_python_ast(src, rep)
    joined = " ".join(rep.warnings)
    check("检出多余参数 c", "'c'" in joined, True)

    src2 = (
        'def g(a, b):\n'
        '    """摘要。\n\n'
        '    Args:\n'
        '        a: 第一个。\n'
        '    """\n'
        '    return a + b\n'
    )
    rep2 = cs.FileReport(path="x.py", language="Python")
    cs.scan_python_ast(src2, rep2)
    check("检出漏写参数 b", "'b'" in " ".join(rep2.warnings), True)


# ---------------------------------------------------------------------------
# 6. 注释行统计（字符串感知）
# ---------------------------------------------------------------------------

def test_line_counting() -> None:
    section("注释行统计")
    src = (
        'url = "http://example.com"   # 行尾注释\n'
        '# 独立注释行\n'
        'name = "has // slashes in string"\n'
        '\n'
        'x = 1\n'
    )
    rep = cs.FileReport(path="x.py", language="Python")
    cs.count_lines(src, rep)
    check("注释行数（字符串内 // 不应计入）", rep.comment_lines, 2)
    check("代码行数", rep.code_lines, 3)
    check("空行数", rep.blank_lines, 1)

    # 块注释跨行
    js = "/**\n * 第一行\n * 第二行\n */\nconst a = 1;\n"
    rep2 = cs.FileReport(path="x.js", language="JavaScript")
    cs.count_lines(js, rep2)
    check("JS 块注释 4 行", rep2.comment_lines, 4)
    check("JS 代码行 1 行", rep2.code_lines, 1)

    # TODO 采集
    todos = "// TODO: 重构这段\n// FIXME: 修 bug\nconst a = 1;\n"
    rep3 = cs.FileReport(path="x.js", language="JavaScript")
    cs.count_lines(todos, rep3)
    check("采集到 2 条 TODO/FIXME", len(rep3.todos), 2)


# ---------------------------------------------------------------------------
# 7. safety_check 判定
# ---------------------------------------------------------------------------

def test_safety_check() -> None:
    section("安全校验判定")
    # 纯注释改动 → SAFE
    check("JS 新增 JSDoc → SAFE",
          sc.compare("function f(){}\n", "/** 说明 */\nfunction f(){}\n",
                     ".js", False)[0], "SAFE")
    # 逻辑改动 → UNSAFE
    check("JS 改逻辑 → UNSAFE",
          sc.compare("x = 1; // c\n", "x = 2; // c\n", ".js", False)[0], "UNSAFE")
    # Python docstring 改动 → SAFE
    check("Python docstring 改动 → SAFE",
          sc.compare('def f():\n    pass\n',
                     'def f():\n    """说明。"""\n    pass\n',
                     ".py", False)[0], "SAFE")
    check("Python 改逻辑 → UNSAFE",
          sc.compare("def f():\n    return 1\n",
                     "def f():\n    return 2\n", ".py", False)[0], "UNSAFE")
    # 关键回归：语法错误文件 + docstring 新增，必须判 SAFE
    broken_old = "def parse_config(path)\n    return {}\n"
    broken_new = (
        '"""配置解析模块。"""\n'
        "def parse_config(path)\n"
        '    """解析配置。\n\n'
        '    Args:\n'
        '        path: 文件路径。\n'
        '    """\n'
        "    return {}\n"
    )
    check("语法错误文件 + 新增 docstring → SAFE",
          sc.compare(broken_old, broken_new, ".py", False)[0], "SAFE")
    # 语法错误文件 + 改逻辑 → UNSAFE
    check("语法错误文件 + 改逻辑 → UNSAFE",
          sc.compare(broken_old,
                     "def parse_config(path)\n    return [1]\n",
                     ".py", False)[0], "UNSAFE")
    # 语言探测兜底：用真实文件名而非扩展名
    check("备份文件名 .commenter.bak 也能识别语言",
          ls.detect_language("app.js.commenter.bak"), "JavaScript")
    # 通用语言字符串内的注释符
    check("字符串内 // 不误判为注释",
          sc.compare('a = "http://x";\n', 'a = "http://x";\n// c\n',
                     ".js", False)[0], "SAFE")


# ---------------------------------------------------------------------------
# 8. CLI 契约
# ---------------------------------------------------------------------------

def test_cli() -> None:
    section("CLI 退出码契约")
    tmp = tempfile.mkdtemp(prefix="scc-test-")
    try:
        doc_path = os.path.join(tmp, "documented.py")

        with open(doc_path, "w", encoding="utf-8") as f:
            f.write('"""模块说明。"""\n\n\n'
                    'def foo(a):\n'
                    '    """做事情。\n\n'
                    '    Args:\n'
                    '        a: 参数。\n'
                    '    """\n'
                    '    return a\n')

        py = sys.executable
        scan = os.path.join(SCRIPTS, "comment_scanner.py")
        guard = os.path.join(SCRIPTS, "safety_check.py")

        def run(args):
            p = subprocess.run([py] + args, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            return p.returncode

        check("扫描存在路径 → 0", run([scan, doc_path, "--quiet"]), 0)
        check("扫描不存在路径 → 2",
              run([scan, os.path.join(tmp, "nope.py")]), 2)
        check("门禁 0% → 0", run([scan, doc_path, "--quiet", "--min-coverage", "0"]), 0)

        # 全无注释文件应低于 90%
        bare = os.path.join(tmp, "bare.py")
        with open(bare, "w", encoding="utf-8") as f:
            f.write("def foo():\n    return 1\n")
        check("无注释文件 + 90% 门禁 → 1",
              run([scan, bare, "--quiet", "--min-coverage", "90"]), 1)

        # safety_check 退出码
        old = os.path.join(tmp, "old.py")
        new_ok = os.path.join(tmp, "new_ok.py")
        new_bad = os.path.join(tmp, "new_bad.py")
        with open(old, "w", encoding="utf-8") as f:
            f.write("def f():\n    return 1\n")
        with open(new_ok, "w", encoding="utf-8") as f:
            f.write('def f():\n    """说明。"""\n    return 1\n')
        with open(new_bad, "w", encoding="utf-8") as f:
            f.write("def f():\n    return 2\n")

        check("SAFE → 0", run([guard, old, new_ok]), 0)
        check("UNSAFE → 1", run([guard, old, new_bad]), 1)
        check("文件不存在 → 2",
              run([guard, old, os.path.join(tmp, "nope.py")]), 2)

        # JSON 输出可被解析
        p = subprocess.run([py, scan, tmp, "--format", "json"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        import json
        try:
            data = json.loads(p.stdout)
            check("JSON 含 summary.coverage_pct",
                  "coverage_pct" in data.get("summary", {}), True)
        except Exception as exc:
            check("JSON 可解析（%s）" % exc, False, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 9. 健壮性
# ---------------------------------------------------------------------------

def test_robustness() -> None:
    section("健壮性")
    tmp = tempfile.mkdtemp(prefix="scc-robust-")
    try:
        # 二进制文件必须被跳过而非崩溃
        binp = os.path.join(tmp, "blob.py")
        with open(binp, "wb") as f:
            f.write(b"\x00\x01\x02\xff\xfe" * 100)
        r = cs.scan_file(binp)
        check("二进制文件被跳过", r.skipped, True)

        # GBK 编码文件可读
        gbk = os.path.join(tmp, "gbk.py")
        with open(gbk, "w", encoding="gbk") as f:
            f.write("# 中文注释\n\ndef f():\n    return 1\n")
        r2 = cs.scan_file(gbk)
        check("GBK 文件可读", r2.skipped, False)

        # 空文件
        empty = os.path.join(tmp, "empty.py")
        open(empty, "w").close()
        check("空文件被跳过", cs.scan_file(empty).skipped, True)

        # 语法严重破损不应抛异常
        bad = os.path.join(tmp, "bad.py")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("def ((((((:\n  ???\n")
        r3 = cs.scan_file(bad)
        check("破损文件不崩溃", r3.skipped or r3.parse_mode == "heuristic", True)

        # 测试文件默认跳过
        tests_dir = os.path.join(tmp, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        tp = os.path.join(tests_dir, "test_x.py")
        with open(tp, "w", encoding="utf-8") as f:
            f.write("def test_a():\n    pass\n")
        check("测试文件默认跳过", cs.scan_file(tp, skip_tests=True).skipped, True)
        check("--include-tests 时不跳过",
              cs.scan_file(tp, skip_tests=False).skipped, False)

        # minified 检测覆盖全文（旧版只看前 50 行）
        minip = os.path.join(tmp, "mini.js")
        with open(minip, "w", encoding="utf-8") as f:
            f.write("\n".join(["var normal = 1;"] * 100
                              + ["var x=1;" * 400] * 5))
        r4 = cs.scan_file(minip)
        check("超长行在第 100 行后也能检出", len(r4.warnings) > 0, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 10. 路径缩短（报告可读性）
# ---------------------------------------------------------------------------

def test_path_shortening() -> None:
    section("路径缩短")
    short = "src/util.py"
    check("短路径原样返回", cs._shorten_path(short, 50), short)

    # 关键回归：超长路径必须保留**文件名**。
    # 旧实现用 path[:50] 从右侧截断，把 55 字符的临时目录路径切成了
    # `...\\Temp\\smoke-xxx\\a`，导致同目录下 a.py / a.js / a.go 在报告里
    # 显示成一模一样的名字，报告完全失去辨识能力。
    long_py = "C:\\Users\\somebody\\AppData\\Local\\Temp\\smoke-abcd1234\\a.py"
    long_js = "C:\\Users\\somebody\\AppData\\Local\\Temp\\smoke-abcd1234\\a.js"
    got_py = cs._shorten_path(long_py, 50)
    got_js = cs._shorten_path(long_js, 50)
    check("超长路径长度不超过上限", len(got_py) <= 50, True)
    check("超长路径保留文件名(py)", got_py.endswith("a.py"), True)
    check("超长路径保留文件名(js)", got_js.endswith("a.js"), True)
    check("同目录不同文件仍可区分", got_py != got_js, True)

    # 文件名本身超过宽度时，至少保留尾部
    huge = "x" * 80 + ".py"
    got_huge = cs._shorten_path(huge, 50)
    check("超长文件名截断后仍保留扩展名", got_huge.endswith(".py"), True)
    check("超长文件名截断后不超上限", len(got_huge) <= 50, True)


def main() -> int:
    print("smart-code-commenter 自测")
    print("Python %s" % sys.version.split()[0])
    test_language_detection()
    test_doc_comment_detection()
    test_symbol_extraction()
    test_python_analysis()
    test_doc_drift()
    test_line_counting()
    test_safety_check()
    test_cli()
    test_robustness()
    test_path_shortening()

    print("\n" + "=" * 58)
    print("通过 %d 项，失败 %d 项" % (_PASS, _FAIL))
    if _FAILURES:
        print("失败用例：")
        for name in _FAILURES:
            print("  - %s" % name)
    print("=" * 58)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
