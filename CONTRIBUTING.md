# 贡献指南

感谢你有兴趣改进 smart-code-commenter。本项目是一个 Agent Skill，包含提示词文档与
配套 Python 工具链两部分，两边的改动要求有所不同。

## 环境准备

```bash
git clone <repo-url>
cd smart-code-commenter

# 无第三方依赖，只需 Python >= 3.8
python --version
```

运行测试：

```bash
python tests/test_skill.py        # 主套件：语言探测、扫描、安全校验
python tests/test_fix_stale.py    # 专项：过期注释修复
```

两个测试脚本都是零依赖的，各自以退出码表示结果（`0` 全部通过）。
**提交前请确保两套测试全绿。**

> 测试运行前如遇莫名失败，先删除 `scripts/__pycache__`——陈旧的 `.pyc`
> 曾在本项目造成过取不到最新代码的假失败。

## 目录结构约定

```
smart-code-commenter/
├── SKILL.md              # Agent 主指令：触发条件、操作步骤、工具调用契约
├── README.md             # 面向人类的项目介绍（GitHub 首页；不参与 Skill 路由）
├── references/
│   └── language-styles.md  # 按需查阅的语言风格规范（progressive disclosure）
├── CHANGELOG.md          # 变更日志
├── CONTRIBUTING.md       # 本文件
├── LICENSE
├── scripts/
│   ├── langspec.py       # ★ 语言规格的单一可信来源
│   ├── comment_scanner.py
│   ├── safety_check.py
│   └── fix_stale.py
├── assets/
│   └── templates/
│       └── report.md     # 覆盖率报告输出模板
├── examples/             # 输入输出成对示例
└── tests/
```

## 修改 SKILL.md

SKILL.md 是给模型读的指令文件，不是给人读的文档。写作时遵守：

- **frontmatter 必须合法**。`name` 只能用小写字母、数字、连字符（须与目录名一致）；
  `description` 控制在 1024 字符内，且必须同时写清"做什么"与"何时触发"，
  因为路由只依赖它。修改后请验证：

  ```bash
  python -c "import yaml,io,re; \
  t=io.open('SKILL.md',encoding='utf-8').read(); \
  print(yaml.safe_load(re.match(r'^---\n(.*?)\n---\n',t,re.S).group(1)))"
  ```

- **只保留必要信息**。详细的语言风格模板放 `references/language-styles.md`，用 §编号 引用，
  不要把长代码块塞进 SKILL.md（会挤占模型的上下文预算）。
- **命令必须实测**。SKILL.md 里出现的每一条命令行都要真实跑通再写进去。
  历史上本项目就曾因为写错 `safety_check.py` 的参数顺序与备份命名，
  导致所有用户按文档操作都会踩到误判。
- **不写易变信息**。不写版本号、日期、作者、目录绝对路径。

## 修改 scripts/

- **新增语言只改 `langspec.py`**。不要在任何脚本里另建语言映射表——
  三份语言表口径不一致正是本项目 1.1.0 修复的主要缺陷来源。
  在 `LANG_SPECS` 加一条 `LangSpec`，在 `EXT_TO_LANG` 加扩展名映射即可，
  `comment_scanner.py` / `safety_check.py` 会自动获得支持。
- **保持零第三方依赖**。仅用标准库。这是本项目能"扔进任何环境就能跑"的前提。
- **每个脚本必须有确定的退出码契约**，并在 `--help` 的 epilog 里写明。
  当前约定：`0` 成功/安全、`1` 发现问题、`2` 输入错误、
  `3` 自检失败已回滚（仅 `fix_stale.py`）。
- **任何写入前必须备份，写入后必须自检**。`fix_stale.py` 是参考实现。
- **只读脚本不得写入文件**。`comment_scanner.py` 与 `safety_check.py` 全程只读。
- **编码兜底**：读文件用 `utf-8-sig` → GBK → Latin-1 回退；
  写 stdout 时捕获 `UnicodeEncodeError` 并降级为 `errors="replace"`
  （Windows GBK 控制台会踩到）。
- **字符串与注释要区分开**。剥离注释时必须用状态机判断是否在字符串字面量内，
  否则 `"http://example.com"` 的 `//` 会被误当行注释。
  Rust / Kotlin / Swift 的块注释可嵌套，别用非贪婪正则图省事。

## 新增语言支持

1. 在 `scripts/langspec.py` 的 `LANG_SPECS` 中登记该语言：
   `LangSpec(name, line, block_open, block_close, doc_prefixes, hash_doc, nesting)`
2. 在 `EXT_TO_LANG` 添加扩展名映射
3. 在 `_CONTENT_HINTS` 添加高置信度内容特征正则（用于无扩展名的文件）
4. 在 `scripts/comment_scanner.py` 的符号解析表中添加该语言的函数/类正则
5. 在 `references/language-styles.md` 补充风格小节
6. 在 `tests/test_skill.py` 补充语言探测与符号解析用例

## 测试写作约定

测试套件刻意不依赖 pytest，用 `check(label, got, expect)` 累积结果而非抛异常，
这样一次运行能看到全部失败项。

```python
def check(label, got, expect):
    global PASS, FAIL
    if got == expect:
        PASS += 1
        print("  [OK  ] %s" % label)
    else:
        FAIL += 1
        print("  [FAIL] %s\n         期望 %r\n         实际 %r" % (label, expect, got))
```

注意：

- 涉及文件写入的用例用 `tempfile.mkdtemp()` 建独立目录，`finally` 里清理；
- 检查 CRLF 相关行为时**必须**显式写 `\r\n`——只测 LF 会漏掉行尾比对类缺陷；
- 不要用 shell 内联 `python -c` 传含 `\n`、`$` 的字符串做断言，
  bash 转义会把内容改掉并产生难以定位的假失败，写成独立测试文件。

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
<type>(<scope>): <描述>

feat(langspec): 新增 Zig 语言支持
fix(safety_check): 修正 CRLF 备份文件的误判
docs(reference): 补充 TSDoc 与 JSDoc 的差异对照
test(scanner): 补充 Swift 符号解析用例
```

type 取值：`feat` / `fix` / `docs` / `test` / `refactor` / `perf` / `chore`。

提交前自查：

- [ ] `python tests/test_skill.py` 全绿
- [ ] `python tests/test_fix_stale.py` 全绿
- [ ] SKILL.md 中新增的命令都手动跑过
- [ ] 新增语言支持时没在 `langspec.py` 之外另建映射表
- [ ] `CHANGELOG.md` 的 `[Unreleased]` 段落已补充

## 报告问题

提交 issue 时请附上：

1. 触发场景（文件类型、操作系统、是否 CRLF 行尾）
2. 完整命令行与输出
3. 期望行为与实际行为
4. 最小复现文件（如能提供）

安全校验类问题（误判 SAFE / 误判 UNSAFE）优先级最高，请务必报告——
这类缺陷会让用户不敢使用工具，或让错误的改动被放行。

## 许可

提交贡献即表示同意以 [MIT 许可证](LICENSE) 发布你的贡献。
