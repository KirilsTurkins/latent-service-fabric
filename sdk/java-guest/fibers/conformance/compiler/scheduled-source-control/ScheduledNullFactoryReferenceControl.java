import java.util.List;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** The same null-factory calls run against the JDK and actual SDK pool source. */
public final class ScheduledNullFactoryReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("null-factory-reference"); }
    private static void recovery(int core) throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        StringBuffer calls = new StringBuffer();
        var pool = new ScheduledThreadPoolExecutor(core,
            task -> attempts.getAndIncrement() == 0 ? null : new Thread(task));
        try {
            var first = pool.schedule(() -> calls.append('1'), 0, TimeUnit.NANOSECONDS);
            require(!first.isDone() && attempts.get() == 1 && calls.length() == 0);
            var second = pool.schedule(() -> calls.append('2'), 0, TimeUnit.NANOSECONDS);
            first.get(5, TimeUnit.SECONDS);
            second.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.toString().equals("12"));
        } finally {
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    private static void noWorker() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1, task -> null);
        var first = pool.schedule(() -> { throw new AssertionError("cancelled-task-ran"); }, 1, TimeUnit.DAYS);
        require(!first.isDone() && first.cancel(false));
        pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS));

        var other = new ScheduledThreadPoolExecutor(1, task -> null);
        var second = other.schedule(() -> { throw new AssertionError("removed-task-ran"); }, 1, TimeUnit.DAYS);
        List<Runnable> removed = other.shutdownNow();
        require(removed.size() == 1 && removed.get(0) == second && !second.isDone());
        require(second.cancel(false) && other.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void reentrant() throws Exception {
        AtomicReference<ScheduledThreadPoolExecutor> selected = new AtomicReference<>();
        AtomicReference<ScheduledFuture<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                nested.set(selected.get().schedule(calls::incrementAndGet, 0, TimeUnit.NANOSECONDS));
                return null;
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            var outer = pool.schedule(calls::incrementAndGet, 0, TimeUnit.NANOSECONDS);
            require(nested.get() != null && !nested.get().isDone() && !outer.isDone() && attempts.get() == 1);
            var later = pool.schedule(calls::incrementAndGet, 0, TimeUnit.NANOSECONDS);
            nested.get().get(5, TimeUnit.SECONDS);
            outer.get(5, TimeUnit.SECONDS);
            later.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.get() == 3);
        } finally {
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
    }
    private static void throwingFactory() throws Exception {
        var failure = new RejectedExecutionException("factory-failed");
        var pool = new ScheduledThreadPoolExecutor(1, target -> { throw failure; });
        try {
            try { pool.schedule(() -> {}, 0, TimeUnit.NANOSECONDS); throw new AssertionError("factory-did-not-throw"); }
            catch (RejectedExecutionException expected) { require(expected == failure); }
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
    }
    public static void main(String[] args) throws Exception {
        recovery(0); recovery(1); noWorker(); reentrant(); throwingFactory();
        System.out.println("SCHEDULED_NULL_FACTORY PASS accepted;recovery;cancel;shutdown-now;reentrant");
    }
}
