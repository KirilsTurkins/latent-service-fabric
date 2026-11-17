import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Same ordinary API calls against the JDK and the selected SDK source. */
public final class ScheduledPeriodicValidationReferenceControl {
    private static void expect(Class<? extends RuntimeException> type, Runnable call) {
        try { call.run(); throw new AssertionError("periodic-invalid-arguments-accepted"); }
        catch (RuntimeException error) {
            if (error.getClass() != type) throw new AssertionError("periodic-validation-order", error);
        }
    }
    private static void schedule(ScheduledExecutorService pool, boolean rate, Runnable task, long interval, TimeUnit unit) {
        if (rate) pool.scheduleAtFixedRate(task, 0, interval, unit);
        else pool.scheduleWithFixedDelay(task, 0, interval, unit);
    }
    public static void check(ScheduledExecutorService pool) {
        Runnable task = () -> { throw new AssertionError("invalid-periodic-task-ran"); };
        for (boolean rate : new boolean[]{false, true}) {
            for (long invalid : new long[]{0, -1}) {
                expect(NullPointerException.class, () -> schedule(pool, rate, null, invalid, TimeUnit.NANOSECONDS));
                expect(NullPointerException.class, () -> schedule(pool, rate, task, invalid, null));
                expect(NullPointerException.class, () -> schedule(pool, rate, null, invalid, null));
                expect(IllegalArgumentException.class, () -> schedule(pool, rate, task, invalid, TimeUnit.NANOSECONDS));
            }
            expect(NullPointerException.class, () -> schedule(pool, rate, null, 1, TimeUnit.NANOSECONDS));
            expect(NullPointerException.class, () -> schedule(pool, rate, task, 1, null));
        }
    }
    public static void main(String[] args) {
        ScheduledThreadPoolExecutor pool = new ScheduledThreadPoolExecutor(1);
        try { check(pool); pool.shutdown(); check(pool); }
        finally { pool.shutdownNow(); }
        System.out.println("SCHEDULED_PERIODIC_VALIDATION PASS null-task;null-unit;nonpositive;open;shutdown");
    }
}
