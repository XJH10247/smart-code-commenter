# 变更日志

本文件记录本项目的所有重要变更。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 计划中
- 支持 Java / Go / TypeScript 的过期注释自动修正（当前仅 Python）
- 提供 pre-commit hook 集成示例

---

## [1.2.0] - 2026-09-20

一次以**结构规范化与 GitHub 可发布性**为核心的整理版本。对照
[Agent Skills 开放规范](https://agentskills.io/specification) 与 skill-creator
校验器，调整目录布局并修正文档路径，使仓库可直接上传 GitHub 并作为 Skill 安装。

### 新增

- `references/language-styles.md` — 原根目录 `reference.md` 迁入 `references/`，
  对齐 Agent Skills progressive disclosure 约定（细节按需加载）。
- `assets/templates/report.md` — 原 `templates/report.md` 迁入 `assets/`，
  对齐规范中 `assets/` 存放模板/静态资源的约定。
- README 补充 MiMo Desktop / MiMoCode（全局与项目级）安装路径。
- SKILL.md frontmatter 增加 `compatibility`（脚本需 Python 3.8+，无 Python 时
  可走提示词降级）与 `metadata.version` / `languages` / `extensions`。
- SKILL.md 增加明确的**负向触发**（不要用于改逻辑、写测试、写 README 等）。

### 变更

- **目录结构**对齐 Agent Skills：`SKILL.md` + `scripts/` + `references/` + `assets/`。
  所有文档中的路径引用已同步更新。
- `description` 补入英文 `Use when ...` 子句，满足跨客户端路由与 skill-creator
  校验器对 WHEN 条件的检测；中文触发短语保持不变。
- frontmatter 顶层非标准的 `version` 字段移入 `metadata.version`；
  `license: MIT` 保留（规范允许）。
- 安装章节说明：`README.md` 仅服务 GitHub 人类读者，不参与 Skill 路由；
  严格校验场景可排除 README 安装。
- 测试徽章与正文统一为 **128 项通过**（此前徽章写 121、正文写 128）。

### 修复

- SKILL.md 总结示例中的 `assets/logo.png` 会被路径校验器误判为引用缺失文件；
  改为无 `assets/` 前缀的示例路径。
- `comment_scanner.py` 文档字符串中的 `templates/report.md` 路径更新为
  `assets/templates/report.md`。

### 兼容性说明

- 脚本行为、CLI 参数与退出码契约**无变更**，仅文档路径与仓库布局调整。
- 若你通过硬编码路径引用 `reference.md` 或 `templates/report.md`，请改为
  `references/language-styles.md` 与 `assets/templates/report.md`。

---

## [1.1.0] - 2026-09-12

一次以**修复正确性缺陷**为核心的审计版本。经联网调研对照官方规范后，修正了两处会导致
工具在正常使用场景下误判的致命缺陷，并将三个脚本的语言知识统一到单一数据源。

### 新增

- `scripts/langspec.py` — **单一可信来源**的语言规格表。登记 21 种语言、48 种扩展名，
  统一提供行注释符、块注释定界符、文档注释前缀、嵌套能力与内容特征探测。
  此前 `comment_scanner.py`（17 种）与 `safety_check.py`（21 种）各维护一份语言表，
  口径不一致，是本项目多处缺陷的共同根因。
- `scripts/fix_stale.py` — 过期注释修复器。检测"文档里写了但签名中已不存在"的参数条目，
  **默认 dry-run**，`--apply` 才写入；写入前自动备份、写入后调用 `safety_check.py` 自检，
  自检失败自动回滚。支持 `--diff` 输出 unified diff 预览、`--format json` 供 CI 消费。
- `tests/` — 零依赖自测套件。`test_skill.py`（110 项）覆盖语言探测、文档注释识别、
  多语言符号解析、AST 与降级路径、注释行统计、路径缩短、CLI 退出码契约、健壮性；
  `test_fix_stale.py`（18 项）覆盖参数提取、dry-run 语义、写入正确性、幂等性。
- `comment_scanner.py` 新增 `--min-coverage PCT` 覆盖率门禁，可直接用于 CI。
- `CHANGELOG.md`、`CONTRIBUTING.md`、`LICENSE`、`.gitignore`。

### 修复

- **【致命】`safety_check.py` 在备份文件上会误判合法操作为 UNSAFE。**
  此前 SKILL.md 指导用户运行 `safety_check.py <原文件> <原文件>.commenter.bak`，
  但脚本按扩展名判断语言，`.commenter.bak` 取不到扩展名 → 回退到默认的 `#` 注释符 →
  JS / Java / C 等语言的 `//` 与 `/* */` 完全剥离不掉 → 任何 CRLF 差异、空白差异都被
  当成代码变更，**加注释这一正常操作必然报 UNSAFE 并触发回滚**。
  现在 `detect_language()` 会剥离 `.bak` / `.orig` / `.old` / `.save` / `.tmp` / `.commenter`
  等 10 种备份后缀再识别；`app.js.commenter.bak` 正确识别为 JavaScript。

- **【致命】语法错误文件走 token 降级路径时，新增 docstring 必然误判 UNSAFE。**
  这是 `examples/output-broken.md` 所描述场景（用户给含语法错误的代码加注释）的真实阻断：
  AST 解析失败后降级到 token 比对，而 docstring 在 token 流中就是普通 `STRING`，
  新增它必然产生 token 差异。现在 `_normalize_python_docstrings()` 先用 `tokenize` 定位
  块首字符串并按坐标原地替换为哨兵，`python_token_fingerprint()` 丢弃哨兵 token，
  使降级路径也能正确区分"改注释"与"改代码"。

- `comment_scanner.py`：**符号解析从 10 种语言扩展到 20 种。** 此前 Ruby / Lua / R /
  Shell / PowerShell / SQL / Scala / Swift / Dart / Perl 的符号数恒为 0，
  覆盖率在这些语言上永远显示 100%（分母为 0），是严重的统计失真。

- `comment_scanner.py`：文档注释识别改为"向上扫描连续注释块"。
  此前只检查紧邻的上一行，导致"JSDoc + 一行补充 `//` 注释 + 函数"这类常见写法被误判为
  未文档化；现在会跨越整段连续注释区，再用三类判据确定是否为文档注释。

- `comment_scanner.py`：私有/半私有符号**默认计入分母**，对齐 `interrogate` 的语义。
  此前默认排除，导致覆盖率虚高。需要旧行为可用 `--no-private`。

- `comment_scanner.py`：minified 检测改为全文等距采样。
  此前只看前 50 行，长文件中的压缩代码段会被漏判。

- `comment_scanner.py`：**`--format text` 报告把文件名截没了。**
  原实现用 `path[:50]` 从右侧硬截断，55 字符的路径被切成 `...\smoke-xxx\a`，
  导致同目录下 `a.py` / `a.js` / `a.go` 在报告里显示成完全相同的名字，
  多文件报告失去辨识能力（尾部 `%-50s` 填充还掩盖了截断事实）。
  现在改为保留文件名、从左侧省略目录前缀。

- `fix_stale.py`：**CRLF 行尾文件上修正静默失效。** 比对时只 `rstrip("\n")`，
  而 Windows 文件的 `\r` 残留导致比对永远不等 → `apply_extra_param_removal()` 返回 False →
  报"已修正 0 个文件"却不报错。

- `fix_stale.py`：**NumPy 风格 docstring 的参数提取返回空。** NumPy 风格的参数条目与
  `Parameters` 标题**同缩进**（靠下一行的 `----------` 区分），而原实现假定条目缩进更深，
  导致所有条目被跳过。现在通过探测标题后的分隔下划线动态下调条目层级。

- `SKILL.md`：修正第 4 步中错误的校验命令示例（原示例传给脚本的参数顺序与备份命名
  自相矛盾，直接导致上述第一个致命缺陷）。

### 变更

- `SKILL.md` 语言支持表与 README 统一为实测的 **21 种语言 / 48 种扩展名**
  （此前 SKILL.md 写 10 种、README 写 "10+"、扫描器实际 17 种、校验器实际 21 种）。
- `reference.md` 依据官方规范补充：Go 的 `// Deprecated:`（须独立成段）/ `// BUG(who)` /
  Go 1.19+ 的 `# 标题` 与 `[Link]` 记号；TSDoc 相对 JSDoc 的差异对照表
  （`@remarks`、`@typeParam`、`@defaultValue`、`@beta`、`{@link}`）；
  Javadoc 的 `@param` 两空格对齐与 `@throws` "if clause" 惯例；
  rustdoc 的 doctest 语义与 clippy lint 约束；Doxygen 的 `@retval`；
  以及全新的 §11 覆盖 Ruby(YARD) / Lua(LDoc) / R(roxygen2) / Swift(DocC) /
  Scala(Scaladoc) / Dart(dartdoc) / Perl(POD)。
- `reference.md` 修正 **KDoc 不存在 `@deprecated` 标签**——Kotlin 生态用 `@Deprecated`
  注解而非文档标签，原文档照搬 Javadoc 写法会误导使用者。
- `reference.md` 补充 Python 三种 docstring 风格的等价对照与风格判别方法，
  以及"什么代码不需要行内注释"的判定清单。

### 移除

- `SKILL.md` frontmatter 中的 `author` 字段（内容为赛事作品署名，不适合作为
  Agent Skills 规范字段发布）。

---

## [1.0.0] - 2026-08-20

### 新增
- 首个发布版：三级注释体系（文件头 / API 文档注释 / 行内逻辑注释）
- `comment_scanner.py` 注释覆盖率扫描器
- `safety_check.py` 零逻辑变更校验器
- 10+ 语言的文档注释风格参考（`reference.md`）
- 覆盖率报告模板与三组输入输出示例

[Unreleased]: #
[1.2.0]: #
[1.1.0]: #
[1.0.0]: #
