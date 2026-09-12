---
name: smart-code-commenter
description: 为源代码自动生成高质量注释：文件头、函数/类文档注释（Docstring、JSDoc/TSDoc、Javadoc、godoc、rustdoc、KDoc 等原生风格）、复杂逻辑行内注释；内置覆盖率扫描、过期注释检测与修复、零逻辑变更安全校验。Use when the user asks to generate/add/write comments, docstrings, JSDoc, Javadoc, comment coverage, or fix stale comments；用户提到"生成注释"、"加注释"、"写注释"、"补注释"、"docstring"、"JSDoc"、"Javadoc"、"注释覆盖率"、"注释过期"、"comment"，或要求为代码/文件/项目补充文档注释时使用。
license: MIT
compatibility: Scripts require Python 3.8+ (stdlib only). Without Python the skill still works via prompt-only workflow.
metadata:
  version: "1.2.0"
  languages: "21"
  extensions: "48"
---

# 智能代码注释生成器（Smart Code Commenter）

为任意语言的源代码生成**符合语言原生规范**的高质量注释，并用工具链保证**只增注释、不改逻辑**。

## 触发条件

用户出现以下任一场景时使用本 Skill：

- 要求为某段代码、某个文件、某个目录"生成注释 / 加注释 / 补注释 / 写注释"
- 提到 docstring、JSDoc、TSDoc、Javadoc、KDoc、godoc、rustdoc、XML Doc、Doxygen 等文档注释关键词
- 要求"检查注释覆盖率"、"哪些函数没有注释"、"注释报告"、"注释门禁"
- 要求"检查注释是否过期"、"注释和代码不一致"、"参数文档对不上"
- 只为 git 改动部分补注释（增量模式）

**不要使用**本 Skill：纯代码重构/改逻辑、生成测试、写 README/架构文档、翻译代码、审查 PR 评论（应优先用 code-review 类 skill）。

## 核心原则（必须遵守）

1. **零逻辑变更**：只允许新增/修改注释与文档字符串，严禁改动任何可执行代码、字符串字面量、导入语句。修改后用 `scripts/safety_check.py` 强制校验。
2. **原生风格**：注释风格必须匹配语言生态惯例（见 `references/language-styles.md`），若项目已有注释风格，优先沿用项目现有风格。
3. **解释 Why 而非 What**：行内注释解释意图、约束、边界条件，不复述代码字面含义（禁止 `i++  // i 加 1` 式注释）。
4. **克制**：简单自解释代码不加行内注释；只为复杂算法、非常规写法、易错边界、魔法值添加。
5. **语言一致**：注释语言跟随用户要求；未指定时，跟随项目已有注释的主要语言；全新项目默认中文。
6. **不臆造参数**：文档注释中出现的每个参数名都必须与函数签名逐一核对，禁止凭空写入不存在的参数。
7. **不泄漏密钥**：源码中的 API Key、密码、token 绝不写入注释；发现时提醒用户存在泄露风险。

## 操作步骤

### 第 1 步：识别输入类型

| 输入 | 处理方式 |
|------|---------|
| 一段粘贴的代码 | 直接进入第 3 步生成注释，结果以代码块输出 |
| 单个文件路径 | 读取文件后进入第 2 步 |
| 目录 / 整个项目 | 先执行覆盖率扫描（第 2 步），按报告排序逐文件处理 |
| git 增量（用户要求只注释改动） | 运行 `git diff --name-only HEAD` 与 `git diff -U0` 定位改动函数，只处理这些函数 |

**异常输入防御**（遇到以下情况不要报错崩溃，给出友好说明并继续可处理的部分）：

- 文件不存在 / 无读取权限 → 提示并跳过
- 非代码文件（图片、二进制、数据文件）→ 说明不适用并跳过
- 包含语法错误的代码 → 仍然生成注释（注释不依赖代码可运行），并在结果末尾提示发现的语法问题
- 压缩 / 混淆 / 生成代码 → 提示该文件疑似生成物，询问是否仍要注释
- 超大文件（> 2000 行）→ 分段处理，按函数/类为单位逐段完成
- 空文件 / 纯注释文件 → 说明无需处理

