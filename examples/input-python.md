# 示例输入：Python 函数补 Docstring

用户请求：

> 帮我给下面这个函数加注释

```python
import re
from decimal import Decimal, ROUND_HALF_UP

def calc_final_price(items, coupon=None, vip_level=0):
    total = sum(Decimal(str(i["price"])) * i["qty"] for i in items)
    if coupon and re.match(r"^SAVE(\d{2})$", coupon):
        off = int(re.match(r"^SAVE(\d{2})$", coupon).group(1))
        total *= (Decimal(100 - off) / 100)
    if vip_level >= 3:
        total *= Decimal("0.95")
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```
