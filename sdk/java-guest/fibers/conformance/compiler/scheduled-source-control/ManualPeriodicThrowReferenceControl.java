import java.util.Collection;
import java.util.List;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and SDK scheduled source observations, not guest execution. */
public final class ManualPeriodicThrowReferenceControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("manual-periodic-factory"); }
    private static int queued(ScheduledThreadPoolExecutor pool) throws Exception {
        try {
            return ((Collection<?>)pool.getClass().getMethod("getQueue").invoke(pool)).size();
        } catch (NoSuchMethodException absent) {
            var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true);
            return ((Collection<?>)field.get(pool)).size();
        }
    }
    private static void remove(ScheduledThreadPoolExecutor pool, ScheduledFuture<?> future) throws Exception {
        List<Runnable> removed = pool.shutdownNow();
        // JDK 25 can return fewer duplicate references than it held internally.
        require(!removed.isEmpty());
        for (Runnable task : removed) require(task == future && task instanceof Future<?>);
        require(!future.isDone() && future.cancel(false) && pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void periodic(boolean fixedRate, boolean asError) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        Throwable failure = asError ? new AssertionError("factory-error") : new IllegalStateException("factory-failed");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) {
                if (failure instanceof Error error) throw error;
                throw (RuntimeException)failure;
            }
            return new Thread(target);
        });
        var future = fixedRate ? pool.scheduleAtFixedRate(calls::incrementAndGet, 3, 1, TimeUnit.DAYS)
            : pool.scheduleWithFixedDelay(calls::incrementAndGet, 3, 1, TimeUnit.DAYS);
        long before = future.getDelay(TimeUnit.HOURS);
        try { ((Runnable)future).run(); throw new AssertionError("factory-did-not-throw"); }
        catch (Throwable observed) { require(observed == failure); }
        long after = future.getDelay(TimeUnit.HOURS);
        require(attempts.get() == 2 && calls.get() == 1 && !future.isDone() && queued(pool) == 2);
        require(fixedRate ? after - before >= 23 && after - before <= 25
            : before - after >= 46 && before - after <= 49);
        remove(pool, future);
    }
    private static void reentrant() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<ScheduledFuture<?>> selected = new AtomicReference<>();
        var failure = new IllegalStateException("nested-factory-failure");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) { ((Runnable)selected.get()).run(); throw failure; }
            return new Thread(target);
        });
        var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
        selected.set(future);
        long before = future.getDelay(TimeUnit.HOURS);
        try { ((Runnable)future).run(); throw new AssertionError("factory-did-not-throw"); }
        catch (IllegalStateException observed) { require(observed == failure); }
        require(attempts.get() == 2 && calls.get() == 2 && !future.isDone() && queued(pool) == 3
            && future.getDelay(TimeUnit.HOURS) >= before + 47);
        remove(pool, future);
    }
    public static void main(String[] args) throws Exception {
        periodic(true, false); periodic(false, false); periodic(true, true); periodic(false, true); reentrant();
        System.out.println("MANUAL_PERIODIC_THROW PASS fixed-rate;fixed-delay;error;copies;reentrant");
    }
}
