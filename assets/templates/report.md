# 注释覆盖率报告

- 扫描文件：{scanned_count} 个（跳过 {skipped_count} 个）
- 可注释符号：{symbol_count} 个，已有文档注释：{documented_count} 个
- **总体文档覆盖率：{coverage}%**

## 各文件明细

| 文件 | 语言 | 代码行 | 注释行 | 符号数 | 文档覆盖率 |
|------|------|-------|-------|-------|-----------|
| {path} | {language} | {total_lines} | {comment_lines} | {symbols} | {coverage}% |

## 缺少文档注释的符号（建议优先处理）

- `{path}:{line}` — {kind} `{name}`

## TODO / FIXME 积压

- `{path}` 第 {line} 行 [{tag}] {content}

## 疑似过期/异常注释

- `{path}` {warning}

## 跳过的文件

- `{path}`（{skip_reason}）

---

## 处理建议（报告末尾向用户给出）

1. 优先补齐"缺少文档注释的符号"中覆盖率最低的文件
2. 核对"疑似过期注释"，修正后再批量生成
3. 请确认处理范围：全部 / 指定文件 / 仅 public API
