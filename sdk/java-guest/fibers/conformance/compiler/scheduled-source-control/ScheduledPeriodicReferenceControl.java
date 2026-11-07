import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Identical public behavior on the reference JDK and the selected SDK bodies. */
public final class ScheduledPeriodicReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("scheduled-periodic-reference"); }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static void hold(CountDownLatch entered, CountDownLatch release) {
        entered.countDown();
        while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
    }
    private static void finish(ScheduledThreadPoolExecutor pool) throws InterruptedException {
        pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void returned(List<Runnable> entries, ScheduledFuture<?> future) {
        // The JDK delayed queue can retain duplicate references after drain;
        // the SDK retires every charged queue occurrence instead.
        require(!entries.isEmpty());
        for (Runnable entry : entries) require(entry == future);
    }
    private static void manual(boolean fixedRate) throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        Runnable callback = calls::incrementAndGet;
        ScheduledFuture<?> future = fixedRate ? pool.scheduleAtFixedRate(callback, 1, 1, TimeUnit.DAYS)
            : pool.scheduleWithFixedDelay(callback, 1, 1, TimeUnit.DAYS);
        try {
            ((Runnable)future).run(); ((Runnable)future).run();
            require(calls.get() == 2 && !future.isDone());
            List<Runnable> entries = pool.shutdownNow(); returned(entries, future);
            entries.get(0).run(); require(future.isCancelled() && calls.get() == 2);
        } finally { finish(pool); }
    }
    private static void reentrant() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<ScheduledFuture<?>> reference = new AtomicReference<>();
        try {
            var future = pool.scheduleAtFixedRate(() -> {
                calls.incrementAndGet(); ((Runnable)reference.get()).run();
            }, 1, 1, TimeUnit.DAYS);
            reference.set(future); ((Runnable)future).run();
            require(calls.get() == 1 && !future.isDone());
            returned(pool.shutdownNow(), future);
        } finally { finish(pool); }
    }
    private static void failure() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        var original = new IllegalArgumentException("periodic-callback");
        try {
            var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); throw original; }, 1, 1, TimeUnit.DAYS);
            ((Runnable)future).run(); require(calls.get() == 1 && future.isDone());
            try { future.get(); throw new AssertionError("expected-failure"); }
            catch (ExecutionException expected) { require(expected.getCause() == original); }
            // The JDK can retain a completed occurrence in its delayed queue;
            // the SDK may retire that inert occurrence immediately.
            pool.shutdownNow();
        } finally { finish(pool); }
    }
    private static void cancelledInside() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<ScheduledFuture<?>> reference = new AtomicReference<>();
        try {
            var future = pool.scheduleAtFixedRate(() -> {
                calls.incrementAndGet(); require(reference.get().cancel(false));
            }, 1, 1, TimeUnit.DAYS);
            reference.set(future); ((Runnable)future).run();
            require(calls.get() == 1 && future.isCancelled());
        } finally { finish(pool); }
    }
    private static void concurrentManual() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 1, 1, TimeUnit.DAYS);
        Thread first = new Thread((Runnable)future);
        try {
            first.start(); await(entered); ((Runnable)future).run();
            require(calls.get() == 1 && !future.isDone());
            release.countDown(); first.join(5000); require(!first.isAlive());
            returned(pool.shutdownNow(), future);
        } finally { release.countDown(); first.join(5000); finish(pool); }
    }
    private static void concurrentWorker() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 0, 1, TimeUnit.DAYS);
        try {
            await(entered); ((Runnable)future).run(); require(calls.get() == 1 && !future.isDone());
            var marker = pool.submit(() -> { });
            release.countDown(); marker.get(5, TimeUnit.SECONDS);
            returned(pool.shutdownNow(), future);
        } finally { release.countDown(); finish(pool); }
    }
    private static void shutdownDuring() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var future = pool.scheduleAtFixedRate(() -> { calls.incrementAndGet(); hold(entered, release); }, 1, 1, TimeUnit.DAYS);
        Thread caller = new Thread((Runnable)future);
        try {
            caller.start(); await(entered); returned(pool.shutdownNow(), future);
            require(!future.isDone()); release.countDown(); caller.join(5000);
            require(!caller.isAlive() && calls.get() == 1 && future.isCancelled());
        } finally { release.countDown(); caller.join(5000); finish(pool); }
    }
    private static void continueAfterShutdown() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        try {
            pool.setContinueExistingPeriodicTasksAfterShutdownPolicy(true);
            var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
            pool.shutdown(); ((Runnable)future).run();
            require(calls.get() == 1 && !future.isDone());
            returned(pool.shutdownNow(), future);
        } finally { finish(pool); }
    }
    public static void main(String[] args) throws Exception {
        manual(true); manual(false); reentrant(); failure(); cancelledInside(); concurrentManual();
        concurrentWorker(); shutdownDuring(); continueAfterShutdown();
        System.out.println("SCHEDULED_PERIODIC_REFERENCE PASS fixed-rate;fixed-delay;reentrant;failure;self-cancel;concurrent-manual;concurrent-worker;shutdown;continue-policy");
    }
}
