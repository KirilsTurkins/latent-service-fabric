import java.lang.reflect.Field;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and real source comparison; reflection controls only the exact test deadlines. */
public final class ScheduledCompareReferenceControl {
    private static void require(boolean yes, String reason) { if (!yes) throw new AssertionError(reason); }
    private static Field field(Class<?> type, String name) throws ReflectiveOperationException {
        Field value = type.getDeclaredField(name); value.setAccessible(true); return value;
    }
    private static void deadline(ScheduledFuture<?> task, ScheduledThreadPoolExecutor pool, long absolute, boolean source)
            throws ReflectiveOperationException {
        if (source) {
            long origin = field(ScheduledThreadPoolExecutor.class, "origin").getLong(pool);
            field(task.getClass(), "next").setLong(task, absolute - origin);
        } else field(task.getClass(), "time").setLong(task, absolute);
    }
    private static void before(ScheduledFuture<?> first, ScheduledFuture<?> second, String reason) {
        require(first.compareTo(second) < 0 && second.compareTo(first) > 0, reason);
    }
    private static void reentrantFactory(boolean source) throws Exception {
        var poolRef = new AtomicReference<ScheduledThreadPoolExecutor>();
        var nested = new AtomicReference<ScheduledFuture<?>>();
        var once = new AtomicBoolean();
        var pool = new ScheduledThreadPoolExecutor(1, work -> {
            if (once.compareAndSet(false, true))
                nested.set(poolRef.get().schedule(() -> {}, 1, TimeUnit.HOURS));
            return new Thread(work);
        });
        poolRef.set(pool);
        try {
            synchronized (pool) {
                var outer = pool.schedule(() -> {}, 1, TimeUnit.HOURS);
                require(nested.get() != null, "factory-reentry-submitted");
                long target = System.nanoTime() + TimeUnit.HOURS.toNanos(1);
                deadline(outer, pool, target, source); deadline(nested.get(), pool, target, source);
                before(outer, nested.get(), "factory-reentry-fifo");
                require(outer.cancel(false) && nested.get().cancel(false), "factory-reentry-cancel");
            }
        } finally {
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "factory-reentry-retire");
        }
    }
    public static void main(String[] args) throws Exception {
        boolean source = args.length == 1 && args[0].equals("source");
        if (args.length != 1 || !(source || args[0].equals("jdk"))) throw new AssertionError("scope");
        var left = new ScheduledThreadPoolExecutor(1);
        var right = new ScheduledThreadPoolExecutor(1);
        ScheduledFuture<?>[] saved = new ScheduledFuture<?>[3];
        try {
            synchronized (left) { synchronized (right) {
                var a = left.schedule(() -> {}, 1, TimeUnit.HOURS);
                var b = right.schedule(() -> {}, 1, TimeUnit.HOURS);
                var samePool = left.schedule(() -> {}, 1, TimeUnit.HOURS);
                long target = System.nanoTime() + TimeUnit.HOURS.toNanos(1);
                deadline(a, left, target, source);
                deadline(b, right, target + 1, source);
                deadline(samePool, left, target, source);
                before(a, b, "cross-pool-close-deadlines");
                before(a, samePool, "same-pool-fifo-tie");
                deadline(b, right, target, source);
                before(a, b, "cross-pool-tie");
                before(b, samePool, "global-submission-tie");
                saved[0] = a; saved[1] = b; saved[2] = samePool;
                var maximum = right.schedule(() -> {}, Long.MAX_VALUE, TimeUnit.NANOSECONDS);
                before(a, maximum, "near-before-maximum");
                require(a.cancel(false) && b.cancel(false) && samePool.cancel(false) && maximum.cancel(false), "cancel");
            } }
        } finally {
            left.shutdownNow(); right.shutdownNow();
            require(left.awaitTermination(5, TimeUnit.SECONDS) && right.awaitTermination(5, TimeUnit.SECONDS), "retire");
        }
        // The Executor lease has settled; retained futures still have stable keys.
        before(saved[0], saved[1], "retired-cross-pool-tie");
        before(saved[1], saved[2], "retired-global-order");
        reentrantFactory(source);
        System.out.println("SCHEDULED_COMPARE_REFERENCE PASS close;fifo;maximum;transitive;retired;global-submission-order;reentrant-factory");
    }
}
