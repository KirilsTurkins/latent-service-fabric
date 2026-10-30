package dev.latent.guest.runtime.concurrent;

import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;

/** Host source control only. Component controls use the actual managed SDK pool. */
public final class Executors {
    private static final ArrayList<ExecutorService> pools = new ArrayList<>();
    public static synchronized ExecutorService newCachedThreadPool() {
        ExecutorService pool = java.util.concurrent.Executors.newCachedThreadPool();
        pools.add(pool);
        return pool;
    }
    static ExecutorService newDefaultAsyncPool() { return newCachedThreadPool(); }
    public static synchronized int pools() { return pools.size(); }
    static boolean isManaged(java.util.concurrent.Executor executor) { return false; }
    public static java.util.concurrent.Executor rejected() {
        return new java.util.concurrent.Executor() {
            @Override public void execute(Runnable command) {
                CompletableFuture.rejectedBeforeAcceptance(command, this);
                throw new java.util.concurrent.RejectedExecutionException("source-control-owned-rejection");
            }
        };
    }
    public static synchronized void cleanup() throws Exception {
        for (ExecutorService pool : pools) {
            pool.shutdown();
            if (!pool.awaitTermination(5, TimeUnit.SECONDS))
                throw new AssertionError("source-control-pool-not-reaped");
        }
        pools.clear();
    }
}
