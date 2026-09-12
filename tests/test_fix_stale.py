#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_stale.py 的专项测试（避免 shell 转义干扰，独立于主测试套件）。"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import fix_stale as fs  # noqa: E402

PASS = FAIL = 0


def check(label, got, expect):
    global PASS, FAIL
    if got == expect:
        PASS += 1
        print("  [OK  ] %s" % label)
    else:
        FAIL += 1
        print("  [FAIL] %s\n         期望 %r\n         实际 %r"
              % (label, expect, got))


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

SOURCE = '''def transfer(from_acct, to_acct, amount):
    """执行转账。

    Args:
        from_acct: 转出账户。
        to_acct: 转入账户。
        amount: 金额。
        currency: 币种（签名里已无此参数）。
        legacy_flag: 已废弃参数。

    Returns:
        流水号。
    """
    return "ok"
'''

print("fix_stale 专项测试")
print("\n=== 文档参数提取 ===")
check("Google 风格", fs._documented_arg_names(DOC),
      {"from_acct": 4, "to_acct": 5, "amount": 6, "currency": 7})
check("NumPy 风格", fs._documented_arg_names(DOC_NUMPY),
      {"from_acct": 5, "amount": 7, "currency": 9})

print("\n=== 静态检测 ===")
tmp = tempfile.mkdtemp(prefix="fixstale-")
try:
    p = os.path.join(tmp, "demo.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(SOURCE)

    findings = fs.analyze_python_file(p)
    extras = [f for f in findings if f.kind == "param-extra"]
    check("检出 2 个多余参数", sorted(f.symbol for f in extras),
          ["transfer", "transfer"])
    check("两条均可自动修正", [f.fixable for f in extras], [True, True])
    check("old_text 指向正确行",
          [f.old_text.strip() for f in extras],
          ["currency: 币种（签名里已无此参数）。", "legacy_flag: 已废弃参数。"])

    print("\n=== dry-run 不改文件 ===")
    before = open(p, encoding="utf-8").read()
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fix_stale.py"), p],
                       capture_output=True, text=True, encoding="utf-8")
    check("dry-run 退出码 1", r.returncode, 1)
    check("dry-run 未修改文件", open(p, encoding="utf-8").read(), before)
    check("输出含 dry-run 提示", "dry-run" in r.stdout, True)

    print("\n=== --apply 实际写入 ===")
    r2 = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "fix_stale.py"), p,
         "--apply", "--verbose"],
        capture_output=True, text=True, encoding="utf-8")
    check("apply 退出码 0", r2.returncode, 0)
    after = open(p, encoding="utf-8").read()
    check("多余参数行已删除", "currency" not in after and "legacy_flag" not in after, True)
    check("保留的参数行完好",
          "from_acct: 转出账户。" in after and "amount: 金额。" in after, True)
    check("代码未被改动", 'return "ok"' in after, True)
    check("备份文件已清理",
          [f for f in os.listdir(tmp) if f.endswith(".bak")], [])

    print("\n=== 幂等性 ===")
    r3 = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fix_stale.py"), p],
                        capture_output=True, text=True, encoding="utf-8")
    check("再次运行无待修正项", r3.returncode, 0)
    check("报告显示无需修正", "未发现需要修正" in r3.stdout, True)

    print("\n=== 参数缺失（仅报告，不自动补写） ===")
    p2 = os.path.join(tmp, "missing.py")
    with open(p2, "w", encoding="utf-8") as f:
        f.write('def g(a, b):\n    """摘要。\n\n    Args:\n        a: 参数 a。\n'
                '    """\n    return a\n')
    f2 = fs.analyze_python_file(p2)
    missing = [x for x in f2 if x.kind == "param-missing"]
    check("检出缺失参数", len(missing), 1)
    check("缺失项不可自动修正", missing[0].fixable, False)

    print("\n=== JSON 输出 ===")
    import json
    r4 = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "fix_stale.py"), tmp,
         "--format", "json"],
        capture_output=True, text=True, encoding="utf-8")
    try:
        data = json.loads(r4.stdout)
        check("JSON 可解析且含 findings", "findings" in data, True)
    except Exception as exc:
        check("JSON 可解析（%s）" % exc, False, True)
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 58)
print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
print("=" * 58)
sys.exit(0 if FAIL == 0 else 1)
