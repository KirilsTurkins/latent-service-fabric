import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledCompareFakeClock;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.TimeUnit;

public final class ScheduledCompareClockControl {
    private static void require(boolean value, String tag) { if (!value) throw new AssertionError(tag); }
    private static void owners(int executors, int queue, int results) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executors, "executor-owner");
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue, "queue-owner");
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == results, "result-owner");
    }
    private static ScheduledThreadPoolExecutor pool() {
        ThreadFactory daemon = work -> { Thread thread = new Thread(work); thread.setDaemon(true); return thread; };
        return new ScheduledThreadPoolExecutor(1, daemon);
    }
    private static ScheduledFuture<?> task(ScheduledThreadPoolExecutor pool, long delay) {
        return pool.schedule(() -> { throw new AssertionError("unexpected-dispatch"); }, delay, TimeUnit.NANOSECONDS);
    }
    private static void before(ScheduledFuture<?> first, ScheduledFuture<?> second, String reason) {
        require(first.compareTo(second) < 0 && second.compareTo(first) > 0, reason);
    }
    private static void close(ScheduledThreadPoolExecutor a, ScheduledThreadPoolExecutor b) throws Exception {
        ScheduledCompareFakeClock.step = 0;
        a.shutdownNow(); b.shutdownNow();
        require(a.awaitTermination(5, TimeUnit.SECONDS) && b.awaitTermination(5, TimeUnit.SECONDS), "worker-retirement");
        owners(0, 0, 0);
    }
    private static void deadlines() throws Exception {
        ScheduledCompareFakeClock.step = 0;
        ScheduledCompareFakeClock.now = 0; var a = pool();
        ScheduledCompareFakeClock.now = 100; var b = pool();
        ScheduledFuture<?>[] saved = new ScheduledFuture<?>[2];
        try {
            synchronized (a) { synchronized (b) {
                ScheduledCompareFakeClock.now = 200;
                var earlier = task(a, 1_000); var later = task(b, 1_001);
                var sameA = task(a, 1_500); var sameB = task(b, 1_500); var samePool = task(a, 1_500);
                var maximumA = task(a, Long.MAX_VALUE); var maximumB = task(b, Long.MAX_VALUE);
                owners(2, 7, 7);
                ScheduledCompareFakeClock.step = 10;
                before(earlier, later, "cross-pool-near-deadlines");
                before(sameA, samePool, "same-pool-fifo");
                before(sameA, sameB, "cross-pool-equal-deadline");
                before(sameB, samePool, "three-task-tie-transitivity");
                saved[0] = sameA; saved[1] = sameB;
                before(maximumA, maximumB, "saturated-max-deadlines");
                before(earlier, maximumB, "near-versus-max-deadline");
                ScheduledCompareFakeClock.step = 0; ScheduledCompareFakeClock.now = 2_000;
                before(earlier, later, "overdue-deadlines");
                owners(2, 7, 7);
                for (var value : new ScheduledFuture<?>[]{earlier,later,sameA,sameB,samePool,maximumA,maximumB})
                    require(value.cancel(false), "future-cancel");
                owners(2, 0, 0);
            } }
        } finally { close(a,b); }
        ScheduledCompareFakeClock.step = 10;
        before(saved[0], saved[1], "retired-cross-pool-identity");
        ScheduledCompareFakeClock.step = 0;
    }
    private static void wrap() throws Exception {
        ScheduledCompareFakeClock.step = 0;
        ScheduledCompareFakeClock.now = Long.MAX_VALUE - 50; var a = pool();
        ScheduledCompareFakeClock.now = Long.MAX_VALUE - 40; var b = pool();
        try {
            synchronized (a) { synchronized (b) {
                ScheduledCompareFakeClock.now = Long.MAX_VALUE - 30;
                var earlier = task(a, 100); var later = task(b, 101);
                owners(2, 2, 2);
                ScheduledCompareFakeClock.now = Long.MIN_VALUE + 5;
                ScheduledCompareFakeClock.step = 10;
                before(earlier, later, "monotonic-clock-wrap");
                owners(2, 2, 2);
                ScheduledCompareFakeClock.step = 0;
                require(earlier.cancel(false) && later.cancel(false), "wrap-cancel");
                owners(2, 0, 0);
            } }
        } finally { close(a,b); }
    }
    private static void unsigned(boolean generation) throws Exception {
        ScheduledCompareFakeClock.step = 0; ScheduledCompareFakeClock.now = 0;
        var a = pool(); var b = pool();
        try {
            synchronized (a) { synchronized (b) {
                ScheduledCompareFakeClock.now = 200;
                Activation.controlNextOwnerIdentity(generation ? Long.MAX_VALUE : 1, generation ? 1 : Long.MAX_VALUE);
                var first = task(a, 1_000);
                if (generation) Activation.controlNextOwnerIdentity(Long.MIN_VALUE, 1);
                var second = task(b, 1_000);
                ScheduledCompareFakeClock.step = 10;
                before(first, second, generation ? "unsigned-generation" : "unsigned-id");
                ScheduledCompareFakeClock.step = 0;
                require(first.cancel(false) && second.cancel(false), "unsigned-cancel");
            } }
        } finally { close(a,b); }
    }
    private static void periodic() throws Exception {
        ScheduledCompareFakeClock.step = 0; ScheduledCompareFakeClock.now = 0;
        var a = pool(); var b = pool(); var calls = new AtomicInteger();
        try {
            synchronized (a) { synchronized (b) {
                ScheduledCompareFakeClock.now = 200;
                var recurring = a.scheduleAtFixedRate(calls::incrementAndGet, 1_000, 1_000, TimeUnit.NANOSECONDS);
                var later = task(b, 2_000);
                owners(2, 2, 2);
                ((Runnable)recurring).run();
                require(calls.get() == 1 && !recurring.isDone(), "periodic-manual-run");
                owners(2, 3, 2);
                // A fresh queued copy was admitted after later, but the
                // original periodic task must keep its initial order.
                before(recurring, later, "periodic-original-order");
                require(recurring.cancel(false) && later.cancel(false), "periodic-cancel");
                owners(2, 0, 0);
            } }
        } finally { close(a,b); }
    }
    private static void reentrant() throws Exception {
        ScheduledCompareFakeClock.step = 0; ScheduledCompareFakeClock.now = 0;
        var a = pool(); var b = pool(); var nested = new AtomicReference<ScheduledFuture<?>>();
        try {
            synchronized (a) { synchronized (b) {
                ScheduledCompareFakeClock.now = 200;
                Activation.admissionObservationKind = "QueuedWork";
                Activation.admissionObservation = () -> nested.set(task(b, 1_000));
                var outer = task(a, 1_000); var last = task(a, 1_000);
                require(nested.get() != null, "reentrant-submission");
                before(outer, nested.get(), "reentrant-original-admission-order");
                before(nested.get(), last, "reentrant-global-order");
                before(outer, last, "reentrant-transitivity");
                owners(2, 3, 3);
                require(outer.cancel(false) && nested.get().cancel(false) && last.cancel(false), "reentrant-cancel");
                owners(2, 0, 0);
            } }
        } finally {
            Activation.admissionObservation = null; Activation.admissionObservationKind = null;
            close(a,b);
        }
    }
    private static void reentrantSamePool() throws Exception {
        ScheduledCompareFakeClock.step = 0; ScheduledCompareFakeClock.now = 0;
        var executor = pool(); var nested = new AtomicReference<ScheduledFuture<?>>();
        try {
            synchronized (executor) {
                ScheduledCompareFakeClock.now = 200;
                Activation.admissionObservationKind = "QueuedWork";
                Activation.admissionObservation = () -> nested.set(task(executor, 1_000));
                var outer = task(executor, 1_000);
                require(nested.get() != null, "same-pool-reentrant-submission");
                before(outer, nested.get(), "same-pool-reentrant-admission-order");
                var queueField = ScheduledThreadPoolExecutor.class.getDeclaredField("queue");
                queueField.setAccessible(true);
                var entries = (java.util.List<?>)queueField.get(executor);
                var first = ScheduledThreadPoolExecutor.class.getDeclaredMethod("first"); first.setAccessible(true);
                Object selected = entries.get((int)first.invoke(executor));
                var taskField = selected.getClass().getDeclaredField("task"); taskField.setAccessible(true);
                require(taskField.get(selected) == outer, "same-pool-queue-and-comparator-agree");
                owners(1, 2, 2);
                require(outer.cancel(false) && nested.get().cancel(false), "same-pool-reentrant-cancel");
                owners(1, 0, 0);
            }
        } finally {
            Activation.admissionObservation = null; Activation.admissionObservationKind = null;
            executor.shutdownNow();
            require(executor.awaitTermination(5, TimeUnit.SECONDS), "same-pool-reentrant-retire");
            owners(0, 0, 0);
        }
    }
    private static void reentrantOverflow(boolean uncertain) throws Exception {
        ScheduledCompareFakeClock.step = 0; ScheduledCompareFakeClock.now = 0;
        var executor = pool(); var nested = new AtomicReference<ScheduledFuture<?>>();
        try {
            synchronized (executor) {
                var sequence = ScheduledThreadPoolExecutor.class.getDeclaredField("sequence");
                sequence.setAccessible(true); sequence.setLong(executor, Long.MAX_VALUE - 1);
                Activation.admissionObservationKind = "QueuedWork";
                Activation.admissionObservation = () -> {
                    nested.set(task(executor, 1_000));
                    if (uncertain) Activation.denyCloseNext = "QueuedWork";
                };
                try { task(executor, 1_000); throw new AssertionError("reentrant-overflow-accepted"); }
                catch (java.util.concurrent.RejectedExecutionException expected) {
                    require("scheduled-sequence-overflow".equals(expected.getMessage()), "reentrant-overflow-error");
                }
                require(nested.get() != null && sequence.getLong(executor) == Long.MAX_VALUE, "reentrant-overflow-bound");
                if (uncertain) {
                    require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1,
                        "overflow-uncertain-original-owner");
                    owners(1, 2, 1);
                } else {
                    require(!Activation.poisoned, "overflow-poisoned"); owners(1, 1, 1);
                    require(nested.get().cancel(false), "overflow-nested-cancel"); owners(1, 0, 0);
                }
            }
        } finally {
            Activation.admissionObservation = null; Activation.admissionObservationKind = null;
            if (!uncertain) {
                executor.shutdownNow();
                require(executor.awaitTermination(5, TimeUnit.SECONDS), "overflow-worker-retirement");
                owners(0, 0, 0);
            }
        }
    }
    private static void rejectedKey(boolean uncertain) throws Exception {
        var executor = pool();
        var failure = new IllegalStateException("synthetic-owner-order-failure");
        Activation.orderFailure = failure;
        if (uncertain) Activation.denyCloseNext = "QueuedWork";
        try { task(executor, 1_000); throw new AssertionError("owner-order-failure-accepted"); }
        catch (IllegalStateException expected) { require(expected == failure, "owner-order-original-error"); }
        finally { Activation.orderFailure = null; }
        if (uncertain) {
            require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1,
                "uncertain-settlement-retains-original-owner");
            owners(1, 1, 0);
        } else {
            require(!Activation.poisoned, "rollback-poisoned"); owners(1, 0, 0);
            executor.shutdownNow();
            require(executor.awaitTermination(5, TimeUnit.SECONDS), "rollback-worker-retirement");
            owners(0, 0, 0);
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("uncertain")) {
            rejectedKey(true);
            System.out.println("SCHEDULED_COMPARE_KEY_UNCERTAIN PASS original-owner-held;single-attempt");
            return;
        }
        if (args.length == 1 && args[0].equals("overflow-uncertain")) {
            reentrantOverflow(true);
            System.out.println("SCHEDULED_COMPARE_OVERFLOW_UNCERTAIN PASS original-owner-held;single-attempt");
            return;
        }
        require(args.length == 0, "arguments");
        deadlines(); wrap(); unsigned(false); unsigned(true); periodic(); reentrant(); reentrantSamePool(); reentrantOverflow(false);
        rejectedKey(false); Activation.idle();
        System.out.println("SCHEDULED_COMPARE_CLOCK PASS close;tie-transitive;fifo;maximum;overdue;wrap;retired;unsigned;periodic;reentrant;same-pool-reentrant;overflow;owners;rollback");
    }
}
