# 示例输入：异常输入（含语法错误的代码）

用户请求：

> 给这段代码加注释

```python
def parse_config(path)
    data = {}
    with open(path) as f:
        for line in f:
            if "=" in line
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data
```

（注意：第 1 行与第 5 行缺少冒号，代码无法运行）
