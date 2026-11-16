import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledCompareFakeClock;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ThreadFactory;
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
                before(samePool, sameB, "three-task-tie-transitivity");
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
        Activation.controlNextOwnerIdentity(generation ? Long.MAX_VALUE : 1, generation ? 1 : Long.MAX_VALUE);
        var a = pool();
        if (generation) Activation.controlNextOwnerIdentity(Long.MIN_VALUE, 1);
        var b = pool();
        try {
            synchronized (a) { synchronized (b) {
                ScheduledCompareFakeClock.now = 200;
                var first = task(a, 1_000); var second = task(b, 1_000);
                ScheduledCompareFakeClock.step = 10;
                before(first, second, generation ? "unsigned-generation" : "unsigned-id");
                ScheduledCompareFakeClock.step = 0;
                require(first.cancel(false) && second.cancel(false), "unsigned-cancel");
            } }
        } finally { close(a,b); }
    }
    private static void rejectedKey(boolean uncertain) {
        var failure = new IllegalStateException("synthetic-owner-order-failure");
        Activation.orderFailure = failure;
        if (uncertain) Activation.denyCloseNext = "Executor";
        try { pool(); throw new AssertionError("owner-order-failure-accepted"); }
        catch (IllegalStateException expected) { require(expected == failure, "owner-order-original-error"); }
        finally { Activation.orderFailure = null; }
        if (uncertain) {
            require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1,
                "uncertain-settlement-retains-original-owner");
            owners(1, 0, 0);
        } else { require(!Activation.poisoned, "rollback-poisoned"); owners(0, 0, 0); }
    }
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("uncertain")) {
            rejectedKey(true);
            System.out.println("SCHEDULED_COMPARE_KEY_UNCERTAIN PASS original-owner-held;single-attempt");
            return;
        }
        require(args.length == 0, "arguments");
        deadlines(); wrap(); unsigned(false); unsigned(true); rejectedKey(false); Activation.idle();
        System.out.println("SCHEDULED_COMPARE_CLOCK PASS close;tie-transitive;fifo;maximum;overdue;wrap;retired;unsigned;owners;rollback");
    }
}
