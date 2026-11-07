import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public final class ScheduledStoppedReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("scheduled-stopped-reference"); }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void hold(CountDownLatch entered, CountDownLatch release) {
        entered.countDown();
        while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
    }
    private static void finish(ScheduledThreadPoolExecutor pool) throws InterruptedException {
        pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void delayed() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        var future = pool.schedule(() -> { calls.incrementAndGet(); return 42; }, 1, TimeUnit.DAYS);
        try {
            List<Runnable> returned = pool.shutdownNow();
            require(returned.size() == 1 && returned.get(0) == future && !future.isDone());
            returned.get(0).run();
            require(future.isDone() && future.isCancelled() && calls.get() == 0);
        } finally { finish(pool); }
    }
    private static void periodic(boolean fixedRate) throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        Runnable task = calls::incrementAndGet;
        ScheduledFuture<?> future = fixedRate ? pool.scheduleAtFixedRate(task, 1, 1, TimeUnit.DAYS)
                : pool.scheduleWithFixedDelay(task, 1, 1, TimeUnit.DAYS);
        try {
            List<Runnable> returned = pool.shutdownNow();
            require(returned.size() == 1 && returned.get(0) == future && !future.isDone());
            returned.get(0).run();
            require(future.isDone() && future.isCancelled() && calls.get() == 0);
        } finally { finish(pool); }
    }
    private static void nested() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        try {
            pool.execute(() -> hold(entered, release)); await(entered);
            var result = CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
            List<Runnable> returned = pool.shutdownNow();
            require(returned.size() == 1 && !result.isDone());
            returned.get(0).run();
            require(((Future<?>)returned.get(0)).isCancelled() && !result.isDone() && calls.get() == 0);
        } finally { release.countDown(); finish(pool); }
    }
    private static void nestedFuture() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        var inner = new FutureTask<>(() -> { calls.incrementAndGet(); return 42; });
        var wrapper = pool.schedule(inner, 1, TimeUnit.DAYS);
        try {
            List<Runnable> returned = pool.shutdownNow();
            require(returned.size() == 1 && returned.get(0) == wrapper);
            returned.get(0).run();
            require(wrapper.isCancelled() && !inner.isDone() && calls.get() == 0);
        } finally { finish(pool); }
    }
    private static void runningAndShutdown() throws Exception {
        for (boolean shutdown : new boolean[]{false, true}) {
            var pool = new ScheduledThreadPoolExecutor(1);
            AtomicInteger calls = new AtomicInteger();
            try {
                var future = pool.schedule(() -> { calls.incrementAndGet(); return 42; }, 1, TimeUnit.DAYS);
                if (shutdown) pool.shutdown();
                ((Runnable)future).run();
                require(future.get(5, TimeUnit.SECONDS) == 42 && calls.get() == 1);
            } finally { finish(pool); }
        }
    }
    private static void disabledShutdownPolicies() throws Exception {
        for (boolean periodic : new boolean[]{false, true}) {
            var pool = new ScheduledThreadPoolExecutor(1);
            AtomicInteger calls = new AtomicInteger();
            try {
                pool.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
                Runnable callback = calls::incrementAndGet;
                ScheduledFuture<?> future = periodic ? pool.scheduleAtFixedRate(callback, 1, 1, TimeUnit.DAYS)
                    : pool.schedule(callback, 1, TimeUnit.DAYS);
                pool.shutdown();
                require(future.isCancelled());
                ((Runnable)future).run();
                require(future.isCancelled() && calls.get() == 0);
            } finally { finish(pool); }
        }
    }
    private static void physicalRunner() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger completed = new AtomicInteger();
        var future = pool.schedule(() -> { hold(entered, release); completed.incrementAndGet(); }, 1, TimeUnit.DAYS);
        Thread caller = new Thread((Runnable)future);
        try {
            caller.start(); await(entered);
            List<Runnable> returned = pool.shutdownNow();
            require(returned.size() == 1 && returned.get(0) == future && !future.isDone());
            returned.get(0).run();
            require(future.isCancelled() && completed.get() == 0);
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && completed.get() == 1 && future.isCancelled());
        } finally { release.countDown(); caller.join(5000); finish(pool); }
    }
    public static void main(String[] arguments) throws Exception {
        delayed(); periodic(true); periodic(false); nested(); nestedFuture(); runningAndShutdown();
        disabledShutdownPolicies(); physicalRunner();
        System.out.println("SCHEDULED_STOPPED_REFERENCE PASS delayed;fixed-rate;fixed-delay;nested;future;running;shutdown;shutdown-policy;physical-runner");
    }
}
