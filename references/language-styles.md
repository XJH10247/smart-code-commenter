# 各语言文档注释风格参考

本文件是 `smart-code-commenter` 的详细风格规范（progressive disclosure 二级资源），
按需查阅对应章节。所有模板中的中文描述在用户要求英文注释时替换为英文，结构不变。

风格依据：[PEP 257](https://peps.python.org/pep-0257/)、
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)、
[JSDoc](https://jsdoc.app/)、[TSDoc](https://tsdoc.org/)、
[Go Doc Comments](https://go.dev/doc/comment) 与
[Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)、
各语言官方文档生成器约定。

---

## §1 Python — Google 风格 Docstring（默认）

```python
def transfer(from_account: str, to_account: str, amount: Decimal) -> str:
    """在两个账户之间执行转账并返回流水号。

    金额校验失败或余额不足时整个操作回滚，不产生任何流水。

    Args:
        from_account: 转出账户 ID，必须为已激活状态。
        to_account: 转入账户 ID，不能与转出账户相同。
        amount: 转账金额，必须为正数，精度最多两位小数。

    Returns:
        本次转账的唯一流水号（26 位 ULID）。

    Raises:
        InsufficientBalanceError: 转出账户余额不足。
        AccountFrozenError: 任一账户处于冻结状态。
    """
```

要点：
- 首行为一句话概括，动词开头，句号结尾（PEP 257：摘要行与 `"""` 同行）；
- `Args` / `Returns` / `Yields` / `Raises` / `Attributes` 段按需出现，参数名后不写类型（类型注解已表达）；
- **生成器函数写 `Yields:` 而不是 `Returns:`**（Google 风格明确要求）；
- 参数描述跨多行时续行再缩进一级，与参数名区分；
- 类 docstring 描述职责与典型用法，`Attributes:` 段列公开属性；
- 项目已用 NumPy 风格（`Parameters\n----------`）或 reST 风格（`:param x:`）时跟随项目；
- TODO 注释统一为 `TODO(username): 描述`（Google 风格；可用 `TODO(确认)` 表示待业务确认）。

NumPy 风格对照（同一函数的等价写法）：

```python
def transfer(from_account: str, to_account: str, amount: Decimal) -> str:
    """在两个账户之间执行转账并返回流水号。

    Parameters
    ----------
    from_account : str
        转出账户 ID，必须为已激活状态。
    to_account : str
        转入账户 ID，不能与转出账户相同。
    amount : Decimal
        转账金额，必须为正数，精度最多两位小数。

    Returns
    -------
    str
        本次转账的唯一流水号（26 位 ULID）。

    Raises
    ------
    InsufficientBalanceError
        转出账户余额不足。
    """
```

reST 风格对照：

```python
def transfer(from_account: str, to_account: str, amount: Decimal) -> str:
    """在两个账户之间执行转账并返回流水号。

    :param from_account: 转出账户 ID，必须为已激活状态。
    :param to_account: 转入账户 ID，不能与转出账户相同。
    :param amount: 转账金额，必须为正数。
    :returns: 本次转账的唯一流水号。
    :raises InsufficientBalanceError: 转出账户余额不足。
    """
```

> 三种风格**不要混用**。判断项目用哪种：`Parameters` + `----------` → NumPy；
> 参数行以 `:param ` 开头 → reST；`Args:` 小节 → Google。

## §2 JavaScript / TypeScript — JSDoc / TSDoc

```javascript
/**
 * 对输入的订单列表按创建时间去重合并。
 *
 * 相同 orderId 只保留 createdAt 最新的一条；输入不会被修改。
 *
 * @param {Order[]} orders - 待合并的订单数组，可为空数组。
 * @returns {Order[]} 去重后的新数组，按 createdAt 升序。
 * @throws {TypeError} orders 不是数组时抛出。
 */
```

要点：
- **文件级**：文件顶部 `/** ... */` 模块块，或用 `@fileoverview` / `@module` 显式标注；
- **必须以 `/**` 开头**才能被 JSDoc 解析；以 `/*`、`/***` 或超过 3 个星号开头的块会被忽略；
- TypeScript 中省略 `{类型}`（类型系统已表达），只写 `@param name - 描述`；JS 中保留 `{类型}`；
- **描述与标签之间空一行**，JSDoc 会把首个空行前的内容当作摘要；
- React 组件：注释写在组件上方，Props 逐字段用 `/** */` 注释在接口定义处；
- 导出的常量/类型别名用单行 `/** 描述 */`。

TSDoc（TypeScript 项目首选，用 `@microsoft/tsdoc` 校验）的差异点：

| JSDoc 写法 | TSDoc 写法 | 说明 |
|-----------|-----------|------|
| `@param {string} name` | `@param name` | 类型交给 TS 类型系统 |
| `@template T` | `@typeParam T` | 泛型参数 |
| `@default` | `@defaultValue` | 默认值说明 |
| （无） | `@remarks` | 摘要之后的详细说明块 |
| （无） | `@privateRemarks` | 只留在源码、不进生成的文档 |
| （无） | `@beta` / `@alpha` / `@internal` | 发布级别标记 |
| `@see foo` | `{@link foo}` | TSDoc 用行内链接标记 |

TSDoc 范例：

```typescript
/**
 * 对输入的订单列表按创建时间去重合并。
 *
 * @remarks
 * 相同 orderId 只保留 createdAt 最新的一条；输入数组不会被修改。
 * 时间复杂度 O(n log n)，依赖 {@link OrderService.normalize} 保证时间戳可解析。
 *
 * @typeParam T - 订单类型，必须含 `orderId` 与 `createdAt` 字段。
 * @param orders - 待合并的订单数组，可为空数组。
 * @returns 去重后的新数组，按 createdAt 升序。
 * @throws {@link OrderFormatError} 当 `orders` 含缺失 `orderId` 的元素时抛出。
 *
 * @defaultValue 无输入时返回 `[]`，不返回 `undefined`。
 * @beta 该 API 的返回顺序在 2.0 前可能调整。
 */
```

## §3 Java — Javadoc

```java
/**
 * 计算购物车应付总额（含税、含优惠券抵扣）。
 *
 * <p>优惠券不可叠加，多张时自动选择抵扣额最大的一张。
 *
 * @param cart    购物车快照，不能为 {@code null}
 * @param coupons 用户可用优惠券列表，可为空列表
 * @return 应付金额，最小值为 0，不会为负
 * @throws PricingException 商品价格数据缺失时抛出
 */
```

要点：
- 首句以句号结束（Javadoc 用**首句**生成摘要表，因此首句必须能独立表意）；
- 空行分隔段落用 `<p>`，段落内换行不生效；
- `@param` 描述与参数名**用两个空格对齐**（Oracle 惯例，非 tab）；
- `@throws` 写成 "if clause"——描述**触发条件**而非重复异常名，如
  `@throws PricingException if 商品价格数据缺失`；
- 空值约束用 `{@code null}` 明确写出，不要用裸 `null`（会被当成普通文本）；
- 不安全/已废弃/自明方法：`@deprecated` 必须给出替代方案（`{@link #newMethod}`）；
  getter/setter 等自明方法可只写一行摘要；
- 代码示例用 `<pre>{@code ...}</pre>`，避免 `<` `>` 被当 HTML 解析。

## §4 Go — godoc 惯例

```go
// MergeOrders 按创建时间对订单去重合并。
//
// 相同 ID 只保留最新一条，输入切片不会被修改。
// 输入为 nil 时返回空切片而非 nil。
func MergeOrders(orders []Order) []Order {
```

要点：
- 注释以被注释的**标识符名开头**（godoc 硬性惯例），如 `// MergeOrders ...`；
- **完整句子**，句号结尾；描述**做了什么**（"returns / writes / encodes"），不是"这个函数是…"；
- 无 `@param` 标签体系，参数约束用自然语言写入正文；
- 首行是摘要，之后空一行再写详情；
- 包注释必须**紧邻 `package` 语句且中间无空行**，或写在独立的 `doc.go`；
  `package main` 可用 `// Command xxx ...` / `// Binary xxx ...` 开头。

godoc 的特殊记号（Go 1.19+，写对了会被 `go doc` 特殊渲染）：

| 记号 | 用途 |
|------|------|
| `// Deprecated: 用 NewXxx 代替。` | **必须单独成段**，会被 `go doc` 高亮并在 IDE 中划删除线 |
| `// BUG(用户名): 描述` | 标记已知缺陷，`go doc` 会汇总展示 |
| `# 标题` | 文档小节标题（替代旧式全大写行） |
| `[MergeOrders]` | 链接到同包标识符；`[fmt.Println]` 链接到其他包 |
| `//go:build linux` | 构建约束，**必须**紧跟空行前、无其他内容 |

```go
// Deprecated: 改用 [NewClientWithTimeout]，本函数在 2.0 移除。
// 保留仅为兼容 v1 调用方。
func NewClient(addr string) *Client {

// BUG(zhaosi): 时区为 UTC 且跨月时，月末结算日期会少一天。见 issue #4821。
func settleMonth(t time.Time) (time.Time, error) {
```

```go
// Package order 提供订单聚合与结算能力。
//
// # 并发安全
//
// 本包所有导出的方法均可并发调用；内部状态由 [sync.RWMutex] 保护。
//
// # 快速开始
//
//	c := order.NewClient(addr)
//	orders, err := c.List(ctx)
//
// 更复杂的用法见 [order.Service]。
package order
```

> `// Deprecated:` 若和普通文本挤在同一段，**不会**触发弃用提示。必须是独立段落，
> 且首选写法是紧跟其后再空一行。扫描器会对此给出提醒。

## §5 C / C++ — Doxygen

```cpp
/**
 * @brief 环形缓冲区写入数据，满时覆盖最旧数据。
 *
 * 线程安全性：仅在单生产者单消费者场景下无锁安全。
 *
 * @param[in]  data 待写入的字节指针，不能为 NULL
 * @param[in]  len  写入长度，超过缓冲区容量时截断为容量大小
 * @return 实际写入的字节数
 */
```

要点：
- `@param[in]` / `@param[out]` / `@param[in,out]` 标明方向；
- 涉及指针的必须写明所有权与生存期约束（谁分配、谁释放）；
- `@brief` 一行摘要，`@details` 或不带标签的后续段落写详情；
- 头文件声明处写完整 Doxygen，实现文件可只写实现要点；
- 返回码/错误用 `@retval` 逐个说明，比在 `@return` 里堆句子清晰：

```cpp
/**
 * @brief 打开配置文件并解析。
 * @param[in]  path 配置文件路径，UTF-8 编码，不能为 NULL
 * @param[out] cfg  解析结果写入此处；成功前内容未定义
 * @retval  0  成功
 * @retval -1  文件不存在或无读权限
 * @retval -2  格式错误，出错位置写入 errno
 * @note 调用方负责释放 cfg 内部持有的缓冲区（见 cfg_free）。
 */
```

## §6 Rust — rustdoc

```rust
/// 按创建时间对订单去重合并。
///
/// 相同 `id` 只保留最新一条，输入不会被修改。
///
/// # Errors
///
/// 订单时间戳无法解析时返回 [`MergeError::BadTimestamp`]。
///
/// # Examples
///
/// ```
/// let merged = merge_orders(&orders)?;
/// ```
pub fn merge_orders(orders: &[Order]) -> Result<Vec<Order>, MergeError> {
```

要点：
- `///` + Markdown；章节惯例：`# Errors`、`# Panics`、`# Safety`（unsafe 函数必写）、`# Examples`；
- crate / 模块级用 `//!`（`//!` 是"描述外层条目"，`///` 是"描述下一个条目"，不要混）；
- **`# Examples` 里的代码块会被 `cargo test` 当作 doctest 编译执行**——所以示例必须真实可跑，
  写不了可运行的示例就用 ```` ```no_run ```` 、```` ```ignore ```` 或 ```` ```text ```` 标注；
- 建议在 crate 根加 `#![warn(missing_docs)]`，让编译期提醒缺失文档；
- 交叉引用用 rustdoc 链接语法：`[`MergeError::BadTimestamp`]`（同路径可省略半截）；
- clippy 的 `missing_errors_doc` / `missing_panics_doc` lint 会强制要求 `# Errors` / `# Panics` 章节，
  写 `pub fn` 时优先满足，避免 CI 报警。

## §7 C# — XML 文档注释

```csharp
/// <summary>
/// 计算购物车应付总额（含税、含优惠券抵扣）。
/// </summary>
/// <param name="cart">购物车快照，不能为 <c>null</c>。</param>
/// <param name="coupons">可用优惠券列表，可为空。</param>
/// <returns>应付金额，最小为 0。</returns>
/// <exception cref="PricingException">商品价格数据缺失时抛出。</exception>
```

## §8 Kotlin — KDoc

```kotlin
/**
 * 计算购物车应付总额（含税、含优惠券抵扣）。
 *
 * 优惠券不可叠加，多张时自动选择抵扣额最大的一张。
 *
 * @param cart 购物车快照
 * @param coupons 可用优惠券列表，可为空
 * @return 应付金额，最小为 0
 * @throws PricingException 商品价格数据缺失时抛出
 * @sample com.example.pricing
 */
```

要点：

- **KDoc 没有 `@deprecated` 标签**。标记弃用要同时用 `@Deprecated` 注解（供编译器）
  和 `@deprecated` 标签（供文档）——Dokka 只识别注解驱动的弃用，写错的标签会被当作普通文本。
  正确写法是两者并存：

```kotlin
@Deprecated("改用 calculateTotalWithPromotion", ReplaceWith("calculateTotalWithPromotion(cart)"))
fun calculateTotal(cart: Cart): Money { /* ... */ }
```

- `@param` / `@return` / `@throws` / `@sample` / `@see` / `@author` / `@since` 是完整标签集；
- 与 Java 不同的三个 Kotlin 专属标签：

| 标签 | 用途 | 示例 |
|------|------|------|
| `@receiver` | 描述扩展函数的接收者 | `fun String.toSlug()` → `@receiver 待转换的原始字符串` |
| `@constructor` | 描述主构造函数 | 写在类 KDoc 中，说明构造参数语义 |
| `@property` | 描述 `val`/`var` 属性 | 用于构造函数中声明的属性 |

```kotlin
/**
 * 将浮点数金额格式化为带货币符号的字符串。
 *
 * @receiver 待格式化的金额，单位元。
 * @param locale 目标区域，决定小数位与千分位符号。
 * @return 形如 `¥1,234.56` 的字符串。
 */
fun Double.toCurrency(locale: Locale = Locale.CHINA): String
```

## §9 PHP — PHPDoc

```php
/**
 * 计算购物车应付总额（含税、含优惠券抵扣）。
 *
 * @param CartSnapshot $cart    购物车快照
 * @param Coupon[]     $coupons 可用优惠券列表，可为空数组
 * @return Money 应付金额，最小为 0
 * @throws PricingException 商品价格数据缺失时抛出
 */
```

## §10 SQL / Shell / 配置类

**SQL**：每个对象定义上方写用途块注释；复杂查询按逻辑段落注释。

```sql
-- 统计近 30 天各渠道的下单转化率
-- 口径：转化率 = 支付成功订单数 / 渠道 UV，UV 来自 dws_traffic_daily
SELECT ...
```

**Shell / PowerShell**：脚本头部写用途、依赖、用法三要素。

```bash
#!/usr/bin/env bash
# 用途：滚动重启指定服务的所有实例（每次一台，健康检查通过后继续）
# 依赖：kubectl >= 1.24，需已配置目标集群 context
# 用法：./rolling-restart.sh <service-name> [namespace]
```

**YAML / TOML / INI 配置**：为非自明的键写行尾或上一行注释，说明取值范围与影响。

---

## §11 Ruby / Lua / R / Swift / Scala / Dart / Perl

这些语言没有形成统一强制工具链的文档注释规范，遵循"块注释 + 该语言惯用标签"即可。

### Ruby — RDoc / YARD

```ruby
# 按创建时间去重合并订单。
#
# @param orders [Array<Order>] 待合并的订单数组，可为空数组
# @return [Array<Order>] 去重后的新数组，按 createdAt 升序
# @raise [OrderFormatError] 元素缺失 orderId 时抛出
# @example 基本用法
#   merge_orders([]) # => []
def merge_orders(orders)
```

- `# frozen_string_literal: true` 之后、类/模块之前写文件头注释；
- RDoc 用 `#--` / `#++` 标记"不生成文档"的区段；
- YARD 标签：`@param`、`@return`、`@raise`、`@example`、`@yield`、`@yieldparam`、`@option`。

### Lua — LDoc

```lua
--- 按创建时间去重合并订单。
-- 相同 id 只保留最新一条。
-- @tparam table orders 待合并的订单数组
-- @treturn table 去重后的新数组
-- @raise 元素缺失 id 时抛出错误
function M.merge_orders(orders)
```

- 文档注释用 `---`（三个连字符），普通注释用 `--`；LuaDoc 用 `--[[ ... ]]` 块；
- 空行以 `--` 延续即可保持在同一文档块内。

### R — roxygen2

```r
#' 按创建时间去重合并订单
#'
#' 相同 id 只保留最新一条，输入不会被修改。
#'
#' @param orders 待合并的订单数据框
#' @return 去重后的数据框，按 created_at 升序
#' @export
#' @examples
#' merge_orders(data.frame())
merge_orders <- function(orders) {
```

- 必须用 `#'`（`#` + 单引号），生成的 `.Rd` 文件由 roxygen2 管理；
- `@export` 决定是否写入 `NAMESPACE`，漏写会导致函数对外不可见——**这是最常见的坑**。

### Swift — DocC

```swift
/// 计算购物车应付总额（含税、含优惠券抵扣）。
///
/// 优惠券不可叠加，多张时自动选择抵扣额最大的一张。
///
/// - Parameters:
///   - cart: 购物车快照
///   - coupons: 可用优惠券列表，可为空
/// - Returns: 应付金额，最小为 0
/// - Throws: `PricingError.missingPrice` 当商品价格缺失时
func calculateTotal(cart: Cart, coupons: [Coupon]) throws -> Money
```

- 用 `///` 或 `/** */`；概览段落用 DocC 记号 `- Parameters:` / `- Returns:` / `- Throws:`
  （注意冒号，且用 `-` 列表缩进，与 Javadoc 的 `@param` 完全不同）；
- 符号链接用双反引号 `` ` `` `MergeError` `` ` `` 或 DocC 的 `` ``Symbol`` `` 语法；
- 文章/教程页用 ` `` ```` 代码块 `` `` ` 与 `- Note:` / `- Warning:` 标注块。

### Scala — Scaladoc

```scala
/**
 * 按创建时间去重合并订单。
 *
 * @param orders 待合并的订单集合
 * @tparam T 订单类型，必须含 id 与 createdAt
 * @return 去重后的新集合，按 createdAt 升序
 * @throws OrderFormatError 元素缺失 id 时抛出
 * @see [[OrderService.normalize]]
 */
def mergeOrders[T <: Order](orders: Seq[T]): Seq[T]
```

- 与 Javadoc 几乎一致，差异：泛型参数用 `@tparam`（不是 `@param <T>`），
  交叉引用用 `[[...]]`（不是 `{@link ...}`）；
- Scaladoc 首句同为摘要行。

### Dart — dartdoc

```dart
/// 按创建时间去重合并订单。
///
/// 相同 [Order.orderId] 只保留最新一条，输入列表不会被修改。
///
/// 抛出 [OrderFormatError] 当元素缺失 orderId 时。
List<Order> mergeOrders(List<Order> orders) { ... }
```

- 全用 `///`（`/** */` 不会被 dartdoc 解析）；
- 方括号 `[Order.orderId]` 自动生成文档链接，**是 Dart 生态最强调的写法**；
- 首行摘要后必须空一行；`library` 级注释写在 `library;` 声明上方或用 `///` 开头。

### Perl — POD

```perl
=head2 merge_orders

按创建时间去重合并订单。相同 C<id> 只保留最新一条。

=head3 参数

=over

=item * C<$orders> - 待合并的数组引用

=back

=head3 返回

去重后的数组引用。

=cut
```

- POD 指令从行首第一个字符开始（`=head2`、`=item`、`=over`/`=back`、`=cut`），
  前面不能有缩进；正文段落则需缩进；
- 行内标记：`C<代码>`、`B<粗体>`、`I<斜体>`、`L<链接>`；
- `=cut` 之前必须有空行，否则 POD 解析器报错。

---

## 附：行内注释（Level 3）质量对照

| ❌ 差（复述代码） | ✅ 好（解释意图/约束） |
|---|---|
| `// 循环所有用户` | `// 逆序遍历：删除元素时避免索引偏移` |
| `// 设置超时为 30` | `// 30s 与网关上限对齐，超过会被 LB 先行掐断` |
| `// 调用 API` | `// 该接口幂等，失败重试最多 3 次不会重复扣款` |
| `# 正则匹配` | `# 匹配 ISO8601 且强制毫秒段，旧客户端不带毫秒需走 fallback` |
| `// i 加 1` | `// 跳过表头行，数据从索引 1 开始` |
| `// 返回结果` | `// 返回副本而非引用：调用方会就地排序，不能污染缓存` |
| `// TODO: 优化` | `// TODO(确认): 单批超 1 万条时内存翻倍，需评估是否改流式` |

### 什么样的代码**不需要**行内注释

| 场景 | 说明 |
|------|------|
| 自解释的取名 | `const MAX_RETRY = 3` 不需要注释解释它是"最大重试次数" |
| 标准库惯用调用 | `list.sort()` / `arr.map()` 不需要解释 |
| 短小纯函数 | 三行以内的取值、拼接、判空 |
| 文档注释已覆盖 | 函数级 docstring 说清了，行内不要重复 |
| 显而易见的控制流 | `if (user == null) return;` 不需要"如果用户为空则返回" |

判断标准：**注释删掉之后，读者会不会误解或写错？** 不会就别加。


