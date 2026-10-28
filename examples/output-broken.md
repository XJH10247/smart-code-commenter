# 示例输出：异常输入（含语法错误的代码）

以下是注释建议预览，尚未写入文件。语法错误不阻止生成建议，但无法据此证明源码安全；新增 docstring 的候选应标记为 UNVERIFIED，不自动替换原文件。

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

**语法问题提醒**（建议已生成，文件未写入）：

| 位置（按代码内容定位） | 问题 | 建议 |
|----------------------|------|------|
| `def parse_config(path)` | 缺少冒号 | 单独修复为 `def parse_config(path):` |
| `if "=" in line` | 缺少冒号 | 单独修复为 `if "=" in line:` |

生成说明：

- 校验结果：`UNVERIFIED`；破损语法下不能可靠证明新增字符串都是 docstring。
- 未修复语法错误、未替换原文件，仅提供注释建议与问题说明。
- 描述基于可见代码；无法确认的异常和业务约束应人工核对。
- 若用户随后要求修复语法，作为独立代码修改处理，再重新校验注释候选。
