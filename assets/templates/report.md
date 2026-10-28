# 注释检查报告

- 扫描范围：{root}；排除配置：{excludes}
- 实际扫描文件：{scanned_count} 个；排除条目：{excluded_count} 个；跳过文件：{skipped_count} 个
- 排除条目可能是整个目录；数量仅统计已遇到的条目，不推算截断后未遍历的文件数
- 扫描完整性：{complete}；达到上限截断：{truncated}；读取或分析错误数：{errors}
- 分母口径：{scope}；可计符号：{symbol_count} 个；非空文档：{documented_count} 个
- **文档存在率：{coverage}**（无可计符号时不适用，不表示内容正确）
- 门禁：{gate_result}（用未舍入计数判断；不完整扫描不得称为全项目达标）

## 各文件明细

| 文件 | 语言 | 分析方式 | 符号数 | 文档存在率 | 警告 |
|------|------|----------|--------|------------|------|
| {path} | {language} | {parse_mode} | {symbols} | {coverage} | {warning} |

## 缺少文档注释的符号

- `{path}:{line}` — {kind} `{name}`

## 已文档符号（指定 --include-covered 时列出）

- `{path}:{line}` — {kind} `{name}`

## 参数结构诊断

- `{path}:{line}` — {code} `{symbol}`：{message}

区分缺失参数、多余参数和可确认的顺序问题；存在率不是结构完整率。

## TODO / FIXME 提醒

- `{path}:{line}` — {content}

标记存在不代表注释已过期，不自动推断积压时间。

## 排除、跳过与未完成项

- `{path}` — {reason}

## 内容待确认

- `{path}:{line}` — {question}（缺少业务依据，只供人工确认，不自动写入源码）

## 实际处理结果

| 文件 | 写入状态 | 校验方式 | 校验结果 | 原因或备份位置 |
|------|----------|----------|----------|----------------|
| {path} | {write_status} | {verification_method} | {verdict} | {detail} |

区分请求写入与实际成功；UNVERIFIED、读取错误或修复失败不能写成 SAFE。
仅在前后范围、配置相同且扫描完整时展示存在率变化。
请用户确认处理范围：全部 / 指定文件 / 仅 public API。