### 第 2 步：扫描注释覆盖率（文件/目录级输入时执行）

运行扫描脚本获取量化基线：

```bash
python scripts/comment_scanner.py <路径> --format markdown
```

脚本输出：注释覆盖率、未注释的函数/类清单、疑似过期注释（文档参数与签名不符、TODO/FIXME 积压）。
按 `assets/templates/report.md` 模板向用户呈现报告，让用户确认处理范围后再继续。

常用选项：

| 选项 | 用途 |
|------|------|
| `--format json` | 机器可读输出，供 CI 消费 |
| `--min-coverage 80` | 覆盖率门禁：低于阈值时退出码为 1 |
| `--no-private` | 把私有/半私有符号排除出分母（默认计入，对齐 interrogate 语义） |
| `--include-tests` | 不跳过测试文件（默认跳过） |
| `--include-covered` | 报告中一并列出已文档符号 |

> 脚本为纯 Python 标准库实现，无第三方依赖；若环境无 Python，跳过此步，直接人工分析文件。

### 第 3 步：生成三级注释

按以下优先级顺序生成（用户指定级别时只做指定级别）：

**Level 1 — 文件头注释**（文件缺失时添加）
- 内容：模块职责一句话、主要对外能力、注意事项
- 不写：作者、日期、版本（交给版本控制系统）

**Level 2 — API 文档注释**（所有 public 函数/类/方法）
- 严格使用该语言的原生文档格式（各语言模板见 `references/language-styles.md`）
- 必含：功能描述、每个参数含义与约束、返回值、可能抛出的异常/错误
- 参数名必须与函数签名逐一核对，禁止臆造不存在的参数
- 有类型注解/类型系统时，不在文档中重复写类型（交给语言自身）

**Level 3 — 行内逻辑注释**（仅复杂逻辑）
- 触发条件：算法核心步骤、正则表达式、位运算、并发/锁、魔法值、绕过某 bug 的 workaround、非常规写法
- 位置：被解释代码的上一行，与代码同缩进

### 第 4 步：安全校验（修改文件后必须执行）

对每个被修改的文件运行安全校验，确保只有注释变化。

设原文件为 `app.py`，修改后为 `app.py.commenter.bak`（备份为原文件拷贝）时：

```bash
# 参数顺序：原始文件(备份)  修改后文件
python scripts/safety_check.py app.py app.py.commenter.bak
```

- 输出 `SAFE`（退出码 0）：确认无逻辑变更，完成该文件
- 输出 `UNSAFE`（退出码 1）：立即回滚该文件，重新只做注释修改
- 加 `--verbose` 可打印首个差异位置，便于定位问题

> **备份文件名的坑**：脚本已能识别 `.bak` / `.orig` / `.old` / `.commenter` 等备份后缀，
> 因此 `app.js.commenter.bak` 会被正确识别为 JavaScript 而非未知语言。
> 但**仍推荐**用 `<file>.commenter.bak` 这种保留真实扩展名的命名，可读性更好。

标准校验流程：

```
1. 复制原文件 → 备份（如 app.py → app.py.commenter.bak）
2. 在「修改后文件」上写入带注释的内容
3. 运行 safety_check.py <备份> <修改后文件>
4. SAFE  → 用修改后文件覆盖原文件，删除备份
   UNSAFE → 用备份覆盖回滚，检查差异后重试
```

**无 Python 环境时的替代做法**：用 `git diff` 逐行人工核对，确认每一处 `+`/`-` 行都只涉及注释。

### 第 5 步：输出总结

处理完成后向用户输出：

