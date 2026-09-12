# 示例输出：异常输入（含语法错误的代码）

Skill 不因语法错误而崩溃或拒绝服务——照常生成注释，并在结尾附上语法问题提醒。

```python
def parse_config(path)
    """解析 key=value 格式的配置文件为字典。

    逐行读取，跳过不含 "=" 的行；key 与 value 两端空白会被去除。
    同名 key 出现多次时，后出现的值覆盖先出现的值。

    Args:
        path: 配置文件路径，文件需可读。

    Returns:
        dict，键值均为去除首尾空白后的字符串。

    Raises:
        FileNotFoundError: path 指向的文件不存在。
    """
    data = {}
    with open(path) as f:
        for line in f:
            if "=" in line
                # 只按第一个 "=" 分割，保证 value 中允许再出现 "="
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data
```

---

**⚠️ 语法问题提醒**（注释已照常生成，但以下问题需要修复代码才能运行）：

| 位置 | 问题 | 建议 |
|------|------|------|
| 第 1 行 | `def parse_config(path)` 缺少冒号 | 改为 `def parse_config(path):` |
| 第 5 行 | `if "=" in line` 缺少冒号 | 改为 `if "=" in line:` |

生成说明（鲁棒性要点）：

- 语法错误不影响注释生成——注释基于代码意图静态推断，不要求代码可运行
- 未擅自修复语法错误（那属于代码变更，超出"只加注释"边界），仅以报告形式提醒
- 若用户随后要求"顺便修一下"，再作为独立的代码修改操作执行
