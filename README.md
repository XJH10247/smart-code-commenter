# smart-code-commenter

> 为任意语言的源代码生成**符合语言原生规范**的高质量注释，并用工具链保证**只增注释、不改逻辑**。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.8-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#5-技术设计要点)
[![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen.svg)](tests/)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-8A2BE2.svg)](https://agentskills.io)
[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](CHANGELOG.md)

一个 Agent Skill + 一套零依赖 Python 工具链。让"AI 帮我把注释补上"这件事，
像 code review 一样可量化、可验证、可信赖。

兼容 [Agent Skills](https://agentskills.io) 开放标准，可在 Claude Code、MiMo Desktop
等支持 SKILL.md 的客户端中作为 Skill 安装；脚本亦可独立作为 CLI 使用。

---

## 目录

- [1. 解决什么痛点](#1-解决什么痛点)
- [2. 工作流](#2-工作流)
- [3. 目录结构](#3-目录结构)
- [4. 安装](#4-安装)
- [5. 技术设计要点](#5-技术设计要点)
- [6. 脚本独立使用](#6-脚本独立使用)
- [7. 支持的语言](#7-支持的语言)
- [8. 鲁棒性设计](#8-鲁棒性设计)
- [9. 安全与合规](#9-安全与合规)
- [10. 已知限制](#10-已知限制)
- [11. 开发](#11-开发)

---

## 1. 解决什么痛点

| 研发真实痛点 | 本 Skill 的应对 |
|-------------|----------------|
| 遗留代码无注释，接手成本高 | 三级注释体系一次性补全：文件头 / API 文档注释 / 复杂逻辑行内注释 |
| AI 加注释时"顺手改了代码"，不敢用 | **零逻辑变更保证**：`safety_check.py` 用 AST / token 级比对强制校验，UNSAFE 自动回滚 |
| 不知道哪些文件最缺注释 | `comment_scanner.py` 量化扫描：覆盖率、未注释符号清单、按缺口排序 |
| 注释写了但过期，比没有更害人 | 文档参数与函数签名一致性检测；`fix_stale.py` 可自动删除已失效的参数条目（默认 dry-run） |
| AI 注释风格不统一、不专业 | 21 种语言的原生文档风格（Docstring / JSDoc / TSDoc / Javadoc / godoc / rustdoc / KDoc…），并优先沿用项目既有风格 |
| 全量注释噪音大 | git 增量模式：只为本次改动的函数补注释，适配 MR / PR 工作流 |
| 想在 CI 里守注释底线 | `--min-coverage` 覆盖率门禁 + 确定的退出码 + JSON 输出 |

## 2. 工作流

```
输入：代码片段 / 文件 / 目录 / git 增量
  │
  ├─ ① 覆盖率扫描   scripts/comment_scanner.py  → 量化报告，确认处理范围
  ├─ ② 三级注释生成
  │     Level 1  文件头注释（模块职责、对外能力、注意事项）
  │     Level 2  API 文档注释（原生风格，参数与签名逐一核对）
  │     Level 3  行内注释（只解释 Why，不复述 What）
  ├─ ③ 安全校验     scripts/safety_check.py     → SAFE 保留 / UNSAFE 回滚
  └─ ④ 结果总结     覆盖率前后对比、跳过项、风险提醒

（可选）⑤ 过期注释修复  scripts/fix_stale.py    → 默认 dry-run，--apply 才写入
```

三个脚本各司其职，形成 **"测 — 改 — 验"** 闭环：扫描器给基线，模型做语义理解，
校验器守边界。模型只负责它最擅长的那一环。

## 3. 目录结构

对齐 [Agent Skills 规范](https://agentskills.io/specification)（`SKILL.md` + `scripts/` + `references/` + `assets/`）：

```
smart-code-commenter/
├── SKILL.md                      # Agent 主指令：触发条件、操作步骤、工具调用契约
├── README.md                     # 面向人类的项目介绍（GitHub 首页；不影响 Skill 加载）
├── CHANGELOG.md                  # 变更日志
├── CONTRIBUTING.md               # 贡献指南
├── LICENSE                       # MIT
├── .gitignore
├── references/
│   └── language-styles.md        # 21 种语言文档注释风格规范（progressive disclosure）
├── scripts/
│   ├── langspec.py               # 语言规格的单一可信来源（21 语言 / 48 扩展名）
│   ├── comment_scanner.py        # 注释覆盖率扫描器（只读、零依赖）
│   ├── safety_check.py           # 零逻辑变更校验器（AST / token 级比对）
│   └── fix_stale.py              # 过期注释修复器（默认 dry-run，写入前备份+自检）
├── assets/
│   └── templates/
│       └── report.md             # 覆盖率报告输出模板
├── examples/
│   ├── input-python.md  /  output-python.md    # Python Docstring 示例
│   ├── input-java.md    /  output-java.md      # Java 遗留代码全量注释示例
│   └── input-broken.md  /  output-broken.md    # 语法错误代码的鲁棒处理示例
└── tests/
    ├── test_skill.py             # 主测试套件（110 项）
    └── test_fix_stale.py         # 过期注释修复专项（18 项）
```

## 4. 安装

### 作为 Agent Skill

把整个目录放进客户端的 skills 目录即可，无需任何配置：

```bash
# MiMo Desktop / MiMoCode（全局）
cp -r smart-code-commenter ~/.config/mimocode/skills/

# MiMoCode（项目级，随仓库共享给团队）
cp -r smart-code-commenter <project>/.mimocode/skills/

# Claude Code（个人）
cp -r smart-code-commenter ~/.claude/skills/

# Claude Code（项目）
cp -r smart-code-commenter <project>/.claude/skills/

# 通用（兼容 Agent Skills 规范的客户端）
cp -r smart-code-commenter <your-client>/skills/
```

安装后**新开对话**才会加载生效。

> **关于 README.md**：本仓库根目录的 `README.md` 只供 GitHub/人类阅读，不参与
> Agent 路由。极少数严格校验器会提示 skill 目录内不应存在 README——若目标客户端
> 因此拒绝加载，安装时排除即可：`cp -r scripts references assets examples SKILL.md <dest>/`
> （再按需复制 LICENSE）。日常使用不影响 Claude Code / MiMo 等主流客户端。

### 作为命令行工具

不需要安装，直接调用：

```bash
python scripts/comment_scanner.py --help
```

**环境要求**：Python ≥ 3.8，**仅标准库，零第三方依赖，无需 `pip install`**。
没有 Python 环境时 Skill 仍可工作——`SKILL.md` 内置了人工替代流程
（用 `git diff` 逐行核对代替自动校验）。

## 5. 技术设计要点

- **单一可信来源**：`scripts/langspec.py` 集中登记语言规格。此前扫描器与校验器各维护一份语言表，
  口径不一致，是多个缺陷的共同根因。
- **AST 优先，启发式兜底**：Python 用 `ast` 精确分析（docstring、参数一致性）；
  语法错误时降级 `tokenize`，再降级正则——三层递进保证"永远有输出"。
- **零逻辑变更校验**：Python 比对剥离 docstring 后的 AST 指纹；
  其他语言用**字符串感知的状态机**剥离注释后比对，避免把 `"http://x"` 里的 `//`
  误判为注释；支持 Rust / Kotlin / Swift 的嵌套块注释。
- **降级路径也准确**：语法错误文件走 token 比对时，docstring 是普通 `STRING` token，
  必然产生差异。因此先用 `tokenize` 把 docstring 归一化为哨兵并丢弃，
  使"改注释"与"改代码"在降级路径下同样可区分。
- **备份后缀感知**：`safety_check.py` 会剥离 `.bak` / `.orig` / `.old` / `.commenter`
  等 10 种备份后缀再识别语言，因此 `app.js.commenter.bak` 能被正确识别为 JavaScript。
- **安全默认值**：`fix_stale.py` 默认 dry-run；任何写入前自动备份、写入后自检、
  失败自动回滚。
- **CI 友好**：三个脚本都有确定的退出码与 JSON 输出，可直接接入流水线。

## 6. 脚本独立使用

### 覆盖率扫描

```bash
# Markdown 报告（人读）
python scripts/comment_scanner.py ./src --format markdown

# JSON（机器读，供 CI 消费）
python scripts/comment_scanner.py ./src --format json

# 覆盖率门禁：低于 80% 时退出码为 1
python scripts/comment_scanner.py ./src --min-coverage 80

# 只输出摘要行（适合流水线日志）
python scripts/comment_scanner.py ./src --quiet
```

| 选项 | 用途 |
|------|------|
| `--format {markdown,json,text}` | 输出格式，默认 `markdown` |
| `--min-coverage PCT` | 覆盖率门禁，低于阈值退出码 1 |
| `--no-private` | 把私有 / 半私有符号排除出分母（默认计入） |
| `--include-tests` | 不跳过测试文件（默认跳过） |
| `--include-covered` | 一并列出已文档符号（默认只列缺失项） |
| `--max-files N` | 目录扫描文件数上限，默认 500 |

退出码：`0` 正常 / `1` 低于 `--min-coverage` / `2` 输入错误

### 零逻辑变更校验

```bash
# 参数顺序：原始文件(备份)  修改后文件
python scripts/safety_check.py app.py app.py.commenter.bak --verbose
```

退出码：`0` SAFE / `1` UNSAFE / `2` 输入错误

### 过期注释修复

```bash
# 预览会改什么（dry-run，不动文件）
python scripts/fix_stale.py ./src --diff

# 确认后写入（自动备份 → 修改 → 自检 → 通过则清理备份，失败则回滚）
python scripts/fix_stale.py ./src --apply --verbose
```

| 检测类型 | 说明 | 自动修正 |
|---------|------|---------|
| `param-extra` | 文档里写了、签名中已不存在的参数 | ✅ 删除该条目 |
| `param-missing` | 签名中有、文档未提及的参数 | ❌ 仅报告 |
| `todo` | TODO / FIXME 积压（需 `--include-todos`） | ❌ 仅报告 |

退出码：`0` 无需修正或已应用 / `1` 存在待修正项（未应用）/ `2` 输入错误 / `3` 自检失败已回滚

## 7. 支持的语言

扫描与校验均内置 **21 种语言规格、覆盖 48 种文件扩展名**：

| 语言 | 文档注释风格 | 扩展名 |
|------|------------|--------|
| Python | Google / NumPy / reST Docstring | `.py` `.pyi` `.pyw` |
| JavaScript | JSDoc | `.js` `.jsx` `.mjs` `.cjs` |
| TypeScript | TSDoc / JSDoc | `.ts` `.tsx` `.mts` `.cts` |
| Java | Javadoc | `.java` |
| Go | godoc 惯例 | `.go` |
| C / C++ | Doxygen | `.c` `.h` `.cc` `.cpp` `.cxx` `.hpp` `.hxx` `.hh` `.ino` |
| Rust | rustdoc | `.rs` |
| C# | XML 文档注释 | `.cs` |
| Kotlin | KDoc | `.kt` `.kts` |
| PHP | PHPDoc | `.php` `.phtml` |
| Ruby | RDoc / YARD | `.rb` `.rake` `.gemspec` |
| Swift | DocC | `.swift` |
| Scala | Scaladoc | `.scala` `.sc` |
| Dart | dartdoc | `.dart` |
| Shell | 脚本头三要素 | `.sh` `.bash` `.zsh` `.ksh` |
| PowerShell | 注释块 | `.ps1` `.psd1` `.psm1` |
| SQL | 块注释 | `.sql` |
| Lua | LDoc | `.lua` |
| R | roxygen2 | `.r` `.rmd` |
| Perl | POD | `.pl` `.pm` |

未列出的语言：采用该语言通用行注释符，参照三级注释原则生成。
各语言的详细风格模板见 [`references/language-styles.md`](references/language-styles.md)。

## 8. 鲁棒性设计

| 异常场景 | 行为 |
|---------|------|
| 文件不存在 / 无权限 | 友好提示并跳过，不中断整体流程 |
| 二进制 / 图片 / 超大文件（> 10 MB） | 识别并跳过，说明原因 |
| 语法错误的代码 | 照常生成注释（AST 失败自动降级 token / 正则），附语法问题报告 |
| 编码非 UTF-8（UTF-8-BOM / GBK / Latin-1） | 多编码回退读取，不抛 `UnicodeDecodeError` |
| 压缩 / 混淆 / 生成代码 | 全文等距采样识别超长行，提示后再决定是否处理 |
| 未知扩展名 | 降级为通用行注释符，不崩溃 |
| 空文件 / 纯注释文件 | 说明无需处理 |
| Windows GBK 控制台 | 输出编码降级兜底，不抛 `UnicodeEncodeError` |
| CRLF 行尾文件 | 行尾归一化比对，修改不会静默失效，也不会把 CRLF 改成 LF |
| 目录含 `node_modules` 等 | 自动跳过依赖 / 产物目录，限制文件数上限 |
| 脚本内部任意异常 | 逐文件异常隔离 + 顶层兜底，单文件失败不影响整体 |

## 9. 安全与合规

- **全程本地处理**：脚本零网络请求，代码不出本机
- **最小权限**：扫描 / 校验均为只读；写入仅限用户明确指定的目标文件，先备份后修改
- **不执行被分析的代码**，不删除任何文件
- **自检回滚**：`fix_stale.py` 写入后自动调用 `safety_check.py` 复验，失败即回滚
- **密钥保护**：遇到源代码中的疑似密钥 / 凭证，不写入注释、不复述其值，并提醒泄露风险
- 无任何硬编码密钥、无越权行为

## 10. 已知限制

- 注释基于静态语义推断，无法获知业务背景；含糊处标注 `TODO(确认)` 供人工补充
- 非 Python 语言的符号统计为启发式，极端代码风格下可能有少量遗漏
  （不影响注释生成质量，仅影响统计精度）
- 过期注释的**自动修正目前仅支持 Python** 的 `param-extra` 类型；
  其他语言与其他类型只报告不自动改（补写内容需语义判断，不宜机械生成）
- 不处理二进制、加密文件与超过 10 MB 的单文件

## 11. 开发

```bash
# 运行全部测试（零依赖，无需安装任何东西）
python tests/test_skill.py
python tests/test_fix_stale.py
```

当前状态：**128 项测试全部通过**（主套件 110 项 + 专项 18 项）。

贡献代码前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)，
尤其是"新增语言只改 `langspec.py`"这条约束。

## License

[MIT](LICENSE)
