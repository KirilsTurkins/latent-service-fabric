package dev.latent.app;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import org.apache.commons.lang3.concurrent.TimedSemaphore;

/** Ordinary unchanged published default factory: no executor or timer injection. */
public final class Capsule {
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("published-scheduled-observable");
    }
    public Long run(Long mode) {
        if (mode == 6) return defaultCompletion();
        if (mode == 7) return standardRejection();
        if (mode == 5) {
            boolean original = false;
            try { new TimedSemaphore(0, TimeUnit.MILLISECONDS, 1); }
            catch (IllegalArgumentException expected) { original = true; }
            require(original);
            return 42L;
        }
        TimedSemaphore semaphore = new TimedSemaphore(1, TimeUnit.MILLISECONDS, mode == 1 ? 2 : 1);
        try {
            synchronized (semaphore) {
                require(semaphore.getPeriod() == 1 && semaphore.getUnit() == TimeUnit.MILLISECONDS);
                if (mode == 0) {
                    semaphore.acquire(); semaphore.acquire();
                    require(semaphore.getAcquireCount() == 1);
                } else if (mode == 1) {
                    semaphore.acquire(); semaphore.acquire(); semaphore.acquire();
                    require(semaphore.getAcquireCount() == 1);
                } else if (mode == 2) {
                    require(semaphore.tryAcquire());
                    semaphore.acquire();
                    require(semaphore.getAcquireCount() == 1);
                } else if (mode == 3) {
                    semaphore.setLimit(0);
                    for (int i = 0; i < 4; ++i) semaphore.acquire();
                    require(semaphore.getAcquireCount() == 4);
                } else if (mode == 4) {
                    semaphore.acquire(); semaphore.shutdown(); semaphore.shutdown();
                    require(semaphore.isShutdown());
                    boolean original = false;
                    try { semaphore.tryAcquire(); }
                    catch (IllegalStateException expected) { original = true; }
                    require(original);
                } else throw new IllegalArgumentException("published-scheduled-mode");
                return 42L;
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } finally { semaphore.shutdown(); }
    }
    private static Long defaultCompletion() {
        Thread root = Thread.currentThread();
        Object gate = new Object();
        boolean[] entered = {false}, released = {false};
        local.set("root");
        CompletableFuture<Integer> pending = CompletableFuture.supplyAsync(() -> {
            require(Thread.currentThread() != root && local.get() == null);
            local.set("default-callback");
            synchronized (gate) {
                entered[0] = true; gate.notifyAll();
                try { while (!released[0]) gate.wait(); }
                catch (InterruptedException error) { throw new IllegalStateException(error); }
            }
            return 20;
        });
        try {
            synchronized (gate) {
                while (!entered[0]) gate.wait();
                require(!pending.isDone());
                released[0] = true; gate.notifyAll();
            }
            require(pending.thenApplyAsync(value -> value + 22).get() == 42);
            require("root".equals(local.get()));
            IllegalArgumentException original = new IllegalArgumentException("default-callback-original-error");
            CompletableFuture<Integer> failed = CompletableFuture.supplyAsync(() -> { throw original; });
            try { failed.get(); throw new IllegalStateException("missing-future-error"); }
            catch (ExecutionException expected) { require(expected.getCause() == original); }
            return 42L;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } catch (ExecutionException error) {
            throw new IllegalStateException(error);
        }
    }
    private static Long standardRejection() {
        Thread root = Thread.currentThread();
        var executor = Executors.newSingleThreadExecutor();
        try {
            require(executor.submit(() -> Thread.currentThread() != root ? 42 : -1).get() == 42);
            executor.shutdown();
            boolean original = false;
            try { executor.submit(() -> { throw new IllegalStateException("rejected-callback-ran"); }); }
            catch (RejectedExecutionException expected) { original = true; }
            require(original && executor.isShutdown());
            require(executor.awaitTermination(1, TimeUnit.SECONDS) && executor.isTerminated());
            return 42L;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } catch (ExecutionException error) {
            throw new IllegalStateException(error);
        } finally { executor.shutdownNow(); }
    }
}