```markdown
## 注释生成完成

| 文件 | 新增文档注释 | 新增行内注释 | 安全校验 |
|------|------------|------------|---------|
| src/foo.py | 5 | 3 | ✅ SAFE |

- 覆盖率变化：42% → 91%
- 跳过：static/logo（非代码文件）
- 提醒：src/bar.py 第 88 行存在语法错误，已照常注释，建议修复
```

## 过期注释修复（可选，需用户确认）

当用户要求"修掉过期注释"而非只检测时，使用 `scripts/fix_stale.py`。
**该脚本默认 dry-run，只有显式加 `--apply` 才会写入文件**——这是刻意的安全默认值。

```bash
# 第 1 步：先预览会改什么（dry-run，不动文件）
python scripts/fix_stale.py ./src --diff

# 第 2 步：向用户展示待修正清单，取得确认

# 第 3 步：确认后写入（自动备份 → 修改 → 自检 → 通过则清理备份，失败则回滚）
python scripts/fix_stale.py ./src --apply --verbose
```

能修与不能修的边界：

| 类型 | 说明 | 是否自动修正 |
|------|------|------------|
| `param-extra` | 文档里记载了、但签名中已不存在的参数 | ✅ 删除该条目 |
| `param-missing` | 签名中有、但文档未提及的参数 | ❌ 仅报告（补写内容需语义判断） |
| `todo` | TODO / FIXME 积压（需 `--include-todos`） | ❌ 仅报告 |

**不要跳过用户确认直接 `--apply`**，除非用户已明确说"直接改"。

## 支持的语言

扫描与校验脚本内置 **21 种语言**规格、覆盖 **48 种文件扩展名**：

| 语言 | 文档注释风格 | 详细模板 |
|------|------------|---------|
| Python | Google 风格 Docstring（默认）/ NumPy / reST | references/language-styles.md §1 |
| JavaScript / TypeScript | JSDoc / TSDoc | references/language-styles.md §2 |
| Java | Javadoc | references/language-styles.md §3 |
| Go | godoc 惯例 | references/language-styles.md §4 |
| C / C++ | Doxygen | references/language-styles.md §5 |
| Rust | rustdoc（`///` + Markdown） | references/language-styles.md §6 |
| C# | XML 文档注释 | references/language-styles.md §7 |
| Kotlin | KDoc | references/language-styles.md §8 |
| PHP | PHPDoc | references/language-styles.md §9 |
| Shell / PowerShell / SQL / YAML 等 | 行注释惯例 | references/language-styles.md §10 |
| Ruby / Lua / R / Perl / Swift / Scala / Dart | 该语言行注释惯例 | references/language-styles.md §11 |

未列出的语言：采用该语言通用行注释符，参照 Level 1-3 原则生成。

## 示例

完整输入/输出示例见 `examples/` 目录：

- Python 函数补 Docstring：`examples/input-python.md` → `examples/output-python.md`
- Java 遗留代码全量注释：`examples/input-java.md` → `examples/output-java.md`
- 异常输入（语法错误代码）处理：`examples/input-broken.md` → `examples/output-broken.md`

## 已知限制

- 注释内容基于代码静态语义推断，无法获知运行时行为与业务背景；对含糊的业务逻辑会用中性描述并标注 `TODO(确认)` 供人工补充
- 非 Python 语言使用启发式解析，极端代码风格下符号识别可能有少量遗漏（不影响注释生成，仅影响统计精度）
- 不处理二进制、加密、超过 10 MB 的单文件
- 过期注释自动修正目前仅覆盖 Python 的 `param-extra` 类型

## 安全与合规

- 全程本地处理，脚本不发起任何网络请求、不上传代码
- 脚本只读分析 + 显式路径写入，不删除文件、不执行被分析的代码
- `fix_stale.py` 写入前自动备份，写入后调用 `safety_check.py` 自检，失败自动回滚
- 遇到源代码中疑似密钥/凭证（API Key、密码）时：不将其写入注释、不复述其值，并提醒用户存在泄露风险
