import java.lang.reflect.Field;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

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
                if (source) before(samePool, b, "source-pool-tie-transitive");
                else before(b, samePool, "jdk-global-submission-tie");
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
        if (source) before(saved[2], saved[1], "retired-source-pool-order");
        else before(saved[1], saved[2], "retired-jdk-global-order");
        System.out.println("SCHEDULED_COMPARE_REFERENCE PASS close;fifo;maximum;transitive;retired;tie-" + (source ? "source-pool-order" : "jdk-global-order"));
    }
}
