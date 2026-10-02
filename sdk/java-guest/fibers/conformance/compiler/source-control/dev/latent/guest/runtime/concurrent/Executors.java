package dev.latent.guest.runtime.concurrent;

import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;

/** Host source control only. Component controls use the actual managed SDK pool. */
public final class Executors {
    private static final ArrayList<ExecutorService> pools = new ArrayList<>();
    public static volatile RuntimeException failNextFactory;
    public static synchronized ExecutorService newCachedThreadPool() {
        if (failNextFactory != null) {
            RuntimeException error = failNextFactory;
            failNextFactory = null;
            throw error;
        }
        ExecutorService pool = java.util.concurrent.Executors.newCachedThreadPool();
        pools.add(pool);
        return pool;
    }
    public static synchronized int pools() { return pools.size(); }
    public static synchronized void cleanup() throws Exception {
        for (ExecutorService pool : pools) {
            pool.shutdown();
            if (!pool.awaitTermination(5, TimeUnit.SECONDS))
                throw new AssertionError("source-control-pool-not-reaped");
        }
        pools.clear();
    }
}
