# 示例输出：Java 遗留代码全量注释

```java
/**
 * 带指数退避的通用重试执行器。
 *
 * <p>由调用方通过 {@code retryable} 谓词决定哪些异常可以重试。
 *
 * <p>实例字段在构造后不变；任务和谓词的并发安全由调用方负责。
 */
public class RetryExecutor {

    /** 最大重试次数（不含首次执行），构造时低于 0 会被归一为 0。 */
    private final int maxRetries;

    /** 首次重试的基准延迟（毫秒），后续按 2 的幂次递增。 */
    private final long baseDelayMs;

    /**
     * 创建重试执行器。
     *
     * @param maxRetries  最大重试次数，负数按 0 处理（即只执行一次）
     * @param baseDelayMs 首次重试延迟毫秒数
     */
    public RetryExecutor(int maxRetries, long baseDelayMs) {
        this.maxRetries = Math.max(0, maxRetries);
        this.baseDelayMs = baseDelayMs;
    }

    /**
     * 执行任务，失败且异常可重试时按指数退避重试。
     *
     * <p>正常数值范围内按 base、2·base、4·base 递增，取与 30000ms
     * 的较小值后叠加 0-99ms 抖动。代码未校验负延迟或位移、乘法溢出，
     * 调用方应限制输入和重试次数；抖动后的总延迟可能超过 30 秒。
     *
     * @param <T>       任务返回值类型
     * @param task      待执行任务，要求幂等（可能被执行多次）
     * @param retryable 判断异常是否可重试的谓词
     * @return 任务成功时的返回值
     * @throws Exception 不可重试的异常直接抛出；重试耗尽时抛出最后一次异常
     */
    public <T> T execute(Supplier<T> task, Predicate<Exception> retryable) throws Exception {
        Exception last = null;
        // attempt=0 是首次执行，因此总执行次数 = maxRetries + 1
        for (int attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                return task.get();
            } catch (Exception e) {
                last = e;
                if (!retryable.test(e) || attempt == maxRetries) {
                    throw e;
                }
                // 大位移或乘法可能溢出；后续 Math.min 不会校验负延迟
                long delay = baseDelayMs * (1L << attempt);
                // 随机抖动打散并发重试时间点，缓解下游瞬时压力
                Thread.sleep(Math.min(delay, 30_000L) + ThreadLocalRandom.current().nextLong(100));
            }
        }
        throw last;
    }
}
```

生成说明：

- Level 1：说明类职责与实例字段不变性，不承诺外部任务和谓词的并发安全。
- Level 2：说明任务可能重复执行、参数范围未校验及实际延迟边界；不替用户修复这些代码问题。
- Level 3：只解释重试计数、溢出边界和抖动意图。
- 可执行源码未修改；校验通过仅表示所支持词法范围内一致，不证明描述语义或运行行为等价。
