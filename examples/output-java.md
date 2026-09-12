# 示例输出：Java 遗留代码全量注释

```java
/**
 * 带指数退避的通用重试执行器。
 *
 * <p>适用于调用不稳定的外部依赖（HTTP、RPC、MQ 等）。由调用方通过
 * {@code retryable} 谓词决定哪些异常值得重试，避免对业务异常盲目重试。
 *
 * <p>线程安全：本类无可变状态，可作为单例被多线程共享。
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
     * <p>退避序列为 base、2·base、4·base……单次延迟封顶 30 秒，
     * 并叠加 0-100ms 随机抖动以避免集群内重试风暴。
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
                // 位移实现 2^attempt 指数退避；封顶 30s 防止延迟无限膨胀
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

- Level 1：类级 Javadoc 说明职责、适用场景与线程安全性（遗留代码最缺的信息）
- Level 2：构造器与 public 方法的完整 Javadoc，特别标注了 task 需幂等这一隐含约束
- Level 3：仅为 3 处易误读逻辑加行内注释（attempt 起点语义、位移退避、抖动目的）
- 代码逻辑零改动
