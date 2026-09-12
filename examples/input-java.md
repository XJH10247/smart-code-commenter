# 示例输入：Java 遗留代码全量注释

用户请求：

> 这是接手的老代码，一行注释都没有，帮我把注释补全

```java
public class RetryExecutor {

    private final int maxRetries;
    private final long baseDelayMs;

    public RetryExecutor(int maxRetries, long baseDelayMs) {
        this.maxRetries = Math.max(0, maxRetries);
        this.baseDelayMs = baseDelayMs;
    }

    public <T> T execute(Supplier<T> task, Predicate<Exception> retryable) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                return task.get();
            } catch (Exception e) {
                last = e;
                if (!retryable.test(e) || attempt == maxRetries) {
                    throw e;
                }
                long delay = baseDelayMs * (1L << attempt);
                Thread.sleep(Math.min(delay, 30_000L) + ThreadLocalRandom.current().nextLong(100));
            }
        }
        throw last;
    }
}
```
