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

- **frontmatter 必须合法**。`name` 只能用小写字母、数字、连字符并与目录名一致；`description` 必须为单行、最多 1024 字符，同时说明功能和触发场景。检查 `---` 边界、必填字段及宿主的 Skill 加载结果，不为验证安装 YAML 依赖。

- **只保留必要信息**。详细的语言风格模板放 `references/language-styles.md`，用 §编号 引用，
  不要把长代码块塞进 SKILL.md（会挤占模型的上下文预算）。
- **命令必须实测**。SKILL.md 里出现的每一条命令行都要真实跑通再写进去。
  历史上本项目就曾因为写错 `safety_check.py` 的参数顺序与备份命名，
  导致所有用户按文档操作都会踩到误判。
- **不写易变信息**。不写版本号、日期、作者、目录绝对路径。

## 修改 scripts/

- **语言规格集中在 `langspec.py`**，不要另建扩展名或注释符映射表。新增语言还需实现符号识别、定义校验子集并补测试；仅登记扩展名不代表完整支持。
- **保持 Python ≥3.8、零第三方依赖**。扫描器和校验器依赖 `langspec`；修复器复用扫描器的参数解析并调用校验器。不要引入循环依赖、目标包导入、缓存或插件框架。
- **固定退出码契约**并同步 `--help`：`0` 成功、`1` 发现问题或仍需处理、`2` 输入错误；`3` 在扫描器表示不完整或门禁无符号，在校验器表示 `UNVERIFIED`，在修复器表示分析不完整或应用失败。
- **校验失败必须阻止写入**。唯一备份和候选文件只属于本次操作；先验证候选，再确认原件未变化并替换。不得覆盖现有备份，恢复失败需保留可恢复数据及其路径。
- **只读脚本不得写入文件**。扫描器和校验器不得执行目标代码；修复器只能清理自己创建的临时文件。
- **编码与输出契约**：读取可降级，但无法可靠往返编码时不自动修复；写入保留 BOM、CRLF 和权限。JSON 的 stdout 不混入日志，控制台编码兜底不能改变机器输出结构。
- **保留词法边界和指令**。字符串内部空白、注释两侧 token 边界、换行、构建条件与工具指令不能被归一化吞掉；不支持的词法结构报告未验证。
- **统计不等于语义质量**。门禁使用未舍入计数，报告明确分母、排除与截断；参数诊断只解析受支持章节，禁止从函数起始行推算清理后 docstring 的源码位置。

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
- 增加误判 SAFE 的反例、空文档/门禁精度边界、多行签名/参数说明、BOM/CRLF 和候选写入失败测试；可使用标准库 `unittest.mock` 注入故障。
- 直接运行入口须以非零退出码报告失败；不要宣传未验证的 pytest 兼容性。最低 Python 版本和宿主加载需要单独验证。

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
