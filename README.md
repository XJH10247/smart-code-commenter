# smart-code-commenter

> 为源代码生成**符合语言原生规范**的注释，通过保守源码检查发现非注释变更，并明确报告无法验证的情况。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.8-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#5-技术设计要点)
[测试用例与运行方式](#11-开发)
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
| 遗留代码无注释，接手成本高 | 按范围生成文件头 / API 文档 / 必要的复杂逻辑说明 |
| AI 加注释时"顺手改了代码"，不敢用 | 候选先校验；非 SAFE 不自动写回，无法验证明确报告 |
| 不知道哪些文件最缺注释 | 扫描文档存在率、未注释符号、结构诊断和扫描完整性 |
| 注释写了但过期，比没有更害人 | Python Google/NumPy 参数章节一致性检测；仅删除可准确定位的多余参数条目，默认 dry-run |
| AI 注释风格不统一、不专业 | 提供多语言原生文档风格指导，优先沿用项目既有风格 |
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
  ├─ ③ 校验候选     scripts/safety_check.py     → SAFE 才可替换 / 其他保留原件
  └─ ④ 结果总结     实际写入状态、扫描完整性、跳过与待确认项

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
│   ├── comment_scanner.py        # 存在率、结构诊断与完整性报告（只读）
│   ├── safety_check.py           # 保守源码比较（SAFE / UNSAFE / UNVERIFIED）
│   └── fix_stale.py              # 精确参数条目修复（默认 dry-run，候选先验）
├── assets/
│   └── templates/
│       └── report.md             # 覆盖率报告输出模板
├── examples/
│   ├── input-python.md  /  output-python.md    # Python Docstring 示例
│   ├── input-java.md    /  output-java.md      # Java 遗留代码全量注释示例
│   └── input-broken.md  /  output-broken.md    # 语法错误代码的鲁棒处理示例
└── tests/
    ├── test_skill.py             # 语言规格、扫描、安全校验与 CLI 自测
    └── test_fix_stale.py         # 精确修复、事务失败及编码专项自测
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

- **保留依赖边界**：扫描器与校验器使用 `langspec.py`；修复器复用扫描器的参数章节解析，并调用校验器。仅使用标准库。
- **分开衡量**：存在率统计非空文档；结构诊断检查参数章节；业务描述是否真实仍需人工判断。覆盖率门禁使用未舍入计数，舍入只用于展示。
- **保守源码校验**：有效 Python 比较去真正 docstring 后的 AST；其他语言只在受支持词法范围内比较，保留字面量、词法边界和指令约束。未知或不可靠语法返回 `UNVERIFIED`，不视为通过。
- **不承诺运行行为等价**：docstring 可被 `__doc__` 读取，构建与工具指令也有语义；只允许修改说明性注释和文档字符串。
- **精确修复**：从原始 docstring/token 定位完整参数条目，不从函数行号推算；无法确定坐标或组合条目包含有效参数时只报告。
- **逐文件事务**：默认 dry-run；唯一备份与候选文件先校验，确认原件未变化后再替换。校验器缺失、超时或失败均阻止写入，不覆盖已有备份。
- **报告真实状态**：扫描器和修复器支持 JSON；安全校验器提供文本及 `--quiet`。报告区分扫描完整性、请求写入与实际结果。

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
| `--include-covered` | 同时列出缺失和已文档符号 |
| `--max-files N` | 合格源码候选上限，默认 500，超过时明确报告截断 |
| `--exclude PATTERN` | 可重复的 glob 排除，基于扫描根目录相对路径，使用 `/` 分隔；单文件输入也生效 |

退出码：`0` 完整扫描且满足门禁 / `1` 覆盖率不足 / `2` 输入错误 / `3` 扫描不完整或门禁无可计符号。
无可计符号时覆盖率不适用；JSON 仍输出结构化结果。主动排除不算读取错误，不完整扫描不能称为全项目达标。
统计只涵盖已遇到的条目，`excluded` 包含被整体排除的目录，不等于目录内文件总数；截断后的未知条目不计数。排除 glob 大小写敏感。

### 保守源码校验

先将原件复制到不存在的备份路径，再在单独候选文件上编辑；不要覆盖现有备份。示例名称为 `app.py.commenter.bak` 和 `app.py.commenter.tmp`，冲突时选择保留真实扩展名的唯一名称。

```bash
python scripts/safety_check.py app.py.commenter.bak app.py.commenter.tmp --verbose
```

退出码：`0` SAFE / `1` UNSAFE / `2` 输入错误 / `3` UNVERIFIED。
只有 `SAFE` 且原件仍与快照一致时才可替换。其他状态保持原件不变，只提供差异和原因；无 Python 时也不能声称自动验证通过。

### 过期注释修复

```bash
# 预览会改什么，默认不写入
python scripts/fix_stale.py ./src --diff

# 确认后，备份并验证候选，通过后才替换原件
python scripts/fix_stale.py ./src --apply --verbose
```

| 检测类型 | 说明 | 自动修正 |
|---------|------|---------|
| `param-extra` | Python Google/NumPy 文档中的多余参数 | 仅删除能可靠定位的完整条目 |
| `param-missing` | 签名中有、文档未提及的参数 | 仅报告 |
| `todo` | TODO / FIXME 标记（需 `--include-todos`） | 仅报告，不推断积压时间 |

支持 `--max-files`、`--exclude` 和 `--format json`。`apply_requested` 表示请求，`applied` 与逐文件结果表示实际处理情况；不能用请求标志推断成功。
退出码：`0` 无问题或全部修正成功 / `1` 仍有待处理项 / `2` 输入错误 / `3` 分析不完整或修复失败。
每个文件独立提交；一个文件失败不会撤销其他已成功文件，须查看逐文件结果。遇到并发修改停止该文件处理，不覆盖用户的新内容。
在 Python 中调用时，`apply_findings(findings)` 返回逐文件结果列表；渲染必须显式传入实际结果，例如 `render_json(findings, True, results)`，不能只从诊断重建应用状态。

## 7. 支持的语言

语言规格登记 **21 种语言、48 种文件扩展名**，不代表每项能力同等支持：

| 输入 | 生成指导 | 存在率统计 | 参数检查 | 源码校验 | 自动修复 |
|------|----------|------------|----------|----------|----------|
| 有效 Python | Google/NumPy/reST | AST，空文档不计入 | Google/NumPy 章节 | 去 docstring 后 AST 比较及指令约束 | 可定位的多余参数 |
| 语法错误 Python | 建议预览 | 启发式，标记降级 | 不承诺 | 不确定则 UNVERIFIED | 不支持 |
| 其他已登记语言 | 原生格式 | 启发式 | 不支持 | 受支持词法子集；不确定则 UNVERIFIED | 不支持 |
| 未知语言 | 人工确认格式后建议 | 不支持 | 不支持 | UNVERIFIED | 不支持 |

以下是生成指导及扩展名登记表：

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
| 文件不存在 / 无权限 | 输入错误或逐文件报告，不能当作通过 |
| 二进制 / 超大源码（> 10 MB） | 跳过并说明无法完成该文件分析 |
| 语法错误 | 可生成建议，扫描标记启发式；不以弱校验承诺 SAFE |
| 非 UTF-8 编码 | 扫描可回退读取；修复要求可可靠解码并往返保存 |
| 压缩 / 混淆 / 生成代码 | 检测超长行并提醒，先确认范围 |
| 未知语言或不支持的词法结构 | 不承诺校验，返回 UNVERIFIED |
| 无可计符号 | 覆盖率不适用，带门禁不通过 |
| BOM / CRLF | 修复保留原始编码标记和行尾 |
| 文件数上限 | 报告截断；排除项不占源码候选额度 |
| 校验器缺失、超时或异常 | 拒绝替换原文件，报告失败 |
| 并发修改或现有备份 | 不覆盖用户内容；本次临时文件使用唯一名称 |

## 9. 安全与合规

- **脚本离线**：脚本不发网络请求；宿主模型是否远程处理代码取决于客户端配置，不能据此承诺整个流程离线。
- **最小权限**：扫描和校验只读；修复只写用户指定范围，不执行被分析代码。
- **候选先验**：备份后校验候选，成功且原件未变化才替换；失败保留原件，不静默跳过校验。
- **临时文件归属**：只清理本次创建的文件；恢复失败时保留备份并报告位置，不删除用户已有文件。
- **密钥保护**：遇到疑似密钥或凭证，不写入注释、不复述值，只提醒风险。

## 10. 已知限制

- 无法仅凭静态代码确认全部业务背景；疑问放结果报告，不自动写 TODO 或臆造描述。
- 非 Python 符号统计与通用源码校验有明确的启发式/词法子集边界，可能遗漏或拒绝不支持的语法；并非完整编译器或行为等价证明。
- 参数检查与自动修正目前只覆盖 Python Google/NumPy 参数章节；reST 和其他语言仍可生成原生风格建议，但不提供对应的自动参数检查。
- 组合参数条目含有效参数、转义/拼接字符串无法可靠定位时只报告，不删除。
- 不处理二进制、加密文件与超过 10 MB 的单文件。未经过可比基准测试，不承诺扫描速度或引入缓存/并行框架。

## 11. 开发

```bash
# 运行全部测试（零依赖，无需安装任何东西）
python tests/test_skill.py
python tests/test_fix_stale.py
```

两套自测均以非零退出码报告失败，包含误判 SAFE、参数定位、门禁精度、事务故障及编码回归用例。通过数量以实际运行输出为准，不用静态徽章代替验证。
Python 3.8 语法兼容检查不等同于在 Python 3.8 上运行；最低版本、当前版本及 Windows 文件行为应分别测试。

贡献代码前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)，遵守标准库依赖、语言规格集中登记和失败不得放行的约束。

## License

[MIT](LICENSE)
