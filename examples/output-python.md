# 示例输出：Python 函数补 Docstring

```python
import re
from decimal import Decimal, ROUND_HALF_UP

def calc_final_price(items, coupon=None, vip_level=0):
    """计算订单最终应付金额（优惠券与 VIP 折扣可叠加）。

    计算顺序固定为：合计原价 → 优惠券折扣 → VIP 折扣，
    顺序不同会导致金额差异，调整时需与计费侧口径对齐。

    Args:
        items: 商品明细列表，每项为含 "price"（单价）与 "qty"（数量）的 dict。
        coupon: 优惠券码，格式为 SAVE + 两位折扣数字（如 SAVE15 表示 85 折）；
            为 None 或格式不符时不参与计算，不报错。
        vip_level: 用户 VIP 等级，3 级及以上在券后价基础上再享 95 折。

    Returns:
        Decimal 类型的应付金额，四舍五入保留两位小数。

    Raises:
        KeyError: items 中缺少 "price" 或 "qty" 字段。
        InvalidOperation: price 字段无法转换为 Decimal。
    """
    # 用 str 中转构造 Decimal，避免 float 直接入参引入二进制精度误差
    total = sum(Decimal(str(i["price"])) * i["qty"] for i in items)
    if coupon and re.match(r"^SAVE(\d{2})$", coupon):
        # SAVE 后两位数字即折扣百分比：SAVE15 -> 减 15%
        off = int(re.match(r"^SAVE(\d{2})$", coupon).group(1))
        total *= (Decimal(100 - off) / 100)
    if vip_level >= 3:
        total *= Decimal("0.95")
    # ROUND_HALF_UP 与财务侧"四舍五入"口径一致，勿改为默认的银行家舍入
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

生成说明：

- Level 2 文档注释：Google 风格，参数与签名逐一对应，标注了 coupon 的容错行为
- Level 3 行内注释：只为 3 处非自明逻辑添加（Decimal 精度、券码语义、舍入口径），
  未给 `if vip_level >= 3` 这类自解释代码加注释
- 代码本身零改动，可通过 `safety_check.py` 校验（输出 SAFE）
